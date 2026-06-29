#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Batch script generation for scripts.jsonl using Ming-omni-TTS.

This script reads a JSONL file of dialogue scripts, converts each entry
into a speaker_1 / speaker_2 dialogue prompt, and generates one WAV file
per dialogue_id.

Default speaker embeddings use the same reference audios as the new
colloquial podcast case in `ming-tts.py`.
"""

import argparse
import json
import os
import re
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch
import torchaudio
from loguru import logger
from transformers import AutoTokenizer

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]
MODEL_REPO_DIR = PROJECT_ROOT / "generation" / "models" / "ming-omni-tts"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "pretrained" / "TTS" / "Ming-omni-tts-0.5B"
DEFAULT_SCRIPTS_FILE = THIS_FILE.parent / "scripts.jsonl"
DEFAULT_OUTPUT_DIR = THIS_FILE.parent / "ming_tss_scripts_tests"
DEFAULT_PATIENT_REF_WAV = MODEL_REPO_DIR / "data" / "wavs" / "CTS-CN-F2F-2019-11-11-423-012-A.wav"
DEFAULT_DOCTOR_REF_WAV = MODEL_REPO_DIR / "data" / "wavs" / "CTS-CN-F2F-2019-11-11-423-012-B.wav"

sys.path.append(str(MODEL_REPO_DIR))
from modeling_bailingmm import BailingMMNativeForConditionalGeneration  # noqa: E402
from sentence_manager.sentence_manager import SentenceNormalizer  # noqa: E402
from spkemb_extractor import SpkembExtractor  # noqa: E402

warnings.filterwarnings("ignore")

DEFAULT_PROMPT = "Please generate speech based on the following description.\n"
CONVERSATIONAL_PROMPT = (
    "Please generate natural conversational speech in Mandarin Chinese. "
    "Make it sound like an everyday clinic dialogue, with natural pauses and "
    "no announcer or drama tone.\n"
)
prompt_diag = [
    {"speaker_1": "并且我们还要进行每个月还要考核 笔试的话还要进行笔试，做个，当服务员还要去笔试了"},
    {"speaker_2": "对啊，这真的很奇怪，就是 单纯的因，单纯自己工资不高，只是因为可能人家那个店比较出名一点，就对你苛刻要求"},
]
DEFAULT_PROMPT_TEXT = " " + "\n ".join([f"{k}:{v}" for item in prompt_diag for k, v in item.items()]) + "\n"

# modify of model loading
class MingAudio:
    def __init__(self, model_path: str | Path, device: str = "cuda:0"):
        self.device = device
        model_path = str(model_path)
        if not os.path.isdir(model_path):
            raise FileNotFoundError(f"Model path not found: {model_path}")

        self.model = BailingMMNativeForConditionalGeneration.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        )
        self.model = self.model.eval().to(torch.bfloat16).to(self.device)

        if self.model.model_type == "dense":
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        else:
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

        self.model.tokenizer = self.tokenizer
        self.sample_rate = self.model.config.audio_tokenizer_config.sample_rate
        self.patch_size = self.model.config.ditar_config["patch_size"]
        self.normalizer = self.init_tn_normalizer(tokenizer=self.tokenizer)
        self.spkemb_extractor = SpkembExtractor(str(Path(model_path) / "campplus.onnx"))

    def init_tn_normalizer(self, config_file_path: Optional[str] = None, tokenizer=None):
        if config_file_path is None:
            config_file_path = str(MODEL_REPO_DIR / "sentence_manager" / "default_config.yaml")

        import yaml

        with open(config_file_path, "r", encoding="utf-8") as f:
            self.sentence_manager_config = yaml.safe_load(f)

        if "split_token" not in self.sentence_manager_config:
            self.sentence_manager_config["split_token"] = []

        assert isinstance(self.sentence_manager_config["split_token"], list)
        if tokenizer is not None:
            self.sentence_manager_config["split_token"].append(re.escape(tokenizer.eos_token))

        return SentenceNormalizer(self.sentence_manager_config.get("text_norm", {}))

    def pad_waveform(self, waveform: torch.Tensor) -> torch.Tensor:
        pad_align = int(1 / 12.5 * self.patch_size * self.sample_rate)
        new_len = (waveform.size(-1) + pad_align - 1) // pad_align * pad_align
        if new_len != waveform.size(1):
            new_waveform = torch.zeros(1, new_len, dtype=waveform.dtype, device=waveform.device)
            new_waveform[:, :waveform.size(1)] = waveform.clone()
            waveform = new_waveform
        return waveform

    def preprocess_one_prompt_wav(self, waveform_path: str, use_spk_emb: bool):
        if waveform_path is None:
            return None, None

        waveform, sr = torchaudio.load(waveform_path)
        waveform1 = waveform.clone()

        if sr != self.sample_rate:
            waveform = torchaudio.transforms.Resample(orig_freq=sr, new_freq=self.sample_rate)(waveform)

        if use_spk_emb:
            waveform1 = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)(waveform1)
            spk_emb = self.spkemb_extractor(waveform1)
        else:
            spk_emb = None

        return waveform, spk_emb

    def speech_generation(
        self,
        prompt: str,
        text: str,
        use_spk_emb: bool = False,
        use_zero_spk_emb: bool = False,
        instruction: Optional[Dict] = None,
        prompt_wav_path=None,
        prompt_text: Optional[str] = None,
        max_decode_steps: int = 200,
        cfg: float = 2.0,
        sigma: float = 0.25,
        temperature: float = 0.0,
        output_wav_path: Optional[str] = "./out.wav",
    ):
        if prompt_wav_path is None:
            prompt_waveform, prompt_text, spk_emb = None, None, None
            if use_zero_spk_emb:
                spk_emb = [torch.zeros(1, 192, device=self.device, dtype=torch.bfloat16)]
        else:
            paths = prompt_wav_path if isinstance(prompt_wav_path, list) else [prompt_wav_path]
            processed_prompts = [self.preprocess_one_prompt_wav(p, use_spk_emb) for p in paths]
            waveforms_list, spk_emb = zip(*processed_prompts)
            prompt_waveform = torch.cat(waveforms_list, dim=-1)
            prompt_waveform = self.pad_waveform(prompt_waveform)
            spk_emb = list(spk_emb)
            if all([x is None for x in spk_emb]):
                spk_emb = None

        if instruction is not None:
            instruction = self.create_instruction(instruction)
            instruction = json.dumps(instruction, ensure_ascii=False)

        waveform = self.model.generate(
            prompt=prompt,
            text=text,
            spk_emb=spk_emb,
            instruction=instruction,
            prompt_waveform=prompt_waveform,
            prompt_text=prompt_text,
            max_decode_steps=max_decode_steps,
            cfg=cfg,
            sigma=sigma,
            temperature=temperature,
            use_zero_spk_emb=use_zero_spk_emb,
        )

        if output_wav_path is not None:
            output_wav_path = str(output_wav_path)
            os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)
            torchaudio.save(output_wav_path, waveform, sample_rate=self.sample_rate)

        return waveform

    def create_instruction(self, user_input: Dict):
        base_caption = {
            "audio_sequence": [
                {
                    "序号": 1,
                    "说话人": "speaker_1",
                    "方言": None,
                    "风格": None,
                    "语速": None,
                    "基频": None,
                    "音量": None,
                    "情感": None,
                    "BGM": {
                        "Genre": None,
                        "Mood": None,
                        "Instrument": None,
                        "Theme": None,
                        "ENV": None,
                        "SNR": None,
                    },
                    "IP": None,
                }
            ]
        }
        new_caption = json.loads(json.dumps(base_caption, ensure_ascii=False))
        target_item_dict = new_caption["audio_sequence"][0]
        for key, value in user_input.items():
            if key in target_item_dict:
                target_item_dict[key] = value
        if target_item_dict["BGM"].get("SNR", None) is not None:
            new_order = ["序号", "说话人", "BGM", "情感", "方言", "风格", "语速", "基频", "音量", "IP"]
            target_item_dict = {k: target_item_dict[k] for k in new_order if k in target_item_dict}
            new_caption["audio_sequence"][0] = target_item_dict
        return new_caption


# ---------------------------------------------------------------------

def safe_name(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] if text else "sample"


def normalize_text(text: str) -> str:
    if text is None:
        return ""

    text = text.strip()
    if not text:
        return ""

    text = text.replace(" ", "，")
    text = text[:-1].replace("。", "，").replace("！", "，").replace("?", "，").replace("？", "，") + text[-1]
    if not (text.endswith("。") or text.endswith("！") or text.endswith("？")) :
        text = text + "。"
    
    return text

def build_dialogue_text(script: Dict) -> str:
    segments = script.get("dialogue", [])
    lines: List[str] = []
    
    speaker_map = {}
    speaker_cnt = 0
    for segment in segments:
        speaker = str(segment.get("speaker", ""))
        voice_role = str(segment.get("voice_role", ""))
        text = normalize_text(segment.get("text", ""))
        if not text:
            continue
        if speaker not in speaker_map :
            speaker_cnt += 1
            speaker_map[speaker] = f"speaker_{speaker_cnt}"
        speaker_key = speaker_map[speaker]
        lines.append(f"{speaker_key}:{text}")
    return " " + "\n ".join(lines) + "\n" if lines else ""


def chunk_dialogue_text(dialogue_text: str, max_chars_per_chunk: int = 800) -> List[str]:
    if max_chars_per_chunk is None or max_chars_per_chunk <= 0:
        return [dialogue_text] if dialogue_text.strip() else []

    lines = [line.strip() for line in dialogue_text.splitlines() if line.strip()]
    if not lines:
        return []

    chunks: List[str] = []
    current_lines: List[str] = []
    current_chunk_text = ""

    for i, line in enumerate(lines) :
        if not current_lines:
            current_lines = [line]
            current_chunk_text = " " + line + "\n"
            continue

        candidate_lines = current_lines + [line]
        candidate_text = " " + "\n ".join(candidate_lines) + "\n"

        if len(candidate_text) > max_chars_per_chunk and i % 2 == 0:
            chunks.append(current_chunk_text)
            current_lines = [line]
            current_chunk_text = " " + line + "\n"
        else:
            current_lines = candidate_lines
            current_chunk_text = candidate_text

    if current_lines:
        chunks.append(current_chunk_text)

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
    model: MingAudio,
    script_id: str,
    text: str,
    output_dir: Path,
    prompt: str,
    prompt_text: Optional[str],
    prompt_wav_path: Optional[List[str]],
    use_spk_emb: bool,
    use_zero_spk_emb: bool,
    cfg: float,
    sigma: float,
    temperature: float,
    max_decode_steps: int,
    max_chars_per_chunk: int = 800,
) -> Dict:
    output_path = output_dir / f"{safe_name(str(script_id))}.wav"
    logger.info("Prompt Text: {}".format(prompt_text))
    logger.info("Total dialogue text length: {} characters".format(len(text)))

    chunk_texts = chunk_dialogue_text(text, max_chars_per_chunk=max_chars_per_chunk)
    if not chunk_texts:
        raise ValueError(f"No valid dialogue lines to generate for script {script_id}")

    logger.info("Generating {} chunk(s) for {}".format(len(chunk_texts), script_id))
    waveform_chunks: List[torch.Tensor] = []
    for chunk_index, chunk_text in enumerate(chunk_texts, start=1):
        logger.info("Generating chunk {}/{} for {}".format(chunk_index, len(chunk_texts), script_id))
        chunk_waveform = model.speech_generation(
            prompt=prompt,
            text=chunk_text,
            use_spk_emb=use_spk_emb,
            use_zero_spk_emb=use_zero_spk_emb,
            prompt_wav_path=prompt_wav_path,
            prompt_text=prompt_text,
            max_decode_steps=max_decode_steps,
            cfg=cfg,
            sigma=sigma,
            temperature=temperature,
            output_wav_path=None,
        )
        if chunk_waveform is None:
            raise RuntimeError(f"Failed to generate waveform for chunk {chunk_index} of script {script_id}")
        waveform_chunks.append(chunk_waveform)

    merged_waveform = torch.cat(waveform_chunks, dim=-1)
    os.makedirs(os.path.dirname(str(output_path)), exist_ok=True)
    torchaudio.save(str(output_path), merged_waveform, sample_rate=model.sample_rate)

    return {
        "dialogue_id": script_id,
        "output_wav_path": str(output_path),
        "speaker_embed_refs": prompt_wav_path,
        "cfg": cfg,
        "sigma": sigma,
        "temperature": temperature,
        "max_decode_steps": max_decode_steps,
        "chunks": len(chunk_texts),
        "max_chars_per_chunk": max_chars_per_chunk,
    }


def build_prompt_wav_path(patient_ref: Optional[Path], doctor_ref: Optional[Path]) -> Optional[List[str]]:
    if patient_ref is None and doctor_ref is None:
        return None
    if patient_ref is None and doctor_ref is not None:
        return [str(doctor_ref), str(doctor_ref)]
    if doctor_ref is None and patient_ref is not None:
        return [str(patient_ref), str(patient_ref)]
    return [str(patient_ref), str(doctor_ref)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate WAVs from scripts.jsonl using Ming-omni-TTS.")
    parser.add_argument("--scripts-file", type=Path, default=DEFAULT_SCRIPTS_FILE)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--patient-ref-wav", type=Path, default=DEFAULT_PATIENT_REF_WAV)
    parser.add_argument("--doctor-ref-wav", type=Path, default=DEFAULT_DOCTOR_REF_WAV)
    parser.add_argument("--no-spk-emb", action="store_true", help="Do not use speaker embedding references.")
    parser.add_argument("--use-zero-spk-emb", action="store_true", help="Use zero speaker embedding when no reference WAV is provided.")
    parser.add_argument("--device", type=str, default="cuda:0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--cfg", type=float, default=2.0)
    parser.add_argument("--sigma", type=float, default=0.25)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-decode-steps", type=int, default=260)
    parser.add_argument(
        "--max-char-per-chunk",
        "--max-lines-per-chunk",
        dest="max_char_per_chunk",
        type=int,
        default=300,
        help="Maximum number of characters per generated audio chunk.",
    )
    parser.add_argument("--prompt", type=str, default=DEFAULT_PROMPT)
    parser.add_argument("--prompt-text", type=str, default=DEFAULT_PROMPT_TEXT)
    parser.add_argument("--sel-ids", type=lambda s : list(map(int, s.split(','))), default=None)
    args = parser.parse_args()

    if not args.scripts_file.exists():
        raise FileNotFoundError(f"scripts file not found: {args.scripts_file}")
    if not args.model_path.exists():
        raise FileNotFoundError(f"Model path not found: {args.model_path}")

    prompt_wav_path = None
    use_spk_emb = False
    if not args.no_spk_emb:
        patient_ref = args.patient_ref_wav if args.patient_ref_wav.exists() else None
        doctor_ref = args.doctor_ref_wav if args.doctor_ref_wav.exists() else None
        prompt_wav_path = build_prompt_wav_path(patient_ref, doctor_ref)
        use_spk_emb = prompt_wav_path is not None
        if prompt_wav_path is None:
            logger.warning("Default reference WAVs not found; generating without speaker embeddings.")
    if args.no_spk_emb:
        prompt_wav_path = None
        use_spk_emb = False
    
    print(f"{'Using speaker embeddings' if use_spk_emb else 'Not using speaker embeddings'}")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading model from: {}".format(args.model_path))
    model = MingAudio(args.model_path, device=args.device)

    entries = parse_scripts_file(args.scripts_file)
    manifest: List[Dict] = []
    
    logger.info("selected indices: {}".format(args.sel_ids))

    for script in entries:
        script_id = script.get("dialogue_id") or script.get("id") or script.get("script_id")
        if script_id is None:
            logger.warning("Skipping script with missing dialogue_id")
            continue
        if args.sel_ids is not None and script_id not in args.sel_ids :
            logger.info("Skipping script {} out of selected indices.".format(script_id))
            continue
        text = build_dialogue_text(script)
        if not text:
            logger.warning("Skipping script {} with no dialogue".format(script_id))
            continue

        entry = run_script_case(
            model=model,
            script_id=script_id,
            text=text,
            output_dir=output_dir,
            prompt=args.prompt,
            prompt_text=args.prompt_text if use_spk_emb else None,
            prompt_wav_path=prompt_wav_path,
            use_spk_emb=use_spk_emb,
            use_zero_spk_emb=args.use_zero_spk_emb,
            cfg=args.cfg,
            sigma=args.sigma,
            temperature=args.temperature,
            max_decode_steps=args.max_decode_steps,
            max_chars_per_chunk=args.max_char_per_chunk,
        )
        manifest.append(entry)

    manifest_path = output_dir / "scripts_generation_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info("Generated {} scripts. Manifest saved to {}".format(len(manifest), manifest_path))


if __name__ == "__main__":
    main()
