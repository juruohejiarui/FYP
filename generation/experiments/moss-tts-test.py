import os
import sys
from pathlib import Path
import torch
import soundfile as sf
import torchaudio
from transformers import AutoModel, AutoProcessor

THIS_FILE = Path(__file__).resolve()
PROJECT_PATH = THIS_FILE.parents[2]
MODEL_WEIGHT_PATH = PROJECT_PATH / "models" / "pretrained" / "TTS"
MODEL_CODE_PATH = PROJECT_PATH / "generation" / "models" / "moss-ttsd"

sys.path.append(str(MODEL_CODE_PATH))

pretrained_model_name_or_path = MODEL_WEIGHT_PATH / "MOSS-TTSD-v1.0"
audio_tokenizer_name_or_path = MODEL_WEIGHT_PATH / "MOSS-Audio-Tokenizer"
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.bfloat16 if device == "cuda" else torch.float32

processor = AutoProcessor.from_pretrained(
    pretrained_model_name_or_path,
    trust_remote_code=True,
    codec_path=audio_tokenizer_name_or_path,
)
processor.audio_tokenizer = processor.audio_tokenizer.to(device)
processor.audio_tokenizer.eval()

attn_implementation = "flash_attention_2" if device == "cuda" else "sdpa"
# If flash_attention_2 is unavailable on your environment, set this to "sdpa".
model = AutoModel.from_pretrained(
    pretrained_model_name_or_path,
    trust_remote_code=True,
    attn_implementation=attn_implementation,
    dtype=dtype,
).to(device)
model.eval()

# --- Inputs ---

prompt_audio_speaker1 = MODEL_CODE_PATH / "asset" / "reference_02_s1.wav"
prompt_audio_speaker2 = MODEL_CODE_PATH / "asset" / "reference_02_s2.wav"
prompt_text_speaker1 = "[S1] In short, we embarked on a mission to make America great again for all Americans."
prompt_text_speaker2 = "[S2] NVIDIA reinvented computing for the first time after 60 years. In fact, Erwin at IBM knows quite well that the computer has largely been the same since the 60s."

text_to_generate = """
[S1] Listen, let's talk business. China. I'm hearing things.
People are saying they're catching up. Fast. What's the real scoop?
Their AI—is it a threat?
[S2] Well, the pace of innovation there is extraordinary, honestly.
They have the researchers, and they have the drive.
[S1] Extraordinary? I don't like that. I want us to be extraordinary.
Are they winning?
[S2] I wouldn't say winning, but their progress is very promising.
They are building massive clusters. They're very determined.
[S1] Promising. There it is. I hate that word.
When China is promising, it means we're losing.
It's a disaster, Jensen. A total disaster.
""".strip()

# --- Load & resample audio ---

target_sr = int(processor.model_config.sampling_rate)
audio1, sr1 = sf.read(prompt_audio_speaker1, dtype="float32", always_2d=True)
audio2, sr2 = sf.read(prompt_audio_speaker2, dtype="float32", always_2d=True)
wav1 = torch.from_numpy(audio1).transpose(0, 1).contiguous()
wav2 = torch.from_numpy(audio2).transpose(0, 1).contiguous()

if wav1.shape[0] > 1:
    wav1 = wav1.mean(dim=0, keepdim=True)
if wav2.shape[0] > 1:
    wav2 = wav2.mean(dim=0, keepdim=True)
if sr1 != target_sr:
    wav1 = torchaudio.functional.resample(wav1, sr1, target_sr)
if sr2 != target_sr:
    wav2 = torchaudio.functional.resample(wav2, sr2, target_sr)

# --- Build conversation ---

reference_audio_codes = processor.encode_audios_from_wav([wav1, wav2], sampling_rate=target_sr)
concat_prompt_wav = torch.cat([wav1, wav2], dim=-1)
prompt_audio = processor.encode_audios_from_wav([concat_prompt_wav], sampling_rate=target_sr)[0]

full_text = f"{prompt_text_speaker1} {prompt_text_speaker2} {text_to_generate}"

conversations = [
    [
        processor.build_user_message(
            text=full_text,
            reference=reference_audio_codes,
        ),
        processor.build_assistant_message(
            audio_codes_list=[prompt_audio]
        ),
    ],
]

# --- Inference ---

batch_size = 1

save_dir = Path("output")
save_dir.mkdir(exist_ok=True, parents=True)
sample_idx = 0
with torch.no_grad():
    for start in range(0, len(conversations), batch_size):
        batch_conversations = conversations[start : start + batch_size]
        batch = processor(batch_conversations, mode="continuation")
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)

        outputs = model.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            max_new_tokens=2000,
        )

        for message in processor.decode(outputs):
            for seg_idx, audio in enumerate(message.audio_codes_list):
                sf.write(
                    save_dir / f"{sample_idx}_{seg_idx}.wav",
                    audio.detach().cpu().to(torch.float32).numpy(),
                    int(processor.model_config.sampling_rate),
                )
            sample_idx += 1
