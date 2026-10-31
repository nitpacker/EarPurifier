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
    from .media_engine import extract_audio, pad_or_trim_audio, remux_media, get_duration, probe_container
    from .config_manager import ConfigManager
    from .dependency_manager import DependencyManager
except ImportError:
    from queue_manager import QueueManager
    from media_engine import extract_audio, pad_or_trim_audio, remux_media, get_duration, probe_container
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
        self.current_process = None

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
        self.progress_update.emit(job_id, message)

    def process_local_job(self, job_id, job):
        if not DependencyManager.has_local_engine():
            raise RuntimeError("Local Engine is not installed.")

        temp_dir = os.path.join(self.config.appdata_dir, "temp", job_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            media_path = job.get("original_media") or job.get("original_video")
            selected_audio_idx = job.get("selected_audio_stream", 0)
            probe_result = job.get("probe_result")
            if not probe_result:
                try:
                    probe_result = probe_container(media_path)
                except Exception:
                    probe_result = {}
            
            if job.get("duration", 0.0) == 0.0:
                try:
                    duration = get_duration(media_path)
                    if duration > 0.0:
                        self.queue_manager.update_job(job_id, {"duration": duration})
                        job["duration"] = duration
                except Exception as e:
                    logger.warning(f"Could not determine media duration: {e}")
            
            self._update_status(job_id, "EXTRACTING")
            self._log(job_id, "Extracting lossless FLAC...")
            
            flac_path = os.path.join(temp_dir, "audio.flac")
            extract_audio(media_path, flac_path, stream_index=selected_audio_idx)
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
            
            # Direct stderr into stdout to form a single stream and avoid pipe buffer deadlocks
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True, "bufsize": 1}
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW")
                
            env = os.environ.copy()
            env_dir = DependencyManager.get_env_dir()
            env["PATH"] = f"{env_dir};{env_dir}\\Library\\mingw-w64\\bin;{env_dir}\\Library\\usr\\bin;{env_dir}\\Library\\bin;{env_dir}\\Scripts;{env.get('PATH', '')}"
                
            self.current_process = subprocess.Popen(cmd, env=env, **kwargs)
            try:
                from .process_tracker import register_process, unregister_process
            except ImportError:
                from process_tracker import register_process, unregister_process
            register_process(self.current_process)
            process = self.current_process
            
            percent_pattern = re.compile(r'(\d{1,3})%')
            last_pct = -1
            captured_output = []
            
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
                                self._log(job_id, f"Processing audio... {pct}%")
                                last_pct = pct
                        except Exception:
                            pass
                            
            process.wait()
            self.current_process = None
            full_output = "".join(captured_output)

            if process.returncode != 0:
                if "DLL load failed" in full_output:
                    error_msg = (
                        "Missing Microsoft Visual C++ Redistributable.\n"
                        "Please download and install it from Microsoft:\n"
                        "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                        "(Restart the app after installing)"
                    )
                    raise RuntimeError(error_msg)
                raise RuntimeError(f"AI Engine failed (exit code {process.returncode}):\n{full_output.strip()}")
            
            # Identify vocal file with case-insensitive check
            clean_wav = None
            for f in os.listdir(temp_dir):
                if f.lower().endswith(".wav") and "(vocals)" in f.lower():
                    clean_wav = os.path.join(temp_dir, f)
                    break
                    
            if not clean_wav or not os.path.exists(clean_wav):
                files_found = os.listdir(temp_dir)
                raise RuntimeError(f"Expected vocal track not found in output directory.\nFiles present: {files_found}\nProcess logs:\n{full_output.strip()}")
                
            self._update_status(job_id, "REMUXING")
            self._log(job_id, "Padding/Trimming audio and Remuxing media...")
            
            padded_wav = os.path.join(temp_dir, "clean_padded.wav")
            pad_or_trim_audio(clean_wav, orig_duration, padded_wav)
            
            # Setup output
            output_folder = self.config.get_output_folder(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            
            try:
                os.makedirs(output_folder, exist_ok=True)
            except Exception:
                pass
                
            base_name, ext = os.path.splitext(os.path.basename(media_path))
            out_media = os.path.join(output_folder, f"{base_name}_purified{ext}")
            
            remux_media(media_path, padded_wav, out_media, probe_result, chosen_stream_idx=selected_audio_idx)
            self.queue_manager.update_job(job_id, {"output_media": out_media, "output_video": out_media})
            
            self._update_status(job_id, "COMPLETED")
            self._log(job_id, "Job finished successfully!")
            self.finished_job.emit(job_id)

        finally:
            if self.current_process is not None:
                try:
                    from process_tracker import unregister_process
                    unregister_process(self.current_process)
                except Exception:
                    pass
            self.current_process = None
            # Always cleanup the temp directory for this job to prevent disk bloat
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.info(f"[{job_id}] Cleaned up temporary files.")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir: {e}")

    def stop(self):
        self.running = False
        if self.current_process is not None:
            try:
                from process_tracker import kill_process_tree
                kill_process_tree(self.current_process.pid)
                self.current_process.kill()
            except Exception:
                pass
        self.requestInterruption()
        if self.isRunning():
            self.terminate()
            self.wait(100)
