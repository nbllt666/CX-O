import torch
import torchaudio
import jieba
from pypinyin import Style, lazy_pinyin


def get_tokenizer(vocab_file_path: str):
    with open(vocab_file_path, "r", encoding="utf-8") as f:
        vocab_char_map = {}
        for i, char in enumerate(f):
            vocab_char_map[char[:-1]] = i
    vocab_size = len(vocab_char_map) + 1  # +1 for padding token
    return vocab_char_map, vocab_size


def convert_char_to_pinyin(reference_target_texts_list, polyphone=True):
    final_reference_target_texts_list = []
    custom_trans = str.maketrans(
        {";": ",", "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}
    )

    def is_chinese(c):
        return "\u3100" <= c <= "\u9fff"

    for text in reference_target_texts_list:
        char_list = []
        text = text.translate(custom_trans)
        for seg in jieba.cut(text):
            seg_byte_len = len(bytes(seg, "UTF-8"))
            if seg_byte_len == len(seg):
                if char_list and seg_byte_len > 1 and char_list[-1] not in " :'\"":
                    char_list.append(" ")
                char_list.extend(seg)
            elif polyphone and seg_byte_len == 3 * len(seg):
                seg_ = lazy_pinyin(seg, style=Style.TONE3, tone_sandhi=True)
                for i, c in enumerate(seg):
                    if is_chinese(c):
                        char_list.append(" ")
                    char_list.append(seg_[i])
            else:
                for c in seg:
                    if ord(c) < 256:
                        char_list.extend(c)
                    elif is_chinese(c):
                        char_list.append(" ")
                        char_list.extend(lazy_pinyin(c, style=Style.TONE3, tone_sandhi=True))
                    else:
                        char_list.append(c)
        final_reference_target_texts_list.append(char_list)

    return final_reference_target_texts_list


def list_str_to_idx(
    text: list[str] | list[list[str]],
    vocab_char_map: dict[str, int],
    padding_value=-1,
):
    list_idx_tensors = [torch.tensor([vocab_char_map.get(c, 0) for c in t]) for t in text]
    return list_idx_tensors


def resample_audio(wav: torch.Tensor, orig_sr: int, target_sr: int) -> torch.Tensor:
    if orig_sr == target_sr:
        return wav
    resampler = torchaudio.transforms.Resample(orig_sr, target_sr)
    return resampler(wav)


def normalize_audio(wav: torch.Tensor, target_rms: float = 0.15) -> torch.Tensor:
    ref_rms = torch.sqrt(torch.mean(torch.square(wav)))
    if ref_rms < target_rms:
        wav = wav * target_rms / ref_rms
    return wav


def compute_mel_spectrogram(
    waveform: torch.Tensor,
    sample_rate: int = 24000,
    n_fft: int = 1024,
    win_length: int = 1024,
    hop_length: int = 256,
    n_mels: int = 100,
) -> torch.Tensor:
    mel_stft = torchaudio.transforms.MelSpectrogram(
        sample_rate=sample_rate,
        n_fft=n_fft,
        win_length=win_length,
        hop_length=hop_length,
        n_mels=n_mels,
        power=1,
        center=True,
        normalized=False,
        norm=None,
    ).to(waveform.device)
    mel = mel_stft(waveform)
    mel = mel.clamp(min=1e-5).log()
    return mel.transpose(1, 2)
