import asyncio
import gc
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import demucs.separate

import edge_tts
import imageio_ffmpeg
import numpy as np
from deep_translator import GoogleTranslator
from faster_whisper import WhisperModel
from moviepy import AudioFileClip, CompositeAudioClip, VideoFileClip


BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "data" / "uploads"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", str(max((os.cpu_count() or 4) - 1, 1))))
WHISPER_WORKERS = int(os.getenv("WHISPER_WORKERS", "2"))
DEFAULT_SPEAKER_GENDER = os.getenv("DEFAULT_SPEAKER_GENDER", "Male")
MALE_KHMER_VOICE = os.getenv("MALE_KHMER_VOICE", "km-KH-PisethNeural")
FEMALE_KHMER_VOICE = os.getenv("FEMALE_KHMER_VOICE", "km-KH-SreymomNeural")
BACKGROUND_MODE = os.getenv("BACKGROUND_MODE", "demucs")
TTS_CONCURRENCY = int(os.getenv("TTS_CONCURRENCY", "4"))
MIN_TTS_TEMPO = float(os.getenv("MIN_TTS_TEMPO", "0.92"))
MAX_TTS_TEMPO = float(os.getenv("MAX_TTS_TEMPO", "1.65"))
BACKGROUND_NORMAL_VOLUME = float(os.getenv("BACKGROUND_NORMAL_VOLUME", "1.0"))
BACKGROUND_DUCKED_VOLUME = float(os.getenv("BACKGROUND_DUCKED_VOLUME", "0.38"))
CENTER_CANCEL_VOLUME = os.getenv("CENTER_CANCEL_VOLUME", "2.0")
DEMUCS_MODEL = os.getenv("DEMUCS_MODEL", "htdemucs")

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

translator = GoogleTranslator(source="auto", target="km")

import google.generativeai as genai
import backend.voxcpm2 as voxcpm2
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel(
        model_name=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        system_instruction=(
            "You are a professional, native Khmer translator. Translate the given English transcript/text "
            "accurately and naturally into standard Khmer, maintaining the exact context, flow, and tone. "
            "Provide only the Khmer translation, with no explanation or introductory text."
        )
    )
else:
    gemini_model = None

whisper_model: WhisperModel | None = None
whisper_runtime: dict[str, str] = {}
ProgressCallback = Callable[[dict[str, Any]], None]
pipeline_semaphore = asyncio.Semaphore(1)


@dataclass
class Speaker:
    id: str
    gender: str
    character: str
    voice: str
    rate: str
    pitch: str
    volume: str


VOICE_PROFILES = {
    "male": {
        "gender": "Male",
        "character": "Male",
        "voice": MALE_KHMER_VOICE,
        "rate": "+4%",
        "pitch": "-2Hz",
        "volume": "+0%",
    },
    "female": {
        "gender": "Female",
        "character": "Female",
        "voice": FEMALE_KHMER_VOICE,
        "rate": "+4%",
        "pitch": "+2Hz",
        "volume": "+0%",
    },
    "kid": {
        "gender": "Child",
        "character": "Kid",
        "voice": FEMALE_KHMER_VOICE,
        "rate": "+10%",
        "pitch": "+18Hz",
        "volume": "+0%",
    },
}


def _safe_filename(filename: str) -> str:
    return Path(filename).name


def _report(progress_callback: ProgressCallback | None, **payload: Any) -> None:
    if progress_callback:
        progress_callback(payload)


def _format_eta(seconds: float | None) -> str | None:
    if seconds is None or seconds <= 0:
        return None
    minutes, secs = divmod(int(seconds), 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _probe_duration(audio_path: Path) -> float | None:
    try:
        clip = AudioFileClip(str(audio_path))
        duration = float(clip.duration or 0)
        clip.close()
        return duration
    except Exception:
        return None


def _atempo_filter(tempo: float) -> str:
    filters: list[str] = []
    while tempo > 2.0:
        filters.append("atempo=2.0")
        tempo /= 2.0
    while tempo < 0.5:
        filters.append("atempo=0.5")
        tempo /= 0.5
    filters.append(f"atempo={tempo:.6f}")
    return ",".join(filters)


def _fit_audio_to_window(input_path: Path, output_path: Path, target_duration: float) -> Path:
    if target_duration <= 0:
        return input_path

    source_duration = _probe_duration(input_path)
    if not source_duration or source_duration <= 0:
        return input_path

    tempo = source_duration / target_duration
    tempo = max(MIN_TTS_TEMPO, min(MAX_TTS_TEMPO, tempo))
    if abs(tempo - 1.0) < 0.03:
        return input_path
    try:
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i",
                str(input_path),
                "-filter:a",
                _atempo_filter(tempo),
                "-vn",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return output_path
    except subprocess.CalledProcessError as exc:
        print(f"Pacing calibration skipped for {input_path.name}: {exc.stderr}")
        return input_path


def _get_whisper_model() -> WhisperModel:
    global whisper_model, whisper_runtime
    if whisper_model is not None:
        return whisper_model

    preferred_devices = ["cuda", "cpu"] if WHISPER_DEVICE == "auto" else [WHISPER_DEVICE]
    last_error: Exception | None = None
    for device in preferred_devices:
        compute_type = "float16" if device == "cuda" else "int8"
        try:
            whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device=device,
                compute_type=compute_type,
                cpu_threads=WHISPER_CPU_THREADS,
                num_workers=WHISPER_WORKERS,
                download_root=str(BASE_DIR / "whisper_models"),
            )
            whisper_runtime = {"device": device, "compute_type": compute_type}
            print(f"Whisper loaded on {device} with {compute_type}")
            return whisper_model
        except Exception as exc:
            last_error = exc
            print(f"Whisper could not use {device}: {exc}")

    raise RuntimeError(f"Unable to load Whisper model: {last_error}")


def _extract_audio(video_path: Path, output_path: Path) -> Path | None:
    try:
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-acodec",
                "pcm_s16le",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return output_path
    except subprocess.CalledProcessError as exc:
        print(f"Audio extraction failed: {exc.stderr}")
        return None
    finally:
        gc.collect()


def _ffmpeg_bin_dir() -> Path:
    bin_dir = PROCESSED_DIR / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = bin_dir / "ffmpeg.exe"
    if not ffmpeg_path.exists():
        shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), ffmpeg_path)
    return bin_dir


def _make_demucs_background(video_path: Path, output_path: Path) -> Path | None:
    audio_path = PROCESSED_DIR / f"{output_path.stem}_source.wav"
    if _extract_audio(video_path, audio_path) is None:
        return None

    demucs_root = PROCESSED_DIR / "demucs"
    env = os.environ.copy()
    env["PATH"] = f"{_ffmpeg_bin_dir()}{os.pathsep}{env.get('PATH', '')}"

    try:
        # Import the monkeypatches from demucs_runner
        import demucs_runner
        
        demucs_args = [
            "--two-stems", "vocals",
            "-n", DEMUCS_MODEL,
            "-o", str(demucs_root),
            str(audio_path)
        ]
        
        # Run demucs directly without spawning a new process
        demucs.separate.main(demucs_args)
    except Exception as exc:
        print(f"Demucs separation failed: {exc}")
        gc.collect()
        return None

    no_vocals_path = demucs_root / DEMUCS_MODEL / audio_path.stem / "no_vocals.wav"
    if not no_vocals_path.exists():
        print(f"Demucs no_vocals output missing: {no_vocals_path}")
        return None

    try:
        shutil.copyfile(no_vocals_path, output_path)
        return output_path
    except OSError as exc:
        print(f"Could not copy Demucs background: {exc}")
    finally:
        gc.collect()
        return no_vocals_path


def _make_voice_suppressed_background(video_path: Path, output_path: Path) -> Path | None:
    if BACKGROUND_MODE == "mute":
        return None

    if BACKGROUND_MODE == "demucs":
        demucs_background = _make_demucs_background(video_path, output_path)
        if demucs_background is not None:
            return demucs_background
        print("Falling back to center cancel because Demucs background was not created.")

    if BACKGROUND_MODE not in {"center_cancel", "demucs"}:
        return None

    try:
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-af",
                f"pan=stereo|FL=FL-FR|FR=FR-FL,volume={CENTER_CANCEL_VOLUME}",
                "-acodec",
                "pcm_s16le",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return output_path
    except subprocess.CalledProcessError as exc:
        print(f"Voice-suppressed background failed: {exc.stderr}")
        return None

async def translate_text(text: str) -> str:
    if gemini_model:
        try:
            prompt = f"Translate the following English text to Khmer. Respond ONLY with the Khmer translation:\n\n{text}"
            response = await asyncio.to_thread(gemini_model.generate_content, prompt)
            translated = response.text.strip()
            if translated:
                return translated
        except Exception as exc:
            print(f"Gemini single translation error: {exc}")

    try:
        return await asyncio.to_thread(translator.translate, text)
    except Exception as exc:
        print(f"Translation error: {exc}")
        return text


async def translate_transcript(transcript: list[dict[str, Any]]) -> list[str]:
    """Translate the entire transcript in a single batch call using Gemini for cohesive context.
    Falls back to segment-by-segment translation on failure.
    """
    if not gemini_model:
        return [await translate_text(seg["text"]) for seg in transcript]

    try:
        texts_to_translate = [seg["text"] for seg in transcript]
        prompt = (
            "Translate the following list of English speech segments into natural Khmer. "
            "Maintain the context and flow of the conversation. "
            "Return the translations as a JSON array of strings in the exact same order and length as the input. "
            "Do not add any explanations, markdown formatting blocks, or other text outside the JSON array.\n\n"
            f"Input segments:\n{json.dumps(texts_to_translate, ensure_ascii=False)}"
        )
        
        response = await asyncio.to_thread(
            gemini_model.generate_content,
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        translated_list = json.loads(response.text)
        if isinstance(translated_list, list) and len(translated_list) == len(transcript):
            print(f"Batch translation successful using Gemini!")
            return [str(item) for item in translated_list]
        else:
            print("Batch translation returned invalid structure or length. Falling back to segment-by-segment.")
    except Exception as exc:
        print(f"Gemini batch translation error: {exc}. Falling back to segment-by-segment.")

    # Fallback: translate segment by segment
    results = []
    for seg in transcript:
        results.append(await translate_text(seg["text"]))
    return results


async def generate_khmer_audio(text: str, output_path: Path, speaker: Speaker) -> None:
    # Use VoxCPM2 local model for high-fidelity Khmer TTS
    style = {
        "rate": speaker.rate,
        "pitch": speaker.pitch,
        "volume": speaker.volume
    }
    voice_profile = speaker.gender.lower()  # "male" or "female" or "kid"
    
    # voxcpm2.generate runs diffusion model inference which is synchronous, so we run it in a thread pool
    await asyncio.to_thread(
        voxcpm2.generate,
        text=text,
        output_path=str(output_path),
        voice_profile=voice_profile,
        target_lang="km",
        style=style
    )


def _speaker_from_profile(profile: str, index: int) -> Speaker:
    settings = VOICE_PROFILES.get(profile, VOICE_PROFILES["male"])
    return Speaker(
        id=f"Speaker_{index:02d}",
        gender=settings["gender"],
        character=settings["character"],
        voice=settings["voice"],
        rate=settings["rate"],
        pitch=settings["pitch"],
        volume=settings["volume"],
    )


def detect_speakers(_: Path, voice_cast: str = "auto") -> list[Speaker]:
    """Pluggable diarization hook.

    Production deployments can replace this with PyAnnote or AssemblyAI. The local
    fallback keeps the rest of the orchestration deterministic and voice-consistent.
    """
    if voice_cast == "auto":
        profiles = ["male", "female", "kid"]
    elif voice_cast == "dual":
        profiles = ["male", "female"]
    elif voice_cast in VOICE_PROFILES:
        profiles = [voice_cast]
    else:
        fallback = "female" if DEFAULT_SPEAKER_GENDER.lower().startswith("f") else "male"
        profiles = [fallback]

    return [_speaker_from_profile(profile, index + 1) for index, profile in enumerate(profiles)]


def _estimate_gender(audio_segment: np.ndarray, sr: int) -> str:
    """Simple pitch-based gender estimation."""
    try:
        # Calculate fundamental frequency (simplified)
        # Higher pitch -> Female/Kid, Lower -> Male
        if len(audio_segment) < 1024:
            return "male"
        
        # Take a sample from the middle
        mid = len(audio_segment) // 2
        sample = audio_segment[mid:mid+4096]
        
        # Simple zero-crossing rate as a proxy for pitch
        zcr = np.mean(np.abs(np.diff(np.sign(sample))))
        
        # Heuristic thresholds for voice types
        if zcr > 0.15:
            return "kid"
        elif zcr > 0.08:
            return "female"
        else:
            return "male"
    except Exception:
        return "male"


def transcribe_video(video_path: Path) -> list[dict[str, Any]]:
    global whisper_model, whisper_runtime
    model = _get_whisper_model()
    
    # Extract audio for gender analysis
    audio_path = PROCESSED_DIR / f"{video_path.stem}_analysis.wav"
    _extract_audio(video_path, audio_path)
    
    # We will read segments from disk on demand to save memory
    import soundfile as sf
    
    try:
        # Use beam_size=1 for faster processing
        segments, _ = model.transcribe(str(video_path), beam_size=1, vad_filter=True)
    except Exception as exc:
        if whisper_runtime.get("device") != "cuda":
            raise
        print(f"CUDA transcription failed, falling back to CPU: {exc}")
        whisper_model = None
        whisper_runtime = {}
        previous_device = os.environ.get("WHISPER_DEVICE")
        os.environ["WHISPER_DEVICE"] = "cpu"
        try:
            cpu_model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type="int8",
                cpu_threads=WHISPER_CPU_THREADS,
                num_workers=WHISPER_WORKERS,
                download_root=str(BASE_DIR / "whisper_models"),
            )
            whisper_model = cpu_model
            whisper_runtime = {"device": "cpu", "compute_type": "int8"}
            segments, _ = cpu_model.transcribe(str(video_path), beam_size=1, vad_filter=True)
        finally:
            if previous_device is None:
                os.environ.pop("WHISPER_DEVICE", None)
            else:
                os.environ["WHISPER_DEVICE"] = previous_device

    transcript: list[dict[str, Any]] = []
    
    # Open the audio file for on-demand reading
    with sf.SoundFile(str(audio_path)) as af:
        samplerate = af.samplerate
        for segment in segments:
            # Analyze segment for gender by reading only this segment's audio
            start_frame = int(segment.start * samplerate)
            end_frame = int(segment.end * samplerate)
            num_frames = end_frame - start_frame
            
            if num_frames > 0:
                af.seek(start_frame)
                segment_audio = af.read(num_frames)
                if len(segment_audio.shape) > 1:
                    segment_audio = np.mean(segment_audio, axis=1) # Mono
                gender = _estimate_gender(segment_audio, samplerate)
            else:
                gender = "male"
            
            transcript.append(
                {
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "text": segment.text.strip(),
                    "detected_gender": gender
                }
            )
            
    gc.collect()
    return transcript


def _assign_speakers(transcript: list[dict[str, Any]], speakers: list[Speaker]) -> None:
    # Map detected gender to available speakers
    male_speaker = next((s for s in speakers if s.character == "Male"), speakers[0])
    female_speaker = next((s for s in speakers if s.character == "Female"), speakers[0])
    kid_speaker = next((s for s in speakers if s.character == "Kid"), speakers[0])

    for segment in transcript:
        detected = segment.get("detected_gender", "male")
        if detected == "kid":
            speaker = kid_speaker
        elif detected == "female":
            speaker = female_speaker
        else:
            speaker = male_speaker
            
        segment["speaker_id"] = speaker.id
        segment["speaker_gender"] = speaker.gender
        segment["speaker_character"] = speaker.character


def _duck_factor(t: Any, speech_windows: list[tuple[float, float]]) -> Any:
    # Use a deeper duck for cleaner separation
    ducked = BACKGROUND_DUCKED_VOLUME * 0.5 
    normal = BACKGROUND_NORMAL_VOLUME
    
    # Add a small buffer to start ducking slightly before speech
    lead_in = 0.15 
    lead_out = 0.2
    
    if isinstance(t, np.ndarray):
        factors = np.full_like(t, normal, dtype=float)
        for start, end in speech_windows:
            factors[(t >= start - lead_in) & (t <= end + lead_out)] = ducked
        return factors[:, None]

    for start, end in speech_windows:
        if start - lead_in <= float(t) <= end + lead_out:
            return ducked
    return normal


def _make_ducked_background(
    background_path: Path | None,
    audio_clips: list[AudioFileClip],
    speech_windows: list[tuple[float, float]],
):
    if background_path is None or not background_path.exists():
        return None

    background = AudioFileClip(str(background_path))
    background = background.transform(
        lambda get_frame, t: get_frame(t) * _duck_factor(t, speech_windows)
    )
    overlays = [background, *audio_clips]
    return CompositeAudioClip(overlays)


def _write_execution_log(
    output_path: Path,
    video: VideoFileClip,
    speakers: list[Speaker],
    transcript: list[dict[str, Any]],
    status: str,
) -> Path:
    gender_split = {
        "male": sum(1 for speaker in speakers if speaker.gender == "Male"),
        "female": sum(1 for speaker in speakers if speaker.gender == "Female"),
        "child": sum(1 for speaker in speakers if speaker.gender == "Child"),
    }
    payload = {
        "status": status,
        "total_video_duration_seconds": round(float(video.duration or 0), 3),
        "speakers_detected": len(speakers),
        "speaker_gender_split": gender_split,
        "speakers": [speaker.__dict__ for speaker in speakers],
        "segments": len(transcript),
        "translated_video": str(output_path),
    }
    log_path = output_path.with_suffix(".log.json")
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


async def run_full_pipeline(video_filename: str) -> dict[str, Any]:
    return await run_full_pipeline_with_progress(video_filename)


def _mix_audio_ffmpeg(
    original_video_path: Path,
    background_path: Path | None,
    audio_clips_data: list[dict[str, Any]],
    output_audio_path: Path,
    video_duration: float
) -> bool:
    """Mix audio using FFmpeg for better performance and memory efficiency."""
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        # 1. Create a concat script for TTS clips and silences
        concat_script_path = output_audio_path.with_suffix(".concat.txt")
        
        # We need a small silence file to fill gaps
        silence_file = PROCESSED_DIR / "silence_1s.wav"
        if not silence_file.exists():
            subprocess.run([
                ffmpeg_exe, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", 
                "-t", "1", str(silence_file)
            ], check=True, capture_output=True)

        current_time = 0.0
        with open(concat_script_path, "w", encoding="utf-8") as f:
            for item in audio_clips_data:
                start = item["start"]
                # Add silence before clip if needed
                if start > current_time:
                    gap = start - current_time
                    # Use forward slashes for FFmpeg compatibility on Windows
                    silence_path_str = str(silence_file.absolute()).replace("\\", "/")
                    f.write(f"file '{silence_path_str}'\n")
                    f.write(f"duration {gap}\n")
                    current_time = start
                
                # Add the clip
                clip_path_str = str(Path(item["path"]).absolute()).replace("\\", "/")
                f.write(f"file '{clip_path_str}'\n")
                
                # We need to know the actual duration of the fitted clip
                dur = _probe_duration(Path(item["path"])) or 0.1
                current_time += dur

        # 2. Generate the concatenated Khmer voices track
        khmer_voices_path = output_audio_path.with_suffix(".khmer_voices.wav")
        subprocess.run([
            ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_script_path),
            "-c", "pcm_s16le", str(khmer_voices_path)
        ], check=True, capture_output=True)

        # 3. Mix with background and apply ducking
        # We use a sidechain compress filter or just a simple amix if background is none
        if background_path and background_path.exists():
            # sidechaincompress: background is [0:a], khmer is [1:a]
            # When [1:a] has sound, [0:a] is compressed (ducked)
            subprocess.run([
                ffmpeg_exe, "-y", "-i", str(background_path), "-i", str(khmer_voices_path),
                "-filter_complex", 
                f"[1:a]asplit[khmer1][khmer2];[0:a][khmer1]sidechaincompress=threshold=0.1:ratio=4:release=500:attack=100[bg_ducked];[bg_ducked][khmer2]amix=inputs=2:duration=first[a]",
                "-map", "[a]", "-ac", "2", "-ar", "44100", str(output_audio_path)
            ], check=True, capture_output=True)
        else:
            shutil.copyfile(khmer_voices_path, output_audio_path)

        return True
    except Exception as e:
        print(f"FFmpeg mixing failed: {e}")
        return False


def _get_video_duration(video_path: Path) -> float:
    """Use ffprobe to get video duration efficiently."""
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe_exe = ffmpeg_exe.replace("ffmpeg", "ffprobe")
        result = subprocess.run([
            ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
        ], capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except:
        return 0.0

async def run_full_pipeline_with_progress(
    video_filename: str,
    progress_callback: ProgressCallback | None = None,
    voice_cast: str = "auto",
) -> dict[str, Any]:
    async with pipeline_semaphore:
        safe_filename = _safe_filename(video_filename)
        video_path = UPLOADS_DIR / safe_filename
        output_video_path = PROCESSED_DIR / f"translated_{safe_filename}"
        started_at = time.monotonic()

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    print(f"--- Starting Khmer dubbing pipeline for {safe_filename} ---")
    _report(progress_callback, step="Analyzing speakers", progress=5, eta=None, detail="Preparing video analysis")

    # Get video duration using ffprobe
    video_duration = _get_video_duration(video_path)

    print("Step 1: Speaker diarization and gender detection...")
    speakers = detect_speakers(video_path, voice_cast)
    _report(progress_callback, step="Transcribing", progress=12, eta=None, detail="Loading Whisper and reading speech")

    print("Step 2: Speech-to-text and timestamping...")
    transcript = transcribe_video(video_path)
    _assign_speakers(transcript, speakers)
    segment_count = max(len(transcript), 1)
    
    _report(
        progress_callback,
        step="Translating",
        progress=30,
        eta=_format_eta((time.monotonic() - started_at) * 2.5),
        detail=f"{len(transcript)} speech segments found",
    )

    print("Step 3: Contextual Khmer translation...")
    translated_texts = await translate_transcript(transcript)
    for index, segment in enumerate(transcript):
        segment["khmer_text"] = translated_texts[index]
        _report(
            progress_callback,
            step="Translating",
            progress=30 + int(((index + 1) / segment_count) * 20),
            eta=_format_eta((time.monotonic() - started_at) * (segment_count - index) / max(index + 1, 1)),
            detail=f"Translated {index + 1}/{len(transcript)} segments",
        )
    gc.collect()

    print("Step 4: Khmer TTS and pacing calibration...")
    audio_clips_data: list[dict[str, Any]] = []
    tts_semaphore = asyncio.Semaphore(TTS_CONCURRENCY)

    async def build_tts(index: int, segment: dict[str, Any]) -> tuple[int, Path]:
        raw_path = PROCESSED_DIR / f"{output_video_path.stem}_raw_{index}.mp3"
        fitted_path = PROCESSED_DIR / f"{output_video_path.stem}_fit_{index}.mp3"
        speaker = next(item for item in speakers if item.id == segment["speaker_id"])
        async with tts_semaphore:
            await generate_khmer_audio(segment["khmer_text"], raw_path, speaker)

        target_duration = max(float(segment["end"]) - float(segment["start"]), 0.1)
        audio_path = _fit_audio_to_window(raw_path, fitted_path, target_duration)
        return index, audio_path

    tts_tasks = [build_tts(index, segment) for index, segment in enumerate(transcript)]
    for completed, task in enumerate(asyncio.as_completed(tts_tasks), start=1):
        index, audio_path = await task
        segment = transcript[index]
        audio_clips_data.append({
            "index": index,
            "path": audio_path,
            "start": float(segment["start"]),
            "end": float(segment["end"])
        })
        
        _report(
            progress_callback,
            step="Generating Khmer voices",
            progress=50 + int((completed / segment_count) * 25),
            eta=_format_eta((time.monotonic() - started_at) * (segment_count - completed) / max(completed, 1)),
            detail=f"Generated {completed}/{len(transcript)} voice clips",
        )

    # Sort clips by start time
    audio_clips_data.sort(key=lambda x: x["start"])

    print("Step 5: Final audio mixing and ducking...")
    _report(progress_callback, step="Mixing audio", progress=78, eta=None, detail="Suppressing original voice and keeping background")
    
    background_path = _make_voice_suppressed_background(
        video_path,
        PROCESSED_DIR / f"{output_video_path.stem}_background.wav",
    )
    
    final_audio_path = PROCESSED_DIR / f"{output_video_path.stem}_final_audio.wav"
    mix_success = _mix_audio_ffmpeg(
        video_path,
        background_path,
        audio_clips_data,
        final_audio_path,
        video_duration
    )

    if not mix_success:
        raise RuntimeError("Failed to mix audio with FFmpeg")

    _report(progress_callback, step="Rendering video", progress=88, eta=None, detail="Combining audio and video (no re-encoding)")
    
    # Use FFmpeg to combine video and audio without re-encoding video
    try:
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-y",
            "-i", str(video_path),
            "-i", str(final_audio_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_video_path)
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg video assembly failed: {e.stderr}")
        # Fallback to re-encoding if copy fails (rare)
        video = VideoFileClip(str(video_path))
        from moviepy import AudioFileClip
        final_audio = AudioFileClip(str(final_audio_path))
        final_video = video.with_audio(final_audio)
        final_video.write_videofile(str(output_video_path), codec="libx264", audio_codec="aac")
        video.close()
        final_audio.close()

    gc.collect()

    # Create dummy video object for log writing
    class DummyVideo:
        def __init__(self, dur): self.duration = dur
    
    log_path = _write_execution_log(output_video_path, DummyVideo(video_duration), speakers, transcript, "success")

    print(f"--- Pipeline finished: {output_video_path} ---")
    _report(progress_callback, step="Completed", progress=100, eta="0s", detail="Khmer dubbed video is ready")

    return {
        "status": "success",
        "original_video": str(video_path),
        "translated_video": str(output_video_path),
        "execution_log": str(log_path),
        "total_video_duration": video_duration,
        "whisper_runtime": whisper_runtime,
        "background_mode": BACKGROUND_MODE,
        "voice_cast": voice_cast,
        "speakers_detected": len(speakers),
        "speaker_gender_split": {
            "male": sum(1 for speaker in speakers if speaker.gender == "Male"),
            "female": sum(1 for speaker in speakers if speaker.gender == "Female"),
            "child": sum(1 for speaker in speakers if speaker.gender == "Child"),
        },
        "transcript": transcript,
    }
