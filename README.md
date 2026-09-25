<div align="center">

# 🌱 EarPurifier

**State-of-the-art AI audio isolation — vocal extraction & noise removal for videos.**

Tear the barrier of modern AI audio processing apart with a **Dual Engine** architecture:
run massive AI models natively on your local Nvidia GPU, or securely offload the heavy lifting
to Kaggle's free T4 Cloud GPUs with a single click.

---

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://wiki.qt.io/Qt_for_Python)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![Kaggle](https://img.shields.io/badge/Kaggle-20BEFF?style=for-the-badge&logo=kaggle&logoColor=white)](https://www.kaggle.com/)
[![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![NVIDIA](https://img.shields.io/badge/NVIDIA-RTX-76B900?style=for-the-badge&logo=nvidia&logoColor=white)](https://www.nvidia.com/)

</div>

---

## ✨ Features

| Feature | Description |
| :--- | :--- |
| ⚙️ **Dual-Engine AI** | Run locally on RTX graphics cards, or offload to the cloud. |
| ⚡ **Lightning Fast Cloud Pipeline** | Uses a pre-compiled V2 Master Cache dataset on Kaggle to bypass network bottlenecks, dropping cloud environment setup time from 45 seconds to just 2 seconds. Processes songs in under 60 seconds. |
| 🎛️ **Top-Tier Models** | Integrates the `audio-separator` library with support for RoFormer, MDX23C, and MDXNET algorithms to achieve pristine studio-quality vocal extraction. |
| 🎬 **Seamless Video Remuxing** | Zero-reencode technology. It extracts the audio, purifies it, and stitches it perfectly back into your `.mp4` or `.mkv` video without degrading video quality or dropping frames. |
| 🛡️ **Bulletproof Job Queue** | Queue dozens of videos across different models and engines simultaneously. Background workers will process them reliably, surviving network disconnects with a built-in 5-attempt retry shield. |

---

## 📋 Requirements

### ☁️ For Cloud Mode
- A free [**Kaggle**](https://www.kaggle.com/) account.
- Your **Kaggle Username** and **API Key**.

### 💻 For Local Mode
- **Windows 10/11**
- An **Nvidia GPU** (RTX 2060 or higher recommended) with up-to-date drivers.

---

## 🚀 Development & Building

> EarPurifier is fully self-contained and comes with a smart build script that handles environment isolation and compilation into a single `.exe`.

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/EarPurifier.git
cd EarPurifier

# 2. Build the application (Requires Python 3.12+)
python build.py
```

The compiled standalone executable will be generated in the `dist/` directory.

---

## 📚 Documentation

For a complete breakdown of the codebase, lifecycle architecture, caching strategies, and instructions on how to extend the application, read the **[Technical Architecture Guide](docs/TECHNICAL.md)**.

---

## 🛠️ Credits

- Built with [**PySide6**](https://wiki.qt.io/Qt_for_Python)
- Engine by [**audio-separator**](https://github.com/nomadkaraoke/python-audio-separator) by nomadkaraoke
- Audio/Video manipulation via [**FFmpeg**](https://ffmpeg.org/)

---

*Made with ❤️ by [nitpacker](https://github.com/nitpacker) ·

*For more, visit [Mariam Initiative](https://telegram.me/MariamInitiative) ·