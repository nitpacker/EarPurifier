import os
import glob
import subprocess
import shutil

INPUT_DIR = "/kaggle/input"
OUTPUT_DIR = "/kaggle/working"

ASSETS_DIR = "/kaggle/input/earpurifier-cloud-assets-v2"
for root, dirs, files in os.walk(INPUT_DIR):
    if "wheels" in dirs and "models" in dirs:
        ASSETS_DIR = root
        break

WHEELS_DIR = os.path.join(ASSETS_DIR, "wheels")
MODEL_DIR = os.path.join(ASSETS_DIR, "models")

def setup_environment():
    if os.path.exists(WHEELS_DIR) and len(os.listdir(WHEELS_DIR)) > 0:
        print("Found pre-cached wheels. Installing offline...")
        try:
            subprocess.run(["pip", "install", "--no-index", "--find-links=" + WHEELS_DIR, "audio-separator[gpu]", "onnxruntime-gpu==1.19.2"], check=True)
        except subprocess.CalledProcessError:
            print("Offline install failed! Falling back to online install...")
            subprocess.run(["pip", "install", "audio-separator[gpu]", "onnxruntime-gpu==1.19.2"], check=True)
    else:
        print("Pre-cached wheels not found. Installing online...")
        subprocess.run(["pip", "install", "audio-separator[gpu]", "onnxruntime-gpu==1.19.2"], check=True)

def run_separation():
    # We must import inside the function after installing
    from audio_separator.separator import Separator

    # Find audio file
    audio_files = []
    if os.path.exists(INPUT_DIR):
        for root, dirs, files in os.walk(INPUT_DIR):
            for file in files:
                if file.endswith((".flac", ".wav", ".mp3", ".mp4", ".mkv")):
                    audio_files.append(os.path.join(root, file))
    
    if not audio_files:
        print(f"No audio files found in {INPUT_DIR}")
        print("Directory contents:")
        for root, dirs, files in os.walk(INPUT_DIR):
            print(f"ROOT: {root}")
            print(f"DIRS: {dirs}")
            print(f"FILES: {files}")
        return
        
    audio_file = audio_files[0]
    print(f"Processing {audio_file}...")

    # Determine model directory
    model_dir = MODEL_DIR if os.path.exists(MODEL_DIR) else "/kaggle/working/models"
    os.makedirs(model_dir, exist_ok=True)

    separator = Separator(
        output_dir=OUTPUT_DIR,
        output_format="WAV",
        model_file_dir=model_dir
    )

    # Load model (will download if not in model_dir)
    separator.load_model(model_filename="vocals_mel_band_roformer.ckpt")

    # Separate
    output_files = separator.separate(audio_file)
    print(f"Separation complete: {output_files}")
    
    # We rename the vocals output to a predictable name: clean_vocals.wav
    # Output files list usually contains [vocals_file, instrumental_file]
    for f in output_files:
        if "(vocals)" in f.lower():
            shutil.move(os.path.join(OUTPUT_DIR, f), os.path.join(OUTPUT_DIR, "clean_vocals.wav"))
            break

if __name__ == "__main__":
    setup_environment()
    run_separation()
