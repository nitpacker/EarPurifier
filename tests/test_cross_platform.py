"""
Unit tests for cross-platform native support across Windows, macOS, and Linux.
Verifies OS detection, path resolution, credential encryption roundtrips,
subprocess safety guards, dependency paths, and typography fallback stacks.
"""

import os
import sys
import signal
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Redirect APPDATA to workspace directory for sandboxed tests
test_appdata = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".test_appdata")
os.makedirs(test_appdata, exist_ok=True)
os.environ["APPDATA"] = test_appdata

from system_utils import (
    get_current_os,
    get_app_data_dir,
    get_default_output_folder,
    get_subprocess_spawn_kwargs,
    reveal_in_file_manager,
    open_directory
)
from config_manager import _protect_secret, _unprotect_secret, ConfigManager
from process_tracker import kill_process_tree
from dependency_manager import DependencyManager
from ui.theme import Theme


class TestCrossPlatformSupport(unittest.TestCase):

    def test_os_detection(self):
        """get_current_os correctly categorizes win32, darwin, and linux."""
        with patch("sys.platform", "win32"):
            self.assertEqual(get_current_os(), "windows")
        with patch("sys.platform", "darwin"):
            self.assertEqual(get_current_os(), "macos")
        with patch("sys.platform", "linux"):
            self.assertEqual(get_current_os(), "linux")
        with patch("sys.platform", "linux2"):
            self.assertEqual(get_current_os(), "linux")

    def test_app_data_dir_resolution(self):
        """Verify standard data directory per platform: %APPDATA%, Application Support, XDG."""
        # Windows
        with patch("system_utils.get_current_os", return_value="windows"):
            with patch.dict(os.environ, {"APPDATA": test_appdata}):
                win_path = get_app_data_dir()
                self.assertTrue(win_path.startswith(test_appdata))
                self.assertTrue(win_path.endswith("EarPurifier"))

        # macOS
        with patch("system_utils.get_current_os", return_value="macos"):
            mac_path = get_app_data_dir()
            self.assertIn("Library/Application Support/EarPurifier", mac_path.replace("\\", "/"))

        # Linux (with XDG_DATA_HOME)
        with patch("system_utils.get_current_os", return_value="linux"):
            with tempfile.TemporaryDirectory() as tmp_xdg:
                with patch.dict(os.environ, {"XDG_DATA_HOME": tmp_xdg}):
                    linux_path = get_app_data_dir()
                    self.assertEqual(linux_path, os.path.join(tmp_xdg, "EarPurifier"))

    def test_default_output_folder(self):
        """Default output folder on macOS/Linux is ~/Desktop/EarPurifier_Output."""
        # macOS
        with patch("system_utils.get_current_os", return_value="macos"):
            mac_out = get_default_output_folder()
            self.assertTrue(mac_out.replace("\\", "/").endswith("Desktop/EarPurifier_Output"))

        # Linux
        with patch("system_utils.get_current_os", return_value="linux"):
            linux_out = get_default_output_folder()
            self.assertTrue(linux_out.replace("\\", "/").endswith("Desktop/EarPurifier_Output"))

        # Windows Source
        with patch("system_utils.get_current_os", return_value="windows"):
            with patch.object(sys, "frozen", False, create=True):
                win_out = get_default_output_folder()
                self.assertTrue(win_out.replace("\\", "/").endswith("Desktop/EarPurifier_Output"))

        # Windows Frozen
        with patch("system_utils.get_current_os", return_value="windows"):
            with patch.object(sys, "frozen", True, create=True):
                with tempfile.TemporaryDirectory() as tmp_exe_dir:
                    fake_exe = os.path.join(tmp_exe_dir, "EarPurifier.exe")
                    with patch.object(sys, "executable", fake_exe):
                        frozen_out = get_default_output_folder()
                        self.assertEqual(frozen_out, os.path.join(tmp_exe_dir, "output"))

    def test_encryption_roundtrip_posix_aes_gcm(self):
        """Verify AES-256-GCM encryption/decryption roundtrip for macOS and Linux."""
        test_secret = "KGAT_super_secret_kaggle_token_12345"
        with patch("sys.platform", "darwin"):
            enc = _protect_secret(test_secret)
            self.assertTrue(enc.startswith("enc:gcm:"), f"Expected enc:gcm: prefix, got {enc}")
            dec = _unprotect_secret(enc)
            self.assertEqual(dec, test_secret)

        with patch("sys.platform", "linux"):
            enc = _protect_secret(test_secret)
            self.assertTrue(enc.startswith("enc:gcm:"))
            dec = _unprotect_secret(enc)
            self.assertEqual(dec, test_secret)

    def test_encryption_roundtrip_windows_dpapi(self):
        """Verify DPAPI encryption on Windows if running natively on win32."""
        if sys.platform == "win32":
            test_secret = "win_native_secret_value_98765"
            enc = _protect_secret(test_secret)
            self.assertTrue(enc.startswith("enc:"))
            self.assertFalse(enc.startswith("enc:gcm:"))
            dec = _unprotect_secret(enc)
            self.assertEqual(dec, test_secret)

    def test_encryption_pass_through_empty_or_plain(self):
        """Empty or unencrypted strings pass through untouched."""
        self.assertEqual(_protect_secret(""), "")
        self.assertEqual(_unprotect_secret(""), "")
        self.assertEqual(_unprotect_secret("plain_text_key"), "plain_text_key")

    def test_subprocess_spawn_kwargs(self):
        """Verify platform-specific subprocess creation kwargs."""
        with patch("sys.platform", "win32"):
            kwargs = get_subprocess_spawn_kwargs()
            self.assertIn("creationflags", kwargs)

        with patch("sys.platform", "darwin"):
            kwargs = get_subprocess_spawn_kwargs()
            self.assertTrue(kwargs.get("start_new_session"))

        with patch("sys.platform", "linux"):
            kwargs = get_subprocess_spawn_kwargs()
            self.assertTrue(kwargs.get("start_new_session"))

    def test_kill_process_tree_posix_parent_protection(self):
        """CRITICAL: kill_process_tree on POSIX must NEVER call killpg if pgid == parent pgid."""
        sigkill = getattr(signal, "SIGKILL", getattr(signal, "SIGTERM", 9))
        with patch("os.name", "posix"):
            with patch("subprocess.run") as mock_subproc, \
                 patch("os.getpgrp", return_value=1000, create=True) as mock_parent_pgrp, \
                 patch("os.killpg", create=True) as mock_killpg, \
                 patch("os.kill", create=True) as mock_kill:

                # Scenario 1: Process is in the SAME group as parent (pgid == 1000)
                with patch("os.getpgid", return_value=1000, create=True):
                    mock_subproc.return_value.returncode = 1  # No child processes
                    kill_process_tree(5555)
                    # killpg must NOT have been called with parent's pgid
                    mock_killpg.assert_not_called()
                    # individual process must be killed with SIGKILL
                    mock_kill.assert_called_once_with(5555, sigkill)

                mock_kill.reset_mock()
                mock_killpg.reset_mock()

                # Scenario 2: Process is in its own detached group (pgid == 5555 != 1000)
                with patch("os.getpgid", return_value=5555, create=True):
                    mock_subproc.return_value.returncode = 1
                    kill_process_tree(5555)
                    # killpg SHOULD be called safely for the detached child process group
                    mock_killpg.assert_called_once_with(5555, sigkill)

    def test_dependency_manager_platform_paths(self):
        """Verify python, separator_exe, and pip paths reflect OS conventions."""
        with patch("sys.platform", "win32"):
            py = DependencyManager.get_engine_python()
            sep = DependencyManager.get_engine_separator_exe()
            self.assertTrue(py.replace("\\", "/").endswith("env/python.exe"))
            self.assertTrue(sep.replace("\\", "/").endswith("env/Scripts/audio-separator.exe"))

        with patch("sys.platform", "darwin"):
            py = DependencyManager.get_engine_python()
            sep = DependencyManager.get_engine_separator_exe()
            self.assertTrue(py.replace("\\", "/").endswith("env/bin/python"))
            self.assertTrue(sep.replace("\\", "/").endswith("env/bin/audio-separator"))

        with patch("sys.platform", "linux"):
            py = DependencyManager.get_engine_python()
            sep = DependencyManager.get_engine_separator_exe()
            self.assertTrue(py.replace("\\", "/").endswith("env/bin/python"))
            self.assertTrue(sep.replace("\\", "/").endswith("env/bin/audio-separator"))

    def test_gpu_detection_per_platform(self):
        """macOS always returns False (uses Apple Silicon Metal/CPU); Windows checks nvcuda.dll."""
        with patch("sys.platform", "darwin"):
            self.assertFalse(DependencyManager.has_nvidia_gpu())

    def test_theme_font_resolution_stacks(self):
        """Fonts resolve cleanly on simulated Windows, macOS, and Linux."""
        with patch("system_utils.get_current_os", return_value="macos"):
            font_ar = Theme.resolve_font_family("ar")
            font_en = Theme.resolve_font_family("en")
            mono = Theme.resolve_mono_font()
            self.assertIsInstance(font_ar, str)
            self.assertIsInstance(font_en, str)
            self.assertIsInstance(mono, str)

        with patch("system_utils.get_current_os", return_value="linux"):
            font_ar = Theme.resolve_font_family("ar")
            font_en = Theme.resolve_font_family("en")
            mono = Theme.resolve_mono_font()
            self.assertIsInstance(font_ar, str)
            self.assertIsInstance(font_en, str)
            self.assertIsInstance(mono, str)

        with patch("system_utils.get_current_os", return_value="windows"):
            font_ar = Theme.resolve_font_family("ar")
            font_en = Theme.resolve_font_family("en")
            mono = Theme.resolve_mono_font()
            self.assertIsInstance(font_ar, str)
            self.assertIsInstance(font_en, str)
            self.assertIsInstance(mono, str)

    def test_device_key_with_whitespace_bytes_not_corrupted(self):
        """CRITICAL: 32-byte binary key containing whitespace bytes must not be stripped."""
        from config_manager import _get_posix_master_key
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("config_manager.get_app_data_dir", return_value=tmp_dir):
                # Construct a 32-byte key that starts with \n and ends with space/return
                key_with_whitespace = b"\n" + (b"A" * 30) + b" "
                self.assertEqual(len(key_with_whitespace), 32)
                key_file = os.path.join(tmp_dir, ".device_key")
                with open(key_file, "wb") as f:
                    f.write(key_with_whitespace)

                loaded_key = _get_posix_master_key()
                self.assertEqual(len(loaded_key), 32)
                self.assertEqual(loaded_key, key_with_whitespace)

    def test_kill_process_tree_posix_pgid_zero_protection(self):
        """CRITICAL: If pgid is 0 or negative, killpg must NEVER be called (would kill parent group)."""
        with patch("os.name", "posix"):
            with patch("subprocess.run") as mock_subproc, \
                 patch("os.getpgrp", return_value=1000, create=True), \
                 patch("os.killpg", create=True) as mock_killpg, \
                 patch("os.kill", create=True) as mock_kill, \
                 patch("os.getpgid", return_value=0, create=True):

                mock_subproc.return_value.returncode = 1
                kill_process_tree(9999)
                mock_killpg.assert_not_called()
                mock_kill.assert_called_once()

    def test_kill_process_tree_refuses_to_kill_self(self):
        """kill_process_tree must immediately return if pid is current pid."""
        with patch("subprocess.run") as mock_subproc:
            kill_process_tree(os.getpid())
            mock_subproc.assert_not_called()

    def test_xdg_data_home_relative_path_fallback(self):
        """Relative XDG_DATA_HOME must fall back to ~/.local/share according to XDG spec."""
        with patch("system_utils.get_current_os", return_value="linux"):
            with patch.dict(os.environ, {"XDG_DATA_HOME": "relative/path/not/allowed"}):
                res = get_app_data_dir()
                expected_prefix = os.path.expanduser("~/.local/share")
                self.assertTrue(res.startswith(expected_prefix))

    def test_reveal_in_file_manager_uses_popen(self):
        """reveal_in_file_manager spawns asynchronously via Popen (non-blocking)."""
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf_path = tf.name
        try:
            with patch("subprocess.Popen") as mock_popen:
                reveal_in_file_manager(tf_path)
                mock_popen.assert_called_once()
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_dpapi_ciphertext_on_posix_returns_empty(self):
        """Windows DPAPI ciphertext loaded on macOS/Linux warns and returns empty string."""
        with patch("sys.platform", "darwin"):
            res = _unprotect_secret("enc:AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAA")
            self.assertEqual(res, "")


if __name__ == "__main__":
    unittest.main()
