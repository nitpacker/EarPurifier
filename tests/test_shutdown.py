"""
EarPurifier - Clean Process and Thread Shutdown Unit Tests
Validates that on window close, all threads, subprocesses, and sockets are cleanly and immediately destroyed.
"""

import os
import sys
import time
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from config_manager import ConfigManager
from queue_manager import QueueManager
from process_tracker import (
    register_process,
    unregister_process,
    cleanup_all_subprocesses,
    kill_process_tree,
    terminate_qt_threads,
    _ACTIVE_SUBPROCESSES
)
from update_checker import (
    GitHubUpdateChecker,
    stop_all_active_checkers,
    _ACTIVE_CHECKERS
)


class TestShutdownLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = ConfigManager()

    def test_subprocess_tracker_and_kill(self):
        """Verifies that child subprocesses are tracked and terminated cleanly."""
        # Spawn a dummy long-running process
        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        proc = subprocess.Popen(cmd)
        register_process(proc)

        self.assertIn(proc, _ACTIVE_SUBPROCESSES)
        self.assertIsNone(proc.poll())  # Process is running

        # Cleanup all subprocesses
        cleanup_all_subprocesses()

        self.assertEqual(len(_ACTIVE_SUBPROCESSES), 0)
        # Give OS 50ms to report exit
        proc.poll()
        self.assertIsNotNone(proc.poll())

    def test_active_checkers_cleanup(self):
        """Verifies that running update checkers are terminated and removed from registry."""
        def slow_get(*args, **kwargs):
            time.sleep(5)
            return MagicMock(status_code=200)

        with patch("update_checker.requests.get", side_effect=slow_get):
            checker = GitHubUpdateChecker(config=self.config, force=True)
            checker.start()
            self.assertTrue(checker.isRunning())
            self.assertIn(checker, _ACTIVE_CHECKERS)

            stop_all_active_checkers()

            self.assertFalse(checker.isRunning())
            self.assertEqual(len(_ACTIVE_CHECKERS), 0)

    def test_main_window_close_event_terminates_all(self):
        """Verifies that MainWindow.closeEvent terminates checkers, worker threads, and subprocesses."""
        from ui.main_window import MainWindow

        win = MainWindow()
        win.show()

        # Simulate active threads
        self.assertTrue(hasattr(win, "local_thread"))
        self.assertTrue(win.local_thread.isRunning())

        # Trigger closeEvent
        win.close()

        # Verify threads are stopped
        time.sleep(0.1)
        self.assertFalse(win.local_thread.isRunning())
        if hasattr(win, "cloud_thread") and win.cloud_thread:
            self.assertFalse(win.cloud_thread.isRunning())
        self.assertEqual(len(_ACTIVE_CHECKERS), 0)

    def test_close_active_job_dialog_bilingual(self):
        """Verifies that CloseActiveJobDialog renders properly with localized text."""
        from ui.overlay_widgets import CloseActiveJobDialog
        from i18n import set_language

        for lang in ["ar", "en"]:
            set_language(lang)
            dlg = CloseActiveJobDialog()
            self.assertTrue(dlg.btn_keep.text())
            self.assertTrue(dlg.btn_abort.text())
            self.assertTrue(dlg.windowTitle())
            dlg.close()

    def test_main_window_close_event_prompt_when_active(self):
        """Verifies that closing with active jobs prompts user, and aborts jobs only on accept."""
        from ui.main_window import MainWindow
        from PySide6.QtGui import QCloseEvent

        win = MainWindow()
        # Add an active job
        jid = "test_active_job_123"
        win.queue_manager.state["jobs"][jid] = {
            "status": "PROCESSING_CLOUD",
            "kaggle_kernel_id": "testuser/earpurifier-job-123",
            "mode": "Cloud (Kaggle)"
        }

        # 1. User cancels exit (clicks Keep Running)
        with patch("ui.overlay_widgets.CloseActiveJobDialog.exec", return_value=0):
            event = QCloseEvent()
            win.closeEvent(event)
            self.assertFalse(event.isAccepted())
            self.assertEqual(win.queue_manager.get_job(jid)["status"], "PROCESSING_CLOUD")

        # 2. User confirms exit (clicks Exit & Abort)
        mock_cloud_thread = MagicMock()
        win.cloud_thread = mock_cloud_thread
        with patch("ui.overlay_widgets.CloseActiveJobDialog.exec", return_value=1):
            event = QCloseEvent()
            win.closeEvent(event)
            self.assertTrue(event.isAccepted())
            self.assertEqual(win.queue_manager.get_job(jid)["status"], "ABORTED")
            mock_cloud_thread.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
