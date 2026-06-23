import sys
import wave
from pathlib import Path

import numpy as np
import torch
import torchaudio.functional as audio_functional

import demucs.separate


def load_track(track, audio_channels, samplerate):
    import soundfile as sf
    import torch
    import torchaudio.functional as audio_functional
    
    path = Path(track)
    # Read using soundfile which is more efficient for large files
    with sf.SoundFile(str(path)) as f:
        audio = f.read(dtype='float32')
        source_rate = f.samplerate
        channels = f.channels

    # Convert to torch tensor
    if channels == 1:
        audio = audio[:, np.newaxis]
    
    audio = audio.T # (channels, frames)
    wav = torch.from_numpy(audio)

    if channels == 1 and audio_channels == 2:
        wav = wav.repeat(2, 1)
    elif channels > audio_channels:
        wav = wav[:audio_channels]

    if source_rate != samplerate:
        wav = audio_functional.resample(wav, source_rate, samplerate)

    return wav


def save_audio(wav, path, samplerate, bitrate=320, clip="rescale", bits_per_sample=16, as_float=False, preset=2):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wav = wav.detach().cpu()
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)

    peak = wav.abs().max().item()
    if clip == "rescale" and peak > 1:
        wav = wav / peak
    else:
        wav = wav.clamp(-1, 1)

    audio = wav.t().numpy()
    pcm = (audio * 32767.0).astype(np.int16)

    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(pcm.shape[1])
        wav_file.setsampwidth(2)
        wav_file.setframerate(samplerate)
        wav_file.writeframes(pcm.tobytes())


demucs.separate.load_track = load_track
demucs.separate.save_audio = save_audio


if __name__ == "__main__":
    demucs.separate.main()
