# Engineering Invariants & Binding Rules

*Verified against codebase (v0.0.1).*

---

## Document Scope

- **In scope**:
  - Non-negotiable technical invariants, fatal traps, and unwritten contracts across the EarPurifier codebase.
  - Razor-sharp rules categorized by severity (CRITICAL, MODERATE, ADVISORY) detailing the rule, the landmine (what catastrophically breaks), and the enforcement point.
- **Out of scope**:
  - Deep system architecture and component designs (governed by [`TECHNICAL.md`](TECHNICAL.md)).
  - Operational runbooks, compilation playbooks, and cache rebuilds (governed by [`OPERATIONS.md`](OPERATIONS.md)).
  - User guides and product showcase (governed by [`README.md`](../README.md)).

---

## Governance & Update Policy

- **Update Triggers**: Any newly discovered SDK trap, silent fallback, concurrency deadlock, container remuxing hazard, or hard architectural boundary triggers an immediate, mandatory addition to this document.
- **Exclusion Policy**: Generic programming guidelines (e.g., "write readable code") and narrative architectural explanations are strictly forbidden here. Keep entries ultra-dense, factual, and minimal.

---

## Table of Contents

1. [Governance & Severity Taxonomy](#1-governance--severity-taxonomy)
2. [CRITICAL Binding Rules (P0)](#2-critical-binding-rules-p0)
3. [MODERATE Binding Rules (P1)](#3-moderate-binding-rules-p1)
4. [ADVISORY Binding Rules (P2)](#4-advisory-binding-rules-p2)

---

## 1. Governance & Severity Taxonomy

| Severity Level | System Impact | Enforcement Action |
| :--- | :--- | :--- |
| **CRITICAL (P0)** | Application deadlocks, native crashes, data loss, credential compromise, cloud GPU quota burn, or zombie process locks. | Immediate build rejection; zero tolerance in code review. |
| **MODERATE (P1)** | Pipe saturation, container stream corruption, A/V desynchronization, UI state resets, or unhandled media traps. | Blocks release pipeline; requires regression testing. |
| **ADVISORY (P2)** | UI layout mirroring glitches, untranslated fallback strings, font rasterization defects, or log disk bloat. | Corrective maintenance required before production tagging. |

---

## 2. CRITICAL Binding Rules (P0)

*Violation causes application deadlock, process locking, data destruction, credential exposure, or cloud GPU quota drain.*

| # | Rule / Invariant & The Landmine | Severity | Enforced at |
|---|---|---|---|
| 1 | **UI Thread Non-Blocking Invariant**: Never call `.wait()` on worker threads without a timeout or execute synchronous network/subprocess calls on the main thread; doing so deadlocks the PySide6 event loop and triggers Windows "Application Not Responding" (Ghost Window). | CRITICAL — UI Stability | `ui/main_window.py`, `process_tracker.py` (`terminate_qt_threads` with 500ms timeout) |
| 2 | **Process Teardown & WER Process Lock Guard**: Application shutdown MUST terminate child process trees via `taskkill /F /T /PID`, stop update checkers, close IPC sockets, and terminate via `os._exit()`. Calling standard `sys.exit()` causes PySide6 C++ destructors to deadlock in `ntdll!RtlAcquireSRWLockExclusive`, leaving `EarPurifier.exe` indefinitely suspended in Task Manager and locking the binary on disk. | CRITICAL — Windows OS | `main.py` (lines around `os._exit`), `process_tracker.py` (`cleanup_all_subprocesses`, `kill_process_tree`) |
| 3 | **Job Snapshot Immutability Contract**: Background processors must read model, mode, and stream parameters exclusively from `job["model"]` snapshots, NEVER from live `ConfigManager` instances; reading live config causes in-flight jobs to mutate when users adjust settings during active queues. | CRITICAL — Data Integrity | `queue_manager.py` (`QueueManager.add_job`), `processor_thread.py`, `local_processor.py` |
| 4 | **Queue Mutex & Deepcopy Isolation**: `QueueManager` state dictionary MUST be locked via `threading.RLock()` on all reads/writes. `get_job()` and `get_all_jobs()` MUST return `copy.deepcopy()`; exposing internal dictionaries directly triggers `RuntimeError: dictionary changed size during iteration`. | CRITICAL — Thread Safety | `queue_manager.py` (`QueueManager._lock`, `get_job`, `get_all_jobs`) |
| 5 | **Windows DPAPI Credential Protection**: Kaggle API keys must be encrypted at rest using Windows DPAPI (`CryptProtectData`) prefixed with `enc:` and decrypted via `CryptUnprotectData`. Allocated native memory must be freed via `kernel32.LocalFree`; storing plaintext keys in `config.json` is strictly prohibited. | CRITICAL — Security | `config_manager.py` (`ConfigManager.save_config`, `_load_config`) |
| 6 | **Atomic Persistence with Windows File-Lock Retry**: State updates (`job_state.json`, `config.json`) must use `_atomic_write_json` with same-directory `NamedTemporaryFile`, `os.fsync`, and an `os.replace` 3-attempt retry loop with 50ms backoff; direct `open("w")` causes zero-byte file truncation on crash or antivirus read locks. | CRITICAL — Storage Safety | `queue_manager.py`, `config_manager.py` (`_atomic_write_json`) |
| 7 | **Kaggle `KGAT_` Bearer Authentication**: Kaggle Personal Access Tokens starting with `KGAT_` MUST be mapped to `KAGGLE_API_TOKEN` (HTTP Bearer Auth) while legacy 32-hex keys map to `KAGGLE_KEY` (Basic Auth). Assigning `KGAT_` to `KAGGLE_KEY` triggers an immediate 401 Unauthorized rejection. | CRITICAL — Cloud Auth | `kaggle_bridge.py` (`KaggleBridge.__init__`) |
| 8 | **PyInstaller `tqdm` Headless Crash Bypass**: All Kaggle SDK dataset and kernel creation calls MUST pass `quiet=True`; in `--windowed` / `--noconsole` executables, detached `sys.stderr` causes `tqdm` writes to raise `AttributeError: 'NoneType'`, silently aborting uploads. | CRITICAL — Runtime Crash | `kaggle_bridge.py` (`dataset_create_new`, `kernels_push`) |
| 9 | **Cloud Disposable Dataset Isolation**: Every cloud job MUST upload audio to a uniquely stamped, disposable dataset buffer (`earpurifier-audio-buffer-{job_id[:8]}`) with matching file `audio_{job_id[:8]}.flac`, and destroy it post-job via `api.dataset_delete()`. Reusing static datasets causes stale-cache processing and race conditions. | CRITICAL — Cloud Quota | `kaggle_bridge.py` (`push_audio`), `processor_thread.py` (`_handle_abort`) |
| 10 | **Active Cloud GPU Session Assertion (Anti-CPU Trap)**: Kaggle worker scripts MUST assert that `"CUDAExecutionProvider"` is present in the active model inference session (`model_run.get_providers()`), aborting in under 5s if absent; relying only on `ort.get_available_providers()` allows silent CPU fallback that burns 25 minutes of GPU quota. | CRITICAL — Cloud Quota | `worker/worker.py` (lines around `CUDAExecutionProvider` check) |
| 11 | **Cloud Quota Teardown on Abort / Close**: Aborting a job or confirming application exit via `CloseActiveJobDialog` MUST cancel the remote Kaggle kernel via `bridge.cancel_kernel()` and delete the remote dataset buffer; simply terminating local threads leaves the cloud kernel burning the user's weekly 30-hour GPU quota. | CRITICAL — Cloud Quota | `ui/main_window.py` (`closeEvent`), `processor_thread.py` (`stop`, `_handle_abort`) |
| 12 | **Settings Save Mid-Job Connection Severing Guard**: In `MainWindow.open_settings()`, background threads and `KaggleBridge` MUST ONLY be re-initialized if credentials (`kaggle_username`, `kaggle_api_key`) have strictly mutated; re-initializing unconditionally severs active connection pools and orphans in-flight cloud jobs. | CRITICAL — Network Resiliency | `ui/main_window.py` (`MainWindow.open_settings`) |

---

## 3. MODERATE Binding Rules (P1)

*Violation causes container stream corruption, subprocess deadlocks, UI state resets, or unhandled media failures.*

| # | Rule / Invariant & The Landmine | Severity | Enforced at |
|---|---|---|---|
| 13 | **Subprocess Pipe Draining & STDOUT Consolidation**: Subprocesses reading stdout line-by-line (`audio-separator`) MUST redirect `stderr=subprocess.STDOUT` with `bufsize=1`. Splitting unbuffered pipes causes Windows 64 KB pipe buffer saturation and permanent subprocess deadlocks. | MODERATE — Process Deadlock | `local_processor.py`, `dependency_manager.py` |
| 14 | **Stereo Frame Extraction Invariant (`-ac 2`)**: Audio extracted for AI separation MUST always enforce `-c:a flac -ar 48000 -ac 2`. Supplying 5.1/7.1 multichannel audio crashes the PyTorch/ONNX separation models with tensor dimension mismatch errors. | MODERATE — Model Execution | `media_engine.py` (`extract_audio`) |
| 15 | **Unified Stream-Graph Remuxing**: Media remuxing must never bifurcate into separate audio/video paths; use a single pipeline with `-map 0:v? -c:v copy`, `-map 0:s? -c:s copy`, and `-map_metadata 0`. Bifurcating drops subtitles, secondary audio dubs, and container metadata. | MODERATE — Media Fidelity | `media_engine.py` (`remux_media`) |
| 16 | **Stream-Specific Bitrate Specifiers (`-b:a:{i}`)**: Encoding bitrates must be strictly stream-indexed (`-c:a:{i} {encoder}`, `-b:a:{i} 256k`). Applying global `-b:a 256k` forces re-encoding or crashes FFmpeg on untouched stream-copied audio tracks. | MODERATE — FFmpeg Muxer | `media_engine.py` (`remux_media`) |
| 17 | **FFmpeg Disposition Flag Whitelisting**: Stream dispositions must be validated against `_VALID_DISPOSITIONS` and joined with `+` (or assigned `"0"` if empty); passing raw `ffprobe` dictionary keys triggers immediate FFmpeg CLI syntax errors. | MODERATE — FFmpeg CLI | `media_engine.py` (`_VALID_DISPOSITIONS`, `remux_media`) |
| 18 | **Album Art Video Stream Exclusion**: Stream probing must exclude video streams with `disposition.attached_pic == 1`; checking only `codec_type == 'video'` misidentifies MP3/FLAC album cover art as video containers, corrupting remuxing logic. | MODERATE — Media Probing | `media_engine.py` (`probe_container`) |
| 19 | **Container-Specific `-movflags +faststart` Scope**: `-movflags +faststart` must strictly be appended only for extensions in `_FASTSTART_EXTS = {".mp4", ".mov", ".m4a", ".m4b"}`; passing it to MKV, WebM, or AVI causes FFmpeg error code 1 (`Option movflags not found`). | MODERATE — FFmpeg CLI | `media_engine.py` (`remux_media`) |
| 20 | **Zero-Duration Audio Protection Guard**: `pad_or_trim_audio` must trap `target_duration <= 0.0` and passthrough the file copy without invoking `-t`; passing `-t 0` truncates the audio to 0 bytes and permanently destroys the isolated stem. | MODERATE — Data Loss | `media_engine.py` (`pad_or_trim_audio`) |
| 21 | **RIFF 4.0 GiB WAV Extensible Ceiling (`-rf64 auto`)**: All intermediate WAV extractions and transformations must include `"-rf64", "auto"`. Standard RIFF headers allocate 32-bit sizes capped at 4.0 GiB; processing 7+ hour audio without RF64 corrupts the file. | MODERATE — Large File I/O | `media_engine.py` (`pad_or_trim_audio`) |
| 22 | **FFprobe Extended Timeout Bounds**: All `ffprobe` operations must enforce `timeout=180.0`, `-analyzeduration 10000000`, `-probesize 10000000`, and `CREATE_NO_WINDOW`. Short 10–15s timeouts trigger `TimeoutExpired` on multi-gigabyte or network media. | MODERATE — Media Probing | `media_engine.py` (`get_duration`, `probe_container`) |
| 23 | **Input-to-Output Container Extension Matching**: Output files must inherit the source container extension with dynamic encoder selection (`_get_audio_encoder_for_ext`). Forcing `.mp4` on MKV containers with incompatible codecs (e.g. VP9, ASS) crashes remuxing. | MODERATE — Media Fidelity | `media_engine.py` (`remux_media`), `main.py` (`add_media`) |
| 24 | **Empty Audio Stream Pre-Flight Check**: Container probing must verify `len(audio_streams) > 0` before queueing; enqueuing video-only containers wastes cloud GPU time and triggers unhandled worker exceptions. | MODERATE — Workflow Safety | `main.py` (`MainWindow.add_media`) |
| 25 | **Interactive Multi-Audio Stream Selection**: Containers with $> 1$ audio stream must prompt `AudioTrackSelectDialog` and record `selected_audio_stream` in the job snapshot; auto-selecting track 0 silently purges alternate dubs and commentary tracks. | MODERATE — UX / Data Fidelity | `main.py` (`add_media`), `media_engine.py` (`extract_audio`) |
| 26 | **Non-Destructive Tab Filtering**: Switching queue filter tabs (`[All | In Progress | Completed]`) MUST use `QListWidgetItem.setHidden()` in-place. Never call `list_widget.clear()`, which destroys active `JobWidget` instances and resets ETA and elapsed timers. | MODERATE — UI State | `ui/job_queue_section.py` (`_apply_filter`) |
| 27 | **Extended Cloud Polling Resilience**: The Kaggle status polling loop must allow at least 60 retries with 60-second backoff; small retry limits cause jobs to fail prematurely during transient home network or Kaggle gateway outages. | MODERATE — Cloud Resiliency | `processor_thread.py` (`JobProcessor.run`) |
| 28 | **Strict English Background Isolation**: Queue states (`PENDING`, `COMPLETED`, `ABORTED`) and model identifiers must strictly remain in English in storage and backend threads. Translating internal strings breaks state recovery and queue filtering. | MODERATE — State Integrity | `queue_manager.py`, `i18n.py` (translation at UI boundary only) |
| 29 | **AI Model Substring Matching Contract**: Model names (`RoFormer`, `MDX23C`, `Kim Vocal 2`) must preserve their exact substrings in settings and UI; backend lookups map these substrings to exact Kaggle dataset filenames. | MODERATE — Model Loading | `local_processor.py`, `processor_thread.py`, `ui/dialogs.py` |

---

## 4. ADVISORY Binding Rules (P2)

*Violation causes layout mirroring defects, font rendering degradation, untranslated strings, or log clutter.*

| # | Rule / Invariant & The Landmine | Severity | Enforced at |
|---|---|---|---|
| 30 | **100% Translation Key Parity**: The `TRANSLATIONS` dictionary in `i18n.py` must maintain strict 1:1 key parity between Arabic (`ar`) and English (`en`); missing keys produce blank labels or interpolation errors during dynamic language switching. | ADVISORY — Localization | `i18n.py`, verified by `tests/test_ui_overhaul.py::test_09_i18n_translation_parity` |
| 31 | **Arabic Grammatical Number Agreement**: Arabic count strings must format via 5-tier pluralization helpers (`format_jobs_count`, `format_delete_confirm_msg`: 0, 1 singular, 2 dual, 3–10 plural, 11+ accusative); generic English-style suffixing produces broken grammar. | ADVISORY — UX Polish | `i18n.py` (`format_jobs_count`, `format_delete_confirm_msg`) |
| 32 | **Direction-Aware Combobox & Rail Indicator Geometry**: Rail navigation buttons must draw the indicator pill at `x = 0` in LTR and `x = width - 3` in RTL. Combobox styling must route through `get_combobox_qss(is_rtl)` to prevent dropdown arrows colliding with Arabic text. | ADVISORY — UI Mirroring | `ui/components.py` (`SidebarNavButton.paintEvent`), `ui/theme.py` (`get_combobox_qss`) |
| 33 | **No Comma-Separated Font Fallbacks in QSS**: Qt QSS does not parse comma-separated font strings; passing `'Plus Jakarta Sans', 'Segoe UI'` triggers an unhinted GDI raster fallback resulting in pixelated, sand-like glyphs. Always resolve a single clean font via `QFontDatabase`. | ADVISORY — Typography | `ui/theme.py` (`Theme.resolve_font_family`, `resolve_mono_font`) |
| 34 | **Windows Per-Monitor DPI Awareness v2**: `main.py` must invoke `SetProcessDpiAwareness(2)` before `QApplication` instantiation; missing this causes Windows DWM bitmap-scaling blur on 125%/150%/200% scaling displays. | ADVISORY — Display Quality | `main.py` (lines before `QApplication`) |
| 35 | **Vector Icons over Unicode Emojis**: Action buttons (e.g. "Show in Folder") must use vector `QIcon` from SVG rather than Unicode emoji characters (`📁`), which Windows font engines render as dull monochrome gray outlines. | ADVISORY — UI Polish | `ui/theme.py` (`get_yellow_folder_icon`), `ui/job_widget.py` |
| 36 | **Job Card Zone 3 Vertical Clearance**: `JobWidget.sizeHint()` must return $\ge 118\text{px}$ and frame minimum height $\ge 108\text{px}$; smaller bounds vertically clip rotating spinners, progress bars, and status text by 12–14px at the card bottom. | ADVISORY — Layout Geometry | `ui/job_widget.py` (`JobWidget.sizeHint`, `__init__`) |
| 37 | **Strict 600-Line Upper Bound per UI Module**: No Python file in `ui/` may exceed 600 lines. Reusable controls belong in `components.py`, queue views in `job_queue_section.py`, dialogs in `dialogs.py`, and tokens in `theme.py`. | ADVISORY — Architecture | `ui/`, verified by `tests/test_ui_overhaul.py::test_01_line_count_ceiling` |
| 38 | **Bounded Log Rotation & Age-Based Purge**: File logging must strictly use `RotatingFileHandler(maxBytes=10*1024*1024, backupCount=3)` (40 MB hard cap), and startup must purge logs older than 48 hours (172,800 seconds). | ADVISORY — Disk Hygiene | `logger_setup.py` (`setup_logger`) |
| 39 | **Auto-Update Engine Decoupling**: `GitHubUpdateChecker` must remain autonomous and isolated; invalid Kaggle tokens, missing local models, or corrupted audio drivers must never block the delivery of software update notifications. | ADVISORY — Maintainability | `ui/main_window.py` (`start_auto_update_check`), `update_checker.py` |
