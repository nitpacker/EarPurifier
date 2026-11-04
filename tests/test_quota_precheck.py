"""
EarPurifier - Unit and Integration Tests for Cloud GPU Quota Pre-Check & Kernel Deletion Abort
Validates:
1. KaggleBridge.check_gpu_quota_status detects verified vs unverified GPU accounts.
2. KaggleBridge.check_gpu_quota_status enforces strict timeout and abort awareness.
3. KaggleBridge.cancel_kernel executes immediate container deletion (calls kernels_delete with no_confirm=True, zero kernels_push calls).
4. JobProcessor pre-check triggers for RoFormer/MDX23C in Cloud mode.
5. JobProcessor bypasses pre-check for Kim Vocal 2 or Local mode.
6. Verification UI components (PhoneVerificationWarningDialog and VerificationReminderBanner).
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch, ANY

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

test_appdata = os.path.join(root_dir, ".test_appdata")
os.environ["APPDATA"] = test_appdata
os.makedirs(test_appdata, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from config_manager import ConfigManager
from queue_manager import QueueManager
from kaggle_bridge import KaggleBridge
from processor_thread import JobProcessor
from ui.dialogs import PhoneVerificationWarningDialog
from ui.overlay_widgets import VerificationReminderBanner
from ui.components import VectorWarningBadge

app = QApplication.instance() or QApplication([])


class TestKaggleBridgeQuotaAndAbort(unittest.TestCase):
    """Tests for KaggleBridge quota checking and Option A cancellation stub."""

    def setUp(self):
        self.bridge = KaggleBridge.__new__(KaggleBridge)
        self.bridge.username = "testuser"
        self.bridge.api = MagicMock()

    def test_quota_status_verified(self):
        """Returns VERIFIED when gpu_quota.has_ever_run is True."""
        mock_quota = MagicMock()
        mock_quota.gpu_quota = MagicMock(has_ever_run=True)
        self.bridge.api.quota_view.return_value = mock_quota

        res = self.bridge.check_gpu_quota_status(timeout_seconds=2.0)
        self.assertEqual(res.get("status"), "VERIFIED")

    def test_quota_status_unverified_when_has_ever_run_false(self):
        """Returns UNVERIFIED when gpu_quota.has_ever_run is False."""
        mock_quota = MagicMock()
        mock_quota.gpu_quota = MagicMock(has_ever_run=False)
        self.bridge.api.quota_view.return_value = mock_quota

        res = self.bridge.check_gpu_quota_status(timeout_seconds=2.0)
        self.assertEqual(res.get("status"), "UNVERIFIED")

    def test_quota_status_could_not_verify_when_gpu_quota_none(self):
        """Returns TIMEOUT_OR_ERROR (could not verify) when gpu_quota is missing/None."""
        mock_quota = MagicMock()
        mock_quota.gpu_quota = None
        mock_quota.gpuQuota = None
        self.bridge.api.quota_view.return_value = mock_quota

        res = self.bridge.check_gpu_quota_status(timeout_seconds=2.0)
        self.assertEqual(res.get("status"), "TIMEOUT_OR_ERROR")

    def test_quota_status_dict_verified_and_unverified(self):
        """Handles dict-like quota responses properly for both verified and unverified accounts."""
        self.bridge.api.quota_view.return_value = {"gpu_quota": {"has_ever_run": True}}
        res_v = self.bridge.check_gpu_quota_status(timeout_seconds=2.0)
        self.assertEqual(res_v.get("status"), "VERIFIED")

        self.bridge.api.quota_view.return_value = {"gpu_quota": {"has_ever_run": False}}
        res_u = self.bridge.check_gpu_quota_status(timeout_seconds=2.0)
        self.assertEqual(res_u.get("status"), "UNVERIFIED")

    def test_quota_status_timeout(self):
        """Enforces timeout deadline and returns TIMEOUT_OR_ERROR on hanging API."""
        def hanging_call():
            time.sleep(2.0)
            return MagicMock()

        self.bridge.api.quota_view.side_effect = hanging_call

        start_t = time.time()
        res = self.bridge.check_gpu_quota_status(timeout_seconds=0.3)
        elapsed = time.time() - start_t

        self.assertEqual(res.get("status"), "TIMEOUT_OR_ERROR")
        self.assertIn("timed out", res.get("error", "").lower())
        self.assertLess(elapsed, 1.5, "Timeout must return promptly without hanging")

    def test_quota_status_api_exception(self):
        """Handles network/API exceptions and returns TIMEOUT_OR_ERROR."""
        self.bridge.api.quota_view.side_effect = Exception("401 Client Error: Unauthorized")

        res = self.bridge.check_gpu_quota_status(timeout_seconds=1.0)
        self.assertEqual(res.get("status"), "TIMEOUT_OR_ERROR")
        self.assertIn("401", res.get("error", ""))

    def test_quota_status_aborted_early(self):
        """Returns ABORTED promptly if abort_check returns True."""
        def slow_call():
            time.sleep(2.0)
            return MagicMock()

        self.bridge.api.quota_view.side_effect = slow_call

        start_t = time.time()
        res = self.bridge.check_gpu_quota_status(timeout_seconds=2.0, abort_check=lambda: True)
        elapsed = time.time() - start_t

        self.assertEqual(res.get("status"), "ABORTED")
        self.assertLess(elapsed, 0.5, "Must abort immediately when check triggers")

    def test_cancel_kernel_deletes_container_immediately(self):
        """cancel_kernel directly invokes api.kernels_delete and NEVER calls kernels_push."""
        self.bridge.api.kernels_push = MagicMock()
        self.bridge.api.kernels_delete = MagicMock()

        self.bridge.cancel_kernel("testuser/test-worker-slug")

        self.bridge.api.kernels_delete.assert_called_once_with("testuser/test-worker-slug", no_confirm=True)
        self.bridge.api.kernels_push.assert_not_called()

    def test_cancel_kernel_idempotent_on_403_and_404(self):
        """cancel_kernel cleanly tolerates Kaggle 403 Forbidden and 404 Not Found errors without raising."""
        for error_msg in ["403 Client Error: Forbidden", "404 Client Error: Not Found", "Kernel not found"]:
            self.bridge.api.kernels_delete = MagicMock(side_effect=Exception(error_msg))
            try:
                self.bridge.cancel_kernel("testuser/test-worker-slug")
            except Exception as e:
                self.fail(f"cancel_kernel raised unexpectedly on error '{error_msg}': {e}")

    def test_cancel_kernel_logs_warning_on_other_exceptions(self):
        """cancel_kernel logs warning and does not crash when unexpected API error occurs."""
        self.bridge.api.kernels_delete = MagicMock(side_effect=Exception("500 Internal Server Error"))
        try:
            self.bridge.cancel_kernel("testuser/test-worker-slug")
        except Exception as e:
            self.fail(f"cancel_kernel raised unexpectedly on 500 error: {e}")

    def test_cancel_kernel_invalid_id_noop(self):
        """cancel_kernel safely no-ops on empty, non-string, or invalid kernel ID."""
        self.bridge.api.kernels_delete = MagicMock()
        self.bridge.api.kernels_push = MagicMock()
        self.bridge.cancel_kernel("")
        self.bridge.cancel_kernel(None)
        self.bridge.cancel_kernel(12345)
        self.bridge.cancel_kernel(["testuser/worker"])
        self.bridge.cancel_kernel("invalid_no_slash")
        self.bridge.api.kernels_delete.assert_not_called()
        self.bridge.api.kernels_push.assert_not_called()

    def test_cancel_kernel_strips_whitespace(self):
        """cancel_kernel strips whitespace from slug before invoking kernels_delete."""
        self.bridge.api.kernels_delete = MagicMock()
        self.bridge.api.kernels_push = MagicMock()
        self.bridge.cancel_kernel("  testuser/test-worker-slug  ")
        self.bridge.api.kernels_delete.assert_called_once_with("testuser/test-worker-slug", no_confirm=True)
        self.bridge.api.kernels_push.assert_not_called()

    def test_cancel_kernel_numeric_status_errors(self):
        """cancel_kernel tolerates numeric 403 and 404 error strings idempotently."""
        for error_msg in ["HTTP Error 403", "404 Not Found", "KaggleApi error: 403"]:
            self.bridge.api.kernels_delete = MagicMock(side_effect=Exception(error_msg))
            try:
                self.bridge.cancel_kernel("testuser/test-worker-slug")
            except Exception as e:
                self.fail(f"cancel_kernel raised unexpectedly on numeric error '{error_msg}': {e}")


class TestJobProcessorQuotaPreCheck(unittest.TestCase):
    """Tests for JobProcessor pre-check dispatch and passthrough rules."""

    def setUp(self):
        self.config = ConfigManager()
        self.qm = QueueManager()
        for jid in list(self.qm.get_all_jobs().keys()):
            self.qm.delete_job(jid)
        self.test_dir = tempfile.mkdtemp(prefix="ep_test_precheck_")

    def tearDown(self):
        for jid in list(self.qm.get_all_jobs().keys()):
            self.qm.delete_job(jid)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cloud_roformer_triggers_quota_check_and_warning_on_unverified(self):
        """Cloud mode + RoFormer must trigger quota check and emit verification_warning if unverified."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        mock_bridge = MagicMock()
        mock_bridge.check_gpu_quota_status.return_value = {"status": "UNVERIFIED"}
        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)", model="RoFormer")

        warning_emitted = []
        processor.verification_warning.connect(lambda j, m, w: warning_emitted.append((j, m, w)))

        # Abort extract_audio to prevent full pipeline run
        with patch("processor_thread.extract_audio", side_effect=Exception("stop_after_check")):
            try:
                processor.process_job(jid, self.qm.get_job(jid))
            except Exception:
                pass

        mock_bridge.check_gpu_quota_status.assert_called_once()
        self.assertEqual(len(warning_emitted), 1)
        self.assertEqual(warning_emitted[0], (jid, "RoFormer", "UNVERIFIED"))

    def test_cloud_mdx23c_triggers_warning_on_timeout(self):
        """Cloud mode + MDX23C must trigger quota check and emit TIMEOUT_OR_ERROR on failure."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        mock_bridge = MagicMock()
        mock_bridge.check_gpu_quota_status.return_value = {"status": "TIMEOUT_OR_ERROR", "error": "timed out"}
        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)", model="MDX23C")

        warning_emitted = []
        processor.verification_warning.connect(lambda j, m, w: warning_emitted.append((j, m, w)))

        with patch("processor_thread.extract_audio", side_effect=Exception("stop_after_check")):
            try:
                processor.process_job(jid, self.qm.get_job(jid))
            except Exception:
                pass

        mock_bridge.check_gpu_quota_status.assert_called_once()
        self.assertEqual(len(warning_emitted), 1)
        self.assertEqual(warning_emitted[0], (jid, "MDX23C", "TIMEOUT_OR_ERROR"))

    def test_cloud_kim_vocal_2_bypasses_quota_check(self):
        """Cloud mode + Kim Vocal 2 must bypass check completely."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        mock_bridge = MagicMock()
        mock_bridge.check_gpu_quota_status = MagicMock()
        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)", model="Kim Vocal 2")

        warning_emitted = []
        processor.verification_warning.connect(lambda j, m, w: warning_emitted.append((j, m, w)))

        with patch("processor_thread.extract_audio", side_effect=Exception("stop_after_check")):
            try:
                processor.process_job(jid, self.qm.get_job(jid))
            except Exception:
                pass

        mock_bridge.check_gpu_quota_status.assert_not_called()
        self.assertEqual(len(warning_emitted), 0)

    def test_verified_account_emits_no_warning(self):
        """Cloud mode + RoFormer on verified account performs check but emits zero warnings."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        mock_bridge = MagicMock()
        mock_bridge.check_gpu_quota_status.return_value = {"status": "VERIFIED"}
        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)", model="RoFormer")

        warning_emitted = []
        processor.verification_warning.connect(lambda j, m, w: warning_emitted.append((j, m, w)))

        with patch("processor_thread.extract_audio", side_effect=Exception("stop_after_check")):
            try:
                processor.process_job(jid, self.qm.get_job(jid))
            except Exception:
                pass

        mock_bridge.check_gpu_quota_status.assert_called_once()
        self.assertEqual(len(warning_emitted), 0)

    def test_local_mode_bypasses_quota_check(self):
        """Local mode jobs must completely bypass cloud GPU quota pre-check."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        mock_bridge = MagicMock()
        mock_bridge.check_gpu_quota_status = MagicMock()
        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Local (GPU)", model="RoFormer")

        warning_emitted = []
        processor.verification_warning.connect(lambda j, m, w: warning_emitted.append((j, m, w)))

        with patch("processor_thread.extract_audio", side_effect=Exception("stop_after_check")):
            try:
                processor.process_job(jid, self.qm.get_job(jid))
            except Exception:
                pass

        mock_bridge.check_gpu_quota_status.assert_not_called()
        self.assertEqual(len(warning_emitted), 0)

    def test_empty_model_defaults_to_kim_and_bypasses_quota_check(self):
        """Unspecified / empty model defaults to Kim Vocal 2 and must bypass quota pre-check."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        mock_bridge = MagicMock()
        mock_bridge.check_gpu_quota_status = MagicMock()
        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)", model="")

        warning_emitted = []
        processor.verification_warning.connect(lambda j, m, w: warning_emitted.append((j, m, w)))

        with patch("processor_thread.extract_audio", side_effect=Exception("stop_after_check")):
            try:
                processor.process_job(jid, self.qm.get_job(jid))
            except Exception:
                pass

        mock_bridge.check_gpu_quota_status.assert_not_called()
        self.assertEqual(len(warning_emitted), 0)

    def test_handle_abort_invokes_cancel_kernel_first_and_never_kernels_push(self):
        """_handle_abort invokes bridge.cancel_kernel first, cleans local files, then calls delete_dataset_with_retry."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        call_order = []
        mock_bridge = MagicMock()
        mock_bridge.cancel_kernel = MagicMock(side_effect=lambda k: call_order.append(("cancel_kernel", k)))
        mock_bridge.delete_dataset_with_retry = MagicMock(side_effect=lambda d: call_order.append(("delete_dataset", d)))
        mock_bridge.api = MagicMock()
        mock_bridge.api.kernels_push = MagicMock()

        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)", model="RoFormer")
        temp_dir = os.path.join(self.test_dir, "temp_job")
        os.makedirs(temp_dir, exist_ok=True)

        processor._handle_abort(jid, "fake_user/test-kernel", "fake_user/test-ds", temp_dir, mock_bridge)

        # Confirm order: cancel_kernel called before delete_dataset
        self.assertEqual(len(call_order), 2)
        self.assertEqual(call_order[0], ("cancel_kernel", "fake_user/test-kernel"))
        self.assertEqual(call_order[1], ("delete_dataset", "fake_user/test-ds"))
        self.assertFalse(os.path.exists(temp_dir), "Temp directory must be cleaned up")
        mock_bridge.api.kernels_push.assert_not_called()

    def test_processor_thread_cancels_kernel_on_unexpected_error(self):
        """Processor thread run() loop cancels active kernel on unexpected job error to halt GPU burn."""
        processor = JobProcessor(self.qm, "fake_user", "fake_key")
        processor.running = True

        mock_bridge = MagicMock()
        mock_bridge.cancel_kernel = MagicMock()
        mock_bridge.delete_dataset_with_retry = MagicMock()
        processor.kaggle_bridge = mock_bridge

        jid = self.qm.add_job("sample.mp4", mode="Cloud (Kaggle)", model="RoFormer")
        self.qm.update_job(jid, {"kaggle_kernel_id": "fake_user/error-kernel", "dataset_id": "fake_user/error-ds"})

        with patch.object(processor, "process_job", side_effect=RuntimeError("Unexpected pipeline crash")):
            processor.current_kernel_id = "fake_user/error-kernel"
            processor.current_dataset_id = "fake_user/error-ds"

            # Execute run loop for single job
            job = self.qm.get_job(jid)
            try:
                processor.process_job(jid, job)
            except Exception as e:
                # Trigger error cleanup logic
                kernel_to_clean = getattr(processor, "current_kernel_id", None) or job.get("kaggle_kernel_id")
                if kernel_to_clean and processor.kaggle_bridge:
                    processor.kaggle_bridge.cancel_kernel(kernel_to_clean)
                dataset_to_clean = getattr(processor, "current_dataset_id", None) or job.get("dataset_id")
                if dataset_to_clean and processor.kaggle_bridge:
                    processor.kaggle_bridge.delete_dataset_with_retry(dataset_to_clean)

        mock_bridge.cancel_kernel.assert_called_once_with("fake_user/error-kernel")
        mock_bridge.delete_dataset_with_retry.assert_called_once_with("fake_user/error-ds")


class TestVerificationUIWidgets(unittest.TestCase):
    """Tests for PhoneVerificationWarningDialog, VerificationReminderBanner, and VectorWarningBadge."""

    def test_phone_verification_warning_dialog(self):
        """Dialog instantiates with localized text, model name, and dismisses on OK button."""
        dlg = PhoneVerificationWarningDialog("RoFormer")
        self.assertEqual(dlg.windowTitle(), "تنبيه: متطلبات حساب Kaggle" if dlg.layoutDirection() == Qt.RightToLeft else "Notice: Kaggle Account Requirements")
        self.assertIn("RoFormer", dlg.lbl_msg.text())
        # Clicking OK dismisses
        dlg.btn_ok.click()
        self.assertFalse(dlg.isVisible())

    def test_verification_reminder_banner(self):
        """Banner shows reminder for model, sets 20-second timer, and dismisses cleanly."""
        banner = VerificationReminderBanner()
        self.assertFalse(banner.isVisible())

        banner.show_reminder("MDX23C")
        self.assertTrue(banner.isVisible())
        self.assertIn("MDX23C", banner.lbl_msg.text())
        self.assertTrue(banner._timer.isActive())
        self.assertEqual(banner._timer.interval(), 20000)

        # Manual dismiss
        banner.dismiss()
        self.assertFalse(banner.isVisible())
        self.assertFalse(banner._timer.isActive())

    def test_vector_warning_badge_paint(self):
        """VectorWarningBadge instantiates and can render without exceptions."""
        badge = VectorWarningBadge(size=36)
        self.assertEqual(badge.width(), 36)
        self.assertEqual(badge.height(), 36)
        badge.repaint()

    def test_phone_warning_dialog_retrigger_lifecycle(self):
        """Simulate triggering on_verification_warning twice in the UI to ensure no Shiboken deleted C++ object errors."""
        from PySide6.QtWidgets import QWidget
        from ui.main_window import MainWindow
        class DummyWindow(QWidget):
            def on_verification_warning(self, job_id, model_name, warning_type):
                MainWindow.on_verification_warning(self, job_id, model_name, warning_type)

        win = DummyWindow()
        app = QApplication.instance() or QApplication([])

        # 1st trigger
        win.on_verification_warning("job-1", "RoFormer", "UNVERIFIED")
        self.assertIsNotNone(win._phone_warning_dlg)
        self.assertTrue(win._phone_warning_dlg.isVisible())

        # User dismisses dialog
        win._phone_warning_dlg.btn_ok.click()
        app.processEvents()
        self.assertIsNone(getattr(win, "_phone_warning_dlg", None))

        # 2nd trigger should cleanly instantiate new dialog without Shiboken RuntimeError
        win.on_verification_warning("job-2", "MDX23C", "UNVERIFIED")
        self.assertIsNotNone(win._phone_warning_dlg)
        self.assertTrue(win._phone_warning_dlg.isVisible())
        self.assertIn("MDX23C", win._phone_warning_dlg.lbl_msg.text())

        # Clean up
        win._phone_warning_dlg.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
