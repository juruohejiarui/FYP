# -*- coding: utf-8 -*-
"""
Qwen3-TTS voice design test suite
Goals:
1) Long text capability test
2) Same prompt, multiple sentences: voice consistency test
3) Role-based tests with explicit gender/age control via instruct
   - patient
   - doctor
   - emotion variations
   - Cantonese-flavored / Mandarin / broad-Guangpu style
"""

from pathlib import Path
import json

import soundfile as sf
import torch
from huggingface_hub import snapshot_download

# Adjust this import if your local package name differs.
from qwen_tts import Qwen3TTSModel


# =========================
# Config
# =========================
OUT_DIR = Path("qwen3_tts_role_tests")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_SIZE = "1.7B"
MODEL_TYPE = "VoiceDesign"
DEVICE_MAP = "cuda"  # change to "cpu" if needed
DTYPE = torch.bfloat16

# Official model id may vary by your environment/cache.
MODEL_PATH = f"../../models/pretrained/Qwen3-TTS-12Hz-{MODEL_SIZE}-{MODEL_TYPE}"

# Generation control
MAX_NEW_TOKENS = 4096
NON_STREAMING_MODE = True


# =========================
# Load model
# =========================
model = Qwen3TTSModel.from_pretrained(
    MODEL_PATH,
    device_map=DEVICE_MAP,
    dtype=DTYPE,
    attn_implementation="sdpa",
)


# =========================
# Helpers
# =========================
def sanitize_name(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        else:
            out.append("_")
    name = "".join(out)
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_")


def build_character_prompt(
    role: str,
    gender: str,
    age_group: str,
    emotion: str,
    language_style: str = "natural spoken Chinese",
    extra_traits: str = "",
) -> str:
    """
    Role prompt builder.
    Since the API does not expose hard gender/age knobs, we encode them in instruct.
    """
    prompt = (
        f"Speak as a {age_group} {gender} {role}. "
        f"The voice should sound {emotion}. "
        f"Use {language_style}. "
        "Keep the timbre stable and consistent across the whole utterance. "
        "Do not change the character identity halfway. "
    )
    if extra_traits.strip():
        prompt += extra_traits.strip()
        if not prompt.endswith("."):
            prompt += "."
        prompt += " "
    return prompt.strip()


def save_batch(wavs, sr: int, prefix: str, labels: list[str]):
    saved = []
    for i, wav in enumerate(wavs):
        label = sanitize_name(labels[i]) if i < len(labels) else f"sample_{i+1}"
        path = OUT_DIR / f"{prefix}_{i+1:02d}_{label}.wav"
        sf.write(str(path), wav, sr)
        saved.append(str(path))
    return saved


def gen_and_save(batch_name: str, texts: list[str], languages: list[str], instructs: list[str]):
    assert len(texts) == len(languages) == len(instructs), "texts/languages/instructs must have the same length"

    wavs, sr = model.generate_voice_design(
        text=texts,
        language=languages,
        instruct=instructs,
        non_streaming_mode=NON_STREAMING_MODE,
        max_new_tokens=MAX_NEW_TOKENS,
    )

    labels = [f"{batch_name}_{i+1}" for i in range(len(texts))]
    saved_files = save_batch(wavs, sr, batch_name, labels)

    manifest = []
    for i in range(len(texts)):
        manifest.append({
            "index": i + 1,
            "batch": batch_name,
            "language": languages[i],
            "text": texts[i],
            "instruct": instructs[i],
            "wav_path": saved_files[i],
        })

    with open(OUT_DIR / f"{batch_name}_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[{batch_name}] saved {len(saved_files)} files, sr={sr}")
    for p in saved_files:
        print("  -", p)


# =========================
# 1) Full long-text test
# =========================
# This is a single long, complete test sample. You can make it even longer if needed.
long_patient_text = (
    "医生，我今天想把情况完整说一下。"
    "大概从两周前开始，我就觉得胸口偶尔会闷，尤其是晚上躺下以后比较明显。"
    "白天工作的时候虽然也会想起这个问题，但因为事情多，注意力会被分散，所以感觉没有那么强烈。"
    "不过一到晚上安静下来，我就会开始担心，是不是心脏、肺，或者别的地方出了问题。"
    "前几天我还特意量了一下血压，有时候会偏高一点，但也不是每次都高。"
    "我也在记心率，快的时候会有点心慌，慢下来的时候又会稍微安心一些。"
    "我之前按您说的先观察了一下，尽量早点睡觉，少喝咖啡，也减少了熬夜。"
    "但效果不太稳定，有时候会好一点，有时候又会反复。"
    "所以我今天来主要是想确认一下，现在这种情况是不是还需要继续观察，还是应该马上做进一步检查。"
    "如果需要做心电图、胸片或者其他检查，我这周都可以安排时间。"
    "我也想确认一下之前开的药是不是继续吃，剂量要不要调整。"
    "还有一个我比较担心的问题是，药物会不会影响白天工作，比如犯困、胃不舒服，或者和我平时吃的东西有冲突。"
    "总之我不是特别严重地不舒服，但因为它一直反复，所以我还是有点焦虑。"
    "我希望您帮我判断一下，接下来最稳妥的处理方式是什么。"
)

long_doctor_text = (
    "从你刚才描述的情况来看，我们先不要自己过度联想最严重的情况。"
    "目前更重要的是把症状、时间、诱因和伴随表现梳理清楚。"
    "如果胸闷主要发生在休息后、夜间，或者和情绪、睡眠、咖啡因摄入有关，那么它不一定代表严重器质性问题。"
    "但是因为你提到它持续了两周，而且有反复出现的趋势，我们还是建议做一些基础检查，先把风险排除掉。"
    "通常我们会先看血压、心率、心电图，有需要的话再结合胸片、血常规或者其他化验结果一起判断。"
    "如果检查结果没有提示明显异常，那么后续就可以更多从睡眠、压力、生活方式和症状管理的角度去处理。"
    "如果结果提示存在问题，我们再根据具体情况决定是否需要调整药物或者进一步转诊。"
    "在没有明确结论之前，你先按之前的方案观察，同时注意记录发作时间、持续时长、是否伴随气短、胸痛、出汗或者头晕。"
    "这些信息对后面判断非常重要。"
    "如果出现明显加重，或者胸痛持续不缓解，就不要等复诊，及时来医院。"
)

gen_and_save(
    batch_name="long_text_patient",
    texts=[long_patient_text],
    languages=["Chinese"],
    instructs=[
        build_character_prompt(
            role="patient",
            gender="female",
            age_group="young adult",
            emotion="anxious but controlled",
            language_style="natural Mandarin with slight Cantonese-influenced spoken feel",
        )
    ],
)

gen_and_save(
    batch_name="long_text_doctor",
    texts=[long_doctor_text],
    languages=["Chinese"],
    instructs=[
        build_character_prompt(
            role="doctor",
            gender="male",
            age_group="middle-aged",
            emotion="calm, professional, and confident",
            language_style="clear standard Mandarin with medical professionalism",
        )
    ],
)


# =========================
# 2) Same prompt, multiple sentences
#    Test voice consistency across different texts
# =========================
same_prompt_patient = build_character_prompt(
    role="patient",
    gender="female",
    age_group="young adult",
    emotion="nervous but fluent",
    language_style="natural Mandarin",
)

same_prompt_doctor = build_character_prompt(
    role="doctor",
    gender="male",
    age_group="middle-aged",
    emotion="slightly tired but still professional",
    language_style="standard Mandarin",
)

same_prompt_patient_texts = [
    "医生，我今天来复诊，主要是想确认一下上次开的药要不要继续吃。",
    "我昨天晚上有一点不舒服，不过今天早上又好了一些。",
    "如果没有大问题，我就按照之前的方案先观察两天。",
    "我比较担心的是副作用，所以想再问清楚一点。",
    "这个检查结果是不是说明情况已经稳定了？",
]

same_prompt_doctor_texts = [
    "先别急，我们先把检查结果和症状对应起来看。",
    "从目前的信息判断，还不能直接下结论。",
    "如果症状继续反复，我们再考虑下一步调整方案。",
    "这个药物一般来说耐受性还可以，但还是要看个体反应。",
    "你先按今天说的方式记录一下，复诊时带过来给我看。",
]

gen_and_save(
    batch_name="same_prompt_patient_multi_sentence",
    texts=same_prompt_patient_texts,
    languages=["Chinese"] * len(same_prompt_patient_texts),
    instructs=[same_prompt_patient] * len(same_prompt_patient_texts),
)

gen_and_save(
    batch_name="same_prompt_doctor_multi_sentence",
    texts=same_prompt_doctor_texts,
    languages=["Chinese"] * len(same_prompt_doctor_texts),
    instructs=[same_prompt_doctor] * len(same_prompt_doctor_texts),
)


# =========================
# 3) Role test set with explicit gender/age
#    patient / doctor, emotion variations, Cantonese-flavored style
# =========================
role_test_cases = [
    {
        "batch_name": "patient_female_young_anxious",
        "text": "医生，我有点担心这个药会不会伤胃，所以想再确认一下。",
        "language": "Chinese",
        "gender": "female",
        "age_group": "young adult",
        "role": "patient",
        "emotion": "anxious and cautious",
        "style": "natural Mandarin",
    },
    {
        "batch_name": "patient_male_middle_stuck",
        "text": "我、我就是想问一下，这个检查是不是一定要今天做？",
        "language": "Chinese",
        "gender": "male",
        "age_group": "middle-aged",
        "role": "patient",
        "emotion": "worried with hesitations and short pauses",
        "style": "natural spoken Mandarin",
    },
    {
        "batch_name": "patient_female_elderly_calm",
        "text": "好的，那我就按照您刚才说的方案继续观察几天。",
        "language": "Chinese",
        "gender": "female",
        "age_group": "elderly",
        "role": "patient",
        "emotion": "calm, cooperative, and slightly relieved",
        "style": "clear Mandarin",
    },
    {
        "batch_name": "patient_cantonese_flavored",
        "text": "医生，我都系有少少担心，想问下呢个药要食几耐先得？",
        "language": "Chinese",
        "gender": "female",
        "age_group": "young adult",
        "role": "patient",
        "emotion": "slightly worried, conversational, Cantonese-flavored",
        "style": "spoken Cantonese-flavored Mandarin",
    },
    {
        "batch_name": "doctor_male_middle_tired",
        "text": "你这个情况我先帮你排一下风险，先做心电图和血压复查，再看需不需要调整药物。",
        "language": "Chinese",
        "gender": "male",
        "age_group": "middle-aged",
        "role": "doctor",
        "emotion": "tired but professional",
        "style": "clear medical Mandarin",
    },
    {
        "batch_name": "doctor_female_middle_energetic",
        "text": "从目前描述来看，我们先按规范做检查，重点排除感染、过敏和药物不良反应。",
        "language": "Chinese",
        "gender": "female",
        "age_group": "middle-aged",
        "role": "doctor",
        "emotion": "energetic, attentive, and precise",
        "style": "standard Mandarin with medical authority",
    },
    {
        "batch_name": "doctor_cantonese_style",
        "text": "你而家先唔好太担心，我哋会先睇检查结果，再决定需唔需要改治疗方案。",
        "language": "Chinese",
        "gender": "male",
        "age_group": "middle-aged",
        "role": "doctor",
        "emotion": "calm, reassuring, and professional",
        "style": "Cantonese-flavored doctor speech",
    },
]

for case in role_test_cases:
    instruct = build_character_prompt(
        role=case["role"],
        gender=case["gender"],
        age_group=case["age_group"],
        emotion=case["emotion"],
        language_style=case["style"],
    )
    gen_and_save(
        batch_name=case["batch_name"],
        texts=[case["text"]],
        languages=[case["language"]],
        instructs=[instruct],
    )


# =========================
# 4) Optional: one mixed batch for blind listening
#    Same gender/age, different emotions and roles
# =========================
blind_test_texts = [
    "医生，我今天有点紧张，想先问清楚再决定要不要做检查。",
    "没问题，我们先把情况梳理一下，慢慢来。",
    "我听懂了，那我先按您说的做。",
    "如果后面还有不舒服，我再尽快回来复诊。",
]

blind_test_instructs = [
    build_character_prompt(
        role="patient",
        gender="female",
        age_group="young adult",
        emotion="anxious",
        language_style="natural spoken Mandarin",
    ),
    build_character_prompt(
        role="doctor",
        gender="male",
        age_group="middle-aged",
        emotion="calm and reassuring",
        language_style="standard Mandarin",
    ),
    build_character_prompt(
        role="patient",
        gender="female",
        age_group="young adult",
        emotion="relieved and cooperative",
        language_style="natural Mandarin",
    ),
    build_character_prompt(
        role="patient",
        gender="female",
        age_group="young adult",
        emotion="slightly worried but composed",
        language_style="natural Mandarin",
    ),
]

gen_and_save(
    batch_name="blind_mix_test",
    texts=blind_test_texts,
    languages=["Chinese"] * len(blind_test_texts),
    instructs=blind_test_instructs,
)

print(f"\nAll done. WAV files are saved in: {OUT_DIR.resolve()}")