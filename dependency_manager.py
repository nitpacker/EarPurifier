import os
import re
import sys
import json
import time
import uuid
import errno
import heapq
import shutil
import socket
import _socket
import hashlib
import platform
import tempfile
import zipfile
import tarfile
import statistics
import threading
import subprocess
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple, List, Dict, Any, Callable, Set

from PySide6.QtCore import QThread, Signal
from system_utils import get_app_data_dir, get_subprocess_spawn_kwargs, get_clean_subprocess_env

logger = logging.getLogger(__name__)


def _t_safe(key: str, fallback: str, **kwargs) -> str:
    try:
        from i18n import t
        res = t(key, **kwargs)
        return fallback if res == key else res
    except Exception:
        return fallback


def is_ffmpeg_missing_error(full_output: str) -> bool:
    low = (full_output or "").lower()
    if "ffmpeg is not installed" in low or "ffmpeg is missing" in low:
        return True
    if ("filenotfounderror" in low or "winerror 2" in low or "no such file or directory" in low) and "ffmpeg" in low:
        return True
    return False


def classify_local_error(full_output: str) -> Tuple[str, str]:
    """
    Classifies raw local engine/model subprocess output into a concise, localized
    user-facing summary plus the full raw details for collapsible error dialogs.
    Returns (localized_summary, raw_details).
    """
    raw = (full_output or "").strip()
    low = raw.lower()

    if is_ffmpeg_missing_error(raw):
        return (
            _t_safe(
                "err_local_ffmpeg_missing",
                "FFmpeg was not found. EarPurifier needs FFmpeg to download models and process audio."
            ),
            raw,
        )

    if sys.platform == "win32" and (
        "dll load failed" in low
        or "msvcp140" in low
        or "vcruntime140" in low
        or "c10.dll" in low
    ):
        return (
            _t_safe(
                "err_local_vcredist_missing",
                "Your Windows system is missing the Microsoft Visual C++ Redistributable.\n\n"
                "Please download and install it from Microsoft:\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                "(Restart the app after installing)"
            ),
            raw,
        )

    if "cuda out of memory" in low or "outofmemoryerror" in low:
        return (
            _t_safe(
                "err_local_cuda_oom",
                "Your graphics card ran out of video memory (VRAM) for this model. Try MDX23C or Kim Vocal 2, or use the Cloud Engine."
            ),
            raw,
        )

    if (
        "no space left on device" in low
        or "errno 28" in low
        or "winerror 112" in low
        or "disk full" in low
    ):
        return (
            _t_safe(
                "err_local_disk_full",
                "Not enough free disk space to complete this operation."
            ),
            raw,
        )

    if (
        "sha256" in low
        or "checksum" in low
        or "hash mismatch" in low
        or "corrupt" in low
    ):
        return (
            _t_safe(
                "err_local_checksum_mismatch",
                "The downloaded file appears incomplete or corrupted. Please try again."
            ),
            raw,
        )

    if any(
        tok in low
        for tok in (
            "connectionerror",
            "newconnectionerror",
            "connectionreseterror",
            "connectionabortederror",
            "readtimeout",
            "connecttimeout",
            "timed out",
            "sslerror",
            "temporary failure in name resolution",
            "getaddrinfo failed",
            "max retries exceeded",
            "httpsconnectionpool",
            "incompleteread",
            "incomplete read",
            "chunkedencodingerror",
            "winerror 10013",
            "winerror 10054",
            "winerror 10053",
            "winerror 10060",
            "winerror 10061",
            "network error",
            "failed after",
        )
    ):
        return (
            _t_safe(
                "err_local_network_error",
                "A network error or timeout occurred while downloading. Please check your internet connection and try again."
            ),
            raw,
        )

    # Extract concise last meaningful line if available
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    tail = lines[-1] if lines else ""
    generic = _t_safe(
        "err_local_generic",
        "An error occurred while running the local engine. Open Details below for technical logs."
    )
    if tail and len(tail) <= 220:
        return (f"{generic}\n\n{tail}", raw)
    return (generic, raw)


def _normalize_cuda_driver_version(driver_ver: Any) -> Optional[Tuple[int, int]]:
    """Normalizes CUDA driver version representations into a (major, minor) tuple."""
    if driver_ver is None:
        return None
    if isinstance(driver_ver, (tuple, list)) and len(driver_ver) >= 2:
        try:
            return (int(driver_ver[0]), int(driver_ver[1]))
        except (TypeError, ValueError):
            return None
    if isinstance(driver_ver, int):
        if driver_ver <= 0:
            return None
        if driver_ver >= 1000:
            return (driver_ver // 1000, (driver_ver % 1000) // 10)
        return (driver_ver, 0)
    if isinstance(driver_ver, float):
        if driver_ver <= 0:
            return None
        major = int(driver_ver)
        minor = int(round((driver_ver - major) * 10))
        return (major, minor)
    if isinstance(driver_ver, str):
        m = re.search(r"(\d+)\.(\d+)", driver_ver)
        if m:
            return (int(m.group(1)), int(m.group(2)))
    return None


class DownloadCancelledError(InterruptedError):
    """Raised when a download is cooperatively cancelled."""


class InsufficientDiskSpaceError(OSError):
    """Raised when pre-flight or runtime checks detect insufficient free disk space."""


class ChecksumMismatchError(ValueError):
    """Raised when a downloaded file fails SHA-256 integrity verification."""


class DownloadNetworkError(IOError):
    """Raised when a download fails due to transient network/transport errors."""


class _RangeNotSupportedError(Exception):
    """Internal signal that a server returned 200 OK instead of 206 Partial Content."""


def _is_disk_full_error(exc: BaseException) -> bool:
    if isinstance(exc, InsufficientDiskSpaceError):
        return True
    if isinstance(exc, OSError):
        if getattr(exc, "errno", None) == errno.ENOSPC:
            return True
        if getattr(exc, "winerror", None) == 112:
            return True
    return False


def _is_permanent_http_error(exc: BaseException) -> bool:
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    return status in (404, 410, 451)


_NETWORK_ERRNOS: Set[int] = {
    getattr(errno, name)
    for name in (
        "ENETDOWN",
        "ENETUNREACH",
        "ENETRESET",
        "ECONNABORTED",
        "ECONNRESET",
        "ETIMEDOUT",
        "ECONNREFUSED",
        "EHOSTDOWN",
        "EHOSTUNREACH",
        "EPIPE",
    )
    if hasattr(errno, name)
}


def _is_recoverable_network_error(exc: BaseException) -> bool:
    if isinstance(exc, (DownloadCancelledError, InterruptedError, InsufficientDiskSpaceError, ChecksumMismatchError)):
        return False
    if _is_disk_full_error(exc) or _is_permanent_http_error(exc):
        return False
    if isinstance(exc, (DownloadNetworkError, ConnectionError, TimeoutError, socket.timeout, socket.gaierror)):
        return True
    mod = type(exc).__module__ or ""
    if mod.startswith("requests.") or mod.startswith("urllib3.") or mod.startswith("ssl"):
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
        if status is not None and status < 500 and status not in (401, 403, 408, 429):
            return False
        return True
    if isinstance(exc, OSError):
        # Match Winsock errors (10000..11999, including WinError 10013 which Python maps to PermissionError)
        # and POSIX network errnos — never treat local filesystem PermissionError/FileNotFoundError or
        # protocol validation IOErrors (e.g. malformed Content-Range) as transient VPN outages.
        winerr = getattr(exc, "winerror", None)
        if isinstance(winerr, int) and 10000 <= winerr <= 11999:
            return True
        if getattr(exc, "errno", None) in _NETWORK_ERRNOS:
            return True
    low = str(exc).lower()
    return any(
        tok in low
        for tok in (
            "timed out",
            "timeout",
            "connection",
            "winerror 100",
            "ssl",
            "reset by peer",
            "broken pipe",
            "getaddrinfo",
            "name resolution",
            "incomplete single-stream read",
            "incompleteread",
            "truncated chunk",
            "failed after",
        )
    )


def _extract_url_host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _cleanup_stale_partial_files(
    models_dir: str,
    filename: str,
    include_segmented_parts: bool = False,
) -> None:
    """Removes leftover audio-separator *.partial files and optionally segmented .part/.part.meta files."""
    if not models_dir or not os.path.isdir(models_dir):
        return
    try:
        prefix = f"{filename}."
        for entry in os.listdir(models_dir):
            should_remove = False
            if entry.startswith(prefix) and entry.endswith(".partial"):
                should_remove = True
            elif include_segmented_parts and entry in (f"{filename}.part", f"{filename}.part.meta"):
                should_remove = True
            if should_remove:
                try:
                    os.remove(os.path.join(models_dir, entry))
                except OSError:
                    pass
    except OSError:
        pass


def _is_transient_lock_error(exc: OSError) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerr = getattr(exc, "winerror", None)
    return winerr in (5, 32)


def _atomic_replace_file(
    src: str,
    dst: str,
    max_attempts: int = 5,
    retry_delay: float = 0.25,
) -> None:
    """
    Replaces dst with src atomically, retrying on transient PermissionError /
    Windows Defender scan locks (5 attempts, 0.25s backoff), and falling back
    to shutil.move across devices.
    """
    last_err: Optional[OSError] = None
    for attempt in range(max_attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last_err = exc
            if _is_transient_lock_error(exc):
                if attempt < max_attempts - 1:
                    time.sleep(retry_delay)
                    continue
                raise
            # Cross-device or non-lock OSError -> fall back to shutil.move with lock retry
            for move_attempt in range(max_attempts):
                try:
                    shutil.move(src, dst)
                    return
                except OSError as move_exc:
                    last_err = move_exc
                    if _is_transient_lock_error(move_exc) and move_attempt < max_attempts - 1:
                        time.sleep(retry_delay)
                        continue
                    raise
    if last_err is not None:
        raise last_err


class DependencyManager:
    _gpu_cache: Dict[str, bool] = {}

    @staticmethod
    def clear_gpu_cache() -> None:
        """Clears cached NVIDIA GPU detection results (primarily for tests)."""
        DependencyManager._gpu_cache.clear()

    @staticmethod
    def get_appdata_dir() -> str:
        return get_app_data_dir()

    @staticmethod
    def get_bin_dir() -> str:
        if sys.platform == "darwin":
            d = os.path.expanduser("~/.earpurifier/bin")
        else:
            d = os.path.join(DependencyManager.get_appdata_dir(), "bin")
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def get_env_dir() -> str:
        if sys.platform == "darwin":
            d = os.path.expanduser("~/.earpurifier/env")
            os.makedirs(os.path.dirname(d), exist_ok=True)
            return d
        elif sys.platform == "win32":
            path = os.path.join(DependencyManager.get_appdata_dir(), "env")
            if " " in path:
                try:
                    import ctypes
                    buf = ctypes.create_unicode_buffer(500)
                    if os.path.exists(path):
                        ret = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 500)
                        if ret > 0:
                            return buf.value
                    parent = os.path.dirname(path)
                    if os.path.exists(parent):
                        ret = ctypes.windll.kernel32.GetShortPathNameW(parent, buf, 500)
                        if ret > 0:
                            return os.path.join(buf.value, os.path.basename(path))
                except Exception:
                    pass
            return path
        else:
            return os.path.join(DependencyManager.get_appdata_dir(), "env")

    @staticmethod
    def get_executable(name: str) -> Optional[str]:
        ext = ".exe" if sys.platform == "win32" else ""

        # 1. Check local managed bin directory first
        local_path = os.path.join(DependencyManager.get_bin_dir(), name + ext)
        if os.path.isfile(local_path):
            if sys.platform != "win32":
                try:
                    if not os.access(local_path, os.X_OK):
                        os.chmod(local_path, 0o755)
                except Exception:
                    pass
            return local_path

        # 2. Check legacy bin directory (e.g. existing installation at ~/Library/Application Support/EarPurifier/bin)
        legacy_path = os.path.join(DependencyManager.get_appdata_dir(), "bin", name + ext)
        if os.path.isfile(legacy_path):
            if sys.platform != "win32":
                try:
                    if not os.access(legacy_path, os.X_OK):
                        os.chmod(legacy_path, 0o755)
                except Exception:
                    pass
            return legacy_path

        # 3. Check system PATH
        sys_path = shutil.which(name)
        if sys_path:
            return sys_path

        # 4. Check standard Unix / Homebrew paths (bypasses macOS GUI PATH truncation)
        if sys.platform != "win32":
            standard_dirs = [
                "/opt/homebrew/bin",
                "/usr/local/bin",
                os.path.expanduser("~/.local/bin"),
                "/usr/bin",
                "/bin",
            ]
            for sdir in standard_dirs:
                cand = os.path.join(sdir, name)
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    return cand

        return None

    @staticmethod
    def has_ffmpeg() -> bool:
        return DependencyManager.get_executable("ffmpeg") is not None and DependencyManager.get_executable("ffprobe") is not None

    @staticmethod
    def get_engine_python() -> str:
        if sys.platform == "win32":
            return os.path.join(DependencyManager.get_env_dir(), "python.exe")
        return os.path.join(DependencyManager.get_env_dir(), "bin", "python")

    @staticmethod
    def get_engine_separator_exe() -> str:
        if sys.platform == "win32":
            return os.path.join(DependencyManager.get_env_dir(), "Scripts", "audio-separator.exe")
        return os.path.join(DependencyManager.get_env_dir(), "bin", "audio-separator")

    @staticmethod
    def get_site_packages_dirs() -> List[str]:
        env_dir = DependencyManager.get_env_dir()
        candidate_site_packages: List[str] = []
        if sys.platform == "win32":
            candidate_site_packages.append(os.path.join(env_dir, "Lib", "site-packages"))
        else:
            lib_dir = os.path.join(env_dir, "lib")
            if os.path.isdir(lib_dir):
                try:
                    for entry in sorted(os.listdir(lib_dir)):
                        if entry.startswith("python"):
                            candidate_site_packages.append(os.path.join(lib_dir, entry, "site-packages"))
                except OSError:
                    pass
        return candidate_site_packages

    @staticmethod
    def get_engine_subprocess_env() -> dict:
        """
        Builds a clean, UTF-8-hardened subprocess environment for all Local Engine
        invocations (EngineDownloader, ModelDownloader, LocalJobProcessor):
        - Prepends platform-correct env_dir paths (including torch/lib on Windows if present).
        - Includes DependencyManager.get_bin_dir().
        - Dynamically injects the directories of resolved ffmpeg and ffprobe executables.
        """
        env_dir = DependencyManager.get_env_dir()
        extra_paths: List[str] = []

        if sys.platform == "win32":
            extra_paths.extend([
                env_dir,
                os.path.join(env_dir, "Library", "mingw-w64", "bin"),
                os.path.join(env_dir, "Library", "usr", "bin"),
                os.path.join(env_dir, "Library", "bin"),
                os.path.join(env_dir, "Scripts"),
            ])
            torch_lib = os.path.join(env_dir, "Lib", "site-packages", "torch", "lib")
            if os.path.isdir(torch_lib):
                extra_paths.append(torch_lib)
        else:
            extra_paths.append(os.path.join(env_dir, "bin"))

        bin_dir = DependencyManager.get_bin_dir()
        if bin_dir and bin_dir not in extra_paths:
            extra_paths.append(bin_dir)

        for tool in ("ffmpeg", "ffprobe"):
            try:
                exe = DependencyManager.get_executable(tool)
                if exe:
                    exe_dir = os.path.dirname(exe)
                    if exe_dir and exe_dir not in extra_paths:
                        extra_paths.append(exe_dir)
            except Exception:
                pass

        return get_clean_subprocess_env(extra_paths)

    @staticmethod
    def has_local_engine() -> bool:
        python_path = DependencyManager.get_engine_python()
        if not os.path.exists(python_path):
            return False

        separator_exe = DependencyManager.get_engine_separator_exe()
        if not os.path.exists(separator_exe):
            return False

        marker_file = os.path.join(DependencyManager.get_env_dir(), ".engine_installed")
        if os.path.exists(marker_file):
            return True

        # If an install/upgrade is in progress or failed before verification,
        # NEVER backfill .engine_installed from leftover site-packages.
        in_progress_file = os.path.join(DependencyManager.get_env_dir(), ".engine_in_progress")
        if os.path.exists(in_progress_file):
            return False

        # Backward compatibility / fallback: check site-packages for legacy v1.0.0 installs
        for sp in DependencyManager.get_site_packages_dirs():
            if os.path.isdir(os.path.join(sp, "audio_separator")) and os.path.isdir(os.path.join(sp, "torch")):
                try:
                    with open(marker_file, "w", encoding="utf-8") as f:
                        f.write("INSTALLED\n")
                    return True
                except Exception:
                    return True

        return False

    @staticmethod
    def has_nvidia_gpu() -> bool:
        """
        Fast, cached host NVIDIA GPU check safe for the main GUI thread.
        Never calls cuInit(0) to avoid waking discrete Optimus/MUX GPUs on laptops.
        Always returns False immediately on macOS ('darwin').
        """
        plat = sys.platform
        if plat == "darwin":
            return False

        if plat in DependencyManager._gpu_cache:
            return DependencyManager._gpu_cache[plat]

        found = False
        if plat == "win32":
            sys_root = os.environ.get("SystemRoot", "C:\\Windows")
            if os.path.exists(os.path.join(sys_root, "System32", "nvcuda.dll")):
                found = True
        elif plat.startswith("linux"):
            cuda_lib_paths = [
                "/usr/lib/x86_64-linux-gnu/libcuda.so",
                "/usr/lib/x86_64-linux-gnu/libcuda.so.1",
                "/usr/lib/aarch64-linux-gnu/libcuda.so",
                "/usr/lib/aarch64-linux-gnu/libcuda.so.1",
                "/usr/lib64/libcuda.so",
                "/usr/lib64/libcuda.so.1",
                "/usr/lib/libcuda.so",
                "/usr/lib/libcuda.so.1",
                "/usr/local/cuda",
            ]
            if any(os.path.exists(p) for p in cuda_lib_paths):
                found = True

        if not found:
            smi = shutil.which("nvidia-smi")
            if smi:
                try:
                    kwargs = get_subprocess_spawn_kwargs()
                    res = subprocess.run(
                        [smi, "-L"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=3,
                        **kwargs,
                    )
                    found = res.returncode == 0 and "GPU" in (res.stdout or "")
                except Exception:
                    found = False

        DependencyManager._gpu_cache[plat] = found
        return found

    @staticmethod
    def get_installed_torch_info() -> Dict[str, Any]:
        """
        Zero-subprocess inspection of installed PyTorch inside the local engine.
        Reads site-packages/torch/version.py directly (checking `cuda = None` vs
        CUDA string, because PyPI wheels omit `+cpu` in dist-info/METADATA).
        Falls back to torch-*.dist-info/METADATA only if version.py is absent.
        """
        for sp in DependencyManager.get_site_packages_dirs():
            version_py = os.path.join(sp, "torch", "version.py")
            if os.path.isfile(version_py):
                try:
                    with open(version_py, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    ver_match = re.search(r"""__version__\s*=\s*['"]([^'"]+)['"]""", content)
                    version_str = ver_match.group(1) if ver_match else ""

                    cuda_val: Optional[str] = None
                    cuda_none = re.search(r"""^\s*cuda\s*=\s*None\b""", content, re.MULTILINE)
                    if not cuda_none:
                        cuda_str_match = re.search(r"""^\s*cuda\s*=\s*['"]([^'"]+)['"]""", content, re.MULTILINE)
                        if cuda_str_match:
                            cuda_val = cuda_str_match.group(1)

                    return {
                        "installed": True,
                        "version": version_str,
                        "cuda": cuda_val,
                        "is_cuda": bool(cuda_val),
                    }
                except Exception as e:
                    logger.debug(f"Could not read torch/version.py at {version_py}: {e}")

        # Fallback to dist-info METADATA only when version.py is missing
        for sp in DependencyManager.get_site_packages_dirs():
            if not os.path.isdir(sp):
                continue
            try:
                for entry in os.listdir(sp):
                    if entry.startswith("torch-") and entry.endswith(".dist-info"):
                        meta_path = os.path.join(sp, entry, "METADATA")
                        if os.path.isfile(meta_path):
                            with open(meta_path, "r", encoding="utf-8", errors="replace") as f:
                                for line in f:
                                    if line.startswith("Version:"):
                                        ver = line.split(":", 1)[1].strip()
                                        cu_match = re.search(r"\+cu(\d+)", ver)
                                        cuda_val = cu_match.group(1) if cu_match else None
                                        return {
                                            "installed": True,
                                            "version": ver,
                                            "cuda": cuda_val,
                                            "is_cuda": bool(cuda_val),
                                        }
            except OSError:
                pass

        return {
            "installed": False,
            "version": "",
            "cuda": None,
            "is_cuda": False,
        }

    @staticmethod
    def needs_gpu_engine_upgrade() -> bool:
        """
        Returns True if the host has an NVIDIA GPU (non-macOS), the Local Engine is
        installed, and the installed PyTorch build lacks CUDA acceleration (e.g. v1.0.0
        users affected by the PyPI torch==2.15.0+cpu overwrite).
        """
        if sys.platform == "darwin":
            return False
        if not DependencyManager.has_local_engine():
            return False
        if not DependencyManager.has_nvidia_gpu():
            return False
        info = DependencyManager.get_installed_torch_info()
        return not info.get("is_cuda", False)

    @staticmethod
    def select_pytorch_cuda_indices(
        driver_ver: Any,
        compute_cap_major: Optional[int] = None,
        device_count: Optional[int] = None,
    ) -> List[str]:
        """
        Selects an ordered list of PyTorch CUDA 12 wheel index tags to try
        (with automatic fallback order) based on the host NVIDIA driver version,
        GPU compute capability, and active device count:
          - device_count == 0 or driver < 12.1 -> [] (install CPU cleanly)
          - Blackwell (compute_cap_major >= 10) & driver >= 12.8 -> ['cu128', 'cu126']
          - driver >= 12.6 -> ['cu126', 'cu124', 'cu121']
          - driver 12.4-12.5 -> ['cu124', 'cu121']
          - driver 12.1-12.3 or unknown driver -> ['cu121']
        """
        if device_count is not None and device_count <= 0:
            return []

        ver = _normalize_cuda_driver_version(driver_ver)
        if ver is None:
            return ["cu121"]

        if ver < (12, 1):
            return []

        if compute_cap_major is not None and compute_cap_major >= 10 and ver >= (12, 8):
            return ["cu128", "cu126"]

        if ver >= (12, 6):
            return ["cu126", "cu124", "cu121"]

        if ver >= (12, 4):
            return ["cu124", "cu121"]

        return ["cu121"]


# ─── Multi-CDN Local Model Manifest & Checksum Loader ────────────────────────

_COMMON_MODEL_SIDECARS: List[Dict[str, Any]] = [
    {
        "filename": "download_checks.json",
        "size": None,
        "sha256": None,
        "validate_json": True,
        "json_required_keys": ("vr_download_list",),
        "json_min_keys": 1,
        "mirrors": [
            ("github_raw", "https://raw.githubusercontent.com/TRvlvr/application_data/main/filelists/download_checks.json"),
            ("jsdelivr", "https://cdn.jsdelivr.net/gh/TRvlvr/application_data@main/filelists/download_checks.json"),
        ],
    },
    {
        "filename": "vr_model_data.json",
        "size": None,
        "sha256": None,
        "validate_json": True,
        "json_required_keys": (),
        "json_min_keys": 1,
        "mirrors": [
            ("github_raw", "https://raw.githubusercontent.com/TRvlvr/application_data/main/vr_model_data/model_data_new.json"),
            ("jsdelivr", "https://cdn.jsdelivr.net/gh/TRvlvr/application_data@main/vr_model_data/model_data_new.json"),
        ],
    },
    {
        "filename": "mdx_model_data.json",
        "size": None,
        "sha256": None,
        "validate_json": True,
        "json_required_keys": (),
        "json_min_keys": 1,
        "mirrors": [
            ("github_raw", "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/model_data_new.json"),
            ("jsdelivr", "https://cdn.jsdelivr.net/gh/TRvlvr/application_data@main/mdx_model_data/model_data_new.json"),
        ],
    },
]

LOCAL_MODEL_MANIFEST: Dict[str, Dict[str, Any]] = {
    "Kim_Vocal_2.onnx": {
        "primary": {
            "filename": "Kim_Vocal_2.onnx",
            "size": 66759214,
            "sha256": "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b",
            "mirrors": [
                ("github", "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/Kim_Vocal_2.onnx"),
                ("huggingface", "https://huggingface.co/Blane187/all_public_uvr_models/resolve/main/Kim_Vocal_2.onnx"),
                ("huggingface", "https://huggingface.co/seanghay/uvr_models/resolve/main/Kim_Vocal_2.onnx"),
                ("github", "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_2.onnx"),
            ],
        },
        "sidecars": list(_COMMON_MODEL_SIDECARS),
    },
    "MDX23C-8KFFT-InstVoc_HQ.ckpt": {
        "primary": {
            "filename": "MDX23C-8KFFT-InstVoc_HQ.ckpt",
            "size": 448101203,
            "sha256": "49d51472769e34a2501cd1da782346a3212555c3a5619fc2c53507445528d816",
            "mirrors": [
                ("github", "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/MDX23C-8KFFT-InstVoc_HQ.ckpt"),
                ("huggingface", "https://huggingface.co/Blane187/all_public_uvr_models/resolve/main/MDX23C-8KFFT-InstVoc_HQ.ckpt"),
                ("github", "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/MDX23C-8KFFT-InstVoc_HQ.ckpt"),
            ],
        },
        "sidecars": [
            {
                "filename": "model_2_stem_full_band_8k.yaml",
                "size": 709,
                "sha256": "451765e869b78dcb9ca9188a74da31f581b7254ff0e8b532aa76b974148de947",
                "mirrors": [
                    ("github", "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/model_2_stem_full_band_8k.yaml"),
                    ("github_raw", "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_2_stem_full_band_8k.yaml"),
                    ("jsdelivr", "https://cdn.jsdelivr.net/gh/TRvlvr/application_data@main/mdx_model_data/mdx_c_configs/model_2_stem_full_band_8k.yaml"),
                ],
            },
            *_COMMON_MODEL_SIDECARS,
        ],
    },
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": {
        "primary": {
            "filename": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "size": 639331213,
            "sha256": "5b84f37e8d444c8cb30c79d77f613a41c05868ff9c9ac6c7049c00aefae115aa",
            "mirrors": [
                ("github", "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/model_bs_roformer_ep_317_sdr_12.9755.ckpt"),
                ("huggingface", "https://huggingface.co/Blane187/all_public_uvr_models/resolve/main/model_bs_roformer_ep_317_sdr_12.9755.ckpt"),
                ("github", "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/model_bs_roformer_ep_317_sdr_12.9755.ckpt"),
            ],
        },
        "sidecars": [
            {
                "filename": "model_bs_roformer_ep_317_sdr_12.9755.yaml",
                "size": 2273,
                "sha256": "2bfdd16c656bd9519aba757cc4f8834b7ede675eb1e00ec4772d74ae1c41af7f",
                "mirrors": [
                    ("github", "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/model_bs_roformer_ep_317_sdr_12.9755.yaml"),
                    ("github_raw", "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_317_sdr_12.9755.yaml"),
                    ("jsdelivr", "https://cdn.jsdelivr.net/gh/TRvlvr/application_data@main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_317_sdr_12.9755.yaml"),
                ],
            },
            *_COMMON_MODEL_SIDECARS,
        ],
    },
}


def load_installed_model_checksums() -> Dict[str, str]:
    """
    Zero-subprocess loader for audio_separator/model-checksums.json from
    DependencyManager.get_site_packages_dirs(). Supports both {'sha256': {...}}
    and flat {filename: sha256} schemas.
    """
    checksums: Dict[str, str] = {}
    for sp in DependencyManager.get_site_packages_dirs():
        path = os.path.join(sp, "audio_separator", "model-checksums.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            mapping = data.get("sha256") if isinstance(data.get("sha256"), dict) else data
            for k, v in mapping.items():
                if isinstance(k, str) and isinstance(v, str):
                    val = v.strip().lower()
                    if len(val) == 64 and all(c in "0123456789abcdef" for c in val):
                        checksums[k] = val
            if checksums:
                return checksums
        except Exception as exc:
            logger.debug(f"Could not read model-checksums.json at {path}: {exc}")
    return checksums


def _format_download_speed(bps: float) -> str:
    """Formats bytes/sec into a concise human-readable speed string."""
    if bps <= 0:
        return ""
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{int(bps)} B/s"


def _compute_file_sha256(
    path: str,
    cancel_check: Optional[Callable[[], bool]] = None,
    block_size: int = 1024 * 1024,
) -> str:
    """Computes SHA-256 hex digest in 1 MiB blocks with cooperative cancellation."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if cancel_check and cancel_check():
                raise DownloadCancelledError("Download cancelled during verification")
            buf = f.read(block_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest().lower()


def _validate_json_file(
    path: str,
    required_keys: Optional[Tuple[str, ...]] = None,
    min_keys: int = 0,
) -> bool:
    """Verifies a JSON metadata file parses cleanly as a dict with required keys."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
        if len(data) < min_keys:
            return False
        if required_keys:
            for key in required_keys:
                if key not in data:
                    return False
        return True
    except Exception:
        return False


class _SegmentedFileDownloader:
    """
    Reusable, thread-safe, resumable multi-CDN segmented HTTP downloader:
    - Idempotent pre-check & self-healing for SHA-256 / JSON files.
    - Pre-flight disk space guard (remaining_bytes + 64 MiB for files > 4 MiB).
    - HEAD / GET Range:0-0 mirror probing with Accept-Encoding: identity.
    - 6-worker sequential HTTP 206 Range transfer (4 MiB chunks, 64 KiB read blocks)
      with per-thread requests.Session, intact OS TCP receive-window auto-tuning,
      instant socket close on cancel(), and zero upfront truncate.
    - Strict 206 enforcement with clean single-stream fallback on HTTP 200.
    - Slow-ISP-safe true-stall (<4 KiB/s for 15s) & relative straggler
      (<32 KiB/s for 10s AND <15% of other workers' median) watchdogs.
    - HTTP 401/403 SAS refresh under lock, graceful anti-thrash cross-CDN failover,
      and interruptible VPN/network recovery with seamless .part resume.
    - Full SHA-256 / JSON verification and Windows Defender-safe atomic promotion.
    """

    DEFAULT_WORKERS = 6
    DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
    DEFAULT_READ_BLOCK_SIZE = 65536
    MIN_SEGMENTED_SIZE = 4 * 1024 * 1024
    DISK_SPACE_BUFFER_BYTES = 64 * 1024 * 1024
    CONNECT_TIMEOUT = 8.0
    PROBE_CONNECT_TIMEOUT = 6.0
    READ_TIMEOUT = 20.0
    PROBE_READ_TIMEOUT = 10.0
    TRUE_STALL_MIN_BPS = 4 * 1024
    TRUE_STALL_SECONDS = 15.0
    STRAGGLER_MAX_BPS = 32 * 1024
    STRAGGLER_SECONDS = 10.0
    STRAGGLER_RATIO = 0.15
    CDN_FAILOVER_MAX_BPS = 768 * 1024
    CDN_FAILOVER_SECONDS = 12.0
    CDN_FAILOVER_STALL_COUNT = 2
    SPEED_WINDOW_SECONDS = 5.0
    MAX_CHUNK_RETRIES = 6
    MAX_SAS_REFRESHES = 3
    PROGRESS_INTERVAL = 0.35
    NETWORK_RECOVERY_BACKOFF: Tuple[float, ...] = (2.0, 4.0, 6.0, 8.0, 10.0)

    _CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)

    def __init__(
        self,
        workers: int = DEFAULT_WORKERS,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        read_block_size: int = DEFAULT_READ_BLOCK_SIZE,
        min_segmented_size: int = MIN_SEGMENTED_SIZE,
        disk_space_buffer_bytes: int = DISK_SPACE_BUFFER_BYTES,
        connect_timeout: float = CONNECT_TIMEOUT,
        probe_connect_timeout: Optional[float] = None,
        read_timeout: float = READ_TIMEOUT,
        probe_read_timeout: float = PROBE_READ_TIMEOUT,
        true_stall_min_bps: float = TRUE_STALL_MIN_BPS,
        true_stall_seconds: float = TRUE_STALL_SECONDS,
        straggler_max_bps: float = STRAGGLER_MAX_BPS,
        straggler_seconds: float = STRAGGLER_SECONDS,
        straggler_ratio: float = STRAGGLER_RATIO,
        cdn_failover_max_bps: float = CDN_FAILOVER_MAX_BPS,
        cdn_failover_seconds: float = CDN_FAILOVER_SECONDS,
        cdn_failover_stall_count: int = CDN_FAILOVER_STALL_COUNT,
        max_chunk_retries: int = MAX_CHUNK_RETRIES,
        progress_interval: float = PROGRESS_INTERVAL,
        network_recovery_backoff: Tuple[float, ...] = NETWORK_RECOVERY_BACKOFF,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        self.workers = max(1, int(workers))
        self.chunk_size = max(1024, int(chunk_size))
        self.read_block_size = max(1024, int(read_block_size))
        self.min_segmented_size = max(1024, int(min_segmented_size))
        self.disk_space_buffer_bytes = max(0, int(disk_space_buffer_bytes))
        self.connect_timeout = float(connect_timeout)
        self.probe_connect_timeout = (
            float(probe_connect_timeout)
            if probe_connect_timeout is not None
            else min(float(connect_timeout), self.PROBE_CONNECT_TIMEOUT)
        )
        self.read_timeout = float(read_timeout)
        self.probe_read_timeout = float(probe_read_timeout)
        self.true_stall_min_bps = float(true_stall_min_bps)
        self.true_stall_seconds = float(true_stall_seconds)
        self.straggler_max_bps = float(straggler_max_bps)
        self.straggler_seconds = float(straggler_seconds)
        self.straggler_ratio = float(straggler_ratio)
        self.cdn_failover_max_bps = float(cdn_failover_max_bps)
        self.cdn_failover_seconds = float(cdn_failover_seconds)
        self.cdn_failover_stall_count = max(1, int(cdn_failover_stall_count))
        self.max_chunk_retries = max(1, int(max_chunk_retries))
        self.progress_interval = max(0.05, float(progress_interval))
        self.network_recovery_backoff = tuple(max(0.0, float(x)) for x in network_recovery_backoff)
        self._cancel_check = cancel_check

        self._cancel_event = threading.Event()
        self._thread_local = threading.local()
        self._active_sockets_lock = threading.Lock()
        self._active_sockets: Set[Any] = set()
        self._thread_sockets: Dict[int, Set[Any]] = {}
        self._thread_abort_events: Dict[int, threading.Event] = {}
        self._active_responses_lock = threading.Lock()
        self._active_responses: Set[Any] = set()
        self._active_sessions_lock = threading.Lock()
        self._all_sessions: List[Any] = []
        self._refresh_lock = threading.Lock()
        self._cancel_callbacks_lock = threading.Lock()
        self._cancel_callbacks: List[Callable[[], None]] = []
        self.last_failed_hosts: Set[str] = set()
        self.last_succeeded_hosts: Set[str] = set()

    def _is_thread_aborted(self, tid: Optional[int] = None) -> bool:
        if self.is_cancelled():
            return True
        if tid is None:
            tid = threading.get_ident()
        with self._active_sockets_lock:
            ev = self._thread_abort_events.get(tid)
        return ev is not None and ev.is_set()

    def is_cancelled(self) -> bool:
        if self._cancel_event.is_set():
            return True
        if self._cancel_check is not None:
            try:
                if self._cancel_check():
                    self._cancel_event.set()
                    return True
            except Exception:
                pass
        return False

    def _add_cancel_callback(self, cb: Callable[[], None]) -> None:
        with self._cancel_callbacks_lock:
            self._cancel_callbacks.append(cb)
        if self.is_cancelled():
            try:
                cb()
            except Exception:
                pass

    def _remove_cancel_callback(self, cb: Callable[[], None]) -> None:
        with self._cancel_callbacks_lock:
            try:
                self._cancel_callbacks.remove(cb)
            except ValueError:
                pass

    def cancel(self) -> None:
        """Immediately aborts all active requests (both pre-header and mid-body) without blocking."""
        self._cancel_event.set()
        with self._cancel_callbacks_lock:
            callbacks = list(self._cancel_callbacks)
        for cb in callbacks:
            try:
                cb()
            except Exception:
                pass
        with self._active_sockets_lock:
            sockets = list(self._active_sockets)
        with self._active_responses_lock:
            responses = list(self._active_responses)
        for sock in sockets:
            self._abort_socket(sock)
        for resp in responses:
            self._abort_response_socket(resp)

    @staticmethod
    def _abort_socket(sock: Any) -> None:
        """Non-blocking OS-level shutdown + close for a plain or SSL socket."""
        if sock is None:
            return
        inner = getattr(sock, "_sock", None)
        seen_ids = set()
        for s in (sock, inner):
            if s is None or id(s) in seen_ids:
                continue
            seen_ids.add(id(s))
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                if isinstance(s, _socket.socket):
                    _socket.socket.close(s)
                else:
                    s.close()
            except Exception:
                pass

    @classmethod
    def _abort_response_socket(cls, resp: Any) -> None:
        """
        Cross-thread non-blocking socket abort for requests/urllib3 responses.
        Bypasses BufferedReader's internal lock (which would block callers up to READ_TIMEOUT)
        and forces OS-level shutdown + closesocket even when socket._io_refs > 0.
        """
        if resp is None:
            return
        candidates = []
        raw = getattr(resp, "raw", None)
        if raw is not None:
            conn = getattr(raw, "_connection", None)
            if conn is not None:
                csock = getattr(conn, "sock", None)
                if csock is not None:
                    candidates.append(csock)
            fp = getattr(raw, "_fp", None)
            if fp is not None:
                fp_inner = getattr(fp, "fp", None)
                fp_raw = getattr(fp_inner, "raw", None) if fp_inner is not None else None
                fsock = getattr(fp_raw, "_sock", None) if fp_raw is not None else None
                if fsock is not None:
                    candidates.append(fsock)

        seen_ids = set()
        aborted_any = False
        for sock in candidates:
            if sock is None or id(sock) in seen_ids:
                continue
            seen_ids.add(id(sock))
            aborted_any = True
            cls._abort_socket(sock)

        if not aborted_any:
            try:
                resp.close()
            except Exception:
                pass

    @staticmethod
    def _close_response_safe(resp: Any) -> None:
        """Owner-thread cleanup for a completed or already-aborted response."""
        if resp is None:
            return
        try:
            resp.close()
        except Exception:
            pass

    def _register_socket(self, sock: Any, tid: Optional[int] = None) -> None:
        if sock is None:
            return
        if tid is None:
            tid = threading.get_ident()
        with self._active_sockets_lock:
            self._active_sockets.add(sock)
            self._thread_sockets.setdefault(tid, set()).add(sock)
        if self.is_cancelled():
            self._abort_socket(sock)

    def _unregister_socket(self, sock: Any) -> None:
        if sock is None:
            return
        with self._active_sockets_lock:
            self._active_sockets.discard(sock)
            empty_tids = []
            for tid, sock_set in self._thread_sockets.items():
                sock_set.discard(sock)
                if not sock_set:
                    empty_tids.append(tid)
            for tid in empty_tids:
                self._thread_sockets.pop(tid, None)

    def _snapshot_thread_sockets(self, tids: List[int]) -> List[Any]:
        """Snapshots live/connecting socket objects owned by `tids` so aborting never kills newer sockets."""
        if not tids:
            return []
        out: List[Any] = []
        seen: Set[int] = set()
        with self._active_sockets_lock:
            for tid in tids:
                for sock in self._thread_sockets.get(tid, ()):
                    sid = id(sock)
                    if sid not in seen:
                        seen.add(sid)
                        out.append(sock)
        return out

    def _abort_thread_sockets(self, tid: Optional[int]) -> None:
        """Aborts all live/connecting sockets owned by a specific worker thread."""
        if tid is None:
            return
        for sock in self._snapshot_thread_sockets([tid]):
            self._abort_socket(sock)

    def _register_response(self, resp: Any) -> None:
        with self._active_responses_lock:
            self._active_responses.add(resp)
        if self.is_cancelled():
            self._abort_response_socket(resp)

    def _unregister_response(self, resp: Any) -> None:
        with self._active_responses_lock:
            self._active_responses.discard(resp)

    def _build_abortable_adapter(self):
        """
        Builds a scoped requests HTTPAdapter whose HTTP/HTTPS connections:
        - Use deadline-bounded, IPv4-interleaved connect() so multi-AAAA IPv6
          blackholes never stall for 80s+ at 0%.
        - Register live sockets BEFORE TCP connect() so cancel() and per-worker
          failover/stall aborts interrupt pre-header probes, SYN handshakes, TLS
          handshakes, and slow TTFB reads instantaneously without global patching.
        """
        from requests.adapters import HTTPAdapter
        import urllib3.exceptions as u3_exc
        from urllib3.connection import HTTPConnection, HTTPSConnection
        from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

        downloader = self
        NameResErr = getattr(u3_exc, "NameResolutionError", u3_exc.NewConnectionError)

        def _connect_bounded(conn):
            tid = threading.get_ident()
            if downloader._is_thread_aborted(tid):
                raise u3_exc.NewConnectionError(conn, "Download cancelled")

            raw_host = getattr(conn, "_dns_host", conn.host) or conn.host
            dns_host = raw_host.strip("[]")
            port = conn.port
            raw_timeout = conn.timeout
            if isinstance(raw_timeout, (int, float)) and raw_timeout > 0:
                total_timeout = float(raw_timeout)
            else:
                total_timeout = downloader.connect_timeout

            try:
                infos = socket.getaddrinfo(dns_host, port, 0, socket.SOCK_STREAM)
            except socket.gaierror as exc:
                if NameResErr is u3_exc.NewConnectionError:
                    raise u3_exc.NewConnectionError(conn, f"Failed to resolve '{conn.host}': {exc}") from exc
                raise NameResErr(conn.host, conn, exc) from exc

            if downloader._is_thread_aborted(tid):
                raise u3_exc.NewConnectionError(conn, "Download cancelled")

            if not infos:
                raise u3_exc.NewConnectionError(conn, f"getaddrinfo returned empty list for {conn.host}")

            # Interleave IPv4-first with IPv6/other so blackholed IPv6 AAAA records never stall IPv4
            v4_infos = [res for res in infos if res[0] == socket.AF_INET]
            other_infos = [res for res in infos if res[0] != socket.AF_INET]
            ordered: List[Any] = []
            max_len = max(len(v4_infos), len(other_infos))
            for i in range(max_len):
                if i < len(v4_infos):
                    ordered.append(v4_infos[i])
                if i < len(other_infos):
                    ordered.append(other_infos[i])

            deadline = time.monotonic() + total_timeout
            last_err: Optional[BaseException] = None
            saw_timeout = False

            for idx, (af, socktype, proto, _canon, sa) in enumerate(ordered):
                if downloader._is_thread_aborted(tid):
                    raise u3_exc.NewConnectionError(conn, "Download cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    saw_timeout = True
                    break

                per_ip_timeout = min(3.5, remaining) if (len(ordered) > 1 and idx < len(ordered) - 1) else remaining
                per_ip_timeout = max(0.15, per_ip_timeout)

                sock = None
                try:
                    sock = socket.socket(af, socktype, proto)
                    if getattr(conn, "socket_options", None):
                        for opt in conn.socket_options:
                            try:
                                sock.setsockopt(*opt)
                            except OSError:
                                pass
                    try:
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    except OSError:
                        pass
                    # Preserve OS TCP receive-window auto-tuning (do NOT set SO_RCVBUF,
                    # which disables Windows TCP auto-tuning and caps high-BDP throughput).

                    sock.settimeout(per_ip_timeout)
                    downloader._register_socket(sock, tid=tid)
                    if getattr(conn, "source_address", None):
                        sock.bind(conn.source_address)
                    sock.connect(sa)

                    if downloader._is_thread_aborted(tid):
                        downloader._unregister_socket(sock)
                        downloader._abort_socket(sock)
                        raise u3_exc.NewConnectionError(conn, "Download cancelled")

                    if raw_timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                        sock.settimeout(raw_timeout)
                    tracked = getattr(conn, "_ep_tracked_socks", None)
                    if tracked is None:
                        tracked = []
                        conn._ep_tracked_socks = tracked
                    tracked.append(sock)
                    try:
                        sys.audit("http.client.connect", conn, conn.host, conn.port)
                    except Exception:
                        pass
                    return sock
                except socket.timeout as exc:
                    saw_timeout = True
                    last_err = exc
                    if sock is not None:
                        downloader._unregister_socket(sock)
                        try:
                            sock.close()
                        except Exception:
                            pass
                except OSError as exc:
                    last_err = exc
                    if sock is not None:
                        downloader._unregister_socket(sock)
                        try:
                            sock.close()
                        except Exception:
                            pass
                    if downloader._is_thread_aborted(tid):
                        raise u3_exc.NewConnectionError(conn, "Download cancelled") from exc

            if saw_timeout and (last_err is None or isinstance(last_err, socket.timeout)):
                raise u3_exc.ConnectTimeoutError(
                    conn,
                    f"Connection to {conn.host} timed out. (connect timeout={total_timeout})",
                ) from last_err
            raise u3_exc.NewConnectionError(
                conn, f"Failed to establish a new connection: {last_err}"
            ) from last_err

        class _TrackedHTTPConnection(HTTPConnection):
            def _new_conn(self):
                return _connect_bounded(self)

            def connect(self):
                super().connect()
                if self.sock is not None:
                    tracked = getattr(self, "_ep_tracked_socks", None)
                    if tracked is None:
                        tracked = []
                        self._ep_tracked_socks = tracked
                    tracked.append(self.sock)
                    downloader._register_socket(self.sock)

            def close(self):
                tracked = getattr(self, "_ep_tracked_socks", None)
                if tracked:
                    for s in list(tracked):
                        downloader._unregister_socket(s)
                    tracked.clear()
                if getattr(self, "sock", None) is not None:
                    downloader._unregister_socket(self.sock)
                super().close()

        class _TrackedHTTPSConnection(HTTPSConnection):
            def _new_conn(self):
                return _connect_bounded(self)

            def connect(self):
                super().connect()
                if self.sock is not None:
                    tracked = getattr(self, "_ep_tracked_socks", None)
                    if tracked is None:
                        tracked = []
                        self._ep_tracked_socks = tracked
                    tracked.append(self.sock)
                    downloader._register_socket(self.sock)

            def close(self):
                tracked = getattr(self, "_ep_tracked_socks", None)
                if tracked:
                    for s in list(tracked):
                        downloader._unregister_socket(s)
                    tracked.clear()
                if getattr(self, "sock", None) is not None:
                    downloader._unregister_socket(self.sock)
                super().close()

        class _TrackedHTTPPool(HTTPConnectionPool):
            ConnectionCls = _TrackedHTTPConnection

        class _TrackedHTTPSPool(HTTPSConnectionPool):
            ConnectionCls = _TrackedHTTPSConnection

        class _AbortableHTTPAdapter(HTTPAdapter):
            def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
                super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)
                self.poolmanager.pool_classes_by_scheme = {
                    "http": _TrackedHTTPPool,
                    "https": _TrackedHTTPSPool,
                }

        pool_sz = max(8, self.workers)
        return _AbortableHTTPAdapter(pool_connections=pool_sz, pool_maxsize=pool_sz)

    def _get_session(self):
        sess = getattr(self._thread_local, "session", None)
        if sess is None:
            import requests
            sess = requests.Session()
            try:
                adapter = self._build_abortable_adapter()
                sess.mount("http://", adapter)
                sess.mount("https://", adapter)
            except Exception:
                pass
            sess.headers.update({
                "User-Agent": "EarPurifier/1.0",
                "Accept-Encoding": "identity",
            })
            self._thread_local.session = sess
            with self._active_sessions_lock:
                self._all_sessions.append(sess)
        return sess

    def _reset_thread_session(self) -> None:
        """Closes and discards the calling thread's Session so stale pre-VPN pools are recreated."""
        sess = getattr(self._thread_local, "session", None)
        if sess is not None:
            try:
                delattr(self._thread_local, "session")
            except Exception:
                self._thread_local.session = None
            with self._active_sessions_lock:
                try:
                    self._all_sessions.remove(sess)
                except ValueError:
                    pass
            try:
                sess.close()
            except Exception:
                pass

    def _close_all_sessions(self) -> None:
        with self._active_sessions_lock:
            sessions = list(self._all_sessions)
            self._all_sessions.clear()
        for sess in sessions:
            try:
                sess.close()
            except Exception:
                pass
        with self._active_sockets_lock:
            self._active_sockets.clear()
            self._thread_sockets.clear()
        if hasattr(self._thread_local, "session"):
            try:
                delattr(self._thread_local, "session")
            except Exception:
                pass

    @staticmethod
    def _parse_int_header(val: Optional[str]) -> Optional[int]:
        if val is None:
            return None
        s = str(val).strip()
        if s.isdigit():
            return int(s)
        return None

    def _probe_mirror(
        self,
        url: str,
        expected_size: Optional[int] = None,
    ) -> Tuple[str, Optional[int], bool]:
        """
        Probes a mirror via HEAD (fallback GET Range: bytes=0-0 only when HEAD
        is unsupported or lacks range/size headers — never doubling timeouts on
        transport/connect errors). Returns (resolved_url, total_size, accept_ranges).
        """
        if self.is_cancelled():
            raise DownloadCancelledError("Download cancelled")

        sess = self._get_session()
        headers = {"Accept-Encoding": "identity", "User-Agent": "EarPurifier/1.0"}
        timeout = (self.probe_connect_timeout, self.probe_read_timeout)

        resolved_url = url
        total_size: Optional[int] = None
        accept_ranges = False
        head_ok = False

        try:
            resp = sess.head(url, headers=headers, allow_redirects=True, timeout=timeout)
            self._register_response(resp)
            try:
                if 200 <= resp.status_code < 400:
                    head_ok = True
                    resolved_url = resp.url or url
                    total_size = self._parse_int_header(resp.headers.get("Content-Length"))
                    ar = (resp.headers.get("Accept-Ranges") or "").lower()
                    accept_ranges = "bytes" in ar
                elif resp.status_code in (404, 410, 451):
                    resp.raise_for_status()
            finally:
                self._unregister_response(resp)
                self._close_response_safe(resp)
        except Exception as exc:
            if self.is_cancelled():
                raise DownloadCancelledError("Download cancelled") from exc
            if _is_permanent_http_error(exc):
                raise
            # Transport / connect / read timeout: do NOT double-hang by sending GET to the same dead host!
            self._reset_thread_session()
            raise

        need_range_probe = (
            not head_ok
            or (
                not accept_ranges
                and (
                    (total_size is not None and total_size > self.min_segmented_size)
                    or (expected_size is not None and expected_size > self.min_segmented_size)
                )
            )
        )

        if need_range_probe:
            if self.is_cancelled():
                raise DownloadCancelledError("Download cancelled")
            probe_headers = dict(headers)
            probe_headers["Range"] = "bytes=0-0"
            try:
                resp = sess.get(url, headers=probe_headers, stream=True, allow_redirects=True, timeout=timeout)
            except Exception as exc:
                if self.is_cancelled():
                    raise DownloadCancelledError("Download cancelled") from exc
                self._reset_thread_session()
                raise
            self._register_response(resp)
            try:
                if resp.status_code == 206:
                    accept_ranges = True
                    resolved_url = resp.url or url
                    cr = (resp.headers.get("Content-Range") or "").strip()
                    m = self._CONTENT_RANGE_RE.match(cr)
                    if m and m.group(3) != "*":
                        total_size = int(m.group(3))
                    elif total_size is None:
                        total_size = self._parse_int_header(resp.headers.get("Content-Length"))
                elif resp.status_code == 200:
                    accept_ranges = False
                    resolved_url = resp.url or url
                    total_size = self._parse_int_header(resp.headers.get("Content-Length"))
                else:
                    resp.raise_for_status()
            finally:
                self._unregister_response(resp)
                self._close_response_safe(resp)

        if expected_size is not None and total_size is not None and total_size != expected_size:
            raise ValueError(
                f"Mirror size mismatch for {url}: expected {expected_size} bytes, got {total_size} bytes"
            )

        return resolved_url, total_size, accept_ranges

    def _check_disk_space(self, dest_dir: str, total_size: Optional[int], already_on_disk: int = 0) -> None:
        if total_size is None or total_size <= self.min_segmented_size:
            return
        remaining = max(0, int(total_size) - max(0, int(already_on_disk)))
        required = remaining + self.disk_space_buffer_bytes
        os.makedirs(dest_dir, exist_ok=True)
        free = shutil.disk_usage(dest_dir).free
        if free < required:
            need_mb = max(1, (required + (1024 * 1024 - 1)) // (1024 * 1024))
            free_mb = free // (1024 * 1024)
            raise InsufficientDiskSpaceError(
                errno.ENOSPC,
                f"No space left on device: need {need_mb} MiB free, only {free_mb} MiB available in {dest_dir}",
            )

    @staticmethod
    def _remove_quiet(path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _chunk_bounds(self, chunk_idx: int, total_size: int) -> Tuple[int, int, int]:
        start = chunk_idx * self.chunk_size
        end = min(total_size - 1, start + self.chunk_size - 1)
        return start, end, (end - start + 1)

    def _validate_resume_state_readonly(
        self,
        part_path: str,
        meta_path: str,
        total_size: int,
        expected_sha256: Optional[str],
    ) -> Set[int]:
        """
        Strictly validates .part and .part.meta (version, size, sha256, chunk_size,
        chunk indices, and .part file bounds) without deleting files.
        Raises ValueError / OSError on any mismatch or corruption.
        """
        if total_size <= 0:
            raise ValueError("invalid total_size")
        if not (os.path.isfile(part_path) and os.path.isfile(meta_path)):
            raise ValueError("missing part or meta file")

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            raise ValueError("meta not dict")
        if meta.get("version") != 1:
            raise ValueError("meta version mismatch")
        if meta.get("expected_size") != total_size:
            raise ValueError("meta expected_size mismatch")
        if meta.get("sha256") != (expected_sha256 or "").lower():
            raise ValueError("meta sha256 mismatch")
        if meta.get("chunk_size") != self.chunk_size:
            raise ValueError("meta chunk_size mismatch")

        raw_completed = meta.get("completed")
        if not isinstance(raw_completed, list):
            raise ValueError("meta completed not list")

        num_chunks = (total_size + self.chunk_size - 1) // self.chunk_size
        completed: Set[int] = set()
        max_completed_end = 0
        for idx in raw_completed:
            if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0 or idx >= num_chunks:
                raise ValueError(f"invalid chunk index: {idx}")
            completed.add(idx)
            _, end, _ = self._chunk_bounds(idx, total_size)
            if end + 1 > max_completed_end:
                max_completed_end = end + 1

        file_size = os.path.getsize(part_path)
        if not (max_completed_end <= file_size <= total_size):
            raise ValueError(
                f"part file size out of bounds: max_completed_end={max_completed_end}, "
                f"file_size={file_size}, expected_size={total_size}"
            )
        if len(completed) == num_chunks and file_size != total_size:
            raise ValueError("all chunks marked complete but part size != total_size")

        return completed

    def _load_resume_state(
        self,
        part_path: str,
        meta_path: str,
        total_size: int,
        expected_sha256: Optional[str],
    ) -> Set[int]:
        """
        Validates .part and .part.meta before resuming. Rejects and purges any
        mismatched, corrupt, or truncated state.
        """
        if not (os.path.isfile(part_path) and os.path.isfile(meta_path)):
            self._remove_quiet(part_path)
            self._remove_quiet(meta_path)
            return set()

        try:
            return self._validate_resume_state_readonly(part_path, meta_path, total_size, expected_sha256)
        except Exception as exc:
            logger.info(f"Discarding stale/invalid resume state for {part_path}: {exc}")
            self._remove_quiet(part_path)
            self._remove_quiet(meta_path)
            return set()

    def _save_resume_meta(
        self,
        meta_path: str,
        total_size: int,
        expected_sha256: Optional[str],
        completed_chunks: Set[int],
    ) -> None:
        payload = {
            "version": 1,
            "expected_size": total_size,
            "sha256": (expected_sha256 or "").lower(),
            "chunk_size": self.chunk_size,
            "completed": sorted(completed_chunks),
        }
        tmp_path = f"{meta_path}.tmp.{uuid.uuid4().hex[:8]}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
                f.flush()
            _atomic_replace_file(tmp_path, meta_path)
        finally:
            self._remove_quiet(tmp_path)

    @staticmethod
    def _window_speed_bps(samples: deque, now: float, window_sec: float, min_span: float = 0.25) -> float:
        """Read-only rolling speed (bytes/sec) over the last `window_sec` seconds without mutating `samples`."""
        cutoff = now - window_sec
        total_bytes = 0
        oldest_in_window: Optional[float] = None
        for ts, n in reversed(samples):
            if ts < cutoff:
                break
            total_bytes += n
            oldest_in_window = ts
        if oldest_in_window is None:
            return 0.0
        span = max(min_span, min(window_sec, now - oldest_in_window))
        return total_bytes / span

    @staticmethod
    def _window_bytes_over_duration(samples: deque, now: float, window_sec: float) -> float:
        """Read-only rolling average bytes/sec over the last `window_sec` seconds."""
        cutoff = now - window_sec
        total_bytes = 0
        for ts, n in reversed(samples):
            if ts < cutoff:
                break
            total_bytes += n
        return total_bytes / max(0.001, window_sec)

    @staticmethod
    def _prune_samples(samples: deque, now: float, max_age: float) -> None:
        cutoff = now - max_age
        while samples and samples[0][0] < cutoff:
            samples.popleft()

    def _verify_existing_file(
        self,
        dest_path: str,
        expected_size: Optional[int],
        expected_sha256: Optional[str],
        validate_json: bool,
        json_required_keys: Optional[Tuple[str, ...]],
        json_min_keys: int,
    ) -> bool:
        if not os.path.isfile(dest_path):
            return False

        try:
            fsize = os.path.getsize(dest_path)
        except OSError:
            return False

        if fsize <= 0:
            self._remove_quiet(dest_path)
            return False

        if expected_sha256:
            if expected_size is not None and fsize != expected_size:
                logger.warning(
                    f"Existing file {dest_path} size mismatch ({fsize} != {expected_size}); deleting to re-download."
                )
                self._remove_quiet(dest_path)
                return False
            actual = _compute_file_sha256(dest_path, cancel_check=self.is_cancelled)
            if actual == expected_sha256.lower():
                return True
            logger.warning(f"Existing file {dest_path} failed SHA-256 verification; deleting to re-download.")
            self._remove_quiet(dest_path)
            return False

        if validate_json or json_required_keys is not None:
            if _validate_json_file(dest_path, json_required_keys, json_min_keys):
                return True
            logger.warning(f"Existing JSON file {dest_path} is invalid/corrupt; deleting to re-download.")
            self._remove_quiet(dest_path)
            return False

        return False

    def _verify_and_promote(
        self,
        part_path: str,
        meta_path: str,
        dest_path: str,
        expected_size: Optional[int],
        expected_sha256: Optional[str],
        validate_json: bool,
        json_required_keys: Optional[Tuple[str, ...]],
        json_min_keys: int,
        progress_cb: Optional[Callable[[int, Optional[int], float, str], None]],
    ) -> None:
        if self.is_cancelled():
            raise DownloadCancelledError("Download cancelled")

        actual_size = os.path.getsize(part_path)
        if expected_size is not None and actual_size != expected_size:
            self._remove_quiet(part_path)
            self._remove_quiet(meta_path)
            raise ValueError(
                f"Downloaded file size mismatch for {os.path.basename(dest_path)}: "
                f"expected {expected_size}, got {actual_size}"
            )

        if expected_sha256:
            if progress_cb:
                progress_cb(actual_size, expected_size or actual_size, 0.0, "verifying")
            actual_hash = _compute_file_sha256(part_path, cancel_check=self.is_cancelled)
            if actual_hash != expected_sha256.lower():
                self._remove_quiet(part_path)
                self._remove_quiet(meta_path)
                raise ChecksumMismatchError(
                    f"SHA256 checksum mismatch for {os.path.basename(dest_path)}: "
                    f"expected {expected_sha256.lower()}, got {actual_hash}"
                )
        elif validate_json or json_required_keys is not None:
            if not _validate_json_file(part_path, json_required_keys, json_min_keys):
                self._remove_quiet(part_path)
                self._remove_quiet(meta_path)
                raise ValueError(f"Corrupt or invalid JSON metadata downloaded for {os.path.basename(dest_path)}")

        _atomic_replace_file(part_path, dest_path)
        self._remove_quiet(meta_path)

    def _download_single_stream(
        self,
        original_url: str,
        resolved_url: str,
        dest_path: str,
        total_size: Optional[int],
        expected_size: Optional[int],
        progress_cb: Optional[Callable[[int, Optional[int], float, str], None]],
    ) -> None:
        part_path = dest_path + ".part"
        meta_path = dest_path + ".part.meta"
        self._remove_quiet(part_path)
        self._remove_quiet(meta_path)

        sess = self._get_session()
        current_url = resolved_url
        sas_refreshes = 0

        while True:
            if self.is_cancelled():
                raise DownloadCancelledError("Download cancelled")

            try:
                resp = sess.get(
                    current_url,
                    headers={"Accept-Encoding": "identity", "User-Agent": "EarPurifier/1.0"},
                    stream=True,
                    allow_redirects=True,
                    timeout=(self.connect_timeout, self.read_timeout),
                )
            except Exception as exc:
                if self.is_cancelled():
                    raise DownloadCancelledError("Download cancelled") from exc
                raise
            self._register_response(resp)
            try:
                if resp.status_code in (401, 403) and sas_refreshes < self.MAX_SAS_REFRESHES:
                    sas_refreshes += 1
                    self._unregister_response(resp)
                    self._close_response_safe(resp)
                    current_url, probed_sz, _ = self._probe_mirror(original_url, expected_size=expected_size)
                    if total_size is None and probed_sz is not None:
                        total_size = probed_sz
                    continue

                resp.raise_for_status()
                header_len = self._parse_int_header(resp.headers.get("Content-Length"))
                effective_total = (
                    total_size if total_size is not None
                    else (header_len if header_len is not None else expected_size)
                )
                self._check_disk_space(os.path.dirname(dest_path) or ".", effective_total, already_on_disk=0)

                downloaded = 0
                samples: deque = deque()
                started_ts = time.monotonic()
                last_emit_ts = 0.0
                max_sample_age = max(self.SPEED_WINDOW_SECONDS, self.true_stall_seconds) + 1.0

                try:
                    with open(part_path, "wb") as out_f:
                        for block in resp.iter_content(chunk_size=self.read_block_size):
                            if self.is_cancelled():
                                raise DownloadCancelledError("Download cancelled")
                            now = time.monotonic()
                            if block:
                                try:
                                    out_f.write(block)
                                except OSError as io_err:
                                    if _is_disk_full_error(io_err):
                                        raise InsufficientDiskSpaceError(errno.ENOSPC, str(io_err)) from io_err
                                    raise
                                blen = len(block)
                                downloaded += blen
                                samples.append((now, blen))
                            self._prune_samples(samples, now, max_sample_age)

                            if (now - started_ts) >= self.true_stall_seconds:
                                stall_bps = self._window_bytes_over_duration(samples, now, self.true_stall_seconds)
                                if stall_bps < self.true_stall_min_bps:
                                    raise TimeoutError(
                                        f"Single-stream download stalled ({stall_bps:.0f} B/s < {self.true_stall_min_bps:.0f} B/s)"
                                    )

                            if progress_cb and (now - last_emit_ts) >= self.progress_interval:
                                speed_bps = self._window_speed_bps(samples, now, self.SPEED_WINDOW_SECONDS)
                                progress_cb(downloaded, effective_total, speed_bps, "downloading")
                                last_emit_ts = now
                        out_f.flush()
                except DownloadCancelledError:
                    self._remove_quiet(part_path)
                    raise
                except Exception as exc:
                    self._remove_quiet(part_path)
                    if self.is_cancelled():
                        raise DownloadCancelledError("Download cancelled") from exc
                    raise

                if effective_total is not None and downloaded != effective_total:
                    self._remove_quiet(part_path)
                    raise IOError(
                        f"Incomplete single-stream read: expected {effective_total} bytes, got {downloaded} bytes"
                    )

                if progress_cb:
                    now = time.monotonic()
                    speed_bps = self._window_speed_bps(samples, now, self.SPEED_WINDOW_SECONDS)
                    progress_cb(downloaded, effective_total or downloaded, speed_bps, "downloading")
                return
            finally:
                self._unregister_response(resp)
                self._close_response_safe(resp)

    def _download_segmented(
        self,
        mirror_states: List[Dict[str, Any]],
        initial_mirror_idx: int,
        dest_path: str,
        total_size: int,
        expected_sha256: Optional[str],
        resume_enabled: bool,
        progress_cb: Optional[Callable[[int, Optional[int], float, str], None]],
    ) -> None:
        part_path = dest_path + ".part"
        meta_path = dest_path + ".part.meta"
        dest_dir = os.path.dirname(dest_path) or "."
        os.makedirs(dest_dir, exist_ok=True)

        num_chunks = (total_size + self.chunk_size - 1) // self.chunk_size
        completed_chunks: Set[int] = set()
        if resume_enabled:
            completed_chunks = self._load_resume_state(part_path, meta_path, total_size, expected_sha256)
        else:
            self._remove_quiet(part_path)
            self._remove_quiet(meta_path)

        resumed_bytes = sum(self._chunk_bounds(idx, total_size)[2] for idx in completed_chunks)
        self._check_disk_space(dest_dir, total_size, already_on_disk=resumed_bytes)

        pending_heap: List[int] = [i for i in range(num_chunks) if i not in completed_chunks]
        heapq.heapify(pending_heap)

        if not pending_heap:
            if progress_cb:
                progress_cb(total_size, total_size, 0.0, "downloading")
            return

        if resumed_bytes > 0 and progress_cb:
            progress_cb(resumed_bytes, total_size, 0.0, "downloading")

        if not os.path.isfile(part_path):
            # Create empty file without upfront f.truncate(total_size) to avoid NTFS VDL stalls
            with open(part_path, "wb"):
                pass

        state_lock = threading.Lock()
        heap_cond = threading.Condition(state_lock)
        file_lock = threading.Lock()
        abort_event = threading.Event()
        done_event = threading.Event()
        monitor_wakeup = threading.Event()

        def _on_cancel_wakeup() -> None:
            abort_event.set()
            monitor_wakeup.set()
            with heap_cond:
                heap_cond.notify_all()

        self._add_cancel_callback(_on_cancel_wakeup)

        state: Dict[str, Any] = {
            "active_mirror_idx": initial_mirror_idx,
            "active_resolved_url": mirror_states[initial_mirror_idx]["resolved_url"],
            "mirror_generation": 0,
            "mirror_started_ts": time.monotonic(),
            "mirror_stall_count": 0,
            "probing_mirror_idx": None,
            "speed_failover_locked": False,
            "completed_bytes": resumed_bytes,
            "inflight_bytes": {},
            "session_samples": deque(),
            "mirror_samples": deque(),
            "worker_states": {},
            "worker_samples": {},
            "worker_started": {},
            "chunk_attempts": {},
            "fatal_error": None,
            "range_not_supported": False,
            "hard_failover_requested": False,
            "tried_cdn_groups": {mirror_states[initial_mirror_idx]["cdn"]},
        }

        part_fp_holder: List[Any] = [open(part_path, "r+b")]

        def _has_failover_candidate_locked() -> bool:
            if state["probing_mirror_idx"] is not None:
                return True
            return any(not ms["tried"] and not ms["failed"] for ms in mirror_states)

        def _refresh_active_url(mirror_idx: int, failed_url: str) -> str:
            with self._refresh_lock:
                with state_lock:
                    if state["active_mirror_idx"] != mirror_idx:
                        return state["active_resolved_url"]
                    if state["active_resolved_url"] != failed_url:
                        return state["active_resolved_url"]
                    mstate = mirror_states[mirror_idx]
                    if mstate["sas_refreshes"] >= self.MAX_SAS_REFRESHES:
                        raise PermissionError(f"Mirror {mstate['url']} exceeded SAS refresh limit (401/403)")
                    mstate["sas_refreshes"] += 1
                    orig_url = mstate["url"]

                new_url, new_size, new_ranges = self._probe_mirror(orig_url, expected_size=total_size)
                if not new_ranges or (new_size is not None and new_size != total_size):
                    raise ValueError(f"SAS refresh probe invalid for {orig_url}")
                with state_lock:
                    if state["active_mirror_idx"] == mirror_idx:
                        state["active_resolved_url"] = new_url
                        mirror_states[mirror_idx]["resolved_url"] = new_url
                    return state["active_resolved_url"]

        def _worker_loop(worker_id: int) -> None:
            my_tid = threading.get_ident()
            with self._active_sockets_lock:
                self._thread_abort_events[my_tid] = abort_event
            try:
                _worker_loop_body(worker_id, my_tid)
            finally:
                with self._active_sockets_lock:
                    if self._thread_abort_events.get(my_tid) is abort_event:
                        self._thread_abort_events.pop(my_tid, None)

        def _worker_loop_body(worker_id: int, my_tid: int) -> None:
            while True:
                sess = self._get_session()
                with heap_cond:
                    while (
                        not pending_heap
                        and len(completed_chunks) < num_chunks
                        and not abort_event.is_set()
                        and not self.is_cancelled()
                    ):
                        heap_cond.wait(timeout=0.2)

                    if (
                        abort_event.is_set()
                        or self.is_cancelled()
                        or len(completed_chunks) >= num_chunks
                    ):
                        return

                    if not pending_heap:
                        continue

                    chunk_idx = heapq.heappop(pending_heap)
                    if chunk_idx in completed_chunks:
                        continue
                    my_mirror_idx = state["active_mirror_idx"]
                    my_url = state["active_resolved_url"]
                    my_gen = state["mirror_generation"]
                    now_ts = time.monotonic()
                    ws: Dict[str, Any] = {
                        "chunk_idx": chunk_idx,
                        "tid": my_tid,
                        "generation": my_gen,
                        "started_ts": now_ts,
                        "last_byte_ts": now_ts,
                        "samples": deque(),
                        "resp": None,
                        "aborted_reason": None,
                    }
                    state["worker_states"][worker_id] = ws
                    state["inflight_bytes"][chunk_idx] = 0

                start, end, expected_len = self._chunk_bounds(chunk_idx, total_size)
                resp = None
                requeue_chunk = False
                count_attempt = True
                count_stall = False
                last_chunk_err: Optional[Exception] = None

                try:
                    resp = sess.get(
                        my_url,
                        headers={
                            "Range": f"bytes={start}-{end}",
                            "Accept-Encoding": "identity",
                            "User-Agent": "EarPurifier/1.0",
                        },
                        stream=True,
                        allow_redirects=True,
                        timeout=(self.connect_timeout, self.read_timeout),
                    )
                    self._register_response(resp)
                    with state_lock:
                        ws["resp"] = resp
                        abort_reason = ws["aborted_reason"]

                    if self.is_cancelled() or abort_event.is_set():
                        return

                    if abort_reason == "mirror_switch":
                        requeue_chunk = True
                        count_attempt = False
                        continue

                    if resp.status_code == 200:
                        with heap_cond:
                            state["range_not_supported"] = True
                            abort_event.set()
                            monitor_wakeup.set()
                            heap_cond.notify_all()
                        return

                    if resp.status_code in (401, 403):
                        self._unregister_response(resp)
                        self._close_response_safe(resp)
                        resp = None
                        try:
                            _refresh_active_url(my_mirror_idx, my_url)
                            requeue_chunk = True
                            count_attempt = False
                            continue
                        except Exception as refresh_err:
                            logger.warning(f"SAS refresh failed for mirror {my_mirror_idx}: {refresh_err}")
                            last_chunk_err = refresh_err
                            requeue_chunk = True
                            count_stall = True
                            with heap_cond:
                                state["hard_failover_requested"] = True
                                monitor_wakeup.set()
                                heap_cond.notify_all()
                            continue

                    if resp.status_code != 206:
                        resp.raise_for_status()
                        raise IOError(f"Expected HTTP 206 Partial Content, got {resp.status_code}")

                    cr = (resp.headers.get("Content-Range") or "").strip()
                    if cr:
                        m = self._CONTENT_RANGE_RE.match(cr)
                        if not m:
                            raise IOError(f"Malformed Content-Range header: {cr}")
                        r_start, r_end, r_tot = int(m.group(1)), int(m.group(2)), m.group(3)
                        if r_start != start or r_end != end or (r_tot != "*" and int(r_tot) != total_size):
                            raise IOError(
                                f"Content-Range mismatch: expected {start}-{end}/{total_size}, got {cr}"
                            )

                    buf = bytearray()
                    for block in resp.iter_content(chunk_size=self.read_block_size):
                        if self.is_cancelled() or abort_event.is_set():
                            return
                        if ws["aborted_reason"] is not None:
                            reason = ws["aborted_reason"]
                            requeue_chunk = True
                            count_attempt = reason != "mirror_switch"
                            break
                        if not block:
                            continue
                        if len(buf) + len(block) > expected_len:
                            raise IOError(
                                f"Oversized chunk {chunk_idx}: received > {expected_len} bytes"
                            )
                        buf.extend(block)
                        now_b = time.monotonic()
                        blen = len(block)
                        with state_lock:
                            ws["last_byte_ts"] = now_b
                            ws["samples"].append((now_b, blen))
                            state["inflight_bytes"][chunk_idx] = len(buf)
                            state["session_samples"].append((now_b, blen))
                            if state["mirror_generation"] == my_gen:
                                state["mirror_samples"].append((now_b, blen))
                                w_samps = state["worker_samples"].setdefault(worker_id, deque())
                                w_samps.append((now_b, blen))
                                state["worker_started"].setdefault(worker_id, now_ts)

                    if requeue_chunk:
                        continue

                    if len(buf) != expected_len:
                        raise IOError(
                            f"Truncated chunk {chunk_idx}: expected {expected_len} bytes, got {len(buf)}"
                        )

                    # Write verified chunk bytes sequentially under file_lock
                    with file_lock:
                        fp = part_fp_holder[0]
                        if fp is None or self.is_cancelled() or abort_event.is_set():
                            return
                        try:
                            fp.seek(start)
                            fp.write(buf)
                            fp.flush()
                        except OSError as io_err:
                            if _is_disk_full_error(io_err):
                                with heap_cond:
                                    state["fatal_error"] = InsufficientDiskSpaceError(errno.ENOSPC, str(io_err))
                                    abort_event.set()
                                    monitor_wakeup.set()
                                    heap_cond.notify_all()
                                return
                            raise

                        with heap_cond:
                            state["inflight_bytes"].pop(chunk_idx, None)
                            if chunk_idx not in completed_chunks:
                                completed_chunks.add(chunk_idx)
                                state["completed_bytes"] += expected_len
                            if state["mirror_generation"] == my_gen:
                                state["mirror_stall_count"] = 0
                            snapshot_completed = set(completed_chunks)
                            if len(completed_chunks) >= num_chunks:
                                done_event.set()
                                monitor_wakeup.set()
                                heap_cond.notify_all()

                        if resume_enabled:
                            self._save_resume_meta(meta_path, total_size, expected_sha256, snapshot_completed)

                except Exception as exc:
                    if self.is_cancelled() or abort_event.is_set():
                        return
                    last_chunk_err = exc
                    reason = ws["aborted_reason"]
                    if reason == "mirror_switch":
                        requeue_chunk = True
                        count_attempt = False
                    elif reason in ("true_stall", "straggler"):
                        requeue_chunk = True
                        count_attempt = True
                        self._reset_thread_session()
                    else:
                        requeue_chunk = True
                        count_attempt = True
                        count_stall = True
                        logger.debug(f"Chunk {chunk_idx} error on mirror {my_mirror_idx}: {exc}")
                        if _is_disk_full_error(exc):
                            with heap_cond:
                                state["fatal_error"] = InsufficientDiskSpaceError(errno.ENOSPC, str(exc))
                                abort_event.set()
                                monitor_wakeup.set()
                                heap_cond.notify_all()
                            return
                        if _is_recoverable_network_error(exc):
                            self._reset_thread_session()
                finally:
                    if resp is not None:
                        self._unregister_response(resp)
                        self._close_response_safe(resp)
                    backoff_sec = 0.0
                    with heap_cond:
                        state["worker_states"].pop(worker_id, None)
                        state["inflight_bytes"].pop(chunk_idx, None)
                        if requeue_chunk and chunk_idx not in completed_chunks and not abort_event.is_set() and not self.is_cancelled():
                            if count_stall and state["mirror_generation"] == my_gen:
                                state["mirror_stall_count"] += 1
                                if state["mirror_stall_count"] >= self.cdn_failover_stall_count:
                                    monitor_wakeup.set()
                            if count_attempt:
                                att = state["chunk_attempts"].get(chunk_idx, 0) + 1
                                state["chunk_attempts"][chunk_idx] = att
                                if att > self.max_chunk_retries:
                                    # Trigger failover if another mirror is untried or currently being probed
                                    if _has_failover_candidate_locked():
                                        state["hard_failover_requested"] = True
                                        monitor_wakeup.set()
                                    else:
                                        err_detail = f" ({last_chunk_err})" if last_chunk_err is not None else ""
                                        if last_chunk_err is None or _is_recoverable_network_error(last_chunk_err):
                                            state["fatal_error"] = DownloadNetworkError(
                                                f"Chunk {chunk_idx} failed after {self.max_chunk_retries} retries{err_detail}"
                                            )
                                        else:
                                            state["fatal_error"] = RuntimeError(
                                                f"Chunk {chunk_idx} failed after {self.max_chunk_retries} retries{err_detail}"
                                            )
                                        abort_event.set()
                                        monitor_wakeup.set()
                                if not abort_event.is_set():
                                    backoff_sec = min(0.5, 0.08 * att)
                            if not abort_event.is_set():
                                heapq.heappush(pending_heap, chunk_idx)
                            heap_cond.notify_all()
                            # Interruptible brief backoff on errors (wakes immediately on mirror switch / abort)
                            if backoff_sec > 0 and state["mirror_generation"] == my_gen and not abort_event.is_set() and not self.is_cancelled():
                                heap_cond.wait(timeout=backoff_sec)

        def _select_failover_candidate(allow_same_cdn: bool, cur_agg_bps: float) -> Optional[int]:
            if state["probing_mirror_idx"] is not None:
                return None
            cur_idx = state["active_mirror_idx"]
            cur_cdn = mirror_states[cur_idx]["cdn"]
            tried_cdns = state["tried_cdn_groups"]

            # Pass 1: untried mirror from a CDN group not yet tried
            for idx, ms in enumerate(mirror_states):
                if not ms["tried"] and not ms["failed"] and ms["cdn"] not in tried_cdns:
                    return idx

            if not allow_same_cdn:
                # Slow-ISP anti-thrash guard: once every distinct CDN group has been
                # measured, never ping-pong across alternate URLs of already-tried CDNs.
                # If a previously measured mirror was significantly faster (>=1.5x and +64 KiB/s),
                # settle back on it once and lock speed-based switching permanently.
                if state["speed_failover_locked"]:
                    return None
                state["speed_failover_locked"] = True
                best_idx: Optional[int] = None
                best_bps = 0.0
                for idx, ms in enumerate(mirror_states):
                    if idx != cur_idx and not ms["failed"] and ms["measured_bps"] > best_bps:
                        best_bps = ms["measured_bps"]
                        best_idx = idx
                if best_idx is not None and best_bps >= max(cur_agg_bps * 1.5, cur_agg_bps + 64 * 1024):
                    return best_idx
                return None

            # Pass 2 (hard errors/stalls only): untried mirror from a different CDN group than current
            for idx, ms in enumerate(mirror_states):
                if not ms["tried"] and not ms["failed"] and ms["cdn"] != cur_cdn:
                    return idx
            # Pass 3 (hard errors/stalls only): any untried mirror
            for idx, ms in enumerate(mirror_states):
                if not ms["tried"] and not ms["failed"]:
                    return idx
            return None

        def _try_switch_mirror(cand_idx: int, cur_agg_bps: float, abort_inflight: bool = True) -> bool:
            cand = mirror_states[cand_idx]
            with heap_cond:
                if state["probing_mirror_idx"] is not None:
                    return False
                state["probing_mirror_idx"] = cand_idx
                cand_url = cand["url"]
                cand_cdn = cand["cdn"]

            try:
                new_url, new_size, new_ranges = self._probe_mirror(cand_url, expected_size=total_size)
                if not new_ranges or (new_size is not None and new_size != total_size):
                    raise ValueError(f"Failover mirror incompatible: ranges={new_ranges}, size={new_size}")
            except DownloadCancelledError:
                with heap_cond:
                    state["probing_mirror_idx"] = None
                    heap_cond.notify_all()
                return False
            except Exception as probe_err:
                logger.warning(f"Cross-CDN failover probe failed for {cand_url}: {probe_err}")
                host = _extract_url_host(cand_url)
                if host:
                    self.last_failed_hosts.add(host)
                with heap_cond:
                    cand["tried"] = True
                    cand["failed"] = True
                    if _is_permanent_http_error(probe_err):
                        cand["permanent_fail"] = True
                    state["tried_cdn_groups"].add(cand_cdn)
                    state["probing_mirror_idx"] = None
                    heap_cond.notify_all()
                return False

            cand_host = _extract_url_host(cand_url)
            if cand_host:
                self.last_succeeded_hosts.add(cand_host)
                self.last_failed_hosts.discard(cand_host)

            old_responses: List[Any] = []
            old_connecting_socks: List[Any] = []
            with heap_cond:
                state["probing_mirror_idx"] = None
                if done_event.is_set() or abort_event.is_set() or self.is_cancelled():
                    heap_cond.notify_all()
                    return False
                cand["tried"] = True
                cand["resolved_url"] = new_url
                state["tried_cdn_groups"].add(cand_cdn)
                prev_idx = state["active_mirror_idx"]
                mirror_states[prev_idx]["measured_bps"] = max(
                    mirror_states[prev_idx]["measured_bps"], cur_agg_bps
                )
                state["active_mirror_idx"] = cand_idx
                state["active_resolved_url"] = new_url
                state["mirror_generation"] += 1
                state["mirror_started_ts"] = time.monotonic()
                state["mirror_stall_count"] = 0
                state["hard_failover_requested"] = False
                state["chunk_attempts"].clear()
                state["mirror_samples"].clear()
                state["worker_samples"].clear()
                state["worker_started"].clear()
                connecting_tids: List[int] = []
                for ws in state["worker_states"].values():
                    if not abort_inflight and ws["resp"] is not None:
                        # Graceful speed-only failover: let workers that have already buffered
                        # >= 50% of their current chunk finish & checkpoint to disk instead of
                        # discarding megabytes of healthy transfer.
                        c_idx = ws["chunk_idx"]
                        _, _, c_len = self._chunk_bounds(c_idx, total_size)
                        buffered = state["inflight_bytes"].get(c_idx, 0)
                        if c_len > 0 and buffered * 2 >= c_len:
                            continue
                    ws["aborted_reason"] = "mirror_switch"
                    if ws["resp"] is not None:
                        old_responses.append(ws["resp"])
                    elif ws.get("tid") is not None:
                        connecting_tids.append(ws["tid"])
                old_connecting_socks = self._snapshot_thread_sockets(connecting_tids)
                heap_cond.notify_all()

            for r in old_responses:
                self._abort_response_socket(r)
            for sock in old_connecting_socks:
                self._abort_socket(sock)
            logger.info(
                "Cross-CDN failover: switched from %s (%s, %.1f KiB/s) -> %s (%s)",
                mirror_states[prev_idx]["cdn"],
                mirror_states[prev_idx]["url"],
                cur_agg_bps / 1024.0,
                cand["cdn"],
                cand["url"],
            )
            return True

        num_workers = min(self.workers, len(pending_heap))
        executor = ThreadPoolExecutor(max_workers=num_workers, thread_name_prefix="ep_seg_dl")
        futures = [executor.submit(_worker_loop, wid) for wid in range(num_workers)]
        last_emit_ts = 0.0
        poll_sleep = min(0.15, self.progress_interval / 2.0)

        try:
            while not done_event.is_set() and not abort_event.is_set() and not self.is_cancelled():
                monitor_wakeup.wait(timeout=poll_sleep)
                monitor_wakeup.clear()
                if done_event.is_set() or abort_event.is_set() or self.is_cancelled():
                    break
                now = time.monotonic()
                responses_to_close: List[Any] = []
                sockets_to_abort: List[Any] = []
                failover_cand: Optional[int] = None
                failover_abort_inflight = True
                agg_mirror_bps = 0.0
                emit_payload: Optional[Tuple[int, int, float]] = None

                with heap_cond:
                    # 1. Check progress emission
                    self._prune_samples(state["session_samples"], now, self.SPEED_WINDOW_SECONDS + 1.0)
                    if progress_cb and (now - last_emit_ts) >= self.progress_interval:
                        eff_dl = min(total_size, state["completed_bytes"] + sum(state["inflight_bytes"].values()))
                        sess_bps = self._window_speed_bps(state["session_samples"], now, self.SPEED_WINDOW_SECONDS)
                        emit_payload = (eff_dl, total_size, sess_bps)
                        last_emit_ts = now

                    # 2. Per-worker true-stall & relative straggler watchdogs
                    cur_gen = state["mirror_generation"]
                    max_sample_age = max(self.true_stall_seconds, self.straggler_seconds, self.SPEED_WINDOW_SECONDS) + 1.0
                    active_ws = [
                        (wid, ws) for wid, ws in state["worker_states"].items()
                        if ws["aborted_reason"] is None
                    ]
                    min_peer_age = min(3.0, self.straggler_seconds * 0.5)
                    peer_speeds: Dict[int, float] = {}
                    for wid, w_samps in state["worker_samples"].items():
                        self._prune_samples(w_samps, now, max_sample_age)
                        w_start = state["worker_started"].get(wid, now)
                        w_age = now - w_start
                        if w_age >= min_peer_age and w_samps:
                            peer_speeds[wid] = self._window_bytes_over_duration(
                                w_samps, now, min(w_age, self.straggler_seconds)
                            )

                    connecting_abort_tids: List[int] = []
                    for wid, ws in active_ws:
                        self._prune_samples(ws["samples"], now, max_sample_age)
                        age = now - ws["started_ts"]
                        if age >= self.true_stall_seconds:
                            stall_bps = self._window_bytes_over_duration(ws["samples"], now, self.true_stall_seconds)
                            if stall_bps < self.true_stall_min_bps:
                                ws["aborted_reason"] = "true_stall"
                                if ws["generation"] == cur_gen:
                                    state["mirror_stall_count"] += 1
                                if ws["resp"] is not None:
                                    responses_to_close.append(ws["resp"])
                                elif ws.get("tid") is not None:
                                    connecting_abort_tids.append(ws["tid"])
                                continue

                        if ws["generation"] == cur_gen and age >= self.straggler_seconds:
                            my_bps = self._window_bytes_over_duration(ws["samples"], now, self.straggler_seconds)
                            other_speeds = [spd for oid, spd in peer_speeds.items() if oid != wid]
                            if other_speeds and my_bps < self.straggler_max_bps:
                                other_med = statistics.median(other_speeds)
                                if other_med > 0 and my_bps < self.straggler_ratio * other_med:
                                    ws["aborted_reason"] = "straggler"
                                    if ws["resp"] is not None:
                                        responses_to_close.append(ws["resp"])
                                    elif ws.get("tid") is not None:
                                        connecting_abort_tids.append(ws["tid"])
                    if connecting_abort_tids:
                        sockets_to_abort = self._snapshot_thread_sockets(connecting_abort_tids)

                    # 3. Cross-CDN failover evaluation
                    self._prune_samples(state["mirror_samples"], now, self.cdn_failover_seconds + 1.0)
                    mirror_age = now - state["mirror_started_ts"]
                    agg_mirror_bps = self._window_bytes_over_duration(
                        state["mirror_samples"], now, min(max(0.25, mirror_age), self.cdn_failover_seconds)
                    )
                    low_speed_trigger = (
                        mirror_age >= self.cdn_failover_seconds
                        and agg_mirror_bps < self.cdn_failover_max_bps
                        and state["completed_bytes"] < int(total_size * 0.75)
                    )
                    stall_trigger = state["mirror_stall_count"] >= self.cdn_failover_stall_count
                    hard_trigger = state["hard_failover_requested"]

                    if hard_trigger or stall_trigger or low_speed_trigger:
                        failover_abort_inflight = bool(hard_trigger or stall_trigger)
                        failover_cand = _select_failover_candidate(
                            allow_same_cdn=failover_abort_inflight,
                            cur_agg_bps=agg_mirror_bps,
                        )
                        if failover_cand is None and hard_trigger:
                            state["hard_failover_requested"] = False

                    # Check if all workers unexpectedly exited without completing
                    if all(f.done() for f in futures) and len(completed_chunks) < num_chunks and not abort_event.is_set():
                        state["fatal_error"] = DownloadNetworkError("Download workers exited before completing all chunks")
                        abort_event.set()

                if emit_payload and progress_cb:
                    progress_cb(emit_payload[0], emit_payload[1], emit_payload[2], "downloading")

                for r in responses_to_close:
                    self._abort_response_socket(r)
                for sock in sockets_to_abort:
                    self._abort_socket(sock)

                if failover_cand is not None and not done_event.is_set() and not abort_event.is_set() and not self.is_cancelled():
                    _try_switch_mirror(failover_cand, agg_mirror_bps, abort_inflight=failover_abort_inflight)

            if self.is_cancelled():
                abort_event.set()
                with heap_cond:
                    heap_cond.notify_all()
                self.cancel()
                raise DownloadCancelledError("Download cancelled")

            if state["range_not_supported"]:
                abort_event.set()
                with heap_cond:
                    heap_cond.notify_all()
                self._close_all_active_responses()
                raise _RangeNotSupportedError("Server returned HTTP 200 instead of 206 Partial Content")

            if state["fatal_error"] is not None:
                abort_event.set()
                with heap_cond:
                    heap_cond.notify_all()
                self._close_all_active_responses()
                raise state["fatal_error"]

            if progress_cb:
                now = time.monotonic()
                with state_lock:
                    sess_bps = self._window_speed_bps(state["session_samples"], now, self.SPEED_WINDOW_SECONDS)
                progress_cb(total_size, total_size, sess_bps, "downloading")
        finally:
            self._remove_cancel_callback(_on_cancel_wakeup)
            abort_event.set()
            monitor_wakeup.set()
            with heap_cond:
                remaining_tids = [ws.get("tid") for ws in state["worker_states"].values() if ws.get("tid") is not None]
                heap_cond.notify_all()
            if self.is_cancelled() or state["fatal_error"] is not None or state["range_not_supported"]:
                self._close_all_active_responses()
                for tid in remaining_tids:
                    self._abort_thread_sockets(tid)
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True)
            with file_lock:
                fp = part_fp_holder[0]
                part_fp_holder[0] = None
                if fp is not None:
                    try:
                        fp.flush()
                    except Exception:
                        pass
                    try:
                        fp.close()
                    except Exception:
                        pass

    def _close_all_active_responses(self) -> None:
        with self._active_responses_lock:
            responses = list(self._active_responses)
        for r in responses:
            self._abort_response_socket(r)

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Sleeps up to `seconds`, waking immediately on cancel(). Returns False if cancelled."""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if self.is_cancelled():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return True
            step = min(0.15, remaining) if self._cancel_check is not None else remaining
            if self._cancel_event.wait(timeout=step):
                return False

    def _compute_resumed_bytes_on_disk(
        self,
        part_path: str,
        meta_path: str,
        total_size: Optional[int],
        expected_sha256: Optional[str],
    ) -> int:
        if total_size is None or total_size <= 0:
            return 0
        try:
            completed = self._validate_resume_state_readonly(part_path, meta_path, total_size, expected_sha256)
            return sum(self._chunk_bounds(idx, total_size)[2] for idx in completed)
        except Exception:
            return 0

    def download(
        self,
        mirrors: List[Tuple[str, str]],
        dest_path: str,
        expected_size: Optional[int] = None,
        expected_sha256: Optional[str] = None,
        validate_json: bool = False,
        json_required_keys: Optional[Tuple[str, ...]] = None,
        json_min_keys: int = 0,
        resume_enabled: bool = True,
        skip_if_valid: bool = True,
        progress_cb: Optional[Callable[[int, Optional[int], float, str], None]] = None,
    ) -> str:
        """
        Downloads a file from ordered (cdn_group, url) mirrors to dest_path with
        verification, resumability, watchdogs, cross-CDN failover, and transient
        network/VPN recovery.
        """
        if self.is_cancelled():
            raise DownloadCancelledError("Download cancelled")

        dest_dir = os.path.dirname(dest_path) or "."
        os.makedirs(dest_dir, exist_ok=True)
        part_path = dest_path + ".part"
        meta_path = dest_path + ".part.meta"

        try:
            # 1. Idempotent pre-check & self-healing
            if skip_if_valid and self._verify_existing_file(
                dest_path,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                validate_json=validate_json,
                json_required_keys=json_required_keys,
                json_min_keys=json_min_keys,
            ):
                fsize = os.path.getsize(dest_path)
                if progress_cb:
                    progress_cb(fsize, fsize, 0.0, "complete")
                return dest_path

            # 2. Pre-flight disk space check if size is already known from manifest
            if expected_size is not None and expected_size > self.min_segmented_size:
                existing_part_bytes = 0
                if resume_enabled and os.path.isfile(part_path) and os.path.isfile(meta_path):
                    existing_part_bytes = min(expected_size, os.path.getsize(part_path))
                self._check_disk_space(dest_dir, expected_size, already_on_disk=existing_part_bytes)

            mirror_states: List[Dict[str, Any]] = [
                {
                    "cdn": cdn,
                    "url": url,
                    "resolved_url": None,
                    "tried": False,
                    "failed": False,
                    "permanent_fail": False,
                    "measured_bps": 0.0,
                    "sas_refreshes": 0,
                }
                for cdn, url in mirrors
            ]

            checksum_retried = False
            recovery_round = 0
            last_known_total = expected_size
            last_progress_bytes = (
                self._compute_resumed_bytes_on_disk(part_path, meta_path, expected_size, expected_sha256)
                if resume_enabled else 0
            )
            last_error: Optional[Exception] = None

            while True:
                if self.is_cancelled():
                    raise DownloadCancelledError("Download cancelled")

                # Find next untried, non-failed mirror to start/retry from
                start_idx: Optional[int] = None
                for idx, ms in enumerate(mirror_states):
                    if not ms["tried"] and not ms["failed"]:
                        start_idx = idx
                        break

                if start_idx is None:
                    resumed_b = (
                        self._compute_resumed_bytes_on_disk(part_path, meta_path, last_known_total, expected_sha256)
                        if resume_enabled else 0
                    )
                    if resumed_b > last_progress_bytes:
                        # Forward progress was made since the last outage -> grant a fresh recovery budget
                        last_progress_bytes = resumed_b
                        recovery_round = 0

                    can_recover = (
                        recovery_round < len(self.network_recovery_backoff)
                        and last_error is not None
                        and _is_recoverable_network_error(last_error)
                        and any(not m["permanent_fail"] for m in mirror_states)
                    )
                    if can_recover:
                        delay = self.network_recovery_backoff[recovery_round]
                        recovery_round += 1
                        logger.warning(
                            "Transient network interruption while downloading %s (recovery %d/%d, waiting %.1fs to resume): %s",
                            os.path.basename(dest_path),
                            recovery_round,
                            len(self.network_recovery_backoff),
                            delay,
                            last_error,
                        )
                        # Close stale pooled sockets bound to old network interface (e.g. pre-WARP/VPN)
                        self._close_all_sessions()
                        if progress_cb:
                            progress_cb(resumed_b, last_known_total, 0.0, "reconnecting")
                        if not self._sleep_interruptible(delay):
                            raise DownloadCancelledError("Download cancelled")
                        for m in mirror_states:
                            if not m["permanent_fail"]:
                                m["tried"] = False
                                m["failed"] = False
                                m["resolved_url"] = None
                                m["measured_bps"] = 0.0
                                m["sas_refreshes"] = 0
                        continue

                    raise last_error or RuntimeError(f"All mirrors failed for {os.path.basename(dest_path)}")

                ms = mirror_states[start_idx]
                ms["tried"] = True

                try:
                    resolved_url, probed_size, accept_ranges = self._probe_mirror(
                        ms["url"], expected_size=expected_size
                    )
                except DownloadCancelledError:
                    raise
                except Exception as probe_err:
                    ms["failed"] = True
                    if _is_permanent_http_error(probe_err):
                        ms["permanent_fail"] = True
                    else:
                        host = _extract_url_host(ms["url"])
                        if host:
                            self.last_failed_hosts.add(host)
                    last_error = probe_err
                    logger.warning(f"Mirror probe failed ({ms['url']}): {probe_err}")
                    continue

                ok_host = _extract_url_host(ms["url"])
                if ok_host:
                    self.last_succeeded_hosts.add(ok_host)
                    self.last_failed_hosts.discard(ok_host)

                ms["resolved_url"] = resolved_url
                effective_size = probed_size if probed_size is not None else expected_size
                if effective_size is not None:
                    last_known_total = effective_size

                use_segmented = (
                    accept_ranges
                    and effective_size is not None
                    and effective_size > self.min_segmented_size
                    and self.workers > 1
                )

                try:
                    if use_segmented:
                        try:
                            self._download_segmented(
                                mirror_states=mirror_states,
                                initial_mirror_idx=start_idx,
                                dest_path=dest_path,
                                total_size=int(effective_size),
                                expected_sha256=expected_sha256,
                                resume_enabled=resume_enabled,
                                progress_cb=progress_cb,
                            )
                        except _RangeNotSupportedError:
                            logger.info(
                                f"Mirror {ms['url']} returned 200 OK for Range; falling back to single-stream."
                            )
                            self._remove_quiet(part_path)
                            self._remove_quiet(meta_path)
                            self._download_single_stream(
                                original_url=ms["url"],
                                resolved_url=resolved_url,
                                dest_path=dest_path,
                                total_size=effective_size,
                                expected_size=expected_size,
                                progress_cb=progress_cb,
                            )
                    else:
                        self._download_single_stream(
                            original_url=ms["url"],
                            resolved_url=resolved_url,
                            dest_path=dest_path,
                            total_size=effective_size,
                            expected_size=expected_size,
                            progress_cb=progress_cb,
                        )

                    self._verify_and_promote(
                        part_path=part_path,
                        meta_path=meta_path,
                        dest_path=dest_path,
                        expected_size=(expected_size if expected_size is not None else effective_size),
                        expected_sha256=expected_sha256,
                        validate_json=validate_json,
                        json_required_keys=json_required_keys,
                        json_min_keys=json_min_keys,
                        progress_cb=progress_cb,
                    )
                    return dest_path

                except (DownloadCancelledError, InsufficientDiskSpaceError):
                    raise
                except ChecksumMismatchError as chk_err:
                    ms["failed"] = True
                    last_error = chk_err
                    logger.warning(f"Checksum mismatch on {ms['url']}: {chk_err}")
                    if checksum_retried:
                        raise
                    checksum_retried = True
                    # Retry cleanly once from the next untried mirror; if all were tried during
                    # failover (e.g. corrupt resumed .part), allow a single clean retry on a non-failed mirror
                    if not any(not m["tried"] and not m["failed"] for m in mirror_states):
                        for m in mirror_states:
                            if not m["failed"]:
                                m["tried"] = False
                                break
                        else:
                            # Single-mirror case: allow one clean retry after deleting corrupt .part
                            ms["failed"] = False
                            ms["tried"] = False
                    if progress_cb:
                        progress_cb(0, effective_size, 0.0, "retrying")
                    continue
                except Exception as dl_err:
                    ms["failed"] = True
                    if _is_permanent_http_error(dl_err):
                        ms["permanent_fail"] = True
                    last_error = dl_err
                    logger.warning(f"Download failed on mirror {ms['url']}: {dl_err}")
                    continue
        finally:
            self._close_all_sessions()


class FFmpegDownloader(QThread):
    progress_update = Signal(int)
    progress_detail = Signal(int, str)
    status_update = Signal(str)
    finished_download = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dl_lock = threading.Lock()
        self._active_downloader: Optional[_SegmentedFileDownloader] = None

    def _download_file(self, url: str, dest_path: str, progress_range: tuple = (0, 100)):
        p_start, p_end = progress_range
        last_percent = -1

        def _on_progress(downloaded: int, total: Optional[int], speed_bps: float, _stage: str):
            nonlocal last_percent
            if total and total > 0:
                pct = p_start + int((min(downloaded, total) / total) * (p_end - p_start))
                pct = max(p_start, min(p_end, pct))
                speed_txt = _format_download_speed(speed_bps)
                if pct > last_percent:
                    self.progress_update.emit(pct)
                    last_percent = pct
                self.progress_detail.emit(max(pct, last_percent), speed_txt)

        downloader = _SegmentedFileDownloader(cancel_check=self.isInterruptionRequested)
        with self._dl_lock:
            self._active_downloader = downloader
        try:
            downloader.download(
                mirrors=[("github", url)],
                dest_path=dest_path,
                expected_size=None,
                expected_sha256=None,
                resume_enabled=False,
                skip_if_valid=False,
                progress_cb=_on_progress,
            )
            if p_end > last_percent:
                self.progress_update.emit(p_end)
                self.progress_detail.emit(p_end, "")
        finally:
            with self._dl_lock:
                if self._active_downloader is downloader:
                    self._active_downloader = None

    def run(self):
        staging_dir = None
        try:
            bin_dir = DependencyManager.get_bin_dir()
            appdata_dir = DependencyManager.get_appdata_dir()
            staging_dir = tempfile.mkdtemp(prefix="ffmpeg_stage_", dir=appdata_dir)
            current_os = sys.platform

            ext = ".exe" if current_os == "win32" else ""
            staged_ffmpeg = os.path.join(staging_dir, f"ffmpeg{ext}")
            staged_ffprobe = os.path.join(staging_dir, f"ffprobe{ext}")

            if current_os == "win32":
                self.status_update.emit("Downloading FFmpeg (Windows)...")
                url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
                archive_path = os.path.join(staging_dir, "ffmpeg.zip")
                self._download_file(url, archive_path, progress_range=(0, 85))

                self.status_update.emit("Extracting FFmpeg binaries...")
                with zipfile.ZipFile(archive_path, 'r') as z:
                    for info in z.infolist():
                        if self.isInterruptionRequested():
                            raise InterruptedError("Download cancelled")
                        if info.filename.endswith('ffmpeg.exe') or info.filename.endswith('ffprobe.exe'):
                            info.filename = os.path.basename(info.filename)
                            z.extract(info, staging_dir)

            elif current_os == "darwin":
                # macOS: Native static Mach-O binaries from descriptinc/ffmpeg-ffprobe-static (b6.1.2-rc.1)
                self.status_update.emit("Downloading FFmpeg (macOS)...")
                is_arm = platform.machine().lower() in ("arm64", "aarch64")
                arch_tag = "arm64" if is_arm else "x64"
                base_url = "https://github.com/descriptinc/ffmpeg-ffprobe-static/releases/download/b6.1.2-rc.1"
                ffmpeg_url = f"{base_url}/ffmpeg-darwin-{arch_tag}"
                ffprobe_url = f"{base_url}/ffprobe-darwin-{arch_tag}"

                self._download_file(ffmpeg_url, staged_ffmpeg, progress_range=(0, 50))
                self.status_update.emit("Downloading FFprobe (macOS)...")
                self._download_file(ffprobe_url, staged_ffprobe, progress_range=(50, 95))

            else:
                # Linux: BtbN tar.xz (supports x86_64 and aarch64/ARM64)
                self.status_update.emit("Downloading FFmpeg (Linux)...")
                linux_arch = "linuxarm64" if platform.machine().lower() in ("arm64", "aarch64") else "linux64"
                url = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-{linux_arch}-gpl.tar.xz"
                archive_path = os.path.join(staging_dir, "ffmpeg.tar.xz")
                self._download_file(url, archive_path, progress_range=(0, 85))

                self.status_update.emit("Extracting FFmpeg binaries...")
                with tarfile.open(archive_path, "r:xz") as tar:
                    for member in tar.getmembers():
                        if self.isInterruptionRequested():
                            raise InterruptedError("Download cancelled")
                        base = os.path.basename(member.name)
                        if base in ("ffmpeg", "ffprobe") and member.isfile():
                            member.name = base
                            tar.extract(member, staging_dir)

            # Verify staged binaries are present and non-empty before atomic promotion
            for staged_path, bin_name in ((staged_ffmpeg, f"ffmpeg{ext}"), (staged_ffprobe, f"ffprobe{ext}")):
                if not os.path.isfile(staged_path) or os.path.getsize(staged_path) <= 0:
                    raise RuntimeError(f"FFmpeg extraction incomplete: missing or empty {bin_name}")
                if current_os != "win32":
                    try:
                        os.chmod(staged_path, 0o755)
                    except Exception:
                        pass

            _atomic_replace_file(staged_ffmpeg, os.path.join(bin_dir, f"ffmpeg{ext}"))
            _atomic_replace_file(staged_ffprobe, os.path.join(bin_dir, f"ffprobe{ext}"))

            self.status_update.emit("FFmpeg installed successfully.")
            self.progress_update.emit(100)
            self.finished_download.emit(True, "Success")

        except InterruptedError:
            logger.info("FFmpeg download cancelled.")
            return
        except Exception as e:
            self.finished_download.emit(False, str(e))
        finally:
            if staging_dir and os.path.exists(staging_dir):
                try:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                except Exception:
                    pass

    def stop(self):
        self.requestInterruption()
        with self._dl_lock:
            dl = self._active_downloader
        if dl is not None:
            try:
                dl.cancel()
            except Exception:
                pass
        if self.isRunning():
            try:
                self.wait(500)
            except Exception:
                pass


class EngineDownloader(QThread):
    progress_update = Signal(int)
    status_update = Signal(str)
    finished_download = Signal(bool, str)

    def __init__(self, upgrade_to_gpu: bool = False, parent=None):
        super().__init__(parent)
        self.upgrade_to_gpu = upgrade_to_gpu
        self.current_process: Optional[subprocess.Popen] = None

    def _run_tracked_command(
        self,
        cmd: List[str],
        env: dict,
        timeout: Optional[float] = None,
    ) -> subprocess.CompletedProcess:
        """
        Runs a subprocess via Popen, registered with process_tracker, with UTF-8
        decoding and cooperative interruption/timeout handling.
        """
        if self.isInterruptionRequested():
            raise InterruptedError("Engine installation cancelled")

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
        }
        kwargs.update(get_subprocess_spawn_kwargs())

        proc = subprocess.Popen(cmd, **kwargs)
        self.current_process = proc

        try:
            from process_tracker import register_process, unregister_process, kill_process_tree
        except ImportError:
            register_process = lambda _p: None
            unregister_process = lambda _p: None
            kill_process_tree = lambda _pid: None

        register_process(proc)
        start_time = time.time()
        stdout_data = ""
        stderr_data = ""

        try:
            while True:
                if self.isInterruptionRequested():
                    kill_process_tree(proc.pid)
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    raise InterruptedError("Engine installation cancelled")

                if timeout is not None and (time.time() - start_time) > timeout:
                    kill_process_tree(proc.pid)
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    raise subprocess.TimeoutExpired(cmd, timeout)

                try:
                    out, err = proc.communicate(timeout=0.2)
                    stdout_data = out or ""
                    stderr_data = err or ""
                    break
                except subprocess.TimeoutExpired:
                    continue

            return subprocess.CompletedProcess(cmd, proc.returncode, stdout_data, stderr_data)
        finally:
            unregister_process(proc)
            if self.current_process is proc:
                self.current_process = None

    def _download_micromamba(self, mamba_url: str, mamba_exe: str, mamba_name: str, bin_dir: str) -> None:
        import requests
        staging_dir = tempfile.mkdtemp(prefix="mamba_stage_", dir=DependencyManager.get_appdata_dir())
        tar_part = os.path.join(staging_dir, "micromamba.tar.bz2.part")
        tar_path = os.path.join(staging_dir, "micromamba.tar.bz2")
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            with requests.get(mamba_url, headers=headers, stream=True, timeout=(15, 60)) as resp:
                resp.raise_for_status()
                with open(tar_part, 'wb') as out_file:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if self.isInterruptionRequested():
                            raise InterruptedError("Download cancelled")
                        if chunk:
                            out_file.write(chunk)
            _atomic_replace_file(tar_part, tar_path)

            self.status_update.emit("Extracting Micromamba...")
            extracted_path = None
            with tarfile.open(tar_path, "r:bz2") as tar:
                for member in tar.getmembers():
                    if self.isInterruptionRequested():
                        raise InterruptedError("Download cancelled")
                    base = os.path.basename(member.name)
                    if base in ("micromamba.exe", "micromamba") and member.isfile():
                        member.name = mamba_name
                        tar.extract(member, staging_dir)
                        extracted_path = os.path.join(staging_dir, mamba_name)
                        break

            if not extracted_path or not os.path.isfile(extracted_path) or os.path.getsize(extracted_path) <= 0:
                raise RuntimeError("Failed to extract micromamba executable.")

            if sys.platform != "win32":
                try:
                    os.chmod(extracted_path, 0o755)
                except Exception:
                    pass

            _atomic_replace_file(extracted_path, mamba_exe)
        finally:
            if os.path.exists(staging_dir):
                try:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                except Exception:
                    pass

    def _probe_cuda_hardware(self, python_exe: str, engine_env: dict) -> Dict[str, Any]:
        """
        Multi-layer fail-safe CUDA hardware probe executed ONLY inside the background
        worker's isolated env_python subprocess (never in the main GUI process, never on macOS):
          1. Primary: ctypes CUDA Driver API (cuDriverGetVersion, cuInit(0),
             cuDeviceGetCount, cuDeviceGetAttribute(75) for compute capability major).
          2. Fallback 1: nvidia-smi CUDA Version query.
          3. Fallback 2: Unknown driver/device -> returns None fields (routed safely to cu121).
        Never raises an unhandled exception; always returns a dict.
        """
        if sys.platform == "darwin":
            return {"driver": None, "device_count": 0, "compute_cap_major": None, "source": "macos"}

        probe_script = (
            "import ctypes, json, sys\n"
            "res = {'driver': None, 'device_count': None, 'compute_cap_major': None, 'source': 'fallback'}\n"
            "lib = None\n"
            "names = ['nvcuda.dll'] if sys.platform == 'win32' else ['libcuda.so.1', 'libcuda.so']\n"
            "for n in names:\n"
            "    try:\n"
            "        lib = ctypes.CDLL(n)\n"
            "        break\n"
            "    except Exception:\n"
            "        pass\n"
            "if lib is not None:\n"
            "    try:\n"
            "        v = ctypes.c_int(0)\n"
            "        if lib.cuDriverGetVersion(ctypes.byref(v)) == 0 and v.value > 0:\n"
            "            res['driver'] = [v.value // 1000, (v.value % 1000) // 10]\n"
            "            res['source'] = 'driver_api'\n"
            "    except Exception:\n"
            "        pass\n"
            "    try:\n"
            "        init_rc = lib.cuInit(0)\n"
            "        if init_rc == 0:\n"
            "            cnt = ctypes.c_int(0)\n"
            "            if lib.cuDeviceGetCount(ctypes.byref(cnt)) == 0:\n"
            "                res['device_count'] = cnt.value\n"
            "                res['source'] = 'driver_api'\n"
            "                max_cc = None\n"
            "                for idx in range(cnt.value):\n"
            "                    try:\n"
            "                        dev = ctypes.c_int(0)\n"
            "                        if lib.cuDeviceGet(ctypes.byref(dev), idx) == 0:\n"
            "                            maj = ctypes.c_int(0)\n"
            "                            if lib.cuDeviceGetAttribute(ctypes.byref(maj), 75, dev) == 0:\n"
            "                                if max_cc is None or maj.value > max_cc:\n"
            "                                    max_cc = maj.value\n"
            "                    except Exception:\n"
            "                        pass\n"
            "                res['compute_cap_major'] = max_cc\n"
            "        elif init_rc == 100:\n"
            "            res['device_count'] = 0\n"
            "            res['source'] = 'driver_api'\n"
            "    except Exception:\n"
            "        pass\n"
            "print(json.dumps(res))\n"
        )

        probe_result: Dict[str, Any] = {
            "driver": None,
            "device_count": None,
            "compute_cap_major": None,
            "source": "fallback",
        }

        try:
            res = self._run_tracked_command([python_exe, "-c", probe_script], env=engine_env, timeout=10)
            if res.returncode == 0 and res.stdout:
                lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
                for ln in reversed(lines):
                    if ln.startswith("{") and ln.endswith("}"):
                        parsed = json.loads(ln)
                        if isinstance(parsed, dict):
                            probe_result.update(parsed)
                            break
        except InterruptedError:
            raise
        except Exception as e:
            logger.warning(f"CUDA driver API probe failed (non-fatal, trying fallback): {e}")

        # Fallback 1: If driver version is still unknown (and not confirmed 0 devices), try nvidia-smi output
        if probe_result.get("driver") is None and probe_result.get("device_count") != 0:
            smi = shutil.which("nvidia-smi")
            if smi:
                try:
                    smi_res = self._run_tracked_command([smi], env=engine_env, timeout=5)
                    if smi_res.returncode == 0 and smi_res.stdout:
                        m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", smi_res.stdout)
                        if m:
                            probe_result["driver"] = [int(m.group(1)), int(m.group(2))]
                            probe_result["source"] = "nvidia-smi"
                except InterruptedError:
                    raise
                except Exception as e:
                    logger.debug(f"nvidia-smi fallback probe failed (non-fatal): {e}")

        logger.info(f"CUDA hardware probe result: {probe_result}")
        return probe_result

    def run(self):
        constraints_path = None
        try:
            bin_dir = DependencyManager.get_bin_dir()
            env_dir = DependencyManager.get_env_dir()
            mamba_name = "micromamba.exe" if sys.platform == "win32" else "micromamba"
            mamba_exe = os.path.join(bin_dir, mamba_name)

            # Cleanup of Corrupted Legacy macOS Environment (~/Library/Application Support/EarPurifier/env)
            if sys.platform == "darwin":
                legacy_env = os.path.join(DependencyManager.get_appdata_dir(), "env")
                if os.path.exists(legacy_env):
                    try:
                        self.status_update.emit("Cleaning up legacy environment...")
                        shutil.rmtree(legacy_env, ignore_errors=True)
                    except Exception as e:
                        logger.warning(f"Failed to clean up legacy env directory {legacy_env}: {e}")

            # 1. Download Micromamba if missing (checking legacy bin first)
            legacy_mamba = os.path.join(DependencyManager.get_appdata_dir(), "bin", mamba_name)
            if not os.path.exists(mamba_exe) and os.path.exists(legacy_mamba):
                try:
                    shutil.copy2(legacy_mamba, mamba_exe)
                    if sys.platform != "win32":
                        os.chmod(mamba_exe, 0o755)
                except Exception:
                    mamba_exe = legacy_mamba

            if not os.path.exists(mamba_exe):
                self.status_update.emit("Downloading Micromamba package manager...")
                machine = platform.machine().lower()
                if sys.platform == "win32":
                    mamba_url = "https://micro.mamba.pm/api/micromamba/win-64/latest"
                elif sys.platform == "darwin":
                    arch = "osx-arm64" if machine in ("arm64", "aarch64") else "osx-64"
                    mamba_url = f"https://micro.mamba.pm/api/micromamba/{arch}/latest"
                else:
                    arch = "linux-aarch64" if machine in ("arm64", "aarch64") else "linux-64"
                    mamba_url = f"https://micro.mamba.pm/api/micromamba/{arch}/latest"

                self._download_micromamba(mamba_url, mamba_exe, mamba_name, bin_dir)

            # Ensure micromamba is executable on POSIX before invocation
            if sys.platform != "win32" and os.path.exists(mamba_exe):
                try:
                    os.chmod(mamba_exe, 0o755)
                except Exception:
                    pass

            # 2. Create / Validate Environment
            self.status_update.emit("Building isolated Python environment... (Step 1/3)")
            self.progress_update.emit(20)

            engine_env = DependencyManager.get_engine_subprocess_env()
            python_exe = DependencyManager.get_engine_python()

            expected_py_ver = "3.10" if sys.platform != "win32" else "3.11"
            rebuild_env = not os.path.exists(env_dir) or not os.path.exists(python_exe)
            if not rebuild_env:
                try:
                    ver_check = self._run_tracked_command(
                        [python_exe, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                        env=engine_env,
                        timeout=10,
                    )
                    if ver_check.returncode != 0 or ver_check.stdout.strip() != expected_py_ver:
                        rebuild_env = True
                except InterruptedError:
                    raise
                except Exception:
                    rebuild_env = True

            if rebuild_env:
                if os.path.exists(env_dir):
                    try:
                        shutil.rmtree(env_dir, ignore_errors=True)
                    except Exception:
                        pass
                py_spec = f"python={expected_py_ver}"
                res = self._run_tracked_command(
                    [mamba_exe, "create", "-y", "-p", env_dir, py_spec, "pip", "-c", "conda-forge"],
                    env=engine_env,
                )
                if res.returncode != 0:
                    err_msg = res.stderr.strip() or res.stdout.strip() or "Unknown micromamba error"
                    raise RuntimeError(f"Environment creation failed: {err_msg}")
                # Refresh engine env after creating env_dir
                engine_env = DependencyManager.get_engine_subprocess_env()

            if sys.platform != "win32" and os.path.exists(python_exe):
                try:
                    os.chmod(python_exe, 0o755)
                except Exception:
                    pass

            # Determine GPU candidates before mutating an existing environment on upgrade
            has_gpu = False if sys.platform == "darwin" else DependencyManager.has_nvidia_gpu()
            cuda_indices: List[str] = []
            if sys.platform != "darwin" and (has_gpu or self.upgrade_to_gpu):
                probe = self._probe_cuda_hardware(python_exe, engine_env)
                cuda_indices = DependencyManager.select_pytorch_cuda_indices(
                    probe.get("driver"),
                    compute_cap_major=probe.get("compute_cap_major"),
                    device_count=probe.get("device_count"),
                )
                if not cuda_indices:
                    if self.upgrade_to_gpu:
                        raise RuntimeError(
                            _t_safe(
                                "gpu_banner_driver_old",
                                "Your NVIDIA graphics driver is too old for CUDA 12 GPU acceleration. Please update your NVIDIA driver and try again."
                            )
                        )
                    logger.warning(
                        "NVIDIA driver < 12.1 or no active CUDA device detected (probe=%s). "
                        "Skipping CUDA 12 download and installing CPU engine.",
                        probe,
                    )

            marker_file = os.path.join(env_dir, ".engine_installed")
            in_progress_file = os.path.join(env_dir, ".engine_in_progress")

            # Mark environment mutation in progress so legacy backfill never resurrects
            # a partially installed or Step-4-rejected environment.
            try:
                if os.path.isdir(env_dir):
                    with open(in_progress_file, "w", encoding="utf-8") as pf:
                        pf.write("IN_PROGRESS\n")
            except Exception as e:
                logger.debug(f"Could not write {in_progress_file}: {e}")

            # Uninstall conflicting CPU/CUDA wheels before Step 2 when upgrading OR when
            # repairing an existing env that has a stale CPU-only torch wheel on a CUDA host.
            needs_stale_cpu_uninstall = False
            if not rebuild_env and not self.upgrade_to_gpu and sys.platform != "darwin" and has_gpu and cuda_indices:
                installed_info = DependencyManager.get_installed_torch_info()
                if installed_info.get("installed") and not installed_info.get("is_cuda"):
                    needs_stale_cpu_uninstall = True

            if self.upgrade_to_gpu or needs_stale_cpu_uninstall:
                if os.path.exists(marker_file):
                    try:
                        os.remove(marker_file)
                    except Exception as e:
                        logger.warning(f"Could not remove {marker_file} before upgrade: {e}")

                self.status_update.emit("NVIDIA GPU detected. Installing PyTorch CUDA acceleration... (Step 2/3)")
                self.progress_update.emit(35)
                uninstall_cmd = [
                    python_exe, "-m", "pip", "uninstall", "-y",
                    "torch", "torchvision", "onnxruntime", "onnxruntime-gpu", "audio-separator",
                ]
                self._run_tracked_command(uninstall_cmd, env=engine_env)

            pip_base = [
                python_exe, "-m", "pip", "install",
                "--no-cache-dir", "--disable-pip-version-check",
                "--prefer-binary", "--default-timeout=120",
            ]

            # 3. Install PyTorch + TorchVision (Adaptive Hardware Acceleration)
            installed_gpu = False
            chosen_index: Optional[str] = None
            last_cuda_err = ""

            if sys.platform == "darwin":
                self.status_update.emit("Installing PyTorch (Apple Silicon Metal / CPU)... (Step 2/3)")
                self.progress_update.emit(50)
                res = self._run_tracked_command(pip_base + ["torch", "torchvision"], env=engine_env)
                if res.returncode != 0:
                    err_msg = res.stderr.strip() or res.stdout.strip() or "Unknown pip error"
                    raise RuntimeError(f"PyTorch install failed: {err_msg}")
            else:
                if (has_gpu or self.upgrade_to_gpu) and cuda_indices:
                    self.status_update.emit("NVIDIA GPU detected. Installing PyTorch CUDA acceleration... (Step 2/3)")
                    self.progress_update.emit(45)
                    for idx_tag in cuda_indices:
                        index_url = f"https://download.pytorch.org/whl/{idx_tag}"
                        logger.info(f"Attempting PyTorch + TorchVision install from {index_url}")
                        res = self._run_tracked_command(
                            pip_base + ["torch", "torchvision", "--index-url", index_url],
                            env=engine_env,
                        )
                        if res.returncode == 0:
                            installed_gpu = True
                            chosen_index = index_url
                            break
                        last_cuda_err = res.stderr.strip() or res.stdout.strip() or f"pip failed for {idx_tag}"
                        logger.warning(f"CUDA PyTorch install failed for {idx_tag} ({last_cuda_err}). Trying next fallback...")

                if not installed_gpu:
                    if self.upgrade_to_gpu:
                        raise RuntimeError(f"CUDA PyTorch upgrade failed: {last_cuda_err or 'No compatible CUDA 12 wheel installed'}")

                    self.status_update.emit("Installing PyTorch CPU engine... (Step 2/3)")
                    self.progress_update.emit(50)
                    cpu_index = "https://download.pytorch.org/whl/cpu"
                    res = self._run_tracked_command(
                        pip_base + ["torch", "torchvision", "--index-url", cpu_index],
                        env=engine_env,
                    )
                    if res.returncode != 0:
                        err_msg = res.stderr.strip() or res.stdout.strip() or "Unknown pip error"
                        raise RuntimeError(f"PyTorch install failed: {err_msg}")
                    chosen_index = cpu_index

            # 4. Constraints-Locked Audio Separator + CUDA 12 ONNXRuntime Install
            self.status_update.emit("Installing Audio Separator... (Step 3/3)")
            self.progress_update.emit(85)

            # Query exact installed torch & torchvision versions to lock pip constraints
            ver_query = self._run_tracked_command(
                [
                    python_exe, "-c",
                    "import importlib.metadata as m; "
                    "print('torch==' + m.version('torch')); "
                    "print('torchvision==' + m.version('torchvision'))"
                ],
                env=engine_env,
                timeout=15,
            )
            constraint_lines = []
            if ver_query.returncode == 0 and ver_query.stdout:
                for ln in ver_query.stdout.splitlines():
                    ln = ln.strip()
                    if ln.startswith("torch==") or ln.startswith("torchvision=="):
                        constraint_lines.append(ln)

            sep_cmd = list(pip_base)
            if constraint_lines:
                c_fname = f".constraints_{uuid.uuid4().hex[:8]}.txt"
                constraints_path = os.path.join(env_dir, c_fname)
                try:
                    with open(constraints_path, "w", encoding="utf-8") as cf:
                        cf.write("\n".join(constraint_lines) + "\n")
                except OSError:
                    constraints_path = os.path.join(tempfile.gettempdir(), c_fname)
                    with open(constraints_path, "w", encoding="utf-8") as cf:
                        cf.write("\n".join(constraint_lines) + "\n")
                sep_cmd.extend(["-c", constraints_path])

            if chosen_index:
                sep_cmd.extend(["--extra-index-url", chosen_index])

            if sys.platform == "darwin":
                sep_cmd.append("audio-separator[cpu]")
            elif installed_gpu:
                sep_cmd.extend(["audio-separator[gpu]", "onnxruntime-gpu<1.27.0"])
            else:
                sep_cmd.append("audio-separator[cpu]")

            res = self._run_tracked_command(sep_cmd, env=engine_env)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip() or "Unknown pip error"
                raise RuntimeError(f"Audio Separator install failed: {err_msg}")

            # On POSIX, ensure all binaries in env/bin are executable
            if sys.platform != "win32":
                env_bin = os.path.join(env_dir, "bin")
                if os.path.isdir(env_bin):
                    for fname in os.listdir(env_bin):
                        fpath = os.path.join(env_bin, fname)
                        if os.path.isfile(fpath):
                            try:
                                os.chmod(fpath, 0o755)
                            except Exception:
                                pass

            # 5. Step 4: Verify Installation Integrity (Anti-CPU-Overwrite Guard)
            self.status_update.emit("Verifying Local AI Engine installation...")
            self.progress_update.emit(95)

            engine_env = DependencyManager.get_engine_subprocess_env()
            verify_script = (
                "import importlib.metadata as m, json, torch, audio_separator\n"
                "mps_avail = bool(hasattr(torch.backends, 'mps') and torch.backends.mps.is_available())\n"
                "print(json.dumps({\n"
                "    'torch_version': getattr(torch, '__version__', ''),\n"
                "    'dist_version': m.version('torch'),\n"
                "    'cuda': getattr(torch.version, 'cuda', None),\n"
                "    'cuda_available': bool(torch.cuda.is_available()),\n"
                "    'mps_available': mps_avail,\n"
                "}))\n"
            )
            v_res = self._run_tracked_command([python_exe, "-c", verify_script], env=engine_env, timeout=60)
            if v_res.returncode != 0:
                err_msg = v_res.stderr.strip() or v_res.stdout.strip() or "Verification import failed"
                raise RuntimeError(f"Engine verification failed: {err_msg}")

            verify_data: Dict[str, Any] = {}
            for ln in reversed((v_res.stdout or "").splitlines()):
                ln = ln.strip()
                if ln.startswith("{") and ln.endswith("}"):
                    try:
                        verify_data = json.loads(ln)
                        break
                    except Exception:
                        pass

            torch_ver = str(verify_data.get("torch_version") or verify_data.get("dist_version") or "")
            dist_ver = str(verify_data.get("dist_version") or "")
            cuda_ver = verify_data.get("cuda")
            cuda_avail = bool(verify_data.get("cuda_available", False))
            mps_avail = bool(verify_data.get("mps_available", False))

            if installed_gpu:
                if not cuda_ver:
                    raise RuntimeError(
                        f"CUDA verification failed: installed torch ({torch_ver}) has torch.version.cuda=None."
                    )
                if sys.platform == "win32" and "+cu" not in dist_ver and "+cu" not in torch_ver:
                    raise RuntimeError(
                        f"CUDA verification failed on Windows: expected '+cu' wheel, got '{torch_ver}'."
                    )

            logger.info(
                "Local Engine verified: torch=%s cuda=%s cuda_available=%s mps_available=%s",
                torch_ver, cuda_ver, cuda_avail, mps_avail,
            )

            # 6. Write installation verification marker
            if installed_gpu:
                mode_tag = "cuda"
            elif sys.platform == "darwin" and mps_avail:
                mode_tag = "mps"
            else:
                mode_tag = "cpu"

            with open(marker_file, "w", encoding="utf-8") as f:
                f.write(f"INSTALLED\nmode={mode_tag}\ntorch={torch_ver}\n")
            if os.path.exists(in_progress_file):
                try:
                    os.remove(in_progress_file)
                except Exception:
                    pass

            if sys.platform == "darwin":
                engine_type = "Apple Silicon Metal / CPU"
            else:
                engine_type = "GPU Accelerated" if installed_gpu else "CPU"
            self.status_update.emit(f"Local AI Engine ({engine_type}) installed successfully.")
            self.progress_update.emit(100)
            self.finished_download.emit(True, "Success")

        except InterruptedError:
            logger.info("Engine installation cancelled.")
            return
        except Exception as e:
            self.finished_download.emit(False, str(e))
        finally:
            if constraints_path and os.path.exists(constraints_path):
                try:
                    os.remove(constraints_path)
                except Exception:
                    pass

    def stop(self):
        self.requestInterruption()
        proc = getattr(self, "current_process", None)
        if proc is not None:
            try:
                from process_tracker import kill_process_tree
                kill_process_tree(proc.pid)
                proc.kill()
            except Exception:
                pass
        if self.isRunning():
            try:
                self.wait(500)
            except Exception:
                pass


class ModelDownloader(QThread):
    progress_update = Signal(int)
    progress_detail = Signal(int, str)
    status_update = Signal(str)
    finished_download = Signal(bool, str)

    # Matches tqdm weight bars with explicit <current>/<total><unit> >= 10 MiB / GiB
    # (supporting k/K/M/G/T, B, kB/KiB, MB/MiB, GB/GiB on current & total) so auxiliary
    # JSON/YAML downloads (e.g. 28.3k/28.3k [90.9MiB/s]) never lock last_pct=100.
    _TQDM_WEIGHT_RE = re.compile(
        r'(\d{1,3})%\|[^|]*\|\s*[\d.]+(?:\s*(?:[kKMGT]i?B?|[bB]))?/([\d.]+)\s*([MG])(?:i?B)?\b'
    )
    _TQDM_SPEED_RE = re.compile(
        r',\s*([\d.]+)\s*([kKMGT]?)(i?B)/s\b'
    )
    _DEGRADED_HOSTS_LOCK = threading.Lock()
    _DEGRADED_HOSTS: Dict[str, float] = {}
    _DEGRADED_HOST_TTL_SEC = 300.0

    @classmethod
    def clear_degraded_hosts(cls) -> None:
        """Clears session-level degraded mirror host memory (primarily for tests)."""
        with cls._DEGRADED_HOSTS_LOCK:
            cls._DEGRADED_HOSTS.clear()

    @classmethod
    def _get_session_degraded_hosts(cls) -> Set[str]:
        now = time.monotonic()
        with cls._DEGRADED_HOSTS_LOCK:
            expired = [h for h, ts in cls._DEGRADED_HOSTS.items() if (now - ts) > cls._DEGRADED_HOST_TTL_SEC]
            for h in expired:
                cls._DEGRADED_HOSTS.pop(h, None)
            return set(cls._DEGRADED_HOSTS.keys())

    @classmethod
    def _record_host_outcomes(cls, failed: Set[str], succeeded: Set[str]) -> None:
        now = time.monotonic()
        with cls._DEGRADED_HOSTS_LOCK:
            for h in failed:
                if h:
                    cls._DEGRADED_HOSTS[h] = now
            for h in succeeded:
                if h:
                    cls._DEGRADED_HOSTS.pop(h, None)

    def __init__(self, model_name: str, models_dir: str):
        super().__init__()
        self.model_name = model_name
        self.models_dir = models_dir
        self.process: Optional[subprocess.Popen] = None
        self._dl_lock = threading.Lock()
        self._active_downloader: Optional[_SegmentedFileDownloader] = None
        self.last_error_details: str = ""
        self.last_error_is_ffmpeg: bool = False

    @classmethod
    def parse_weight_progress(cls, line: str) -> Optional[int]:
        """
        Extracts percentage (0..100) from a tqdm progress line ONLY when the
        total file size is >= 10 MB (or in GB), filtering out small metadata JSON/YAML
        downloads like download_checks.json (28.3k/28.3k [90.9MiB/s]).
        """
        match = cls._TQDM_WEIGHT_RE.search(line)
        if not match:
            return None
        try:
            pct = int(match.group(1))
            total_val = float(match.group(2))
            unit = match.group(3)
            if unit == "G" or (unit == "M" and total_val >= 10.0):
                if 0 <= pct <= 100:
                    return pct
        except Exception:
            return None
        return None

    @classmethod
    def parse_weight_speed(cls, line: str) -> str:
        """Extracts a human-readable speed string from a tqdm progress line, if present."""
        match = cls._TQDM_SPEED_RE.search(line)
        if not match:
            return ""
        try:
            val = float(match.group(1))
            prefix = match.group(2).upper()
            if val <= 0:
                return ""
            if prefix == "G":
                return f"{val * 1024.0:.1f} MB/s"
            if prefix == "M":
                return f"{val:.1f} MB/s"
            if prefix == "K":
                return f"{val:.0f} KB/s"
            return f"{int(val)} B/s"
        except Exception:
            return ""

    def stop(self):
        self.requestInterruption()
        with self._dl_lock:
            dl = self._active_downloader
        if dl is not None:
            try:
                dl.cancel()
            except Exception:
                pass
        proc = getattr(self, "process", None)
        if proc is not None:
            try:
                from process_tracker import kill_process_tree
                kill_process_tree(proc.pid)
                proc.kill()
            except Exception:
                pass
        if self.isRunning():
            try:
                self.wait(500)
            except Exception:
                pass

    def _create_segmented_downloader(self) -> _SegmentedFileDownloader:
        return _SegmentedFileDownloader(cancel_check=self.isInterruptionRequested)

    def _download_manifest_entry(self, manifest_entry: Dict[str, Any]) -> None:
        os.makedirs(self.models_dir, exist_ok=True)
        installed_checksums = load_installed_model_checksums()
        failed_hosts: Set[str] = self._get_session_degraded_hosts()

        def _prioritize_mirrors(mirrors: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            if not failed_hosts:
                return list(mirrors)
            healthy = [m for m in mirrors if _extract_url_host(m[1]) not in failed_hosts]
            degraded = [m for m in mirrors if _extract_url_host(m[1]) in failed_hosts]
            return healthy + degraded

        def _resolve_sha_and_size(spec: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
            fname = spec["filename"]
            fallback_sha = spec.get("sha256")
            installed_sha = installed_checksums.get(fname)
            if installed_sha:
                # If audio-separator updated a file's checksum, don't enforce a stale hardcoded byte size
                exp_size = spec.get("size") if (not fallback_sha or installed_sha == fallback_sha.lower()) else None
                return installed_sha, exp_size
            return (fallback_sha.lower() if fallback_sha else None), spec.get("size")

        primary = manifest_entry["primary"]
        p_sha, p_size = _resolve_sha_and_size(primary)
        p_dest = os.path.join(self.models_dir, primary["filename"])
        # Remove any orphaned audio-separator *.partial files from earlier runs
        _cleanup_stale_partial_files(self.models_dir, primary["filename"], include_segmented_parts=False)

        # If resuming a prior segmented download, surface existing progress immediately before sidecars
        last_pct = 0
        if p_size and p_size > 0:
            probe_dl = self._create_segmented_downloader()
            resumed_b = probe_dl._compute_resumed_bytes_on_disk(
                p_dest + ".part", p_dest + ".part.meta", p_size, p_sha
            )
            if resumed_b > 0:
                init_pct = min(99, int((resumed_b / p_size) * 100))
                if init_pct > 0:
                    last_pct = init_pct
                    self.progress_update.emit(init_pct)
                    self.progress_detail.emit(init_pct, "")
                    self.status_update.emit(f"Resuming... {init_pct}%")

        def _on_sidecar_progress(_downloaded: int, _total: Optional[int], _speed_bps: float, stage: str):
            if stage == "reconnecting":
                self.progress_detail.emit(last_pct, "__RECONNECTING__")
                self.status_update.emit(f"Reconnecting... {last_pct}%")

        # 1. Download small required sidecars (.yaml, JSON metadata) first
        for sidecar in manifest_entry.get("sidecars", []):
            if self.isInterruptionRequested():
                raise DownloadCancelledError("Model download cancelled")
            sc_sha, sc_size = _resolve_sha_and_size(sidecar)
            sc_dest = os.path.join(self.models_dir, sidecar["filename"])
            dl = self._create_segmented_downloader()
            with self._dl_lock:
                self._active_downloader = dl
            try:
                dl.download(
                    mirrors=_prioritize_mirrors(sidecar["mirrors"]),
                    dest_path=sc_dest,
                    expected_size=sc_size,
                    expected_sha256=sc_sha,
                    validate_json=bool(sidecar.get("validate_json", False)),
                    json_required_keys=sidecar.get("json_required_keys"),
                    json_min_keys=int(sidecar.get("json_min_keys", 0)),
                    resume_enabled=False,
                    skip_if_valid=True,
                    progress_cb=_on_sidecar_progress,
                )
            finally:
                dl_failed = set(getattr(dl, "last_failed_hosts", set()))
                dl_succeeded = set(getattr(dl, "last_succeeded_hosts", set()))
                failed_hosts.update(dl_failed)
                failed_hosts.difference_update(dl_succeeded)
                self._record_host_outcomes(dl_failed, dl_succeeded)
                with self._dl_lock:
                    if self._active_downloader is dl:
                        self._active_downloader = None

        # 2. Download primary model weights with segmented transfer, VPN recovery, & speed telemetry
        def _on_weight_progress(downloaded: int, total: Optional[int], speed_bps: float, stage: str):
            nonlocal last_pct
            if stage == "retrying":
                last_pct = 0
                self.progress_update.emit(0)
                self.progress_detail.emit(0, "")
                self.status_update.emit("Retrying model download...")
                return
            if stage == "reconnecting":
                if total and total > 0 and downloaded > 0:
                    raw_pct = int((min(downloaded, total) / total) * 100)
                    last_pct = max(last_pct, min(99, raw_pct))
                self.progress_detail.emit(last_pct, "__RECONNECTING__")
                self.status_update.emit(f"Reconnecting... {last_pct}%")
                return
            if stage == "verifying":
                pct = max(last_pct, 100)
                if pct > last_pct:
                    self.progress_update.emit(pct)
                    last_pct = pct
                self.progress_detail.emit(pct, "__VERIFYING__")
                self.status_update.emit("Verifying model integrity...")
                return

            if total and total > 0:
                raw_pct = int((min(downloaded, total) / total) * 100)
                pct = max(last_pct, min(100, raw_pct))
                speed_txt = _format_download_speed(speed_bps)
                if pct > last_pct:
                    self.progress_update.emit(pct)
                    self.status_update.emit(f"Downloading... {pct}%")
                    last_pct = pct
                self.progress_detail.emit(pct, speed_txt)

        dl = self._create_segmented_downloader()
        with self._dl_lock:
            self._active_downloader = dl
        try:
            dl.download(
                mirrors=_prioritize_mirrors(primary["mirrors"]),
                dest_path=p_dest,
                expected_size=p_size,
                expected_sha256=p_sha,
                resume_enabled=True,
                skip_if_valid=True,
                progress_cb=_on_weight_progress,
            )
            _cleanup_stale_partial_files(self.models_dir, primary["filename"], include_segmented_parts=False)
        finally:
            dl_failed = set(getattr(dl, "last_failed_hosts", set()))
            dl_succeeded = set(getattr(dl, "last_succeeded_hosts", set()))
            self._record_host_outcomes(dl_failed, dl_succeeded)
            with self._dl_lock:
                if self._active_downloader is dl:
                    self._active_downloader = None

    def _run_separator_subprocess_fallback(self, prior_error: str = "") -> None:
        script_path = None
        try:
            env_python = DependencyManager.get_engine_python()
            env_dir = DependencyManager.get_env_dir()

            script_path = os.path.join(env_dir, f"{uuid.uuid4().hex[:8]}_temp_download.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(
                    "import inspect, logging, sys\n"
                    "from audio_separator.separator import Separator\n"
                    "logging.basicConfig(stream=sys.stdout, level=logging.INFO)\n"
                    f"init_kwargs = {{'model_file_dir': {repr(self.models_dir)}, 'log_level': logging.INFO}}\n"
                    "if 'info_only' in inspect.signature(Separator.__init__).parameters and hasattr(Separator, 'download_model_and_data'):\n"
                    "    init_kwargs['info_only'] = True\n"
                    "    separator = Separator(**init_kwargs)\n"
                    f"    separator.download_model_and_data({repr(self.model_name)})\n"
                    "else:\n"
                    "    separator = Separator(**init_kwargs)\n"
                    f"    separator.load_model({repr(self.model_name)})\n"
                    "print('SUCCESS_DOWNLOAD')\n"
                )

            # Direct stderr to stdout to form a single stream and prevent pipe buffer deadlocks
            kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            }
            kwargs.update(get_subprocess_spawn_kwargs())

            env = DependencyManager.get_engine_subprocess_env()

            self.process = subprocess.Popen([env_python, script_path], env=env, **kwargs)
            process = self.process
            try:
                from process_tracker import register_process, unregister_process
                register_process(process)
            except Exception:
                pass

            captured_output: List[str] = []
            last_pct = -1

            while True:
                if self.isInterruptionRequested():
                    try:
                        from process_tracker import kill_process_tree
                        kill_process_tree(process.pid)
                        process.kill()
                    except Exception:
                        pass
                    raise InterruptedError("Model download cancelled")

                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    captured_output.append(line)
                    pct = self.parse_weight_progress(line)
                    if pct is not None:
                        speed_txt = self.parse_weight_speed(line)
                        if pct > last_pct:
                            self.progress_update.emit(pct)
                            self.progress_detail.emit(pct, speed_txt)
                            self.status_update.emit(f"Downloading... {pct}%")
                            last_pct = pct
                        elif speed_txt:
                            self.progress_detail.emit(max(0, last_pct), speed_txt)

            process.wait()
            try:
                from process_tracker import unregister_process
                unregister_process(process)
            except Exception:
                pass
            self.process = None

            full_output = "".join(captured_output)
            if "SUCCESS_DOWNLOAD" in full_output:
                return

            combined_output = f"Direct download error: {prior_error}\n\n{full_output}" if prior_error else full_output
            self.last_error_is_ffmpeg = is_ffmpeg_missing_error(combined_output)
            summary, raw_details = classify_local_error(combined_output)
            self.last_error_details = raw_details
            raise RuntimeError(summary)
        finally:
            if getattr(self, "process", None) is not None:
                try:
                    from process_tracker import unregister_process
                    unregister_process(self.process)
                except Exception:
                    pass
                self.process = None
            if script_path and os.path.exists(script_path):
                try:
                    os.remove(script_path)
                except Exception:
                    pass

    def run(self):
        self.last_error_details = ""
        self.last_error_is_ffmpeg = False
        try:
            self.status_update.emit("Downloading Model...")
            self.progress_update.emit(0)
            self.progress_detail.emit(0, "")

            manifest_entry = LOCAL_MODEL_MANIFEST.get(self.model_name)
            if manifest_entry is not None:
                try:
                    self._download_manifest_entry(manifest_entry)
                except InterruptedError:
                    raise
                except InsufficientDiskSpaceError as disk_err:
                    raw = str(disk_err)
                    summary, raw_details = classify_local_error(raw)
                    self.last_error_details = raw_details
                    raise RuntimeError(summary) from disk_err
                except Exception as direct_err:
                    if self.isInterruptionRequested():
                        raise InterruptedError("Model download cancelled") from direct_err
                    if _is_disk_full_error(direct_err):
                        raw = str(direct_err)
                        summary, raw_details = classify_local_error(raw)
                        self.last_error_details = raw_details
                        raise RuntimeError(summary) from direct_err
                    if _is_recoverable_network_error(direct_err):
                        # Preserve .part and .part.meta on disk so the user can resume seamlessly
                        # without falling back to audio-separator (which restarts at 0% and orphans parts).
                        raw = str(direct_err)
                        summary, raw_details = classify_local_error(raw)
                        self.last_error_details = raw_details
                        raise RuntimeError(summary) from direct_err
                    logger.warning(
                        "Direct multi-CDN download failed for %s (%s); cleaning up partial parts and falling back to audio-separator subprocess.",
                        self.model_name,
                        direct_err,
                    )
                    primary_fn = manifest_entry["primary"]["filename"]
                    _cleanup_stale_partial_files(self.models_dir, primary_fn, include_segmented_parts=True)
                    self._run_separator_subprocess_fallback(prior_error=str(direct_err))
            else:
                self._run_separator_subprocess_fallback()

            self.progress_update.emit(100)
            self.progress_detail.emit(100, "")
            self.status_update.emit("Model downloaded successfully!")
            self.finished_download.emit(True, "Success")

        except InterruptedError:
            logger.info("Model download cancelled.")
            return
        except Exception as e:
            self.finished_download.emit(False, str(e))
