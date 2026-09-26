import os
import sys
import time
import subprocess
import logging
import re
import shutil
from PySide6.QtCore import QThread, Signal
try:
    from .queue_manager import QueueManager
    from .media_engine import extract_audio, pad_or_trim_audio, remux_video, get_duration
    from .config_manager import ConfigManager
    from .dependency_manager import DependencyManager
except ImportError:
    from queue_manager import QueueManager
    from media_engine import extract_audio, pad_or_trim_audio, remux_video, get_duration
    from config_manager import ConfigManager
    from dependency_manager import DependencyManager

logger = logging.getLogger(__name__)

class LocalJobProcessor(QThread):
    progress_update = Signal(str, str) # job_id, message
    status_update = Signal(str, str) # job_id, new_status
    finished_job = Signal(str) # job_id
    error_job = Signal(str, str) # job_id, error_message

    def __init__(self, queue_manager: QueueManager, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.queue_manager = queue_manager
        self.config = config
        self.running = True

    def run(self):
        while self.running:
            job_id = self.queue_manager.get_next_pending_job(mode="Local (GPU)")
            if job_id:
                job = self.queue_manager.get_job(job_id)
                if job.get("status") == "ABORTED":
                    continue
                try:
                    self.process_local_job(job_id, job)
                except Exception as e:
                    logger.exception(f"Error processing local job {job_id}")
                    self._update_status(job_id, "ERROR")
                    self.error_job.emit(job_id, str(e))
            else:
                for _ in range(20):
                    if not self.running:
                        break
                    time.sleep(0.1)

    def _update_status(self, job_id, status):
        self.queue_manager.update_job(job_id, {"status": status})
        self.status_update.emit(job_id, status)

    def _log(self, job_id, message):
        logger.info(f"[{job_id}] {message}")
        progress = self.queue_manager.get_job(job_id).get("progress", 0)
        self.progress_update.emit(job_id, message)

    def process_local_job(self, job_id, job):
        if not DependencyManager.has_local_engine():
            raise Exception("Local Engine is not installed.")

        temp_dir = os.path.join(self.config.appdata_dir, "temp", job_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            video_path = job["original_video"]
            
            if job.get("duration", 0.0) == 0.0:
                try:
                    duration = get_duration(video_path)
                    self.queue_manager.update_job(job_id, {"duration": duration})
                    job["duration"] = duration
                except Exception:
                    pass
            
            self._update_status(job_id, "EXTRACTING")
            self._log(job_id, "Extracting lossless FLAC...")
            
            flac_path = os.path.join(temp_dir, "audio.flac")
            extract_audio(video_path, flac_path)
            orig_duration = job.get("duration", 0.0)
            
            self.queue_manager.update_job(job_id, {"flac_audio": flac_path})
            
            # Local AI Processing
            self._update_status(job_id, "PROCESSING_LOCAL")
            self._log(job_id, "Running Local AI Engine...")
            
            # Map selected model from the specific job
            model_selection = job.get("model", "")
            if "RoFormer" in model_selection:
                model_name = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
                subfolder = "RoFormer"
            elif "MDX23C" in model_selection:
                model_name = "MDX23C-8KFFT-InstVoc_HQ.ckpt"
                subfolder = "MDX23C"
            else:
                model_name = "Kim_Vocal_2.onnx"
                subfolder = "Kim_Vocal_2"
                
            models_dir = os.path.join(self.config.appdata_dir, "models", subfolder)
            os.makedirs(models_dir, exist_ok=True)
            
            engine_exe = DependencyManager.get_engine_separator_exe()
            cmd = [
                engine_exe, flac_path,
                "-m", model_name,
                "--model_file_dir", models_dir,
                "--output_dir", temp_dir,
                "--output_format", "WAV",
                "--log_level", "INFO"
            ]
            
            self._log(job_id, f"Model {model_name} initialized. Processing audio...")
            
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True, "bufsize": 1}
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
                
            env = os.environ.copy()
            try:
                from .dependency_manager import DependencyManager
            except ImportError:
                from dependency_manager import DependencyManager
            env_dir = DependencyManager.get_env_dir()
            env["PATH"] = f"{env_dir};{env_dir}\\Library\\mingw-w64\\bin;{env_dir}\\Library\\usr\\bin;{env_dir}\\Library\\bin;{env_dir}\\Scripts;{env.get('PATH', '')}"
                
            process = subprocess.Popen(cmd, env=env, **kwargs)
            
            percent_pattern = re.compile(r'(\d{1,3})%')
            last_pct = -1
            
            captured_stderr = []
            while True:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    captured_stderr.append(line)
                    match = percent_pattern.search(line)
                    if match:
                        try:
                            pct = int(match.group(1))
                            if pct != last_pct:
                                self._log(job_id, f"Processing audio... {pct}%")
                                last_pct = pct
                        except:
                            pass
                            
            stdout_out, _ = process.communicate()
            if process.returncode != 0:
                full_stderr = "".join(captured_stderr)
                if "DLL load failed" in full_stderr:
                    error_msg = (
                        "Missing Microsoft Visual C++ Redistributable.\n"
                        "Please download and install it from Microsoft:\n"
                        "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                        "(Restart the app after installing)"
                    )
                    raise Exception(error_msg)
                raise Exception(f"AI Engine failed:\n{full_stderr.strip()}\n{stdout_out}")
            
            # Identify vocal file
            clean_wav = None
            for f in os.listdir(temp_dir):
                if f.endswith(".wav") and "(Vocals)" in f:
                    clean_wav = os.path.join(temp_dir, f)
                    break
                    
            if not clean_wav or not os.path.exists(clean_wav):
                raise Exception(f"Expected vocal track not found in output directory.\n{res.stdout}\n{res.stderr}")
                
            self._update_status(job_id, "REMUXING")
            self._log(job_id, "Padding/Trimming audio and Remuxing video...")
            
            padded_wav = os.path.join(temp_dir, "clean_padded.wav")
            pad_or_trim_audio(clean_wav, orig_duration, padded_wav)
            
            # Setup output
            output_folder = self.config.get_output_folder(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            
            try:
                os.makedirs(output_folder, exist_ok=True)
            except Exception:
                pass # We try our best, fallback to letting ffmpeg fail if blocked
                
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            out_video = os.path.join(output_folder, f"{base_name}_purified.mp4")
            
            remux_video(video_path, padded_wav, out_video)
            self.queue_manager.update_job(job_id, {"output_video": out_video})
            
            self._update_status(job_id, "COMPLETED")
            self._log(job_id, "Job finished successfully!")
            self.finished_job.emit(job_id)

        finally:
            # Always cleanup the temp directory for this job to prevent disk bloat
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.info(f"[{job_id}] Cleaned up temporary files.")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir: {e}")

    def stop(self):
        self.running = False
