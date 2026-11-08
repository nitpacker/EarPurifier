import os
import sys
import shutil
import hashlib
import platform
import urllib.request
import zipfile
import tarfile
import subprocess
import logging
from typing import Optional

from PySide6.QtCore import QThread, Signal
from system_utils import get_app_data_dir, get_subprocess_spawn_kwargs

logger = logging.getLogger(__name__)


class DependencyManager:
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

        # Backward compatibility / fallback: check site-packages
        env_dir = DependencyManager.get_env_dir()
        candidate_site_packages = []
        if sys.platform == "win32":
            candidate_site_packages.append(os.path.join(env_dir, "Lib", "site-packages"))
        else:
            lib_dir = os.path.join(env_dir, "lib")
            if os.path.isdir(lib_dir):
                for entry in os.listdir(lib_dir):
                    if entry.startswith("python"):
                        candidate_site_packages.append(os.path.join(lib_dir, entry, "site-packages"))

        for sp in candidate_site_packages:
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
        """Detects whether an NVIDIA GPU with CUDA driver support is present on the host."""
        if sys.platform == "darwin":
            return False

        if sys.platform == "win32":
            sys_root = os.environ.get("SystemRoot", "C:\\Windows")
            if os.path.exists(os.path.join(sys_root, "System32", "nvcuda.dll")):
                return True
        elif sys.platform.startswith("linux"):
            cuda_lib_paths = [
                "/usr/lib/x86_64-linux-gnu/libcuda.so",
                "/usr/lib/aarch64-linux-gnu/libcuda.so",
                "/usr/lib64/libcuda.so",
                "/usr/lib/libcuda.so",
                "/usr/local/cuda",
            ]
            if any(os.path.exists(p) for p in cuda_lib_paths):
                return True

        smi = shutil.which("nvidia-smi")
        if smi:
            try:
                kwargs = get_subprocess_spawn_kwargs()
                res = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=3, **kwargs)
                return res.returncode == 0 and "GPU" in res.stdout
            except Exception:
                pass
        return False


class FFmpegDownloader(QThread):
    progress_update = Signal(int)
    status_update = Signal(str)
    finished_download = Signal(bool, str)

    def _download_file(self, url: str, dest_path: str, progress_range: tuple = (0, 100)):
        import requests
        headers = {'User-Agent': 'Mozilla/5.0'}
        with requests.get(url, headers=headers, stream=True, timeout=(15, 60)) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get('Content-Length', 0))
            block_size = 65536
            downloaded = 0
            last_percent = -1
            p_start, p_end = progress_range

            with open(dest_path, 'wb') as out_file:
                for chunk in resp.iter_content(chunk_size=block_size):
                    if self.isInterruptionRequested():
                        raise InterruptedError("Download cancelled")
                    if chunk:
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = p_start + int((downloaded / total_size) * (p_end - p_start))
                            if pct > last_percent:
                                self.progress_update.emit(pct)
                                last_percent = pct

    def run(self):
        try:
            bin_dir = DependencyManager.get_bin_dir()
            current_os = sys.platform

            if current_os == "win32":
                self.status_update.emit("Downloading FFmpeg (Windows)...")
                url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
                archive_path = os.path.join(DependencyManager.get_appdata_dir(), "ffmpeg.zip")
                self._download_file(url, archive_path)

                self.status_update.emit("Extracting FFmpeg binaries...")
                with zipfile.ZipFile(archive_path, 'r') as z:
                    for info in z.infolist():
                        if info.filename.endswith('ffmpeg.exe') or info.filename.endswith('ffprobe.exe'):
                            info.filename = os.path.basename(info.filename)
                            z.extract(info, bin_dir)
                try:
                    os.remove(archive_path)
                except Exception:
                    pass

            elif current_os == "darwin":
                # macOS: Native static Mach-O binaries from descriptinc/ffmpeg-ffprobe-static (b6.1.2-rc.1)
                self.status_update.emit("Downloading FFmpeg (macOS)...")
                is_arm = platform.machine().lower() in ("arm64", "aarch64")
                arch_tag = "arm64" if is_arm else "x64"
                base_url = "https://github.com/descriptinc/ffmpeg-ffprobe-static/releases/download/b6.1.2-rc.1"
                ffmpeg_url = f"{base_url}/ffmpeg-darwin-{arch_tag}"
                ffprobe_url = f"{base_url}/ffprobe-darwin-{arch_tag}"

                ffmpeg_dest = os.path.join(bin_dir, "ffmpeg")
                ffprobe_dest = os.path.join(bin_dir, "ffprobe")

                self._download_file(ffmpeg_url, ffmpeg_dest, progress_range=(0, 50))
                self.status_update.emit("Downloading FFprobe (macOS)...")
                self._download_file(ffprobe_url, ffprobe_dest, progress_range=(50, 95))

                for binary_path in (ffmpeg_dest, ffprobe_dest):
                    if os.path.exists(binary_path):
                        try:
                            os.chmod(binary_path, 0o755)
                        except Exception:
                            pass

            else:
                # Linux: BtbN tar.xz (supports x86_64 and aarch64/ARM64)
                self.status_update.emit("Downloading FFmpeg (Linux)...")
                linux_arch = "linuxarm64" if platform.machine().lower() in ("arm64", "aarch64") else "linux64"
                url = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-{linux_arch}-gpl.tar.xz"
                archive_path = os.path.join(DependencyManager.get_appdata_dir(), "ffmpeg.tar.xz")
                self._download_file(url, archive_path)

                self.status_update.emit("Extracting FFmpeg binaries...")
                with tarfile.open(archive_path, "r:xz") as tar:
                    for member in tar.getmembers():
                        base = os.path.basename(member.name)
                        if base in ("ffmpeg", "ffprobe") and member.isfile():
                            member.name = base
                            tar.extract(member, bin_dir)
                try:
                    os.remove(archive_path)
                except Exception:
                    pass

                for binary in ["ffmpeg", "ffprobe"]:
                    p = os.path.join(bin_dir, binary)
                    if os.path.exists(p):
                        try:
                            os.chmod(p, 0o755)
                        except Exception:
                            pass

            self.status_update.emit("FFmpeg installed successfully.")
            self.progress_update.emit(100)
            self.finished_download.emit(True, "Success")

        except Exception as e:
            self.finished_download.emit(False, str(e))

    def stop(self):
        self.requestInterruption()
        if self.isRunning():
            try:
                self.terminate()
                self.wait(100)
            except Exception:
                pass


class EngineDownloader(QThread):
    progress_update = Signal(int)
    status_update = Signal(str)
    finished_download = Signal(bool, str)

    def run(self):
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

                tar_path = os.path.join(DependencyManager.get_appdata_dir(), "micromamba.tar.bz2")
                req = urllib.request.Request(mamba_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response, open(tar_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)

                self.status_update.emit("Extracting Micromamba...")
                with tarfile.open(tar_path, "r:bz2") as tar:
                    for member in tar.getmembers():
                        base = os.path.basename(member.name)
                        if base in ("micromamba.exe", "micromamba"):
                            member.name = mamba_name
                            tar.extract(member, bin_dir)
                try:
                    os.remove(tar_path)
                except Exception:
                    pass

                if sys.platform != "win32" and os.path.exists(mamba_exe):
                    try:
                        os.chmod(mamba_exe, 0o755)
                    except Exception:
                        pass

            # Ensure micromamba is executable on POSIX before invocation
            if sys.platform != "win32" and os.path.exists(mamba_exe):
                try:
                    os.chmod(mamba_exe, 0o755)
                except Exception:
                    pass

            # 2. Create Environment
            self.status_update.emit("Building isolated Python environment... (Step 1/3)")
            self.progress_update.emit(20)

            kwargs = {"capture_output": True, "text": True}
            kwargs.update(get_subprocess_spawn_kwargs())
            from system_utils import get_clean_subprocess_env
            kwargs["env"] = get_clean_subprocess_env([bin_dir, os.path.join(env_dir, "bin")])

            python_exe = DependencyManager.get_engine_python()
            pip_exe = os.path.join(env_dir, "Scripts", "pip.exe") if sys.platform == "win32" else os.path.join(env_dir, "bin", "pip")

            expected_py_ver = "3.10" if sys.platform != "win32" else "3.11"
            rebuild_env = not os.path.exists(env_dir) or not os.path.exists(python_exe)
            if not rebuild_env:
                try:
                    ver_check = subprocess.run(
                        [python_exe, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        **get_subprocess_spawn_kwargs()
                    )
                    if ver_check.returncode != 0 or ver_check.stdout.strip() != expected_py_ver:
                        rebuild_env = True
                except Exception:
                    rebuild_env = True

            if rebuild_env:
                if os.path.exists(env_dir):
                    try:
                        shutil.rmtree(env_dir, ignore_errors=True)
                    except Exception:
                        pass
                py_spec = f"python={expected_py_ver}"
                res = subprocess.run([mamba_exe, "create", "-y", "-p", env_dir, py_spec, "pip", "-c", "conda-forge"], **kwargs)
                if res.returncode != 0:
                    err_msg = res.stderr.strip() or res.stdout.strip() or "Unknown micromamba error"
                    raise RuntimeError(f"Environment creation failed: {err_msg}")

            if sys.platform != "win32" and os.path.exists(python_exe):
                try:
                    os.chmod(python_exe, 0o755)
                except Exception:
                    pass

            pip_base = [python_exe, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", "--prefer-binary", "--default-timeout=120"]

            # 3. Install PyTorch (Adaptive Hardware Acceleration)
            installed_gpu = False
            if sys.platform == "darwin":
                self.status_update.emit("Installing PyTorch (Apple Silicon Metal / CPU)... (Step 2/3)")
                self.progress_update.emit(50)
                res = subprocess.run(pip_base + ["torch"], **kwargs)
                if res.returncode != 0:
                    err_msg = res.stderr.strip() or res.stdout.strip() or "Unknown pip error"
                    raise RuntimeError(f"PyTorch install failed: {err_msg}")
            else:
                has_gpu = DependencyManager.has_nvidia_gpu()
                if has_gpu:
                    self.status_update.emit("NVIDIA GPU detected. Installing PyTorch CUDA acceleration... (Step 2/3)")
                    self.progress_update.emit(45)
                    res = subprocess.run(pip_base + ["torch", "--index-url", "https://download.pytorch.org/whl/cu121"], **kwargs)
                    if res.returncode == 0:
                        installed_gpu = True
                    else:
                        logger.warning(f"CUDA PyTorch install failed ({res.stderr}). Falling back to CPU.")

                if not installed_gpu:
                    self.status_update.emit("Installing PyTorch CPU engine... (Step 2/3)")
                    self.progress_update.emit(50)
                    res = subprocess.run(pip_base + ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"], **kwargs)
                    if res.returncode != 0:
                        err_msg = res.stderr.strip() or res.stdout.strip() or "Unknown pip error"
                        raise RuntimeError(f"PyTorch install failed: {err_msg}")

            # 4. Install Audio Separator
            self.status_update.emit("Installing Audio Separator... (Step 3/3)")
            self.progress_update.emit(85)
            if sys.platform == "darwin":
                sep_pkg = "audio-separator[cpu]"
            else:
                sep_pkg = "audio-separator[gpu]" if installed_gpu else "audio-separator[cpu]"
            res = subprocess.run(pip_base + [sep_pkg], **kwargs)
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

            # 5. Write installation verification marker
            marker_file = os.path.join(env_dir, ".engine_installed")
            with open(marker_file, "w", encoding="utf-8") as f:
                f.write("INSTALLED\n")

            if sys.platform == "darwin":
                engine_type = "Apple Silicon Metal / CPU"
            else:
                engine_type = "GPU Accelerated" if installed_gpu else "CPU"
            self.status_update.emit(f"Local AI Engine ({engine_type}) installed successfully.")
            self.progress_update.emit(100)
            self.finished_download.emit(True, "Success")

        except Exception as e:
            self.finished_download.emit(False, str(e))

    def stop(self):
        self.requestInterruption()
        if self.isRunning():
            try:
                self.terminate()
                self.wait(100)
            except Exception:
                pass


class ModelDownloader(QThread):
    progress_update = Signal(int)
    status_update = Signal(str)
    finished_download = Signal(bool, str)

    def __init__(self, model_name: str, models_dir: str):
        super().__init__()
        self.model_name = model_name
        self.models_dir = models_dir
        self.process = None

    def stop(self):
        if getattr(self, 'process', None):
            try:
                from process_tracker import kill_process_tree
                kill_process_tree(self.process.pid)
                self.process.kill()
            except Exception:
                pass
        self.requestInterruption()
        if self.isRunning():
            try:
                self.terminate()
                self.wait(100)
            except Exception:
                pass

    def run(self):
        script_path = None
        try:
            self.status_update.emit("Downloading Model...")
            self.progress_update.emit(0)

            env_python = DependencyManager.get_engine_python()

            script_path = os.path.join(DependencyManager.get_env_dir(), "temp_download.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(f'''
import logging, sys
from audio_separator.separator import Separator
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
separator = Separator(model_file_dir={repr(self.models_dir)}, log_level=logging.INFO)
separator.load_model({repr(self.model_name)})
print("SUCCESS_DOWNLOAD")
''')

            # Direct stderr to stdout to form a single stream and prevent pipe buffer deadlocks
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True, "bufsize": 1}
            kwargs.update(get_subprocess_spawn_kwargs())

            from system_utils import get_clean_subprocess_env
            env_dir = DependencyManager.get_env_dir()
            if sys.platform == "win32":
                env = get_clean_subprocess_env([
                    env_dir,
                    os.path.join(env_dir, "Library", "mingw-w64", "bin"),
                    os.path.join(env_dir, "Library", "usr", "bin"),
                    os.path.join(env_dir, "Library", "bin"),
                    os.path.join(env_dir, "Scripts")
                ])
            else:
                env = get_clean_subprocess_env([os.path.join(env_dir, "bin")])

            self.process = subprocess.Popen([env_python, script_path], env=env, **kwargs)
            process = self.process
            try:
                from process_tracker import register_process, unregister_process
                register_process(process)
            except Exception:
                pass

            import re
            percent_pattern = re.compile(r'(\d{1,3})%')
            captured_output = []
            last_pct = -1

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    captured_output.append(line)
                    match = percent_pattern.search(line)
                    if match:
                        try:
                            pct = int(match.group(1))
                            if pct > last_pct:
                                self.progress_update.emit(pct)
                                self.status_update.emit(f"Downloading... {pct}%")
                                last_pct = pct
                        except Exception:
                            pass

            process.wait()
            try:
                from process_tracker import unregister_process
                unregister_process(process)
            except Exception:
                pass

            full_output = "".join(captured_output)
            if "SUCCESS_DOWNLOAD" in full_output:
                self.progress_update.emit(100)
                self.status_update.emit("Model downloaded successfully!")
                self.finished_download.emit(True, "Success")
            else:
                if "DLL load failed" in full_output:
                    if sys.platform == "win32":
                        error_msg = (
                            "Your Windows system is missing the Microsoft Visual C++ Redistributable, "
                            "which is required to run the AI engine locally.\n\n"
                            "Please download and install it from Microsoft:\n"
                            "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                            "(Restart the app after installing)"
                        )
                    else:
                        error_msg = f"Failed to load AI engine library:\n{full_output.strip()}"
                    raise RuntimeError(error_msg)
                else:
                    raise RuntimeError(f"Failed to download model:\n{full_output.strip()}")

        except Exception as e:
            self.finished_download.emit(False, str(e))
        finally:
            if script_path and os.path.exists(script_path):
                try:
                    os.remove(script_path)
                except Exception:
                    pass
