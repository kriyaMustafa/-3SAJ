import os
import threading
import re
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import numpy as np
import soundfile as sf

BASE_DIR = Path(__file__).resolve().parent
VOXCPM2_OPTIMIZE = os.getenv("VOXCPM2_OPTIMIZE", "1").strip().lower() in {"1", "true", "yes"}
VOXCPM2_DEVICE = os.getenv("VOXCPM2_DEVICE", "auto").strip().lower()
VOXCPM2_FAST_MODE = os.getenv("VOXCPM2_FAST_MODE", "1").strip().lower() in {"1", "true", "yes"}
VOXCPM2_CFG_VALUE = float(os.getenv("VOXCPM2_CFG_VALUE", "1.25" if VOXCPM2_FAST_MODE else "1.7"))
VOXCPM2_INFERENCE_TIMESTEPS = int(os.getenv("VOXCPM2_INFERENCE_TIMESTEPS", "4" if VOXCPM2_FAST_MODE else "8"))
VOXCPM2_MAX_LEN = int(os.getenv("VOXCPM2_MAX_LEN", "1400" if VOXCPM2_FAST_MODE else "2048"))
VOXCPM2_RETRY_BADCASE = os.getenv("VOXCPM2_RETRY_BADCASE", "0").strip().lower() in {"1", "true", "yes"}
VOXCPM2_USE_STYLE = os.getenv("VOXCPM2_USE_STYLE", "0").strip().lower() in {"1", "true", "yes"}

# Lazy loader for VoxCPM model
_model = None
_model_lock = threading.Lock()
_generate_lock = threading.Lock()

# ==============================================================================
# STEP 2: FIXED VOICE OVERRIDE
# Once you have selected your favorite voice samples from Step 1, 
# set these to the absolute paths of the generated .wav files.
# It will force VoxCPM2 to clone these exact voices for EVERY sentence, 
# ensuring 100% consistency throughout the entire video.
# ==============================================================================
SELECTED_MALE_VOICE_FILE = r"Z:\year3\projecj video translate backup\backend\voice_samples\faster_gentle_recap\faster_gentle_var_7_seed_10451.wav"
SELECTED_FEMALE_VOICE_FILE = r"Z:\year3\projecj video translate backup\backend\voice_samples\faster_gentle_recap\faster_gentle_var_9_seed_23843.wav"





def _resolve_model_source() -> tuple[str, dict[str, object]]:
    """Pick the best available VoxCPM2 source for this machine."""
    local_model_dir = BASE_DIR.parent / "VoxCPM2_Model"
    if (local_model_dir / "model.safetensors").exists():
        return str(local_model_dir), {"local_files_only": True}

    env_path = os.getenv("VOXCPM2_MODEL_PATH", "").strip()
    if env_path and Path(env_path).is_dir():
        return env_path, {"local_files_only": True}

    local_cache_dir = local_model_dir / ".cache" / "huggingface"
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
                        load_denoiser=True,
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
                            load_denoiser=True,
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
        return "A clear, professional, warm natural voice with crisp articulation"
    if profile == "female":
        return "A professional, highly clear female voice with perfect articulation, beautiful studio quality, smooth and warm Khmer narration"
    if profile == "male":
        return "A professional, highly clear male voice with perfect articulation, beautiful studio quality, smooth and warm Khmer narration"
    if profile == "kid":
        return "A highly clear, bright, youthful child voice with gentle and precise Khmer articulation"
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
    
    # --- Step 2: Apply Global Voice Override ---
    requested_profile = (voice_profile or "").strip().lower()
    override_file = None
    
    if requested_profile in ("male", "elder_male") and SELECTED_MALE_VOICE_FILE and os.path.exists(SELECTED_MALE_VOICE_FILE):
        override_file = SELECTED_MALE_VOICE_FILE
    elif requested_profile in ("female", "elder_female", "kid") and SELECTED_FEMALE_VOICE_FILE and os.path.exists(SELECTED_FEMALE_VOICE_FILE):
        override_file = SELECTED_FEMALE_VOICE_FILE
        
    if override_file:
        reference_wav_path = override_file
        print(f"🔒 Forcing 100% consistent character using selected voice override: {override_file}")
    elif voice_profile and os.path.exists(voice_profile):
        reference_wav_path = voice_profile


    # 3. Format the text for Voice Design.
    # User requested to drop all per-segment persona modifications.
    # We pass the text cleanly without any (A professional...) prepends.

    print(f"🎤 Synthesizing with VoxCPM2: text={repr(text)}, target_lang={target_lang}")
    if reference_wav_path:
        print(f"📂 Using reference audio for cloning: {reference_wav_path}")

    # 4. Generate the audio waveform
    with _generate_lock:
        import torch
        import random
        # Lock the voice to exactly ONE persona per profile
        seed_map = {"male": 100, "female": 200, "kid": 300, "elder_male": 400, "elder_female": 500}
        seed_val = seed_map.get((voice_profile or "").strip().lower(), 42)
        torch.manual_seed(seed_val)
        np.random.seed(seed_val)
        random.seed(seed_val)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed_val)

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


def generate_voice_samples(description: str, num_samples: int = 4, output_dir: str = "voice_samples", sample_text: str = "This is a sample voice for your video narration. I can express shifting emotions according to the storyline.") -> list[str]:
    """
    Generate multiple voice samples using VoxCPM2 Voice Design feature.
    Saves the generated wav files into output_dir.
    """
    model = get_model()
    out_dir = Path(BASE_DIR) / output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"🎤 Generating {num_samples} voice samples for description: '{description}'")

    # In VoxCPM, text design is usually done by prepending the description
    # inside the text, or relying on the seed if no reference is passed.
    # We will use the description in the prompt and vary the seed to get different voices.
    text_with_prompt = f"({description}) {sample_text}"

    generated_files = []
    with _generate_lock:
        import torch
        import random

        for i in range(1, num_samples + 1):
            seed_val = random.randint(1000, 99999)
            torch.manual_seed(seed_val)
            np.random.seed(seed_val)
            random.seed(seed_val)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed_val)

            wav = model.generate(
                text=text_with_prompt,
                cfg_value=VOXCPM2_CFG_VALUE,
                inference_timesteps=VOXCPM2_INFERENCE_TIMESTEPS,
                max_len=_estimate_max_len(text_with_prompt),
                retry_badcase=VOXCPM2_RETRY_BADCASE,
                retry_badcase_max_times=1,
            )

            sample_filename = out_dir / f"voice_sample_{i}_seed_{seed_val}.wav"
            _save_wav_or_convert(wav, sample_filename, model.tts_model.sample_rate)
            generated_files.append(str(sample_filename))
            print(f"✅ Generated sample {i}: {sample_filename}")

    return generated_files

