import os
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

class QueueManager:
    def __init__(self):
        self.app_data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "EarPurifier")
        self.state_file = os.path.join(self.app_data_dir, "job_state.json")
        os.makedirs(self.app_data_dir, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        state = {"jobs": {}}
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
            except json.JSONDecodeError:
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
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def add_job(self, video_path: str, mode: str = "Cloud (Kaggle)", duration: float = 0.0, model: str = "") -> str:
        job_id = str(uuid.uuid4())
        self.state["jobs"][job_id] = {
            "original_video": video_path,
            "flac_audio": "",
            "clean_wav": "",
            "output_video": "",
            "status": "PENDING",
            "kaggle_kernel_id": "",
            "mode": mode,
            "model": model,
            "duration": duration,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        self._save_state()
        return job_id

    def update_job(self, job_id: str, updates: Dict[str, Any]):
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
                            # Default to added_at if started_at is somehow missing (e.g., aborted while pending)
                            start_time_str = job.get("started_at", job.get("added_at", now.isoformat()))
                            start_time = datetime.fromisoformat(start_time_str)
                            job["final_elapsed_seconds"] = int((now - start_time).total_seconds())
                        except Exception:
                            pass
            
            self._save_state()

    def get_job(self, job_id: str) -> Dict[str, Any]:
        return self.state["jobs"].get(job_id, {})

    def get_all_jobs(self) -> Dict[str, Any]:
        return self.state["jobs"]

    def get_next_pending_job(self, mode: str = "Cloud (Kaggle)") -> str:
        for job_id, job in self.state["jobs"].items():
            if job["status"] == "PENDING" and job.get("mode", "Cloud (Kaggle)") == mode:
                return job_id
        return None

    def has_active_cloud_job(self) -> bool:
        for job in self.state["jobs"].values():
            if job["status"] in ["UPLOADING", "PROCESSING_CLOUD"]:
                return True
        return False

    def abort_job(self, job_id: str):
        if job_id in self.state["jobs"]:
            self.update_job(job_id, {"status": "ABORTED"})

    def delete_job(self, job_id: str, delete_output: bool = False) -> bool:
        if job_id not in self.state["jobs"]:
            return False
        job = self.state["jobs"][job_id]
        if delete_output and job.get("output_video"):
            out_file = job["output_video"]
            if os.path.exists(out_file) and os.path.isfile(out_file):
                try:
                    os.remove(out_file)
                except OSError as e:
                    logger.warning(f"Could not delete output file {out_file}: {e}")
        del self.state["jobs"][job_id]
        self._save_state()
        return True

    def delete_jobs(self, job_ids: list[str], delete_output: bool = False) -> int:
        count = 0
        for jid in job_ids:
            if self.delete_job(jid, delete_output=delete_output):
                count += 1
        return count

    def clear_history(self, mode: str, delete_output: bool = False) -> int:
        to_delete = []
        for jid, job in self.state["jobs"].items():
            if job.get("mode", "Cloud (Kaggle)") == mode and job["status"] in ["COMPLETED", "ERROR", "ABORTED"]:
                to_delete.append(jid)
        return self.delete_jobs(to_delete, delete_output=delete_output)
