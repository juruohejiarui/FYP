from pydub import AudioSegment
from pathlib import Path
from utils import generate, export
from tqdm import tqdm
import pandas as pd
import os
import random

RAW_DATA_DIR = Path(__file__).parents[3] / "data" / "Mandarin_Chinese_Conversational_Speech_Corpus"

txt_lst = os.listdir(RAW_DATA_DIR / "TXT")
fid = 0

random.seed(114)

for txt_name in tqdm(txt_lst) :
    fid += 1
    wav_name = txt_name[:-4] + ".wav"
    
    txt_path = RAW_DATA_DIR / "TXT" / txt_name
    wav_path = RAW_DATA_DIR / "WAV" / wav_name
    
    tqdm.write(f"txt: {txt_path}")
    
    seg = AudioSegment.from_file(str(wav_path))
    
    roles : dict[str, dict[str, list | str]]= {}
    
    with open(txt_path, 'r') as f :
        lines = f.readlines()
        
    for idx, line in enumerate(lines) :        
        chunk, rid, gender, text = map(str.strip, line.split('\t'))
        
        st, ed = map(float, chunk[1 : -1].split(','))
        
        if rid == '0' or gender == 'none' or '[' in text or '+' in text or len(text) == 0: continue

        if text[-1] not in ['。', '？', '！'] : text += "。"
        
        if rid not in roles :
            roles[rid] = {
                'meta' : {
                    'gender': gender,
                    'language' : 'zh',
                    'id' : f'{fid}_{rid}'
                },
                'chunks' : []
            }
        
        roles[rid]['chunks'].append((st, ed, text))
        
    # for each role, construct chunk list and
    for rid in roles.keys() :
        random.shuffle(roles[rid]['chunks'])
        
        # only use at most 15s
        acc = 0.0
        idx = 0
        while idx < len(roles[rid]['chunks']) and acc < 13 :
            ele = roles[rid]['chunks'][idx]
            acc += ele[1] - ele[0]
            idx += 1
            
        tqdm.write(f"generating role {rid} of {txt_path}")
        
        roles[rid]['chunks'] = roles[rid]['chunks'][:idx]
                
        rseg, text = generate(seg, roles[rid]['chunks'])
        roles[rid]['meta']['text'] = text
        export(rseg, roles[rid]['meta'])
    
    