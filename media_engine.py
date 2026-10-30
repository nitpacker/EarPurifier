import os
import sys
import shutil
import subprocess
import logging
from typing import Optional
try:
    from .dependency_manager import DependencyManager
except ImportError:
    from dependency_manager import DependencyManager

logger = logging.getLogger(__name__)

class MediaEngineError(Exception):
    pass

def get_duration(media_path: str) -> float:
    """
    Returns the duration of the media file in seconds using ffprobe.
    """
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"Media file not found: {media_path}")
    
    ffprobe_exe = DependencyManager.get_executable("ffprobe")
    if not ffprobe_exe:
        raise MediaEngineError("ffprobe is missing. Please restart the app to install it.")
        
    cmd = [
        ffprobe_exe, 
        "-v", "error", 
        "-analyzeduration", "1000000",
        "-probesize", "1000000",
        "-show_entries", "format=duration", 
        "-of", "csv=p=0", 
        media_path
    ]
    
    try:
        kwargs = {"capture_output": True, "text": True, "check": True, "timeout": 15.0}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
        result = subprocess.run(cmd, **kwargs)
        duration_val = float(result.stdout.strip())
        return max(0.0, duration_val)
    except (subprocess.SubprocessError, ValueError) as e:
        logger.error(f"ffprobe failed or timed out for {media_path}: {e}")
        raise MediaEngineError(f"Failed to get duration for {media_path}: {e}") from e

def extract_audio(video_path: str, output_flac: str) -> str:
    """
    Extracts audio from video as a 48kHz lossless FLAC.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
        
    ffmpeg_exe = DependencyManager.get_executable("ffmpeg")
    if not ffmpeg_exe:
        raise MediaEngineError("ffmpeg is missing. Please restart the app to install it.")
        
    cmd = [
        ffmpeg_exe, "-y",
        "-i", video_path,
        "-vn",
        "-c:a", "flac",
        "-ar", "48000",
        "-ac", "2",
        output_flac
    ]
    
    try:
        kwargs = {"capture_output": True, "text": True, "check": True}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
        subprocess.run(cmd, **kwargs)
        return output_flac
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg extraction failed: {e.stderr}")
        raise MediaEngineError(f"Failed to extract audio from {video_path}") from e

def pad_or_trim_audio(audio_path: str, target_duration: float, output_path: str) -> str:
    """
    Pads with silence or trims the audio to exactly match target_duration.
    Guards strictly against 0 or invalid target_duration to avoid truncating audio to 0 seconds.
    """
    ffmpeg_exe = DependencyManager.get_executable("ffmpeg")
    if not ffmpeg_exe:
        raise MediaEngineError("ffmpeg is missing. Please restart the app to install it.")

    kwargs = {"capture_output": True, "text": True, "check": True}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")

    if target_duration <= 0.0:
        logger.warning(f"Target duration is invalid ({target_duration}s). Skipping pad/trim to prevent audio destruction.")
        try:
            cmd = [ffmpeg_exe, "-y", "-i", audio_path, output_path]
            subprocess.run(cmd, **kwargs)
            return output_path
        except Exception:
            shutil.copyfile(audio_path, output_path)
            return output_path

    current_duration = get_duration(audio_path)
    cmd = [ffmpeg_exe, "-y", "-i", audio_path]
    
    if current_duration < target_duration:
        # Pad with silence
        cmd.extend(["-af", "apad", "-t", str(target_duration)])
    elif current_duration > target_duration:
        # Trim
        cmd.extend(["-t", str(target_duration)])
    else:
        # Exact match
        pass
        
    cmd.append(output_path)
    
    try:
        subprocess.run(cmd, **kwargs)
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg pad/trim failed: {e.stderr}")
        raise MediaEngineError(f"Failed to pad/trim audio {audio_path}") from e

def get_fast_aac_encoder() -> str:
    """
    Returns the fastest hardware/OS-accelerated AAC encoder available:
    - Windows: 'aac_mf' (Microsoft MediaFoundation AAC, ~58x real-time)
    - macOS:   'aac_at' (Apple AudioToolbox hardware AAC, ~60x real-time)
    - Linux / Generic Fallback: 'aac' (FFmpeg built-in native)
    """
    if sys.platform == "win32":
        return "aac_mf"
    elif sys.platform == "darwin":
        return "aac_at"
    return "aac"

def remux_video(original_video: str, clean_audio: str, output_video: str) -> str:
    """
    Remuxes original video with the new clean audio, preserving video without re-encoding.
    Uses OS-accelerated AAC encoders (aac_mf on Windows, aac_at on macOS) with automatic
    fallback to standard native aac.
    """
    ffmpeg_exe = DependencyManager.get_executable("ffmpeg")
    if not ffmpeg_exe:
        raise MediaEngineError("ffmpeg is missing. Please restart the app to install it.")

    primary_encoder = get_fast_aac_encoder()
    encoders_to_try = [primary_encoder]
    if primary_encoder != "aac":
        encoders_to_try.append("aac")

    kwargs = {"capture_output": True, "text": True, "check": True}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")

    last_error = None
    for encoder in encoders_to_try:
        cmd = [
            ffmpeg_exe, "-y",
            "-i", original_video,
            "-i", clean_audio,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-map", "0:s?",
            "-c:v", "copy",
            "-c:a", encoder,
            "-b:a", "256k",
            "-c:s", "copy",
            "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero",
            output_video
        ]
        try:
            subprocess.run(cmd, **kwargs)
            return output_video
        except subprocess.CalledProcessError as e:
            last_error = e
            logger.warning(f"Remuxing with encoder '{encoder}' failed: {e.stderr}. Trying fallback...")
            continue

    logger.error(f"ffmpeg remux failed: {last_error.stderr if last_error else 'Unknown error'}")
    raise MediaEngineError(f"Failed to remux {original_video}") from last_error
