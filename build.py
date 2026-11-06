import os
import sys
import subprocess
import venv
import shutil

def main():
    print("=== EarPurifier Smart Cross-Platform Build Script ===")
    root_dir = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(root_dir, "venv")
    req_file = os.path.join(root_dir, "requirements.txt")

    print(f"-> Target platform: {sys.platform}")
    print(f"-> Setting up isolated virtual environment at '{venv_dir}' to ensure a small executable size.")

    if not os.path.exists(venv_dir):
        print("-> Creating fresh virtual environment (system site packages disabled)...")
        venv.create(venv_dir, with_pip=True, system_site_packages=False)
    else:
        print("-> Using existing virtual environment...")

    if sys.platform == 'win32':
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
    if sys.platform == 'win32':
        try:
            subprocess.run(["taskkill", "/F", "/IM", "EarPurifier.exe"], capture_output=True)
        except Exception:
            pass
    else:
        try:
            # Use exact binary name match (-x) to avoid terminating python build.py itself
            subprocess.run(["pkill", "-x", "EarPurifier"], capture_output=True)
        except Exception:
            pass

    print("\nRunning PyInstaller...")
    main_script = os.path.join(root_dir, "main.py")
    assets_dir = os.path.join(root_dir, "assets")
    worker_dir = os.path.join(root_dir, "worker")

    build_cmd = [
        target_python, "-m", "PyInstaller",
        "--name", "EarPurifier",
        "--windowed",
        "--clean",
        "--noconfirm",
        "--add-data", f"{assets_dir}{os.pathsep}assets",
        "--add-data", f"{assets_dir}{os.pathsep}src/assets",
        "--add-data", f"{worker_dir}{os.pathsep}worker",
        "--add-data", f"{worker_dir}{os.pathsep}src/worker",
        "--hidden-import", "loguru",
        "--hidden-import", "PySide6",
        "--hidden-import", "ui",
        "--hidden-import", "i18n",
        "--hidden-import", "update_checker",
        "--hidden-import", "process_tracker",
        "--hidden-import", "system_utils",
        "--hidden-import", "packaging",
        "--hidden-import", "cryptography",
        "--hidden-import", "cryptography.hazmat.primitives.ciphers.aead",
        "--collect-all", "cryptography",
        "--hidden-import", "text_unidecode",
    ]

    if sys.platform == "win32":
        ico_file = os.path.join(root_dir, "assets", "logo.ico")
        build_cmd.extend([
            "--onefile",
            "--icon", ico_file,
        ])
    elif sys.platform == "darwin":
        icns_file = os.path.join(root_dir, "assets", "logo.icns")
        build_cmd.extend([
            "--icon", icns_file,
            "--osx-bundle-identifier", "com.sproutaudio.earpurifier",
        ])
    else:  # Linux
        png_file = os.path.join(root_dir, "assets", "logo.png")
        build_cmd.extend([
            "--onefile",
            "--icon", png_file,
        ])

    build_cmd.append(main_script)

    # Run in root_dir so /dist appears directly in cleanerEARS/dist
    subprocess.check_call(build_cmd, cwd=root_dir)

    # Post-build adjustments per platform
    dist_dir = os.path.join(root_dir, "dist")
    if sys.platform.startswith("linux"):
        linux_bin = os.path.join(dist_dir, "EarPurifier")
        if os.path.exists(linux_bin):
            try:
                os.chmod(linux_bin, 0o755)
            except Exception:
                pass

        desktop_file = os.path.join(dist_dir, "EarPurifier.desktop")
        desktop_content = """[Desktop Entry]
Type=Application
Name=EarPurifier
Comment=AI Audio Vocal & Instrumental Isolation Studio
Exec=EarPurifier
Icon=earpurifier
Terminal=false
Categories=AudioVideo;Audio;AudioVideoEditing;
Keywords=audio;vocals;music;separator;karaoke;
StartupWMClass=EarPurifier
"""
        with open(desktop_file, "w", encoding="utf-8") as f:
            f.write(desktop_content)
        try:
            os.chmod(desktop_file, 0o755)
        except Exception:
            pass

        shutil.copyfile(os.path.join(assets_dir, "logo.png"), os.path.join(dist_dir, "earpurifier.png"))
        print(f"-> Generated Linux desktop launcher at {desktop_file}")

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
    if sys.platform == "win32":
        print(f"Standalone Windows executable: {os.path.join(dist_dir, 'EarPurifier.exe')}")
    elif sys.platform == "darwin":
        print(f"Native macOS Application Bundle: {os.path.join(dist_dir, 'EarPurifier.app')}")
    else:
        print(f"Standalone Linux executable: {os.path.join(dist_dir, 'EarPurifier')}")

if __name__ == "__main__":
    main()
