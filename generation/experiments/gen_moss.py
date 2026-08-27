import argparse
import json
import os
import random
import sys
from pathlib import Path

import soundfile as sf
import torch
import torchaudio
from tqdm import tqdm
from transformers import AutoModel, AutoProcessor

from ref.utils import RefEntry, get_entries, filter_entires
from utils.script import parse

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


def build_dialogue_turns(dialogue: list[dict[str, str]]) -> list[tuple[int, str]]:
    turns: list[tuple[int, str]] = []
    spk_map: dict[str, int] = {}

    for seg in dialogue:
        spk = str(seg.get("speaker", ""))
        txt = seg.get("text", "")

        if not txt:
            continue

        if spk not in spk_map:
            spk_map[spk] = len(spk_map)

        turns.append((spk_map[spk], txt))

    return turns


def build_turn_chunks(
    turns: list[tuple[int, str]], mx_chars_per_chunk: int = -1
) -> list[list[tuple[int, str]]]:
    if mx_chars_per_chunk is None or mx_chars_per_chunk < 0:
        return [turns]

    chunks: list[list[tuple[int, str]]] = []
    acc_turns: list[tuple[int, str]] = []
    acc_lens = 0

    for turn in turns:
        acc_lens += len(turn[1])
        acc_turns.append(turn)

        if acc_lens >= mx_chars_per_chunk:
            chunks.append(acc_turns)
            acc_lens = 0
            acc_turns = []

    if acc_turns:
        chunks.append(acc_turns)

    return chunks


def turns_to_text(turns: list[tuple[int, str]]) -> str:
    return "".join(f"[S{spk + 1}]{txt}" for spk, txt in turns)


def load_mono_wav(wav_path: str, target_sr: int) -> torch.Tensor:
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    wav = torch.from_numpy(audio).transpose(0, 1).contiguous()
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != target_sr:
        wav = torchaudio.functional.resample(wav, sr, target_sr)
    return wav


def load_model_and_processor(model_path: Path, codec_path: Path, device: str):
    dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32

    processor = AutoProcessor.from_pretrained(
        str(model_path), trust_remote_code=True, codec_path=str(codec_path)
    )
    if getattr(processor, "audio_tokenizer", None) is not None:
        processor.audio_tokenizer = processor.audio_tokenizer.to(device)
        processor.audio_tokenizer.eval()

    def _load(attn_implementation: str):
        return AutoModel.from_pretrained(
            str(model_path),
            trust_remote_code=True,
            attn_implementation=attn_implementation,
            dtype=dtype,
        ).to(device)

    if device.startswith("cuda"):
        try:
            model = _load("flash_attention_2")
        except Exception as exc:
            tqdm.write(f"[WARN] flash_attention_2 unavailable, fallback to sdpa. error={exc}")
            model = _load("sdpa")
    else:
        model = _load("sdpa")

    model.eval()
    return model, processor


def build_conversation(processor, refs: list[RefEntry], chunk_turns: list[tuple[int, str]], target_sr: int):
    wav1 = load_mono_wav(refs[0].wav, target_sr)
    wav2 = load_mono_wav(refs[1].wav, target_sr)

    reference_audio_codes = processor.encode_audios_from_wav([wav1, wav2], sampling_rate=target_sr)
    concat_prompt_wav = torch.cat([wav1, wav2], dim=-1)
    prompt_audio = processor.encode_audios_from_wav([concat_prompt_wav], sampling_rate=target_sr)[0]

    prompt_text = f"[S1]{refs[0].text}[S2]{refs[1].text}"
    full_text = prompt_text + turns_to_text(chunk_turns)

    return [
        processor.build_user_message(text=full_text, reference=reference_audio_codes),
        processor.build_assistant_message(audio_codes_list=[prompt_audio]),
    ]


def generate_chunk_wav(
    model,
    processor,
    conversation: list[dict],
    device: str,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
) -> torch.Tensor:
    batch = processor([conversation], mode="continuation")
    input_ids = batch["input_ids"].to(device)
    attention_mask = batch["attention_mask"].to(device)

    with torch.no_grad():
        outputs = model.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            max_new_tokens=max_new_tokens,
            audio_temperature=temperature,
            audio_top_p=top_p,
            audio_top_k=top_k,
            audio_repetition_penalty=repetition_penalty,
        )

    message = processor.decode(outputs)[0]
    wav_segments = [
        wav.detach().to(dtype=torch.float32, device="cpu").reshape(-1)
        for wav in message.audio_codes_list
        if isinstance(wav, torch.Tensor)
    ]
    if not wav_segments:
        raise RuntimeError("Model produced no audio for this chunk")
    return torch.cat(wav_segments, dim=0)


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
            processor=processor,
            device=device,
            script=script,
            refs=[patient_ref, doctor_ref],
            args=args,
        )
        manifests[script['dialogue_id']] = ent

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifests, f, ensure_ascii=False, indent=2)
