import os
import json
import shutil
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class KaggleError(Exception):
    pass

class KaggleBridge:
    def __init__(self, username: str, api_key: str):
        self.username = username.strip().lower()
        self.dataset_name = "earpurifier-audio-buffer"
        self.dataset_id = f"{self.username}/{self.dataset_name}"
        self.assets_dataset_id = f"{self.username}/audio-separation-assets"
        
        # Inject API credentials to environment for kaggle API SDK
        os.environ["KAGGLE_USERNAME"] = self.username
        os.environ["KAGGLE_KEY"] = api_key.strip()
        
        # Initialize native Kaggle API client (NO CLI SUBPROCESS DEPENDENCY)
        from kaggle.api.kaggle_api_extended import KaggleApi
        self.api = KaggleApi()
        self.api.authenticate()

    def ensure_buffer_dataset(self, temp_dir: str):
        """Ensures the audio buffer dataset exists on Kaggle, creates it if not."""
        metadata = {
            "title": self.dataset_name,
            "id": self.dataset_id,
            "licenses": [{"name": "CC0-1.0"}]
        }
        with open(os.path.join(temp_dir, "dataset-metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            
        try:
            # Check if dataset exists via native API
            self.api.dataset_status(self.dataset_id)
            logger.info(f"Dataset {self.dataset_id} exists on Kaggle.")
        except Exception as e:
            logger.info(f"Dataset {self.dataset_id} not found ({e}), creating new one on Kaggle...")
            try:
                self.api.dataset_create_new(folder=temp_dir, dir_mode="zip")
                logger.info("Successfully created dataset on Kaggle.")
            except Exception as create_err:
                logger.warning(f"dataset_create_new note: {create_err}")

    def push_audio(self, audio_path: str, temp_dir: str):
        """Pushes an audio file to the Kaggle buffer dataset."""
        os.makedirs(temp_dir, exist_ok=True)
        # Clear temp dir except metadata
        for f in os.listdir(temp_dir):
            if f != "dataset-metadata.json":
                try:
                    os.remove(os.path.join(temp_dir, f))
                except Exception:
                    pass
                
        # Copy new audio
        shutil.copy(audio_path, temp_dir)
        
        # Ensure dataset exists
        self.ensure_buffer_dataset(temp_dir)
        
        logger.info(f"Pushing new version of {self.dataset_id}...")
        try:
            self.api.dataset_create_version(folder=temp_dir, version_notes="New audio job", dir_mode="zip")
        except Exception as e:
            logger.info(f"Dataset version push note: {e}")

        logger.info("Waiting 30s for Kaggle to process the dataset version...")
        time.sleep(30)

    def flush_buffer_dataset(self, empty_dir: str):
        """Flushes/clears the Kaggle buffer dataset on abort."""
        os.makedirs(empty_dir, exist_ok=True)
        self.ensure_buffer_dataset(empty_dir)
        try:
            self.api.dataset_create_version(folder=empty_dir, version_notes="Clear buffer on abort", dir_mode="zip")
        except Exception as e:
            logger.warning(f"Failed to clear Kaggle buffer on abort: {e}")
        
    def push_kernel(self, kernel_dir: str, kernel_name: str) -> str:
        """Pushes the worker kernel and returns the kernel ID."""
        kernel_id = f"{self.username}/{kernel_name}"
        
        metadata = {
          "id": kernel_id,
          "title": kernel_name,
          "code_file": "worker.py",
          "language": "python",
          "kernel_type": "script",
          "is_private": True,
          "enable_gpu": True,
          "enable_internet": True,
          "dataset_sources": [
            self.dataset_id,
            "verymuch/earpurifier-cloud-assets-v2"
          ],
          "competition_sources": [],
          "kernel_sources": []
        }
        
        with open(os.path.join(kernel_dir, "kernel-metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            
        logger.info(f"Pushing kernel {kernel_id} via Kaggle API...")
        self.api.kernels_push(folder=kernel_dir)
        return kernel_id
        
    def poll_status(self, kernel_id: str) -> str:
        """Polls the status of the kernel using native Kaggle SDK."""
        resp = self.api.kernels_status(kernel_id)
        status_val = getattr(resp, "status", str(resp))
        out_lower = str(status_val).lower()

        if "complete" in out_lower:
            return "COMPLETE"
        elif "error" in out_lower or "cancel" in out_lower or "fail" in out_lower:
            return "ERROR"
        elif "running" in out_lower:
            return "RUNNING"
        else:
            return "QUEUED"
            
    def download_output(self, kernel_id: str, download_dir: str):
        """Downloads the output of the completed kernel."""
        logger.info(f"Downloading output for {kernel_id}...")
        import builtins
        _open = builtins.open
        def safe_open(*args, **kwargs):
            mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
            if 'w' in mode and 'b' not in mode:
                kwargs['encoding'] = 'utf-8'
            return _open(*args, **kwargs)
            
        builtins.open = safe_open
        try:
            self.api.kernels_output(kernel_id, path=download_dir)
        finally:
            builtins.open = _open

    def cancel_kernel(self, kernel_id: str):
        """Cancels and deletes a running or queued kernel on Kaggle."""
        try:
            self.api.kernels_delete(kernel_id, no_confirm=True)
            logger.info(f"Successfully cancelled/deleted kernel {kernel_id} on Kaggle.")
        except Exception as e:
            logger.warning(f"Could not cancel kernel {kernel_id} on Kaggle: {e}")
