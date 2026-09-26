import os
import json
import shutil
import time
import logging
import certifi
from typing import Optional

os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["CURL_CA_BUNDLE"] = certifi.where()

logger = logging.getLogger(__name__)

class KaggleError(Exception):
    pass

class KaggleBridge:
    def __init__(self, username: str, api_key: str):
        self.username = username.strip().lower().replace('"', '').replace("'", "")
        clean_key = api_key.strip().replace('"', '').replace("'", "").replace(",", "")
        self.dataset_name = "earpurifier-audio-buffer"
        self.dataset_id = f"{self.username}/{self.dataset_name}"
        self.assets_dataset_id = f"{self.username}/audio-separation-assets"
        
        # Inject API credentials to environment for kaggle API SDK
        os.environ["KAGGLE_USERNAME"] = self.username
        
        # Clear previous credentials from memory to prevent pollution if user switches token formats mid-session
        os.environ.pop("KAGGLE_KEY", None)
        os.environ.pop("KAGGLE_API_TOKEN", None)
        
        if clean_key.startswith("KGAT_"):
            os.environ["KAGGLE_API_TOKEN"] = clean_key
        else:
            os.environ["KAGGLE_KEY"] = clean_key
            
        # Force the config dir to a dummy path so the SDK can NEVER accidentally fall back to a stale ~/.kaggle/kaggle.json
        os.environ["KAGGLE_CONFIG_DIR"] = os.path.join(os.environ.get("APPDATA", ""), "EarPurifier", "dummy_kaggle")
        
        # Initialize native Kaggle API client
        from kaggle.api.kaggle_api_extended import KaggleApi
        self.api = KaggleApi()
        self.api.authenticate()
        
        # DEBUG LOGGING
        try:
            raw_key = os.environ.get("KAGGLE_KEY", "")
            mask_pass = f"{raw_key[:4]}...{raw_key[-4:]}" if len(raw_key) > 8 else "INVALID_LENGTH"
            logger.info(f"Kaggle Auth Debug -> Enforced User: '{self.username}', Enforced Key: '{mask_pass}'")
        except Exception as e:
            logger.error(f"Kaggle Auth Debug Failed: {e}")

    def push_audio(self, audio_path: str, temp_dir: str, stamped_name: str, job_id: str, abort_check: Optional[callable] = None) -> str:
        """Pushes an audio file to a fresh, job-specific Kaggle buffer dataset."""
        os.makedirs(temp_dir, exist_ok=True)
        # Clear temp dir
        for f in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, f))
            except Exception:
                pass
                
        # Copy new audio with the job-stamped name
        dest_path = os.path.join(temp_dir, stamped_name)
        shutil.copy(audio_path, dest_path)
        
        job_slug = f"earpurifier-audio-buffer-{job_id[:8]}"
        dataset_id = f"{self.username}/{job_slug}"
        
        metadata = {
            "title": job_slug,
            "id": dataset_id,
            "licenses": [{"name": "CC0-1.0"}],
            "isPrivate": False
        }
        with open(os.path.join(temp_dir, "dataset-metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            
        logger.info(f"Creating unique job dataset {dataset_id}...")
        resp = self.api.dataset_create_new(folder=temp_dir, dir_mode="zip", quiet=True)
        # Kaggle sometimes returns an empty string for error even on success
        if resp and getattr(resp, "error", None):
            error_msg = getattr(resp, "error")
            if error_msg.strip():
                raise KaggleError(f"Failed to create dataset on Kaggle: {error_msg}")
            
        logger.info("Successfully created dataset on Kaggle. Waiting 45s for processing...")
        if abort_check:
            for _ in range(45):
                if abort_check():
                    break
                time.sleep(1)
        else:
            time.sleep(45)
        return dataset_id

    def push_kernel(self, kernel_dir: str, kernel_name: str, dataset_id: str) -> str:
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
            dataset_id,
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
