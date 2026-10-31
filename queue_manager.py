import os
import json
import uuid
import time
import copy
import logging
import tempfile
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

def _atomic_write_json(file_path: str, data: dict, indent: int = 2):
    dir_name = os.path.dirname(file_path)
    os.makedirs(dir_name, exist_ok=True)
    f = tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8")
    temp_path = f.name
    try:
        json.dump(data, f, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    finally:
        f.close()

    for attempt in range(3):
        try:
            os.replace(temp_path, file_path)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.05)
        finally:
            if os.path.exists(temp_path) and os.path.exists(file_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

class QueueManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.app_data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "EarPurifier")
        self.state_file = os.path.join(self.app_data_dir, "job_state.json")
        os.makedirs(self.app_data_dir, exist_ok=True)
        with self._lock:
            self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        state = {"jobs": {}}
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.error("Corrupt state file, starting fresh.")
        
        # Auto-abort any jobs that were interrupted by app shutdown
        changed = False
        for jid, job in state.get("jobs", {}).items():
            if job.get("status") in ["PENDING", "EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "DOWNLOADING", "REMUXING", "PROCESSING_LOCAL"]:
                job["status"] = "ERROR"
                job["error_message"] = "Interrupted by application shutdown."
                changed = True
                
        # Clean up all temporary files on startup to prevent corrupted states
        try:
            import shutil
            temp_dir = os.path.join(self.app_data_dir, "temp")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            empty_buffer = os.path.join(self.app_data_dir, "empty_buffer")
            if os.path.exists(empty_buffer):
                shutil.rmtree(empty_buffer, ignore_errors=True)
        except Exception:
            pass

        return state

    def _save_state(self):
        try:
            _atomic_write_json(self.state_file, self.state, indent=2)
        except Exception as e:
            logger.error(f"Failed to save job state: {e}")

    def add_job(self, media_path: str, mode: str = "Cloud (Kaggle)", duration: float = 0.0, model: str = "", selected_audio_stream: int = 0, probe_result: dict = None, save: bool = True) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self.state["jobs"][job_id] = {
                "original_media": media_path,
                "original_video": media_path,
                "flac_audio": "",
                "clean_wav": "",
                "output_media": "",
                "output_video": "",
                "status": "PENDING",
                "kaggle_kernel_id": "",
                "mode": mode,
                "model": model,
                "duration": duration,
                "selected_audio_stream": selected_audio_stream,
                "probe_result": probe_result or {},
                "added_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            if save:
                self._save_state()
        return job_id

    def update_job(self, job_id: str, updates: Dict[str, Any]):
        with self._lock:
            if job_id in self.state["jobs"]:
                job = self.state["jobs"][job_id]
                job.update(updates)
                now = datetime.now(timezone.utc)
                job["updated_at"] = now.isoformat()
                
                if "status" in updates:
                    # If job is transitioning out of PENDING into an active state, mark start time
                    if updates["status"] not in ["PENDING", "COMPLETED", "ERROR", "ABORTED"]:
                        if "started_at" not in job:
                            job["started_at"] = now.isoformat()
                            
                    # If job is finished, calculate final elapsed time based on started_at
                    if updates["status"] in ["COMPLETED", "ERROR", "ABORTED"]:
                        if "final_elapsed_seconds" not in job:
                            try:
                                start_time_str = job.get("started_at", job.get("added_at", now.isoformat()))
                                start_time = datetime.fromisoformat(start_time_str)
                                job["final_elapsed_seconds"] = int((now - start_time).total_seconds())
                            except Exception:
                                pass
                
                self._save_state()

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.state["jobs"].get(job_id, {}))

    def get_all_jobs(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.state["jobs"])

    def get_next_pending_job(self, mode: str = "Cloud (Kaggle)") -> Optional[str]:
        with self._lock:
            for job_id, job in self.state["jobs"].items():
                if job.get("status") == "PENDING" and job.get("mode", "Cloud (Kaggle)") == mode:
                    return job_id
            return None

    def has_active_cloud_job(self) -> bool:
        with self._lock:
            for job in self.state["jobs"].values():
                if job.get("status") in ["UPLOADING", "PROCESSING_CLOUD"]:
                    return True
            return False

    def abort_job(self, job_id: str):
        with self._lock:
            if job_id in self.state["jobs"]:
                self.update_job(job_id, {"status": "ABORTED"})

    def delete_job(self, job_id: str, delete_output: bool = False) -> bool:
        with self._lock:
            if job_id not in self.state["jobs"]:
                return False
            job = self.state["jobs"][job_id]
            out_file = job.get("output_media") or job.get("output_video")
            if delete_output and out_file:
                if os.path.exists(out_file) and os.path.isfile(out_file):
                    try:
                        os.remove(out_file)
                    except OSError as e:
                        logger.warning(f"Could not delete output file {out_file}: {e}")
            del self.state["jobs"][job_id]
            self._save_state()
            return True

    def delete_jobs(self, job_ids: List[str], delete_output: bool = False) -> int:
        count = 0
        with self._lock:
            for jid in job_ids:
                if self.delete_job(jid, delete_output=delete_output):
                    count += 1
        return count

    def clear_history(self, mode: str, delete_output: bool = False) -> int:
        with self._lock:
            to_delete = []
            for jid, job in self.state["jobs"].items():
                if job.get("mode", "Cloud (Kaggle)") == mode and job.get("status") in ["COMPLETED", "ERROR", "ABORTED"]:
                    to_delete.append(jid)
            return self.delete_jobs(to_delete, delete_output=delete_output)
