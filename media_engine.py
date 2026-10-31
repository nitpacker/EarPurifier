import os
import sys
import shutil
import subprocess
import logging
import json
from typing import Optional

try:
    from .dependency_manager import DependencyManager
except ImportError:
    from dependency_manager import DependencyManager

logger = logging.getLogger(__name__)

class MediaEngineError(Exception):
    pass

_FASTSTART_EXTS = {".mp4", ".mov", ".m4a", ".m4b"}

_VALID_DISPOSITIONS = {
    "default", "dub", "original", "comment", "lyrics",
    "karaoke", "forced", "hearing_impaired", "visual_impaired",
    "clean_effects", "attached_pic", "captions", "descriptions",
    "dependent", "metadata",
}

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
        kwargs = {"capture_output": True, "text": True, "check": True, "timeout": 180.0}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
        result = subprocess.run(cmd, **kwargs)
        duration_val = float(result.stdout.strip())
        return max(0.0, duration_val)
    except (subprocess.SubprocessError, ValueError) as e:
        logger.error(f"ffprobe failed or timed out for {media_path}: {e}")
        raise MediaEngineError(f"Failed to get duration for {media_path}: {e}") from e

def probe_container(media_path: str) -> dict:
    """
    Probes a media file and returns a structured dict of its stream layout.
    
    Returns:
        {
            "video_streams": [...],      # list of video stream info dicts (excluding attached_pic)
            "audio_streams": [...],      # list of audio stream info dicts
            "subtitle_streams": [...],   # list of subtitle stream info dicts
            "format": {...}              # format-level metadata
        }
    """
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"Media file not found: {media_path}")

    ffprobe_exe = DependencyManager.get_executable("ffprobe")
    if not ffprobe_exe:
        raise MediaEngineError("ffprobe is missing. Please restart the app to install it.")

    cmd = [
        ffprobe_exe,
        "-v", "error",
        "-analyzeduration", "10000000",
        "-probesize", "10000000",
        "-show_streams",
        "-show_format",
        "-of", "json",
        media_path
    ]

    kwargs = {"capture_output": True, "text": True, "check": True, "timeout": 180.0}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")

    try:
        result = subprocess.run(cmd, **kwargs)
        probe_data = json.loads(result.stdout)
    except subprocess.SubprocessError as e:
        raise MediaEngineError(f"ffprobe failed for {media_path}: {e}") from e
    except json.JSONDecodeError as e:
        raise MediaEngineError(f"ffprobe returned invalid JSON for {media_path}: {e}") from e

    video_streams = []
    audio_streams = []
    subtitle_streams = []

    for stream in probe_data.get("streams", []):
        codec_type = stream.get("codec_type", "")
        if codec_type == "video":
            # Skip attached pictures (album art in audio files)
            disposition = stream.get("disposition") or {}
            if disposition.get("attached_pic", 0) == 1:
                continue
            video_streams.append(stream)
        elif codec_type == "audio":
            tags = stream.get("tags") or {}
            audio_streams.append({
                "index": stream.get("index", 0),
                "codec_name": stream.get("codec_name", "unknown"),
                "channels": stream.get("channels", 0),
                "sample_rate": stream.get("sample_rate", "0"),
                "tags": {
                    "language": tags.get("language", tags.get("LANGUAGE", "")),
                    "title": tags.get("title", tags.get("TITLE", "")),
                },
                "disposition": stream.get("disposition") or {},
            })
        elif codec_type == "subtitle":
            subtitle_streams.append(stream)

    return {
        "video_streams": video_streams,
        "audio_streams": audio_streams,
        "subtitle_streams": subtitle_streams,
        "format": probe_data.get("format") or {},
    }

def extract_audio(media_path: str, output_flac: str, stream_index: int = 0) -> str:
    """
    Extracts a specific audio stream from media as a 48kHz stereo lossless FLAC.
    Downmixing to stereo (-ac 2) is mandatory as the AI models (RoFormer, MDX23C,
    Kim Vocal) require mono/stereo frames.
    """
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"Media file not found: {media_path}")
        
    ffmpeg_exe = DependencyManager.get_executable("ffmpeg")
    if not ffmpeg_exe:
        raise MediaEngineError("ffmpeg is missing. Please restart the app to install it.")
        
    cmd = [
        ffmpeg_exe, "-y",
        "-i", media_path,
        "-map", f"0:a:{stream_index}",
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
        raise MediaEngineError(f"Failed to extract audio from {media_path}") from e

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
        
    if output_path.lower().endswith(".wav"):
        cmd.extend(["-rf64", "auto"])

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

def _get_audio_encoder_for_ext(ext: str) -> tuple:
    """
    Returns (encoder_name, [extra_args]) appropriate for the output container.
    Extra args like -b:a or -q:a will be rewritten to stream-specific flags
    (-b:a:{i}, -q:a:{i}) by remux_media.
    """
    ext = ext.lower()
    if ext in (".mp4", ".mov", ".m4a", ".m4b"):
        return get_fast_aac_encoder(), ["-b:a", "256k"]
    elif ext in (".mkv", ".mka"):
        return "flac", []
    elif ext in (".webm", ".weba"):
        return "libopus", ["-b:a", "192k"]
    elif ext == ".ogg":
        return "libvorbis", ["-q:a", "6"]
    elif ext == ".mp3":
        return "libmp3lame", ["-q:a", "0"]
    elif ext == ".flac":
        return "flac", []
    elif ext == ".wav":
        return "pcm_s16le", []
    elif ext == ".aac":
        return get_fast_aac_encoder(), ["-b:a", "256k"]
    elif ext == ".opus":
        return "libopus", ["-b:a", "192k"]
    elif ext == ".avi":
        return "mp3", ["-b:a", "256k"]
    elif ext == ".wmv":
        return "wmav2", ["-b:a", "192k"]
    elif ext == ".flv":
        return get_fast_aac_encoder(), ["-b:a", "256k"]
    else:
        return get_fast_aac_encoder(), ["-b:a", "256k"]

def remux_media(
    original_media: str,
    clean_audio: str,
    output_media: str,
    probe_result: dict,
    chosen_stream_idx: int = 0
) -> str:
    """
    Unified stream-graph remuxer for both video and audio-only containers.
    
    Replaces only the chosen audio stream with purified audio. All other
    streams (video, subtitles, other audio tracks, chapters, album art)
    are copied bit-for-bit losslessly via -map 0:v? / -map 0:s? (no-ops
    when absent) and -map_metadata 0.
    """
    ffmpeg_exe = DependencyManager.get_executable("ffmpeg")
    if not ffmpeg_exe:
        raise MediaEngineError("ffmpeg is missing. Please restart the app to install it.")

    audio_streams = probe_result.get("audio_streams", [])
    num_audio = len(audio_streams)
    # Fallback if probe_result has no audio stream entry for chosen_stream_idx
    if num_audio == 0:
        num_audio = max(1, chosen_stream_idx + 1)

    ext = os.path.splitext(output_media)[1].lower()
    encoder, extra_args = _get_audio_encoder_for_ext(ext)

    primary_encoder = encoder
    encoders_to_try = [primary_encoder]
    if primary_encoder in ("aac_mf", "aac_at") and "aac" not in encoders_to_try:
        encoders_to_try.append("aac")

    kwargs = {"capture_output": True, "text": True, "check": True}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")

    last_error = None
    for enc in encoders_to_try:
        cmd = [
            ffmpeg_exe, "-y",
            "-i", original_media,
            "-i", clean_audio,
        ]

        # Map video losslessly if present (silent no-op if absent)
        cmd.extend(["-map", "0:v?", "-c:v", "copy"])

        # Map subtitles losslessly if present (silent no-op if absent)
        cmd.extend(["-map", "0:s?", "-c:s", "copy"])

        # Map audio streams: replace chosen_stream_idx with 1:a:0, copy all others
        for i in range(num_audio):
            if i == chosen_stream_idx:
                cmd.extend(["-map", "1:a:0"])
            else:
                cmd.extend(["-map", f"0:a:{i}"])

        # Per-stream audio codec and stream-specific extra arguments
        for i in range(num_audio):
            if i == chosen_stream_idx:
                cmd.extend([f"-c:a:{i}", enc])
                for arg in extra_args:
                    if arg.startswith("-b:a"):
                        cmd.append(f"-b:a:{i}")
                    elif arg.startswith("-q:a"):
                        cmd.append(f"-q:a:{i}")
                    else:
                        cmd.append(arg)
            else:
                cmd.extend([f"-c:a:{i}", "copy"])

        # Metadata tags and disposition for each audio stream
        for i in range(num_audio):
            stream_info = audio_streams[i] if i < len(audio_streams) else {}
            tags = stream_info.get("tags") or {}
            if tags.get("language"):
                cmd.extend([f"-metadata:s:a:{i}", f"language={tags['language']}"])
            if tags.get("title"):
                cmd.extend([f"-metadata:s:a:{i}", f"title={tags['title']}"])

            disp = stream_info.get("disposition") or {}
            valid_flags = [k for k, v in disp.items() if v == 1 and k in _VALID_DISPOSITIONS]
            disp_str = "+".join(valid_flags) if valid_flags else "0"
            cmd.extend([f"-disposition:a:{i}", disp_str])

        # Preserve container metadata (chapters, album art, lyrics, etc.)
        cmd.extend(["-map_metadata", "0"])

        cmd.extend(["-avoid_negative_ts", "make_zero"])
        if ext in _FASTSTART_EXTS:
            cmd.extend(["-movflags", "+faststart"])

        cmd.append(output_media)

        try:
            subprocess.run(cmd, **kwargs)
            return output_media
        except subprocess.CalledProcessError as e:
            last_error = e
            logger.warning(f"Remuxing with encoder '{enc}' failed: {e.stderr}. Trying fallback...")
            continue

    logger.error(f"ffmpeg remux failed: {last_error.stderr if last_error else 'Unknown error'}")
    raise MediaEngineError(f"Failed to remux {original_media}") from last_error

def remux_video(original_video: str, clean_audio: str, output_video: str) -> str:
    """
    Backward compatibility wrapper around remux_media.
    """
    try:
        probe = probe_container(original_video)
    except Exception:
        probe = {"audio_streams": [{"tags": {}, "disposition": {}}], "video_streams": [{}], "subtitle_streams": []}
    return remux_media(original_video, clean_audio, output_video, probe, chosen_stream_idx=0)
