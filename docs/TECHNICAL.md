# Technical Architecture

*Verified against codebase (v0.0.1).*

---

## Document Scope

- **In scope**:
  - System topology, architectural boundaries, component inventory, thread affinity, and IPC protocols.
  - End-to-end job state machine and lifecycle data contracts.
  - Dual-engine mechanics (Local Subprocess vs. Kaggle Cloud Master Cache).
  - Media pipeline specifications: container probing, stream extraction, alignment, and hardware remuxing.
  - Security architecture, Windows DPAPI encryption at rest, and atomic persistence schemas.
  - Edge-case resiliency catalog (network retry loops, GCS multi-threaded range downloader, PyInstaller compatibility).
- **Out of scope**:
  - Concrete operational procedures, releases, and incident response playbooks (governed by [`OPERATIONS.md`](OPERATIONS.md)).
  - Non-negotiable engineering rules, DOs/DON'Ts, and severity levels (governed by [`BINDING_RULES.md`](BINDING_RULES.md)).
  - End-user installation guides, marketing overviews, and screenshots (governed by [`README.md`](../README.md)).

---

## Governance & Update Policy

- **Update Triggers**: Any modification to thread boundaries, IPC handshakes, state persistence schemas (`job_state.json`, `config.json`), model inference pipelines, media stream mapping logic, or Kaggle cloud integration requires an immediate, synchronized update to this document.
- **Exclusion Policy**: Operational commands, step-by-step incident runbooks, and strict coding invariants must NOT be recorded here; route them to their respective single-source-of-truth documents.

---

## Table of Contents

1. [System Overview & Product Identity](#1-system-overview--product-identity)
2. [Process & Concurrency Topology](#2-process--concurrency-topology)
   - 2.1. [Thread Affinity & Event Marshalling](#21-thread-affinity--event-marshalling)
   - 2.2. [Single-Instance IPC Handshake](#22-single-instance-ipc-handshake)
   - 2.3. [Application Initialization Sequence](#23-application-initialization-sequence)
3. [Domain Map](#3-domain-map)
4. [Component Inventory Table](#4-component-inventory-table)
5. [The Job Lifecycle Pipeline](#5-the-job-lifecycle-pipeline)
   - 5.1. [State Machine Transition Graph](#51-state-machine-transition-graph)
   - 5.2. [Stage-by-Stage Data Contracts](#52-stage-by-stage-data-contracts)
6. [Dual Engine Architecture](#6-dual-engine-architecture)
   - 6.1. [Local Engine Execution Harness](#61-local-engine-execution-harness)
   - 6.2. [Cloud Engine & Kaggle Infrastructure](#62-cloud-engine--kaggle-infrastructure)
   - 6.3. [Master Cache Acceleration (`earpurifier-cloud-assets-v2`)](#63-master-cache-acceleration-earpurifier-cloud-assets-v2)
7. [Media Engine & Multi-Track Stream Preservation](#7-media-engine--multi-track-stream-preservation)
   - 7.1. [Container Probing & Stream Classification](#71-container-probing--stream-classification)
   - 7.2. [Lossless Audio Extraction](#72-lossless-audio-extraction)
   - 7.3. [Duration Padding & Alignment](#73-duration-padding--alignment)
   - 7.4. [OS Hardware Remuxing & Codec Selection](#74-os-hardware-remuxing--codec-selection)
8. [Security, DPAPI & State Persistence Schema](#8-security-dpapi--state-persistence-schema)
   - 8.1. [Windows DPAPI Encryption Architecture](#81-windows-dpapi-encryption-architecture)
   - 8.2. [Configuration Schema (`config.json`)](#82-configuration-schema-configjson)
   - 8.3. [Queue State Schema (`job_state.json`)](#83-queue-state-schema-job_statejson)
   - 8.4. [Atomic File Replacement Mechanics](#84-atomic-file-replacement-mechanics)
9. [Resiliency & Edge-Case Catalog](#9-resiliency--edge-case-catalog)
10. [Cross-Document References](#10-cross-document-references)

---

## 1. System Overview & Product Identity

EarPurifier is a desktop audio isolation and vocal purification studio engineered with PySide6. The application is built to remove background music, instrumentation, and noise from video and audio containers while preserving multi-track stream graphs, subtitles, metadata, and container timing.

EarPurifier operates via an asymmetric **Dual-Engine Architecture**:
- **Local Engine**: Spawns an isolated Python 3.11 environment managed via micromamba, running PyTorch with CUDA 12.1 hardware acceleration or CPU fallback.
- **Cloud Engine**: Offloads compute to remote Kaggle T4 cloud GPUs via serverless worker scripts. It leverages an immutable offline asset cache (`earpurifier-cloud-assets-v2`) to eliminate container boot overhead and reduce spin-up latency from 45 seconds to 2 seconds.

---

## 2. Process & Concurrency Topology

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                Main Process (EarPurifier.exe)                          │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                    UI Thread (Qt Event Loop - QApplication)                      │  │
│  │  • MainWindow, JobQueueSection, JobWidget, UpdateBannerWidget                    │  │
│  │  • QLocalServer ("EarPurifier_SingleInstance_IPC")                               │  │
│  │  • 1-second UI Timers (Elapsed Time, Client-Side ETA Countdown)                  │  │
│  └──────────▲──────────────────▲──────────────────▲──────────────────▲──────────────┘  │
│             │                  │                  │                  │                 │
│      Queued Signals     Queued Signals     Queued Signals     Queued Signals           │
│             │                  │                  │                  │                 │
│  ┌──────────┴────────┐  ┌──────┴────────┐  ┌──────┴────────┐  ┌──────┴──────────────┐  │
│  │ JobProcessor      │  │ LocalJob-     │  │ GitHubUpdate- │  │ Downloader Threads  │  │
│  │ (QThread - Cloud) │  │ Processor     │  │ Checker       │  │ (FFmpeg, Engine,    │  │
│  │ • Ephemeral GCS   │  │ (QThread)     │  │ (QThread)     │  │  Model)             │  │
│  │ • 4-Thread GCS    │  │ • CLI Runner  │  │ • Raw Manifest│  │ • HTTP Streaming    │  │
│  │   Range Downloader│  │ • Subprocess  │  │ • GitHub API  │  │ • Archive Extraction│  │
│  └───────────────────┘  └──────┬────────┘  └───────────────┘  └─────────────────────┘  │
└────────────────────────────────┼───────────────────────────────────────────────────────┘
                                 │ subprocess.Popen
                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                    Child Subprocess Tree (Tracked via process_tracker)                 │
│  • Local Engine: %APPDATA%/EarPurifier/env/Scripts/audio-separator.exe                 │
│  • Transitory FFmpeg/FFprobe invocations                                               │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1. Thread Affinity & Event Marshalling
To prevent thread contention and GUI freezing:
- **UI Thread**: Owns all `QWidget` derived instances. Direct access to GUI elements from worker threads is structurally impossible. Synchronous remote network I/O is strictly forbidden on the UI thread; credential changes via `JobProcessor.update_credentials()` only stage dirty flags in memory, leaving remote API client authentication strictly to the worker thread.
- **Worker QThreads**:
  - `JobProcessor` (`processor_thread.py`): Manages Cloud Kaggle lifecycle, REST calls, kernel polling, and multi-threaded range downloads.
  - `LocalJobProcessor` (`local_processor.py`): Manages local CLI execution and real-time pipe parsing.
  - `GitHubUpdateChecker` (`update_checker.py`): Queries remote update manifests asynchronously.
  - `FFmpegDownloader`, `EngineDownloader`, `ModelDownloader` (`dependency_manager.py`): Execute heavy network downloads.
- **Inter-Thread Signaling**: Workers emit `progress_update`, `status_update`, `finished_job`, and `error_job` Qt Signals. The Qt meta-object compiler routes these across thread boundaries as `QMetaCallEvent` objects into the main thread's event loop.

### 2.2. Single-Instance IPC Handshake
File: `main.py`
- **Server Pipe Name**: `"EarPurifier_SingleInstance_IPC"`
- **Handshake Protocol**:
  1. Secondary instance launches and attempts connection to `EarPurifier_SingleInstance_IPC` via `QLocalSocket`.
  2. If connection succeeds (`waitForConnected(500)`):
     - Writes `b"ACTIVATE\n"`, flushes (`waitForBytesWritten(500)`), and disconnects.
     - Calls `os._exit(0)` for instantaneous process termination.
  3. Primary instance receives incoming connection on `QLocalServer.newConnection`:
     - Reads payload (`waitForReadyRead(500)`).
     - If payload is `"ACTIVATE"`: invokes `window.showNormal()`, `window.raise_()`, and `window.activateWindow()` to restore and focus the window.
     - If connection fails on boot, the primary instance calls `QLocalServer.removeServer(server_name)` to clean orphaned pipe descriptors and calls `local_server.listen(server_name)`.

### 2.3. Application Initialization Sequence
1. **OS Integration**: Configures `SetCurrentProcessExplicitAppUserModelID("EarPurifier.SproutAudio.Studio.2.0")` for taskbar icon binding. Configures Per-Monitor DPI Awareness v2 (`SetProcessDpiAwareness(2)`).
2. **Crash Trap**: Binds `sys.excepthook = handle_uncaught_exception` to intercept unhandled exceptions and render localized modal alerts.
3. **Single-Instance Check**: Validates that no existing instance is listening on `EarPurifier_SingleInstance_IPC`.
4. **Filesystem Provisioning**: Creates `%APPDATA%/EarPurifier/` directory hierarchy (`temp/`, `empty_buffer/`, `applogs/`, `bin/`, `env/`).
5. **State Reconciliation**: `QueueManager._load_state()` resets transient interrupted jobs to `"ERROR"` and cleans old temp directories.
6. **Logging Initialization**: `logger_setup.setup_logger()` initializes a 10 MB rotating file handler and evicts logs older than 48 hours.
7. **UI Instantiation**: Constructs `MainWindow`, applies initial theme and language (defaults to Arabic `"ar"` with Right-to-Left layout), and starts workers.
8. **Deferred Update Check**: Schedules `start_auto_update_check()` via `QTimer.singleShot(2500)` to preserve instant startup responsiveness.

---

## 3. Domain Map

| Domain | Files | Responsibilities |
| :--- | :--- | :--- |
| **Presentation (UI)** | `ui/main_window.py`<br>`ui/job_queue_section.py`<br>`ui/job_widget.py`<br>`ui/components.py`<br>`ui/dialogs.py`<br>`ui/theme.py`<br>`ui/update_banner.py`<br>`ui/overlay_widgets.py`<br>`ui/queue_widgets.py` | PySide6 widget tree, custom vector painting, theme tokens (Soft Sage / Botanical Slate), dynamic RTL layout mirroring, modal dialogs, and non-blocking update banners. |
| **Localization** | `i18n.py` | Bilingual translation dictionary (`ar`/`en`), Arabic pluralization rules, and runtime language retranslation without application restart. |
| **State & Lifecycle** | `queue_manager.py`<br>`config_manager.py`<br>`process_tracker.py` | Concurrency synchronization (`threading.RLock`), atomic JSON persistence, Windows DPAPI encryption, and recursive process tree termination. |
| **Cloud Engine** | `processor_thread.py`<br>`kaggle_bridge.py`<br>`worker/worker.py` | Kaggle API authentication (`KGAT_`), disposable dataset buffers, dynamic kernel injection, execution polling, and 4-thread chunked GCS downloader. |
| **Local Engine** | `local_processor.py`<br>`dependency_manager.py` | Micromamba environment bootstrap, CUDA/CPU detection, subprocess pipe draining (`bufsize=1`), and real-time stdout regex tracking. |
| **Media Pipeline** | `media_engine.py` | FFprobe stream probing, lossless FLAC extraction, audio padding/trimming, and hardware-accelerated remuxing (`aac_mf`, `aac_at`). |
| **Tooling & Build** | `build.py`<br>`update_checker.py`<br>`logger_setup.py` | Isolated PyInstaller compilation pipeline, SemVer release checker, and bounded log rotation. |

---

## 4. Component Inventory Table

| Module | Primary Classes / Symbols | Thread Affinity | State Managed | I/O Operations |
| :--- | :--- | :--- | :--- | :--- |
| `main.py` | `handle_uncaught_exception`, `main` | Main UI Thread | Process lifecycle, Single-Instance IPC | `QLocalServer`, `QLocalSocket` |
| `ui/main_window.py` | `MainWindow`, `SidebarLogo` | Main UI Thread | Navigation index, active worker thread handles | Reads `config.json`, triggers process launches |
| `ui/job_queue_section.py`| `JobQueueSection` | Main UI Thread | View filter state, selection mode, batch lists | Invokes `QueueManager` mutations |
| `ui/job_widget.py` | `JobWidget` | Main UI Thread | Local card presentation, 1-second countdown timer | Local UI timer updates |
| `ui/components.py` | `SidebarNavButton`, `EngineTelemetryPill`, `RotatingSpinner` | Main UI Thread | Vector painting state, breath timer phase | In-memory canvas rendering |
| `ui/dialogs.py` | `SettingsDialog`, `DeleteConfirmDialog`, `AudioTrackSelectDialog` | Main UI Thread | Form entries, transient selections | Reads/writes `config.json` via `ConfigManager` |
| `ui/theme.py` | `Theme`, `ThemeMode` | Main UI Thread | Color tokens, QSS templates, font families | Resolves SVG assets on disk |
| `queue_manager.py` | `QueueManager` | Thread-Safe (Any) | `self.state["jobs"]`, `self._pending_deletions` protected by `threading.RLock` | Atomic read/write `%APPDATA%/.../job_state.json` |
| `config_manager.py`| `ConfigManager` | Thread-Safe (Any) | Application preferences, encrypted API key | Atomic read/write `%APPDATA%/.../config.json` |
| `process_tracker.py`| `register_process`, `kill_process_tree`, `cleanup_all_subprocesses` | Thread-Safe (Any) | `_ACTIVE_SUBPROCESSES: Set[Popen]` | Subprocess signals, `taskkill` executions |
| `processor_thread.py`| `JobProcessor` | Cloud Worker QThread | Active Kaggle kernel ID, retry counters | Network REST calls to Kaggle, temporary audio files |
| `kaggle_bridge.py` | `KaggleBridge` | Cloud Worker QThread | Disposable dataset metadata, GCS URL tokens | Multi-threaded HTTP Range GET requests, Kaggle SDK |
| `local_processor.py`| `LocalJobProcessor` | Local Worker QThread | Active subprocess handle, progress percentage | Subprocess pipe reading (`stdout`/`stderr`), disk audio |
| `media_engine.py` | `get_duration`, `probe_container`, `extract_audio`, `remux_media`, `_run_ffmpeg_abortable`, `JobAbortedError` | Worker Thread Context| Stateless functional operations | Spawns `ffmpeg.exe` and `ffprobe.exe` subprocesses |
| `update_checker.py`| `GitHubUpdateChecker` | Checker QThread | Cached release metadata, SemVer tuples | HTTPS queries to raw manifest and GitHub API |
| `logger_setup.py` | `setup_logger` | Global | Python logging handlers | Rotating disk writes to `applogs/earpurifier.log` |

---

## 5. The Job Lifecycle Pipeline

### 5.1. State Machine Transition Graph

```
                                  ┌─────────────┐
                                  │   PENDING   │ ◄─── QueueManager.add_job()
                                  └──────┬──────┘
                                         │ Worker picks up next job
                                         ▼
                                  ┌─────────────┐
                                  │ EXTRACTING  │ ◄─── media_engine.extract_audio()
                                  └──────┬──────┘
                                         │ Lossless FLAC extracted
                    ┌────────────────────┴────────────────────┐
                    │ (Cloud Engine)                          │ (Local Engine)
                    ▼                                         ▼
             ┌─────────────┐                           ┌──────────────────┐
             │  UPLOADING  │                           │ PROCESSING_LOCAL │
             └──────┬──────┘                           └────────┬─────────┘
                    │ Kaggle buffer ingest complete             │
                    ▼                                           │
          ┌──────────────────┐                                  │
          │ PROCESSING_CLOUD │                                  │
          └─────────┬────────┘                                  │
                    │ Kaggle kernel status: COMPLETE            │
                    ▼                                           │
             ┌─────────────┐                                    │
             │ DOWNLOADING │ (4-Thread Chunked GCS Downloader)  │
             └──────┬──────┘                                    │
                    │ Output FLAC reconstructed                 │
                    └────────────────────┬──────────────────────┘
                                         │
                                         ▼
                                  ┌─────────────┐
                                  │  REMUXING   │ ◄─── media_engine.remux_media()
                                  └──────┬──────┘
                                         │ Container assembled losslessly
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
             ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
             │  COMPLETED  │      │    ERROR    │      │   ABORTED   │
             └─────────────┘      └─────────────┘      └─────────────┘
              (Terminal)           (Terminal)           (Terminal)
  * Note: Any active phase transitions directly to ABORTED on user abort, card deletion, or window close.
```

### 5.2. Stage-by-Stage Data Contracts

1. **Queueing (`PENDING`)**:
   - **2-Pass Atomic Batch Pipeline**:
     - *Pass 1 (Probing & Track Aggregation)*: `media_engine.probe_container()` probes all selected containers without mutating `QueueManager`. If any containers contain $> 1$ audio stream, a unified scrollable `AudioTrackSelectDialog` presents each multi-track file with a folded-by-default stream dropdown (defaulting strictly to the first audio stream `0:a:0`).
     - *Pass 2 (Atomic Ingestion & UI Synchronization)*: Upon user confirmation, all jobs are committed in memory via `QueueManager.add_job(..., save=False)` and flushed to physical disk via a single atomic `QueueManager._save_state()`. This prevents premature background dequeueing ("ghost execution") and guarantees all UI cards are rendered before worker threads can claim pending jobs.
   - Each job captures an immutable snapshot: file path, duration, selected audio track index, mode, and model name.
   - Initial state written atomically to `job_state.json`.
2. **Extraction (`EXTRACTING`)**:
   - `started_at` ISO-8601 UTC timestamp stamped on the job.
   - Invokes `media_engine.extract_audio()` to generate a 48,000 Hz, 2-channel stereo FLAC file in `%APPDATA%/EarPurifier/temp/<job_id>/audio_<job_id[:8]>.flac`.
3. **AI Separation Phase**:
   - **ETA Engine Mechanics**:
     - **Cloud Path (`UPLOADING` $\to$ `PROCESSING_CLOUD` $\to$ `DOWNLOADING`)**: ETA is calculated from empirical Real-Time Factors ($\text{RTF}_{\text{model}}$) on Kaggle T4 GPUs: Kim Vocal 2 ($\text{RTF} = 0.135$, ~7.5x real-time), MDX23C ($\text{RTF} = 0.270$, ~3.7x real-time), and Band-Split RoFormer ($\text{RTF} = 0.680$, ~1.45x real-time), plus bounded stage overheads for extraction, upload, container boot, download, and hardware remuxing. As stages complete, remaining ETA dynamically clamps to the sum of remaining phases.
     - **Local Path (`PROCESSING_LOCAL`)**: `LocalJobProcessor` launches isolated `audio-separator.exe`. Real-time progress is scraped from stdout regex `r'(\d{1,3})%'` and dispatched to UI, where `JobWidget` dynamically calculates remaining time from elapsed stage time ($\text{elapsed} \times \frac{100 - P}{P} + T_{\text{remux}}$) and drives a determinate progress bar.
   - **Cloud Infrastructure Mechanics**:
     - Creates ephemeral dataset buffer `{username}/earpurifier-audio-buffer-{job_id[:8]}`.
     - Actively polls `api.dataset_status()` every 2 seconds until verified `"ready"` (90s ceiling), eliminating blind sleep latency and unindexed dataset push errors.
     - Pushes worker kernel with injected model specifications and dynamic duration-aware session timeout (`\min(43200, \max(7200, \text{duration} \times 3.0 + 1800))`).
     - Polls status every 30 seconds (sliced into 1-second ticks for responsive abort handling). If `QUEUED` exceeds 2 minutes, dispatches `QUEUE_CONGESTED` telemetry, pausing the client-side ETA countdown until `RUNNING`.
     - Downloads `clean_vocals.flac` via 4-thread chunked HTTP Range queries.
4. **Remuxing & Assembly (`REMUXING`)**:
   - `media_engine.pad_or_trim_audio()` guarantees exact duration parity with the source file.
   - `media_engine.remux_media()` maps original video tracks (`-map 0:v? -c:v copy`), original subtitle tracks (`-map 0:s? -c:s copy`), and replaces the targeted audio stream with hardware-accelerated encoding (`aac_mf`/`aac_at`).
5. **Completion (`COMPLETED`)**:
   - `final_elapsed_seconds` computed. Local temp folder purged. Ephemeral Kaggle dataset deleted via API.
6. **Abortion & Teardown (`ABORTED`)**:
   - **Trigger Paths**: User clicks "Abort" on active job card, deletes in-flight job card, or confirms exit in `CloseActiveJobDialog` during application shutdown.
   - **Resurrection Guard**: `QueueManager.update_job()` actively blocks and suppresses any status updates attempting to revert an `ABORTED` job back to an active or `COMPLETED` status.
   - **Transient Deletion Buffer**: Deleting an active job immediately removes it from the UI while staging its metadata and deletion parameters in `QueueManager._pending_deletions`. The worker thread evaluates `is_job_aborted()` (which returns `True` for pending deletions) and invokes `finalize_job_abort()` to execute deferred disk cleanup.
   - **Subprocess & Remote Teardown**:
     - Local Engine: Immediately executes `process_tracker.kill_process_tree()` on `audio-separator.exe` upon detecting abort in the stdout reader.
     - Media Engine: `_run_ffmpeg_abortable()` polls `abort_check()` every 50–100 ms, killing FFmpeg process trees on abort and raising `JobAbortedError`.
     - Cloud Engine: Cancels remote Kaggle kernel via `api.kernel_cancel()`, executes `delete_dataset_with_retry()` with exponential backoff to cleanly release dataset mounts, purges local temporary working directories, and halts chunk downloading.

---

## 6. Dual Engine Architecture

### 6.1. Local Engine Execution Harness
Managed by `local_processor.py` and `dependency_manager.py`:
- **Isolation Boundary**: Runs in a hermetic Python 3.11 environment in `%APPDATA%/EarPurifier/env` provisioned via micromamba.
- **Hardware Routing**: Queries CUDA availability via Windows driver probe (`nvcuda.dll`) and `nvidia-smi -L` (3-second timeout). Selects PyTorch `cu121` on NVIDIA platforms or `cpu` wheels on non-GPU platforms.
- **Subprocess Execution**:
  - Sets `bufsize=1` and `stderr=subprocess.STDOUT` to eliminate OS pipe saturation deadlocks.
  - Prepends isolated environment scripts and MinGW DLL paths to process `PATH`.
  - Registers the `Popen` instance in `process_tracker`.
- **Supported Local Model Weights**:
  - Band-Split RoFormer: `model_bs_roformer_ep_317_sdr_12.9755.ckpt` (~1.8 GB)
  - MDX23C: `MDX23C-8KFFT-InstVoc_HQ.ckpt` (~1.2 GB)
  - Kim Vocal 2: `Kim_Vocal_2.onnx` (~215 MB)

### 6.2. Cloud Engine & Kaggle Infrastructure
Managed by `processor_thread.py`, `kaggle_bridge.py`, and `worker/worker.py`:
- **Authentication**: Dynamically maps credentials. Tokens prefixed with `KGAT_` are mapped to `KAGGLE_API_TOKEN` (HTTP Bearer Auth); legacy tokens are mapped to `KAGGLE_KEY` (HTTP Basic Auth). Sets `KAGGLE_CONFIG_DIR` to a dummy path to prevent reading stale local config files. Credential updates stage an in-memory dirty flag (`_credentials_dirty`); Kaggle REST client re-initialization occurs exclusively within worker thread context when idle (`not active_cloud`) to eliminate UI thread network freezes and avoid mid-job connection severance.
- **Ephemeral Dataset Architecture**: Each job uses an isolated dataset slug `earpurifier-audio-buffer-<uuid>` containing the 48kHz FLAC stem and `dataset-metadata.json`, actively polled via `api.dataset_status()` until verified `"ready"`.
- **Ephemeral Dataset Teardown & Backoff**: Dataset deletion on abort or completion calls `delete_dataset_with_retry(dataset_id)`, which applies exponential backoff on HTTP 403 Forbidden / 400 Bad Request to safely wait for Kaggle to unmount datasets from stopping kernels, while treating 404 Not Found as immediate success.
- **Kernel Injection & Dynamic Timeout**: Modifies `worker/worker.py` in-memory using regex substitutions to bind target model filenames and expected audio stem identifiers. Computes a bounded duration-aware execution timeout (`min(43200, max(7200, duration * 3.0 + 1800))`) passed to `api.kernels_push()`.
- **4-Thread Chunked GCS Downloader**: Bypasses Kaggle SDK output methods. Retrieves direct Google Cloud Storage signed URLs via `ApiListKernelSessionOutputRequest`, determines file size via streaming GET, and downloads across 4 concurrent threads using `Range: bytes=X-Y` requests into `.part0` through `.part3` before sequential stitching. Accepts `abort_check` callback to cleanly stop worker download threads and purge incomplete `.part*` fragments upon user cancellation.

### 6.3. Master Cache Acceleration (`earpurifier-cloud-assets-v2`)
- **Dataset Slug**: `verymuch/earpurifier-cloud-assets-v2` (mounted read-only under `/kaggle/input/`).
- **Cache Contents**:
  - `models/`: Static binary weights for RoFormer, MDX23C, and Kim Vocal 2.
  - `wheels/`: Pre-compiled manylinux binary wheels for `audio-separator[gpu]`, `torch`, `onnxruntime-gpu<1.27.0`.
- **Startup Latency**: Worker runs `pip install --no-index --find-links=.../wheels`, reducing environment setup from 45 seconds to **2 seconds**.
- **Graceful Fallback**: If Kaggle updates its underlying Python runtime and offline wheel installations fail, `worker.py` catches `subprocess.CalledProcessError` and installs compatible packages from PyPI online.

---

## 7. Media Engine & Multi-Track Stream Preservation

File: `media_engine.py`

### 7.1. Container Probing & Stream Classification
- **Duration Probe**: Invokes `ffprobe -v error -analyzeduration 1000000 -probesize 1000000 -show_entries format=duration -of csv=p=0` (180.0s timeout).
- **Container Structure Probe**: Invokes `ffprobe -v error -analyzeduration 10000000 -probesize 10000000 -show_streams -show_format -of json` (180.0s timeout).
- **Attached Picture Filtering**: Explicitly discards video streams where `disposition.attached_pic == 1` (e.g., embedded album art in MP3/FLAC), preventing audio files from being misidentified as videos.

### 7.2. Lossless Audio Extraction
- **Command Structure**:
  `ffmpeg -y -i <input> -map 0:a:<index> -vn -c:a flac -ar 48000 -ac 2 <output.flac>`
- **Downmix Invariant**: Enforces `-ac 2` (stereo) and `-ar 48000` (48 kHz) to match the fixed Short-Time Fourier Transform (STFT) tensor shapes required by neural separation networks.

### 7.3. Duration Padding & Alignment
- **Duration Drift Compensation**: AI separation models introduce small timing offsets (50–500 ms) due to STFT hop-length framing.
- **Under-length Streams**: Appends `-af apad -t <target_duration>` to pad digital PCM silence to the exact millisecond.
- **Over-length Streams**: Appends `-t <target_duration>` to truncate container boundary excess.
- **Large File Protection**: Appends `-rf64 auto` when writing WAV containers to prevent corruption if files exceed 4 GiB.
- **Zero-Duration Trap**: Traps `target_duration <= 0.0` to prevent destroying audio stems via empty truncations.

### 7.4. OS Hardware Remuxing & Codec Selection

#### Hardware Encoder Priority
- **Windows (`win32`)**: `aac_mf` (Microsoft Media Foundation AAC encoder). Runs at **~1,500 fps** (~58x real-time).
- **macOS (`darwin`)**: `aac_at` (Apple AudioToolbox AAC encoder). Runs at **~60x real-time**.
- **Fallback**: Native built-in `aac`.

#### Container Extension Routing Table
| Extension Group | Audio Codec | Bitrate / Quality Flags | Video / Subtitle Strategy |
| :--- | :--- | :--- | :--- |
| `.mp4`, `.mov`, `.m4a` | `aac_mf` / `aac_at` / `aac` | `-b:a 256k` | `-map 0:v? -c:v copy`, `-map 0:s? -c:s copy` |
| `.mkv`, `.mka`, `.flac` | `flac` | Lossless | `-map 0:v? -c:v copy`, `-map 0:s? -c:s copy` |
| `.webm`, `.opus` | `libopus` | `-b:a 192k` | `-map 0:v? -c:v copy`, `-map 0:s? -c:s copy` |
| `.ogg` | `libvorbis` | `-q:a 6` | `-map 0:v? -c:v copy` |
| `.mp3` | `libmp3lame` | `-q:a 0` (V0 VBR) | Direct stream replacement |

#### Non-Destructive Stream Mapping Rules
```text
-map 0:v? -c:v copy             # Losslessly copies all video streams
-map 0:s? -c:s copy             # Losslessly copies all subtitle tracks
-map 1:a:0 -c:a:<target> <enc>  # Replaces designated audio stream
-map 0:a:<i> -c:a:<i> copy      # Retains all other audio tracks bit-for-bit
-map_metadata 0                 # Preserves global container tags & chapters
-avoid_negative_ts make_zero    # Eliminates initial timestamp desync
-movflags +faststart            # Relocates moov atom for streaming optimization
```

---

## 8. Security, DPAPI & State Persistence Schema

### 8.1. Windows DPAPI Encryption Architecture
File: `config_manager.py`
- **Native Implementation**: Invokes `CryptProtectData` and `CryptUnprotectData` via `ctypes.windll.crypt32`.
- **Entropy & Description**: Tagged with description string `"EarPurifierKey"`.
- **Memory Safety**: Invokes `ctypes.windll.kernel32.LocalFree` on output data pointers immediately after reading byte arrays, preventing native Windows heap leaks.
- **Prefix Format**: Encrypted strings are stored as Base64 with prefix:
  `"enc:" + base64.b64encode(cipher_bytes).decode("ascii")`

### 8.2. Configuration Schema (`config.json`)
Stored at `%APPDATA%/EarPurifier/config.json`:
```json
{
  "kaggle_username": "username_string",
  "kaggle_api_key": "enc:AQAAANCMnd8BFdERjHoAwE...",
  "output_folder": "C:\\Users\\User\\Desktop\\EarPurifier_Output",
  "enable_logging": true,
  "local_model": "SOTA (RoFormer) - Requires High-End GPU",
  "processing_mode": "Cloud (Kaggle)",
  "delete_output_files": false,
  "language": "ar",
  "check_updates": true,
  "ignored_release_tag": "",
  "last_update_check": "2026-10-31T12:00:00"
}
```

### 8.3. Queue State Schema (`job_state.json`)
Stored at `%APPDATA%/EarPurifier/job_state.json`:
```json
{
  "jobs": {
    "c8a1451b-4352-4911-b016-b51cfa8cfc65": {
      "id": "c8a1451b-4352-4911-b016-b51cfa8cfc65",
      "original_media": "C:\\Media\\Podcast.mp4",
      "mode": "Cloud (Kaggle)",
      "duration": 345.2,
      "model": "Band-Split RoFormer (HQ Vocal/Instrumental)",
      "selected_audio_stream": 0,
      "probe_result": { ... },
      "status": "COMPLETED",
      "message": "Purification complete · Audio isolated",
      "error_message": "",
      "started_at": "2026-10-31T12:05:00+00:00",
      "added_at": "2026-10-31T12:04:30+00:00",
      "final_elapsed_seconds": 68,
      "output_media": "C:\\Output\\Podcast_purified.mp4"
    }
  }
}
```

### 8.4. Atomic File Replacement Mechanics
All updates to `config.json` and `job_state.json` invoke `_atomic_write_json()`:
1. Writes JSON payload to `tempfile.NamedTemporaryFile` in the target directory.
2. Flushes application buffers (`f.flush()`).
3. Enforces physical disk sync via `os.fsync(f.fileno())`.
4. Closes file handle explicitly.
5. Replaces target file via `os.replace()` in a 3-attempt loop with 50 ms sleep intervals to bypass transient Windows file locks.

---

## 9. Resiliency & Edge-Case Catalog

| Problem / Edge Case | Root Cause | Engineered Remediation | Code Reference |
| :--- | :--- | :--- | :--- |
| **PyInstaller `tqdm` Crash** | Under `--windowed` / `--noconsole` builds, `sys.stderr` is `None`. Kaggle SDK `tqdm` calls crash with `AttributeError`. | Kaggle SDK dataset and kernel upload methods strictly pass `quiet=True` to disable `tqdm`. | `kaggle_bridge.py` |
| **Kaggle `KGAT_` Bearer Auth** | New Personal Access Tokens starting with `KGAT_` fail with 401 when assigned to legacy `KAGGLE_KEY` (Basic Auth). | Inspects token prefix. If `KGAT_`, assigns to `KAGGLE_API_TOKEN` to force Bearer Auth; pops stale keys. | `kaggle_bridge.py` |
| **GCS Signed URL Download Truncation** | Official `api.kernels_output()` truncates partially downloaded files to 0 bytes on `IncompleteRead` retries. | Intercepts direct GCS signed URLs; downloads chunks concurrently across 4 worker threads via HTTP `Range`. | `kaggle_bridge.py` |
| **GCS `HEAD` Request 404** | Google Cloud Storage rejects HTTP `HEAD` verbs on Kaggle signed URLs with 404/403. | Queries `Content-Length` via an initial streaming `GET` request before dispatching range threads. | `kaggle_bridge.py` |
| **Silent Cloud GPU $\to$ CPU Fallback** | Dynamic linking errors in ONNX Runtime can cause silent fallback to CPU, burning 25 mins of quota. | Inspects active inference session (`model_run.get_providers()`). Aborts with `RuntimeError` within 5s if CUDA missing. | `worker/worker.py` |
| **Deadlock on Child Process Pipes** | Unbuffered separate pipes (`stdout`/`stderr`) saturate Windows 64 KB kernel pipe buffers. | Binds `stderr=subprocess.STDOUT` with `bufsize=1` for unified, line-buffered stream draining. | `local_processor.py` |
| **Orphaned Background Workers** | `proc.kill()` on Windows leaves underlying worker processes running in memory. | Executes `taskkill /F /T /PID <pid>` to annihilate the entire process tree down to child leaves. | `process_tracker.py` |
| **Zero-Duration Audio Destruction** | Corrupt container headers returning `0.0` duration cause `ffmpeg -t 0` to create empty files. | Traps `target_duration <= 0.0` and falls back to a passthrough file copy without trimming. | `media_engine.py` |
| **Attached Picture Remux False Positives** | Audio files with embedded album art have video streams flagged with `disposition.attached_pic == 1`. | Probing filters out attached picture streams from the video list, treating the file as pure audio. | `media_engine.py` |
| **Windows Title Bar Theme Mismatch** | Dark theme in Qt doesn't automatically theme the OS window frame on Windows 10/11. | Calls native DWM API `DwmSetWindowAttribute` with `DWMWA_USE_IMMERSIVE_DARK_MODE` (attribute 20 / 19). | `ui/theme.py` |
| **Unindexed Dataset Push Race** | Static 45s sleep pushes kernel while GCS ingestion is still unpacking, causing scheduler deferrals. | Actively polls `api.dataset_status()` every 2s until verified `"ready"`. | `kaggle_bridge.py` |
| **Cloud GPU Queue Congestion** | Platform-wide GPU pool demand spikes leave batch kernels queued for multiple minutes. | Dynamic session timeout bounds footprint; UI freezes client-side ETA and alerts user after 2m. | `processor_thread.py`, `ui/job_widget.py` |
| **Single-Instance Deadlocks** | Second instance attempts to initialize resources or corrupt state files. | Handshake via `QLocalSocket` activates existing instance window and immediately terminates second process via `os._exit(0)`. | `main.py` |
| **UI Thread Remote Auth Freeze** | Synchronous Kaggle token introspection during "+ Add Media" or Settings save blocks Qt event loop for 2–5s. | Stages credentials in memory; defers `KaggleBridge` instantiation to idle cycles on the worker thread. | `processor_thread.py`, `ui/main_window.py` |
| **Premature Batch Dequeue (Ghost Job Race)** | Single-pass queueing caused background worker to dequeue single-stream audio jobs while the multi-track dialog blocked the UI. | Enforces 2-pass atomic batch ingestion: probes and resolves track dialogs before any job enters `QueueManager`. | `ui/main_window.py`, `queue_manager.py` |

---

## 10. Cross-Document References

- For mandatory development invariants, non-negotiable coding rules, and severity levels, see [`BINDING_RULES.md`](BINDING_RULES.md).
- For operational runbooks, building standalone executables, publishing GitHub releases, and Kaggle cache maintenance, see [`OPERATIONS.md`](OPERATIONS.md).
- For high-level product identity, feature highlights, and build commands, see [`README.md`](../README.md).
