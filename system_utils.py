"""
EarPurifier - Cross-Platform System and Environment Utilities.
Provides unified OS detection, standard user data directory resolution,
default output directory resolution, process group management,
and native desktop file manager interactions.
"""

import os
import sys
import subprocess
import logging
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

logger = logging.getLogger(__name__)


def get_current_os() -> str:
    """
    Returns normalized OS name: 'windows', 'macos', or 'linux'.
    """
    if sys.platform.startswith("win"):
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    return "linux"


def get_app_data_dir() -> str:
    """
    Returns the platform-standard application data directory:
    - Windows: %APPDATA%/EarPurifier (e.g. C:/Users/<user>/AppData/Roaming/EarPurifier)
    - macOS:   ~/Library/Application Support/EarPurifier
    - Linux:   $XDG_DATA_HOME/EarPurifier or ~/.local/share/EarPurifier
    Creates the directory if it does not already exist.
    """
    current_os = get_current_os()
    if current_os == "windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "EarPurifier")
    elif current_os == "macos":
        path = os.path.expanduser("~/Library/Application Support/EarPurifier")
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
        if not xdg_data or not os.path.isabs(xdg_data):
            xdg_data = os.path.expanduser("~/.local/share")
        path = os.path.join(xdg_data, "EarPurifier")

    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        logger.warning(f"Could not create app data directory at {path}: {e}")
    return path


def get_default_output_folder() -> str:
    """
    Returns a safe, visible default output directory:
    - macOS & Linux: ~/Desktop/EarPurifier_Output
    - Windows (frozen): <exe_dir>/output if writable, else ~/Desktop/EarPurifier_Output
    - Windows (source): ~/Desktop/EarPurifier_Output
    Creates the directory if it does not already exist.
    """
    current_os = get_current_os()

    if current_os == "windows" and getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        out = os.path.join(exe_dir, "output")
        try:
            os.makedirs(out, exist_ok=True)
            # Test writability (e.g. if installed in Program Files, output might not be writable)
            test_file = os.path.join(out, ".ep_write_test")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("write_test")
            os.remove(test_file)
            return out
        except Exception as e:
            logger.debug(f"Exe output folder {out} not writable ({e}), falling back to Desktop.")

    desktop_out = os.path.join(os.path.expanduser("~"), "Desktop", "EarPurifier_Output")
    try:
        os.makedirs(desktop_out, exist_ok=True)
        return desktop_out
    except Exception as e:
        logger.warning(f"Could not create default output folder at {desktop_out}: {e}")
        # Fallback to app data output directory
        fallback_out = os.path.join(get_app_data_dir(), "output")
        try:
            os.makedirs(fallback_out, exist_ok=True)
            return fallback_out
        except Exception:
            return desktop_out


def reveal_in_file_manager(target_path: str) -> None:
    """
    Reveals the file or folder in the platform's native file browser:
    - Windows: explorer.exe /select, <path>
    - macOS:   open -R <path>
    - Linux:   xdg-open <parent_dir> or QDesktopServices fallback
    Spawns asynchronously via Popen to prevent UI event loop freezes.
    """
    if not target_path or not os.path.exists(target_path):
        return

    norm_path = os.path.normpath(target_path)
    current_os = get_current_os()

    if current_os == "windows":
        try:
            # Note: explorer.exe /select, <path> requires commas or raw quotes
            subprocess.Popen(["explorer.exe", f"/select,{norm_path}"])
        except Exception:
            try:
                os.startfile(os.path.dirname(norm_path) if os.path.isfile(norm_path) else norm_path)
            except Exception as e:
                logger.error(f"Failed to reveal in Windows explorer: {e}")
    elif current_os == "macos":
        try:
            subprocess.Popen(["open", "-R", norm_path])
        except Exception:
            parent_dir = os.path.dirname(norm_path) if os.path.isfile(norm_path) else norm_path
            QDesktopServices.openUrl(QUrl.fromLocalFile(parent_dir))
    else:
        # Linux
        parent_dir = os.path.dirname(norm_path) if os.path.isfile(norm_path) else norm_path
        try:
            subprocess.Popen(["xdg-open", parent_dir])
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(parent_dir))


def open_directory(dir_path: str) -> None:
    """
    Cross-platform folder opening in default file manager.
    """
    if not dir_path or not os.path.exists(dir_path):
        return
    norm_path = os.path.normpath(dir_path)
    if os.path.isfile(norm_path):
        norm_path = os.path.dirname(norm_path)
    QDesktopServices.openUrl(QUrl.fromLocalFile(norm_path))


def get_subprocess_spawn_kwargs(is_async: bool = False) -> dict:
    """
    Returns platform-safe subprocess kwargs:
    - Windows: CREATE_NO_WINDOW flag
    - POSIX: start_new_session=True (detaches child into new process group so it can be terminated safely)
    """
    kwargs = {}
    if sys.platform == "win32":
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
    else:
        kwargs["start_new_session"] = True
    return kwargs


def get_clean_subprocess_env(extra_paths: Optional[list] = None) -> dict:
    """
    Builds a clean environment dictionary for spawning child processes:
    - Strips PyInstaller frozen application leaks (PYTHONHOME, PYTHONPATH, DYLD_*, LD_*)
      so external Python/Micromamba runtimes don't crash when loading libraries.
    - Prepend extra_paths, local bin_dir, and standard OS tool paths (Homebrew on macOS).
    """
    env = os.environ.copy()

    # Strip PyInstaller runtime leaks that corrupt child Python/Micromamba runtimes
    for var in (
        "PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "_MEIPASS2",
        "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "LD_LIBRARY_PATH"
    ):
        env.pop(var, None)

    path_entries = []
    if extra_paths:
        path_entries.extend(extra_paths)

    # Local EarPurifier bin directory (contains managed ffmpeg/ffprobe/micromamba)
    bin_dir = os.path.join(get_app_data_dir(), "bin")
    if bin_dir not in path_entries:
        path_entries.append(bin_dir)

    # macOS Homebrew and standard tool paths
    if sys.platform == "darwin":
        for hb in ("/opt/homebrew/bin", "/usr/local/bin"):
            if hb not in path_entries:
                path_entries.append(hb)
    elif sys.platform.startswith("linux"):
        user_bin = os.path.expanduser("~/.local/bin")
        if user_bin not in path_entries:
            path_entries.append(user_bin)

    existing_path = env.get("PATH", "")
    if existing_path:
        path_entries.append(existing_path)

    env["PATH"] = os.pathsep.join(path_entries)
    return env
