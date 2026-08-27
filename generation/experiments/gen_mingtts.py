import argparse
import json
import os
import torch
import torchaudio
import random
from pathlib import Path
from tqdm import tqdm
from utils.mingtts import MingAudio, build_dialogue_chunks, build_prompt_text
from utils.script import parse
from ref.utils import RefEntry, get_entries, filter_entires

random.seed(42)

OUTPUT_DIR = Path(__file__).parent / "data" / "audio" / "mingtts"
PROJECT_ROOT = Path(__file__).parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "pretrained" / "TTS" / "Ming-omni-tts-0.5B"

DEFAULT_PROMPT = "Please generate speech based on the following description.\n"

os.makedirs(str(OUTPUT_DIR), exist_ok=True)

def random_select(refs : list[RefEntry], ignore : RefEntry) -> RefEntry :
    while True :
        idx = random.randint(0, len(refs) - 1)
        ref = refs[idx]
        if ref != ignore :
            return ref
        
def generate(model : MingAudio,
            script : dict[str, str | list],
            prompt : str,
            refs : list[RefEntry],
            cfg : float,
            sigma : float,
            temperature : float,
            mx_decode_steps : int,
            mx_chars_per_chunks : int = -1) -> dict[str]:
    script_id = script['dialogue_id']
    output_path = OUTPUT_DIR / f"{script_id}.wav"
    
    chunks = build_dialogue_chunks(script['dialogue'], mx_chars_per_chunks)
    
    ref_wavs = [ref.wav for ref in refs]
    ref_text = build_prompt_text([{f"speaker_{idx}": ref.text} for idx, ref in enumerate(refs)])
    
    wav_chunks : list[torch.Tensor] = []
    for chunk_idx, chunk_txt in enumerate(chunks) :
        wav_chunk = model.speech_generation(
            prompt=prompt,
            text=chunk_txt,
            use_spk_emb=True,
            prompt_wav_path=ref_wavs, 
            prompt_text=ref_text,
            max_decode_steps=mx_decode_steps,
            cfg=cfg,
            sigma=sigma,
            temperature=temperature,
            output_wav_path=None
        )
        if wav_chunk is None : 
            raise RuntimeError(f"Failed to generate waveform for chunk {chunk_idx} of script {script_id}")
        wav_chunks.append(wav_chunk)
    
    merged_wav = torch.cat(wav_chunks, dim=-1)
    
    torchaudio.save(str(output_path), merged_wav, sample_rate=model.sample_rate)
    
    return {
        "script_id": script_id,
        "wav_path" : str(output_path),
        "ref_paths": [ref.iden for ref in refs],
        "param": {
            "cfg": cfg,
            "sigma": sigma,
            "temperature": temperature,
            "max_decode_steps": mx_decode_steps,
            "chunks": len(chunk_txt),
            "max_chars_per_chunk": mx_chars_per_chunks
        }
    }

if __name__ == "__main__" :
    parser = argparse.ArgumentParser(description="Generate WAVs from scripts.jsonl using Ming-omni-TTS.")
    
    parser.add_argument("scripts", type=Path)
    parser.add_argument("--prompt", type=str, default=DEFAULT_PROMPT)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--cfg", type=float, default=2.0)
    parser.add_argument("--sigma", type=float, default=0.25)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--mx-decode-steps", type=int, default=260)
    parser.add_argument(
        "--mx-char-per-chunk", type=int, default=300,
        help="Maximum number of characters per generated audio chunk. Use -1 to disable chunking.",
    )
    parser.add_argument("--sel-ids", type=lambda s : list(map(int, s.split(','))), default=None)
    args = parser.parse_args()
    
    ref_ents = get_entries()
    
    scripts : list[dict[str, dict | list]]= parse(args.scripts)
    
    model = MingAudio(args.model_path)
    
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifests : dict[str, dict[str]] = {}
    
    if os.path.exists(manifest_path) :
        with open(manifest_path, 'r') as f :
            manifests = json.load(f)
    
    for script in tqdm(scripts) :
        script_id = script['dialogue_id']
        if args.sel_ids is not None and script_id not in args.sel_ids :
            tqdm.write(f"Skipping script {script_id}: not in sel_ids")
            continue
                
        # randomly select a ref for patient
        patient_ref = random_select(
            filter_entires(ref_ents, script['meta'].get('language', 'Chinese'), script['meta']['sex']),
            None
        )
        doctor_ref = random_select(ref_ents, patient_ref)
        
        print(patient_ref, doctor_ref)
        
        ent = generate(
            model=model,
            script=script,
            prompt=args.prompt,
            refs=[patient_ref, doctor_ref],
            cfg=args.cfg,
            sigma=args.sigma,
            temperature=args.temperature,
            mx_decode_steps=args.mx_decode_steps,
            mx_chars_per_chunks=args.mx_char_per_chunk
        )
        manifests[script['dialogue_id']] = ent
        
    with open(manifest_path, 'w', encoding='utf-8') as f :
        json.dump(manifests, f, ensure_ascii=False, indent=2)
    