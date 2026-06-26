#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ming-omni-TTS experiment script for realistic clinic-dialogue style tests.

What this script covers:
1) Long-text stability test
2) Same prompt, multiple sentences -> voice consistency test
3) Role/emotion variations:
   - patient: fluent / hesitant / calm / anxious
   - doctor: tired / energetic / professional / warm
   - Cantonese-flavored / broad-Guangpu / Mandarin
4) Optional podcast-style multi-speaker test if the cookbook reference WAVs exist

Model path:
    ../../models/pretrained/Ming-omni-tts-0.5B
from generation/experiments/ming-tts.py

Notes:
- Ming's cookbook shows the podcast case uses speaker_1/speaker_2 text format and multiple reference audios.
- This script keeps the same overall usage pattern as the cookbook's `speech_generation(...)`.
"""

import json
import os
import random
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

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]  # .../generation/experiments -> project root
MODEL_REPO_DIR = PROJECT_ROOT / "generation" / "models" / "ming-omni-tts"
MODEL_PATH = PROJECT_ROOT / "models" / "pretrained" / "Ming-omni-tts-0.5B"
OUTPUT_DIR = THIS_FILE.parent / "ming_tts_tests"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Add local model repo to sys.path so cookbook modules can be imported.
sys.path.append(str(MODEL_REPO_DIR))

from modeling_bailingmm import BailingMMNativeForConditionalGeneration  # noqa: E402
from sentence_manager.sentence_manager import SentenceNormalizer  # noqa: E402
from spkemb_extractor import SpkembExtractor  # noqa: E402

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------
def seed_everything(seed: int = 1895) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


seed_everything()


# ---------------------------------------------------------------------
# Cookbook-like template
# ---------------------------------------------------------------------
BASE_CAPTION_TEMPLATE = {
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

DEFAULT_PROMPT = "Please generate speech based on the following description.\n"
CONVERSATIONAL_PROMPT = (
    "Please generate natural conversational speech in Mandarin Chinese. "
    "Make it sound like an everyday clinic dialogue, with natural pauses and no announcer or drama tone.\n"
)



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
            self.tokenizer = AutoTokenizer.from_pretrained(".", trust_remote_code=True)

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

    def create_instruction(self, user_input: Dict):
        new_caption = json.loads(json.dumps(BASE_CAPTION_TEMPLATE, ensure_ascii=False))
        target_item_dict = new_caption["audio_sequence"][0]

        for key, value in user_input.items():
            if key in target_item_dict:
                target_item_dict[key] = value

        if target_item_dict["BGM"].get("SNR", None) is not None:
            new_order = ["序号", "说话人", "BGM", "情感", "方言", "风格", "语速", "基频", "音量", "IP"]
            target_item_dict = {k: target_item_dict[k] for k in new_order if k in target_item_dict}
            new_caption["audio_sequence"][0] = target_item_dict

        return new_caption

    def pad_waveform(self, waveform: torch.Tensor) -> torch.Tensor:
        # Pad to patch alignment
        pad_align = int(1 / 12.5 * self.patch_size * self.sample_rate)
        new_len = (waveform.size(-1) + pad_align - 1) // pad_align * pad_align
        if new_len != waveform.size(1):
            new_wav = torch.zeros(1, new_len, dtype=waveform.dtype, device=waveform.device)
            new_wav[:, :waveform.size(1)] = waveform.clone()
            waveform = new_wav
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

    def generation(self, prompt: str, text: str, max_decode_steps: int = 200):
        return self.model.generate_text(
            prompt=prompt,
            text=text,
            max_decode_steps=max_decode_steps,
        )


# ---------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------
def safe_name(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] if text else "sample"


def write_manifest(name: str, entries: List[Dict]) -> None:
    path = OUTPUT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def make_instruction(
    role: str,
    gender: str,
    age_group: str,
    emotion: str,
    dialect: Optional[str] = None,
    style_extra: Optional[str] = None,
    rate: Optional[str] = None,
    pitch: Optional[str] = None,
    volume: Optional[str] = None,
    ip: Optional[str] = None,
) -> Dict:
    """
    Ming's instruction fields are caption-like Chinese keys.
    We encode age/gender in `风格`, while using `情感/方言/语速/基频/音量/IP`
    for controllable attributes that the cookbook already demonstrates.
    """
    parts = [f"{age_group}的{gender}{role}", f"情感上呈现{emotion}"]
    if style_extra:
        parts.append(style_extra)
    style = "，".join(parts)

    ins: Dict[str, object] = {"风格": style}
    if dialect:
        ins["方言"] = dialect
    if rate:
        ins["语速"] = rate
    if pitch:
        ins["基频"] = pitch
    if volume:
        ins["音量"] = volume
    if ip:
        ins["IP"] = ip
    return ins


def run_case(
    model: MingAudio,
    case_name: str,
    text: str,
    *,
    prompt: str = DEFAULT_PROMPT,
    instruction: Optional[Dict] = None,
    use_spk_emb: bool = False,
    use_zero_spk_emb: bool = False,
    prompt_wav_path=None,
    prompt_text: Optional[str] = None,
    max_decode_steps: int = 200,
    cfg: float = 2.0,
    sigma: float = 0.25,
    temperature: float = 0.0,
) -> Dict:
    out_path = OUTPUT_DIR / f"{case_name}.wav"
    logger.info(f"Generating: {case_name}")
    model.speech_generation(
        prompt=prompt,
        text=text,
        use_spk_emb=use_spk_emb,
        use_zero_spk_emb=use_zero_spk_emb,
        instruction=instruction,
        prompt_wav_path=prompt_wav_path,
        prompt_text=prompt_text,
        max_decode_steps=max_decode_steps,
        cfg=cfg,
        sigma=sigma,
        temperature=temperature,
        output_wav_path=str(out_path),
    )
    logger.info(f"Saved: {out_path}")
    return {
        "case_name": case_name,
        "text": text,
        "instruction": instruction,
        "prompt_wav_path": prompt_wav_path,
        "prompt_text": prompt_text,
        "output_wav_path": str(out_path),
    }


def run_multi_sentence_consistency(
    model: MingAudio,
    group_name: str,
    texts: List[str],
    instruction: Dict,
    *,
    prompt: str = DEFAULT_PROMPT,
    use_zero_spk_emb: bool = True,
    max_decode_steps: int = 200,
    cfg: float = 2.0,
    sigma: float = 0.25,
    temperature: float = 0.0,
) -> List[Dict]:
    entries = []
    for idx, text in enumerate(texts, 1):
        case_name = f"{group_name}_{idx:02d}_{safe_name(text)}"
        entries.append(
            run_case(
                model,
                case_name,
                text,
                prompt=prompt,
                instruction=instruction,
                use_zero_spk_emb=use_zero_spk_emb,
                max_decode_steps=max_decode_steps,
                cfg=cfg,
                sigma=sigma,
                temperature=temperature,
            )
        )
    write_manifest(group_name, entries)
    return entries


def maybe_run_podcast_case(model: MingAudio) -> Optional[Dict]:
    """
    Optional podcast-style multi-speaker test.
    This follows the cookbook's `speaker_1/speaker_2` text format and uses two
    reference audios if they are available in the repo checkout.
    """
    ref_a = MODEL_REPO_DIR / "data" / "wavs" / "CTS-CN-F2F-2019-11-11-423-012-A.wav"
    ref_b = MODEL_REPO_DIR / "data" / "wavs" / "CTS-CN-F2F-2019-11-11-423-012-B.wav"

    if not ref_a.exists() or not ref_b.exists():
        logger.warning("Podcast refs not found; skipping podcast-style test.")
        return None

    dialog_text = (
        " speaker_1:医生，我最近总觉得胸口有点闷，尤其晚上躺下以后更明显。"
        "不过白天忙起来的时候又没那么明显，所以我有点拿不准。\n"
        " speaker_2:嗯，先别急。这个情况大概持续多久了？"
        "有没有伴随气短、心慌，或者说活动后更重？\n"
        " speaker_1:大概两周了。不是一直都很重，但反反复复的，"
        "有时候我会忍不住去想是不是哪里出问题了。\n"
        " speaker_2:好，我先把重点给你捋一下："
        "先做心电图和血压复查，再看需不需要进一步检查。\n"
        " speaker_1:嗯，明白。那我之前开的药还要继续吃吗？"
        "我有点担心会不会犯困，或者影响上班。\n"
        " speaker_2:先按原方案观察，药物如果有不舒服再回来调整。"
        "你先把发作时间和症状记下来，复诊时带给我。\n"
        " speaker_1:好，那我今天就去安排检查。谢谢医生。\n"
    )

    prompt_diag = [
        {"speaker_1": "并且我们还要进行每个月还要考核 笔试的话还要进行笔试，做个，当服务员还要去笔试了"},
        {"speaker_2": "对啊，这真的很奇怪，就是 单纯的因，单纯自己工资不高，只是因为可能人家那个店比较出名一点，就对你苛刻要求"},
    ]
    prompt_text = " " + "\n ".join([f"{k}:{v}" for item in prompt_diag for k, v in item.items()]) + "\n"

    entry = run_case(
        model,
        "podcast_like_real_dialogue",
        dialog_text,
        prompt=DEFAULT_PROMPT,
        instruction=None,
        use_spk_emb=True,
        prompt_wav_path=[str(ref_a), str(ref_b)],
        prompt_text=prompt_text,
        max_decode_steps=200,
        cfg=2.0,
        sigma=0.25,
        temperature=0.2,
    )
    return entry


def maybe_run_podcast_colloquial_case(model: MingAudio) -> Optional[Dict]:
    """
    New test: highly colloquial clinic dialogue (no reference audios).
    Produces a podcast-like short dialogue with natural fillers, hesitations
    and conversational pacing similar to the `test.py` example.
    """

    ref_a = MODEL_REPO_DIR / "data" / "wavs" / "CTS-CN-F2F-2019-11-11-423-012-A.wav"
    ref_b = MODEL_REPO_DIR / "data" / "wavs" / "CTS-CN-F2F-2019-11-11-423-012-B.wav"

    prompt_diag = [
        {"speaker_1": "并且我们还要进行每个月还要考核 笔试的话还要进行笔试，做个，当服务员还要去笔试了"},
        {"speaker_2": "对啊，这真的很奇怪，就是 单纯的因，单纯自己工资不高，只是因为可能人家那个店比较出名一点，就对你苛刻要求"},
    ]
    prompt_text = " " + "\n ".join([f"{k}:{v}" for item in prompt_diag for k, v in item.items()]) + "\n"

    dialog = [
        {"speaker_1": "啊医生，你好。"},
        {"speaker_2": "你好你好。有什么不舒服吗？"},
        {"speaker_1": "我这几天胸口总是有点闷，偶尔还有点心慌，挺烦的。"},
        {"speaker_2": "嗯好的。具体什么时候开始的，有没有别的症状？"},
        {"speaker_1": "大概，唔，两周吧，晚上躺下就明显，白天忙就好很多。"},
        {"speaker_2": "有没有胸痛、头晕或者出汗之类的？"},
        {"speaker_1": "胸痛，呃，没有胸痛，就是，就是有点闷，有时候会喘不过气来，尤其爬楼就明显。"},
        {"speaker_2": "好，那我们先做个心电图和血压检查，顺便把用药情况告诉我。"},
        {"speaker_1": "之前开的药我还在吃，但是我担心会不会太困，影响上班。"},
        {"speaker_2": "如果药物影响明显，我们可以换药或者调整剂量，你先把最近几次感觉记录下来。"},
        {"speaker_1": "好的好的，我会记的，谢谢。"},
    ]

    text = " " + "\n ".join([f"{k}:{v}" for item in dialog for k, v in item.items()]) + "\n"

    instruction = {
        "风格": "非常口语化，包含口头语、犹豫和短促停顿，像真实门诊对话，不要像播音员。"
    }

    entry = run_case(
        model,
        "podcast_colloquial",
        text,
        prompt=CONVERSATIONAL_PROMPT,
        # prompt=DEFAULT_PROMPT,
        use_spk_emb=True,
        prompt_wav_path=[str(ref_a), str(ref_b)],
        prompt_text=prompt_text,
        # instruction=instruction,
        max_decode_steps=200,
        cfg=2.0,
        sigma=0.25,
    )
    return entry


# ---------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------
def main():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model path not found: {MODEL_PATH}")

    logger.info(f"Loading model from: {MODEL_PATH}")
    model = MingAudio(MODEL_PATH, device="cuda:0" if torch.cuda.is_available() else "cpu")

    # 1) Long-text capability tests
    long_patient_text = (
        "医生，我这几天老觉得胸口有点闷。白天忙起来还好，一静下来就感觉不太舒服。"
        "前几天我量过血压，有时候有点高，但也不是每次都高。"
        "我也注意睡得早一点、少喝咖啡、少熬夜，结果有时候好一点，有时候又反复。"
        "所以我今天就是想问问，这种情况是不是先继续观察，还是得做点检查？"
        "比如心电图、胸片，还是先按原来的药吃着？"
        "我还有点担心这药会不会影响我白天上班，犯困、胃不舒服，或者和吃的东西冲突。"
        "总之不是特别难受，但一直反复，所以我有点不安，想听您怎么说比较稳妥。"
        "要是您觉得先观察也可以，我这周会再记录一下症状，看看有没有更明显的规律。"
    )

    long_doctor_text = (
        "嗯，我听你这么说，先别往最严重的方向想。"
        "现在我们要把你这几天的症状、发生时间和伴随情况捋清楚。"
        "比如晚上躺下以后闷，是不是还有心慌、头晕、出汗，或者活动后更明显？"
        "你这两周反复出现，我们还是建议先做一些基础检查，先把风险排除掉。"
        "一般先看血压、心率、心电图，必要时再加个胸片、血常规。"
        "如果检查没什么异常，后面主要从睡眠、压力、生活方式方面调整就可以了。"
        "要是结果提示有点问题，再看需不需要调整药物或者进一步转诊。"
        "现在这个阶段，你就先按原来的方案观察，注意记一下发作时间、持续多久，和有没有气短、胸痛或者头晕。"
        "要是胸痛明显不缓解，就别拖，及时来医院。"
    )

    long_cases = [
        (
            "long_text_patient",
            long_patient_text,
            make_instruction(
                role="患者",
                gender="女性",
                age_group="年轻",
                emotion="有点不安,虚弱,说话慢，像真实患者向医生描述情况",
                style_extra="口语化、停顿多，像和医生聊天，别像主持人或电视剧台词",
                rate="自然",
            ),
            0.7,
        ),
        (
            "long_text_doctor",
            long_doctor_text,
            make_instruction(
                role="医生",
                gender="男性",
                age_group="中年",
                emotion="耐心、平稳，语气亲切、不夸张",
                style_extra="像门诊医生给病人解释，不是戏剧化演绎",
                rate="自然",
            ),
            0.6,
        ),
    ]

    long_manifest = []
    for case_name, text, instruction, temp in long_cases:
        long_manifest.append(
            run_case(
                model,
                case_name,
                text,
                prompt=CONVERSATIONAL_PROMPT,
                instruction=instruction,
                use_zero_spk_emb=True,
                max_decode_steps=320,
                cfg=2.0,
                sigma=0.25,
                temperature=temp,
            )
        )
    write_manifest("long_text_suite", long_manifest)

    # 2) Same prompt, multiple sentences
    patient_instruction = make_instruction(
        role="患者",
        gender="女性",
        age_group="年轻",
        emotion="紧张但流利，像真实复诊病人",
        style_extra="轻微广普口语感，句子自然、真实、不要像电视剧",
    )
    doctor_instruction = make_instruction(
        role="医生",
        gender="男性",
        age_group="中年",
        emotion="专业、温和、略疲惫但清楚",
        style_extra="门诊场景口吻，短句更自然",
    )

    patient_texts = [
        "医生，我今天来复诊，主要是想确认一下上次开的药要不要继续吃。",
        "我昨天晚上有一点不舒服，不过今天早上又好了一些。",
        "如果没有大问题，我就按照之前的方案先观察两天。",
        "我比较担心的是副作用，所以想再问清楚一点。",
        "这个检查结果是不是说明情况已经稳定了？",
    ]

    doctor_texts = [
        "先别急，我们先把检查结果和症状对应起来看。",
        "从目前的信息判断，还不能直接下结论。",
        "如果症状继续反复，我们再考虑下一步调整方案。",
        "这个药物一般来说耐受性还可以，但还是要看个体反应。",
        "你先按今天说的方式记录一下，复诊时带过来给我看。",
    ]

    run_multi_sentence_consistency(
        model,
        "same_prompt_patient_multi_sentence",
        patient_texts,
        patient_instruction,
        use_zero_spk_emb=True,
        max_decode_steps=180,
        temperature=0.15,
    )
    run_multi_sentence_consistency(
        model,
        "same_prompt_doctor_multi_sentence",
        doctor_texts,
        doctor_instruction,
        use_zero_spk_emb=True,
        max_decode_steps=180,
        temperature=0.15,
    )
    # 3) Role / emotion / dialect variation suite
    role_cases = [
        {
            "case_name": "patient_female_young_anxious",
            "text": "医生，我有点担心这个药会不会伤胃，所以想再确认一下。",
            "instruction": make_instruction(
                role="患者",
                gender="女性",
                age_group="年轻",
                emotion="焦虑、谨慎、但说话比较流利",
                style_extra="自然普通话，带一点点吞音和口语停顿",
                rate="自然，稍慢",
            ),
            "temperature": 0.55,
        },
        {
            "case_name": "patient_male_middle_stuck",
            "text": "我、我就是想问一下，这个检查是不是一定要今天做？",
            "instruction": make_instruction(
                role="患者",
                gender="男性",
                age_group="中年",
                emotion="担心、卡壳、略显犹豫",
                style_extra="中间可以有轻微停顿感，不要过度夸张",
            ),
            "temperature": 0.65,
        },
        {
            "case_name": "patient_female_elderly_calm",
            "text": "好的，那我就按照您刚才说的方案继续观察几天。",
            "instruction": make_instruction(
                role="患者",
                gender="女性",
                age_group="老年",
                emotion="平静、配合、稍微放心",
                style_extra="说话慢一点，清楚一点",
            ),
            "temperature": 0.35,
        },
        {
            "case_name": "patient_cantonese_flavored",
            "text": "医生，我都系有少少担心，想问下呢个药要食几耐先得？",
            "instruction": make_instruction(
                role="患者",
                gender="女性",
                age_group="年轻",
                emotion="有一点担心，偏口语化，粤语味更自然",
                dialect="广粤话",
                style_extra="更像香港门诊里的患者说话，不要太播音",
            ),
            "temperature": 0.55,
        },
        {
            "case_name": "doctor_male_middle_tired",
            "text": "你这个情况我先帮你排一下风险，先做心电图和血压复查，再看需不需要调整药物。",
            "instruction": make_instruction(
                role="医生",
                gender="男性",
                age_group="中年",
                emotion="疲惫但仍然专业，有点忙但保持耐心",
                style_extra="门诊语气，简洁、清楚、可信",
            ),
            "temperature": 0.45,
        },
        {
            "case_name": "doctor_female_middle_energetic",
            "text": "从目前描述来看，我们先按规范做检查，重点排除感染、过敏和药物不良反应。",
            "instruction": make_instruction(
                role="医生",
                gender="女性",
                age_group="中年",
                emotion="精神好、条理清楚、比较有亲和力",
                style_extra="像经验丰富的门诊医生，语气不死板",
            ),
            "temperature": 0.45,
        },
        {
            "case_name": "doctor_broad_guangpu_warm",
            "text": "你而家先唔好太担心，我哋会先睇检查结果，再决定需唔需要改治疗方案。",
            "instruction": make_instruction(
                role="医生",
                gender="男性",
                age_group="中年",
                emotion="温和、安抚、自然",
                style_extra="广普口语感，轻微粤语腔，但保持专业",
                dialect="广粤话",
            ),
            "temperature": 0.55,
        },
        {
            "case_name": "doctor_soft_persuasive",
            "text": "你先按今天的方案试两天，如果还是不舒服，我们再看下一步怎么处理。",
            "instruction": make_instruction(
                role="医生",
                gender="男性",
                age_group="青年到中年",
                emotion="柔和、会安抚人、略带说服力",
                style_extra="不要夸张表演，要像真实劝导病人的医生",
            ),
            "temperature": 0.5,
        },
    ]

    role_manifest = []
    for case in role_cases:
        role_manifest.append(
            run_case(
                model,
                case["case_name"],
                case["text"],
                instruction=case["instruction"],
                use_zero_spk_emb=True,
                max_decode_steps=200,
                cfg=2.0,
                sigma=0.25,
                temperature=case["temperature"],
            )
        )
    write_manifest("role_emotion_suite", role_manifest)

    # 4) Optional podcast-style test with reference audios
    podcast_entry = maybe_run_podcast_case(model)
    if podcast_entry is not None:
        write_manifest("podcast_like_real_dialogue", [podcast_entry])
        
    podcast_colloquial_case = maybe_run_podcast_colloquial_case(model)
    if podcast_colloquial_case is not None :
        write_manifest("podcast_colloquial_case", [podcast_colloquial_case])

    logger.info(f"All done. Outputs are under: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()