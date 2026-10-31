import os
import sys
import shutil
import hashlib
import urllib.request
import zipfile
import tarfile
import subprocess
import logging
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

class DependencyManager:
    @staticmethod
    def get_appdata_dir() -> str:
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "EarPurifier")
        os.makedirs(base, exist_ok=True)
        return base

    @staticmethod
    def get_bin_dir() -> str:
        d = os.path.join(DependencyManager.get_appdata_dir(), "bin")
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def get_env_dir() -> str:
        return os.path.join(DependencyManager.get_appdata_dir(), "env")

    @staticmethod
    def get_executable(name: str) -> str:
        # 1. Check system PATH
        sys_path = shutil.which(name)
        if sys_path:
            return sys_path
        
        # 2. Check local bin directory
        ext = ".exe" if os.name == "nt" else ""
        local_path = os.path.join(DependencyManager.get_bin_dir(), name + ext)
        if os.path.exists(local_path):
            return local_path
            
        return None

    @staticmethod
    def has_ffmpeg() -> bool:
        return DependencyManager.get_executable("ffmpeg") is not None and DependencyManager.get_executable("ffprobe") is not None

    @staticmethod
    def has_local_engine() -> bool:
        ext = ".exe" if os.name == "nt" else ""
        python_path = os.path.join(DependencyManager.get_env_dir(), "python" + ext)
        if not os.path.exists(python_path):
            return False
            
        separator_exe = os.path.join(DependencyManager.get_env_dir(), "Scripts", "audio-separator" + ext)
        return os.path.exists(separator_exe)

    @staticmethod
    def has_nvidia_gpu() -> bool:
        """Detects whether an NVIDIA GPU with CUDA driver support is present on the host."""
        if os.name == "nt":
            sys_root = os.environ.get("SystemRoot", "C:\\Windows")
            if os.path.exists(os.path.join(sys_root, "System32", "nvcuda.dll")):
                return True
        smi = shutil.which("nvidia-smi")
        if smi:
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                res = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=3, creationflags=creationflags)
                return res.returncode == 0 and "GPU" in res.stdout
            except Exception:
                pass
        return False

    @staticmethod
    def get_engine_python() -> str:
        ext = ".exe" if os.name == "nt" else ""
        return os.path.join(DependencyManager.get_env_dir(), "python" + ext)
        
    @staticmethod
    def get_engine_separator_exe() -> str:
        ext = ".exe" if os.name == "nt" else ""
        return os.path.join(DependencyManager.get_env_dir(), "Scripts", "audio-separator" + ext)


class FFmpegDownloader(QThread):
    progress_update = Signal(int)
    status_update = Signal(str)
    finished_download = Signal(bool, str)

    def run(self):
        try:
            self.status_update.emit("Downloading FFmpeg...")
            zip_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
            zip_path = os.path.join(DependencyManager.get_appdata_dir(), "ffmpeg.zip")
            
            req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(zip_path, 'wb') as out_file:
                total_size = int(response.getheader('Content-Length', 0))
                block_size = 8192
                downloaded = 0
                last_percent = -1

                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    out_file.write(buffer)
                    downloaded += len(buffer)
                    
                    if total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        if percent > last_percent:
                            self.progress_update.emit(percent)
                            last_percent = percent

            self.status_update.emit("Extracting FFmpeg binaries...")
            bin_dir = DependencyManager.get_bin_dir()
            with zipfile.ZipFile(zip_path, 'r') as z:
                for info in z.infolist():
                    if info.filename.endswith('ffmpeg.exe') or info.filename.endswith('ffprobe.exe'):
                        info.filename = os.path.basename(info.filename)
                        z.extract(info, bin_dir)

            os.remove(zip_path)
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
            mamba_exe = os.path.join(bin_dir, "micromamba.exe")

            # 1. Download Micromamba if missing
            if not os.path.exists(mamba_exe):
                self.status_update.emit("Downloading Micromamba package manager...")
                mamba_url = "https://micro.mamba.pm/api/micromamba/win-64/latest"
                tar_path = os.path.join(DependencyManager.get_appdata_dir(), "micromamba.tar.bz2")
                
                req = urllib.request.Request(mamba_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response, open(tar_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)

                self.status_update.emit("Extracting Micromamba...")
                with tarfile.open(tar_path, "r:bz2") as tar:
                    for member in tar.getmembers():
                        if member.name.endswith("micromamba.exe"):
                            member.name = "micromamba.exe"
                            tar.extract(member, bin_dir)
                os.remove(tar_path)
            
            # 2. Create Environment
            self.status_update.emit("Building isolated Python environment (this may take a minute)...")
            self.progress_update.emit(20)
            
            kwargs = {"capture_output": True, "text": True, "check": True}
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")

            if not os.path.exists(env_dir):
                subprocess.run([mamba_exe, "create", "-y", "-p", env_dir, "python=3.11", "pip", "-c", "conda-forge"], **kwargs)

            pip_exe = os.path.join(env_dir, "Scripts", "pip.exe") if os.name == "nt" else os.path.join(env_dir, "bin", "pip")
            has_gpu = DependencyManager.has_nvidia_gpu()

            # 3. Install PyTorch (Adaptive Hardware Acceleration)
            installed_gpu = False
            if has_gpu:
                self.status_update.emit("NVIDIA GPU detected. Installing PyTorch CUDA acceleration...")
                self.progress_update.emit(45)
                res = subprocess.run([pip_exe, "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu121"], **kwargs)
                if res.returncode == 0:
                    installed_gpu = True
                else:
                    logger.warning(f"CUDA PyTorch install failed ({res.stderr}). Falling back to CPU.")

            if not installed_gpu:
                self.status_update.emit("Installing PyTorch CPU engine...")
                self.progress_update.emit(50)
                res = subprocess.run([pip_exe, "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu"], **kwargs)
                if res.returncode != 0:
                    raise RuntimeError(f"PyTorch install failed: {res.stderr}")

            # 4. Install Audio Separator
            self.status_update.emit("Installing Audio Separator...")
            self.progress_update.emit(85)
            sep_pkg = "audio-separator[gpu]" if installed_gpu else "audio-separator[cpu]"
            res = subprocess.run([pip_exe, "install", sep_pkg], **kwargs)
            if res.returncode != 0:
                raise RuntimeError(f"Audio Separator install failed: {res.stderr}")

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
        try:
            self.status_update.emit("Downloading Model...")
            self.progress_update.emit(0)
            
            env_python = DependencyManager.get_engine_python()
            
            script_path = os.path.join(DependencyManager.get_appdata_dir(), "temp_download.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(f'''
import logging, sys
from audio_separator.separator import Separator
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
separator = Separator(model_file_dir=r"{self.models_dir}", log_level=logging.INFO)
separator.load_model(r"{self.model_name}")
print("SUCCESS_DOWNLOAD")
''')

            # Direct stderr to stdout to form a single stream and prevent pipe buffer deadlocks
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True, "bufsize": 1}
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
                
            env = os.environ.copy()
            env_dir = DependencyManager.get_env_dir()
            env["PATH"] = f"{env_dir};{env_dir}\\Library\\mingw-w64\\bin;{env_dir}\\Library\\usr\\bin;{env_dir}\\Library\\bin;{env_dir}\\Scripts;{env.get('PATH', '')}"
                
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
                            if pct != last_pct:
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
            
            try:
                os.remove(script_path)
            except Exception:
                pass
                
            full_output = "".join(captured_output)
            if "SUCCESS_DOWNLOAD" in full_output:
                self.progress_update.emit(100)
                self.status_update.emit("Model downloaded successfully!")
                self.finished_download.emit(True, "Success")
            else:
                if "DLL load failed" in full_output:
                    error_msg = (
                        "Your Windows system is missing the Microsoft Visual C++ Redistributable, "
                        "which is required to run the AI engine locally.\n\n"
                        "Please download and install it from Microsoft:\n"
                        "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                        "(Restart the app after installing)"
                    )
                    raise RuntimeError(error_msg)
                else:
                    raise RuntimeError(f"Failed to download model:\n{full_output.strip()}")
                
        except Exception as e:
            self.finished_download.emit(False, str(e))
