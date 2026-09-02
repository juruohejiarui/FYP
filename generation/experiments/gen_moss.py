import argparse
from collections import deque
import json
import os
import sys
from pathlib import Path

import torch
from tqdm import tqdm

from ref.utils import RefEntry, get_entries, select_patient_doctor_refs
from utils.moss import (
    build_conversation,
    build_dialogue_turns,
    build_turn_chunks,
    generate_chunk_wavs,
    load_model_and_processor,
)
from utils.script import parse
from utils.wav_chk import get_wav_duration_seconds, is_wav_too_long, remove_wav_if_exists

OUTPUT_DIR = Path(__file__).parent / "data" / "audio" / "moss"
PROJECT_ROOT = Path(__file__).parents[2]
MODEL_CODE_PATH = PROJECT_ROOT / "generation" / "models" / "moss-ttsd"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "pretrained" / "TTS" / "MOSS-TTSD-v1.0"
DEFAULT_CODEC_PATH = PROJECT_ROOT / "models" / "pretrained" / "TTS" / "MOSS-Audio-Tokenizer"

sys.path.append(str(MODEL_CODE_PATH))
from generation_utils import resolve_sampling_args  # noqa: E402

os.makedirs(str(OUTPUT_DIR), exist_ok=True)


def load_existing_manifests(manifest_jsonl_path: Path) -> dict[str, dict]:
    manifests: dict[str, dict] = {}
    legacy_manifest_path = manifest_jsonl_path.with_suffix(".json")

    if legacy_manifest_path.exists():
        with open(legacy_manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, dict) and "script_id" in value:
                    manifests[str(value["script_id"])] = value
        elif isinstance(data, list):
            for value in data:
                if isinstance(value, dict) and "script_id" in value:
                    manifests[str(value["script_id"])] = value

    if manifest_jsonl_path.exists():
        with open(manifest_jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                manifests[str(entry["script_id"])] = entry

    return manifests


def _save_wav(wav: torch.Tensor, output_path: Path, target_sr: int) -> None:
    import soundfile as sf
    sf.write(str(output_path), wav.numpy(), target_sr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate WAVs from scripts.jsonl using MOSS-TTSD.")

    parser.add_argument("scripts", type=Path)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--codec-model-path", type=Path, default=DEFAULT_CODEC_PATH)
    parser.add_argument("--max-new-tokens", type=int, default=3072)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--repetition-penalty", type=float, default=1.4)
    parser.add_argument("--max-wav-seconds", type=float, default=180.0)
    parser.add_argument("--max-regen-attempts", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument(
        "--mx-char-per-chunk", type=int, default=-1,
        help="Maximum number of characters per generated audio chunk. Use -1 to disable chunking.",
    )
    parser.add_argument("--sel-ids", type=lambda s: list(map(int, s.split(','))), default=None)
    args = parser.parse_args()

    # resolve_sampling_args expects args.model_path to read the model's own generation_config.json defaults
    args.model_path = str(args.model_path)
    resolve_sampling_args(args)
    args.model_path = Path(args.model_path)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    ref_ents = get_entries()

    scripts: list[dict[str, dict | list]] = parse(args.scripts)

    model, processor = load_model_and_processor(args.model_path, args.codec_model_path, device)
    target_sr = int(processor.model_config.sampling_rate)

    manifest_path = OUTPUT_DIR / "manifest.jsonl"
    manifests = load_existing_manifests(manifest_path)

    try:
        selected_scripts = [
            script
            for script in scripts
            if args.sel_ids is None or script['dialogue_id'] in args.sel_ids
        ]

        pending_scripts = deque(selected_scripts)
        active_script_ids: deque[str] = deque()
        task_queue: deque[dict] = deque()
        script_states: dict[str, dict] = {}

        def activate_script(script: dict[str, dict | list]) -> str:
            script_id = str(script['dialogue_id'])
            patient_ref, doctor_ref = select_patient_doctor_refs(ref_ents, script.get('meta'))

            if script['dialogue'] and script['dialogue'][0]['speaker'] == '医生':
                patient_ref, doctor_ref = doctor_ref, patient_ref

            refs = [patient_ref, doctor_ref]
            turns = build_dialogue_turns(script['dialogue'])
            chunks = build_turn_chunks(turns, args.mx_char_per_chunk)
            if not chunks:
                raise RuntimeError(f"script {script_id} has no valid dialogue turns")

            script_states[script_id] = {
                'script': script,
                'script_id': script_id,
                'refs': refs,
                'chunks': chunks,
                'attempt': 1,
                'next_chunk_idx': 0,
                'wav_chunks': {},
                'done': False,
            }
            return script_id

        def enqueue_until_full() -> None:
            while len(active_script_ids) < args.batch_size and pending_scripts:
                script = pending_scripts.popleft()
                script_id = activate_script(script)
                active_script_ids.append(script_id)

            while len(task_queue) < args.batch_size:
                if not active_script_ids:
                    break

                progressed = False
                active_count = len(active_script_ids)

                for _ in range(active_count):
                    script_id = active_script_ids.popleft()
                    state = script_states[script_id]

                    if state['done']:
                        continue

                    chunk_idx = state['next_chunk_idx']
                    if chunk_idx < len(state['chunks']):
                        task_queue.append(
                            {
                                'script_id': script_id,
                                'attempt': state['attempt'],
                                'chunk_idx': chunk_idx,
                                'conversation': build_conversation(
                                    processor,
                                    state['refs'],
                                    state['chunks'][chunk_idx],
                                    target_sr,
                                ),
                            }
                        )
                        state['next_chunk_idx'] = chunk_idx + 1
                        progressed = True

                    active_script_ids.append(script_id)
                    if len(task_queue) >= args.batch_size:
                        break

                while len(active_script_ids) < args.batch_size and pending_scripts:
                    script = pending_scripts.popleft()
                    script_id = activate_script(script)
                    active_script_ids.append(script_id)

                if not progressed:
                    break

        total_scripts = len(selected_scripts)
        done_scripts = 0
        pbar = tqdm(total=total_scripts, desc="Scripts", unit="script")

        while pending_scripts or active_script_ids or task_queue:
            enqueue_until_full()
            if not task_queue:
                break

            batch_size = min(args.batch_size, len(task_queue))
            batch_tasks = [task_queue.popleft() for _ in range(batch_size)]
            conversations = [task['conversation'] for task in batch_tasks]

            tqdm.write(f"[BATCH] "
                    f"tasks={len(batch_tasks)} queue={len(task_queue)} "
                    f"active={len(active_script_ids)} pending={len(pending_scripts)} done={done_scripts}/{total_scripts}"
            )

            wavs = generate_chunk_wavs(
                model=model,
                processor=processor,
                conversations=conversations,
                device=device,
                max_new_tokens=args.max_new_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                top_k=args.top_k,
                repetition_penalty=args.repetition_penalty,
            )

            for task, wav in zip(batch_tasks, wavs):
                script_id = task['script_id']
                state = script_states[script_id]

                if state['done'] or task['attempt'] != state['attempt']: continue

                state['wav_chunks'][task['chunk_idx']] = wav

                if len(state['wav_chunks']) < len(state['chunks']): continue

                ordered_wavs = [state['wav_chunks'][idx] for idx in range(len(state['chunks']))]
                merged_wav = torch.cat(ordered_wavs, dim=-1)
                output_path = OUTPUT_DIR / f"{script_id}.wav"
                _save_wav(merged_wav, output_path, target_sr)

                ent = {
                    "script_id": int(state['script_id']),
                    "wav_path": str(output_path),
                    "ref_paths": [ref.iden for ref in state['refs']],
                    "param": {
                        "temperature": args.temperature,
                        "top_k": args.top_k,
                        "top_p": args.top_p,
                        "repetition_penalty": args.repetition_penalty,
                        "max_new_tokens": args.max_new_tokens,
                        "chunks": len(state['chunks']),
                        "max_chars_per_chunk": args.mx_char_per_chunk,
                    },
                }

                if not is_wav_too_long(ent['wav_path'], args.max_wav_seconds):
                    manifests[script_id] = ent
                    state['done'] = True
                    active_script_ids = deque(sid for sid in active_script_ids if sid != script_id)
                    done_scripts += 1
                    pbar.update(1)
                    continue

                duration = get_wav_duration_seconds(ent['wav_path'])
                tqdm.write(f"Regenerate script {script_id}: duration {duration:.2f}s > {args.max_wav_seconds:.2f}s")
                remove_wav_if_exists(ent['wav_path'])

                if state['attempt'] >= args.max_regen_attempts:
                    raise RuntimeError(f"script {script_id} exceeds max duration after {state['attempt']} attempts")

                state['attempt'] += 1
                state['next_chunk_idx'] = 0
                state['wav_chunks'] = {}

        pbar.close()
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        with open(manifest_path, 'w', encoding='utf-8') as f:
            for entry in manifests.values():
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
