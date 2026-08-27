import os
import re
import sys
import json
import numpy as np
import torch
import torchaudio
from pathlib import Path
from loguru import logger
from typing import Dict, List, Optional
from transformers import AutoTokenizer

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[3]
MODEL_REPO_DIR = PROJECT_ROOT / "generation" / "models" / "ming-omni-tts"

sys.path.append(str(MODEL_REPO_DIR))
from modeling_bailingmm import BailingMMNativeForConditionalGeneration  # noqa: E402
from sentence_manager.sentence_manager import SentenceNormalizer  # noqa: E402
from spkemb_extractor import SpkembExtractor  # noqa: E402

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

def build_prompt_text(ref_txts : list[dict[str, str]]) :
    return " " + "\n ".join([f"{k}:{v}" for item in ref_txts for k, v in item.items()]) + "\n"

def _build_dialog_list(script : list[dict[str, str]]) -> list[str] :
    lines : list[str] = []
    spk_map : dict[str, int] = {}
    spk_cnt = 0
    for seg in script :
        spk = str(seg.get("speaker", ""))
        txt = seg.get("text", "")
        
        if not txt : continue
        
        if spk not in spk_map :
            spk_cnt += 1
            spk_map[spk] = spk_cnt
        spk_ky = spk_map[spk]
        
        lines.append(f"speaker_{spk_ky}: {txt}")
    return lines

def _dialog_list_to_text(lines : list[str]) -> str :
    return " " + "\n ".join(lines) + "\n" if lines else ""

def build_dialogue_text(script : list[dict[str, str]]) -> str :
    lines = _build_dialog_list(script)
    return _dialog_list_to_text(lines)

def build_dialogue_chunks(script : list[dict[str, str]], mx_chars_per_chunk : int = 300) -> list[str] :
    if mx_chars_per_chunk is None : return [build_dialogue_text(script)]
    
    lines = _build_dialog_list(script)
    chunks : list[str] = []
    
    acc_lines : list[str] = []
    acc_lens : int = 0
    
    for line in lines :
        acc_lens += len(line)
        acc_lines.append(line)
        
        if acc_lens >= mx_chars_per_chunk :
            chunks.append(_dialog_list_to_text(acc_lines))
            acc_lens = 0
            acc_lines = []
    
    if acc_lens > 0 :
        chunks.append(_dialog_list_to_text(acc_lines))
    
    return chunks