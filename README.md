<div align="center">

# 🌱 EarPurifier

**State-of-the-Art AI Audio Isolation & Vocal Purification Studio**

[![Release](https://img.shields.io/badge/Release-v0.0.1-10b981?style=for-the-badge&logo=github&logoColor=white)](https://github.com/nitpacker/EarPurifier/releases/tag/v0.0.1)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-Qt%206-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://wiki.qt.io/Qt_for_Python)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Hardware%20Accelerated-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![Kaggle T4](https://img.shields.io/badge/Kaggle-T4%20Cloud%20GPU-20BEFF?style=for-the-badge&logo=kaggle&logoColor=white)](https://www.kaggle.com/)
[![Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11%20x64-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Tests](https://img.shields.io/badge/Tests-40%20Passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](tests/)

<p align="center">
  <b>Tear down the computational barrier of deep learning audio isolation.</b><br>
  Execute cutting-edge neural networks locally on your NVIDIA GPU, or offload the heavy lifting<br>
  to Kaggle's free T4 Cloud GPUs with fast spin-up via a master cache.
</p>

</div>

---

## 🌟 Key Capabilities

- ⚡ **Asymmetric Dual-Engine Processing**:
  - **Cloud Engine (Kaggle T4)**: Runs high-end models for free without stressing local hardware. Mounts the pre-compiled `earpurifier-cloud-assets-v2` master cache.
  - **Local Engine (CUDA / CPU)**: Autonomous offline processing running in an isolated Python 3.11 environment with real-time progress parsing.
- 🎛️ **State-of-the-Art Separation Models**:
  - **Band-Split RoFormer** (`model_bs_roformer_ep_317_sdr_12.9755.ckpt`): World-class SDR (12.97 dB) vocal/music isolation.
  - **MDX23C** (`MDX23C-8KFFT-InstVoc_HQ.ckpt`): Multi-band convolutional cross-transformer architecture.
  - **Kim Vocal 2** (`Kim_Vocal_2.onnx`): Ultra-fast, high-precision ONNX neural separation.
- 🚀 **Lossless Video Remuxing & Stream Preservation**:
  - Zero video re-encoding (`-c:v copy`): 100% video quality preserved, 0% CPU waste.
  - Retains all subtitle streams (`-c:s copy`), alternate audio dubs, and container metadata tags.
  - Hardware-accelerated audio remuxing (`aac_mf` on Windows Media Foundation / `aac_at` on macOS) rendering at **~1,500 fps**.
  - Automatic audio duration padding and alignment (`-af apad`) with zero-duration safeguards.
- 🎨 **Modern Studio PySide6 Interface**:
  - Bilingual localization: Full **العربية (Arabic - Default)** and **English** support with live dynamic switching without restart.
  - Native Qt RTL (Right-to-Left) layout mirroring and vector symmetry.
  - Dual theme engine: **Soft Sage (Light)** and **Deep Botanical Slate (Dark)** with Windows 10/11 DWM immersive dark title bar integration.
- 📦 **Zero-Install Single Executable**:
  - Completely self-contained ~53 MB portable `.exe` requiring zero system installation or administrative privileges.

---

## 🏗️ System Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │               User Media Input               │
                    │         (Video / Multi-track Audio)          │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        media_engine.py Pipeline Frontend                               │
│  • Container Graph Probe (analyzeduration=10M, probesize=10M, timeout=180s)            │
│  • Lossless Extraction to 48kHz Stereo FLAC (-map 0:a:{idx} -vn -c:a flac -ar 48k -ac 2)│
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │                                             │
                    ▼                                             ▼
┌──────────────────────────────────────┐      ┌───────────────────────────────────────────┐
│     Local Engine (GPU/CPU)           │      │          Cloud Engine (Kaggle)            │
│     local_processor.py               │      │    processor_thread.py & kaggle_bridge.py │
│  • Micromamba isolated Python 3.11   │      │  • Ephemeral Dataset Buffer               │
│  • PyTorch CU121 / CPU fallback      │      │    `earpurifier-audio-buffer-<uuid>`      │
│  • audio-separator CLI subprocess    │      │  • KGAT_ Bearer Auth / KAGGLE_CONFIG_DIR  │
│  • bufsize=1, stderr=STDOUT          │      │  • Dynamic worker injection (worker.py)   │
│  • ProcessTracker taskkill PID tree  │      │  • Kaggle T4 GPU: offline cache mount     │
│  • Real-time stdout progress regex   │      │  • 4-Thread GCS HTTP Range Downloader     │
└──────────────────┬───────────────────┘      └─────────────────────┬─────────────────────┘
                   │                                                │
                   └───────────────────────┬────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        media_engine.py Pipeline Backend                                │
│  • Duration Protection & Alignment (pad_or_trim_audio, -af apad / -rf64 auto)          │
│  • OS-Accelerated Remuxing (aac_mf on Win32, aac_at on Darwin, native aac fallback)    │
│  • Non-destructive Stream Mapping (-map 0:v? -c:v copy, -map 0:s? -c:s copy)           │
│  • Audio Disposition & Metadata Preservation (_VALID_DISPOSITIONS, -map_metadata 0)    │
│  • Web Streaming Optimization (-movflags +faststart, -avoid_negative_ts make_zero)     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📋 Prerequisites & System Requirements

### Platform Requirements
- **Operating System**: Windows 10 (Build 19041+) or Windows 11 x64.
- **Media Engine**: FFmpeg and FFprobe in system `PATH` (or auto-downloaded on first run into `%APPDATA%/EarPurifier/bin/`).

### Engine Requirements
- **For Cloud Mode (Recommended)**:
  - Free [Kaggle](https://www.kaggle.com/) account.
  - Kaggle Username & API Token (`KGAT_...` Personal Access Token or legacy key).
- **For Local Mode**:
  - NVIDIA GPU with CUDA support (RTX 2060 or higher recommended, minimum 6 GB VRAM).
  - Fallback CPU mode available (inference runs slower, try Kim Vocal 2).

---

## 🚀 Getting Started

### Option A: Portable Standalone Binary (Recommended)
1. Download the latest `EarPurifier.exe` from [GitHub Releases](https://github.com/nitpacker/EarPurifier/releases/latest).
2. Place `EarPurifier.exe` in any folder and run it. No installer or administrative rights required.

### Option B: Running from Source
```powershell
# 1. Clone the repository
git clone https://github.com/nitpacker/EarPurifier.git
cd EarPurifier

# 2. Create and activate a clean virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install core application dependencies
pip install -r requirements.txt

# 4. Launch EarPurifier Studio
python main.py
```

### Option C: Building the Executables
(See Packaging & Compilation Below).

---

## 🧪 Verification & Test Suite

EarPurifier includes a 40-test verification suite covering UI rendering, shutdown signals, SemVer update logic, and studio parity:

```powershell
# Run the complete test suite
python -m unittest discover -s tests -p "test_*.py"

# Or run individual verification suites:
python -m unittest tests/test_ui_overhaul.py      # UI hierarchy, theme tokens, i18n parity
python -m unittest tests/test_studio_parity.py    # Job card 3-zone parity, spinners, toolbars
python -m unittest tests/test_update_checker.py   # SemVer 2.0.0, bilingual notes, mock API
python -m unittest tests/test_shutdown.py         # Thread joins, process trees, exit interceptor
```

---

## 🔨 Packaging & Compilation

To compile a portable standalone `.exe`:

```powershell
python build.py
```

The script automatically:
1. Creates an isolated `./venv/` with `system_site_packages=False` to prevent bloating the binary.
2. Installs strictly dependencies from `requirements.txt`.
3. Compiles `dist/EarPurifier.exe` (~53 MB) via PyInstaller with embedded assets and icon.
4. Cleans intermediate spec and build artifacts.

---

## 📖 Complete Engineering & Operations Suite

For deep architectural and operational reference, consult the authoritative documentation suite:

| Document | Purpose |
| :--- | :--- |
| 📘 **[Technical Architecture](docs/TECHNICAL.md)** | System topology, thread affinity, component inventory, job state machine, media pipeline, and edge-case resiliency catalog. |
| 🛡️ **[Engineering Invariants & Binding Rules](docs/BINDING_RULES.md)** | Strict ruleset of non-negotiable DOs and DON'Ts classified by severity (Critical, Moderate, Advisory). |
| 🔧 **[Operations & Maintenance Manual](docs/OPERATIONS.md)** | Build playbooks, GitHub release procedures, Kaggle cache updates, DPAPI key operations, and emergency hazard playbooks. |

---

## 🛠️ Credits & Technologies

- **UI Framework**: [PySide6](https://wiki.qt.io/Qt_for_Python) (Qt 6 for Python)
- **AI Separation**: [audio-separator](https://github.com/nomadkaraoke/python-audio-separator) by nomadkaraoke
- **Media Engine**: [FFmpeg](https://ffmpeg.org/) & Microsoft Media Foundation (`aac_mf`)
- **Cloud Infrastructure**: [Kaggle](https://www.kaggle.com/) T4 GPU Instances

---

<div align="center">

*For more, visit [Mariam Initiative](https://telegram.me/MariamInitiative)*

</div>
