import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
os.environ["APPDATA"] = os.path.join(root_dir, ".test_appdata")

from PySide6.QtWidgets import QApplication
from ui.job_widget import JobWidget
from ui.theme import Theme
from i18n import t, set_language, get_current_language, translate_worker_message
from kaggle_bridge import KaggleBridge

app = QApplication.instance() or QApplication([])

class TestThreeFixes(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def tearDown(self):
        from queue_manager import QueueManager
        qm = QueueManager()
        for jid in list(qm.get_all_jobs().keys()):
            qm.delete_job(jid)
        worker_file = os.path.join(root_dir, "worker", "worker.py")
        if os.path.exists(worker_file):
            with open(worker_file, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            fixed = re.sub(r'EXPECTED_AUDIO_NAME\s*=\s*"[^"]*"', 'EXPECTED_AUDIO_NAME = "audio.flac"', content)
            if fixed != content:
                with open(worker_file, "w", encoding="utf-8") as f:
                    f.write(fixed)
        app = QApplication.instance()
        if app:
            app.closeAllWindows()
            app.processEvents()

    def test_fix1_lbl_meta_dur_total_processing_time(self):
        """Test Fix 1: lbl_meta_dur slot repurposed to Total Processing Time without --:--."""
        # 1. PENDING status: displays 00:00
        pending_job = {
            "original_media": "C:/test/sample.mp4",
            "duration": 250.0,
            "status": "PENDING",
            "model": "RoFormer"
        }
        widget_pending = JobWidget("job_p", pending_job)
        self.assertEqual(widget_pending.lbl_meta_dur.text(), "00:00")
        self.assertFalse(widget_pending.lbl_elapsed.isVisible())

        # 2. Card initialization on app relaunch with final_elapsed_seconds
        relaunch_job = {
            "original_media": "C:/test/sample.mp4",
            "duration": 500.0,
            "status": "COMPLETED",
            "final_elapsed_seconds": 125,
            "model": "RoFormer"
        }
        widget_relaunch = JobWidget("job_r", relaunch_job)
        self.assertEqual(widget_relaunch.lbl_meta_dur.text(), "02:05")
        self.assertNotIn("--:--", widget_relaunch.lbl_meta_dur.text())
        # Large duration >= 3600s
        large_job = {
            "original_media": "C:/test/sample.mp4",
            "duration": 7200.0,
            "status": "COMPLETED",
            "final_elapsed_seconds": 3665,
            "model": "RoFormer"
        }
        widget_large = JobWidget("job_l", large_job)
        self.assertEqual(widget_large.lbl_meta_dur.text(), "01:01:05")

        # 3. Active processing: ticks live during _on_timer_tick
        running_job = {
            "original_media": "C:/test/sample.mp4",
            "duration": 180.0,
            "status": "PROCESSING_CLOUD",
            "model": "RoFormer"
        }
        widget_running = JobWidget("job_run", running_job)
        widget_running.show()
        self.assertEqual(widget_running.lbl_meta_dur.text(), "00:00")
        widget_running._on_timer_tick()
        self.assertEqual(widget_running.lbl_meta_dur.text(), "00:01")
        widget_running._on_timer_tick()
        self.assertEqual(widget_running.lbl_meta_dur.text(), "00:02")
        self.assertFalse(widget_running.lbl_elapsed.isVisible())

        # 4. Status transitions to COMPLETED, ABORTED, ERROR
        widget_running.elapsed_seconds = 75
        widget_running.update_status("COMPLETED")
        self.assertEqual(widget_running.lbl_meta_dur.text(), "01:15")
        # Ensure btn_show_folder is visible and Zone 3 is clean without elapsed text next to it
        self.assertFalse(widget_running.btn_show_folder.isHidden())
        self.assertFalse(widget_running.lbl_elapsed.isVisible())

        widget_running.elapsed_seconds = 80
        widget_running.update_status("ABORTED")
        self.assertEqual(widget_running.lbl_meta_dur.text(), "01:20")
        self.assertFalse(widget_running.lbl_elapsed.isVisible())

        widget_running.elapsed_seconds = 95
        widget_running.update_status("ERROR")
        self.assertEqual(widget_running.lbl_meta_dur.text(), "01:35")
        self.assertFalse(widget_running.lbl_elapsed.isVisible())

        for w in [widget_pending, widget_relaunch, widget_large, widget_running]:
            w.timer.stop()
            w.spinner.stop()
            w.close()

    def test_fix1_main_window_probe_duration_extraction(self):
        """Test Fix 1: duration extraction from probe_result in add_media."""
        from ui.main_window import MainWindow
        mock_probe = {
            "format": {"duration": "142.75"},
            "audio_streams": [{"channels": 2}]
        }
        with patch.object(MainWindow, "init_threads"), \
             patch.object(MainWindow, "start_auto_update_check"):
            win = MainWindow()
            win.config.set("kaggle_username", "testuser")
            win.config.set("kaggle_api_key", "testkey")
            with patch("ui.main_window.probe_container", return_value=mock_probe), \
                 patch("PySide6.QtWidgets.QFileDialog.getOpenFileNames", return_value=(["C:/fake/sample_probe.mp4"], "")):
                win.add_media("Local (GPU)")
                all_jobs = win.queue_manager.get_all_jobs()
                created_job = [j for j in all_jobs.values() if "sample_probe.mp4" in j.get("original_media", "")][0]
                self.assertAlmostEqual(created_job.get("duration", 0.0), 142.75)
            win.close()

    def test_fix2_kaggle_bridge_dataset_status_polling(self):
        """Test Fix 2: push_audio actively polls dataset_status until 'ready'."""
        bridge = KaggleBridge.__new__(KaggleBridge)
        bridge.username = "testuser"
        mock_api = MagicMock()
        bridge.api = mock_api

        # Mock dataset_create_new success
        mock_api.dataset_create_new.return_value = MagicMock(error=None)

        # Mock dataset_status: "pending", "pending", "ready"
        mock_api.dataset_status.side_effect = ["pending", "pending", "ready"]

        # Call push_audio with temp mock file
        temp_dir = os.path.join(root_dir, ".test_appdata", "temp_push_test")
        os.makedirs(temp_dir, exist_ok=True)
        dummy_audio = os.path.join(temp_dir, "input.flac")
        with open(dummy_audio, "wb") as f:
            f.write(b"RIFFdummydata")

        with patch("time.sleep", return_value=None):
            dataset_id = bridge.push_audio(dummy_audio, os.path.join(temp_dir, "push"), "audio_123.flac", "job_12345678")

        self.assertEqual(dataset_id, "testuser/earpurifier-audio-buffer-job_1234")
        self.assertEqual(mock_api.dataset_status.call_count, 3)

    def test_fix2_kaggle_bridge_push_kernel_dynamic_timeout(self):
        """Test Fix 2: push_kernel accepts duration and sets duration-aware timeout."""
        bridge = KaggleBridge.__new__(KaggleBridge)
        bridge.username = "testuser"
        mock_api = MagicMock()
        bridge.api = mock_api

        kernel_dir = os.path.join(root_dir, ".test_appdata", "temp_kernel_test")
        os.makedirs(kernel_dir, exist_ok=True)

        # 1. duration = 0.0 -> max(7200, 0 + 1800) = 7200
        bridge.push_kernel(kernel_dir, "worker-1", "user/dataset-1", duration=0.0)
        mock_api.kernels_push.assert_called_with(folder=kernel_dir, timeout="7200")

        # 2. duration = 3600.0 (1 hour) -> min(43200, max(7200, 3600*3 + 1800)) = 12600
        bridge.push_kernel(kernel_dir, "worker-2", "user/dataset-2", duration=3600.0)
        mock_api.kernels_push.assert_called_with(folder=kernel_dir, timeout="12600")

        # 3. duration = 20000.0 (very long) -> min(43200, max(7200, 60000 + 1800)) = 43200
        bridge.push_kernel(kernel_dir, "worker-3", "user/dataset-3", duration=20000.0)
        mock_api.kernels_push.assert_called_with(folder=kernel_dir, timeout="43200")

    def test_fix3_queue_congestion_notice_and_eta_freeze_resume(self):
        """Test Fix 3: Queue congestion notice in i18n, freezing remaining_seconds and graceful resume."""
        # 1. Translation parity
        for lang in ["en", "ar"]:
            set_language(lang)
            text = t("eta_cloud_congested", mins=5)
            self.assertTrue(text)
            self.assertIn("5", text)
        set_language("en")

        # 2. JobWidget receives QUEUE_CONGESTED
        job_data = {
            "original_media": "C:/fake/vid.mp4",
            "duration": 300.0,
            "status": "PROCESSING_CLOUD",
            "model": "RoFormer-T4"
        }
        widget = JobWidget("job_cong", job_data, mode="Cloud (Kaggle)")
        widget.update_status("PROCESSING_CLOUD")

        # Initial timer tick initializes remaining_seconds
        widget._on_timer_tick()
        initial_remaining = widget.remaining_seconds
        self.assertGreater(initial_remaining, 0)
        self.assertFalse(widget.is_cloud_congested)

        # Timer ticks normal -> remaining_seconds decrements
        widget._on_timer_tick()
        self.assertEqual(widget.remaining_seconds, initial_remaining - 1)
        expected_paused = widget.remaining_seconds

        # Receive congestion update
        widget.update_message("QUEUE_CONGESTED:3")
        self.assertTrue(widget.is_cloud_congested)
        self.assertIn("congested (queued for 3m)", widget.lbl_eta.text())

        # Tick timer while congested -> remaining_seconds must FREEZE!
        widget._on_timer_tick()
        widget._on_timer_tick()
        self.assertEqual(widget.remaining_seconds, expected_paused)
        self.assertIn("congested (queued for 3m)", widget.lbl_eta.text())
        # elapsed_seconds should still tick
        self.assertGreater(widget.elapsed_seconds, 3)

        # Transition to RUNNING (via QUEUE_RESOLVED or Kaggle Status: RUNNING)
        widget.update_message("QUEUE_RESOLVED")
        self.assertFalse(widget.is_cloud_congested)
        self.assertNotIn("congested", widget.lbl_eta.text())

        # Next tick decrements remaining_seconds from paused state
        widget._on_timer_tick()
        self.assertEqual(widget.remaining_seconds, expected_paused - 1)
        widget.timer.stop()
        widget.spinner.stop()
        widget.close()

    def test_fix3_processor_thread_congestion_tracking(self):
        """Test Fix 3: processor_thread tracks QUEUED state and emits QUEUE_CONGESTED >= 120s."""
        from processor_thread import JobProcessor
        from queue_manager import QueueManager
        from config_manager import ConfigManager

        qm = QueueManager()
        cfg = ConfigManager()
        processor = JobProcessor(qm, "testuser", "dummykey")

        emitted_messages = []
        processor.progress_update.connect(lambda jid, msg: emitted_messages.append(msg))

        mock_bridge = MagicMock()
        mock_bridge.push_audio.return_value = "user/audio-dataset-test"
        mock_bridge.push_kernel.return_value = "user/worker-test"

        simulated_clock = [1000.0]
        poll_count = [0]
        def mock_poll(kid):
            poll_count[0] += 1
            if poll_count[0] == 1:
                simulated_clock[0] = 1000.0
                return "QUEUED"
            elif poll_count[0] == 2:
                simulated_clock[0] = 1150.0  # +150s => congested (2m)
                return "QUEUED"
            elif poll_count[0] == 3:
                simulated_clock[0] = 1200.0
                return "RUNNING"
            else:
                return "COMPLETE"

        mock_bridge.poll_status.side_effect = mock_poll
        mock_bridge.download_output.return_value = None

        job_id = qm.add_job("C:/fake/vid.mp4", mode="Cloud (Kaggle)", duration=100.0)
        job = qm.get_job(job_id)

        with patch("processor_thread.time.time", side_effect=lambda: simulated_clock[0]), \
             patch("time.time", side_effect=lambda: simulated_clock[0]), \
             patch("time.sleep", return_value=None), \
             patch.object(processor, "_save_kaggle_log", return_value=None), \
             patch("processor_thread.extract_audio", return_value=None), \
             patch("processor_thread.pad_or_trim_audio", return_value=None), \
             patch("processor_thread.remux_media", return_value=None), \
             patch("shutil.rmtree", return_value=None), \
             patch("os.remove", return_value=None):
            
            processor.kaggle_bridge = mock_bridge
            processor.running = True
            try:
                processor.process_job(job_id, job)
            except Exception:
                pass

        # Verify bridge.push_kernel received duration=100.0
        mock_bridge.push_kernel.assert_called()
        call_kwargs = mock_bridge.push_kernel.call_args[1]
        self.assertEqual(call_kwargs.get("duration"), 100.0)

        # Verify QUEUE_CONGESTED:2 was emitted, followed by QUEUE_RESOLVED
        self.assertIn("QUEUE_CONGESTED:2", emitted_messages)
        self.assertIn("QUEUE_RESOLVED", emitted_messages)

if __name__ == "__main__":
    unittest.main()
