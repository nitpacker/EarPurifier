import os
import glob
import subprocess
import shutil

INPUT_DIR = "/kaggle/input"
OUTPUT_DIR = "/kaggle/working"

# This constant is injected by the app before dispatch. It is the unique,
# job-stamped filename (e.g. audio_be4f89dc.flac) uploaded for THIS specific job.
# If the dataset somehow contains a different file, separation is aborted.
EXPECTED_AUDIO_NAME = "audio.flac"

ASSETS_DIR = "/kaggle/input/earpurifier-cloud-assets-v2"
for root, dirs, files in os.walk(INPUT_DIR):
    if "wheels" in dirs and "models" in dirs:
        ASSETS_DIR = root
        break

WHEELS_DIR = os.path.join(ASSETS_DIR, "wheels")
MODEL_DIR = os.path.join(ASSETS_DIR, "models")

def setup_environment():
    if os.path.exists(WHEELS_DIR) and len(os.listdir(WHEELS_DIR)) > 0:
        print("[CACHE] Found pre-cached wheels. Attempting offline install...")
        try:
            subprocess.run(["pip", "install", "--no-index", "--find-links=" + WHEELS_DIR,
                          "audio-separator[gpu]", "onnxruntime-gpu<1.27.0"], check=True)
            print("[CACHE] Offline install SUCCESS.")
            return
        except subprocess.CalledProcessError:
            print("[CACHE] WARNING: Cached wheels are STALE or incompatible. Falling back to PyPI...")
    else:
        print("[CACHE] No pre-cached wheels found.")

    print("[NETWORK] Installing from PyPI (this may take 30-45s)...")
    subprocess.run(["pip", "install", "audio-separator[gpu]", "onnxruntime-gpu<1.27.0"], check=True)
    print("[NETWORK] Online install SUCCESS.")

def run_separation():
    # We must import inside the function after installing
    from audio_separator.separator import Separator

    # Find the expected audio file by its job-stamped name
    audio_file = None
    for root, dirs, files in os.walk(INPUT_DIR):
        for file in files:
            if file == EXPECTED_AUDIO_NAME:
                audio_file = os.path.join(root, file)
                break
        if audio_file:
            break

    # Hard fail if the expected file is not found - this catches stale dataset scenarios
    if not audio_file:
        print(f"FATAL: Expected audio file '{EXPECTED_AUDIO_NAME}' not found in dataset.")
        print("This may mean the Kaggle dataset still has a file from a previous job.")
        print("Listing all files in input directory:")
        for root, dirs, files in os.walk(INPUT_DIR):
            print(f"ROOT: {root}")
            print(f"FILES: {files}")
        raise FileNotFoundError(f"Expected '{EXPECTED_AUDIO_NAME}' not found. Aborting to prevent processing wrong audio.")

    print(f"Processing {audio_file}...")

    # Determine model directory
    model_dir = MODEL_DIR if os.path.exists(MODEL_DIR) else "/kaggle/working/models"
    os.makedirs(model_dir, exist_ok=True)

    separator = Separator(
        output_dir=OUTPUT_DIR,
        output_format="FLAC",
        model_file_dir=model_dir
    )

    # Load model (will download if not in model_dir)
    separator.load_model(model_filename="Kim_Vocal_2.onnx")

    # Guard: fail fast if GPU is unavailable rather than silently crawling on CPU
    import onnxruntime as ort
    providers = ort.get_available_providers()
    print(f"[GPU CHECK] Available providers: {providers}")
    if "CUDAExecutionProvider" not in providers:
        raise RuntimeError(
            f"GPU FAILURE: CUDAExecutionProvider not available. "
            f"Got: {providers}. Aborting to prevent 10x slower CPU fallback."
        )

    # Active session check: ensure the ONNX session actually initialized with CUDA
    # (Catches missing dynamic libraries like libcublasLt where get_available_providers() succeeds but session falls back to CPU)
    model_session = getattr(separator.model_instance, "model_run", None)
    if model_session is not None and hasattr(model_session, "get_providers"):
        active_providers = model_session.get_providers()
    else:
        active_providers = getattr(separator, "providers", providers)
    print(f"[GPU CHECK] Active session providers: {active_providers}")
    if "CUDAExecutionProvider" not in active_providers:
        raise RuntimeError(
            f"GPU FAILURE: Model session initialized with {active_providers} instead of CUDAExecutionProvider. "
            f"Aborting to prevent 10x slower CPU fallback."
        )

    # Separate
    output_files = separator.separate(audio_file)
    print(f"Separation complete: {output_files}")

    # We rename the vocals output to a predictable name and delete everything else to save Kaggle backend packaging time
    for f in output_files:
        filepath = os.path.join(OUTPUT_DIR, f)
        if "(vocals)" in f.lower():
            shutil.move(filepath, os.path.join(OUTPUT_DIR, "clean_vocals.flac"))
        else:
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Failed to delete {f}: {e}")

if __name__ == "__main__":
    setup_environment()
    run_separation()
