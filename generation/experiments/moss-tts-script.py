#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Batch script generation for scripts.jsonl using MOSS-TTSD.

This script reads a JSONL file of dialogue scripts, converts each entry into
an [S1]/[S2] conversation text, and generates one WAV file per dialogue_id.

Chunking behavior:
- --max-char-per-chunk -1 (default): do not split, generate in one pass.
- positive value: split by character budget and merge chunk audios.
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import soundfile as sf
import torch
import torchaudio
from loguru import logger
from transformers import AutoModel, AutoProcessor

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]
MODEL_WEIGHT_PATH = PROJECT_ROOT / "models" / "pretrained" / "TTS"
MODEL_CODE_PATH = PROJECT_ROOT / "generation" / "models" / "moss-ttsd"

DEFAULT_MODEL_PATH = MODEL_WEIGHT_PATH / "MOSS-TTSD-v1.0"
DEFAULT_AUDIO_TOKENIZER_PATH = MODEL_WEIGHT_PATH / "MOSS-Audio-Tokenizer"
DEFAULT_SCRIPTS_FILE = THIS_FILE.parent / "scripts.jsonl"
DEFAULT_OUTPUT_DIR = THIS_FILE.parent / "moss_tts_scripts_tests"
DEFAULT_PATIENT_REF_WAV = MODEL_CODE_PATH / "asset" / "reference_02_s1.wav"
DEFAULT_DOCTOR_REF_WAV = MODEL_CODE_PATH / "asset" / "reference_02_s2.wav"

MODEL_REPO_DIR = PROJECT_ROOT / "generation" / "models" / "ming-omni-tts"
DEFAULT_PATIENT_REF_WAV = MODEL_REPO_DIR / "data" / "wavs" / "CTS-CN-F2F-2019-11-11-423-012-A.wav"
DEFAULT_DOCTOR_REF_WAV = MODEL_REPO_DIR / "data" / "wavs" / "CTS-CN-F2F-2019-11-11-423-012-B.wav"

sys.path.append(str(MODEL_CODE_PATH))

_GEN_UTILS_SPEC = importlib.util.spec_from_file_location(
    "moss_generation_utils", MODEL_CODE_PATH / "generation_utils.py"
)
if _GEN_UTILS_SPEC is None or _GEN_UTILS_SPEC.loader is None:
    raise ImportError(f"Unable to load generation_utils from {MODEL_CODE_PATH}")
_GEN_UTILS_MODULE = importlib.util.module_from_spec(_GEN_UTILS_SPEC)
_GEN_UTILS_SPEC.loader.exec_module(_GEN_UTILS_MODULE)

resolve_sampling_args = _GEN_UTILS_MODULE.resolve_sampling_args
run_infer_batch = _GEN_UTILS_MODULE.run_infer_batch


class MossAudio:
    def __init__(
        self,
        model_path: Path,
        audio_tokenizer_path: Path,
        device: Optional[str] = None,
        attn_implementation: Optional[str] = None,
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self.attn_implementation = attn_implementation or (
            "flash_attention_2" if self.device == "cuda" else "sdpa"
        )

        self.processor = AutoProcessor.from_pretrained(
            model_path,
            trust_remote_code=True,
            codec_path=audio_tokenizer_path,
        )
        self.processor.audio_tokenizer = self.processor.audio_tokenizer.to(self.device)
        self.processor.audio_tokenizer.eval()

        self.model = AutoModel.from_pretrained(
            model_path,
            trust_remote_code=True,
            attn_implementation=self.attn_implementation,
            torch_dtype=self.dtype,
        ).to(self.device)
        self.model.eval()

        self.sample_rate = int(self.processor.model_config.sampling_rate)

    def _load_prompt_wav(self, wav_path: Path) -> torch.Tensor:
        audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
        wav = torch.from_numpy(audio).transpose(0, 1).contiguous()
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        if sr != self.sample_rate:
            wav = torchaudio.functional.resample(wav, sr, self.sample_rate)
        return wav

    def _build_reference_and_prompt_audio(
        self,
        prompt_audio_speaker1: Path,
        prompt_audio_speaker2: Path,
        sample_rate_normalize: bool,
    ):
        audio1, sr1 = sf.read(prompt_audio_speaker1, dtype="float32", always_2d=True)
        audio2, sr2 = sf.read(prompt_audio_speaker2, dtype="float32", always_2d=True)
        wav1 = torch.from_numpy(audio1).transpose(0, 1).contiguous()
        wav2 = torch.from_numpy(audio2).transpose(0, 1).contiguous()

        if wav1.shape[0] > 1:
            wav1 = wav1.mean(dim=0, keepdim=True)
        if wav2.shape[0] > 1:
            wav2 = wav2.mean(dim=0, keepdim=True)

        if sample_rate_normalize:
            min_sr = min(sr1, sr2)
            if sr1 != min_sr:
                wav1 = torchaudio.functional.resample(wav1, sr1, min_sr)
            if sr2 != min_sr:
                wav2 = torchaudio.functional.resample(wav2, sr2, min_sr)
            sr1 = sr2 = min_sr

        if sr1 != self.sample_rate:
            wav1 = torchaudio.functional.resample(wav1, sr1, self.sample_rate)
        if sr2 != self.sample_rate:
            wav2 = torchaudio.functional.resample(wav2, sr2, self.sample_rate)

        reference_audio_codes = self.processor.encode_audios_from_wav(
            [wav1, wav2], sampling_rate=self.sample_rate
        )
        concat_prompt_wav = torch.cat([wav1, wav2], dim=-1)
        prompt_audio = self.processor.encode_audios_from_wav(
            [concat_prompt_wav], sampling_rate=self.sample_rate
        )[0]
        return reference_audio_codes, prompt_audio

    def speech_generation(
        self,
        text: str,
        prompt_text_speaker1: str,
        prompt_text_speaker2: str,
        prompt_audio_speaker1: Path,
        prompt_audio_speaker2: Path,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        repetition_penalty: float,
        sample_rate_normalize: bool,
    ) -> torch.Tensor:
        reference_audio_codes, prompt_audio = self._build_reference_and_prompt_audio(
            prompt_audio_speaker1=prompt_audio_speaker1,
            prompt_audio_speaker2=prompt_audio_speaker2,
            sample_rate_normalize=sample_rate_normalize,
        )

        full_text = f"{prompt_text_speaker1} {prompt_text_speaker2} {text}".strip()

        conversations = [
            [
                self.processor.build_user_message(
                    text=full_text,
                    reference=reference_audio_codes,
                ),
                self.processor.build_assistant_message(audio_codes_list=[prompt_audio]),
            ]
        ]

        with torch.no_grad():
            batch = self.processor(conversations, mode="continuation")
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)

            outputs = self.model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=max_new_tokens,
                audio_temperature=temperature,
                audio_top_p=top_p,
                audio_top_k=top_k,
                audio_repetition_penalty=repetition_penalty,
            )

            decoded = self.processor.decode(outputs)
            if not decoded:
                raise RuntimeError("MOSS decode returned empty result")
            first_msg = decoded[0]
            if not getattr(first_msg, "audio_codes_list", None):
                raise RuntimeError("MOSS decode has no audio_codes_list")

            # Use the first generated segment for each generation call.
            audio = first_msg.audio_codes_list[0]
            return audio.detach().cpu().to(torch.float32)

    def speech_generation_batch(
        self,
        texts: List[str],
        prompt_text_speaker1: str,
        prompt_text_speaker2: str,
        prompt_audio_speaker1: Path,
        prompt_audio_speaker2: Path,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        repetition_penalty: float,
        sample_rate_normalize: bool,
    ) -> List[torch.Tensor]:
        if not texts:
            return []

        reference_audio_codes, prompt_audio = self._build_reference_and_prompt_audio(
            prompt_audio_speaker1=prompt_audio_speaker1,
            prompt_audio_speaker2=prompt_audio_speaker2,
            sample_rate_normalize=sample_rate_normalize,
        )

        conversations = []
        for text in texts:
            full_text = f"{prompt_text_speaker1} {prompt_text_speaker2} {text}".strip()
            conversations.append(
                [
                    self.processor.build_user_message(
                        text=full_text,
                        reference=reference_audio_codes,
                    ),
                    self.processor.build_assistant_message(audio_codes_list=[prompt_audio]),
                ]
            )

        with torch.no_grad():
            batch = self.processor(conversations, mode="continuation")
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)

            outputs = self.model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=max_new_tokens,
                audio_temperature=temperature,
                audio_top_p=top_p,
                audio_top_k=top_k,
                audio_repetition_penalty=repetition_penalty,
            )

            decoded = self.processor.decode(outputs)
            if not decoded:
                raise RuntimeError("MOSS decode returned empty result")

            waveforms: List[torch.Tensor] = []
            for message in decoded:
                if not getattr(message, "audio_codes_list", None):
                    raise RuntimeError("MOSS decode has no audio_codes_list")
                audio = message.audio_codes_list[0]
                waveforms.append(audio.detach().cpu().to(torch.float32))

            return waveforms

def safe_name(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] if text else "sample"


def normalize_text(text: str) -> str:
    if text is None:
        return ""

    text = str(text).strip()
    if not text:
        return ""

    text = text.replace(" ", "，")
    if len(text) > 1:
        text = text[:-1].replace("。", "，").replace("！", "，").replace("?", "，").replace("？", "，") + text[-1]
    if not (text.endswith("。") or text.endswith("！") or text.endswith("？")):
        text = text + "。"
    return text


def build_dialogue_text(script: Dict, text_normalize: bool = False) -> str:
    segments = script.get("dialogue", [])
    lines: List[str] = []
    speaker_map: Dict[str, str] = {}
    speaker_cnt = 0

    for segment in segments:
        speaker = str(segment.get("speaker", ""))
        text = normalize_text(segment.get("text", ""))
        if not text:
            continue

        if speaker not in speaker_map:
            speaker_cnt += 1
            speaker_map[speaker] = f"S{speaker_cnt}"
        speaker_key = speaker_map[speaker]
        lines.append(f"[{speaker_key}] {text}")

    merged_text = "\n".join(lines)
    return merged_text if not text_normalize else normalize_text(merged_text)


def chunk_dialogue_text(dialogue_text: str, max_chars_per_chunk: int = -1) -> List[str]:
    if max_chars_per_chunk is None or max_chars_per_chunk <= 0:
        return [dialogue_text] if dialogue_text.strip() else []

    lines = [line.strip() for line in dialogue_text.splitlines() if line.strip()]
    if not lines:
        return []

    chunks: List[str] = []
    current_lines: List[str] = []

    for i, line in enumerate(lines):
        if not current_lines:
            current_lines = [line]
            continue

        candidate_lines = current_lines + [line]
        candidate_text = "\n".join(candidate_lines)

        # Keep rough turn-pair boundary behavior from existing ming script.
        if len(candidate_text) > max_chars_per_chunk and i % 2 == 0:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
        else:
            current_lines = candidate_lines

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def parse_scripts_file(path: Path) -> List[Dict]:
    entries: List[Dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping invalid JSON at {}:{}: {}".format(path, line_number, exc))
    return entries


def run_script_case(
    model: MossAudio,
    script_id: str,
    text: str,
    output_dir: Path,
    prompt_text_speaker1: str,
    prompt_text_speaker2: str,
    prompt_audio_speaker1: Path,
    prompt_audio_speaker2: Path,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
    sample_rate_normalize: bool,
    chunk_batch_size: int,
    max_chars_per_chunk: int = -1,
) -> Dict:
    output_path = output_dir / f"{safe_name(str(script_id))}.wav"
    logger.info("Total dialogue text length: {} characters".format(len(text)))

    chunk_texts = chunk_dialogue_text(text, max_chars_per_chunk=max_chars_per_chunk)
    if not chunk_texts:
        raise ValueError(f"No valid dialogue lines to generate for script {script_id}")

    logger.info("Generating {} chunk(s) for {}".format(len(chunk_texts), script_id))

    waveform_chunks: List[torch.Tensor] = []
    total_chunks = len(chunk_texts)
    chunk_batch_size = max(1, min(chunk_batch_size, total_chunks))
    for start in range(0, total_chunks, chunk_batch_size):
        end = min(start + chunk_batch_size, total_chunks)
        logger.info("Generating chunks {}/{}-{} for {}".format(start + 1, end, total_chunks, script_id))
        chunk_waveforms = model.speech_generation_batch(
            texts=chunk_texts[start:end],
            prompt_text_speaker1=prompt_text_speaker1,
            prompt_text_speaker2=prompt_text_speaker2,
            prompt_audio_speaker1=prompt_audio_speaker1,
            prompt_audio_speaker2=prompt_audio_speaker2,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            sample_rate_normalize=sample_rate_normalize,
        )
        waveform_chunks.extend(chunk_waveforms)

    merged_waveform = torch.cat(waveform_chunks, dim=-1)
    sf.write(
        output_path,
        merged_waveform.numpy().squeeze(),
        model.sample_rate,
    )

    return {
        "dialogue_id": script_id,
        "output_wav_path": str(output_path),
        "prompt_audio_speaker1": str(prompt_audio_speaker1),
        "prompt_audio_speaker2": str(prompt_audio_speaker2),
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "repetition_penalty": repetition_penalty,
        "chunks": len(chunk_texts),
        "max_chars_per_chunk": max_chars_per_chunk,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate WAVs from scripts.jsonl using MOSS-TTSD.")
    parser.add_argument("--input_jsonl", "--scripts-file", type=Path, default=DEFAULT_SCRIPTS_FILE)
    parser.add_argument("--save_dir", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model_path", "--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--codec_model_path", "--audio-tokenizer-path", type=Path, default=DEFAULT_AUDIO_TOKENIZER_PATH)
    parser.add_argument("--patient-ref-wav", type=Path, default=DEFAULT_PATIENT_REF_WAV)
    parser.add_argument("--doctor-ref-wav", type=Path, default=DEFAULT_DOCTOR_REF_WAV)
    # parser.add_argument("--prompt-text-speaker1", type=str, default="[S1] In short, we embarked on a mission to make America great again for all Americans.")
    # parser.add_argument("--prompt-text-speaker2", type=str, default="[S2] NVIDIA reinvented computing for the first time after 60 years. In fact, Erwin at IBM knows quite well that the computer has largely been the same since the 60s.")
    parser.add_argument("--prompt-text-speaker1", type=str, default="[S1] 并且我们还要进行每个月还要考核 笔试的话还要进行笔试，做个，当服务员还要去笔试了。")
    parser.add_argument("--prompt-text-speaker2", type=str, default="[S2] 对啊，这真的很奇怪，就是 单纯的因，单纯自己工资不高，只是因为可能人家那个店比较出名一点，就对你苛刻要求，")
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--attn-implementation", type=str, default=None)
    parser.add_argument(
        "--mode",
        type=str,
        choices=["generation", "continuation", "voice_clone", "voice_clone_and_continuation"],
        default="voice_clone_and_continuation",
    )
    parser.add_argument("--max_new_tokens", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top_p", type=float, default=None)
    parser.add_argument("--top_k", type=int, default=None)
    parser.add_argument("--repetition_penalty", type=float, default=None)
    parser.add_argument("--text_normalize", action="store_true", default=False)
    parser.add_argument("--sample_rate_normalize", action="store_true", default=False)
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size for script-level generation.")
    parser.add_argument(
        "--max-char-per-chunk",
        dest="max_char_per_chunk",
        type=int,
        default=-1,
        help="Maximum number of characters per generated audio chunk. Use -1 to disable chunking.",
    )
    parser.add_argument("--sel-ids", type=lambda s: list(map(int, s.split(","))), default=None)
    args = parser.parse_args()

    resolve_sampling_args(args)

    if args.batch_size < 1:
        raise ValueError("`batch-size` must be >= 1.")
    if not args.input_jsonl.exists():
        raise FileNotFoundError(f"scripts file not found: {args.input_jsonl}")
    if not args.model_path.exists():
        raise FileNotFoundError(f"Model path not found: {args.model_path}")
    if not args.codec_model_path.exists():
        raise FileNotFoundError(f"Audio tokenizer path not found: {args.codec_model_path}")
    if not args.patient_ref_wav.exists():
        raise FileNotFoundError(f"Patient reference wav not found: {args.patient_ref_wav}")
    if not args.doctor_ref_wav.exists():
        raise FileNotFoundError(f"Doctor reference wav not found: {args.doctor_ref_wav}")

    args.save_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading MOSS model from: {}".format(args.model_path))
    model = MossAudio(
        model_path=args.model_path,
        audio_tokenizer_path=args.codec_model_path,
        device=args.device,
        attn_implementation=args.attn_implementation,
    )

    entries = parse_scripts_file(args.input_jsonl)
    manifest: List[Dict] = []
    prompt_reference_audio = None
    prompt_audio = None

    if args.max_char_per_chunk <= 0 and args.mode in ("continuation", "voice_clone", "voice_clone_and_continuation"):
        prompt_reference_audio, prompt_audio = model._build_reference_and_prompt_audio(
            prompt_audio_speaker1=args.patient_ref_wav,
            prompt_audio_speaker2=args.doctor_ref_wav,
            sample_rate_normalize=args.sample_rate_normalize,
        )

    logger.info("selected indices: {}".format(args.sel_ids))

    if args.max_char_per_chunk <= 0:
        batch_data: List = []
        output_jsonl_path = args.save_dir / "output.jsonl"
        for line_no, script in enumerate(entries, start=1):
            script_id = script.get("dialogue_id") or script.get("id") or script.get("script_id")
            if script_id is None:
                logger.warning("Skipping script with missing dialogue_id")
                continue
            if args.sel_ids is not None and script_id not in args.sel_ids:
                logger.info("Skipping script {} out of selected indices.".format(script_id))
                continue

            text = build_dialogue_text(script, text_normalize=args.text_normalize)
            if not text:
                logger.warning("Skipping script {} with no dialogue".format(script_id))
                continue

            raw_sample = {
                "id": str(script_id),
                "text": text,
                "prompt_audio_speaker1": str(args.patient_ref_wav),
                "prompt_text_speaker1": args.prompt_text_speaker1,
                "prompt_audio_speaker2": str(args.doctor_ref_wav),
                "prompt_text_speaker2": args.prompt_text_speaker2,
            }
            sample_id = str(script_id)
            output_record = dict(raw_sample)
            conversation = [model.processor.build_user_message(text=text)]
            if args.mode == "continuation":
                conversation = [
                    model.processor.build_user_message(text=text),
                    model.processor.build_assistant_message(audio_codes_list=[prompt_audio]),
                ]
            elif args.mode == "voice_clone":
                conversation = [
                    model.processor.build_user_message(text=text, reference=prompt_reference_audio),
                ]
            elif args.mode == "voice_clone_and_continuation":
                conversation = [
                    model.processor.build_user_message(text=text, reference=prompt_reference_audio),
                    model.processor.build_assistant_message(audio_codes_list=[prompt_audio]),
                ]

            batch_data.append((sample_id, output_record, conversation))
            if len(batch_data) < args.batch_size:
                continue

            with open(output_jsonl_path, "a", encoding="utf-8") as out_fp:
                run_infer_batch(
                    batch_data=batch_data,
                    model=model.model,
                    processor=model.processor,
                    mode=args.mode,
                    device=args.device,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    top_k=args.top_k,
                    repetition_penalty=args.repetition_penalty,
                    save_dir=args.save_dir,
                    out_fp=out_fp,
                )
            for sample_id, output_record, _conversation in batch_data:
                manifest.append(
                    {
                        "dialogue_id": output_record.get("id", sample_id),
                        "output_wav_path": str((args.save_dir / f"{sample_id}.wav").resolve()),
                        "chunks": 1,
                        "max_chars_per_chunk": args.max_char_per_chunk,
                        "batch_size": args.batch_size,
                    }
                )
            batch_data = []

        if batch_data:
            with open(output_jsonl_path, "a", encoding="utf-8") as out_fp:
                run_infer_batch(
                    batch_data=batch_data,
                    model=model.model,
                    processor=model.processor,
                    mode=args.mode,
                    device=args.device,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    top_k=args.top_k,
                    repetition_penalty=args.repetition_penalty,
                    save_dir=args.save_dir,
                    out_fp=out_fp,
                )
            for sample_id, output_record, _conversation in batch_data:
                manifest.append(
                    {
                        "dialogue_id": output_record.get("id", sample_id),
                        "output_wav_path": str((args.save_dir / f"{sample_id}.wav").resolve()),
                        "chunks": 1,
                        "max_chars_per_chunk": args.max_char_per_chunk,
                        "batch_size": args.batch_size,
                    }
                )
    else:
        for script in entries:
            script_id = script.get("dialogue_id") or script.get("id") or script.get("script_id")
            if script_id is None:
                logger.warning("Skipping script with missing dialogue_id")
                continue
            if args.sel_ids is not None and script_id not in args.sel_ids:
                logger.info("Skipping script {} out of selected indices.".format(script_id))
                continue

            text = build_dialogue_text(script, text_normalize=args.text_normalize)
            if not text:
                logger.warning("Skipping script {} with no dialogue".format(script_id))
                continue

            entry = run_script_case(
                model=model,
                script_id=script_id,
                text=text,
                output_dir=args.save_dir,
                prompt_text_speaker1=args.prompt_text_speaker1,
                prompt_text_speaker2=args.prompt_text_speaker2,
                prompt_audio_speaker1=args.patient_ref_wav,
                prompt_audio_speaker2=args.doctor_ref_wav,
                max_new_tokens=args.max_new_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                top_k=args.top_k,
                repetition_penalty=args.repetition_penalty,
                sample_rate_normalize=args.sample_rate_normalize,
                chunk_batch_size=args.batch_size,
                max_chars_per_chunk=args.max_char_per_chunk,
            )
            manifest.append(entry)

    manifest_path = args.save_dir / "scripts_generation_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info("Generated {} scripts. Manifest saved to {}".format(len(manifest), manifest_path))


if __name__ == "__main__":
    main()
