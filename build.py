import os
import sys
import subprocess
import venv
import shutil

def main():
    print("=== EarPurifier Smart Build Script ===")
    root_dir = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(root_dir, "venv")
    req_file = os.path.join(root_dir, "requirements.txt")

    print(f"-> Setting up isolated virtual environment at '{venv_dir}' to ensure a small executable size.")
    
    if not os.path.exists(venv_dir):
        print("-> Creating fresh virtual environment (system site packages disabled)...")
        venv.create(venv_dir, with_pip=True, system_site_packages=False)
    else:
        print("-> Using existing virtual environment...")

    if os.name == 'nt':
        target_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        target_python = os.path.join(venv_dir, "bin", "python")

    print("-> Installing exact dependencies from requirements.txt...")
    try:
        subprocess.check_call([target_python, "-m", "pip", "install", "-r", req_file])
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to install requirements into venv: {e}")
        sys.exit(1)

    # Ensure no running instances of EarPurifier lock the output executable
    if os.name == 'nt':
        try:
            subprocess.run(["taskkill", "/F", "/IM", "EarPurifier.exe"], capture_output=True)
        except Exception:
            pass

    print("\nRunning PyInstaller...")
    main_script = os.path.join(root_dir, "main.py")
    ico_file = os.path.join(root_dir, "assets", "logo.ico")
    assets_dir = os.path.join(root_dir, "assets")
    worker_dir = os.path.join(root_dir, "worker")

    build_cmd = [
        target_python, "-m", "PyInstaller",
        "--name", "EarPurifier",
        "--windowed",
        "--onefile",
        "--clean",
        "--icon", ico_file,
        "--add-data", f"{assets_dir}{os.pathsep}assets",
        "--add-data", f"{assets_dir}{os.pathsep}src/assets",
        "--add-data", f"{worker_dir}{os.pathsep}worker",
        "--add-data", f"{worker_dir}{os.pathsep}src/worker",
        "--hidden-import", "loguru",
        "--hidden-import", "PySide6",
        "--hidden-import", "ui",
        "--hidden-import", "text_unidecode",
        main_script
    ]
    
    # Run in root_dir so /dist appears directly in cleanerEARS/dist
    subprocess.check_call(build_cmd, cwd=root_dir)
    
    # Clean up temporary build artifacts (build folder and .spec file)
    print("Cleaning up intermediate build artifacts...")
    build_dir = os.path.join(root_dir, "build")
    spec_file = os.path.join(root_dir, "EarPurifier.spec")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)
    if os.path.exists(spec_file):
        try:
            os.remove(spec_file)
        except OSError:
            pass

    print("\n=== Build Complete! ===")
    print(f"Your standalone executable is located in: {os.path.join(root_dir, 'dist')}")

if __name__ == "__main__":
    main()
