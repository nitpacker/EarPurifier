import os
import sys
import json
import time

try:
    from config_manager import ConfigManager
except ImportError:
    try:
        from src.config_manager import ConfigManager
    except ImportError:
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
        from config_manager import ConfigManager

cfg = ConfigManager()
username = cfg.get("kaggle_username")
api_key = cfg.get("kaggle_api_key")

if not username or not api_key:
    print("Missing Kaggle credentials")
    exit(1)

os.environ["KAGGLE_USERNAME"] = username
os.environ.pop("KAGGLE_KEY", None)
os.environ.pop("KAGGLE_API_TOKEN", None)
if api_key.startswith("KGAT_"):
    os.environ["KAGGLE_API_TOKEN"] = api_key
else:
    os.environ["KAGGLE_KEY"] = api_key

import kaggle
from kaggle.api.kaggle_api_extended import KaggleApi
api = KaggleApi()
api.authenticate()

builder_dir = "master_builder"
os.makedirs(builder_dir, exist_ok=True)

# 1. Write the metadata for the kernel itself
kernel_metadata = {
  "id": f"{username}/earpurifier-cache-builder",
  "title": "earpurifier-cache-builder",
  "code_file": "builder.py",
  "language": "python",
  "kernel_type": "script",
  "is_private": True,
  "enable_gpu": True,
  "enable_internet": True,
  "dataset_sources": [],
  "competition_sources": [],
  "kernel_sources": []
}
with open(os.path.join(builder_dir, "kernel-metadata.json"), "w", encoding="utf-8") as f:
    json.dump(kernel_metadata, f, indent=2)

# 2. Write the builder script that runs ON Kaggle
builder_script = f"""
import os
import subprocess
import json
import shutil

# Inject credentials so the kernel can use Kaggle API
os.environ["KAGGLE_USERNAME"] = "{username}"
_key = "{api_key}"
if _key.startswith("KGAT_"):
    os.environ["KAGGLE_API_TOKEN"] = _key
else:
    os.environ["KAGGLE_KEY"] = _key

CACHE_DIR = "/kaggle/working/cache"
WHEELS_DIR = os.path.join(CACHE_DIR, "wheels")
MODELS_DIR = os.path.join(CACHE_DIR, "models")
os.makedirs(WHEELS_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

print("1. Building wheels...")
subprocess.run(["pip", "wheel", "audio-separator[gpu]", "onnxruntime-gpu<1.27.0", "-w", WHEELS_DIR], check=True)
subprocess.run(["pip", "install", "--no-index", "--find-links=" + WHEELS_DIR, "audio-separator[gpu]", "onnxruntime-gpu<1.27.0"], check=True)

print("2. Downloading models...")
from audio_separator.separator import Separator
s = Separator(model_file_dir=MODELS_DIR)

models_to_download = [
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    "MDX23C-8KFFT-InstVoc_HQ.ckpt",
    "Kim_Vocal_2.onnx"
]

for m in models_to_download:
    print(f"Downloading {{m}}...")
    s.load_model(model_filename=m)

print("3. Generating dataset metadata...")
dataset_metadata = {{
  "title": "earpurifier-cloud-assets-v2",
  "id": "{username}/earpurifier-cloud-assets-v2",
  "licenses": [{{"name": "CC0-1.0"}}]
}}
with open(os.path.join(CACHE_DIR, "dataset-metadata.json"), "w", encoding="utf-8") as f:
    json.dump(dataset_metadata, f, indent=2)

print("4. Uploading dataset to Kaggle...")
res = subprocess.run(["kaggle", "datasets", "version", "-p", CACHE_DIR, "-m", "Updated cache for Python 3.13 and CUDA 12 (onnxruntime-gpu<1.27.0)", "--dir-mode", "zip"], capture_output=True, text=True)
print(res.stdout)
print(res.stderr)
if res.returncode != 0 or "error" in (res.stderr or "").lower() or "not found" in (res.stdout or "").lower():
    print("Version update failed or dataset does not exist yet. Trying create...")
    res2 = subprocess.run(["kaggle", "datasets", "create", "-p", CACHE_DIR, "--dir-mode", "zip"], capture_output=True, text=True)
    print(res2.stdout)
    print(res2.stderr)

print("Dataset creation complete!")
"""

with open(os.path.join(builder_dir, "builder.py"), "w", encoding="utf-8") as f:
    f.write(builder_script)

print("Pushing builder kernel to Kaggle...")
api.kernels_push(builder_dir)
print(f"Kernel pushed to {username}/earpurifier-cache-builder")
print("Polling status...")

kernel_id = f"{username}/earpurifier-cache-builder"
while True:
    try:
        resp = api.kernels_status(kernel_id)
        status = str(getattr(resp, "status", str(resp))).lower()
        print(f"Status: {status}")
        if "complete" in status or "error" in status or "cancel" in status:
            print("Done!")
            break
    except Exception as e:
        print(f"Error polling: {e}")
    time.sleep(10)
