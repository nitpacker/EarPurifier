import unittest
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from ui.job_widget import (
    JobWidget,
    get_model_rtf,
    compute_stage_estimates,
    format_eta_time
)
from i18n import t, set_language


class TestETACalculation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if not cls.app:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        set_language("en")

    def test_01_model_rtf_calibration(self):
        """Verify empirical RTF and overhead for all supported model architectures."""
        # Kim Vocal 2 (~7.5x real-time)
        rtf, ovh = get_model_rtf("Kim Vocal 2")
        self.assertAlmostEqual(rtf, 0.135, places=3)
        self.assertEqual(ovh, 45.0)

        # MDX23C (~3.7x real-time)
        rtf, ovh = get_model_rtf("MDX23C-8KFFT-InstVoc_HQ.ckpt")
        self.assertAlmostEqual(rtf, 0.270, places=3)
        self.assertEqual(ovh, 50.0)

        # Band-Split RoFormer (~1.45x real-time)
        rtf, ovh = get_model_rtf("model_bs_roformer_ep_317_sdr_12.9755.ckpt")
        self.assertAlmostEqual(rtf, 0.680, places=3)
        self.assertEqual(ovh, 55.0)

        # Unknown / default fallback
        rtf, ovh = get_model_rtf("Unknown_Custom_Model")
        self.assertAlmostEqual(rtf, 0.270, places=3)
        self.assertEqual(ovh, 50.0)

    def test_02_hansa_user_video_estimate_parity(self):
        """Verify that a 24.5m video with Kim Vocal 2 estimates ~5.5m instead of the broken 39m."""
        duration = 1469.4  # Exactly the Hansa video duration in seconds (~24.5 mins)
        model = "Kim Vocal 2"

        estimates = compute_stage_estimates(duration, model)

        # Individual stages check
        self.assertGreaterEqual(estimates["EXTRACTING"], 10.0)
        self.assertLessEqual(estimates["EXTRACTING"], 12.0)

        self.assertGreaterEqual(estimates["UPLOADING"], 40.0)
        self.assertLessEqual(estimates["UPLOADING"], 45.0)

        # Cloud separation: 45s overhead + (0.135 * 1469.4 = 198.3s) = ~243s (~4m)
        self.assertGreaterEqual(estimates["PROCESSING_CLOUD"], 235.0)
        self.assertLessEqual(estimates["PROCESSING_CLOUD"], 250.0)

        self.assertGreaterEqual(estimates["DOWNLOADING"], 18.0)
        self.assertLessEqual(estimates["DOWNLOADING"], 22.0)

        self.assertGreaterEqual(estimates["REMUXING"], 18.0)
        self.assertLessEqual(estimates["REMUXING"], 22.0)

        # Total cloud pipeline: ~335 seconds (~5m 35s)
        total_cloud = (
            estimates["EXTRACTING"] +
            estimates["UPLOADING"] +
            estimates["PROCESSING_CLOUD"] +
            estimates["DOWNLOADING"] +
            estimates["REMUXING"]
        )
        self.assertGreaterEqual(total_cloud, 320.0)
        self.assertLessEqual(total_cloud, 360.0)
        # Old broken formula was 150 + 1469.4 * 1.5 = 2354s (~39 minutes)
        self.assertLess(total_cloud, 600.0, "ETA must be well under 10 minutes, matching the 6:24 actual runtime.")

    def test_03_format_eta_time(self):
        """Verify localized formatting for seconds, minutes, hours, and anytime-now fallback."""
        set_language("en")
        self.assertEqual(format_eta_time(0), "ETA: Anytime now...")
        self.assertEqual(format_eta_time(25), "ETA: ~25s")
        self.assertEqual(format_eta_time(335), "ETA: ~5m 35s")
        self.assertEqual(format_eta_time(3665), "ETA: ~1h 1m")

        set_language("ar")
        self.assertEqual(format_eta_time(0), "الوقت المتبقي: على وشك الانتهاء...")
        self.assertEqual(format_eta_time(25), "الوقت المتبقي: ~25 ث")
        self.assertEqual(format_eta_time(335), "الوقت المتبقي: ~5 د 35 ث")
        self.assertEqual(format_eta_time(3665), "الوقت المتبقي: ~1 س 1 د")

    def test_04_job_widget_cloud_stage_transitions(self):
        """Verify dynamic stage re-estimation and clamping in JobWidget."""
        set_language("en")
        job_data = {
            "original_media": "C:/test/hansa.mp4",
            "duration": 1469.4,
            "model": "Kim Vocal 2",
            "status": "PENDING"
        }
        widget = JobWidget("job-123", job_data, mode="Cloud (Kaggle)")
        self.assertEqual(widget.lbl_eta.text(), "In Queue")

        # Transition to EXTRACTING
        widget.update_status("EXTRACTING")
        self.assertFalse(widget.lbl_eta.isHidden())
        self.assertFalse(widget.sep3.isHidden())
        initial_eta = widget.remaining_seconds
        self.assertGreaterEqual(initial_eta, 320)
        self.assertLessEqual(initial_eta, 360)

        # Transition to PROCESSING_CLOUD
        widget.update_status("PROCESSING_CLOUD")
        cloud_eta = widget.remaining_seconds
        self.assertLess(cloud_eta, initial_eta)

        # Simulate cloud separation finishing early: transition to DOWNLOADING
        widget.update_status("DOWNLOADING")
        # DOWNLOADING + REMUXING should be ~40s total
        self.assertLessEqual(widget.remaining_seconds, 45)
        self.assertGreaterEqual(widget.remaining_seconds, 30)

        # Transition to REMUXING
        widget.update_status("REMUXING")
        self.assertLessEqual(widget.remaining_seconds, 25)

        # Transition to COMPLETED
        widget.update_status("COMPLETED")
        self.assertEqual(widget.lbl_eta.text(), "Saved to Output")
        widget.deleteLater()

    def test_05_job_widget_local_mode_progress(self):
        """Verify local mode ETA visibility, progress bar updating, and percent-based extrapolation."""
        set_language("en")
        job_data = {
            "original_media": "C:/test/sample.mp4",
            "duration": 600.0,
            "model": "Kim Vocal 2",
            "status": "PENDING"
        }
        widget = JobWidget("job-456", job_data, mode="Local (GPU)")
        widget.update_status("PROCESSING_LOCAL")

        self.assertFalse(widget.lbl_eta.isHidden())
        self.assertFalse(widget.sep3.isHidden())

        # Simulate local engine outputting 50% after 20 seconds
        widget.stage_elapsed = 20
        widget.update_message("Processing audio... 50%")

        # Progress bar should update to 50
        self.assertEqual(widget.progress.value(), 50)
        self.assertEqual(widget.progress.maximum(), 100)

        # Remaining inference = 20 * (100 - 50) / 50 = 20s. Remux ~ 11s. Total ~ 31s
        self.assertGreaterEqual(widget.remaining_seconds, 28)
        self.assertLessEqual(widget.remaining_seconds, 35)

        widget.deleteLater()

    def test_06_timer_tick_monotonic_decrement(self):
        """Verify 1-second countdown and anytime fallback without going negative."""
        job_data = {
            "original_media": "C:/test/sample.mp4",
            "duration": 100.0,
            "model": "Kim Vocal 2",
            "status": "PROCESSING_CLOUD"
        }
        widget = JobWidget("job-789", job_data, mode="Cloud (Kaggle)")
        widget.remaining_seconds = 2

        widget._on_timer_tick()
        self.assertEqual(widget.remaining_seconds, 1)

        widget._on_timer_tick()
        self.assertEqual(widget.remaining_seconds, 0)
        self.assertEqual(widget.lbl_eta.text(), "ETA: Anytime now...")

        # Further ticks should keep it at 0 and anytime text
        widget._on_timer_tick()
        self.assertEqual(widget.remaining_seconds, 0)
        self.assertEqual(widget.lbl_eta.text(), "ETA: Anytime now...")

        widget.deleteLater()

    def test_07_zero_duration_fallback(self):
        """Verify that jobs without known duration show 'Calculating...' rather than crashing or showing 0s."""
        job_data = {
            "original_media": "C:/test/sample.mp4",
            "duration": 0.0,
            "model": "Kim Vocal 2",
            "status": "EXTRACTING"
        }
        widget = JobWidget("job-000", job_data, mode="Cloud (Kaggle)")
        self.assertEqual(widget.lbl_eta.text(), "ETA: Calculating...")

        # Update duration via update_state
        widget.update_state({"duration": 300.0})
        self.assertGreater(widget.remaining_seconds, 0)
        self.assertIn("ETA:", widget.lbl_eta.text())

        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
