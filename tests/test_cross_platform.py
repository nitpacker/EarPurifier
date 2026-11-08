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
from unittest.mock import patch, MagicMock, mock_open

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
            env_dir = DependencyManager.get_env_dir()
            bin_dir = DependencyManager.get_bin_dir()
            py = DependencyManager.get_engine_python()
            sep = DependencyManager.get_engine_separator_exe()
            self.assertEqual(env_dir, os.path.expanduser("~/.earpurifier/env"))
            self.assertEqual(bin_dir, os.path.expanduser("~/.earpurifier/bin"))
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

    def test_clean_subprocess_env_strips_pyinstaller_vars(self):
        """Verify get_clean_subprocess_env strips PyInstaller leaks and includes bin_dir."""
        from system_utils import get_clean_subprocess_env
        leak_env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONHOME": "/frozen/python",
            "PYTHONPATH": "/frozen/site-packages",
            "DYLD_LIBRARY_PATH": "/frozen/frameworks",
            "_MEIPASS2": "/tmp/_MEI12345"
        }
        with patch.dict(os.environ, leak_env, clear=True):
            with patch("sys.platform", "darwin"):
                cleaned = get_clean_subprocess_env(["/custom/env/bin"])
                self.assertNotIn("PYTHONHOME", cleaned)
                self.assertNotIn("PYTHONPATH", cleaned)
                self.assertNotIn("DYLD_LIBRARY_PATH", cleaned)
                self.assertNotIn("_MEIPASS2", cleaned)
                self.assertIn("/custom/env/bin", cleaned["PATH"])
                self.assertIn("/opt/homebrew/bin", cleaned["PATH"])
                self.assertIn("EarPurifier/bin", cleaned["PATH"].replace("\\", "/"))
                self.assertIn(".earpurifier/bin", cleaned["PATH"].replace("\\", "/"))

    def test_get_executable_legacy_bin_discovery_on_macos(self):
        """Verify get_executable discovers FFmpeg in legacy Application Support/EarPurifier/bin."""
        legacy_bin = os.path.normpath(os.path.join(test_appdata, "EarPurifier", "bin", "ffmpeg"))
        with patch("sys.platform", "darwin"):
            with patch.object(DependencyManager, "get_bin_dir", return_value=os.path.expanduser("~/.earpurifier/bin")), \
                 patch.object(DependencyManager, "get_appdata_dir", return_value=os.path.join(test_appdata, "EarPurifier")):
                def fake_isfile(path):
                    return os.path.normpath(path) == legacy_bin
                with patch("os.path.isfile", side_effect=fake_isfile):
                    found = DependencyManager.get_executable("ffmpeg")
                    self.assertIsNotNone(found)
                    self.assertEqual(os.path.normpath(found), legacy_bin)

    def test_dependency_manager_windows_short_path_resolution(self):
        """Verify Windows resolves 8.3 short paths when env path contains spaces."""
        fake_appdata = "C:\\Users\\John Doe\\AppData\\Roaming\\EarPurifier"
        fake_short = "C:\\Users\\JOHNDE~1\\AppData\\Roaming\\EarPurifier\\env"
        with patch("sys.platform", "win32"):
            with patch.object(DependencyManager, "get_appdata_dir", return_value=fake_appdata):
                with patch("ctypes.windll.kernel32.GetShortPathNameW", create=True) as mock_short:
                    def side_effect(path, buf, size):
                        buf.value = fake_short
                        return len(fake_short)
                    mock_short.side_effect = side_effect
                    with patch("os.path.exists", return_value=True):
                        resolved = DependencyManager.get_env_dir()
                        self.assertEqual(resolved, fake_short)

    def test_local_processor_cmd_prefix_shebang_immunity(self):
        """Verify LocalJobProcessor executes Python directly on POSIX to bypass kernel shebang traps."""
        from local_processor import LocalJobProcessor

        # Windows uses binary .exe wrapper directly
        with patch("sys.platform", "win32"):
            engine_exe = "C:\\env\\Scripts\\audio-separator.exe"
            engine_python = "C:\\env\\python.exe"
            cmd_prefix = LocalJobProcessor.get_cmd_prefix(engine_exe, engine_python)
            self.assertEqual(cmd_prefix, [engine_exe])

        # macOS / POSIX with python present directly invokes python interpreter
        with patch("sys.platform", "darwin"):
            engine_exe = "/Users/test/.earpurifier/env/bin/audio-separator"
            engine_python = "/Users/test/.earpurifier/env/bin/python"
            with patch("os.path.exists", return_value=True):
                cmd_prefix = LocalJobProcessor.get_cmd_prefix(engine_exe, engine_python)
                self.assertEqual(cmd_prefix, [engine_python, engine_exe])

        # macOS / POSIX fallback when python path does not exist
        with patch("sys.platform", "darwin"):
            engine_exe = "/Users/test/.earpurifier/env/bin/audio-separator"
            engine_python = "/Users/test/.earpurifier/env/bin/python"
            with patch("os.path.exists", return_value=False):
                cmd_prefix = LocalJobProcessor.get_cmd_prefix(engine_exe, engine_python)
                self.assertEqual(cmd_prefix, [engine_exe])

    def test_local_processor_popen_uses_cmd_prefix(self):
        """Verify process_local_job actually passes cmd_prefix to subprocess.Popen."""
        from local_processor import LocalJobProcessor
        mock_qm = MagicMock()
        mock_qm.is_job_aborted.return_value = False
        mock_qm.get_all_jobs.return_value = {}
        mock_config = MagicMock()
        mock_config.appdata_dir = test_appdata
        mock_config.get_output_folder.return_value = os.path.join(test_appdata, "out")

        processor = LocalJobProcessor(mock_qm, mock_config)
        temp_dir = os.path.join(test_appdata, "temp", "test_jid")
        os.makedirs(temp_dir, exist_ok=True)
        vocal_file = os.path.join(temp_dir, "audio_(Vocals).wav")
        with open(vocal_file, "w") as f:
            f.write("dummy")

        job = {
            "original_media": os.path.join(test_appdata, "audio.mp4"),
            "selected_audio_stream": 0,
            "duration": 5.0,
            "model": "MDX23C"
        }

        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout.readline.return_value = ""

        real_exists = os.path.exists
        with patch("sys.platform", "darwin"), \
             patch("local_processor.DependencyManager.has_local_engine", return_value=True), \
             patch("local_processor.DependencyManager.get_engine_separator_exe", return_value="/env/bin/audio-separator"), \
             patch("local_processor.DependencyManager.get_engine_python", return_value="/env/bin/python"), \
             patch("local_processor.DependencyManager.get_env_dir", return_value="/env"), \
             patch("local_processor.probe_container", return_value={"audio_streams": [{}]}), \
             patch("local_processor.extract_audio", return_value=""), \
             patch("local_processor.pad_or_trim_audio", return_value=""), \
             patch("local_processor.remux_media", return_value=""), \
             patch("os.path.exists", side_effect=lambda p: True if p in (vocal_file, "/env/bin/python") else real_exists(p)), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("process_tracker.register_process"), \
             patch("process_tracker.unregister_process"):

            processor.process_local_job("test_jid", job)
            spawned_cmd = mock_popen.call_args[0][0]
            self.assertEqual(spawned_cmd[0], "/env/bin/python")
            self.assertEqual(spawned_cmd[1], "/env/bin/audio-separator")

    def test_engine_downloader_detects_wrong_python_version_and_rebuilds(self):
        """Verify EngineDownloader wipes and recreates environment if python version does not match."""
        from dependency_manager import EngineDownloader
        downloader = EngineDownloader()

        with patch("sys.platform", "darwin"), \
             patch.object(DependencyManager, "get_bin_dir", return_value="/test/bin"), \
             patch.object(DependencyManager, "get_env_dir", return_value="/test/env"), \
             patch.object(DependencyManager, "get_engine_python", return_value="/test/env/bin/python"), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=test_appdata), \
             patch("os.path.exists", return_value=True), \
             patch("shutil.rmtree") as mock_rmtree, \
             patch("subprocess.run") as mock_run:

            # Simulate existing python reporting 3.11 instead of expected 3.10 on macOS
            ver_res = MagicMock()
            ver_res.returncode = 0
            ver_res.stdout = "3.11\n"

            create_res = MagicMock()
            create_res.returncode = 0

            pip_res = MagicMock()
            pip_res.returncode = 0

            def fake_run(cmd, **kwargs):
                if "-c" in cmd:
                    return ver_res
                elif "create" in cmd:
                    return create_res
                return pip_res

            mock_run.side_effect = fake_run
            with patch("builtins.open", mock_open()):
                downloader.run()

            # Confirm legacy env cleanup + rebuild rmtree were called
            self.assertTrue(mock_rmtree.called)
            # Confirm micromamba create was called with python=3.10
            create_calls = [call for call in mock_run.call_args_list if "create" in call[0][0]]
            self.assertTrue(len(create_calls) > 0)
            self.assertIn("python=3.10", create_calls[0][0][0])

    def test_model_downloader_escapes_paths_and_cleans_temp_script(self):
        """Verify ModelDownloader uses safe repr formatting and cleans up temp_download.py in finally."""
        from dependency_manager import ModelDownloader
        # Path with spaces and trailing backslash (notoriously breaks raw strings)
        tricky_dir = "C:\\EarPurifier AppData\\models\\RoFormer\\"
        downloader = ModelDownloader("test_model.ckpt", tricky_dir)

        written_content = {}
        def fake_open(path, mode="r", encoding=None):
            class FakeFile:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def write(self, content): written_content["code"] = content
            return FakeFile()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.stdout.readline.side_effect = ["SUCCESS_DOWNLOAD\n", ""]

        removed_files = []
        with patch.object(DependencyManager, "get_engine_python", return_value="python"), \
             patch.object(DependencyManager, "get_env_dir", return_value="/env"), \
             patch("builtins.open", side_effect=fake_open), \
             patch("subprocess.Popen", return_value=mock_proc), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove", side_effect=lambda p: removed_files.append(p)), \
             patch("process_tracker.register_process"), \
             patch("process_tracker.unregister_process"):

            downloader.run()

            # Verify the written code is syntactically compilable python
            self.assertIn("code", written_content)
            compile(written_content["code"], "<test_script>", "exec")
            # Verify script_path was removed in finally
            self.assertTrue(any(p.endswith("temp_download.py") for p in removed_files))

    def test_get_executable_posix_chmod_safety(self):
        """Verify get_executable attempts chmod 0o755 when binary exists without executable bit."""
        fake_bin = os.path.join("/test/bin", "ffmpeg")
        with patch("sys.platform", "darwin"):
            with patch.object(DependencyManager, "get_bin_dir", return_value="/test/bin"), \
                 patch("os.path.isfile", return_value=True), \
                 patch("os.access", return_value=False), \
                 patch("os.chmod") as mock_chmod:
                exe = DependencyManager.get_executable("ffmpeg")
                self.assertIsNotNone(exe)
                mock_chmod.assert_called_with(fake_bin, 0o755)

    def test_media_engine_fast_aac_encoder(self):
        """Verify get_fast_aac_encoder returns hardware encoders: aac_mf on win, aac_at on mac."""
        from media_engine import get_fast_aac_encoder
        with patch("sys.platform", "win32"):
            self.assertEqual(get_fast_aac_encoder(), "aac_mf")
        with patch("sys.platform", "darwin"):
            self.assertEqual(get_fast_aac_encoder(), "aac_at")
        with patch("sys.platform", "linux"):
            self.assertEqual(get_fast_aac_encoder(), "aac")

    def test_get_executable_homebrew_fallback_on_macos(self):
        """Verify get_executable discovers Homebrew binaries when not in default GUI PATH."""
        target_bin = os.path.normpath("/opt/homebrew/bin/ffmpeg")
        with patch("sys.platform", "darwin"):
            with patch("shutil.which", return_value=None):
                with patch("os.path.isfile") as mock_isfile, \
                     patch("os.access", return_value=True):
                    # Simulate /opt/homebrew/bin/ffmpeg exists
                    def fake_isfile(path):
                        return os.path.normpath(path) == target_bin
                    mock_isfile.side_effect = fake_isfile
                    res = DependencyManager.get_executable("ffmpeg")
                    self.assertIsNotNone(res)
                    self.assertEqual(os.path.normpath(res), target_bin)


if __name__ == "__main__":
    unittest.main()
