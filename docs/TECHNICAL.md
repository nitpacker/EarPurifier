# EarPurifier - Engineering Wiki & Technical Architecture

This document serves as the definitive engineering reference for the EarPurifier codebase. It maps the domain architecture, dependency constraints, and edge-case resiliency mechanisms. 

**Any developer or AI modifying this codebase MUST review the Binding Rules (Section 8) before writing code.**

---

## 1. System Overview

EarPurifier is a desktop application (PySide6) providing state-of-the-art AI audio isolation. It implements a **Dual Engine Architecture**:
*   **Local Processing**: Executes `audio-separator` directly on the user's local Nvidia GPU. Requires significant local hardware.
*   **Cloud Processing**: Offloads workload to Kaggle's free T4 Cloud GPUs via headless Python worker scripts. Utilizes a V2/V3 Cache Dataset to bypass Kaggle network bottlenecks, dropping spin-up times from 45s to 2s.

---

## 2. Domain Map: Where to Look

When debugging or extending the application, start your search here:

### 🖥️ Presentation Layer (UI)
*   **`main.py`**: The PySide6 entry point. Houses the main window, settings dialog, tab states, and the `JobCard` UI components. 
    *   *Look here for:* UI freezes, button connections, CSS styling, ETA display updates, and thread initialization.
*   **`config_manager.py`**: Interacts with `%APPDATA%/EarPurifier/config.json`.
    *   *Look here for:* Adding new user preferences or global settings.

### 🧠 State & Concurrency Layer
*   **`queue_manager.py`**: The heart of state persistence (`%APPDATA%/EarPurifier/job_state.json`). 
    *   *Look here for:* Job status transitions, elapsed time calculations, and startup temp/crash cleanup.
*   **`processor_thread.py`**: The **Cloud Engine** (`JobProcessor` QThread). 
    *   *Look here for:* Kaggle network orchestrations, retry loops, dynamic worker script injection, and Kaggle execution log piping.
*   **`local_processor.py`**: The **Local Engine** (`LocalJobProcessor` QThread).
    *   *Look here for:* Subprocess executions of the local `audio-separator` engine.

### 🎬 Media & Integration Layer
*   **`media_engine.py`**: Wrapper for `ffmpeg` and `ffprobe`.
    *   *Look here for:* FLAC extraction, audio padding (to fix AI silence drops), and `-c:v copy` remuxing.
*   **`kaggle_bridge.py`**: Abstraction over the `kaggle` Python API.
    *   *Look here for:* Dataset pushing, kernel dispatching, status polling, output downloading, and kernel log retrieval.
*   **`worker/worker.py`**: The isolated, headless Python script dispatched to Kaggle.
    *   *Look here for:* What the Kaggle cloud GPU is actually executing (offline pip installs, online fallback, GPU assertion, separation).

### 🛠️ Tooling
*   **`build.py`**: The smart PyInstaller build orchestration script.
*   **`logger_setup.py`**: Rotating file logging to `%APPDATA%/EarPurifier/applogs/` and rotation for `kaggle_logs/`.
*   **`docs/archive/build_master_cache.py`**: Automates generating offline wheels and model datasets on Kaggle.

---

## 3. The Job Lifecycle Pipeline

Regardless of the engine (Cloud/Local), jobs strictly adhere to a synchronous pipeline:

1.  **Queueing**: Video is added. `QueueManager` snapshots the chosen `job["model"]` to prevent UI setting changes from mutating queued jobs. Status: `PENDING`.
2.  **Extraction**: `media_engine.extract_audio` pulls a lossless 48kHz FLAC to `%APPDATA%/EarPurifier/temp/<job_id>/audio.flac`. `started_at` is stamped. Status: `EXTRACTING`.
3.  **Separation (AI Phase)**:
    *   *Local*: `local_processor.py` invokes the local engine subprocess.
    *   *Cloud*: `kaggle_bridge.py` uploads the FLAC -> dispatches `worker.py` -> Kaggle mounts the Cache Dataset -> runs separation -> `processor_thread.py` polls and downloads the output.
4.  **Alignment**: `media_engine.pad_or_trim_audio` ensures the new audio exactly matches original duration.
5.  **Remuxing**: `media_engine.remux_video` merges the original video stream with the new audio losslessly. Saved to the user's output directory. Status: `COMPLETED`.

---

## 4. The Cloud Master Cache Architecture

To make Cloud processing instant (~60s total), EarPurifier bypasses Kaggle's slow internet connection using an offline cache.

*   **The Dataset (`earpurifier-cloud-assets-v2`)**: Hosted on the developer's Kaggle account. Contains pre-downloaded `.ckpt`/`.onnx` models, and a `wheels/` directory of binary `.whl` files.
    *   *Model weights* (`.onnx`, `.ckpt`) are raw data: they are Python-agnostic and never expire across Python runtime upgrades.
    *   *Wheel files* (`.whl`) are compiled C-extensions tied to specific CPython ABIs (`cp312`, `cp313`).
*   **Execution**: `worker.py` uses `os.walk` to find this dataset (as Kaggle mounts are dynamically hashed). It runs `pip install --no-index --find-links=/path/wheels audio-separator[gpu] onnxruntime-gpu`. This drops Kaggle setup from 45s to 2s.
*   **Disaster Recovery & Evolution**: When Kaggle upgrades its container Python version (e.g. from 3.12 to 3.13), older wheels become incompatible. The worker script gracefully falls back to installing from PyPI online so jobs continue to work. Use `docs/archive/build_master_cache.py` to regenerate the wheel cache on Kaggle and push an updated cache version to restore 2-second startup times.

---

## 5. Known Edge Cases & Resiliency Mechanisms

If you encounter unexpected behavior, it is likely governed by one of these engineered edge cases:

*   **Kaggle Network Drops (`IncompleteRead`)**: Downloading/Uploading 20MB files via the Kaggle API routinely fails due to dropped packets. **Fix:** Every network call in `processor_thread.py` is wrapped in a strict 5-attempt retry loop with a 3-second sleep.
*   **Kaggle Dataset Race Conditions & Unique Buffers**: Previously, jobs shared a single dataset buffer. This caused race conditions when multiple jobs tried to update the dataset concurrently, and Kaggle's versioning was slow to propagate. **Fix:** `kaggle_bridge.py` creates a unique, disposable dataset (e.g. `earpurifier-audio-buffer-<uuid>`) for *every single job*. This allows the user to queue and process 5 videos simultaneously in the cloud without them interfering.
*   **PyInstaller tqdm Crash (The Invisible Abort)**: The Kaggle SDK internally uses the `tqdm` progress bar. In a PyInstaller `--windowed` executable, the default `sys.stderr` is detached. When `tqdm` attempts to print the progress bar, it throws an exception that the Kaggle SDK silently catches, causing uploads to mysteriously abort and submit empty datasets (resulting in "Please upload at least one file" errors). **Fix:** We strictly pass `quiet=True` to Kaggle SDK methods (like `dataset_create_new`) to disable `tqdm` and bypass the crash entirely.
*   **Kaggle API Token Format Migration (The `KGAT_` Bug)**: Kaggle recently deprecated standard 32-hex API keys in favor of Personal Access Tokens (prefixed with `KGAT_`). The Kaggle SDK will *violently reject* `KGAT_` tokens with a `401 Unauthorized` if they are mapped to the legacy `KAGGLE_KEY` environment variable (which forces HTTP Basic Auth). **Fix:** `kaggle_bridge.py` dynamically inspects the key string. If it detects `KGAT_`, it maps it to `KAGGLE_API_TOKEN` to force the SDK to use Bearer Auth. It also aggressively `.pop()`s both keys from `os.environ` before assignment to prevent memory pollution when users hot-swap keys.
*   **Kaggle SDK Download Truncation (`IncompleteRead`)**: The official `kaggle.api.kernels_output` method has a fatal flaw: it lacks resumable download support. If a network stutter triggers an `IncompleteRead` while downloading massive output files from Google Cloud Storage, the SDK catches the error but explicitly opens the file in `"wb"` mode on the retry, truncating progress back to 0 bytes. This causes infinite download loops on slightly unstable connections. **Fix:** `kaggle_bridge.py` completely bypasses the SDK's download logic. It intercepts the raw GCS Signed URL via `list_kernel_session_output` and implements a multi-threaded `requests` downloader (4 concurrent connections via `ThreadPoolExecutor`) using the HTTP `Range: bytes=X-Y` header. *Note: Kaggle explicitly blocks `HEAD` requests (returns 404) on these signed URLs, so we extract the `Content-Length` via a streaming `GET` request before dispatching threads.* This stitches the file together safely and multiplies download speed by 4x, bypassing single-connection ISP throttling.
*   **Kaggle Python Runtime Upgrades & Graceful Degradation**: When Kaggle updates its default Python runtime, pre-cached `.whl` files may fail offline installation. **Fix:** `worker.py` attempts offline install first; if cached wheels fail, it logs a warning and gracefully falls back to installing compatible versions from PyPI online. `worker.py` does not hardcode restrictive version pins.
*   **Silent GPU -> CPU Fallback Prevention**: In certain driver or CUDA misconfigurations (e.g. CUDA 13 wheels looking for `libcublasLt.so.13` on a CUDA 12 host), ONNX Runtime bindings report CUDA as available, but session initialization silently falls back to `CPUExecutionProvider`, running 10x slower without failing. **Fix:** `worker.py` inspects both `ort.get_available_providers()` AND the active model session (`separator.model_instance.model_run.get_providers()`). If `"CUDAExecutionProvider"` is missing from the active session, it immediately raises `RuntimeError`, aborting in under 5 seconds to prevent burning GPU quota on a crawling CPU job.
*   **Kaggle Kernel Execution Logs (`applogs/kaggle_logs/`)**: To avoid polluting `earpurifier.log` with high-volume kernel stdout/stderr, `processor_thread.py` safely fetches the kernel execution log upon job completion or error and writes it to `%APPDATA%/EarPurifier/applogs/kaggle_logs/<job_id>.log`. Failures to fetch logs are non-fatal and never crash the pipeline.
*   **ETA Calculations (Cloud)**: Cloud jobs cannot precisely report progress percentages. **Fix:** `main.py` uses a deterministic formula (`remaining_seconds = 150 + (duration * 1.5)`) to run a local countdown. If it hits 0 early, it displays `"ETA: Anytime now..."`. Local jobs rely on stdout regex parsing for real percentages.
*   **Vocal Track Matching**: The `audio-separator` output filename is unpredictable based on the model. **Fix:** The worker script explicitly checks `if "(vocals)" in f.lower():` and forcefully renames it to `clean_vocals.flac` before downloading.
*   **Hardware-Accelerated Audio Remuxing**: FFmpeg's native `aac` encoder is single-threaded and defaults to an iterative two-loop algorithm, bottlenecking remux speed to ~100 fps (~5.5 minutes for 25-minute audio). **Fix:** `media_engine.remux_video` dynamically routes to OS-accelerated hardware AAC encoders (`aac_mf` on Windows, `aac_at` on macOS), accelerating remux speeds to ~1,500 fps (~25 seconds) with automatic fallback to standard native `aac` if the platform encoder is unavailable.
*   **Storage Cleanup**: To prevent Kaggle from hitting limits and keeping a clutter of unique datasets, `processor_thread.py` calls `api.dataset_delete` to destroy the unique disposable dataset post-job. To prevent `%APPDATA%` from bloating locally, `QueueManager` actively runs `shutil.rmtree(temp)` on application startup to sweep orphaned files from force-closures.

---

## 6. Dependency Matrix

EarPurifier relies on a fragile web of ML libraries. **Never arbitrarily update `requirements.txt`.**

| Dependency | Purpose | Strict Constraint |
| :--- | :--- | :--- |
| `PySide6` | Application UI framework | None |
| `audio-separator[gpu]` | Core AI isolation engine | Unpinned in cloud worker; dynamically resolves compatible PyTorch/ONNX dependencies. |
| `onnxruntime-gpu` | Hardware Acceleration | Pinned to `<1.27.0` (resolves to `1.26.0`) in worker and cache builder to align with Kaggle's CUDA 12.8 + cuDNN 9.x environment (releases >= 1.27.0 default to CUDA 13.0 and fail on Kaggle's `libcublasLt.so.12`). |
| `kaggle` | Cloud orchestrator API | Must be careful with progress bars in PyInstaller (use `quiet=True`). |
| `ffmpeg-python` | Media extraction | The host system must have the `ffmpeg` binary in PATH. |

---

## 7. Build & Release Engineering

The `build.py` script is highly specialized.
*   **Smart Virtual Environments**: PyInstaller sweeps the entire Python environment into the `.exe`. To prevent a 2GB executable, `build.py` automatically isolates a clean `venv`, installs exactly `requirements.txt`, and builds from there.
*   **Artifact Cleanup**: Automatically removes `.spec` files and intermediate `build/` directories post-compilation.

---

## 8. Binding Rules For Developers

When contributing to this codebase, you **must** adhere to the following rules:

1.  **Do NOT Block the UI Thread:** Never call `.wait()` on `cloud_thread` or `local_thread` inside `main.py` when settings change. Threads must read config dynamically. Blocking the UI thread during a Kaggle HTTP request will deadlock the application.
2.  **Respect the Job Snapshot:** Jobs inherit their model from `job["model"]`, NOT from the live `ConfigManager`. This allows users to queue different models simultaneously. Do not regress this by making background threads read live global settings.
3.  **Elapsed Time Integrity:** `elapsed_seconds` must only increment if `status != PENDING`. Do not include queue wait times in final benchmarks.
4.  **Sync Local & Cloud Dependencies:** If you update an AI dependency in `requirements.txt` to run locally, you **must** rebuild and publish a new Kaggle Master Cache. The cloud engine is optimized for offline cache hits; if dependencies drift, jobs gracefully fall back to PyPI but take ~30s longer.
5.  **Dependency Compatibility in Cloud Worker:** Do not pin to outdated minor releases that lack modern Python ABI wheels (e.g. legacy `1.19.2` lacked Python 3.13). However, maintain environment alignment constraints where upstream defaults break host hardware (e.g. `onnxruntime-gpu<1.27.0` to remain on CUDA 12 rather than defaulting to CUDA 13).
