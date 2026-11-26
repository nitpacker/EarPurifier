"""
EarPurifier - Local Engine Resiliency, CUDA 12 Integrity, & UI Concurrency Tests.
Covers:
- Dynamic FFmpeg/FFprobe PATH injection, torch/lib, and UTF-8 subprocess hardening
- Cached per-platform has_nvidia_gpu() & macOS safety
- Adaptive CUDA 12 wheel selection matrix & multi-layer fail-safe probes
- Zero-subprocess torch/version.py inspection (detecting PyPI CPU overwrite)
- EngineDownloader constraints lock, onnxruntime-gpu<1.27.0 pin, Step 4 verification, & upgrade_to_gpu
- ModelDownloader info_only=True + download_model_and_data(), tqdm weight regex, & error classification
- Atomic FFmpegDownloader staging
- MainWindow ffmpeg_overlay resizeEvent safety, DropZone concurrency guard, GpuUpgradeBanner, & immediate local abort
"""

import os
import sys
import json
import time
import shutil
import hashlib
import zipfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, MagicMock

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

test_appdata = os.path.join(root_dir, ".test_appdata")
os.makedirs(test_appdata, exist_ok=True)
os.environ["APPDATA"] = test_appdata

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QSize
from PySide6.QtGui import QResizeEvent

import i18n
import local_processor
from dependency_manager import (
    DependencyManager,
    EngineDownloader,
    ModelDownloader,
    FFmpegDownloader,
    LOCAL_MODEL_MANIFEST,
    DownloadCancelledError,
    InsufficientDiskSpaceError,
    ChecksumMismatchError,
    _SegmentedFileDownloader,
    _atomic_replace_file,
    load_installed_model_checksums,
    classify_local_error,
)
from local_processor import LocalJobProcessor
from config_manager import ConfigManager
from queue_manager import QueueManager
from ui.job_queue_section import JobQueueSection
from ui.overlay_widgets import GpuUpgradeBanner
from ui.main_window import MainWindow
from ui.job_widget import _has_active_local_gpu

app = QApplication.instance() or QApplication([])


class TestLocalEngineResiliency(unittest.TestCase):
    def setUp(self):
        DependencyManager.clear_gpu_cache()
        self.tmp_dir = tempfile.mkdtemp(prefix="ep_resiliency_")

    def tearDown(self):
        DependencyManager.clear_gpu_cache()
        i18n.set_language("ar")
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        qapp = QApplication.instance()
        if qapp:
            qapp.closeAllWindows()
            qapp.processEvents()

    # ── 1. Subprocess Env & UTF-8 Hardening ──────────────────────────────────

    def test_engine_subprocess_env_dynamic_ffmpeg_torch_lib_and_utf8(self):
        """get_engine_subprocess_env injects dynamic ffmpeg dir, torch/lib, and UTF-8 vars."""
        # Linux / custom FFmpeg location
        with patch("sys.platform", "linux"), \
             patch.object(DependencyManager, "get_env_dir", return_value="/opt/ep/env"), \
             patch.object(DependencyManager, "get_bin_dir", return_value="/opt/ep/bin"), \
             patch.object(
                 DependencyManager,
                 "get_executable",
                 side_effect=lambda name: f"/usr/local/custom_bin/{name}",
             ):
            env = DependencyManager.get_engine_subprocess_env()
            self.assertEqual(env.get("PYTHONUTF8"), "1")
            self.assertEqual(env.get("PYTHONIOENCODING"), "utf-8")
            path_parts = env["PATH"].split(os.pathsep)
            self.assertIn("/usr/local/custom_bin", path_parts)
            self.assertIn("/usr/local/bin", path_parts)
            self.assertIn("/usr/bin", path_parts)
            self.assertIn("/bin", path_parts)

        # Windows with torch/lib present
        fake_env = os.path.join(self.tmp_dir, "env")
        torch_lib = os.path.join(fake_env, "Lib", "site-packages", "torch", "lib")
        os.makedirs(torch_lib, exist_ok=True)
        fake_ffmpeg = os.path.join(self.tmp_dir, "portable_ff", "ffmpeg.exe")
        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=fake_env), \
             patch.object(DependencyManager, "get_bin_dir", return_value=os.path.join(self.tmp_dir, "bin")), \
             patch.object(DependencyManager, "get_executable", return_value=fake_ffmpeg):
            env = DependencyManager.get_engine_subprocess_env()
            self.assertEqual(env.get("PYTHONUTF8"), "1")
            self.assertEqual(env.get("PYTHONIOENCODING"), "utf-8")
            path_parts = env["PATH"].split(os.pathsep)
            self.assertIn(torch_lib, path_parts)
            self.assertIn(os.path.dirname(fake_ffmpeg), path_parts)

    # ── 2. Cached Per-Platform GPU Detection & macOS Safety ──────────────────

    def test_has_nvidia_gpu_per_platform_cache_and_macos_safety(self):
        """has_nvidia_gpu caches per sys.platform and immediately returns False on darwin."""
        with patch("sys.platform", "win32"), \
             patch("os.path.exists", return_value=True) as mock_exists:
            self.assertTrue(DependencyManager.has_nvidia_gpu())
            self.assertEqual(mock_exists.call_count, 1)
            # Second call hits cache
            self.assertTrue(DependencyManager.has_nvidia_gpu())
            self.assertEqual(mock_exists.call_count, 1)

        # Even with win32 cached True, darwin MUST immediately return False
        with patch("sys.platform", "darwin"), \
             patch("os.path.exists", return_value=True):
            self.assertFalse(DependencyManager.has_nvidia_gpu())

        # Clearing cache allows fresh re-probe
        DependencyManager.clear_gpu_cache()
        with patch("sys.platform", "win32"), \
             patch("os.path.exists", return_value=False), \
             patch("shutil.which", return_value=None):
            self.assertFalse(DependencyManager.has_nvidia_gpu())

    # ── 3. Adaptive CUDA 12 Selection Matrix ─────────────────────────────────

    def test_select_pytorch_cuda_indices_matrix(self):
        """select_pytorch_cuda_indices routes driver & compute capability accurately."""
        # Driver < 12.1 -> skip CUDA (CPU)
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((11, 8)), [])
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 0)), [])
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices(12000), [])

        # device_count == 0 -> skip CUDA even with new driver
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 6), 8, device_count=0), [])

        # 12.1 - 12.3 -> cu121
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 1)), ["cu121"])
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 3)), ["cu121"])

        # 12.4 - 12.5 -> cu124, cu121
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 4)), ["cu124", "cu121"])
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices("12.5"), ["cu124", "cu121"])

        # >= 12.6 non-Blackwell -> cu126, cu124, cu121
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 6), compute_cap_major=8), ["cu126", "cu124", "cu121"])
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices(12080, compute_cap_major=8), ["cu126", "cu124", "cu121"])
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices(12.6), ["cu126", "cu124", "cu121"])

        # Blackwell (compute_cap_major >= 10) + driver >= 12.8 -> cu128, cu126
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 8), compute_cap_major=10), ["cu128", "cu126"])
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 8), compute_cap_major=12), ["cu128", "cu126"])

        # Blackwell with driver 12.6 -> falls back to cu126 chain
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices((12, 6), compute_cap_major=12), ["cu126", "cu124", "cu121"])

        # Unknown driver (None) -> safe cu121 baseline
        self.assertEqual(DependencyManager.select_pytorch_cuda_indices(None), ["cu121"])

    # ── 4. Zero-Subprocess Torch Inspection & Upgrade Detection ──────────────

    def test_get_installed_torch_info_and_needs_gpu_upgrade(self):
        """Detects PyPI torch==2.15.0+cpu overwrite via torch/version.py even when METADATA omits +cpu."""
        env_dir = os.path.join(self.tmp_dir, "env")
        sp_dir = os.path.join(env_dir, "Lib", "site-packages")
        torch_dir = os.path.join(sp_dir, "torch")
        dist_info = os.path.join(sp_dir, "torch-2.15.0.dist-info")
        os.makedirs(torch_dir, exist_ok=True)
        os.makedirs(dist_info, exist_ok=True)

        # PyPI wheel METADATA omits '+cpu', while torch/version.py has cuda = None
        with open(os.path.join(dist_info, "METADATA"), "w", encoding="utf-8") as f:
            f.write("Metadata-Version: 2.1\nName: torch\nVersion: 2.15.0\n")
        with open(os.path.join(torch_dir, "version.py"), "w", encoding="utf-8") as f:
            f.write("__version__ = '2.15.0+cpu'\ncuda = None\n")

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir), \
             patch.object(DependencyManager, "has_local_engine", return_value=True), \
             patch.object(DependencyManager, "has_nvidia_gpu", return_value=True):
            info = DependencyManager.get_installed_torch_info()
            self.assertTrue(info["installed"])
            self.assertEqual(info["version"], "2.15.0+cpu")
            self.assertIsNone(info["cuda"])
            self.assertFalse(info["is_cuda"])
            self.assertTrue(DependencyManager.needs_gpu_engine_upgrade())

        # macOS NEVER requests NVIDIA GPU upgrade
        with patch("sys.platform", "darwin"):
            self.assertFalse(DependencyManager.needs_gpu_engine_upgrade())

        # Now simulate CUDA 12.6 installed
        with open(os.path.join(torch_dir, "version.py"), "w", encoding="utf-8") as f:
            f.write("__version__ = '2.14.1+cu126'\ncuda = '12.6'\n")

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir), \
             patch.object(DependencyManager, "has_local_engine", return_value=True), \
             patch.object(DependencyManager, "has_nvidia_gpu", return_value=True):
            info = DependencyManager.get_installed_torch_info()
            self.assertTrue(info["is_cuda"])
            self.assertEqual(info["cuda"], "12.6")
            self.assertFalse(DependencyManager.needs_gpu_engine_upgrade())

        # Fallback to METADATA if version.py is absent
        os.remove(os.path.join(torch_dir, "version.py"))
        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir):
            info = DependencyManager.get_installed_torch_info()
            self.assertTrue(info["installed"])
            self.assertFalse(info["is_cuda"])

    # ── 5. EngineDownloader CUDA 12 Constraints Lock & Fallback Chain ────────

    def test_engine_downloader_cuda12_constraints_lock_and_fallback_chain(self):
        """EngineDownloader falls back cu126 -> cu124, locks constraints, pins onnxruntime-gpu<1.27.0, and verifies CUDA."""
        env_dir = os.path.join(self.tmp_dir, "env")
        bin_dir = os.path.join(self.tmp_dir, "bin")
        os.makedirs(env_dir, exist_ok=True)
        os.makedirs(bin_dir, exist_ok=True)
        py_exe = os.path.join(env_dir, "python.exe")
        mamba_exe = os.path.join(bin_dir, "micromamba.exe")
        with open(py_exe, "w") as f:
            f.write("")
        with open(mamba_exe, "w") as f:
            f.write("")

        downloader = EngineDownloader()
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append((cmd, kwargs))
            proc = MagicMock()
            proc.pid = 777
            proc.returncode = 0
            joined = " ".join(str(x) for x in cmd)

            if "version_info.major" in joined:
                proc.communicate.return_value = ("3.11\n", "")
            elif "cuDriverGetVersion" in joined:
                proc.communicate.return_value = ('{"driver": [12, 6], "device_count": 1, "compute_cap_major": 8, "source": "driver_api"}\n', "")
            elif "whl/cu126" in joined and "torchvision" in joined:
                # Simulate cu126 failure to verify automatic fallback to cu124
                proc.returncode = 1
                proc.communicate.return_value = ("", "No matching distribution on cu126")
            elif "whl/cu124" in joined and "torchvision" in joined:
                proc.communicate.return_value = ("Successfully installed torch torchvision\n", "")
            elif "torch==" in joined and "importlib.metadata" in joined:
                proc.communicate.return_value = ("torch==2.6.0+cu124\ntorchvision==0.21.0+cu124\n", "")
            elif "audio-separator[gpu]" in joined:
                proc.communicate.return_value = ("Successfully installed audio-separator\n", "")
            elif "cuda_available" in joined:
                proc.communicate.return_value = (
                    '{"torch_version": "2.6.0+cu124", "dist_version": "2.6.0+cu124", "cuda": "12.4", "cuda_available": true, "mps_available": false}\n',
                    "",
                )
            else:
                proc.communicate.return_value = ("", "")
            return proc

        results = []
        downloader.finished_download.connect(lambda ok, msg: results.append((ok, msg)))

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch.object(DependencyManager, "get_engine_python", return_value=py_exe), \
             patch.object(DependencyManager, "has_nvidia_gpu", return_value=True), \
             patch("subprocess.Popen", side_effect=fake_popen), \
             patch("process_tracker.register_process"), \
             patch("process_tracker.unregister_process"):
            downloader.run()

        self.assertEqual(results, [(True, "Success")])

        # ver_check received clean UTF-8 env (fixes S2)
        ver_calls = [(c, kw) for c, kw in calls if any("version_info.major" in str(a) for a in c)]
        self.assertEqual(len(ver_calls), 1)
        self.assertEqual(ver_calls[0][1]["env"].get("PYTHONUTF8"), "1")

        # Step 3 passed -c <constraints>, --extra-index-url cu124, audio-separator[gpu], onnxruntime-gpu<1.27.0
        sep_calls = [c for c, _ in calls if "audio-separator[gpu]" in c]
        self.assertEqual(len(sep_calls), 1)
        sep_cmd = sep_calls[0]
        self.assertIn("-c", sep_cmd)
        self.assertIn("--extra-index-url", sep_cmd)
        self.assertIn("https://download.pytorch.org/whl/cu124", sep_cmd)
        self.assertIn("onnxruntime-gpu<1.27.0", sep_cmd)

        # Temporary constraints.txt was cleaned up
        leftover_constraints = [f for f in os.listdir(env_dir) if f.startswith(".constraints_")]
        self.assertEqual(leftover_constraints, [])

        # .engine_installed written with mode=cuda
        marker = os.path.join(env_dir, ".engine_installed")
        self.assertTrue(os.path.isfile(marker))
        with open(marker, "r", encoding="utf-8") as f:
            marker_txt = f.read()
        self.assertIn("mode=cuda", marker_txt)
        self.assertIn("2.6.0+cu124", marker_txt)

    # ── 6. Step 4 Rejects Silent CPU Overwrite When GPU Expected ─────────────

    def test_engine_downloader_step4_rejects_cpu_overwrite_when_gpu_expected(self):
        """Step 4 fails cleanly and refuses to write .engine_installed if torch.version.cuda is None."""
        env_dir = os.path.join(self.tmp_dir, "env")
        bin_dir = os.path.join(self.tmp_dir, "bin")
        os.makedirs(env_dir, exist_ok=True)
        os.makedirs(bin_dir, exist_ok=True)
        py_exe = os.path.join(env_dir, "python.exe")
        mamba_exe = os.path.join(bin_dir, "micromamba.exe")
        open(py_exe, "w").close()
        open(mamba_exe, "w").close()

        downloader = EngineDownloader()

        def fake_popen(cmd, **kwargs):
            proc = MagicMock()
            proc.pid = 888
            proc.returncode = 0
            joined = " ".join(str(x) for x in cmd)
            if "version_info.major" in joined:
                proc.communicate.return_value = ("3.11\n", "")
            elif "cuDriverGetVersion" in joined:
                proc.communicate.return_value = ('{"driver": [12, 6], "device_count": 1, "compute_cap_major": 8}\n', "")
            elif "torch==" in joined:
                proc.communicate.return_value = ("torch==2.14.1+cu126\ntorchvision==0.29.1+cu126\n", "")
            elif "cuda_available" in joined:
                # Simulate silent CPU overwrite bug!
                proc.communicate.return_value = (
                    '{"torch_version": "2.15.0+cpu", "dist_version": "2.15.0", "cuda": null, "cuda_available": false, "mps_available": false}\n',
                    "",
                )
            else:
                proc.communicate.return_value = ("", "")
            return proc

        results = []
        downloader.finished_download.connect(lambda ok, msg: results.append((ok, msg)))

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch.object(DependencyManager, "get_engine_python", return_value=py_exe), \
             patch.object(DependencyManager, "has_nvidia_gpu", return_value=True), \
             patch("subprocess.Popen", side_effect=fake_popen), \
             patch("process_tracker.register_process"), \
             patch("process_tracker.unregister_process"):
            downloader.run()

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0][0])
        self.assertIn("CUDA verification failed", results[0][1])
        self.assertFalse(os.path.exists(os.path.join(env_dir, ".engine_installed")))
        self.assertTrue(os.path.exists(os.path.join(env_dir, ".engine_in_progress")))

        # Even if site-packages/torch & audio_separator exist, has_local_engine() MUST NOT resurrect it!
        os.makedirs(os.path.join(env_dir, "Scripts"), exist_ok=True)
        os.makedirs(os.path.join(env_dir, "Lib", "site-packages", "torch"), exist_ok=True)
        os.makedirs(os.path.join(env_dir, "Lib", "site-packages", "audio_separator"), exist_ok=True)
        open(os.path.join(env_dir, "Scripts", "audio-separator.exe"), "w").close()
        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir):
            self.assertFalse(DependencyManager.has_local_engine())
            self.assertFalse(os.path.exists(os.path.join(env_dir, ".engine_installed")))

    # ── 7. Upgrade-to-GPU Flow & Pre-Mutation Old Driver Guard ───────────────

    def test_engine_downloader_upgrade_to_gpu_uninstall_first_and_old_driver_guard(self):
        """upgrade_to_gpu preserves env if driver < 12.1; removes marker & uninstalls first on valid driver."""
        env_dir = os.path.join(self.tmp_dir, "env")
        bin_dir = os.path.join(self.tmp_dir, "bin")
        os.makedirs(env_dir, exist_ok=True)
        os.makedirs(bin_dir, exist_ok=True)
        py_exe = os.path.join(env_dir, "python.exe")
        mamba_exe = os.path.join(bin_dir, "micromamba.exe")
        marker = os.path.join(env_dir, ".engine_installed")
        open(py_exe, "w").close()
        open(mamba_exe, "w").close()
        with open(marker, "w", encoding="utf-8") as f:
            f.write("INSTALLED\n")

        # Subtest A: Old driver (11.8) -> MUST NOT remove marker or uninstall!
        dl_old = EngineDownloader(upgrade_to_gpu=True)
        old_calls = []

        def fake_popen_old(cmd, **kwargs):
            old_calls.append(cmd)
            proc = MagicMock()
            proc.pid = 901
            proc.returncode = 0
            joined = " ".join(str(x) for x in cmd)
            if "version_info.major" in joined:
                proc.communicate.return_value = ("3.11\n", "")
            elif "cuDriverGetVersion" in joined:
                proc.communicate.return_value = ('{"driver": [11, 8], "device_count": 1, "compute_cap_major": 7}\n', "")
            else:
                proc.communicate.return_value = ("", "")
            return proc

        old_results = []
        dl_old.finished_download.connect(lambda ok, msg: old_results.append((ok, msg)))

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch.object(DependencyManager, "get_engine_python", return_value=py_exe), \
             patch.object(DependencyManager, "has_nvidia_gpu", return_value=True), \
             patch("subprocess.Popen", side_effect=fake_popen_old), \
             patch("process_tracker.register_process"), \
             patch("process_tracker.unregister_process"):
            dl_old.run()

        self.assertFalse(old_results[0][0])
        self.assertTrue(os.path.exists(marker), "Existing .engine_installed must remain untouched on old driver")
        self.assertFalse(any("uninstall" in c for c in old_calls))

        # Subtest B: Valid driver 12.6 -> removes marker FIRST, runs pip uninstall -y, then installs CUDA 12
        dl_ok = EngineDownloader(upgrade_to_gpu=True)
        marker_existed_at_uninstall = []
        ok_calls = []

        def fake_popen_ok(cmd, **kwargs):
            ok_calls.append(cmd)
            proc = MagicMock()
            proc.pid = 902
            proc.returncode = 0
            joined = " ".join(str(x) for x in cmd)
            if "uninstall" in cmd:
                marker_existed_at_uninstall.append(os.path.exists(marker))
            if "version_info.major" in joined:
                proc.communicate.return_value = ("3.11\n", "")
            elif "cuDriverGetVersion" in joined:
                proc.communicate.return_value = ('{"driver": [12, 6], "device_count": 1, "compute_cap_major": 8}\n', "")
            elif "torch==" in joined:
                proc.communicate.return_value = ("torch==2.14.1+cu126\ntorchvision==0.29.1+cu126\n", "")
            elif "cuda_available" in joined:
                proc.communicate.return_value = (
                    '{"torch_version": "2.14.1+cu126", "dist_version": "2.14.1+cu126", "cuda": "12.6", "cuda_available": true, "mps_available": false}\n',
                    "",
                )
            else:
                proc.communicate.return_value = ("", "")
            return proc

        ok_results = []
        dl_ok.finished_download.connect(lambda ok, msg: ok_results.append((ok, msg)))

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch.object(DependencyManager, "get_engine_python", return_value=py_exe), \
             patch.object(DependencyManager, "has_nvidia_gpu", return_value=True), \
             patch("subprocess.Popen", side_effect=fake_popen_ok), \
             patch("process_tracker.register_process"), \
             patch("process_tracker.unregister_process"):
            dl_ok.run()

        self.assertEqual(ok_results, [(True, "Success")])
        self.assertEqual(marker_existed_at_uninstall, [False], ".engine_installed must be removed before pip uninstall")
        uninstall_calls = [c for c in ok_calls if "uninstall" in c]
        self.assertEqual(len(uninstall_calls), 1)
        for pkg in ("torch", "torchvision", "onnxruntime", "onnxruntime-gpu"):
            self.assertIn(pkg, uninstall_calls[0])
        self.assertTrue(os.path.exists(marker))

    # ── 8. Multi-Layer Fail-Safe CUDA Probe Fallbacks ────────────────────────

    def test_cuda_probe_multi_failsafe_fallbacks(self):
        """If ctypes driver probe fails, falls back to nvidia-smi; if both fail, safely routes to cu121."""
        dl = EngineDownloader()

        # Fallback 1: ctypes probe fails, nvidia-smi succeeds with CUDA 12.6
        def fake_tracked_smi(cmd, env, timeout=None):
            res = MagicMock()
            if "-c" in cmd:
                res.returncode = 1
                res.stdout = ""
            else:
                res.returncode = 0
                res.stdout = "| NVIDIA-SMI 560.94   Driver Version: 560.94   CUDA Version: 12.6 |"
            return res

        with patch("sys.platform", "win32"), \
             patch.object(dl, "_run_tracked_command", side_effect=fake_tracked_smi), \
             patch("shutil.which", return_value="nvidia-smi"):
            probe = dl._probe_cuda_hardware("python.exe", {})
            self.assertEqual(probe["driver"], [12, 6])
            self.assertEqual(probe["source"], "nvidia-smi")
            self.assertEqual(
                DependencyManager.select_pytorch_cuda_indices(probe["driver"]),
                ["cu126", "cu124", "cu121"],
            )

        # Fallback 2: both ctypes and nvidia-smi fail -> never raises, routes safely to cu121
        with patch("sys.platform", "win32"), \
             patch.object(dl, "_run_tracked_command", side_effect=OSError("probe failed")), \
             patch("shutil.which", return_value=None):
            probe = dl._probe_cuda_hardware("python.exe", {})
            self.assertIsNone(probe["driver"])
            self.assertEqual(
                DependencyManager.select_pytorch_cuda_indices(probe["driver"]),
                ["cu121"],
            )

    # ── 9. ModelDownloader info_only, tqdm Filter, & UTF-8 Arabic ────────────

    def test_model_downloader_info_only_tqdm_filter_and_utf8_arabic(self):
        """ModelDownloader uses info_only=True, filters small metadata tqdm bars, and decodes Arabic UTF-8."""
        # tqdm regex unit verification
        self.assertIsNone(
            ModelDownloader.parse_weight_progress("100%|██████████| 28.3k/28.3k [00:00<00:00, 90.9MiB/s]")
        )
        self.assertIsNone(
            ModelDownloader.parse_weight_progress("100%|██████████| 28.3kB/28.3kB [00:00<00:00, 90.9MiB/s]")
        )
        self.assertIsNone(
            ModelDownloader.parse_weight_progress("100%|██████████| 709/709 [00:00<00:00, 1.45MiB/s]")
        )
        self.assertIsNone(
            ModelDownloader.parse_weight_progress("100%|██████████| 709B/709B [00:00<00:00, 1.45MiB/s]")
        )
        self.assertIsNone(
            ModelDownloader.parse_weight_progress("100%|██████████| 2.5M/2.5M [00:00<00:00, 15.0MiB/s]")
        )
        self.assertEqual(
            ModelDownloader.parse_weight_progress("  0%|          | 0.00B/610MB [00:00<?, ?B/s]"),
            0,
        )
        self.assertEqual(
            ModelDownloader.parse_weight_progress("  1%|▏         | 512KiB/610MiB [00:01<02:00, 5.0MiB/s]"),
            1,
        )
        self.assertEqual(
            ModelDownloader.parse_weight_progress("50%|█████     | 305M/610M [00:12<00:12, 25.1MiB/s]"),
            50,
        )
        self.assertEqual(
            ModelDownloader.parse_weight_progress("50%|█████     | 305MB/610MB [00:12<00:12, 25.1MB/s]"),
            50,
        )
        self.assertEqual(
            ModelDownloader.parse_weight_progress("50%|█████     | 305MiB/610MiB [00:12<00:12, 25.1MiB/s]"),
            50,
        )
        self.assertEqual(
            ModelDownloader.parse_weight_progress("75%|███████▌  | 0.90G/1.20G [00:20<00:06, 45.0MiB/s]"),
            75,
        )
        self.assertEqual(
            ModelDownloader.parse_weight_progress("75%|███████▌  | 900MB/1.20GB [00:20<00:06, 45.0MB/s]"),
            75,
        )

        # Full run simulation with Arabic logs + download_checks.json 100% + weight progression
        # Uses an unknown/custom model name to exercise the scoped audio-separator subprocess fallback
        env_dir = os.path.join(self.tmp_dir, "env")
        os.makedirs(env_dir, exist_ok=True)
        dl = ModelDownloader("custom_roformer_fallback.ckpt", os.path.join(self.tmp_dir, "مجلد_عربي"))

        captured_script = {}
        popen_kwargs = {}

        mock_proc = MagicMock()
        mock_proc.pid = 555
        mock_proc.poll.return_value = 0
        mock_proc.stdout.readline.side_effect = [
            "جارٍ التحميل في المجلد العربي...\n",
            "100%|██████████| 28.3k/28.3k [00:00<00:00, 90.9MiB/s]\n",
            "25%|██▌       | 152M/610M [00:05<00:15, 30.0MiB/s]\n",
            "60%|██████    | 366M/610M [00:12<00:08, 30.0MiB/s]\n",
            "100%|██████████| 610M/610M [00:20<00:00, 30.5MiB/s]\n",
            "SUCCESS_DOWNLOAD\n",
            "",
        ]

        def fake_popen(cmd, **kwargs):
            popen_kwargs.update(kwargs)
            script_file = cmd[1]
            captured_script["path"] = script_file
            with open(script_file, "r", encoding="utf-8") as sf:
                captured_script["code"] = sf.read()
            return mock_proc

        pcts = []
        done = []
        dl.progress_update.connect(pcts.append)
        dl.finished_download.connect(lambda ok, msg: done.append((ok, msg)))

        with patch.object(DependencyManager, "get_env_dir", return_value=env_dir), \
             patch.object(DependencyManager, "get_engine_python", return_value="python"), \
             patch("subprocess.Popen", side_effect=fake_popen), \
             patch("process_tracker.register_process"), \
             patch("process_tracker.unregister_process"):
            dl.run()

        self.assertEqual(done, [(True, "Success")])
        # 100% from 28.3k download_checks.json was ignored, so 25 -> 60 -> 100 emitted smoothly!
        self.assertEqual(pcts, [0, 25, 60, 100, 100])
        self.assertEqual(popen_kwargs.get("encoding"), "utf-8")
        self.assertEqual(popen_kwargs.get("errors"), "replace")
        self.assertIn("info_only", captured_script["code"])
        self.assertIn("download_model_and_data", captured_script["code"])
        self.assertTrue(captured_script["path"].endswith("_temp_download.py"))
        self.assertFalse(os.path.exists(captured_script["path"]), "Temp download script must be cleaned up")

    # ── 10. Classified Local Error Messages ──────────────────────────────────

    def test_classify_local_error_all_categories(self):
        """classify_local_error cleanly categorizes FFmpeg, VC++, CUDA OOM, Disk, Checksum, Network."""
        i18n.set_language("en")

        s, raw = classify_local_error("FileNotFoundError: FFmpeg is not installed")
        self.assertIn("FFmpeg", s)
        self.assertIn("FileNotFoundError", raw)

        with patch("sys.platform", "win32"):
            s, _ = classify_local_error("ImportError: DLL load failed while importing _C: c10.dll")
            self.assertIn("Visual C++", s)

        s, _ = classify_local_error("torch.cuda.OutOfMemoryError: CUDA out of memory")
        self.assertIn("VRAM", s)

        s, _ = classify_local_error("OSError: [Errno 28] No space left on device")
        self.assertIn("disk space", s.lower())

        s, _ = classify_local_error("ValueError: SHA256 hash mismatch for model file")
        self.assertIn("corrupted", s.lower())

        s, _ = classify_local_error("requests.exceptions.ReadTimeout: HTTPSConnectionPool timed out")
        self.assertIn("network", s.lower())

    # ── 11. Atomic FFmpegDownloader Staging ──────────────────────────────────

    def test_ffmpeg_downloader_atomic_staging_and_incomplete_rejection(self):
        """FFmpegDownloader atomically promotes verified binaries and rejects incomplete archives."""
        bin_dir = os.path.join(self.tmp_dir, "bin")
        os.makedirs(bin_dir, exist_ok=True)

        # Build a valid Windows zip containing both ffmpeg.exe and ffprobe.exe
        good_zip = os.path.join(self.tmp_dir, "good.zip")
        with zipfile.ZipFile(good_zip, "w") as zf:
            zf.writestr("ffmpeg-build/bin/ffmpeg.exe", b"MZ_FAKE_FFMPEG")
            zf.writestr("ffmpeg-build/bin/ffprobe.exe", b"MZ_FAKE_FFPROBE")

        dl_ok = FFmpegDownloader()
        ok_res = []
        dl_ok.finished_download.connect(lambda ok, msg: ok_res.append((ok, msg)))

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch.object(dl_ok, "_download_file", side_effect=lambda url, dst, **kw: shutil.copyfile(good_zip, dst)):
            dl_ok.run()

        self.assertEqual(ok_res, [(True, "Success")])
        self.assertTrue(os.path.isfile(os.path.join(bin_dir, "ffmpeg.exe")))
        self.assertTrue(os.path.isfile(os.path.join(bin_dir, "ffprobe.exe")))

        # Now test incomplete archive missing ffprobe.exe -> fails without polluting bin_dir
        bad_bin_dir = os.path.join(self.tmp_dir, "bad_bin")
        os.makedirs(bad_bin_dir, exist_ok=True)
        bad_zip = os.path.join(self.tmp_dir, "bad.zip")
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("ffmpeg-build/bin/ffmpeg.exe", b"MZ_ONLY_FFMPEG")

        dl_bad = FFmpegDownloader()
        bad_res = []
        dl_bad.finished_download.connect(lambda ok, msg: bad_res.append((ok, msg)))

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bad_bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch.object(dl_bad, "_download_file", side_effect=lambda url, dst, **kw: shutil.copyfile(bad_zip, dst)):
            dl_bad.run()

        self.assertFalse(bad_res[0][0])
        self.assertFalse(os.path.exists(os.path.join(bad_bin_dir, "ffmpeg.exe")))

    # ── 12. MainWindow ffmpeg_overlay Lifecycle & resizeEvent Safety (M2) ────

    def test_main_window_ffmpeg_overlay_resize_and_rail_lock(self):
        """on_ffmpeg_downloaded clears ffmpeg_overlay=None and re-enables rail; subsequent resizeEvent never crashes."""
        with patch.object(MainWindow, "init_threads"), \
             patch.object(MainWindow, "start_auto_update_check"), \
             patch.object(DependencyManager, "has_ffmpeg", return_value=False):
            win = MainWindow()
            self.assertIsNotNone(win.ffmpeg_overlay)
            self.assertFalse(win.stack.isEnabled())
            self.assertFalse(win.rail.isEnabled())

            # Complete FFmpeg download
            win.on_ffmpeg_downloaded(True, "Success")
            QApplication.processEvents()

            self.assertIsNone(win.ffmpeg_overlay)
            self.assertTrue(win.stack.isEnabled())
            self.assertTrue(win.rail.isEnabled())

            # Resize after overlay deletion MUST NOT raise RuntimeError
            ev = QResizeEvent(QSize(1100, 760), QSize(980, 680))
            win.resizeEvent(ev)
            win.close()

    # ── 13. ModelDownloader Double-Download & Settings Clobber Guard (M4) ────

    def test_model_download_double_click_dropzone_and_settings_clobber_guard(self):
        """Active model download disables dropzone, blocks second downloader, and survives update_model_button_state."""
        with patch.object(MainWindow, "init_threads"), \
             patch.object(MainWindow, "start_auto_update_check"), \
             patch.object(DependencyManager, "has_ffmpeg", return_value=True), \
             patch.object(DependencyManager, "has_local_engine", return_value=True), \
             patch.object(DependencyManager, "needs_gpu_engine_upgrade", return_value=False):
            win = MainWindow()
            win.local_section._model_needs_download = True

            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = True

            with patch("ui.main_window.ModelDownloader", return_value=mock_thread) as mock_cls:
                win.download_local_model("model_bs_roformer_ep_317_sdr_12.9755.ckpt", "RoFormer")
                self.assertEqual(mock_cls.call_count, 1)
                self.assertFalse(win.local_section.btn_add.isEnabled())
                if win.local_section.dropzone_widget is not None:
                    self.assertFalse(win.local_section.dropzone_widget.isEnabled())

                # Simulate progress at 42%
                win.local_section.set_download_progress(42, "RoFormer")
                btn_text_mid = win.local_section.btn_add.text()
                self.assertIn("42", btn_text_mid)

                # Second click / DropZone trigger must NOT spawn another ModelDownloader
                win.local_section._on_add_clicked()
                win.download_local_model("model_bs_roformer_ep_317_sdr_12.9755.ckpt", "RoFormer")
                self.assertEqual(mock_cls.call_count, 1)

                # Saving settings calls update_model_button_state(); progress text must NOT be clobbered!
                win.local_section.update_model_button_state()
                self.assertIn("42", win.local_section.btn_add.text())

                # Toggling Light/Dark theme mid-download must preserve progress bar gradient!
                win.local_section.apply_theme("dark")
                self.assertIn("42", win.local_section.btn_add.text())
                self.assertIn("#a7d0be", win.local_section.btn_add.styleSheet())

            win.model_thread = None
            win.close()

    # ── 14. Model Presence Check & Required MDXC .yaml Sidecar (S7) ──────────

    def test_model_presence_requires_non_empty_file_and_yaml_sidecar(self):
        """update_model_button_state verifies non-empty weights AND required .yaml sidecars for MDXC models."""
        cfg = ConfigManager()
        cfg.appdata_dir = self.tmp_dir
        cfg.config_path = os.path.join(self.tmp_dir, "config.json")
        cfg.set("local_model", "SOTA (RoFormer) - Requires High-End GPU")
        qm = QueueManager()
        section = JobQueueSection("Local (GPU)", qm, cfg)

        roformer_dir = os.path.join(self.tmp_dir, "models", "RoFormer")
        os.makedirs(roformer_dir, exist_ok=True)
        ckpt = os.path.join(roformer_dir, "model_bs_roformer_ep_317_sdr_12.9755.ckpt")
        yaml_file = os.path.join(roformer_dir, "model_bs_roformer_ep_317_sdr_12.9755.yaml")

        # 0-byte ckpt -> still needs download
        open(ckpt, "wb").close()
        section.update_model_button_state()
        self.assertTrue(section._model_needs_download)

        # Non-empty ckpt WITHOUT yaml -> still needs download
        with open(ckpt, "wb") as f:
            f.write(b"weights")
        section.update_model_button_state()
        self.assertTrue(section._model_needs_download)

        # Non-empty ckpt WITH non-empty yaml -> installed!
        with open(yaml_file, "w", encoding="utf-8") as f:
            f.write("model: roformer\n")
        section.update_model_button_state()
        self.assertFalse(section._model_needs_download)

        # Kim Vocal 2 ONNX needs only non-empty .onnx (no yaml sidecar)
        cfg.set("local_model", "Fast (Kim Vocal 2)")
        kim_dir = os.path.join(self.tmp_dir, "models", "Kim_Vocal_2")
        os.makedirs(kim_dir, exist_ok=True)
        with open(os.path.join(kim_dir, "Kim_Vocal_2.onnx"), "wb") as f:
            f.write(b"onnx_bytes")
        section.update_model_button_state()
        self.assertFalse(section._model_needs_download)

    # ── 15. GpuUpgradeBanner Bilingual & Busy-Guard ──────────────────────────

    def test_gpu_upgrade_banner_lifecycle_bilingual_and_busy_guard(self):
        """GpuUpgradeBanner renders in EN/AR and refuses upgrade while a local job is active."""
        with patch.object(MainWindow, "init_threads"), \
             patch.object(MainWindow, "start_auto_update_check"), \
             patch.object(DependencyManager, "has_ffmpeg", return_value=True), \
             patch.object(DependencyManager, "has_local_engine", return_value=True), \
             patch.object(DependencyManager, "needs_gpu_engine_upgrade", return_value=True):
            win = MainWindow()
            self.assertIsNotNone(win.gpu_upgrade_banner)
            self.assertFalse(win.gpu_upgrade_banner.isHidden())

            # Bilingual retranslation check
            win.apply_language("en")
            self.assertIn("NVIDIA", win.gpu_upgrade_banner.lbl_msg.text())
            win.apply_language("ar")
            self.assertIn("NVIDIA", win.gpu_upgrade_banner.lbl_msg.text())

            # Add a PENDING local job -> upgrade must also be refused cleanly
            jid_pending = win.queue_manager.add_job("queued.mp3", mode="Local (GPU)")
            with patch.object(QMessageBox, "information") as mock_info, \
                 patch("ui.main_window.EngineDownloader") as mock_ed:
                win.start_gpu_engine_upgrade()
                mock_info.assert_called_once()
                mock_ed.assert_not_called()
            win.queue_manager.delete_job(jid_pending)

            # Add an active local job -> upgrade must be refused cleanly
            jid = win.queue_manager.add_job("song.mp3", mode="Local (GPU)")
            win.queue_manager.update_job(jid, {"status": "PROCESSING_LOCAL"})

            with patch.object(QMessageBox, "information") as mock_info, \
                 patch("ui.main_window.EngineDownloader") as mock_ed:
                win.start_gpu_engine_upgrade()
                mock_info.assert_called_once()
                mock_ed.assert_not_called()

            # Multiline pip error on upgrade failure must be condensed cleanly for inline banner
            win.on_gpu_upgrade_finished(
                False,
                "CUDA PyTorch upgrade failed:\nTraceback...\nrequests.exceptions.ReadTimeout: HTTPSConnectionPool timed out\n" * 5,
            )
            self.assertLessEqual(len(win.gpu_upgrade_banner.lbl_status.text()), 260)
            win.gpu_upgrade_banner.reset_idle()

            # Cleanup active job and verify idle upgrade spawns EngineDownloader(upgrade_to_gpu=True)
            win.queue_manager.delete_job(jid)
            mock_ed_inst = MagicMock()
            mock_ed_inst.isRunning.return_value = False
            with patch("ui.main_window.EngineDownloader", return_value=mock_ed_inst) as mock_ed:
                win.start_gpu_engine_upgrade()
                mock_ed.assert_called_once_with(upgrade_to_gpu=True)
                mock_ed_inst.start.assert_called_once()
                self.assertFalse(win.local_section.isEnabled())

            win.engine_thread = None
            win.close()

    # ── 16. LocalJobProcessor Optional Annotation & Immediate Abort (M1, M5) ─

    def test_local_processor_optional_import_and_immediate_abort_current_job(self):
        """local_processor defines Optional cleanly and abort_current_job kills matching process immediately."""
        self.assertIn("Optional", vars(local_processor))
        qm = QueueManager()
        cfg = ConfigManager()
        proc_thread = LocalJobProcessor(qm, cfg)

        mock_proc = MagicMock()
        mock_proc.pid = 43210
        proc_thread.current_job_id = "job_abc"
        proc_thread.current_process = mock_proc

        with patch("process_tracker.kill_process_tree") as mock_kill:
            # Non-matching job id does nothing
            self.assertFalse(proc_thread.abort_current_job("other_job"))
            mock_kill.assert_not_called()

            # Matching job id kills immediately
            self.assertTrue(proc_thread.abort_current_job("job_abc"))
            mock_kill.assert_called_once_with(43210)
            mock_proc.kill.assert_called_once()

    # ── 17. JobWidget Hardware Baseline Accuracy ─────────────────────────────

    def test_job_widget_uses_cpu_eta_when_gpu_needs_upgrade(self):
        """_has_active_local_gpu returns False when NVIDIA GPU is present but engine is stuck on CPU."""
        with patch.object(DependencyManager, "has_nvidia_gpu", return_value=True), \
             patch.object(DependencyManager, "needs_gpu_engine_upgrade", return_value=True):
            self.assertFalse(_has_active_local_gpu())

        with patch.object(DependencyManager, "has_nvidia_gpu", return_value=True), \
             patch.object(DependencyManager, "needs_gpu_engine_upgrade", return_value=False):
            self.assertTrue(_has_active_local_gpu())

    # ── 18. Stale CPU Torch Repair Uninstall Guard ───────────────────────────

    def test_non_upgrade_install_uninstalls_stale_cpu_torch_before_cuda_install(self):
        """If an existing env has stale CPU torch (e.g. from prior failed upgrade), non-upgrade GPU install uninstalls first."""
        env_dir = os.path.join(self.tmp_dir, "env")
        bin_dir = os.path.join(self.tmp_dir, "bin")
        torch_dir = os.path.join(env_dir, "Lib", "site-packages", "torch")
        os.makedirs(torch_dir, exist_ok=True)
        os.makedirs(bin_dir, exist_ok=True)
        py_exe = os.path.join(env_dir, "python.exe")
        mamba_exe = os.path.join(bin_dir, "micromamba.exe")
        open(py_exe, "w").close()
        open(mamba_exe, "w").close()
        with open(os.path.join(torch_dir, "version.py"), "w", encoding="utf-8") as f:
            f.write("__version__ = '2.15.0+cpu'\ncuda = None\n")

        dl = EngineDownloader(upgrade_to_gpu=False)
        cmds = []

        def fake_popen(cmd, **kwargs):
            cmds.append(cmd)
            proc = MagicMock()
            proc.pid = 999
            proc.returncode = 0
            joined = " ".join(str(x) for x in cmd)
            if "version_info.major" in joined:
                proc.communicate.return_value = ("3.11\n", "")
            elif "cuDriverGetVersion" in joined:
                proc.communicate.return_value = ('{"driver": [12, 6], "device_count": 1, "compute_cap_major": 8, "source": "driver_api"}\n', "")
            elif "torch==" in joined:
                proc.communicate.return_value = ("torch==2.14.1+cu126\ntorchvision==0.29.1+cu126\n", "")
            elif "cuda_available" in joined:
                proc.communicate.return_value = (
                    '{"torch_version": "2.14.1+cu126", "dist_version": "2.14.1+cu126", "cuda": "12.6", "cuda_available": true, "mps_available": false}\n',
                    "",
                )
            else:
                proc.communicate.return_value = ("", "")
            return proc

        results = []
        dl.finished_download.connect(lambda ok, msg: results.append((ok, msg)))

        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_env_dir", return_value=env_dir), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch.object(DependencyManager, "get_engine_python", return_value=py_exe), \
             patch.object(DependencyManager, "has_nvidia_gpu", return_value=True), \
             patch("subprocess.Popen", side_effect=fake_popen), \
             patch("process_tracker.register_process"), \
             patch("process_tracker.unregister_process"):
            dl.run()

        self.assertEqual(results, [(True, "Success")])
        uninstall_calls = [c for c in cmds if "uninstall" in c]
        self.assertEqual(len(uninstall_calls), 1, "Stale CPU torch must be uninstalled before CUDA wheel install")
        self.assertFalse(os.path.exists(os.path.join(env_dir, ".engine_in_progress")))
        self.assertTrue(os.path.exists(os.path.join(env_dir, ".engine_installed")))


class _LocalMirrorHTTPServer:
    """Thread-safe local HTTP/1.1 test server supporting custom Range, stall, 200, 403, and chunked scenarios."""

    def __init__(self, route_handler):
        self._route_handler = route_handler
        self.requests_log = []
        self._log_lock = threading.Lock()
        parent = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                pass

            def _record(self):
                with parent._log_lock:
                    parent.requests_log.append({
                        "method": self.command,
                        "path": self.path,
                        "range": self.headers.get("Range"),
                        "accept_encoding": self.headers.get("Accept-Encoding"),
                    })

            def do_HEAD(self):
                self._record()
                parent._route_handler(self, is_head=True)

            def do_GET(self):
                self._record()
                parent._route_handler(self, is_head=False)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._server.handle_error = lambda request, client_address: None
        self.port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass


def _serve_bytes_range(handler: BaseHTTPRequestHandler, data: bytes, is_head: bool,
                       force_200: bool = False, delay_per_block: float = 0.0,
                       block_size: int = 8192, stop_event: threading.Event = None):
    total = len(data)
    rng = handler.headers.get("Range")
    if rng and not force_200 and rng.startswith("bytes="):
        spec = rng[6:].split(",")[0].strip()
        s_str, e_str = spec.split("-", 1)
        start = int(s_str) if s_str else 0
        end = int(e_str) if e_str else total - 1
        end = min(end, total - 1)
        body = data[start:end + 1]
        handler.send_response(206)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
    else:
        body = data
        handler.send_response(200)
        if not force_200:
            handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()

    if is_head:
        return

    try:
        for i in range(0, len(body), block_size):
            if stop_event is not None and stop_event.is_set():
                return
            if delay_per_block > 0:
                time.sleep(delay_per_block)
            handler.wfile.write(body[i:i + block_size])
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        pass


class TestSegmentedDownloaderAndSpeedTelemetry(unittest.TestCase):
    def setUp(self):
        ModelDownloader.clear_degraded_hosts()
        self.tmp_dir = tempfile.mkdtemp(prefix="ep_seg_dl_")
        self._servers = []

    def tearDown(self):
        ModelDownloader.clear_degraded_hosts()
        for srv in self._servers:
            srv.close()
        self._servers.clear()
        i18n.set_language("ar")
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        qapp = QApplication.instance()
        if qapp:
            qapp.closeAllWindows()
            qapp.processEvents()

    def _start_server(self, handler_fn) -> _LocalMirrorHTTPServer:
        srv = _LocalMirrorHTTPServer(handler_fn)
        self._servers.append(srv)
        return srv

    # ── 1. 4-Worker HTTP 206 Range Assembly + SHA-256 + Accept-Encoding: identity ──

    def test_segmented_4worker_206_range_sha256_and_identity_header(self):
        """Assembles 4-worker HTTP 206 Range chunks, sends Accept-Encoding: identity, and verifies SHA-256."""
        # Non-multiple of chunk_size (64 KiB) to test tail chunk boundary math
        payload = os.urandom(300 * 1024 + 777)
        expected_sha = hashlib.sha256(payload).hexdigest()

        srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, payload, is_head))
        dest = os.path.join(self.tmp_dir, "model.onnx")

        stages = []
        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=64 * 1024,
            min_segmented_size=64 * 1024,
            disk_space_buffer_bytes=0,
            progress_interval=0.05,
        )
        dl.download(
            mirrors=[("github", f"{srv.base_url}/model.onnx")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
            progress_cb=lambda d, tot, bps, st: stages.append((d, tot, bps, st)),
        )

        self.assertTrue(os.path.isfile(dest))
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertFalse(os.path.exists(dest + ".part"))
        self.assertFalse(os.path.exists(dest + ".part.meta"))

        # Verify Accept-Encoding: identity was sent on EVERY request and multiple Range requests were used
        self.assertTrue(len(srv.requests_log) >= 6)
        for req in srv.requests_log:
            self.assertEqual(req["accept_encoding"], "identity")
        range_gets = [r for r in srv.requests_log if r["method"] == "GET" and r["range"]]
        self.assertEqual(len(range_gets), 5)  # 300 KiB + 777 B across 64 KiB chunks = 5 chunks
        self.assertTrue(any(st == "verifying" for _, _, _, st in stages))

        # Idempotent second call must skip network completely!
        prev_count = len(srv.requests_log)
        dl2 = _SegmentedFileDownloader(workers=4, chunk_size=64 * 1024, min_segmented_size=64 * 1024)
        dl2.download(
            mirrors=[("github", f"{srv.base_url}/model.onnx")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        self.assertEqual(len(srv.requests_log), prev_count)

    # ── 2. HTTP 200 OK Fallback Without Offset Corruption ────────────────────

    def test_segmented_http_200_fallback_no_offset_corruption(self):
        """If server advertises Accept-Ranges on HEAD but ignores Range (returns 200 OK), falls back cleanly."""
        payload = os.urandom(200 * 1024 + 123)
        expected_sha = hashlib.sha256(payload).hexdigest()

        def route(h, is_head):
            if is_head:
                h.send_response(200)
                h.send_header("Accept-Ranges", "bytes")
                h.send_header("Content-Length", str(len(payload)))
                h.end_headers()
            else:
                # Ignore Range header and return full 200 OK!
                _serve_bytes_range(h, payload, is_head=False, force_200=True)

        srv = self._start_server(route)
        dest = os.path.join(self.tmp_dir, "fallback_200.ckpt")
        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=64 * 1024,
            min_segmented_size=64 * 1024,
            disk_space_buffer_bytes=0,
        )
        dl.download(
            mirrors=[("github", f"{srv.base_url}/file")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertFalse(os.path.exists(dest + ".part"))

    # ── 3. .part.meta Resume & Mismatch / Truncation Rejection ───────────────

    def test_resume_skips_completed_chunks_and_rejects_mismatched_meta(self):
        """Valid .part + .part.meta downloads only remaining chunks; corrupt/mismatched meta resets cleanly."""
        chunk_sz = 64 * 1024
        payload = os.urandom(chunk_sz * 4)
        expected_sha = hashlib.sha256(payload).hexdigest()

        srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, payload, is_head))
        dest = os.path.join(self.tmp_dir, "resumable.ckpt")
        part = dest + ".part"
        meta = dest + ".part.meta"

        # Pre-populate chunks 0 and 1 on disk
        with open(part, "wb") as f:
            f.write(payload[:chunk_sz * 2])
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "expected_size": len(payload),
                "sha256": expected_sha,
                "chunk_size": chunk_sz,
                "completed": [0, 1],
            }, f)

        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
        )
        dl.download(
            mirrors=[("github", f"{srv.base_url}/resumable.ckpt")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

        # Only chunks 2 and 3 should have been fetched!
        range_headers = [r["range"] for r in srv.requests_log if r["method"] == "GET" and r["range"]]
        self.assertEqual(len(range_headers), 2)
        self.assertIn(f"bytes={2 * chunk_sz}-{3 * chunk_sz - 1}", range_headers)
        self.assertIn(f"bytes={3 * chunk_sz}-{4 * chunk_sz - 1}", range_headers)

        # Subtest B: Truncated .part where file_size < max_completed_end must be rejected and re-downloaded
        os.remove(dest)
        srv.requests_log.clear()
        with open(part, "wb") as f:
            f.write(payload[:chunk_sz])  # Only 1 chunk on disk, while meta claims chunk 2 is done!
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "expected_size": len(payload),
                "sha256": expected_sha,
                "chunk_size": chunk_sz,
                "completed": [0, 2],
            }, f)

        dl2 = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
        )
        dl2.download(
            mirrors=[("github", f"{srv.base_url}/resumable.ckpt")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        range_headers_2 = [r["range"] for r in srv.requests_log if r["method"] == "GET" and r["range"]]
        self.assertEqual(len(range_headers_2), 4, "Truncated .part must discard stale meta and fetch all 4 chunks")

        # Subtest C: Mismatched sha256 in .part.meta must also be rejected
        os.remove(dest)
        srv.requests_log.clear()
        with open(part, "wb") as f:
            f.write(payload[:chunk_sz * 2])
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "expected_size": len(payload),
                "sha256": "0" * 64,
                "chunk_size": chunk_sz,
                "completed": [0, 1],
            }, f)
        dl3 = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
        )
        dl3.download(
            mirrors=[("github", f"{srv.base_url}/resumable.ckpt")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        range_headers_3 = [r["range"] for r in srv.requests_log if r["method"] == "GET" and r["range"]]
        self.assertEqual(len(range_headers_3), 4)

    # ── 4. Slow-ISP (1 Mbps) Zero-False-Abort Safety ─────────────────────────

    def test_slow_isp_1mbps_zero_false_aborts_and_anti_thrash(self):
        """A steady ~125 KiB/s (1 Mbps) connection across 4 workers must NOT trigger false stall/straggler aborts."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 4)
        expected_sha = hashlib.sha256(payload).hexdigest()

        # Each worker delivers 8 KiB every 0.25s = 32 KiB/s per worker (~128 KiB/s aggregate = 1 Mbps)
        def route(h, is_head):
            _serve_bytes_range(h, payload, is_head, delay_per_block=0.12, block_size=4096)

        srv = self._start_server(route)
        dest = os.path.join(self.tmp_dir, "slow_isp.onnx")

        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            read_block_size=4096,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
            true_stall_min_bps=4 * 1024,
            true_stall_seconds=0.45,
            straggler_max_bps=32 * 1024,
            straggler_seconds=0.35,
            straggler_ratio=0.15,
            cdn_failover_seconds=5.0,
            progress_interval=0.1,
        )
        dl.download(
            mirrors=[("github", f"{srv.base_url}/slow.onnx")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

        # Exactly 4 Range GETs = ZERO false aborts/retries!
        range_gets = [r for r in srv.requests_log if r["method"] == "GET" and r["range"]]
        self.assertEqual(len(range_gets), 4, f"Expected 4 range GETs with 0 false aborts, got {len(range_gets)}")

    # ── 5. True-Stall / Low-Speed Cross-CDN Failover (GitHub -> HuggingFace) ─

    def test_cross_cdn_failover_github_to_huggingface_finishes_remaining_chunks(self):
        """When GitHub mirror crawls/stalls, downloader probes HuggingFace and finishes only remaining chunks."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 6)
        expected_sha = hashlib.sha256(payload).hexdigest()
        stop_slow = threading.Event()

        def route_slow_github(h, is_head):
            if is_head:
                _serve_bytes_range(h, payload, is_head=True)
                return
            # Chunk 0 completes fast; all subsequent chunks crawl at ~2 KiB/s (triggers true-stall + failover)
            rng = h.headers.get("Range") or ""
            if rng == f"bytes=0-{chunk_sz - 1}":
                _serve_bytes_range(h, payload, is_head=False)
            else:
                _serve_bytes_range(h, payload, is_head=False, delay_per_block=0.25, block_size=512, stop_event=stop_slow)

        def route_fast_hf(h, is_head):
            _serve_bytes_range(h, payload, is_head=is_head)

        gh_srv = self._start_server(route_slow_github)
        hf_srv = self._start_server(route_fast_hf)
        dest = os.path.join(self.tmp_dir, "failover.onnx")

        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
            true_stall_min_bps=4 * 1024,
            true_stall_seconds=0.4,
            straggler_seconds=0.35,
            cdn_failover_max_bps=150 * 1024,
            cdn_failover_seconds=0.45,
            cdn_failover_stall_count=2,
            progress_interval=0.1,
        )
        try:
            dl.download(
                mirrors=[
                    ("github", f"{gh_srv.base_url}/Kim_Vocal_2.onnx"),
                    ("huggingface", f"{hf_srv.base_url}/Kim_Vocal_2.onnx"),
                ],
                dest_path=dest,
                expected_size=len(payload),
                expected_sha256=expected_sha,
            )
        finally:
            stop_slow.set()

        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

        # HuggingFace must have received requests and completed remaining chunks (NOT chunk 0 which GitHub finished!)
        hf_ranges = [r["range"] for r in hf_srv.requests_log if r["method"] == "GET" and r["range"]]
        self.assertGreater(len(hf_ranges), 0, "Expected cross-CDN failover to HuggingFace mirror")
        self.assertNotIn(f"bytes=0-{chunk_sz - 1}", hf_ranges, "Chunk 0 completed on GitHub should not be re-fetched on HF")

    # ── 6. HTTP 401/403 SAS Token Refresh Under Lock ─────────────────────────

    def test_http_403_sas_token_refresh_recovers_seamlessly(self):
        """HTTP 403 on an expired signed URL triggers a locked re-probe of the original mirror URL and succeeds."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 4)
        expected_sha = hashlib.sha256(payload).hexdigest()
        token_counter = {"n": 0}
        lock = threading.Lock()

        def route(h, is_head):
            if h.path == "/orig":
                with lock:
                    token_counter["n"] += 1
                    tok = token_counter["n"]
                h.send_response(302)
                h.send_header("Location", f"/signed?tok={tok}")
                h.end_headers()
                return
            if h.path == "/signed?tok=1":
                if is_head:
                    _serve_bytes_range(h, payload, is_head=True)
                    return
                # Simulate expired Azure SAS token on Range GET!
                h.send_response(403)
                h.send_header("Content-Length", "0")
                h.end_headers()
                return
            if h.path.startswith("/signed?tok="):
                _serve_bytes_range(h, payload, is_head=is_head)
                return
            h.send_response(404)
            h.end_headers()

        srv = self._start_server(route)
        dest = os.path.join(self.tmp_dir, "sas_refreshed.onnx")
        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
        )
        dl.download(
            mirrors=[("github", f"{srv.base_url}/orig")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        # Initial probe = tok=1, single locked SAS refresh = tok=2 (no 4-way stampede!)
        self.assertEqual(token_counter["n"], 2)

    # ── 7. Content-Length: None Chunked JSON & Corrupt JSON Rejection ────────

    def test_chunked_no_content_length_json_and_corrupt_json_self_heal(self):
        """Handles Transfer-Encoding: chunked (Content-Length: None) JSON and rejects corrupt JSON mirrors."""
        valid_json = json.dumps({"vr_download_list": {"demo": "ok"}}).encode("utf-8")

        def route_corrupt(h, is_head):
            body = b'{"broken": '
            h.send_response(200)
            h.send_header("Content-Length", str(len(body)))
            h.end_headers()
            if not is_head:
                h.wfile.write(body)

        def route_chunked_good(h, is_head):
            h.send_response(200)
            h.send_header("Transfer-Encoding", "chunked")
            h.end_headers()
            if not is_head:
                chunk_hdr = f"{len(valid_json):x}\r\n".encode("ascii")
                h.wfile.write(chunk_hdr + valid_json + b"\r\n0\r\n\r\n")
                h.wfile.flush()

        bad_srv = self._start_server(route_corrupt)
        good_srv = self._start_server(route_chunked_good)
        dest = os.path.join(self.tmp_dir, "download_checks.json")

        # Pre-seed a corrupt existing JSON on disk to verify idempotent pre-check self-healing
        with open(dest, "w", encoding="utf-8") as f:
            f.write("{corrupt_disk_file")

        dl = _SegmentedFileDownloader(disk_space_buffer_bytes=0)
        dl.download(
            mirrors=[
                ("github_raw", f"{bad_srv.base_url}/download_checks.json"),
                ("jsdelivr", f"{good_srv.base_url}/download_checks.json"),
            ],
            dest_path=dest,
            validate_json=True,
            json_required_keys=("vr_download_list",),
            json_min_keys=1,
            resume_enabled=False,
        )
        with open(dest, "r", encoding="utf-8") as f:
            parsed = json.load(f)
        self.assertIn("vr_download_list", parsed)

    # ── 8. SHA-256 Mismatch Cleanup & Single Clean Retry on Next Mirror ──────

    def test_sha256_mismatch_deletes_part_and_retries_cleanly_on_next_mirror(self):
        """SHA-256 mismatch purges .part/.part.meta and succeeds via one clean retry on the next mirror."""
        chunk_sz = 32 * 1024
        good_payload = os.urandom(chunk_sz * 3)
        bad_payload = os.urandom(chunk_sz * 3)
        expected_sha = hashlib.sha256(good_payload).hexdigest()

        bad_srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, bad_payload, is_head))
        good_srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, good_payload, is_head))
        dest = os.path.join(self.tmp_dir, "verified.onnx")

        dl = _SegmentedFileDownloader(
            workers=3,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
        )
        dl.download(
            mirrors=[
                ("github", f"{bad_srv.base_url}/model"),
                ("huggingface", f"{good_srv.base_url}/model"),
            ],
            dest_path=dest,
            expected_size=len(good_payload),
            expected_sha256=expected_sha,
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), good_payload)
        self.assertFalse(os.path.exists(dest + ".part"))
        self.assertFalse(os.path.exists(dest + ".part.meta"))

        # If BOTH mirrors serve corrupt bytes, raises ChecksumMismatchError and leaves no partial junk
        dest2 = os.path.join(self.tmp_dir, "double_bad.onnx")
        dl2 = _SegmentedFileDownloader(
            workers=3,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
        )
        with self.assertRaises(ChecksumMismatchError):
            dl2.download(
                mirrors=[
                    ("github", f"{bad_srv.base_url}/m1"),
                    ("huggingface", f"{bad_srv.base_url}/m2"),
                ],
                dest_path=dest2,
                expected_size=len(good_payload),
                expected_sha256=expected_sha,
            )
        self.assertFalse(os.path.exists(dest2))
        self.assertFalse(os.path.exists(dest2 + ".part"))

    # ── 9. Pre-Flight Disk-Full Abort (Zero Subprocess Fallback) ─────────────

    def test_preflight_disk_full_aborts_without_subprocess_fallback(self):
        """Insufficient disk space fails fast with classified disk error and NEVER spawns audio-separator."""
        dl = ModelDownloader("Kim_Vocal_2.onnx", os.path.join(self.tmp_dir, "models"))
        results = []
        dl.finished_download.connect(lambda ok, msg: results.append((ok, msg)))

        fake_usage = MagicMock(free=10 * 1024 * 1024)  # Only 10 MiB free (< 64 MiB + 64 MiB buffer)
        with patch("shutil.disk_usage", return_value=fake_usage), \
             patch("subprocess.Popen") as mock_popen, \
             patch.object(dl, "_run_separator_subprocess_fallback") as mock_fb:
            # Skip sidecars by pre-populating valid JSONs so we directly hit primary weight disk check
            os.makedirs(dl.models_dir, exist_ok=True)
            for fn, body in (
                ("download_checks.json", {"vr_download_list": {"k": "v"}}),
                ("vr_model_data.json", {"abc": {}}),
                ("mdx_model_data.json", {"def": {}}),
            ):
                with open(os.path.join(dl.models_dir, fn), "w", encoding="utf-8") as f:
                    json.dump(body, f)
            dl.run()

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0][0])
        mock_popen.assert_not_called()
        mock_fb.assert_not_called()
        self.assertIn("no space left", dl.last_error_details.lower())

    # ── 10. Instant Cooperative stop() Cancellation ──────────────────────────

    def test_instant_cooperative_stop_closes_live_sockets_without_fallback(self):
        """Calling stop() mid-download closes live HTTP sockets and exits in < 1.5s without fallback."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 4)
        expected_sha = hashlib.sha256(payload).hexdigest()
        started_transfer = threading.Event()
        release_server = threading.Event()

        def route_blocking(h, is_head):
            if is_head:
                _serve_bytes_range(h, payload, is_head=True)
                return
            started_transfer.set()
            h.send_response(206)
            h.send_header("Accept-Ranges", "bytes")
            h.send_header("Content-Range", f"bytes 0-{chunk_sz - 1}/{len(payload)}")
            h.send_header("Content-Length", str(chunk_sz))
            h.end_headers()
            try:
                h.wfile.write(b"\x00" * 1024)
                h.wfile.flush()
                release_server.wait(timeout=15.0)
            except OSError:
                pass

        srv = self._start_server(route_blocking)
        dest_dir = os.path.join(self.tmp_dir, "cancel_models")
        os.makedirs(dest_dir, exist_ok=True)
        for fn, body in (
            ("download_checks.json", {"vr_download_list": {"k": "v"}}),
            ("vr_model_data.json", {"abc": {}}),
            ("mdx_model_data.json", {"def": {}}),
        ):
            with open(os.path.join(dest_dir, fn), "w", encoding="utf-8") as f:
                json.dump(body, f)

        fake_manifest = {
            "Kim_Vocal_2.onnx": {
                "primary": {
                    "filename": "Kim_Vocal_2.onnx",
                    "size": len(payload),
                    "sha256": expected_sha,
                    "mirrors": [("github", f"{srv.base_url}/Kim_Vocal_2.onnx")],
                },
                "sidecars": [],
            }
        }

        dl = ModelDownloader("Kim_Vocal_2.onnx", dest_dir)
        finished = []
        dl.finished_download.connect(lambda ok, msg: finished.append((ok, msg)))

        def _make_fast_dl():
            return _SegmentedFileDownloader(
                workers=2,
                chunk_size=chunk_sz,
                min_segmented_size=chunk_sz,
                disk_space_buffer_bytes=0,
                cancel_check=dl.isInterruptionRequested,
            )

        with patch.dict(LOCAL_MODEL_MANIFEST, fake_manifest, clear=False), \
             patch.object(dl, "_create_segmented_downloader", side_effect=_make_fast_dl), \
             patch.object(dl, "_run_separator_subprocess_fallback") as mock_fb:
            dl.start()
            self.assertTrue(started_transfer.wait(timeout=5.0), "Worker never reached live HTTP stream")
            t0 = time.monotonic()
            dl.stop()
            elapsed = time.monotonic() - t0
            release_server.set()
            dl.wait(2000)

        self.assertLess(elapsed, 2.0, f"stop() took too long ({elapsed:.2f}s); sockets did not close promptly")
        self.assertFalse(dl.isRunning())
        self.assertEqual(finished, [], "Cancelled download must not emit finished_download failure")
        mock_fb.assert_not_called()

    # ── 11. Windows Defender PermissionError Atomic Promote Retry ────────────

    def test_atomic_replace_retries_on_windows_defender_permission_error(self):
        """_atomic_replace_file retries transient PermissionError and succeeds once lock releases."""
        src = os.path.join(self.tmp_dir, "src.part")
        dst = os.path.join(self.tmp_dir, "dst.onnx")
        with open(src, "wb") as f:
            f.write(b"verified_model")

        real_replace = os.replace
        attempts = {"n": 0}

        def flaky_replace(a, b):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise PermissionError("Windows Defender scanning file")
            return real_replace(a, b)

        with patch("os.replace", side_effect=flaky_replace):
            _atomic_replace_file(src, dst, max_attempts=5, retry_delay=0.01)

        self.assertEqual(attempts["n"], 3)
        self.assertTrue(os.path.isfile(dst))

    # ── 12. Zero-Subprocess Checksum Loader ──────────────────────────────────

    def test_load_installed_model_checksums_parses_sha256_schema(self):
        """load_installed_model_checksums reads audio_separator/model-checksums.json without subprocesses."""
        sp = os.path.join(self.tmp_dir, "site-packages")
        as_dir = os.path.join(sp, "audio_separator")
        os.makedirs(as_dir, exist_ok=True)
        fake_hash = "a" * 64
        with open(os.path.join(as_dir, "model-checksums.json"), "w", encoding="utf-8") as f:
            json.dump({"_comment": "test", "sha256": {"Kim_Vocal_2.onnx": fake_hash}}, f)

        with patch.object(DependencyManager, "get_site_packages_dirs", return_value=[sp]):
            loaded = load_installed_model_checksums()
        self.assertEqual(loaded.get("Kim_Vocal_2.onnx"), fake_hash)

    # ── 13. FFmpegDownloader Routed Through _SegmentedFileDownloader ─────────

    def test_ffmpeg_downloader_uses_segmented_range_transfer(self):
        """FFmpegDownloader downloads archive via HTTP 206 Range and atomically promotes ffmpeg/ffprobe."""
        bin_dir = os.path.join(self.tmp_dir, "ff_bin")
        os.makedirs(bin_dir, exist_ok=True)

        zip_path = os.path.join(self.tmp_dir, "big_ffmpeg.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("ffmpeg-master/bin/ffmpeg.exe", b"MZ" + os.urandom(140 * 1024))
            zf.writestr("ffmpeg-master/bin/ffprobe.exe", b"MZ" + os.urandom(140 * 1024))
        with open(zip_path, "rb") as f:
            zip_bytes = f.read()

        srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, zip_bytes, is_head))
        dl = FFmpegDownloader()
        pcts = []
        done = []
        dl.progress_update.connect(pcts.append)
        dl.finished_download.connect(lambda ok, msg: done.append((ok, msg)))

        real_cls = _SegmentedFileDownloader
        def _small_chunk_factory(**kwargs):
            kwargs.setdefault("chunk_size", 64 * 1024)
            kwargs.setdefault("min_segmented_size", 64 * 1024)
            kwargs.setdefault("disk_space_buffer_bytes", 0)
            return real_cls(**kwargs)

        orig_download_file = dl._download_file
        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch("dependency_manager._SegmentedFileDownloader", side_effect=_small_chunk_factory), \
             patch.object(
                 dl,
                 "_download_file",
                 side_effect=lambda _url, dst, progress_range=(0, 100): orig_download_file(
                     f"{srv.base_url}/ffmpeg.zip", dst, progress_range=progress_range
                 ),
             ):
            dl.run()

        self.assertEqual(done, [(True, "Success")])
        self.assertTrue(os.path.isfile(os.path.join(bin_dir, "ffmpeg.exe")))
        self.assertTrue(os.path.isfile(os.path.join(bin_dir, "ffprobe.exe")))
        range_gets = [r for r in srv.requests_log if r["method"] == "GET" and r["range"]]
        self.assertGreaterEqual(len(range_gets), 4, "FFmpegDownloader should use segmented HTTP 206 Range requests")
        self.assertIn(100, pcts)

    # ── 14. Live Speed Telemetry UI & Theme / Language Switch Preservation ───

    def test_ui_download_speed_telemetry_verifying_and_language_theme_preservation(self):
        """JobQueueSection renders % + MB/s and Verifying state, preserved across theme and EN/AR switches."""
        cfg = ConfigManager()
        cfg.appdata_dir = self.tmp_dir
        cfg.config_path = os.path.join(self.tmp_dir, "config.json")
        qm = QueueManager()
        section = JobQueueSection("Local (GPU)", qm, cfg)
        section._model_needs_download = True
        section.set_model_downloading(True)

        # English with speed
        i18n.set_language("en")
        section.set_download_progress(48, "Kim Vocal 2", "14.2 MB/s")
        self.assertIn("48%", section.btn_add.text())
        self.assertIn("14.2 MB/s", section.btn_add.text())

        # Theme toggle must preserve cached speed!
        section.apply_theme("dark")
        self.assertIn("48%", section.btn_add.text())
        self.assertIn("14.2 MB/s", section.btn_add.text())

        # Language switch to Arabic must preserve cached speed and flip RTL gradient
        i18n.set_language("ar")
        section.retranslate_ui()
        self.assertIn("48", section.btn_add.text())
        self.assertIn("14.2 MB/s", section.btn_add.text())
        self.assertIn("x1:1", section.btn_add.styleSheet())

        # Verifying sentinel translates cleanly in both AR and EN
        section.set_download_progress(100, "Kim Vocal 2", "__VERIFYING__")
        self.assertIn("التحقق", section.btn_add.text())
        i18n.set_language("en")
        section.retranslate_ui()
        self.assertIn("Verifying", section.btn_add.text())

        # Reset clears cached speed so subsequent empty-speed calls use btn_downloading_model
        section.reset_download_progress()
        section.set_download_progress(20, "Kim Vocal 2")
        self.assertIn("Downloading Kim Vocal 2... 20%", section.btn_add.text())
        self.assertNotIn("MB/s", section.btn_add.text())

    # ── 15. Relative Straggler Watchdog Recovery ─────────────────────────────

    def test_relative_straggler_watchdog_aborts_wedged_worker_and_requeues(self):
        """A single wedged worker (<32 KiB/s and <15% of fast peers) is aborted and re-queued cleanly."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 12)
        expected_sha = hashlib.sha256(payload).hexdigest()
        chunk0_hits = {"n": 0}
        hit_lock = threading.Lock()
        stop_wedged = threading.Event()

        def route(h, is_head):
            if is_head:
                _serve_bytes_range(h, payload, is_head=True)
                return
            rng = h.headers.get("Range") or ""
            if rng == f"bytes=0-{chunk_sz - 1}":
                with hit_lock:
                    chunk0_hits["n"] += 1
                    hit_num = chunk0_hits["n"]
                if hit_num == 1:
                    # First attempt on chunk 0 crawls at ~8 KiB/s (> 4 KiB/s true-stall, < 32 KiB/s straggler)
                    _serve_bytes_range(h, payload, is_head=False, delay_per_block=0.125, block_size=1024, stop_event=stop_wedged)
                    return
            # All other chunks (and chunk 0 retry) run fast (~100 KiB/s+ per worker across 11 chunks)
            _serve_bytes_range(h, payload, is_head=False, delay_per_block=0.02, block_size=8192)

        srv = self._start_server(route)
        dest = os.path.join(self.tmp_dir, "straggler.onnx")
        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            read_block_size=1024,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
            true_stall_min_bps=4 * 1024,
            true_stall_seconds=5.0,   # Keep true-stall high so ONLY relative straggler can fire!
            straggler_max_bps=32 * 1024,
            straggler_seconds=0.35,
            straggler_ratio=0.15,
            cdn_failover_seconds=5.0,
            progress_interval=0.1,
        )
        try:
            dl.download(
                mirrors=[("github", f"{srv.base_url}/straggler.onnx")],
                dest_path=dest,
                expected_size=len(payload),
                expected_sha256=expected_sha,
            )
        finally:
            stop_wedged.set()

        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertGreaterEqual(chunk0_hits["n"], 2, "Straggler watchdog should have aborted and re-queued chunk 0")

    # ── 16. Resumed Download Speed Strictly Excludes Resumed Bytes ───────────

    def test_resumed_download_speed_excludes_resumed_bytes(self):
        """Speed telemetry must reflect only session-transferred bytes, not pre-existing resumed chunks."""
        chunk_sz = 64 * 1024
        payload = os.urandom(chunk_sz * 10)  # 640 KiB total
        expected_sha = hashlib.sha256(payload).hexdigest()

        # Pre-seed 9 of 10 chunks (576 KiB resumed), leaving only 1 chunk (64 KiB) to transfer at ~64 KiB/s
        dest = os.path.join(self.tmp_dir, "resume_speed.ckpt")
        with open(dest + ".part", "wb") as f:
            f.write(payload[:chunk_sz * 9])
        with open(dest + ".part.meta", "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "expected_size": len(payload),
                "sha256": expected_sha,
                "chunk_size": chunk_sz,
                "completed": list(range(9)),
            }, f)

        # Serve remaining 64 KiB at ~64 KiB/s (16 KiB every 0.25s = ~1.0s)
        srv = self._start_server(
            lambda h, is_head: _serve_bytes_range(h, payload, is_head, delay_per_block=0.12, block_size=8192)
        )
        observed_speeds = []
        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            read_block_size=8192,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
            progress_interval=0.1,
        )
        dl.download(
            mirrors=[("github", f"{srv.base_url}/resume_speed.ckpt")],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
            progress_cb=lambda d, tot, bps, st: observed_speeds.append(bps) if st == "downloading" and bps > 0 else None,
        )
        self.assertTrue(len(observed_speeds) > 0)
        # If resumed 576 KiB were included, speed would spike > 500 KiB/s; session-only must stay < 250 KiB/s
        self.assertLess(max(observed_speeds), 250 * 1024)

    # ── 17. FFmpegDownloader Instant Cooperative stop() Cancellation ─────────

    def test_ffmpeg_downloader_stop_cancels_live_socket_immediately(self):
        """Calling FFmpegDownloader.stop() aborts active HTTP sockets in < 2.0s without error."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 4)
        started_transfer = threading.Event()
        release_server = threading.Event()

        def route_blocking(h, is_head):
            if is_head:
                _serve_bytes_range(h, payload, is_head=True)
                return
            started_transfer.set()
            h.send_response(206)
            h.send_header("Accept-Ranges", "bytes")
            h.send_header("Content-Range", f"bytes 0-{chunk_sz - 1}/{len(payload)}")
            h.send_header("Content-Length", str(chunk_sz))
            h.end_headers()
            try:
                h.wfile.write(b"\x00" * 1024)
                h.wfile.flush()
                release_server.wait(timeout=15.0)
            except OSError:
                pass

        srv = self._start_server(route_blocking)
        bin_dir = os.path.join(self.tmp_dir, "ff_cancel_bin")
        os.makedirs(bin_dir, exist_ok=True)
        dl = FFmpegDownloader()
        finished = []
        dl.finished_download.connect(lambda ok, msg: finished.append((ok, msg)))

        real_cls = _SegmentedFileDownloader
        def _small_factory(**kwargs):
            kwargs.setdefault("chunk_size", chunk_sz)
            kwargs.setdefault("min_segmented_size", chunk_sz)
            kwargs.setdefault("disk_space_buffer_bytes", 0)
            return real_cls(**kwargs)

        orig_download_file = dl._download_file
        with patch("sys.platform", "win32"), \
             patch.object(DependencyManager, "get_bin_dir", return_value=bin_dir), \
             patch.object(DependencyManager, "get_appdata_dir", return_value=self.tmp_dir), \
             patch("dependency_manager._SegmentedFileDownloader", side_effect=_small_factory), \
             patch.object(
                 dl,
                 "_download_file",
                 side_effect=lambda _url, dst, progress_range=(0, 100): orig_download_file(
                     f"{srv.base_url}/ffmpeg.zip", dst, progress_range=progress_range
                 ),
             ):
            dl.start()
            self.assertTrue(started_transfer.wait(timeout=5.0))
            t0 = time.monotonic()
            dl.stop()
            elapsed = time.monotonic() - t0
            release_server.set()
            dl.wait(2000)

        self.assertLess(elapsed, 2.0, f"FFmpegDownloader.stop() took {elapsed:.2f}s")
        self.assertFalse(dl.isRunning())
        self.assertEqual(finished, [])

    # ── 18. HTTP 500 Failover Race Guard (Never Abandon Healthy Mirror) ──────

    def test_http_500_failover_during_probe_succeeds_without_abandoning_mirror(self):
        """HTTP 500 bursts on mirror 0 must fail over cleanly to healthy mirror 1 without racing probe."""
        chunk_sz = 16 * 1024
        payload = os.urandom(chunk_sz * 10)
        expected_sha = hashlib.sha256(payload).hexdigest()
        hits = {"m0": 0, "m1": 0}
        hit_lock = threading.Lock()

        def route(h, is_head):
            if is_head:
                if h.path == "/m1":
                    time.sleep(0.03)  # Keep probe in flight while workers retry m0
                _serve_bytes_range(h, payload, is_head=True)
                return
            if h.path == "/m0":
                with hit_lock:
                    hits["m0"] += 1
                h.send_response(500)
                h.send_header("Content-Length", "0")
                h.end_headers()
                return
            with hit_lock:
                hits["m1"] += 1
            _serve_bytes_range(h, payload, is_head=False)

        srv = self._start_server(route)
        dest = os.path.join(self.tmp_dir, "failover_500.onnx")
        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
            max_chunk_retries=4,
        )
        dl.download(
            mirrors=[
                ("github", f"{srv.base_url}/m0"),
                ("huggingface", f"{srv.base_url}/m1"),
            ],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertGreater(hits["m1"], 0)
        self.assertLess(hits["m0"], 40, f"Unexpected HTTP 500 retry storm: {hits['m0']} hits")

    # ── 19. Single-Stream Stall Window Not Corrupted By Speed Window ─────────

    def test_single_stream_slow_steady_speed_above_stall_threshold_no_false_abort(self):
        """Single-stream at 8 KiB/s (> 4 KiB/s stall threshold) must not false-abort when progress_cb is set."""
        class _ShortSpeedWinDL(_SegmentedFileDownloader):
            SPEED_WINDOW_SECONDS = 0.4

        payload = b"S" * (14 * 1024)  # 14 KiB at ~8 KiB/s ~= 1.75s > true_stall_seconds=1.2s

        def route(h, is_head):
            _serve_bytes_range(h, payload, is_head=is_head, force_200=True, delay_per_block=0.0625, block_size=512)

        srv = self._start_server(route)
        dest = os.path.join(self.tmp_dir, "single_slow.bin")
        speeds = []
        dl = _ShortSpeedWinDL(
            workers=1,
            read_block_size=512,
            min_segmented_size=1024 * 1024,
            disk_space_buffer_bytes=0,
            true_stall_min_bps=4 * 1024,
            true_stall_seconds=1.2,
            progress_interval=0.1,
        )
        dl.download(
            mirrors=[("github", f"{srv.base_url}/single")],
            dest_path=dest,
            expected_size=len(payload),
            progress_cb=lambda d, tot, bps, st: speeds.append(bps),
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertTrue(any(s > 0 for s in speeds))

    # ── 20. Slow-ISP 4-Mirror Anti-Thrash Guard ──────────────────────────────

    def test_slow_isp_4mirror_anti_thrash_does_not_ping_pong_tried_cdns(self):
        """On a slow ISP across 4 mirrors (2 GitHub + 2 HF), tries each CDN once and never ping-pongs."""
        chunk_sz = 16 * 1024
        payload = os.urandom(chunk_sz * 10)
        expected_sha = hashlib.sha256(payload).hexdigest()
        hits = {"m0": 0, "m1": 0, "m2": 0, "m3": 0}
        hit_lock = threading.Lock()

        def route(h, is_head):
            key = h.path.strip("/")
            if not is_head and key in hits:
                with hit_lock:
                    hits[key] += 1
            # ~25 KiB/s per worker (~100 KiB/s total < 150 KiB/s failover threshold)
            _serve_bytes_range(h, payload, is_head=is_head, delay_per_block=0.08, block_size=2048)

        srv = self._start_server(route)
        dest = os.path.join(self.tmp_dir, "antithrash.onnx")
        dl = _SegmentedFileDownloader(
            workers=4,
            chunk_size=chunk_sz,
            read_block_size=2048,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
            cdn_failover_max_bps=150 * 1024,
            cdn_failover_seconds=0.35,
            true_stall_seconds=5.0,
            straggler_seconds=5.0,
            progress_interval=0.1,
        )
        dl.download(
            mirrors=[
                ("github", f"{srv.base_url}/m0"),
                ("huggingface", f"{srv.base_url}/m1"),
                ("huggingface", f"{srv.base_url}/m2"),
                ("github", f"{srv.base_url}/m3"),
            ],
            dest_path=dest,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        # Must try m0 (github) -> m1 (huggingface) and NEVER thrash onto m2 or m3
        self.assertGreater(hits["m0"], 0)
        self.assertGreater(hits["m1"], 0)
        self.assertEqual(hits["m2"], 0, f"Thrashed to second HF mirror: {hits}")
        self.assertEqual(hits["m3"], 0, f"Ping-ponged back to second GitHub mirror: {hits}")

    # ── 21. Pre-Header HEAD Cancel & Real HTTPS SSLSocket Mid-Stream Cancel ──

    def test_pre_header_head_probe_and_https_tls_cancel_aborts_immediately(self):
        """cancel() aborts both pre-header blocking HEAD probes and live HTTPS SSLSocket streams in < 1.5s."""
        # Part A: Pre-header blocking HEAD probe
        started_head = threading.Event()
        release_head = threading.Event()

        def route_head_hang(h, is_head):
            started_head.set()
            release_head.wait(timeout=10.0)
            h.send_response(200)
            h.end_headers()

        srv_head = self._start_server(route_head_hang)
        dl_head = _SegmentedFileDownloader(probe_read_timeout=10.0, connect_timeout=10.0)
        errs_head = []

        def _run_head():
            try:
                dl_head.download(
                    mirrors=[("github", f"{srv_head.base_url}/hang")],
                    dest_path=os.path.join(self.tmp_dir, "hang.bin"),
                )
            except Exception as exc:
                errs_head.append(exc)

        th_head = threading.Thread(target=_run_head)
        th_head.start()
        self.assertTrue(started_head.wait(timeout=4.0))
        time.sleep(0.05)
        t0 = time.monotonic()
        dl_head.cancel()
        th_head.join(timeout=3.0)
        dt_head = time.monotonic() - t0
        release_head.set()
        self.assertFalse(th_head.is_alive(), "Pre-header HEAD probe thread stayed blocked after cancel()")
        self.assertLess(dt_head, 1.5)
        self.assertTrue(errs_head and isinstance(errs_head[0], DownloadCancelledError))

        # Part B: Real HTTPS (ssl.SSLSocket) mid-stream cancellation
        import datetime
        import ipaddress
        import ssl
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subj)
            .issuer_name(subj)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now_utc - datetime.timedelta(minutes=5))
            .not_valid_after(now_utc + datetime.timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPAddress("127.0.0.1") if hasattr(ipaddress, "IPAddress") else ipaddress.IPv4Address("127.0.0.1"))]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        cert_path = os.path.join(self.tmp_dir, "tls_cert.pem")
        key_path = os.path.join(self.tmp_dir, "tls_key.pem")
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(key_path, "wb") as f:
            f.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption(),
                )
            )

        started_tls = threading.Event()
        release_tls = threading.Event()
        tls_total = 128 * 1024

        class _TLSHandler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_HEAD(self):
                self.send_response(200)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(tls_total))
                self.end_headers()

            def do_GET(self):
                started_tls.set()
                self.send_response(206)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes 0-32767/{tls_total}")
                self.send_header("Content-Length", "32768")
                self.end_headers()
                try:
                    self.wfile.write(b"T" * 1024)
                    self.wfile.flush()
                    release_tls.wait(timeout=10.0)
                except OSError:
                    pass

        tls_srv = ThreadingHTTPServer(("127.0.0.1", 0), _TLSHandler)
        tls_srv.daemon_threads = True
        tls_srv.handle_error = lambda *a: None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        tls_srv.socket = ctx.wrap_socket(tls_srv.socket, server_side=True)
        tls_port = tls_srv.server_address[1]
        threading.Thread(target=tls_srv.serve_forever, daemon=True).start()

        try:
            dl_tls = _SegmentedFileDownloader(
                workers=4,
                chunk_size=32 * 1024,
                min_segmented_size=32 * 1024,
                disk_space_buffer_bytes=0,
            )
            orig_get_sess = dl_tls._get_session

            def _verified_sess():
                s = orig_get_sess()
                s.trust_env = False
                s.verify = cert_path
                return s

            dl_tls._get_session = _verified_sess
            errs_tls = []

            def _run_tls():
                try:
                    dl_tls.download(
                        mirrors=[("github", f"https://127.0.0.1:{tls_port}/tls_model")],
                        dest_path=os.path.join(self.tmp_dir, "tls_model.onnx"),
                        expected_size=tls_total,
                    )
                except Exception as exc:
                    errs_tls.append(exc)

            th_tls = threading.Thread(target=_run_tls)
            th_tls.start()
            self.assertTrue(started_tls.wait(timeout=4.0))
            time.sleep(0.05)
            t1 = time.monotonic()
            dl_tls.cancel()
            th_tls.join(timeout=3.0)
            dt_tls = time.monotonic() - t1
            release_tls.set()
            self.assertFalse(th_tls.is_alive(), "HTTPS SSLSocket download stayed blocked after cancel()")
            self.assertLess(dt_tls, 1.5)
            self.assertTrue(errs_tls and isinstance(errs_tls[0], DownloadCancelledError))
        finally:
            release_tls.set()
            try:
                tls_srv.shutdown()
                tls_srv.server_close()
            except Exception:
                pass

    # ── 22. Installed Checksum Override (exp_size=None) + Retry Progress Reset ─

    def test_installed_checksum_override_and_retry_resets_progress(self):
        """When installed model-checksums.json differs from manifest, ignores stale size and resets pct on retry."""
        chunk_sz = 32 * 1024
        bad_payload = os.urandom(chunk_sz * 3)
        good_payload = os.urandom(chunk_sz * 3 + 512)  # Different size than manifest!
        good_sha = hashlib.sha256(good_payload).hexdigest()

        bad_srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, bad_payload, is_head))
        good_srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, good_payload, is_head))

        dest_dir = os.path.join(self.tmp_dir, "override_models")
        os.makedirs(dest_dir, exist_ok=True)
        fake_manifest = {
            "Kim_Vocal_2.onnx": {
                "primary": {
                    "filename": "Kim_Vocal_2.onnx",
                    "size": 66759214,  # Stale hardcoded size must be ignored when installed SHA differs
                    "sha256": "1" * 64,
                    "mirrors": [
                        ("github", f"{bad_srv.base_url}/Kim_Vocal_2.onnx"),
                        ("huggingface", f"{good_srv.base_url}/Kim_Vocal_2.onnx"),
                    ],
                },
                "sidecars": [],
            }
        }

        dl = ModelDownloader("Kim_Vocal_2.onnx", dest_dir)
        details = []
        done = []
        dl.progress_detail.connect(lambda pct, spd: details.append((pct, spd)))
        dl.finished_download.connect(lambda ok, msg: done.append((ok, msg)))

        def _make_dl():
            return _SegmentedFileDownloader(
                workers=3,
                chunk_size=chunk_sz,
                min_segmented_size=chunk_sz,
                disk_space_buffer_bytes=0,
                progress_interval=0.05,
                cancel_check=dl.isInterruptionRequested,
            )

        with patch.dict(LOCAL_MODEL_MANIFEST, fake_manifest, clear=False), \
             patch("dependency_manager.load_installed_model_checksums", return_value={"Kim_Vocal_2.onnx": good_sha}), \
             patch.object(dl, "_create_segmented_downloader", side_effect=_make_dl):
            dl.run()

        self.assertEqual(done, [(True, "Success")])
        with open(os.path.join(dest_dir, "Kim_Vocal_2.onnx"), "rb") as f:
            self.assertEqual(f.read(), good_payload)
        # Verify verifying occurred, then progress reset to 0 on checksum retry, then finished at 100
        verifying_indices = [i for i, (_, spd) in enumerate(details) if spd == "__VERIFYING__"]
        self.assertGreaterEqual(len(verifying_indices), 2)
        between = [pct for pct, _ in details[verifying_indices[0] + 1:verifying_indices[1]]]
        self.assertIn(0, between, f"Expected progress reset to 0 on checksum retry, got {between}")

    # ── 23. Mid-Download VPN / Cloudflare WARP Outage Recovery (Resume + Speed) ──

    @staticmethod
    def _drop_client_connection(h: BaseHTTPRequestHandler) -> None:
        """Immediately terminates client TCP socket with RST (simulating VPN/WARP drop)."""
        import socket as _sock
        import struct as _struct
        h.close_connection = True
        try:
            h.connection.setsockopt(_sock.SOL_SOCKET, _sock.SO_LINGER, _struct.pack("ii", 1, 0))
        except Exception:
            pass
        for obj in (getattr(h, "wfile", None), getattr(h, "rfile", None), getattr(h, "connection", None)):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass

    def test_vpn_outage_recovery_resumes_part_without_fallback_and_preserves_speed(self):
        """Mid-download VPN/WARP outage enters reconnecting, resumes existing .part without fallback, and restores live speed."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 8)  # 256 KiB = 8 chunks
        expected_sha = hashlib.sha256(payload).hexdigest()

        outage_lock = threading.Lock()
        outage_state = {"down": False, "triggered": False, "chunks_served": 0}
        range_hits = []

        def route(h, is_head):
            with outage_lock:
                is_down = outage_state["down"]
            if is_down:
                self._drop_client_connection(h)
                return

            if is_head:
                _serve_bytes_range(h, payload, is_head=True)
                return

            rng = h.headers.get("Range") or ""
            with outage_lock:
                range_hits.append(rng)
                outage_state["chunks_served"] += 1
                if not outage_state["triggered"] and outage_state["chunks_served"] == 3:
                    # Trigger a transient ~0.6s total network outage after first 2 chunks are served!
                    outage_state["triggered"] = True
                    outage_state["down"] = True
                    def _restore():
                        time.sleep(0.6)
                        with outage_lock:
                            outage_state["down"] = False
                    threading.Thread(target=_restore, daemon=True).start()
                    self._drop_client_connection(h)
                    return
            _serve_bytes_range(h, payload, is_head=False, delay_per_block=0.01, block_size=8192)

        srv = self._start_server(route)
        dest_dir = os.path.join(self.tmp_dir, "warp_recovery_models")
        os.makedirs(dest_dir, exist_ok=True)
        # Pre-seed a stale audio-separator .partial file to ensure it gets cleaned up!
        stale_partial = os.path.join(dest_dir, "model_bs_roformer_ep_317_sdr_12.9755.ckpt.99999.partial")
        with open(stale_partial, "wb") as f:
            f.write(b"stale_subprocess_junk")

        fake_manifest = {
            "model_bs_roformer_ep_317_sdr_12.9755.ckpt": {
                "primary": {
                    "filename": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
                    "size": len(payload),
                    "sha256": expected_sha,
                    "mirrors": [
                        ("github", f"{srv.base_url}/gh1"),
                        ("huggingface", f"{srv.base_url}/hf1"),
                    ],
                },
                "sidecars": [],
            }
        }

        dl = ModelDownloader("model_bs_roformer_ep_317_sdr_12.9755.ckpt", dest_dir)
        details = []
        done = []
        dl.progress_detail.connect(lambda pct, spd: details.append((pct, spd)))
        dl.finished_download.connect(lambda ok, msg: done.append((ok, msg)))

        def _make_dl():
            return _SegmentedFileDownloader(
                workers=2,
                chunk_size=chunk_sz,
                read_block_size=8192,
                min_segmented_size=chunk_sz,
                disk_space_buffer_bytes=0,
                max_chunk_retries=1,
                progress_interval=0.05,
                network_recovery_backoff=(0.2, 0.3, 0.4),
                cancel_check=dl.isInterruptionRequested,
            )

        with patch.dict(LOCAL_MODEL_MANIFEST, fake_manifest, clear=False), \
             patch("dependency_manager.load_installed_model_checksums", return_value={}), \
             patch.object(dl, "_create_segmented_downloader", side_effect=_make_dl), \
             patch.object(dl, "_run_separator_subprocess_fallback") as mock_fb:
            dl.run()

        self.assertEqual(done, [(True, "Success")])
        mock_fb.assert_not_called()
        final_path = os.path.join(dest_dir, "model_bs_roformer_ep_317_sdr_12.9755.ckpt")
        with open(final_path, "rb") as f:
            self.assertEqual(f.read(), payload)
        # Stale .partial, .part, and .part.meta must all be cleaned up!
        self.assertFalse(os.path.exists(stale_partial))
        self.assertFalse(os.path.exists(final_path + ".part"))
        self.assertFalse(os.path.exists(final_path + ".part.meta"))
        # Reconnecting state must have preserved progress (> 0%) and live speed must appear after recovery
        reconnecting_events = [(p, s) for p, s in details if s == "__RECONNECTING__"]
        self.assertTrue(len(reconnecting_events) >= 1, f"Expected __RECONNECTING__ telemetry, got {details}")
        self.assertGreater(reconnecting_events[0][0], 0, "Reconnecting must preserve completed % rather than resetting to 0")
        last_reconn_idx = max(i for i, (_, s) in enumerate(details) if s == "__RECONNECTING__")
        post_recovery_speeds = [s for _, s in details[last_reconn_idx + 1:] if "B/s" in s]
        self.assertTrue(len(post_recovery_speeds) > 0, f"Expected live speed telemetry after VPN recovery, got {details[last_reconn_idx:]}")

    # ── 24. Persistent Outage Preserves .part (No Subprocess Fallback) & Resumes ──

    def test_persistent_network_outage_preserves_part_and_skips_subprocess_fallback(self):
        """If network stays down past all recovery rounds, keeps .part/.part.meta for resume without spawning audio-separator."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 6)
        expected_sha = hashlib.sha256(payload).hexdigest()

        state = {"down": False, "served": 0}
        lock = threading.Lock()
        first_run_ranges = []
        second_run_ranges = []
        run_tag = {"n": 1}

        dest_dir = os.path.join(self.tmp_dir, "offline_resume_models")
        os.makedirs(dest_dir, exist_ok=True)
        part_file = os.path.join(dest_dir, "Kim_Vocal_2.onnx.part")
        meta_file = os.path.join(dest_dir, "Kim_Vocal_2.onnx.part.meta")

        def _saved_chunk_count() -> int:
            if not os.path.isfile(meta_file):
                return 0
            try:
                with open(meta_file, "r", encoding="utf-8") as mf:
                    return len(json.load(mf).get("completed", []))
            except Exception:
                return 0

        def route(h, is_head):
            with lock:
                if state["down"]:
                    self._drop_client_connection(h)
                    return
                if not is_head:
                    rng = h.headers.get("Range") or ""
                    if run_tag["n"] == 1:
                        first_run_ranges.append(rng)
                    else:
                        second_run_ranges.append(rng)
                    state["served"] += 1
                    if run_tag["n"] == 1 and _saved_chunk_count() >= 2:
                        state["down"] = True
                        self._drop_client_connection(h)
                        return
            _serve_bytes_range(h, payload, is_head=is_head)

        srv = self._start_server(route)
        fake_manifest = {
            "Kim_Vocal_2.onnx": {
                "primary": {
                    "filename": "Kim_Vocal_2.onnx",
                    "size": len(payload),
                    "sha256": expected_sha,
                    "mirrors": [("github", f"{srv.base_url}/model")],
                },
                "sidecars": [],
            }
        }

        # Run 1: Network dies permanently mid-download -> fails cleanly, NEVER falls back, preserves .part + .part.meta
        dl1 = ModelDownloader("Kim_Vocal_2.onnx", dest_dir)
        done1 = []
        dl1.finished_download.connect(lambda ok, msg: done1.append((ok, msg)))

        def _make_dl1():
            return _SegmentedFileDownloader(
                workers=2,
                chunk_size=chunk_sz,
                min_segmented_size=chunk_sz,
                disk_space_buffer_bytes=0,
                max_chunk_retries=1,
                network_recovery_backoff=(0.05,),
                cancel_check=dl1.isInterruptionRequested,
            )

        with patch.dict(LOCAL_MODEL_MANIFEST, fake_manifest, clear=False), \
             patch("dependency_manager.load_installed_model_checksums", return_value={}), \
             patch.object(dl1, "_create_segmented_downloader", side_effect=_make_dl1), \
             patch.object(dl1, "_run_separator_subprocess_fallback") as mock_fb:
            dl1.run()

        self.assertEqual(len(done1), 1)
        self.assertFalse(done1[0][0])
        mock_fb.assert_not_called()
        part_file = os.path.join(dest_dir, "Kim_Vocal_2.onnx.part")
        meta_file = os.path.join(dest_dir, "Kim_Vocal_2.onnx.part.meta")
        self.assertTrue(os.path.isfile(part_file), "Partial file must be preserved for resume")
        self.assertTrue(os.path.isfile(meta_file), "Resume metadata must be preserved")
        with open(meta_file, "r", encoding="utf-8") as mf:
            saved_chunks = set(json.load(mf)["completed"])
        self.assertGreaterEqual(len(saved_chunks), 2, f"Expected >=2 checkpointed chunks, got {saved_chunks}")

        # Run 2: Network comes back -> resumes ONLY remaining chunks (saved chunks NOT re-fetched!)
        with lock:
            state["down"] = False
            run_tag["n"] = 2

        dl2 = ModelDownloader("Kim_Vocal_2.onnx", dest_dir)
        done2 = []
        pcts2 = []
        dl2.progress_update.connect(pcts2.append)
        dl2.finished_download.connect(lambda ok, msg: done2.append((ok, msg)))

        def _make_dl2():
            return _SegmentedFileDownloader(
                workers=2,
                chunk_size=chunk_sz,
                min_segmented_size=chunk_sz,
                disk_space_buffer_bytes=0,
                network_recovery_backoff=(0.05,),
                cancel_check=dl2.isInterruptionRequested,
            )

        with patch.dict(LOCAL_MODEL_MANIFEST, fake_manifest, clear=False), \
             patch("dependency_manager.load_installed_model_checksums", return_value={}), \
             patch.object(dl2, "_create_segmented_downloader", side_effect=_make_dl2):
            dl2.run()

        self.assertEqual(done2, [(True, "Success")])
        with open(os.path.join(dest_dir, "Kim_Vocal_2.onnx"), "rb") as f:
            self.assertEqual(f.read(), payload)
        for cidx in saved_chunks:
            c_start = cidx * chunk_sz
            c_end = min(len(payload) - 1, c_start + chunk_sz - 1)
            self.assertNotIn(
                f"bytes={c_start}-{c_end}",
                second_run_ranges,
                f"Checkpointed chunk {cidx} must not be re-downloaded on resume",
            )
        self.assertTrue(any(p >= 30 and p < 100 for p in pcts2), f"Expected resumed initial progress, got {pcts2}")

    # ── 25. _probe_mirror No Double Timeout & IPv4-Interleaved Connect ───────

    def test_probe_mirror_no_double_timeout_and_ipv4_interleaving_avoids_ipv6_blackhole(self):
        """Transport errors on HEAD fail fast without redundant GET; IPv4 interleaving bypasses dead IPv6 records."""
        import requests as req_lib
        import socket as sock_mod

        # Part A: HEAD ConnectTimeout must NOT trigger a second GET Range:0-0 to the same dead host
        dl = _SegmentedFileDownloader(probe_connect_timeout=1.0, probe_read_timeout=1.0)
        fake_sess = MagicMock()
        fake_sess.head.side_effect = req_lib.exceptions.ConnectTimeout("simulated timeout")
        with patch.object(dl, "_get_session", return_value=fake_sess):
            with self.assertRaises(req_lib.exceptions.ConnectTimeout):
                dl._probe_mirror("https://dead.example.com/model.ckpt")
        self.assertEqual(fake_sess.head.call_count, 1)
        self.assertEqual(fake_sess.get.call_count, 0, "_probe_mirror must NOT double-timeout with GET after HEAD connect timeout")

        # Part B: 8 unreachable IPv6 addresses before 1 reachable IPv4 localhost -> connects immediately via IPv4!
        payload = b"ok_ipv4" * 1024
        srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, payload, is_head=is_head))
        real_getaddrinfo = sock_mod.getaddrinfo

        def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            if host == "127.0.0.1" and port == srv.port:
                fake_v6 = [
                    (sock_mod.AF_INET6, sock_mod.SOCK_STREAM, 6, "", (f"2001:db8::{i}", port, 0, 0))
                    for i in range(1, 9)
                ]
                real_v4 = real_getaddrinfo("127.0.0.1", port, sock_mod.AF_INET, sock_mod.SOCK_STREAM)
                return fake_v6 + real_v4
            return real_getaddrinfo(host, port, family, type, proto, flags)

        dl2 = _SegmentedFileDownloader(connect_timeout=3.0, probe_connect_timeout=3.0, disk_space_buffer_bytes=0)
        dest = os.path.join(self.tmp_dir, "ipv4_fast.bin")
        t0 = time.monotonic()
        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            dl2.download(
                mirrors=[("huggingface", f"{srv.base_url}/file")],
                dest_path=dest,
                expected_size=len(payload),
                resume_enabled=False,
            )
        dt = time.monotonic() - t0
        self.assertLess(dt, 2.0, f"IPv4 interleaving should bypass dead IPv6 records quickly, took {dt:.2f}s")
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

    # ── 26. Consecutive 2-Model Downloads in Same Session + Host Deprioritization ──

    def test_consecutive_two_model_downloads_in_same_session_and_host_deprioritization(self):
        """Downloading 2 models sequentially in one MainWindow session succeeds cleanly without getting stuck at 0%."""
        chunk_sz = 32 * 1024
        payload1 = os.urandom(chunk_sz * 3)
        sha1 = hashlib.sha256(payload1).hexdigest()
        payload2 = os.urandom(chunk_sz * 4)
        sha2 = hashlib.sha256(payload2).hexdigest()
        yaml2 = b"model: mdx23c\n"
        yaml2_sha = hashlib.sha256(yaml2).hexdigest()

        good_srv = self._start_server(
            lambda h, is_head: _serve_bytes_range(
                h,
                payload1 if "m1" in h.path else (yaml2 if "yaml" in h.path else payload2),
                is_head=is_head,
            )
        )

        # Dead mirror on a distinct host (localhost vs 127.0.0.1) to verify host deprioritization
        dead_hits = {"yaml": 0, "ckpt": 0}
        def dead_route(h, is_head):
            if "yaml" in h.path:
                dead_hits["yaml"] += 1
            else:
                dead_hits["ckpt"] += 1
            self._drop_client_connection(h)

        dead_srv = self._start_server(dead_route)
        dead_host_url = f"http://localhost:{dead_srv.port}"

        fake_manifest = {
            "Kim_Vocal_2.onnx": {
                "primary": {
                    "filename": "Kim_Vocal_2.onnx",
                    "size": len(payload1),
                    "sha256": sha1,
                    "mirrors": [("github", f"{good_srv.base_url}/m1")],
                },
                "sidecars": [],
            },
            "MDX23C-8KFFT-InstVoc_HQ.ckpt": {
                "primary": {
                    "filename": "MDX23C-8KFFT-InstVoc_HQ.ckpt",
                    "size": len(payload2),
                    "sha256": sha2,
                    "mirrors": [
                        ("github", f"{dead_host_url}/m2_ckpt"),
                        ("huggingface", f"{good_srv.base_url}/m2_ckpt"),
                    ],
                },
                "sidecars": [
                    {
                        "filename": "model_2_stem_full_band_8k.yaml",
                        "size": len(yaml2),
                        "sha256": yaml2_sha,
                        "mirrors": [
                            ("github", f"{dead_host_url}/m2_yaml"),
                            ("github_raw", f"{good_srv.base_url}/m2_yaml"),
                        ],
                    }
                ],
            },
        }

        real_cls = _SegmentedFileDownloader
        def _fast_seg_factory(**kwargs):
            kwargs.setdefault("workers", 2)
            kwargs.setdefault("chunk_size", chunk_sz)
            kwargs.setdefault("min_segmented_size", chunk_sz)
            kwargs.setdefault("disk_space_buffer_bytes", 0)
            kwargs.setdefault("probe_connect_timeout", 2.0)
            kwargs.setdefault("probe_read_timeout", 2.0)
            kwargs.setdefault("progress_interval", 0.05)
            kwargs.setdefault("network_recovery_backoff", (0.05,))
            return real_cls(**kwargs)

        with patch.object(MainWindow, "init_threads"), \
             patch.object(MainWindow, "start_auto_update_check"), \
             patch.object(DependencyManager, "has_ffmpeg", return_value=True), \
             patch.object(DependencyManager, "has_local_engine", return_value=True), \
             patch.object(DependencyManager, "needs_gpu_engine_upgrade", return_value=False), \
             patch.object(QMessageBox, "exec", return_value=0), \
             patch.dict(LOCAL_MODEL_MANIFEST, fake_manifest, clear=False), \
             patch("dependency_manager.load_installed_model_checksums", return_value={}), \
             patch("dependency_manager._SegmentedFileDownloader", side_effect=_fast_seg_factory):
            win = MainWindow()
            try:
                win.config.appdata_dir = self.tmp_dir

                # Download Model 1 (Kim Vocal 2)
                win.config.set("local_model", "Fast (Kim Vocal 2) - Fast & Low VRAM")
                win.local_section.update_model_button_state()
                self.assertTrue(win.local_section._model_needs_download)
                win.download_local_model("Kim_Vocal_2.onnx", "Kim_Vocal_2")
                deadline = time.monotonic() + 8.0
                while win.local_section._is_downloading_model and time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.02)
                self.assertFalse(win.local_section._is_downloading_model, "Model 1 failed to complete")
                self.assertIsNone(win.model_thread, "Model 1 thread should be cleanly cleared after completion")
                self.assertTrue(os.path.isfile(os.path.join(self.tmp_dir, "models", "Kim_Vocal_2", "Kim_Vocal_2.onnx")))

                # Immediately download Model 2 (MDX23C) in the SAME session!
                win.config.set("local_model", "Mid (MDX23C) - Balanced Quality & Speed")
                win.local_section.update_model_button_state()
                self.assertTrue(win.local_section._model_needs_download)
                win.download_local_model("MDX23C-8KFFT-InstVoc_HQ.ckpt", "MDX23C")
                deadline = time.monotonic() + 8.0
                while win.local_section._is_downloading_model and time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.02)
                self.assertFalse(win.local_section._is_downloading_model, "Model 2 got stuck instead of completing!")
                self.assertIsNone(win.model_thread)
                m2_path = os.path.join(self.tmp_dir, "models", "MDX23C", "MDX23C-8KFFT-InstVoc_HQ.ckpt")
                self.assertTrue(os.path.isfile(m2_path))
                with open(m2_path, "rb") as f:
                    self.assertEqual(f.read(), payload2)
                # Dead host from sidecar must have been deprioritized so primary weights NEVER hit it!
                self.assertGreaterEqual(dead_hits["yaml"], 1)
                self.assertEqual(dead_hits["ckpt"], 0, "Dead host from sidecar should be deprioritized for primary weights")
            finally:
                if win.model_thread is not None:
                    win.model_thread.stop()
                win.close()

    # ── 27. Reconnecting UI State & tqdm Speed Extraction ────────────────────

    def test_ui_reconnecting_state_and_tqdm_speed_parsing(self):
        """JobQueueSection renders localized reconnecting state at preserved %, and parse_weight_speed extracts tqdm speed."""
        self.assertEqual(
            ModelDownloader.parse_weight_speed("50%|█████     | 305M/610M [00:12<00:12, 25.1MiB/s]"),
            "25.1 MB/s",
        )
        self.assertEqual(
            ModelDownloader.parse_weight_speed("10%|█         | 60M/610M [00:12<01:40, 820kB/s]"),
            "820 KB/s",
        )
        self.assertEqual(ModelDownloader.parse_weight_speed("no speed here"), "")

        cfg = ConfigManager()
        cfg.appdata_dir = self.tmp_dir
        cfg.config_path = os.path.join(self.tmp_dir, "config.json")
        qm = QueueManager()
        section = JobQueueSection("Local (GPU)", qm, cfg)
        section._model_needs_download = True
        section.set_model_downloading(True)

        i18n.set_language("en")
        section.set_download_progress(8, "RoFormer", "__RECONNECTING__")
        self.assertIn("Reconnecting", section.btn_add.text())
        self.assertIn("8%", section.btn_add.text())

        i18n.set_language("ar")
        section.retranslate_ui()
        self.assertIn("إعادة الاتصال", section.btn_add.text())
        self.assertIn("8", section.btn_add.text())

    # ── 28. Stale / Truncated .part Does Not Freeze Progress Bar ─────────────

    def test_stale_or_truncated_part_does_not_freeze_initial_progress_bar(self):
        """Mismatched sha256 or truncated .part must return 0 resumed bytes so ModelDownloader never freezes at stale %."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 5)  # 160 KiB = 5 chunks
        expected_sha = hashlib.sha256(payload).hexdigest()

        dl_probe = _SegmentedFileDownloader(chunk_size=chunk_sz, min_segmented_size=chunk_sz, disk_space_buffer_bytes=0)

        # Case A: SHA-256 mismatch claiming 4/5 chunks (80%) completed
        dest_a = os.path.join(self.tmp_dir, "stale_sha.ckpt")
        with open(dest_a + ".part", "wb") as f:
            f.write(payload[:chunk_sz * 4])
        with open(dest_a + ".part.meta", "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "expected_size": len(payload),
                "sha256": "0" * 64,
                "chunk_size": chunk_sz,
                "completed": [0, 1, 2, 3],
            }, f)
        self.assertEqual(
            dl_probe._compute_resumed_bytes_on_disk(dest_a + ".part", dest_a + ".part.meta", len(payload), expected_sha),
            0,
            "Stale sha256 .part.meta must report 0 resumed bytes",
        )

        # Case B: Matching SHA-256, but truncated 0-byte .part file
        dest_b = os.path.join(self.tmp_dir, "truncated_part.ckpt")
        with open(dest_b + ".part", "wb") as f:
            f.write(b"")
        with open(dest_b + ".part.meta", "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "expected_size": len(payload),
                "sha256": expected_sha,
                "chunk_size": chunk_sz,
                "completed": [0, 1, 2, 3],
            }, f)
        self.assertEqual(
            dl_probe._compute_resumed_bytes_on_disk(dest_b + ".part", dest_b + ".part.meta", len(payload), expected_sha),
            0,
            "Truncated .part file must report 0 resumed bytes",
        )

        # Case C: End-to-end ModelDownloader with stale sha256 .part advances cleanly (does NOT jump to 80% before downloading!)
        srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, payload, is_head=is_head, delay_per_block=0.01, block_size=8192))
        dest_dir = os.path.join(self.tmp_dir, "stale_resume_model")
        os.makedirs(dest_dir, exist_ok=True)
        model_dest = os.path.join(dest_dir, "Kim_Vocal_2.onnx")
        with open(model_dest + ".part", "wb") as f:
            f.write(payload[:chunk_sz * 4])
        with open(model_dest + ".part.meta", "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "expected_size": len(payload),
                "sha256": "0" * 64,
                "chunk_size": chunk_sz,
                "completed": [0, 1, 2, 3],
            }, f)

        fake_manifest = {
            "Kim_Vocal_2.onnx": {
                "primary": {
                    "filename": "Kim_Vocal_2.onnx",
                    "size": len(payload),
                    "sha256": expected_sha,
                    "mirrors": [("github", f"{srv.base_url}/Kim_Vocal_2.onnx")],
                },
                "sidecars": [],
            }
        }
        dl = ModelDownloader("Kim_Vocal_2.onnx", dest_dir)
        pcts = []
        done = []
        dl.progress_update.connect(pcts.append)
        dl.finished_download.connect(lambda ok, msg: done.append((ok, msg)))
        with patch.dict(LOCAL_MODEL_MANIFEST, fake_manifest, clear=False), \
             patch("dependency_manager.load_installed_model_checksums", return_value={}), \
             patch.object(
                 dl,
                 "_create_segmented_downloader",
                 side_effect=lambda: _SegmentedFileDownloader(
                     workers=2,
                     chunk_size=chunk_sz,
                     read_block_size=8192,
                     min_segmented_size=chunk_sz,
                     disk_space_buffer_bytes=0,
                     progress_interval=0.02,
                     cancel_check=dl.isInterruptionRequested,
                 ),
             ):
            dl.run()
        self.assertEqual(done, [(True, "Success")])
        # Must emit low intermediate percentages (< 60%) instead of starting locked at 80%
        self.assertTrue(any(0 < p < 60 for p in pcts), f"Expected low progress before 80%, got {pcts}")

    # ── 29. Precise Recoverable Network Error Classification ─────────────────

    def test_recoverable_network_error_classification_excludes_local_fs_and_protocol_errors(self):
        """Winsock errors (incl. WinError 10013) are recoverable; local PermissionError/FileNotFoundError/protocol IOError are NOT."""
        from dependency_manager import _is_recoverable_network_error, DownloadNetworkError

        # Must be recoverable network errors
        win_10013 = OSError(13, "An attempt was made to access a socket in a way forbidden by its access permissions")
        win_10013.winerror = 10013
        self.assertTrue(_is_recoverable_network_error(win_10013))
        self.assertTrue(_is_recoverable_network_error(ConnectionResetError("reset")))
        self.assertTrue(_is_recoverable_network_error(TimeoutError("timed out")))
        self.assertTrue(_is_recoverable_network_error(DownloadNetworkError("chunk failed")))
        self.assertTrue(_is_recoverable_network_error(IOError("Truncated chunk 3: expected 4096, got 512")))
        self.assertTrue(_is_recoverable_network_error(IOError("Incomplete single-stream read: expected 100, got 10")))

        # Must NOT be misclassified as recoverable network outages
        local_perm = PermissionError(13, "Access is denied")
        local_perm.winerror = 5
        self.assertFalse(_is_recoverable_network_error(local_perm))
        self.assertFalse(_is_recoverable_network_error(FileNotFoundError("no such file")))
        self.assertFalse(_is_recoverable_network_error(IOError("Malformed Content-Range header: garbage")))
        self.assertFalse(_is_recoverable_network_error(IOError("Oversized chunk 0: received > 1024 bytes")))
        self.assertFalse(_is_recoverable_network_error(ChecksumMismatchError("bad sha")))
        self.assertFalse(_is_recoverable_network_error(InsufficientDiskSpaceError(28, "disk full")))
        self.assertFalse(_is_recoverable_network_error(DownloadCancelledError("cancelled")))

    # ── 30. Graceful Speed Failover & Recovery Budget Reset Across 2 Outages ─

    def test_graceful_speed_failover_preserves_inflight_chunks_and_two_outages_reset_budget(self):
        """Speed-only failover preserves >=50% chunks instead of discarding them; 2 distinct outages get fresh recovery budgets."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 6)
        expected_sha = hashlib.sha256(payload).hexdigest()

        # Part A: Graceful speed-only failover preserves >=50% complete chunks on m0
        m0_ranges = []
        m1_ranges = []
        lock_a = threading.Lock()

        def route_a(h, is_head):
            if is_head:
                _serve_bytes_range(h, payload, is_head=True)
                return
            rng = h.headers.get("Range") or ""
            with lock_a:
                if h.path == "/m0":
                    m0_ranges.append(rng)
                else:
                    m1_ranges.append(rng)
            if h.path == "/m0":
                # 16 blocks * 0.03s = 0.48s per 32 KiB chunk (~66 KiB/s); at t=0.35s (>50% done!) failover fires
                _serve_bytes_range(h, payload, is_head=False, delay_per_block=0.03, block_size=2048)
            else:
                _serve_bytes_range(h, payload, is_head=False)

        srv_a = self._start_server(route_a)
        dest_a = os.path.join(self.tmp_dir, "graceful.onnx")
        dl_a = _SegmentedFileDownloader(
            workers=2,
            chunk_size=chunk_sz,
            read_block_size=2048,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
            cdn_failover_max_bps=300 * 1024,
            cdn_failover_seconds=0.32,
            true_stall_seconds=5.0,
            straggler_seconds=5.0,
            progress_interval=0.05,
        )
        dl_a.download(
            mirrors=[("github", f"{srv_a.base_url}/m0"), ("huggingface", f"{srv_a.base_url}/m1")],
            dest_path=dest_a,
            expected_size=len(payload),
            expected_sha256=expected_sha,
        )
        with open(dest_a, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertGreater(len(m1_ranges), 0, "Should have switched remaining chunks to m1")
        # Chunks 0 and 1 were >=50% complete when speed failover triggered, so m1 should NOT re-fetch them!
        self.assertNotIn(f"bytes=0-{chunk_sz - 1}", m1_ranges)

        # Part B: Two separate network outages separated by forward progress BOTH recover with a 1-round budget
        dest_b = os.path.join(self.tmp_dir, "two_outages.onnx")
        meta_b = dest_b + ".part.meta"
        outage_lock = threading.Lock()
        st = {"down": False, "outages": 0}

        def _saved_b() -> int:
            if not os.path.isfile(meta_b):
                return 0
            try:
                with open(meta_b, "r", encoding="utf-8") as mf:
                    return len(json.load(mf).get("completed", []))
            except Exception:
                return 0

        def route_b(h, is_head):
            with outage_lock:
                if st["down"]:
                    self._drop_client_connection(h)
                    return
                if not is_head:
                    saved_cnt = _saved_b()
                    # Trigger outage #1 after >=1 chunk checkpointed and outage #2 after >=3 chunks checkpointed!
                    if (st["outages"] == 0 and saved_cnt >= 1) or (st["outages"] == 1 and saved_cnt >= 3):
                        st["down"] = True
                        st["outages"] += 1
                        def _up():
                            time.sleep(0.12)
                            with outage_lock:
                                st["down"] = False
                        threading.Thread(target=_up, daemon=True).start()
                        self._drop_client_connection(h)
                        return
            _serve_bytes_range(h, payload, is_head=is_head)

        srv_b = self._start_server(route_b)
        reconn_events = []
        dl_b = _SegmentedFileDownloader(
            workers=2,
            chunk_size=chunk_sz,
            min_segmented_size=chunk_sz,
            disk_space_buffer_bytes=0,
            max_chunk_retries=1,
            # Only 1 retry round per outage — succeeds ONLY if forward progress resets recovery_round!
            network_recovery_backoff=(0.2,),
        )
        dl_b.download(
            mirrors=[("github", f"{srv_b.base_url}/file")],
            dest_path=dest_b,
            expected_size=len(payload),
            expected_sha256=expected_sha,
            progress_cb=lambda d, tot, bps, stage: reconn_events.append((d, stage)) if stage == "reconnecting" else None,
        )
        with open(dest_b, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertEqual(st["outages"], 2)
        self.assertGreaterEqual(len(reconn_events), 2)

    # ── 31. Session-Level Degraded Host Memory & Self-Healing ────────────────

    def test_session_degraded_host_deprioritized_across_models_and_self_heals(self):
        """A host that failed in Model 1 is immediately deprioritized in Model 2 and self-heals once healthy again."""
        chunk_sz = 32 * 1024
        payload = os.urandom(chunk_sz * 2)
        sha = hashlib.sha256(payload).hexdigest()

        dead_state = {"down": True, "hits": 0}
        lock = threading.Lock()

        def dead_route(h, is_head):
            with lock:
                dead_state["hits"] += 1
                is_down = dead_state["down"]
            if is_down:
                self._drop_client_connection(h)
                return
            _serve_bytes_range(h, payload, is_head=is_head)

        dead_srv = self._start_server(dead_route)
        good_srv = self._start_server(lambda h, is_head: _serve_bytes_range(h, payload, is_head=is_head))
        dead_url = f"http://localhost:{dead_srv.port}/m"
        good_url = f"{good_srv.base_url}/m"

        manifest = {
            "Kim_Vocal_2.onnx": {
                "primary": {
                    "filename": "Kim_Vocal_2.onnx",
                    "size": len(payload),
                    "sha256": sha,
                    "mirrors": [("github", dead_url), ("huggingface", good_url)],
                },
                "sidecars": [],
            },
            "MDX23C-8KFFT-InstVoc_HQ.ckpt": {
                "primary": {
                    "filename": "MDX23C-8KFFT-InstVoc_HQ.ckpt",
                    "size": len(payload),
                    "sha256": sha,
                    "mirrors": [("github", dead_url), ("huggingface", good_url)],
                },
                "sidecars": [],
            },
            "model_bs_roformer_ep_317_sdr_12.9755.ckpt": {
                "primary": {
                    "filename": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
                    "size": len(payload),
                    "sha256": sha,
                    "mirrors": [("github", dead_url)],
                },
                "sidecars": [],
            },
        }

        def _make_dl(dl_inst):
            return _SegmentedFileDownloader(
                workers=2,
                chunk_size=chunk_sz,
                min_segmented_size=chunk_sz,
                disk_space_buffer_bytes=0,
                network_recovery_backoff=(0.02,),
                cancel_check=dl_inst.isInterruptionRequested,
            )

        with patch.dict(LOCAL_MODEL_MANIFEST, manifest, clear=False), \
             patch("dependency_manager.load_installed_model_checksums", return_value={}):
            # Model 1 hits dead_url, fails over to good_url, and records localhost as degraded
            d1 = os.path.join(self.tmp_dir, "s_m1")
            dl1 = ModelDownloader("Kim_Vocal_2.onnx", d1)
            with patch.object(dl1, "_create_segmented_downloader", side_effect=lambda: _make_dl(dl1)):
                dl1.run()
            hits_after_m1 = dead_state["hits"]
            self.assertGreaterEqual(hits_after_m1, 1)

            # Model 2 in same session immediately prioritizes good_url -> ZERO hits to dead_url!
            d2 = os.path.join(self.tmp_dir, "s_m2")
            dl2 = ModelDownloader("MDX23C-8KFFT-InstVoc_HQ.ckpt", d2)
            with patch.object(dl2, "_create_segmented_downloader", side_effect=lambda: _make_dl(dl2)):
                dl2.run()
            self.assertEqual(dead_state["hits"], hits_after_m1, "Model 2 should deprioritize degraded host from Model 1")

            # Now dead_url recovers -> Model 3 succeeds on dead_url and self-heals _DEGRADED_HOSTS!
            with lock:
                dead_state["down"] = False
            d3 = os.path.join(self.tmp_dir, "s_m3")
            dl3 = ModelDownloader("model_bs_roformer_ep_317_sdr_12.9755.ckpt", d3)
            with patch.object(dl3, "_create_segmented_downloader", side_effect=lambda: _make_dl(dl3)):
                dl3.run()
            self.assertNotIn("localhost", ModelDownloader._get_session_degraded_hosts())

    # ── 32. MainWindow Retired Model Thread No Dangling Leak ─────────────────

    def test_main_window_retired_model_thread_no_dangling_leak_when_finished_fires_first(self):
        """If QThread.finished retires the thread before on_model_downloaded runs, _retired_model_threads must not retain it."""
        with patch.object(MainWindow, "init_threads"), \
             patch.object(MainWindow, "start_auto_update_check"), \
             patch.object(DependencyManager, "has_ffmpeg", return_value=True), \
             patch.object(DependencyManager, "has_local_engine", return_value=True), \
             patch.object(DependencyManager, "needs_gpu_engine_upgrade", return_value=False):
            win = MainWindow()
            try:
                fake_th = MagicMock()
                fake_th.isRunning.return_value = False
                fake_th._ep_retired = False
                win.model_thread = fake_th

                # Simulate finished signal firing BEFORE on_model_downloaded
                win._retire_model_thread(fake_th)
                win.on_model_downloaded(True, "Success", fake_th)
                self.assertIsNone(win.model_thread)
                self.assertEqual(win._retired_model_threads, [])
                fake_th.deleteLater.assert_called_once()
            finally:
                win.close()


if __name__ == "__main__":
    unittest.main()
