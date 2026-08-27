import argparse
import json
import os
import random
import sys
from pathlib import Path

import torch
from tqdm import tqdm

from ref.utils import RefEntry, get_entries, filter_entires
from utils.moss import (
    build_conversation,
    build_dialogue_turns,
    build_turn_chunks,
    generate_chunk_wav,
    load_model_and_processor,
)
from utils.script import parse
from utils.wav_chk import get_wav_duration_seconds, is_wav_too_long, remove_wav_if_exists

random.seed(42)

OUTPUT_DIR = Path(__file__).parent / "data" / "audio" / "moss"
PROJECT_ROOT = Path(__file__).parents[2]
MODEL_CODE_PATH = PROJECT_ROOT / "generation" / "models" / "moss-ttsd"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "pretrained" / "TTS" / "MOSS-TTSD-v1.0"
DEFAULT_CODEC_PATH = PROJECT_ROOT / "models" / "pretrained" / "TTS" / "MOSS-Audio-Tokenizer"

sys.path.append(str(MODEL_CODE_PATH))
from generation_utils import resolve_sampling_args  # noqa: E402

os.makedirs(str(OUTPUT_DIR), exist_ok=True)


def random_select(refs: list[RefEntry], ignore: RefEntry) -> RefEntry:
    while True:
        idx = random.randint(0, len(refs) - 1)
        ref = refs[idx]
        if ref != ignore:
            return ref


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


def generate(
    model,
    processor,
    device: str,
    script: dict[str, str | list],
    refs: list[RefEntry],
    args: argparse.Namespace,
) -> dict[str]:
    script_id = script["dialogue_id"]
    output_path = OUTPUT_DIR / f"{script_id}.wav"
    target_sr = int(processor.model_config.sampling_rate)

    turns = build_dialogue_turns(script["dialogue"])
    chunks = build_turn_chunks(turns, args.mx_char_per_chunk)

    wav_chunks: list[torch.Tensor] = []
    for chunk_turns in chunks:
        conversation = build_conversation(processor, refs, chunk_turns, target_sr)
        wav_chunk = generate_chunk_wav(
            model=model,
            processor=processor,
            conversation=conversation,
            device=device,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            top_k=args.top_k,
            repetition_penalty=args.repetition_penalty,
        )
        wav_chunks.append(wav_chunk)

    merged_wav = torch.cat(wav_chunks, dim=-1)
    import soundfile as sf
    sf.write(str(output_path), merged_wav.numpy(), target_sr)

    return {
        "script_id": script_id,
        "wav_path": str(output_path),
        "ref_paths": [ref.iden for ref in refs],
        "param": {
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "repetition_penalty": args.repetition_penalty,
            "max_new_tokens": args.max_new_tokens,
            "chunks": len(chunks),
            "max_chars_per_chunk": args.mx_char_per_chunk,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate WAVs from scripts.jsonl using MOSS-TTSD.")

    parser.add_argument("scripts", type=Path)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--codec-model-path", type=Path, default=DEFAULT_CODEC_PATH)
    parser.add_argument("--max-new-tokens", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--repetition-penalty", type=float, default=None)
    parser.add_argument("--max-wav-seconds", type=float, default=300.0)
    parser.add_argument("--max-regen-attempts", type=int, default=20)
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

    manifest_path = OUTPUT_DIR / "manifest.jsonl"
    manifests = load_existing_manifests(manifest_path)

    for script in tqdm(scripts):
        tqdm.write(f"[SCRIPT] {script['dialogue_id']}")
        script_id = script['dialogue_id']
        if args.sel_ids is not None and script_id not in args.sel_ids:
            tqdm.write(f"Skipping script {script_id}: not in sel_ids")
            continue

        attempts = 0
        while True:
            attempts += 1

            # randomly select a ref for patient
            patient_ref = random_select(
                filter_entires(ref_ents, script['meta'].get('language', 'Chinese'), script['meta']['sex']),
                None
            )
            doctor_ref = random_select(ref_ents, patient_ref)

            if script['dialogue'][0]['speaker'] == '医生':
                patient_ref, doctor_ref = doctor_ref, patient_ref

            ent = generate(
                model=model,
                processor=processor,
                device=device,
                script=script,
                refs=[patient_ref, doctor_ref],
                args=args,
            )

            if not is_wav_too_long(ent['wav_path'], args.max_wav_seconds):
                manifests[str(script_id)] = ent
                break

            duration = get_wav_duration_seconds(ent['wav_path'])
            tqdm.write(
                f"Regenerate script {script_id}: duration {duration:.2f}s > {args.max_wav_seconds:.2f}s"
            )
            remove_wav_if_exists(ent['wav_path'])

            if attempts >= args.max_regen_attempts:
                raise RuntimeError(
                    f"script {script_id} exceeds max duration after {attempts} attempts"
                )

    with open(manifest_path, 'w', encoding='utf-8') as f:
        for entry in manifests.values():
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
