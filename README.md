# EarPurifier

EarPurifier is a desktop application built with PySide6 that provides state-of-the-art AI audio isolation (vocal extraction and noise removal) for videos. 

It solves the hardware barrier of modern AI audio processing by offering a **Dual Engine** architecture: you can run the massive AI models natively on your local Nvidia GPU, or securely offload the heavy lifting to Kaggle's free T4 Cloud GPUs with a single click.

## Features

- **Dual-Engine AI**: Run locally on RTX graphics cards, or offload to the cloud.
- **Lightning Fast Cloud Pipeline**: Uses a pre-compiled V2 Master Cache dataset on Kaggle to bypass network bottlenecks, dropping cloud environment setup time from 45 seconds to just 2 seconds. Processes songs in under 60 seconds.
- **Top-Tier Models**: Integrates the `audio-separator` library with support for RoFormer, MDX23C, and MDXNET algorithms to achieve pristine studio-quality vocal extraction.
- **Seamless Video Remuxing**: Zero-reencode technology. It extracts the audio, purifies it, and stitches it perfectly back into your `.mp4` or `.mkv` video without degrading video quality or dropping frames.
- **Bulletproof Job Queue**: Queue dozens of videos across different models and engines simultaneously. Background workers will process them reliably, surviving network disconnects with a built-in 5-attempt retry shield.

## Requirements

### For Cloud Mode
- A free [Kaggle](https://www.kaggle.com/) account.
- Your Kaggle Username and API Key.

### For Local Mode
- Windows 10/11
- An Nvidia GPU (RTX 2060 or higher recommended) with up-to-date drivers.

## Development & Building

EarPurifier is fully self-contained and comes with a smart build script that handles environment isolation and compilation into a single `.exe`.

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/EarPurifier.git
cd EarPurifier

# 2. Build the application (Requires Python 3.12+)
python build.py
```
The compiled standalone executable will be generated in the `dist/` directory.

## Documentation
For a complete breakdown of the codebase, lifecycle architecture, caching strategies, and instructions on how to extend the application, read the [Technical Architecture Guide](docs/TECHNICAL.md).

## Credits
- Built with [PySide6](https://wiki.qt.io/Qt_for_Python)
- Powered by [audio-separator](https://github.com/nomadkaraoke/python-audio-separator) by nomadkaraoke
- Audio/Video manipulation via [FFmpeg](https://ffmpeg.org/)
