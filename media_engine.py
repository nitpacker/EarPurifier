import os
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
        kwargs = {"capture_output": True, "text": True, "check": True, "timeout": 2.0}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
        result = subprocess.run(cmd, **kwargs)
        return float(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe failed: {e.stderr}")
        raise MediaEngineError(f"Failed to get duration for {media_path}") from e
    except ValueError as e:
        logger.error(f"Could not parse duration from ffprobe output: {result.stdout}")
        raise MediaEngineError(f"Invalid duration format for {media_path}") from e

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
    """
    current_duration = get_duration(audio_path)
    
    ffmpeg_exe = DependencyManager.get_executable("ffmpeg")
    cmd = [ffmpeg_exe, "-y", "-i", audio_path]
    
    if current_duration < target_duration:
        # Pad with silence
        cmd.extend(["-af", "apad", "-t", str(target_duration)])
    elif current_duration > target_duration:
        # Trim
        cmd.extend(["-t", str(target_duration)])
    else:
        # Exact match, just copy (though rare)
        cmd.extend(["-c:a", "copy"])
        
    cmd.append(output_path)
    
    try:
        kwargs = {"capture_output": True, "text": True, "check": True}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
        subprocess.run(cmd, **kwargs)
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg pad/trim failed: {e.stderr}")
        raise MediaEngineError(f"Failed to pad/trim audio {audio_path}") from e

def remux_video(original_video: str, clean_audio: str, output_video: str) -> str:
    """
    Remuxes original video with the new clean audio, preserving video without re-encoding.
    """
    ffmpeg_exe = DependencyManager.get_executable("ffmpeg")
    cmd = [
        ffmpeg_exe, "-y",
        "-i", original_video,
        "-i", clean_audio,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-map", "0:s?",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "256k",
        "-c:s", "copy",
        "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero",
        output_video
    ]
    
    try:
        kwargs = {"capture_output": True, "text": True, "check": True}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
        subprocess.run(cmd, **kwargs)
        return output_video
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg remux failed: {e.stderr}")
        raise MediaEngineError(f"Failed to remux {original_video}") from e
