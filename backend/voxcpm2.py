import os
import threading
import re
from pathlib import Path

import numpy as np
import soundfile as sf

BASE_DIR = Path(__file__).resolve().parent
VOXCPM2_OPTIMIZE = os.getenv("VOXCPM2_OPTIMIZE", "0").strip().lower() in {"1", "true", "yes"}
VOXCPM2_DEVICE = os.getenv("VOXCPM2_DEVICE", "auto").strip().lower()
VOXCPM2_FAST_MODE = os.getenv("VOXCPM2_FAST_MODE", "1").strip().lower() in {"1", "true", "yes"}
VOXCPM2_CFG_VALUE = float(os.getenv("VOXCPM2_CFG_VALUE", "1.25" if VOXCPM2_FAST_MODE else "1.7"))
VOXCPM2_INFERENCE_TIMESTEPS = int(os.getenv("VOXCPM2_INFERENCE_TIMESTEPS", "7" if VOXCPM2_FAST_MODE else "8"))
VOXCPM2_MAX_LEN = int(os.getenv("VOXCPM2_MAX_LEN", "1400" if VOXCPM2_FAST_MODE else "2048"))
VOXCPM2_RETRY_BADCASE = os.getenv("VOXCPM2_RETRY_BADCASE", "0").strip().lower() in {"1", "true", "yes"}
VOXCPM2_USE_STYLE = os.getenv("VOXCPM2_USE_STYLE", "0").strip().lower() in {"1", "true", "yes"}

# Lazy loader for VoxCPM model
_model = None
_model_lock = threading.Lock()
_generate_lock = threading.Lock()


def _resolve_model_source() -> tuple[str, dict[str, object]]:
    """Pick the best available VoxCPM2 source for this machine."""
    env_path = os.getenv("VOXCPM2_MODEL_PATH", "").strip()
    if env_path and Path(env_path).is_dir():
        return env_path, {"local_files_only": True}

    local_cache_dir = BASE_DIR.parent / "VoxCPM2_Model" / ".cache" / "huggingface"
    if local_cache_dir.exists():
        return "openbmb/VoxCPM2", {"cache_dir": str(local_cache_dir)}

    return "openbmb/VoxCPM2", {}


def _resolve_device() -> str | None:
    if VOXCPM2_DEVICE in {"", "auto"}:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"
    if VOXCPM2_DEVICE == "none":
        return None
    return VOXCPM2_DEVICE


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from voxcpm import VoxCPM
                print("🚀 Loading VoxCPM2 model weights (this may take a moment on the first run)...")
                model_source, extra_kwargs = _resolve_model_source()
                # Load the model. We set load_denoiser=False for speed/stability as recommended.
                selected_device = _resolve_device()
                try:
                    _model = VoxCPM.from_pretrained(
                        model_source,
                        load_denoiser=False,
                        optimize=VOXCPM2_OPTIMIZE,
                        device=selected_device,
                        **extra_kwargs,
                    )
                    print(f"✅ VoxCPM2 model loaded successfully on device={selected_device or 'auto'}!")
                except Exception as exc:
                    if selected_device != "cpu":
                        print(f"⚠️ VoxCPM2 GPU load failed, falling back to CPU: {exc}")
                        _model = VoxCPM.from_pretrained(
                            model_source,
                            load_denoiser=False,
                            optimize=False,
                            device="cpu",
                            **extra_kwargs,
                        )
                        print("✅ VoxCPM2 model loaded successfully on device=cpu!")
                    else:
                        raise
    return _model


def _voice_description_from_profile(voice_profile: str) -> str:
    profile = (voice_profile or "").strip().lower()
    if not profile:
        return "A clear, warm, smooth natural voice"
    if profile == "female":
        return "A clear, warm female voice with smooth studio delivery, gentle and polished"
    if profile == "male":
        return "A clear, warm male voice with smooth studio delivery, gentle and polished"
    if profile == "kid":
        return "A bright youthful child voice with gentle, clear delivery"
    return voice_profile.strip()


def _style_description(style: dict | None) -> str:
    if not style:
        return ""

    parts: list[str] = []
    rate_val = str(style.get("rate", "+0%")).strip()
    pitch_val = str(style.get("pitch", "+0Hz")).strip()
    volume_val = str(style.get("volume", "+0%")).strip()

    if rate_val.startswith("+") and rate_val != "+0%":
        parts.append("slightly faster")
    elif rate_val.startswith("-") and rate_val != "-0%":
        parts.append("slightly slower")

    if pitch_val.startswith("+") and pitch_val != "+0Hz":
        parts.append("a touch brighter")
    elif pitch_val.startswith("-") and pitch_val != "-0Hz":
        parts.append("a touch deeper")

    if volume_val.startswith("+") and volume_val != "+0%":
        parts.append("slightly stronger projection")
    elif volume_val.startswith("-") and volume_val != "-0%":
        parts.append("slightly softer delivery")

    if not parts:
        return ""
    return "clear and polished, " + ", ".join(parts)


def _save_wav_or_convert(wav, output_path: Path, sample_rate: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(wav, "detach"):
        wav = wav.detach().cpu().numpy()
    else:
        wav = np.asarray(wav)

    if wav.ndim == 2 and wav.shape[0] in {1, 2} and wav.shape[0] < wav.shape[-1]:
        wav = wav.T

    if output_path.suffix.lower() == ".wav":
        sf.write(str(output_path), wav, sample_rate)
        return

    temp_wav = output_path.with_suffix(".wav")
    sf.write(str(temp_wav), wav, sample_rate)
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_wav(temp_wav)
        audio.export(output_path, format=output_path.suffix.lstrip(".") or "wav")
    finally:
        if temp_wav.exists():
            temp_wav.unlink()


def _estimate_max_len(text: str) -> int:
    # Lower ceilings keep the diffusion loop tighter and reduce latency.
    char_count = len(re.sub(r"\s+", "", text))
    estimated = max(384, char_count * 4)
    return min(VOXCPM2_MAX_LEN, estimated)


def generate(text: str, output_path: str, voice_profile: str = "female", target_lang: str = "km", style: dict = None) -> str:
    """
    Main entry point for VoxCPM2 TTS generation.
    Supports Voice Design, Controllable Voice Cloning, and style instructions.
    """
    model = get_model()

    # 2. Check if voice_profile is a path to a reference audio file (Voice Cloning)
    reference_wav_path = None
    if voice_profile and os.path.exists(voice_profile):
        reference_wav_path = voice_profile

    # 3. Format the text for Voice Design.
    if not text.startswith("(") and not reference_wav_path:
        desc_parts = [_voice_description_from_profile(voice_profile)]
        desc_parts = [item for item in desc_parts if item]
        if VOXCPM2_USE_STYLE:
            style_desc = _style_description(style)
            if style_desc:
                desc_parts.append(style_desc)
        if desc_parts:
            text = f"({', '.join(desc_parts)}){text}"

    print(f"🎤 Synthesizing with VoxCPM2: text={repr(text)}, target_lang={target_lang}")
    if reference_wav_path:
        print(f"📂 Using reference audio for cloning: {reference_wav_path}")

    # 4. Generate the audio waveform
    with _generate_lock:
        if reference_wav_path:
            wav = model.generate(
                text=text,
                reference_wav_path=reference_wav_path,
                cfg_value=VOXCPM2_CFG_VALUE,
                inference_timesteps=VOXCPM2_INFERENCE_TIMESTEPS,
                max_len=_estimate_max_len(text),
                retry_badcase=VOXCPM2_RETRY_BADCASE,
                retry_badcase_max_times=1,
            )
        else:
            wav = model.generate(
                text=text,
                cfg_value=VOXCPM2_CFG_VALUE,
                inference_timesteps=VOXCPM2_INFERENCE_TIMESTEPS,
                max_len=_estimate_max_len(text),
                retry_badcase=VOXCPM2_RETRY_BADCASE,
                retry_badcase_max_times=1,
            )

    # 5. Save output file
    output_path_obj = Path(output_path)
    _save_wav_or_convert(wav, output_path_obj, model.tts_model.sample_rate)
    print(f"💾 Audio saved to: {output_path_obj}")
    return str(output_path_obj)
