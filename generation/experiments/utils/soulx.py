import sys
import torch
import torchaudio
from pathlib import Path
from typing import Optional

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[3]
MODEL_REPO_DIR = PROJECT_ROOT / "generation" / "models" / "soulx-podcast"

sys.path.append(str(MODEL_REPO_DIR))
import s3tokenizer  # noqa: E402
from soulxpodcast.config import Config, SamplingParams  # noqa: E402
from soulxpodcast.utils.infer_utils import initiate_model  # noqa: E402

SAMPLE_RATE = 24000


class SoulxAudio:
    def __init__(
        self,
        model_path: str | Path,
        llm_engine: str = "hf",
        fp16_flow: bool = False,
        seed: int = 1988,
    ):
        self.model, self.dataset = initiate_model(seed, str(model_path), llm_engine, fp16_flow)
        self.sample_rate = SAMPLE_RATE

    def generate_dialogue(
        self,
        key: str,
        prompt_wavs: list[str],
        prompt_texts: list[str],
        turns: list[tuple[int, str]],
        sampling_params: SamplingParams,
    ) -> torch.Tensor:
        dataitem = {
            "key": key,
            "prompt_text": prompt_texts,
            "prompt_wav": prompt_wavs,
            "text": [text for _, text in turns],
            "spk": [spk for spk, _ in turns],
        }
        self.dataset.update_datasource([dataitem])
        data = self.dataset[0]

        prompt_mels_for_llm, prompt_mels_lens_for_llm = s3tokenizer.padding(data["log_mel"])
        spk_emb_for_flow = torch.tensor(data["spk_emb"])
        prompt_mels_for_flow = torch.nn.utils.rnn.pad_sequence(
            data["mel"], batch_first=True, padding_value=0
        )
        prompt_mels_lens_for_flow = torch.tensor(data["mel_len"])

        processed_data = {
            "prompt_mels_for_llm": prompt_mels_for_llm,
            "prompt_mels_lens_for_llm": prompt_mels_lens_for_llm,
            "prompt_text_tokens_for_llm": data["prompt_text_tokens"],
            "text_tokens_for_llm": data["text_tokens"],
            "prompt_mels_for_flow_ori": prompt_mels_for_flow,
            "prompt_mels_lens_for_flow": prompt_mels_lens_for_flow,
            "spk_emb_for_flow": spk_emb_for_flow,
            "sampling_params": sampling_params,
            "spk_ids": data["spks_list"],
            "infos": [data["info"]],
            "use_dialect_prompt": False,
        }

        results_dict = self.model.forward_longform(**processed_data)

        target_audio: Optional[torch.Tensor] = None
        for wav in results_dict["generated_wavs"]:
            target_audio = wav if target_audio is None else torch.cat([target_audio, wav], dim=1)
        return target_audio

    def save(self, wav: torch.Tensor, output_path: str | Path) -> None:
        torchaudio.save(str(output_path), wav.cpu(), sample_rate=self.sample_rate)


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
