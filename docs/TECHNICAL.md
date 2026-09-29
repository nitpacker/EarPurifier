# EarPurifier - Engineering Wiki & Technical Architecture

This document serves as the definitive engineering reference for the EarPurifier codebase. It maps the domain architecture, dependency constraints, and edge-case resiliency mechanisms. 

**Any developer or AI modifying this codebase MUST review the Binding Rules (Section 8) before writing code.**

---

## 1. System Overview

EarPurifier is a desktop application (PySide6) providing state-of-the-art AI audio isolation. It implements a **Dual Engine Architecture**:
*   **Local Processing**: Executes `audio-separator` directly on the user's local Nvidia GPU. Requires significant local hardware.
*   **Cloud Processing**: Offloads workload to Kaggle's free T4 Cloud GPUs via headless Python worker scripts. Utilizes a V2 Cache Dataset to bypass Kaggle network bottlenecks, dropping spin-up times from 45s to 2s.

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
    *   *Look here for:* Kaggle network orchestrations, retry loops, dynamic worker script injection.
*   **`local_processor.py`**: The **Local Engine** (`LocalJobProcessor` QThread).
    *   *Look here for:* Subprocess executions of the local `audio-separator` engine.

### 🎬 Media & Integration Layer
*   **`media_engine.py`**: Wrapper for `ffmpeg` and `ffprobe`.
    *   *Look here for:* FLAC extraction, audio padding (to fix AI silence drops), and `-c:v copy` remuxing.
*   **`kaggle_bridge.py`**: Abstraction over the `kaggle` Python API.
    *   *Look here for:* Dataset pushing, kernel dispatching, and output downloading.
*   **`worker/worker.py`**: The isolated, headless Python script dispatched to Kaggle.
    *   *Look here for:* What the Kaggle cloud GPU is actually executing (offline pip installs, separation).

### 🛠️ Tooling
*   **`build.py`**: The smart PyInstaller build orchestration script.
*   **`logger_setup.py`**: Rotating file logging to `%APPDATA%/EarPurifier/applogs/`.

---

## 3. The Job Lifecycle Pipeline

Regardless of the engine (Cloud/Local), jobs strictly adhere to a synchronous pipeline:

1.  **Queueing**: Video is added. `QueueManager` snapshots the chosen `job["model"]` to prevent UI setting changes from mutating queued jobs. Status: `PENDING`.
2.  **Extraction**: `media_engine.extract_audio` pulls a lossless 48kHz FLAC to `%APPDATA%/EarPurifier/temp/<job_id>/audio.flac`. `started_at` is stamped. Status: `EXTRACTING`.
3.  **Separation (AI Phase)**:
    *   *Local*: `local_processor.py` invokes the local engine subprocess.
    *   *Cloud*: `kaggle_bridge.py` uploads the FLAC -> dispatches `worker.py` -> Kaggle mounts the V2 Cache -> runs separation -> `processor_thread.py` polls and downloads the output.
4.  **Alignment**: `media_engine.pad_or_trim_audio` ensures the new audio exactly matches original duration.
5.  **Remuxing**: `media_engine.remux_video` merges the original video stream with the new audio losslessly. Saved to the user's output directory. Status: `COMPLETED`.

---

## 4. The Cloud V2 Master Cache Architecture

To make Cloud processing instant (~60s total), EarPurifier bypasses Kaggle's slow internet connection using an offline cache.

*   **The Dataset (`earpurifier-cloud-assets-v2`)**: Hosted on the developer's Kaggle account. Contains pre-downloaded `.ckpt`/`.onnx` models, and a `wheels/` directory of strict binary `.whl` files.
*   **Execution**: `worker.py` uses `os.walk` to find this dataset (as Kaggle mounts are dynamically hashed). It runs `pip install --no-index --find-links=/path/wheels audio-separator[gpu]`. This drops Kaggle setup from 45s to 2s.
*   **Disaster Recovery**: If Kaggle breaks the cache (e.g., Python 3.13 upgrade), use `docs/archive/build_master_cache.py` to regenerate the wheels (`pip wheel`) and push a new V3 master cache.

---

## 5. Known Edge Cases & Resiliency Mechanisms

If you encounter unexpected behavior, it is likely governed by one of these engineered edge cases:

*   **Kaggle Network Drops (`IncompleteRead`)**: Downloading/Uploading 20MB files via the Kaggle API routinely fails due to dropped packets. **Fix:** Every network call in `processor_thread.py` is wrapped in a strict 5-attempt retry loop with a 3-second sleep.
*   **Kaggle Dataset Race Conditions & Unique Buffers**: Previously, jobs shared a single dataset buffer. This caused race conditions when multiple jobs tried to update the dataset concurrently, and Kaggle's versioning was slow to propagate. **Fix:** `kaggle_bridge.py` creates a unique, disposable dataset (e.g. `earpurifier-audio-buffer-<uuid>`) for *every single job*. This allows the user to queue and process 5 videos simultaneously in the cloud without them interfering.
*   **PyInstaller tqdm Crash (The Invisible Abort)**: The Kaggle SDK internally uses the `tqdm` progress bar. In a PyInstaller `--windowed` executable, the default `sys.stderr` is detached. When `tqdm` attempts to print the progress bar, it throws an exception that the Kaggle SDK silently catches, causing uploads to mysteriously abort and submit empty datasets (resulting in "Please upload at least one file" errors). **Fix:** We strictly pass `quiet=True` to Kaggle SDK methods (like `dataset_create_new`) to disable `tqdm` and bypass the crash entirely.
*   **Kaggle API Token Format Migration (The `KGAT_` Bug)**: Kaggle recently deprecated standard 32-hex API keys in favor of Personal Access Tokens (prefixed with `KGAT_`). The Kaggle SDK will *violently reject* `KGAT_` tokens with a `401 Unauthorized` if they are mapped to the legacy `KAGGLE_KEY` environment variable (which forces HTTP Basic Auth). **Fix:** `kaggle_bridge.py` dynamically inspects the key string. If it detects `KGAT_`, it maps it to `KAGGLE_API_TOKEN` to force the SDK to use Bearer Auth. It also aggressively `.pop()`s both keys from `os.environ` before assignment to prevent memory pollution when users hot-swap keys.
*   **Kaggle SDK Download Truncation (`IncompleteRead`)**: The official `kaggle.api.kernels_output` method has a fatal flaw: it lacks resumable download support. If a network stutter triggers an `IncompleteRead` while downloading a massive uncompressed 250MB WAV file from Google Cloud Storage, the SDK catches the error but explicitly opens the file in `"wb"` mode on the retry, truncating progress back to 0 bytes. This causes infinite download loops on slightly unstable connections. **Fix:** `kaggle_bridge.py` completely bypasses the SDK's download logic. It intercepts the raw GCS Signed URL via `list_kernel_session_output` and implements a custom HTTP `Range: bytes=X-` loop using `requests`, appending via `"ab"` mode to seamlessly stitch broken connections together byte-by-byte.
*   **ETA Calculations (Cloud)**: Cloud jobs cannot precisely report progress percentages. **Fix:** `main.py` uses a deterministic formula (`remaining_seconds = 150 + (duration * 1.5)`) to run a local countdown. If it hits 0 early, it displays `"ETA: Anytime now..."`. Local jobs rely on stdout regex parsing for real percentages.
*   **Vocal Track Matching**: The `audio-separator` output filename is unpredictable based on the model. **Fix:** The worker script explicitly checks `if "(vocals)" in f.lower():` and forcefully renames it to `clean_vocals.wav` before downloading.
*   **Storage Cleanup**: To prevent Kaggle from hitting limits and keeping a clutter of unique datasets, `processor_thread.py` calls `api.dataset_delete` to destroy the unique disposable dataset post-job. To prevent `%APPDATA%` from bloating locally, `QueueManager` actively runs `shutil.rmtree(temp)` on application startup to sweep orphaned files from force-closures.

---

## 6. Dependency Matrix

EarPurifier relies on a fragile web of ML libraries. **Never arbitrarily update `requirements.txt`.**

| Dependency | Purpose | Strict Constraint |
| :--- | :--- | :--- |
| `PySide6` | Application UI framework | None |
| `audio-separator[gpu]` | Core AI isolation engine | Tied heavily to PyTorch/ONNX compatibility. |
| `onnxruntime-gpu` | Hardware Acceleration | **Must be pinned to `==1.19.2`**. Kaggle T4 GPUs run CUDA 12. Versions `>= 1.20.0` require CUDA 13. Upgrading this causes silent CPU fallback (10x slower). |
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
4.  **Sync Local & Cloud Dependencies:** If you update an AI dependency in `requirements.txt` to run locally, you **must** rebuild and publish a new Kaggle V2 Master Cache. The cloud engine is 100% offline; if the local requirements drift from the cloud wheels, the application will break.
