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
            raw_key = os.environ.get("KAGGLE_API_TOKEN", "") or os.environ.get("KAGGLE_KEY", "")
            if raw_key.startswith("KGAT_"):
                mask_pass = f"KGAT_...{raw_key[-4:]}"
            elif len(raw_key) > 8:
                mask_pass = f"{raw_key[:4]}...{raw_key[-4:]}"
            else:
                mask_pass = "INVALID_LENGTH"
            auth_mode = "Bearer (KGAT)" if "KAGGLE_API_TOKEN" in os.environ else "Basic (Legacy Key)"
            logger.info(f"Kaggle Auth Debug -> User: '{self.username}', Key: '{mask_pass}', Mode: {auth_mode}")
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
            "licenses": [{"name": "CC0-1.0"}]
        }
        with open(os.path.join(temp_dir, "dataset-metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            
        logger.info(f"Creating unique job dataset {dataset_id}...")
        resp = self.api.dataset_create_new(folder=temp_dir, dir_mode="zip", quiet=True, public=False)
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
            
    def download_output(self, kernel_id: str, download_dir: str, progress_callback=None):
        """Downloads the output of the completed kernel robustly with resume support."""
        logger.info(f"Downloading output for {kernel_id}...")
        
        from kagglesdk.kernels.types.kernels_api_service import ApiListKernelSessionOutputRequest
        import requests
        
        owner_slug, kernel_slug = kernel_id.split("/")
        with self.api.build_kaggle_client() as kaggle_client:
            req = ApiListKernelSessionOutputRequest()
            req.user_name = owner_slug
            req.kernel_slug = kernel_slug
            resp = kaggle_client.kernels.kernels_api_client.list_kernel_session_output(req)
            
        if not resp.files:
            raise Exception("No output files found for kernel.")
            
        os.makedirs(download_dir, exist_ok=True)
        
        for item in resp.files:
            # We strictly only care about the clean_vocals.flac file. Do not waste user bandwidth downloading instrumentals or logs.
            if item.file_name != "clean_vocals.flac":
                continue
                
            outfile = os.path.join(download_dir, item.file_name)
            url = item.url
            
            # Robust Multi-Threaded Resumable Download Loop
            # Kaggle returns 404 for HEAD requests, so we must use a stream GET to fetch headers
            with requests.get(url, stream=True, timeout=15) as head_res:
                total_expected = int(head_res.headers.get("Content-Length", 0))
                
            if total_expected == 0:
                raise Exception("Could not determine file size for download.")

            num_threads = 4
            import math, threading, concurrent.futures, shutil
            chunk_size = math.ceil(total_expected / num_threads)
            
            progress_lock = threading.Lock()
            downloaded_bytes = 0
            last_percent = -1
            
            def download_part(part_num, start, end):
                nonlocal downloaded_bytes, last_percent
                part_file = f"{outfile}.part{part_num}"
                expected_size = end - start + 1
                
                # If part already exists and is full size, skip
                if os.path.exists(part_file) and os.path.getsize(part_file) == expected_size:
                    with progress_lock:
                        downloaded_bytes += expected_size
                    return part_file
                    
                headers = {"Range": f"bytes={start}-{end}"}
                for attempt in range(5):
                    written_so_far = 0
                    try:
                        res = requests.get(url, headers=headers, stream=True, timeout=15)
                        if res.status_code not in (200, 206):
                            res.raise_for_status()
                            
                        with open(part_file, "wb") as f:
                            for chunk in res.iter_content(chunk_size=1024*1024):
                                if chunk:
                                    f.write(chunk)
                                    chunk_len = len(chunk)
                                    written_so_far += chunk_len
                                    with progress_lock:
                                        downloaded_bytes += chunk_len
                                        if progress_callback:
                                            percent = int((downloaded_bytes / total_expected) * 100)
                                            if percent > last_percent:
                                                mb_done = downloaded_bytes / (1024 * 1024)
                                                mb_total = total_expected / (1024 * 1024)
                                                progress_callback(percent, f"Downloading {item.file_name} [4 Threads] ({mb_done:.1f}MB / {mb_total:.1f}MB)")
                                                last_percent = percent
                        
                        if os.path.getsize(part_file) == expected_size:
                            return part_file
                    except Exception as e:
                        logger.warning(f"Thread {part_num} attempt {attempt+1} failed: {e}")
                        with progress_lock:
                            downloaded_bytes -= written_so_far
                        time.sleep(2)
                raise Exception(f"Failed to fully download {item.file_name} part {part_num} after 5 attempts.")

            # Execute threaded downloads
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = []
                for i in range(num_threads):
                    start = i * chunk_size
                    end = min(start + chunk_size - 1, total_expected - 1)
                    futures.append(executor.submit(download_part, i, start, end))
                    
                part_files = [f.result() for f in futures]
                
            # Stitch files together
            logger.info(f"Stitching {num_threads} parts for {item.file_name}...")
            with open(outfile, "wb") as final_f:
                for pf in part_files:
                    with open(pf, "rb") as part_f:
                        shutil.copyfileobj(part_f, final_f, length=1024*1024*5)
                    os.remove(pf)
                    
            logger.info(f"Successfully downloaded and stitched {item.file_name}")

    def fetch_kernel_logs(self, kernel_id: str) -> str:
        """Fetches the stdout/stderr log from a completed or errored Kaggle kernel.
        Returns the raw log string, or an error message if retrieval fails."""
        try:
            log_output = self.api.kernels_logs(kernel_id)
            return str(log_output)
        except Exception as e:
            return f"[Could not retrieve Kaggle logs: {e}]"

    def cancel_kernel(self, kernel_id: str):
        """Cancels and deletes a running or queued kernel on Kaggle."""
        try:
            self.api.kernels_delete(kernel_id, no_confirm=True)
            logger.info(f"Successfully cancelled/deleted kernel {kernel_id} on Kaggle.")
        except Exception as e:
            logger.warning(f"Could not cancel kernel {kernel_id} on Kaggle: {e}")
