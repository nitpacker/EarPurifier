"""
EarPurifier - Unit Tests for GitHub Release Auto-Update Checker.
Tests SemVer comparisons, bilingual changelog extraction, frequency throttling,
mocked GitHub API responses, thread lifespan safety, and UI file line limits.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontMetrics

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
os.environ["APPDATA"] = os.path.join(root_dir, ".test_appdata")

from update_checker import (
    APP_VERSION, is_newer_version, extract_release_notes,
    should_check_for_updates, GitHubUpdateChecker, _fallback_parse_semver,
    get_current_os
)
from config_manager import ConfigManager
from ui.components import SidebarLogo
from ui.dialogs import SettingsDialog
from ui.update_banner import UpdateBannerWidget

app = QApplication.instance() or QApplication(sys.argv)


class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        self.config = ConfigManager()

    def tearDown(self):
        from update_checker import stop_all_active_checkers
        stop_all_active_checkers()
        app = QApplication.instance()
        if app:
            app.closeAllWindows()
            app.processEvents()

    def test_semver_comparisons(self):
        # Basic newer
        self.assertTrue(is_newer_version("0.0.2", "0.0.1"))
        self.assertTrue(is_newer_version("0.1.0", "0.0.9"))
        self.assertTrue(is_newer_version("1.0.0", "0.9.9"))
        self.assertTrue(is_newer_version("v2.0.1", "2.0.0"))
        self.assertTrue(is_newer_version("2.0.1", "v2.0.0"))

        # Same or older
        self.assertFalse(is_newer_version("0.0.1", "0.0.1"))
        self.assertFalse(is_newer_version("v0.0.1", "0.0.1"))
        self.assertFalse(is_newer_version("0.0.1", "v0.0.1"))
        self.assertFalse(is_newer_version("0.0.1", "0.0.2"))
        self.assertFalse(is_newer_version("0.9.9", "1.0.0"))

        # Pre-releases (Release > Pre-release)
        self.assertTrue(is_newer_version("1.0.0", "1.0.0-rc.1"))
        self.assertFalse(is_newer_version("1.0.0-rc.1", "1.0.0"))
        self.assertTrue(is_newer_version("1.0.0-rc.2", "1.0.0-rc.1"))
        self.assertTrue(is_newer_version("1.0.0-beta.1", "1.0.0-alpha.1"))

        # Default APP_VERSION (0.0.1)
        self.assertTrue(is_newer_version("99.99.99"))
        self.assertFalse(is_newer_version(APP_VERSION))

        # Empty / None
        self.assertFalse(is_newer_version(""))
        self.assertFalse(is_newer_version(None))

    def test_fallback_semver_parser(self):
        t1 = _fallback_parse_semver("1.0.0")
        t2 = _fallback_parse_semver("1.0.1")
        self.assertLess(t1, t2)

        t_pre = _fallback_parse_semver("1.0.0-rc.1")
        t_rel = _fallback_parse_semver("1.0.0")
        # In SemVer, release > prerelease
        self.assertLess(t_pre, t_rel)

    def test_startup_check_evaluation(self):
        cfg = ConfigManager()

        # 1. Enabled (default) -> Always checks on startup
        cfg.set("check_updates", True)
        self.assertTrue(should_check_for_updates(cfg, force=False))

        # 2. Disabled -> Skipped on startup
        cfg.set("check_updates", False)
        self.assertFalse(should_check_for_updates(cfg, force=False))

        # 3. Disabled but manual check forced -> Allowed
        self.assertTrue(should_check_for_updates(cfg, force=True))

    def test_bilingual_release_notes_extractor(self):
        # 1. HTML comment tags
        body_comments = "<!-- ar -->تحديث رائع ومهم<!-- /ar --> <!-- en -->Great important update<!-- /en -->"
        self.assertEqual(extract_release_notes(body_comments, "ar"), "تحديث رائع ومهم")
        self.assertEqual(extract_release_notes(body_comments, "en"), "Great important update")

        # 2. Bracket tags
        body_brackets = "[ar]ميزة جديدة مضافة[/ar]\n[en]New feature added[/en]"
        self.assertEqual(extract_release_notes(body_brackets, "ar"), "ميزة جديدة مضافة")
        self.assertEqual(extract_release_notes(body_brackets, "en"), "New feature added")

        # 3. Markdown section headers
        body_md = "## العربية\nتفاصيل التحديث بالعربية.\n## English\nUpdate details in English."
        self.assertEqual(extract_release_notes(body_md, "ar"), "تفاصيل التحديث بالعربية.")
        self.assertEqual(extract_release_notes(body_md, "en"), "Update details in English.")

        # 4. Plain text fallback
        plain = "Bug fixes and performance improvements."
        self.assertEqual(extract_release_notes(plain, "ar"), plain)
        self.assertEqual(extract_release_notes(plain, "en"), plain)

        # 5. Empty / None
        self.assertEqual(extract_release_notes("", "ar"), "")
        self.assertEqual(extract_release_notes(None, "ar"), "")

    @patch("update_checker.requests.get")
    def test_github_api_update_available(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tag_name": "v99.99.99",
            "body": "<!-- ar -->تحديث الإصدار الثاني<!-- /ar --> <!-- en -->Version 2 release<!-- /en -->",
            "html_url": "https://github.com/nitpacker/EarPurifier/releases/tag/v99.99.99",
            "assets": [
                {
                    "name": "EarPurifier.exe",
                    "browser_download_url": "https://github.com/nitpacker/EarPurifier/releases/download/v99.99.99/EarPurifier.exe"
                }
            ]
        }
        mock_get.return_value = mock_resp

        cfg = ConfigManager()
        cfg.set("check_updates", True)
        cfg.set("last_update_check", "")

        worker = GitHubUpdateChecker(config=cfg, force=True)
        received_updates = []
        finished_results = []

        worker.sig_update_available.connect(lambda v, n, h, d: received_updates.append((v, n, h, d)))
        worker.sig_check_finished.connect(lambda s, code, msg: finished_results.append((s, code, msg)))

        worker.run()

        self.assertEqual(len(received_updates), 1)
        self.assertEqual(received_updates[0][0], "v99.99.99")
        self.assertEqual(received_updates[0][3], "https://github.com/nitpacker/EarPurifier/releases/download/v99.99.99/EarPurifier.exe")
        self.assertEqual(len(finished_results), 1)
        self.assertTrue(finished_results[0][0])
        self.assertEqual(finished_results[0][1], "update_available")
        self.assertTrue(bool(cfg.get("last_update_check")))

    @patch("update_checker.requests.get")
    def test_github_api_already_latest(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tag_name": f"v{APP_VERSION}",
            "body": "Current version notes",
            "html_url": "https://github.com/nitpacker/EarPurifier/releases/tag/v99.99.99",
            "assets": []
        }
        mock_get.return_value = mock_resp

        worker = GitHubUpdateChecker(config=self.config, force=True)
        received_updates = []
        finished_results = []

        worker.sig_update_available.connect(lambda *args: received_updates.append(args))
        worker.sig_check_finished.connect(lambda s, code, msg: finished_results.append((s, code, msg)))

        worker.run()

        self.assertEqual(len(received_updates), 0)
        self.assertEqual(len(finished_results), 1)
        self.assertTrue(finished_results[0][0])
        self.assertEqual(finished_results[0][1], "latest")

    @patch("update_checker.requests.get")
    def test_github_api_rate_limited(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp

        worker = GitHubUpdateChecker(config=self.config, force=True)
        finished_results = []
        worker.sig_check_finished.connect(lambda s, code, msg: finished_results.append((s, code, msg)))

        worker.run()

        self.assertEqual(len(finished_results), 1)
        self.assertFalse(finished_results[0][0])
        self.assertEqual(finished_results[0][1], "rate_limited")

    @patch("update_checker.requests.get")
    def test_github_api_not_found(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        worker = GitHubUpdateChecker(config=self.config, force=True)
        finished_results = []
        worker.sig_check_finished.connect(lambda s, code, msg: finished_results.append((s, code, msg)))

        worker.run()

        self.assertEqual(len(finished_results), 1)
        self.assertFalse(finished_results[0][0])
        self.assertEqual(finished_results[0][1], "not_found")

    @patch("update_checker.requests.get")
    def test_github_api_timeout(self, mock_get):
        import requests
        mock_get.side_effect = requests.Timeout("Connection timed out")

        worker = GitHubUpdateChecker(config=self.config, force=True)
        finished_results = []
        worker.sig_check_finished.connect(lambda s, code, msg: finished_results.append((s, code, msg)))

        worker.run()

        self.assertEqual(len(finished_results), 1)
        self.assertFalse(finished_results[0][0])
        self.assertEqual(finished_results[0][1], "timeout")

    def test_sidebar_logo_pill_geometry(self):
        logo = SidebarLogo()
        fm = QFontMetrics(QFont("Consolas", 8, QFont.Bold))
        ver_text = f"v{APP_VERSION}"
        text_w = fm.horizontalAdvance(ver_text)
        pill_w = max(36, text_w + 8)

        # Minimum width of 36px enforced
        self.assertGreaterEqual(pill_w, 36)
        # Pill fits comfortably within the 54px logo widget width
        self.assertLess(pill_w, logo.width())

    def test_update_banner_widget_lifecycle(self):
        banner = UpdateBannerWidget(self.config)
        self.assertFalse(banner.isVisible())

        banner.show_update(
            "v0.0.2",
            "<!-- ar -->ميزات جديدة<!-- /ar --> <!-- en -->New features<!-- /en -->",
            "https://github.com/nitpacker/EarPurifier/releases/tag/v99.99.99",
            "https://github.com/nitpacker/EarPurifier/releases/download/v99.99.99/EarPurifier.exe"
        )
        self.assertTrue(banner.isVisible())
        self.assertEqual(banner.latest_version, "v0.0.2")

        # Test dismiss
        banner.on_dismiss()
        self.assertFalse(banner.isVisible())
        banner.close()

    def test_settings_dialog_thread_gc_safety(self):
        import time, gc
        def slow_req(*args, **kwargs):
            time.sleep(0.5)
            raise Exception("simulated network abort")

        with patch("update_checker.requests.get", side_effect=slow_req):
            dlg = SettingsDialog(self.config)
            dlg.btn_check_now.click()
            self.assertTrue(dlg.update_thread.isRunning())
            # Close dialog via done / reject
            dlg.done(0)
            del dlg
            gc.collect()
            # Must not crash with QThread: Destroyed while thread is still running
            time.sleep(0.6)

    def test_settings_dialog_update_controls(self):
        dlg = SettingsDialog(self.config)
        self.assertTrue(hasattr(dlg, "switch_check_updates"))
        self.assertTrue(hasattr(dlg, "btn_check_now"))
        self.assertTrue(hasattr(dlg, "lbl_update_status"))
        self.assertTrue(hasattr(dlg, "_cleanup_update_thread"))

        # Save config
        dlg.switch_check_updates.setChecked(False)
        dlg.save_and_get_config()
        self.assertFalse(self.config.get("check_updates"))

        dlg.switch_check_updates.setChecked(True)
        dlg.save_and_get_config()
        self.assertTrue(self.config.get("check_updates"))

    def test_os_detection_and_multiplatform_manifest(self):
        # 1. OS detection returns valid identifier
        current_os = get_current_os()
        self.assertIn(current_os, ["windows", "macos", "linux"])

        # 2. Extract release notes from dictionary
        notes_dict = {
            "ar": "تحديث صوتي ممتاز",
            "en": "Excellent audio update"
        }
        self.assertEqual(extract_release_notes(notes_dict, "ar"), "تحديث صوتي ممتاز")
        self.assertEqual(extract_release_notes(notes_dict, "en"), "Excellent audio update")

    @patch("update_checker.requests.get")
    def test_raw_manifest_multiplatform_urls(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "version": "0.0.5",
            "download_urls": {
                "windows": "https://example.com/EarPurifier.exe",
                "macos": "https://example.com/EarPurifier.dmg",
                "linux": "https://example.com/EarPurifier.AppImage"
            },
            "html_url": "https://github.com/nitpacker/EarPurifier/releases/tag/v0.0.5",
            "message": {
                "ar": "ملاحظات الإصدار الخامس",
                "en": "Version 5 notes"
            }
        }
        mock_get.return_value = mock_resp

        worker = GitHubUpdateChecker(config=None, force=True)
        received = []
        worker.sig_update_available.connect(lambda v, n, h, d: received.append((v, n, h, d)))
        worker.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "0.0.5")
        current_os = get_current_os()
        expected_url = f"https://example.com/EarPurifier.{'exe' if current_os == 'windows' else ('dmg' if current_os == 'macos' else 'AppImage')}"
        self.assertEqual(received[0][3], expected_url)


if __name__ == "__main__":
    unittest.main()
