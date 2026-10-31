import os
import sys
import shutil
import unittest

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Redirect APPDATA to workspace directory for sandboxed tests
test_appdata = os.path.join(root_dir, ".test_appdata")
os.environ["APPDATA"] = test_appdata
os.makedirs(test_appdata, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from config_manager import ConfigManager
from queue_manager import QueueManager
import i18n
from ui.theme import Theme, ThemeMode, get_asset_path, get_checkbox_qss
from ui.components import (
    SidebarLogo, SidebarNavButton, SidebarThemeButton,
    EngineTelemetryPill, ModernToggleSwitch, CleanCloseButton, VectorAlertBadge
)
from ui.queue_widgets import (
    SegmentedPillSwitcher, FloatingBatchDock, DropZoneWidget
)
from ui.dialogs import SettingsDialog, DeleteConfirmDialog, AudioTrackSelectDialog
from ui.job_widget import JobWidget
from ui.job_queue_section import JobQueueSection
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestUIOverhaul(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        # Cleanup test appdata
        if os.path.exists(test_appdata):
            try:
                shutil.rmtree(test_appdata, ignore_errors=True)
            except Exception:
                pass

    def test_01_line_count_ceiling(self):
        """Verify that every python file in ui/ is strictly under 600 lines."""
        ui_dir = os.path.join(root_dir, "ui")
        for fname in os.listdir(ui_dir):
            if fname.endswith(".py"):
                fpath = os.path.join(ui_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    lines = len(f.readlines())
                self.assertLess(lines, 600, f"File {fname} has {lines} lines, exceeding 600 line limit!")

    def test_02_theme_tokens_and_default(self):
        """Verify that Light Mode is default and tokens toggle seamlessly."""
        cfg = ConfigManager()
        default_theme = cfg.get("theme_mode", ThemeMode.LIGHT)
        self.assertEqual(default_theme, ThemeMode.LIGHT)

        Theme.set_mode(ThemeMode.LIGHT)
        self.assertEqual(Theme.get_token("CANVAS_BG"), "#f4f8f5")
        self.assertEqual(Theme.get_token("CARD_BG"), "#ffffff")

        Theme.set_mode(ThemeMode.DARK)
        self.assertEqual(Theme.get_token("CANVAS_BG"), "#0c1410")
        self.assertEqual(Theme.get_token("CARD_BG"), "#14211a")

        # Reset to light
        Theme.set_mode(ThemeMode.LIGHT)

    def test_03_checkbox_svg_asset_and_qss(self):
        """Verify crisp white checkmark SVG exists and is referenced in checkbox QSS."""
        svg_path = get_asset_path("check_white.svg")
        self.assertTrue(os.path.exists(svg_path), f"SVG asset missing at {svg_path}")
        qss = get_checkbox_qss("light")
        self.assertIn("check_white.svg", qss)
        self.assertIn("border: 1.5px solid", qss)

    def test_04_serene_telemetry_pill(self):
        """Verify telemetry pill is static when idle (no active timers) and breathes only when active."""
        pill = EngineTelemetryPill()
        self.assertFalse(pill.is_active)
        self.assertFalse(pill.breath_timer.isActive(), "Idle pill must NOT run a blinking timer!")

        pill.set_active_processing(True)
        self.assertTrue(pill.is_active)
        self.assertTrue(pill.breath_timer.isActive(), "Active processing pill must activate smooth breath timer.")

        pill.set_active_processing(False)
        self.assertFalse(pill.is_active)
        self.assertFalse(pill.breath_timer.isActive())

    def test_05_job_widget_3_zone_and_signals(self):
        """Verify JobWidget structured 3 zones, signals, and 'Show in Folder' button."""
        sample_job = {
            "original_media": "C:/Audio/Podcast_Episode_42.mp4",
            "mode": "Cloud (Kaggle)",
            "duration": 300.0,
            "model": "RoFormer",
            "status": "PENDING",
            "message": "Waiting in queue...",
            "added_at": "2026-10-31T05:00:00"
        }
        widget = JobWidget("job_test", sample_job, mode="Cloud (Kaggle)")
        widget.show()
        self.assertIsNotNone(widget.chk_select)
        self.assertIsNotNone(widget.lbl_name)
        self.assertIsNotNone(widget.meta_container)
        self.assertIsNotNone(widget.progress)
        self.assertIsNotNone(widget.btn_show_folder)

        # In pending state, show in folder is hidden
        self.assertTrue(widget.btn_show_folder.isHidden())

        # Transition to completed
        widget.update_status("COMPLETED")
        self.assertFalse(widget.btn_show_folder.isHidden(), "Show in folder button must appear when COMPLETED!")

        # Verify signals
        abort_called = []
        delete_called = []
        folder_called = []
        select_called = []

        widget.sig_abort_clicked.connect(lambda jid: abort_called.append(jid))
        widget.sig_delete_clicked.connect(lambda jid: delete_called.append(jid))
        widget.sig_open_folder_clicked.connect(lambda jid: folder_called.append(jid))
        widget.sig_selection_toggled.connect(lambda jid, chk: select_called.append((jid, chk)))

        widget.btn_abort.click()
        self.assertEqual(abort_called, ["job_test"])

        widget.btn_delete.click()
        self.assertEqual(delete_called, ["job_test"])

        widget.btn_show_folder.click()
        self.assertEqual(folder_called, ["job_test"])

        widget.set_selection_mode(True)
        widget.set_selected(True)
        self.assertTrue(any(c[1] is True for c in select_called))

    def test_06_queue_segmented_switcher_and_floating_dock(self):
        """Verify SegmentedPillSwitcher and FloatingBatchDock behavior."""
        cfg = ConfigManager()
        qm = QueueManager()
        section = JobQueueSection("Cloud (Kaggle)", qm, cfg)
        section.show()

        self.assertIsNotNone(section.switcher)
        self.assertIsNotNone(section.batch_dock)
        self.assertTrue(section.batch_dock.isHidden())

        # Toggle selection mode: dock appears
        section.toggle_selection_mode()
        self.assertFalse(section.batch_dock.isHidden())

        # Switch filter tab
        section.switcher.set_current_index(1)
        self.assertEqual(section.switcher.current_index, 1)

        section.toggle_selection_mode()
        self.assertTrue(section.batch_dock.isHidden())

    def test_07_dialogs_instantiation(self):
        """Verify Settings, DeleteConfirm, and AudioTrackSelect dialogs instantiate without error."""
        cfg = ConfigManager()
        dlg_set = SettingsDialog(cfg)
        self.assertIsNotNone(dlg_set.switch_logging)
        self.assertTrue(isinstance(dlg_set.switch_logging, ModernToggleSwitch))

        dlg_del = DeleteConfirmDialog(2, cfg)
        self.assertIsNotNone(dlg_del.chk_delete_files)

        streams = [{"index": 0, "codec_name": "aac", "channels": 2}]
        dlg_tr = AudioTrackSelectDialog(streams, "test.mp4")
        self.assertIsNotNone(dlg_tr.track_list)

    def test_08_main_window_theme_toggle_and_shutdown(self):
        """Verify MainWindow theme toggle and clean thread shutdown."""
        win = MainWindow()
        win.show()
        initial_theme = win.theme_mode

        # Click theme button
        win.btn_theme.click()
        new_theme = win.theme_mode
        self.assertNotEqual(initial_theme, new_theme)

        # Toggle back
        win.btn_theme.click()
        self.assertEqual(win.theme_mode, initial_theme)

        # Test bilingual toggle
        win.apply_language("en")
        self.assertEqual(win.language, "en")
        win.apply_language("ar")
        self.assertEqual(win.language, "ar")

        # Clean shutdown
        if hasattr(win, 'local_thread') and win.local_thread:
            win.local_thread.stop()
            win.local_thread.wait(1000)
        if hasattr(win, 'cloud_thread') and win.cloud_thread:
            win.cloud_thread.stop()
            win.cloud_thread.wait(1000)
        win.close()

    def test_09_i18n_translation_parity(self):
        """Verify 100% translation key parity between Arabic and English."""
        ar_keys = set(i18n.TRANSLATIONS["ar"].keys())
        en_keys = set(i18n.TRANSLATIONS["en"].keys())
        diff = ar_keys ^ en_keys
        self.assertEqual(len(diff), 0, f"Translation key mismatch: {diff}")


if __name__ == "__main__":
    unittest.main()
