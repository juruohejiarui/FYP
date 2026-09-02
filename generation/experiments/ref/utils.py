from pydub import AudioSegment
from pathlib import Path
import json
import os
import random

REF_DIR = Path(__file__).parents[1] / "data" / "ref"

# Speech-friendly peak targets:
# - If the clip peak is below -12 dBFS, boost it.
# - Boost until peak reaches -6 dBFS.
MIN_PEAK_DBFS = -12.0
TARGET_PEAK_DBFS = -6.0

def name(meta : dict[str, str]) -> str :
    return f"{meta['language']}_{meta['gender']}_{meta['id']}"

def generate(audio : AudioSegment, chunks : list[tuple[float, float, str]]) -> tuple[AudioSegment, str]:
    output = AudioSegment.empty()
    silence = AudioSegment.silent(duration=0)
    
    text = ""
    
    for chunk in chunks :
        st, ed = int(chunk[0] * 1000), int(chunk[1] * 1000)
        
        seg = audio[st : ed]
        
        text += chunk[2]
        
        output += seg
        output += silence
    
    return output, text


def amplify_if_too_quiet(
    audio: AudioSegment,
    min_peak_dbfs: float = MIN_PEAK_DBFS,
    target_peak_dbfs: float = TARGET_PEAK_DBFS,
) -> AudioSegment:
    """Boost audio only when peak level is too low.

    pydub peak uses dBFS where 0 is full scale and lower values are quieter.
    """
    if len(audio) == 0:
        return audio

    peak_dbfs = audio.max_dBFS
    if peak_dbfs == float("-inf"):
        return audio

    if peak_dbfs < min_peak_dbfs:
        gain_db = target_peak_dbfs - peak_dbfs
        return audio.apply_gain(gain_db)

    return audio
        
def export(audio : AudioSegment, meta : dict[str, str]) :
    audio = amplify_if_too_quiet(audio)
    audio.export(str(REF_DIR / name(meta)) + ".wav", format='wav')
    
    with open(str(REF_DIR / name(meta)) + ".json", 'w') as f :
        f.write(json.dumps(meta, ensure_ascii=False))
        
class RefEntry :
    def __init__(self, iden : str, language : str, gender : str, text : str, wav : str) :
        self.iden = iden,
        self.language = language
        self.gender = gender
        self.text = text
        self.wav = wav

def get_entries() -> list[RefEntry] :
    idens = set(item[: item.rfind('.')] for item in os.listdir(REF_DIR))
    
    refs = []
    
    for iden in idens :
        wav_name = iden + ".wav"
        meta_name = iden + ".json"
        if not os.path.exists(REF_DIR / wav_name) or not os.path.exists(REF_DIR / meta_name) :
            continue
        with open(REF_DIR / meta_name, 'r') as f :
            meta : dict[str, str] = json.load(f)
        refs.append(RefEntry(
            iden=iden,
            language=meta['language'],
            gender=meta['gender'],
            text=meta['text'],
            wav=str(REF_DIR / wav_name)
        ))
    return refs

LANGUAGE_MAP = {
    "Chinese": "zh"
}
GENDER_MAP = {
    "男": "male",
    "女": "female"
}

def filter_entires(refs : list[RefEntry], language : str | None = None, gender : str | None = None) -> list[RefEntry] :
    filtered_refs = []
    
    for ref in refs :
        if (language is None or ref.language in [LANGUAGE_MAP.get(language, None), language]) \
                and (gender is None or ref.gender in [GENDER_MAP.get(gender, None), gender]) :
            filtered_refs.append(ref)
            
    return filtered_refs


def select_patient_doctor_refs(refs: list[RefEntry], meta: dict[str, str] | None = None) -> tuple[RefEntry, RefEntry]:
    meta = meta or {}
    language = meta.get("language")
    patient_gender = meta.get("sex") or meta.get("gender")

    patient_pool = filter_entires(refs, language=language, gender=patient_gender) or refs
    patient_ref = random.choice(patient_pool)

    doctor_gender = "男" if random.random() < 0.8 else "女"
    doctor_pool = (
        filter_entires(refs, language=language, gender=doctor_gender)
        or filter_entires(refs, gender=doctor_gender)
        or refs
    )
    doctor_candidates = [ref for ref in doctor_pool if ref != patient_ref] or doctor_pool
    doctor_ref = random.choice(doctor_candidates)

    return patient_ref, doctor_ref