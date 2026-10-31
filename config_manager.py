import os
import sys
import json
import time
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def _atomic_write_json(file_path: str, data: dict, indent: int = 4):
    dir_name = os.path.dirname(file_path)
    os.makedirs(dir_name, exist_ok=True)
    f = tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8")
    temp_path = f.name
    try:
        json.dump(data, f, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    finally:
        f.close()

    for attempt in range(3):
        try:
            os.replace(temp_path, file_path)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.05)
        finally:
            if os.path.exists(temp_path) and os.path.exists(file_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

def _protect_secret(plain_text: str) -> str:
    if not plain_text or sys.platform != "win32":
        return plain_text
    try:
        import base64
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        raw_bytes = plain_text.encode('utf-8')
        in_blob = DATA_BLOB(len(raw_bytes), ctypes.cast(ctypes.create_string_buffer(raw_bytes), ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(in_blob), "EarPurifierKey", None, None, None, 0, ctypes.byref(out_blob)):
            cipher_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return "enc:" + base64.b64encode(cipher_bytes).decode('ascii')
    except Exception as e:
        logger.warning(f"DPAPI encryption failed: {e}")
    return plain_text

def _unprotect_secret(cipher_text: str) -> str:
    if not cipher_text or not isinstance(cipher_text, str) or not cipher_text.startswith("enc:") or sys.platform != "win32":
        return cipher_text
    try:
        import base64
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        raw_bytes = base64.b64decode(cipher_text[4:])
        in_blob = DATA_BLOB(len(raw_bytes), ctypes.cast(ctypes.create_string_buffer(raw_bytes), ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            plain_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return plain_bytes.decode('utf-8')
    except Exception as e:
        logger.warning(f"DPAPI decryption failed: {e}")
        return ""
    return cipher_text

class ConfigManager:
    def __init__(self):
        self.appdata_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'EarPurifier')
        os.makedirs(self.appdata_dir, exist_ok=True)
        self.config_file = os.path.join(self.appdata_dir, 'config.json')
        self.default_config = {
            "kaggle_username": "",
            "kaggle_api_key": "",
            "output_folder": "",
            "enable_logging": True,
            "local_model": "SOTA (RoFormer) - Requires High-End GPU",
            "processing_mode": "Cloud (Kaggle)", # or "Local (GPU)"
            "delete_output_files": False
        }
        self.config = self.load_config()

    def load_config(self) -> dict:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Merge with defaults
                    for k, v in self.default_config.items():
                        if k not in data:
                            data[k] = v
                    if data.get("kaggle_api_key"):
                        data["kaggle_api_key"] = _unprotect_secret(data["kaggle_api_key"])
                    return data
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                return self.default_config.copy()
        return self.default_config.copy()

    def save_config(self, new_config: dict):
        self.config.update(new_config)
        to_save = self.config.copy()
        if to_save.get("kaggle_api_key"):
            to_save["kaggle_api_key"] = _protect_secret(to_save["kaggle_api_key"])
        try:
            _atomic_write_json(self.config_file, to_save, indent=4)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value
        self.save_config({}) # Triggers an atomic save

    def get_output_folder(self, executable_dir: str) -> str:
        folder = self.get("output_folder")
        if not folder or not os.path.exists(folder):
            if getattr(sys, "frozen", False):
                # When built as EXE, output to EXE directory / output
                exe_dir = os.path.dirname(sys.executable)
                default_out = os.path.join(exe_dir, "output")
            else:
                # When running from source, use Desktop which avoids Windows Defender Controlled Folder Access
                default_out = os.path.join(os.path.expanduser("~"), "Desktop", "EarPurifier_Output")
            try:
                os.makedirs(default_out, exist_ok=True)
            except Exception as e:
                logger.warning(f"Could not create default output folder: {e}")
            return default_out
        return folder
