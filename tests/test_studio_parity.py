import os
import sys
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# Ensure src/root is in path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
os.environ["APPDATA"] = os.path.join(root_dir, ".test_appdata")

from ui.theme import Theme, ThemeMode
from ui.components import RotatingSpinner, SidebarNavButton, SidebarThemeButton
from ui.queue_widgets import SegmentedPillSwitcher
from ui.job_widget import JobWidget
from ui.job_queue_section import JobQueueSection
from ui.main_window import MainWindow, set_native_window_theme
from config_manager import ConfigManager
from queue_manager import QueueManager
from i18n import t, set_language

app = QApplication.instance() or QApplication(sys.argv)

class TestStudioParity(unittest.TestCase):
    def setUp(self):
        self.config = ConfigManager()
        self.queue_mgr = QueueManager()
        for jid in list(self.queue_mgr.get_all_jobs().keys()):
            self.queue_mgr.delete_job(jid)
        set_language("en")

    def tearDown(self):
        from update_checker import stop_all_active_checkers
        stop_all_active_checkers()
        app = QApplication.instance()
        if app:
            app.closeAllWindows()
            app.processEvents()

    def test_rotating_spinner_lifecycle(self):
        spinner = RotatingSpinner(14)
        self.assertFalse(spinner._is_spinning)
        self.assertFalse(spinner._timer.isActive())

        spinner.start()
        self.assertTrue(spinner._is_spinning)
        self.assertTrue(spinner._timer.isActive())

        # Advance angle
        initial_angle = spinner._angle
        spinner._rotate()
        self.assertNotEqual(spinner._angle, initial_angle)

        spinner.stop()
        self.assertFalse(spinner._is_spinning)
        self.assertFalse(spinner._timer.isActive())

    def test_job_widget_3zone_and_spinner(self):
        job_data = {
            "original_media": "C:/fake/audio/Podcast_Ep_01.mp4",
            "duration": 185.0,
            "status": "PROCESSING_CLOUD",
            "model": "RoFormer-T4",
            "probe_result": {"audio_streams": [{"channels": 2}]}
        }
        widget = JobWidget("job_1", job_data, mode="Cloud (Kaggle)")
        widget.show()
        
        # In running state:
        self.assertTrue(widget.spinner._is_spinning)
        self.assertFalse(widget.progress.isHidden())
        self.assertTrue(widget.btn_show_folder.isHidden())
        self.assertFalse(widget.sep3.isHidden())
        self.assertFalse(widget.lbl_eta.isHidden())
        self.assertIn("RoFormer-T4", widget.lbl_meta_model.text())
        self.assertEqual(widget.lbl_meta_dur.text(), "00:00")

        # Test live tick
        widget._on_timer_tick()
        self.assertEqual(widget.lbl_meta_dur.text(), "00:01")

        # Transition to COMPLETED
        widget.job_dict["final_elapsed_seconds"] = 185
        widget.update_status("COMPLETED")
        self.assertEqual(widget.lbl_meta_dur.text(), "03:05")
        self.assertFalse(spinner := widget.spinner._is_spinning)
        self.assertTrue(widget.progress.isHidden())
        self.assertFalse(widget.btn_show_folder.isHidden())
        self.assertFalse(widget.btn_show_folder.icon().isNull())
        self.assertIn("Show in Folder", widget.btn_show_folder.text())
        self.assertEqual(widget.lbl_eta.text(), "Saved to Output")
        self.assertFalse(widget.sep3.isHidden())

        # Transition to ABORTED
        widget.update_status("ABORTED")
        self.assertFalse(widget.spinner._is_spinning)
        self.assertTrue(widget.lbl_eta.isHidden())
        self.assertTrue(widget.sep3.isHidden())  # NO dangling separator!
        widget.timer.stop()
        widget.spinner.stop()
        widget.close()

    def test_segmented_capsule_switcher(self):
        switcher = SegmentedPillSwitcher()
        self.assertEqual(switcher.height(), 30)
        switcher.set_counts(5, 2, 3)
        self.assertEqual(switcher.btn_all.text(), "All 5")
        self.assertEqual(switcher.btn_active.text(), "In Progress 2")
        self.assertEqual(switcher.btn_completed.text(), "Completed 3")

    def test_job_queue_section_toolbar_and_overflow(self):
        section = JobQueueSection("Cloud (Kaggle)", self.queue_mgr, self.config)
        self.assertEqual(section.btn_select_mode.text(), "Select")
        self.assertEqual(section.btn_clear_history.text(), "Clear")
        self.assertEqual(section.lbl_view.text(), "View:")
        self.assertIn("🌱", section.btn_mariam.text())
        self.assertIn("Mariam Initiative", section.btn_mariam.text())

        # Verify subtle divider exists in ghost toolbar
        self.assertIsNotNone(section.sep_ghost1)

    def test_no_group_header_badges(self):
        # Adding completed and active jobs should list cards directly without banner header badges
        jid1 = self.queue_mgr.add_job("C:/fake/vid1.mp4", mode="Cloud (Kaggle)")
        self.queue_mgr.update_job(jid1, {"status": "COMPLETED"})
        jid2 = self.queue_mgr.add_job("C:/fake/vid2.mp4", mode="Cloud (Kaggle)")
        self.queue_mgr.update_job(jid2, {"status": "PROCESSING_CLOUD"})
        section = JobQueueSection("Cloud (Kaggle)", self.queue_mgr, self.config)
        section.refresh_list()
        
        # Verify exactly 2 items in list (the 2 JobWidgets), no StatusGroupHeader items!
        self.assertEqual(section.list_widget.count(), 2)
        for i in range(section.list_widget.count()):
            item = section.list_widget.item(i)
            widget = section.list_widget.itemWidget(item)
            self.assertIsInstance(widget, JobWidget)

    def test_theme_button_render_safety(self):
        btn = SidebarThemeButton(ThemeMode.LIGHT)
        from PySide6.QtGui import QPixmap
        pix = QPixmap(btn.size())
        btn.render(pix)  # Light mode crescent
        btn.set_theme_mode(ThemeMode.DARK)
        btn.render(pix)  # Dark mode radiant sun

    def test_job_widget_tooltip_and_breathing_room(self):
        job_data = {"original_media": "C:/fake/path/audio.mp4", "duration": 120.0, "status": "PENDING"}
        widget = JobWidget("job_test", job_data)
        # 1. Tooltip must be completely removed
        self.assertEqual(widget.lbl_name.toolTip(), "")
        # 2. Vertical breathing room
        self.assertGreaterEqual(widget.sizeHint().height(), 118)
        self.assertGreaterEqual(widget.frame.minimumHeight(), 108)

    def test_worker_polling_message_localization(self):
        from i18n import translate_worker_message
        # In Arabic:
        set_language("ar")
        self.assertEqual(translate_worker_message("Kaggle Status: RUNNING (Polling...)"), t("msg_isolating_vocals"))
        self.assertEqual(translate_worker_message("Kaggle Status: QUEUED (Polling...)"), t("msg_waiting_kaggle_gpu"))
        # In English:
        set_language("en")
        self.assertEqual(translate_worker_message("Kaggle Status: RUNNING (Polling...)"), "Isolating vocals with AI...")
        self.assertEqual(translate_worker_message("Kaggle Status: QUEUED (Polling...)"), "Waiting for Kaggle GPU processing...")

    def test_header_divider_and_capsule_switcher(self):
        from PySide6.QtWidgets import QFrame
        section = JobQueueSection("Cloud (Kaggle)", self.queue_mgr, self.config)
        # Separator line exists
        self.assertIsNotNone(section.header_divider)
        self.assertEqual(section.header_divider.height(), 1)
        # Capsule container frame
        self.assertIsInstance(section.switcher, QFrame)
        self.assertTrue(section.switcher.testAttribute(Qt.WA_StyledBackground))

    def test_native_window_theme_safe_call(self):
        # Must execute without exception even in headless/mock environments
        window = MainWindow()
        set_native_window_theme(window, True)
        set_native_window_theme(window, False)
        if hasattr(window, 'local_thread') and window.local_thread:
            window.local_thread.stop()
            window.local_thread.wait()
        if hasattr(window, 'cloud_thread') and window.cloud_thread:
            window.cloud_thread.stop()
            window.cloud_thread.wait()
        window.close()

if __name__ == "__main__":
    unittest.main()
