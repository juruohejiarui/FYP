import argparse
import json
import os
import torch
import random
from pathlib import Path
from tqdm import tqdm
from utils.soulx import SoulxAudio, build_dialogue_turns, build_turn_chunks
from utils.script import parse
from ref.utils import RefEntry, get_entries, filter_entires
from soulxpodcast.config import SamplingParams

random.seed(42)

OUTPUT_DIR = Path(__file__).parent / "data" / "audio" / "soulx"
PROJECT_ROOT = Path(__file__).parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "pretrained" / "TTS" / "SoulX-Podcast-1.7B-dialect"

os.makedirs(str(OUTPUT_DIR), exist_ok=True)


def random_select(refs: list[RefEntry], ignore: RefEntry) -> RefEntry:
    while True:
        idx = random.randint(0, len(refs) - 1)
        ref = refs[idx]
        if ref != ignore:
            return ref


def generate(
    model: SoulxAudio,
    script: dict[str, str | list],
    refs: list[RefEntry],
    sampling_params: SamplingParams,
    mx_chars_per_chunk: int,
) -> dict[str]:
    script_id = script["dialogue_id"]
    output_path = OUTPUT_DIR / f"{script_id}.wav"

    turns = build_dialogue_turns(script["dialogue"])
    chunks = build_turn_chunks(turns, mx_chars_per_chunk)

    prompt_wavs = [ref.wav for ref in refs]
    prompt_texts = [ref.text for ref in refs]

    wav_chunks: list[torch.Tensor] = []
    for chunk_idx, chunk_turns in enumerate(chunks):
        wav_chunk = model.generate_dialogue(
            key=f"{script_id}-{chunk_idx}",
            prompt_wavs=prompt_wavs,
            prompt_texts=prompt_texts,
            turns=chunk_turns,
            sampling_params=sampling_params,
        )
        if wav_chunk is None:
            raise RuntimeError(f"Failed to generate waveform for chunk {chunk_idx} of script {script_id}")
        wav_chunks.append(wav_chunk)

    merged_wav = torch.cat(wav_chunks, dim=-1)
    model.save(merged_wav, output_path)

    return {
        "script_id": script_id,
        "wav_path": str(output_path),
        "ref_paths": [ref.iden for ref in refs],
        "param": {
            "temperature": sampling_params.temperature,
            "top_k": sampling_params.top_k,
            "top_p": sampling_params.top_p,
            "repetition_penalty": sampling_params.repetition_penalty,
            "chunks": len(chunks),
            "max_chars_per_chunk": mx_chars_per_chunk,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate WAVs from scripts.jsonl using SoulX-Podcast.")

    parser.add_argument("scripts", type=Path)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--llm-engine", type=str, choices=["hf", "vllm"], default="hf")
    parser.add_argument("--fp16-flow", action="store_true")
    parser.add_argument("--seed", type=int, default=1988)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--repetition-penalty", type=float, default=2.0)
    parser.add_argument(
        "--mx-char-per-chunk", type=int, default=-1,
        help="Maximum number of characters per generated audio chunk. Use -1 to disable chunking.",
    )
    parser.add_argument("--sel-ids", type=lambda s: list(map(int, s.split(','))), default=None)
    args = parser.parse_args()

    ref_ents = get_entries()

    scripts: list[dict[str, dict | list]] = parse(args.scripts)

    model = SoulxAudio(
        model_path=args.model_path,
        llm_engine=args.llm_engine,
        fp16_flow=args.fp16_flow,
        seed=args.seed,
    )

    sampling_params = SamplingParams(
        temperature=args.temperature,
        top_k=args.top_k,
        top_p=args.top_p,
        repetition_penalty=args.repetition_penalty,
    )

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifests: dict[str, dict[str]] = {}

    if os.path.exists(manifest_path):
        with open(manifest_path, 'r') as f:
            manifests = json.load(f)

    for script in tqdm(scripts):
        script_id = script['dialogue_id']
        if args.sel_ids is not None and script_id not in args.sel_ids:
            tqdm.write(f"Skipping script {script_id}: not in sel_ids")
            continue

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
            script=script,
            refs=[patient_ref, doctor_ref],
            sampling_params=sampling_params,
            mx_chars_per_chunk=args.mx_char_per_chunk,
        )
        manifests[script['dialogue_id']] = ent

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifests, f, ensure_ascii=False, indent=2)
