from pathlib import Path

import soundfile as sf


def get_wav_duration_seconds(wav_path: str | Path) -> float:
    info = sf.info(str(wav_path))
    if info.samplerate <= 0:
        return 0.0
    return float(info.frames) / float(info.samplerate)


def is_wav_too_long(wav_path: str | Path, max_seconds: float = 300.0) -> bool:
    return get_wav_duration_seconds(wav_path) > max_seconds


def remove_wav_if_exists(wav_path: str | Path) -> None:
    p = Path(wav_path)
    if p.exists():
        p.unlink()
