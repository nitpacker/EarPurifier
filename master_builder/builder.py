
import os
import subprocess
import json
import shutil

# Inject credentials so the kernel can use Kaggle API
os.environ["KAGGLE_USERNAME"] = "verymuch"
_key = "KGAT_35f2a305979b8b05d4f3ac3a2eb0aabe"
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
    print(f"Downloading {m}...")
    s.load_model(model_filename=m)

print("3. Generating dataset metadata...")
dataset_metadata = {
  "title": "earpurifier-cloud-assets-v2",
  "id": "verymuch/earpurifier-cloud-assets-v2",
  "licenses": [{"name": "CC0-1.0"}]
}
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
