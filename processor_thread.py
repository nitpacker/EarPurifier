import os
import time
import logging
from PySide6.QtCore import QThread, Signal
try:
    from .queue_manager import QueueManager
    from .media_engine import extract_audio, pad_or_trim_audio, remux_video, get_duration
    from .kaggle_bridge import KaggleBridge
except ImportError:
    from queue_manager import QueueManager
    from media_engine import extract_audio, pad_or_trim_audio, remux_video, get_duration
    from kaggle_bridge import KaggleBridge

logger = logging.getLogger(__name__)

class JobProcessor(QThread):
    progress_update = Signal(str, str) # job_id, message
    status_update = Signal(str, str) # job_id, new_status
    finished_job = Signal(str) # job_id
    error_job = Signal(str, str) # job_id, error_message

    def __init__(self, queue_manager: QueueManager, username: str, api_key: str, parent=None):
        super().__init__(parent)
        self.queue_manager = queue_manager
        self.username = username
        self.api_key = api_key
        self.kaggle_bridge = None
        self.running = True

    def run(self):
        try:
            try:
                from .kaggle_bridge import KaggleBridge
            except ImportError:
                from kaggle_bridge import KaggleBridge
            self.kaggle_bridge = KaggleBridge(self.username, self.api_key)
        except Exception as e:
            logger.error(f"Failed to initialize KaggleBridge: {e}")
            return
            
        while self.running:
            # Re-evaluate state
            jobs = self.queue_manager.get_all_jobs()
            active_cloud = self.queue_manager.has_active_cloud_job()
            
            # Find a job to resume or start
            job_to_process = None
            for jid, job in jobs.items():
                if job["status"] in ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "DOWNLOADING", "REMUXING"] and job.get("mode", "Cloud (Kaggle)") == "Cloud (Kaggle)":
                    job_to_process = (jid, job)
                    break
            
            if not job_to_process and not active_cloud:
                jid = self.queue_manager.get_next_pending_job()
                if jid:
                    job_to_process = (jid, jobs[jid])
                    
            if not job_to_process:
                for _ in range(20):
                    if not self.running:
                        break
                    time.sleep(0.1)
                continue
                
            job_id, job = job_to_process
            try:
                self.process_job(job_id, job)
            except Exception as e:
                logger.exception(f"Error processing job {job_id}")
                self.queue_manager.update_job(job_id, {"status": "ERROR"})
                self.error_job.emit(job_id, str(e))
                self.status_update.emit(job_id, "ERROR")

    def stop(self):
        self.running = False

    def _update_status(self, job_id, status):
        self.queue_manager.update_job(job_id, {"status": status})
        self.status_update.emit(job_id, status)
        
    def _log(self, job_id, msg):
        logger.info(f"[{job_id}] {msg}")
        self.progress_update.emit(job_id, msg)

    def _handle_abort(self, job_id: str, kernel_id: str, temp_dir: str):
        self._log(job_id, "Aborting: Cleaning up local temporary files and cancelling Kaggle kernel...")
        # 1. Cancel/delete Kaggle kernel
        if kernel_id:
            try:
                self.kaggle_bridge.cancel_kernel(kernel_id)
            except Exception as e:
                logger.warning(f"Failed to cancel Kaggle kernel: {e}")

        # 2. Flush Kaggle buffer dataset
        try:
            empty_dir = os.path.join(self.queue_manager.app_data_dir, "empty_buffer")
            self.kaggle_bridge.flush_buffer_dataset(empty_dir)
        except Exception as e:
            logger.warning(f"Failed to clear Kaggle buffer on abort: {e}")

        # 3. Clean up local temp files
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Failed to remove temp dir on abort: {e}")

        self._log(job_id, "Job aborted and all resources cleaned up successfully.")

    def process_job(self, job_id: str, job: dict):
        video_path = job["original_video"]
        status = job["status"]
        temp_dir = os.path.join(self.queue_manager.app_data_dir, "temp", job_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        if job.get("duration", 0.0) == 0.0:
            try:
                duration = get_duration(video_path)
                self.queue_manager.update_job(job_id, {"duration": duration})
                job["duration"] = duration
            except Exception:
                pass
        
        flac_path = job.get("flac_audio")
        if not flac_path:
            flac_path = os.path.join(temp_dir, "audio.flac")
            
        clean_wav = job.get("clean_wav")
        if not clean_wav:
            clean_wav = os.path.join(temp_dir, "clean_vocals.wav")

        kernel_id = job.get("kaggle_kernel_id")
        
        # 1. EXTRACTING
        if status in ["PENDING", "EXTRACTING"]:
            self._update_status(job_id, "EXTRACTING")
            self._log(job_id, "Extracting lossless FLAC...")
            extract_audio(video_path, flac_path)
            self.queue_manager.update_job(job_id, {"flac_audio": flac_path})
            status = "UPLOADING"
            
        # 2. UPLOADING
        if status == "UPLOADING":
            self._update_status(job_id, "UPLOADING")
            self._log(job_id, "Pushing audio to Kaggle dataset...")
            
            upload_success = False
            for up_attempt in range(5):
                if not self.running:
                    return
                try:
                    self.kaggle_bridge.push_audio(flac_path, os.path.join(temp_dir, "dataset_push"))
                    upload_success = True
                    break
                except Exception as e:
                    self._log(job_id, f"Upload interrupted (attempt {up_attempt+1}/5). Retrying...")
                    time.sleep(3)
            
            if not upload_success:
                raise Exception("Failed to upload audio to Kaggle after 5 attempts.")
            
            self._log(job_id, "Dispatching Kaggle worker kernel...")
            worker_dir = os.path.join(os.path.dirname(__file__), "worker")
            
            # Use the model specifically captured when this job was queued
            model_selection = job.get("model", "")
            if "RoFormer" in model_selection:
                c_model = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
            elif "MDX23C" in model_selection:
                c_model = "MDX23C-8KFFT-InstVoc_HQ.ckpt"
            else:
                c_model = "Kim_Vocal_2.onnx"
                
            worker_path = os.path.join(worker_dir, "worker.py")
            with open(worker_path, "r", encoding="utf-8") as f:
                worker_code = f.read()
                
            import re
            worker_code = re.sub(r'separator\.load_model\(model_filename="[^"]+"\)', f'separator.load_model(model_filename="{c_model}")', worker_code)
            
            with open(worker_path, "w", encoding="utf-8") as f:
                f.write(worker_code)
                
            dispatch_success = False
            for disp_attempt in range(5):
                if not self.running:
                    return
                try:
                    kernel_id = self.kaggle_bridge.push_kernel(worker_dir, f"earpurifier-worker-{job_id[:8]}")
                    dispatch_success = True
                    break
                except Exception as e:
                    self._log(job_id, f"Dispatch interrupted (attempt {disp_attempt+1}/5). Retrying...")
                    time.sleep(3)
                    
            if not dispatch_success:
                raise Exception("Failed to dispatch worker kernel after 5 attempts.")
                
            self.queue_manager.update_job(job_id, {"kaggle_kernel_id": kernel_id})
            status = "PROCESSING_CLOUD"
            
        # 3. PROCESSING_CLOUD
        if status == "PROCESSING_CLOUD":
            self._update_status(job_id, "PROCESSING_CLOUD")
            self._log(job_id, "Waiting for Kaggle GPU processing...")
            
            retries = 0
            while self.running:
                # Check for abort
                if self.queue_manager.get_job(job_id).get("status") == "ABORTED":
                    self._handle_abort(job_id, kernel_id, temp_dir)
                    return

                try:
                    k_status = self.kaggle_bridge.poll_status(kernel_id)
                    if k_status == "COMPLETE":
                        break
                    elif k_status == "ERROR":
                        raise Exception("Kaggle Kernel failed or was cancelled.")
                    
                    self._log(job_id, f"Kaggle Status: {k_status} (Polling...)")
                    # Sleep in small increments to react promptly to user abort
                    for _ in range(30):
                        if not self.running or self.queue_manager.get_job(job_id).get("status") == "ABORTED":
                            break
                        time.sleep(1)
                    if self.queue_manager.get_job(job_id).get("status") == "ABORTED":
                        self._handle_abort(job_id, kernel_id, temp_dir)
                        return

                    retries = 0 # reset retries on success
                except Exception as e:
                    if "Kernel failed" in str(e):
                        raise
                    retries += 1
                    if retries > 5:
                        self._update_status(job_id, "ERROR")
                        raise Exception("Network retries exhausted while polling Kaggle.")
                    for _ in range(60):
                        if not self.running or self.queue_manager.get_job(job_id).get("status") == "ABORTED":
                            break
                        time.sleep(1)
                    if self.queue_manager.get_job(job_id).get("status") == "ABORTED":
                        self._handle_abort(job_id, kernel_id, temp_dir)
                        return
                    
            status = "DOWNLOADING"
            
        # 4. DOWNLOADING
        if status == "DOWNLOADING":
            self._update_status(job_id, "DOWNLOADING")
            self._log(job_id, "Downloading clean audio from Kaggle...")
            
            # Robust retry loop for downloading in case Kaggle API drops connection
            download_success = False
            last_dl_error = None
            for dl_attempt in range(5):
                if not self.running:
                    return
                try:
                    self.kaggle_bridge.download_output(kernel_id, temp_dir)
                    download_success = True
                    break
                except Exception as e:
                    last_dl_error = e
                    self._log(job_id, f"Download interrupted (attempt {dl_attempt+1}/5). Retrying...")
                    time.sleep(3)
                    
            if not download_success:
                raise Exception(f"Failed to download output after 5 attempts: {last_dl_error}")
                
            self.queue_manager.update_job(job_id, {"clean_wav": clean_wav})
            status = "REMUXING"
            
        # 5. REMUXING
        if status == "REMUXING":
            self._update_status(job_id, "REMUXING")
            self._log(job_id, "Padding/Trimming audio and Remuxing video...")
            
            orig_duration = job.get("duration", 0.0)
            # Make sure clean_wav exists (sometimes it's downloaded as clean_vocals.wav depending on worker)
            downloaded_wav = os.path.join(temp_dir, "clean_vocals.wav")
            if not os.path.exists(downloaded_wav):
                # Check what was downloaded
                dl_files = os.listdir(temp_dir)
                raise Exception(f"Expected clean_vocals.wav not found. Files in temp: {dl_files}")
                
            padded_wav = os.path.join(temp_dir, "clean_padded.wav")
            pad_or_trim_audio(downloaded_wav, orig_duration, padded_wav)
            
            # Output file
            try:
                from .config_manager import ConfigManager
            except ImportError:
                from config_manager import ConfigManager
            cfg = ConfigManager()
            output_folder = cfg.get_output_folder(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            
            try:
                os.makedirs(output_folder, exist_ok=True)
            except Exception:
                pass # If it fails (e.g. Defender), ffmpeg might fail later, but we tried
                
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            out_video = os.path.join(output_folder, f"{base_name}_purified.mp4")
            
            remux_video(video_path, padded_wav, out_video)
            self.queue_manager.update_job(job_id, {"output_video": out_video})
            
            # Housekeeping / Cleanup (Points 3, 12)
            try:
                import shutil
                shutil.rmtree(temp_dir)
                self._log(job_id, "Cleaned up local temporary files.")
                
                # Clear Kaggle dataset buffer
                empty_dir = os.path.join(self.queue_manager.app_data_dir, "empty_buffer")
                self.kaggle_bridge.flush_buffer_dataset(empty_dir)
                self._log(job_id, "Cleared Kaggle buffer dataset.")
            except Exception as e:
                logger.warning(f"Failed to perform cleanup: {e}")
                
            status = "COMPLETED"
            
        if status == "COMPLETED":
            self._update_status(job_id, "COMPLETED")
            self._log(job_id, "Job finished successfully!")
            self.finished_job.emit(job_id)
