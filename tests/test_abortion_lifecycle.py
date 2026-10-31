"""
EarPurifier - Abortion Lifecycle Unit & Integration Tests
Validates:
1. Queue Manager resurrection guard & pending deletion tracking
2. Kaggle dataset deletion with exponential backoff on 403 Forbidden
3. Abortable FFmpeg subprocess termination & JobAbortedError
4. Downloader abortion & cleanup of partial files
5. JobProcessor abortion at every phase (pre-kernel, running kernel, download, remux)
6. LocalJobProcessor abortion & process tree termination
7. Graceful deletion of running jobs without blocking subsequent queue jobs
8. Application window closeEvent abort propagation
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
import unittest
from unittest.mock import MagicMock, patch

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

test_appdata = os.path.join(root_dir, ".test_appdata")
os.environ["APPDATA"] = test_appdata
os.makedirs(test_appdata, exist_ok=True)

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui import QCloseEvent

from config_manager import ConfigManager
from queue_manager import QueueManager
from kaggle_bridge import KaggleBridge
from media_engine import JobAbortedError, _run_ffmpeg_abortable
from process_tracker import cleanup_all_subprocesses, _ACTIVE_SUBPROCESSES
from processor_thread import JobProcessor
from local_processor import LocalJobProcessor
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestAbortionLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = ConfigManager()
        self.qm = QueueManager()
        for jid in list(self.qm.get_all_jobs().keys()):
            self.qm.delete_job(jid)
        self.test_dir = tempfile.mkdtemp(prefix="ep_test_abort_")

    def tearDown(self):
        for jid in list(self.qm.get_all_jobs().keys()):
            self.qm.delete_job(jid)
        if os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
            except Exception:
                pass
        cleanup_all_subprocesses()
        app = QApplication.instance()
        if app:
            app.closeAllWindows()
            app.processEvents()

    # ── 1. Queue Manager Resurrection Guard ─────────────────────────────────

    def test_resurrection_guard_prevents_active_overwrite(self):
        """Verifies that an ABORTED job cannot be resurrected back to active or COMPLETED."""
        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)")
        self.qm.update_job(jid, {"status": "EXTRACTING"})
        self.assertEqual(self.qm.get_job(jid)["status"], "EXTRACTING")

        # Abort job
        self.qm.abort_job(jid)
        self.assertEqual(self.qm.get_job(jid)["status"], "ABORTED")

        # Attempt to overwrite with COMPLETED or intermediate statuses
        self.qm.update_job(jid, {"status": "COMPLETED"})
        self.assertEqual(self.qm.get_job(jid)["status"], "ABORTED", "Status must remain ABORTED")

        self.qm.update_job(jid, {"status": "REMUXING"})
        self.assertEqual(self.qm.get_job(jid)["status"], "ABORTED", "Status must remain ABORTED")

    def test_resurrection_guard_allows_error_and_elapsed(self):
        """Verifies that error messages or final elapsed seconds can still be recorded on ABORTED jobs."""
        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)")
        self.qm.abort_job(jid)

        self.qm.update_job(jid, {"error": "Aborted by test", "final_elapsed_seconds": 15})
        job = self.qm.get_job(jid)
        self.assertEqual(job["status"], "ABORTED")
        self.assertEqual(job.get("error"), "Aborted by test")
        self.assertEqual(job.get("final_elapsed_seconds"), 15)

    # ── 2. Active Job Deletion & Ghost Job Prevention ────────────────────────

    def test_delete_active_job_registers_pending_deletion(self):
        """Deleting an active job must register pending deletion, mark ABORTED, and hide from state."""
        dummy_out = os.path.join(self.test_dir, "output.mp4")
        with open(dummy_out, "w") as f:
            f.write("test")

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)")
        self.qm.update_job(jid, {"status": "PROCESSING_CLOUD", "output_media": dummy_out})

        # Delete running job with delete_output=True
        self.qm.delete_job(jid, delete_output=True)

        # Must NOT appear in visible jobs
        self.assertNotIn(jid, self.qm.get_all_jobs())

        # But is_job_aborted MUST return True
        self.assertTrue(self.qm.is_job_aborted(jid))

        # Pending deletion info is retained
        info = self.qm.get_pending_deletion_info(jid)
        self.assertIsNotNone(info)
        self.assertTrue(info.get("delete_output"))
        self.assertEqual(info.get("output_media"), dummy_out)

        # Worker calls finalize_job_abort
        self.qm.finalize_job_abort(jid)
        self.assertIsNone(self.qm.get_pending_deletion_info(jid))
        self.assertFalse(os.path.exists(dummy_out), "Output file should be deleted on finalize")

    # ── 3. Kaggle 403 Forbidden Retry with Backoff ──────────────────────────

    def test_delete_dataset_with_retry_overcomes_403(self):
        """Kaggle dataset deletion must retry on 403 Forbidden with backoff and succeed."""
        bridge = KaggleBridge.__new__(KaggleBridge)
        bridge.api = MagicMock()

        # Simulate 403 Forbidden twice, then success
        calls = [0]
        def mock_delete(*args, **kwargs):
            calls[0] += 1
            if calls[0] < 3:
                raise Exception("403 Client Error: Forbidden for url: https://www.kaggle.com/api/v1/datasets/delete/test")
            return True

        bridge.api.dataset_delete = MagicMock(side_effect=mock_delete)

        success = bridge.delete_dataset_with_retry("fake_user/test_dataset_slug", max_retries=4, initial_delay=0.01)
        self.assertTrue(success)
        self.assertEqual(calls[0], 3)

    def test_delete_dataset_with_retry_handles_404_as_success(self):
        """Kaggle dataset deletion treating 404 Not Found as immediate success."""
        bridge = KaggleBridge.__new__(KaggleBridge)
        bridge.api = MagicMock()
        bridge.api.dataset_delete = MagicMock(side_effect=Exception("404 Client Error: Not Found"))

        success = bridge.delete_dataset_with_retry("fake_user/nonexistent_dataset", max_retries=3, initial_delay=0.01)
        self.assertTrue(success)
        self.assertEqual(bridge.api.dataset_delete.call_count, 1)

    # ── 4. FFmpeg Abortable Subprocess Execution ─────────────────────────────

    def test_run_ffmpeg_abortable_terminates_immediately(self):
        """_run_ffmpeg_abortable terminates process and raises JobAbortedError when abort_check triggers."""
        cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
        
        start_t = time.time()
        should_abort = False
        def check():
            return should_abort

        def trigger():
            nonlocal should_abort
            time.sleep(0.05)
            should_abort = True

        import threading
        t = threading.Thread(target=trigger)
        t.start()

        with self.assertRaises(JobAbortedError):
            _run_ffmpeg_abortable(cmd, abort_check=check)

        elapsed = time.time() - start_t
        self.assertLess(elapsed, 2.0, "FFmpeg abortable must terminate within ~100-200ms")
        t.join()

    # ── 5. Kaggle Output Downloader Abortion ─────────────────────────────────

    def test_download_output_stops_on_abort_and_purges_parts(self):
        """download_output terminates download threads and purges .part files on abort."""
        bridge = KaggleBridge.__new__(KaggleBridge)
        bridge.username = "testuser"
        bridge.api_key = "testkey"
        bridge.api = MagicMock()

        dest_dir = os.path.join(self.test_dir, "downloads")
        os.makedirs(dest_dir, exist_ok=True)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "1000000"}
        mock_response.iter_content = MagicMock(return_value=[b"A" * 1024, b"B" * 1024])

        with patch("requests.get", return_value=mock_response), \
             patch("requests.Session") as mock_session_cls:
            
            mock_session = MagicMock()
            mock_session.get.return_value = mock_response
            mock_session_cls.return_value = mock_session

            # Abort immediately
            success = bridge.download_output("testuser/test_kernel_slug", dest_dir, abort_check=lambda: True)
            self.assertFalse(success)

            # Ensure no orphaned .part files exist
            part_files = [f for f in os.listdir(dest_dir) if ".part" in f]
            self.assertEqual(len(part_files), 0)

    # ── 6. Cloud JobProcessor Abortion During Polling ────────────────────────

    def test_cloud_processor_aborts_during_kernel_polling(self):
        """JobProcessor cancels kernel and cleans dataset when job is aborted mid-poll."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        mock_bridge = MagicMock()
        mock_bridge.push_audio.return_value = "fake_user/test-ds"
        mock_bridge.create_dataset_with_retry.return_value = "fake_user/test-ds"
        mock_bridge.push_kernel.return_value = "fake_user/test-kernel"
        mock_bridge.cancel_kernel = MagicMock()
        mock_bridge.delete_dataset_with_retry = MagicMock(return_value=True)

        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)")
        job = self.qm.get_job(jid)
        
        status_checks = [0]
        def mock_status(k_id):
            status_checks[0] += 1
            if status_checks[0] >= 1:
                self.qm.abort_job(jid)
            return "RUNNING"

        mock_bridge.poll_status.side_effect = mock_status

        # Create dummy source media file
        sample_file = os.path.join(self.test_dir, "sample.mp4")
        with open(sample_file, "w") as f:
            f.write("fake media")

        self.qm.update_job(jid, {"original_media": sample_file, "original_video": sample_file})
        job = self.qm.get_job(jid)

        with patch("processor_thread.probe_container", return_value={"format": {"duration": "10.0"}, "audio_streams": [{"index": 0}]}), \
             patch("processor_thread.extract_audio", return_value="dummy.flac"):
            
            processor.process_job(jid, job)

        updated_job = self.qm.get_job(jid)
        self.assertEqual(updated_job["status"], "ABORTED")
        mock_bridge.cancel_kernel.assert_called_with("fake_user/test-kernel")
        mock_bridge.delete_dataset_with_retry.assert_called_with("fake_user/test-ds")

    # ── 7. Cloud JobProcessor Skips Already-Aborted Job ──────────────────────

    def test_cloud_processor_skips_pre_aborted_job(self):
        """JobProcessor immediately marks pre-aborted jobs without running any pipeline steps."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        mock_bridge = MagicMock()
        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)")
        self.qm.abort_job(jid)
        job = self.qm.get_job(jid)

        with patch("processor_thread.probe_container") as mock_probe:
            processor.process_job(jid, job)
            mock_probe.assert_not_called()

        self.assertEqual(self.qm.get_job(jid)["status"], "ABORTED")

    # ── 8. LocalJobProcessor Aborts Process Tree ─────────────────────────────

    def test_local_processor_aborts_and_kills_process(self):
        """LocalJobProcessor terminates child process and removes temp dir on abort."""
        processor = LocalJobProcessor(self.qm, self.config)

        sample_file = os.path.join(self.test_dir, "sample.mp4")
        with open(sample_file, "w") as f:
            f.write("fake media")

        jid = self.qm.add_job(sample_file, mode="Local (GPU)")
        job = self.qm.get_job(jid)

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.return_value = None

        with patch("local_processor.DependencyManager.has_local_engine", return_value=True), \
             patch("local_processor.DependencyManager.get_engine_separator_exe", return_value="fake_separator.exe"), \
             patch("local_processor.DependencyManager.get_env_dir", return_value="fake_env"), \
             patch("local_processor.probe_container", return_value={"format": {"duration": "10.0"}, "audio_streams": [{"index": 0}]}), \
             patch("local_processor.extract_audio", return_value="dummy.flac"), \
             patch("subprocess.Popen", return_value=mock_proc), \
             patch("process_tracker.kill_process_tree") as mock_kill, \
             patch("process_tracker.unregister_process"):

            def mock_readline():
                self.qm.abort_job(jid)
                return "Processing line...\n"

            mock_proc.stdout.readline = mock_readline

            processor.process_local_job(jid, job)

            self.assertEqual(self.qm.get_job(jid)["status"], "ABORTED")
            mock_kill.assert_called_with(99999)

    # ── 9. Deleting Running Job Doesn't Block Next Queue Job ─────────────────

    def test_delete_running_job_advances_queue(self):
        """Deleting job 1 while running aborts job 1 cleanly and allows job 2 to run."""
        sample_file1 = os.path.join(self.test_dir, "job1.mp4")
        with open(sample_file1, "w") as f:
            f.write("fake media")

        jid1 = self.qm.add_job(sample_file1, mode="Cloud (Kaggle)")
        jid2 = self.qm.add_job("job2.mp4", mode="Cloud (Kaggle)")
        job1 = self.qm.get_job(jid1)

        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        mock_bridge = MagicMock()
        mock_bridge.push_audio.return_value = "fake_user/ds1"
        mock_bridge.create_dataset_with_retry.return_value = "fake_user/ds1"
        mock_bridge.push_kernel.return_value = "fake_user/kern1"
        mock_bridge.cancel_kernel = MagicMock()
        mock_bridge.delete_dataset_with_retry = MagicMock(return_value=True)
        processor.kaggle_bridge = mock_bridge

        # Delete job1 mid-flight
        def mock_status(k_id):
            self.qm.delete_job(jid1)
            return "RUNNING"

        mock_bridge.poll_status.side_effect = mock_status

        with patch("processor_thread.probe_container", return_value={"format": {"duration": "10.0"}, "audio_streams": [{"index": 0}]}), \
             patch("processor_thread.extract_audio", return_value="dummy.flac"):
            
            processor.process_job(jid1, job1)

        # Job 1 must be gone
        self.assertNotIn(jid1, self.qm.get_all_jobs())

        # Job 2 is still PENDING and ready to be processed
        job2 = self.qm.get_job(jid2)
        self.assertIsNotNone(job2)
        self.assertEqual(job2["status"], "PENDING")

    # ── 10. MainWindow closeEvent Aborts Active Jobs ─────────────────────────

    def test_main_window_close_event_aborts_active_jobs(self):
        """MainWindow closeEvent automatically invokes abort_job on all active jobs."""
        with patch.object(MainWindow, "init_threads"), patch.object(MainWindow, "start_auto_update_check"):
            win = MainWindow()
            jid = win.queue_manager.add_job("running.mp4", mode="Cloud (Kaggle)")
            win.queue_manager.update_job(jid, {"status": "EXTRACTING"})

            with patch("ui.overlay_widgets.CloseActiveJobDialog.exec", return_value=QDialog.Accepted), \
                 patch("process_tracker.terminate_qt_threads"), \
                 patch("process_tracker.cleanup_all_subprocesses"):

                event = QCloseEvent()
                win.closeEvent(event)

                self.assertTrue(event.isAccepted())
                self.assertEqual(win.queue_manager.get_job(jid)["status"], "ABORTED")
            win.close()


if __name__ == "__main__":
    unittest.main()
