from pydub import AudioSegment
from pathlib import Path
import json
import os

REF_DIR = Path(__file__).parents[1] / "data" / "ref"

def name(meta : dict[str, str]) -> str :
    return f"{meta['language']}_{meta['gender']}_{meta['id']}"

def generate(audio : AudioSegment, chunks : list[tuple[float, float, str]]) -> tuple[AudioSegment, str]:
    output = AudioSegment.empty()
    silence = AudioSegment.silent(duration=120)
    
    text = ""
    
    for chunk in chunks :
        st, ed = int(chunk[0] * 1000), int(chunk[1] * 1000)
        
        seg = audio[st : ed]
        
        text += chunk[2]
        
        output += seg
        output += silence
    
    return output, text
        
def export(audio : AudioSegment, meta : dict[str, str]) :
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