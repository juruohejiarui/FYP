import soundfile as sf
import torch
import torchaudio
from pathlib import Path
from tqdm import tqdm
from transformers import AutoModel, AutoProcessor

from ref.utils import RefEntry


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
