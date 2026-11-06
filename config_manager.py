import os
import sys
import json
import time
import tempfile
import logging
from pathlib import Path

from system_utils import get_app_data_dir, get_default_output_folder

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


def _get_posix_master_key() -> bytes:
    """Retrieves or creates a 256-bit machine-local encryption key with 0600 permissions."""
    key_path = os.path.join(get_app_data_dir(), ".device_key")
    if os.path.exists(key_path):
        try:
            with open(key_path, "rb") as f:
                key = f.read(32)
                if len(key) == 32:
                    return key
        except Exception as e:
            logger.warning(f"Could not read device key from {key_path}: {e}")

    import secrets
    key = secrets.token_bytes(32)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= getattr(os, "O_BINARY")
        mode = 0o600
        fd = os.open(key_path, flags, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        if hasattr(os, "chmod") and sys.platform != "win32":
            try:
                os.chmod(key_path, 0o600)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Could not persist POSIX device key to {key_path}: {e}")
    return key


def _protect_secret(plain_text: str) -> str:
    """
    Encrypts sensitive string (e.g., Kaggle API key):
    - Windows: DPAPI (CryptProtectData) prefixed with 'enc:'
    - macOS & Linux: AES-256-GCM via cryptography prefixed with 'enc:gcm:'
    """
    if not plain_text:
        return plain_text

    if sys.platform == "win32":
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
    else:
        # macOS & Linux: AES-256-GCM
        try:
            import base64
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = _get_posix_master_key()
            aesgcm = AESGCM(key)
            nonce = os.urandom(12)
            ct = aesgcm.encrypt(nonce, plain_text.encode('utf-8'), None)
            return "enc:gcm:" + base64.b64encode(nonce + ct).decode('ascii')
        except Exception as e:
            logger.warning(f"POSIX AES-GCM encryption failed: {e}")
            return plain_text


def _unprotect_secret(cipher_text: str) -> str:
    """
    Decrypts protected string:
    - 'enc:gcm:...': AES-256-GCM (macOS, Linux, cross-platform)
    - 'enc:...': Windows DPAPI (CryptUnprotectData)
    """
    if not cipher_text or not isinstance(cipher_text, str) or not cipher_text.startswith("enc:"):
        return cipher_text

    if cipher_text.startswith("enc:gcm:"):
        try:
            import base64
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = _get_posix_master_key()
            raw = base64.b64decode(cipher_text[8:])
            nonce, ct = raw[:12], raw[12:]
            aesgcm = AESGCM(key)
            return aesgcm.decrypt(nonce, ct, None).decode('utf-8')
        except Exception as e:
            logger.warning(f"POSIX AES-GCM decryption failed: {e}")
            return ""

    if sys.platform == "win32":
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

    logger.warning("Windows DPAPI ciphertext cannot be decrypted on non-Windows platforms. Please re-enter API key.")
    return ""


class ConfigManager:
    def __init__(self):
        self.appdata_dir = get_app_data_dir()
        self.config_file = os.path.join(self.appdata_dir, 'config.json')
        self.default_config = {
            "kaggle_username": "",
            "kaggle_api_key": "",
            "output_folder": "",
            "enable_logging": True,
            "local_model": "SOTA (RoFormer) - Requires High-End GPU",
            "processing_mode": "Cloud (Kaggle)", # or "Local (GPU)"
            "delete_output_files": False,
            "language": "ar",
            "check_updates": True,
            "ignored_release_tag": "",
            "last_update_check": ""
        }
        self.config = self.load_config()

    def load_config(self) -> dict:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Merge with defaults
                    for k, v in self.default_config.items():
                        if k not in data or (k == "local_model" and not data.get("local_model")):
                            data[k] = v
                    if data.get("kaggle_api_key"):
                        data["kaggle_api_key"] = _unprotect_secret(data["kaggle_api_key"])
                    return data
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                return self.default_config.copy()

        # Fresh startup: instantiate and persist default config immediately
        default_cfg = self.default_config.copy()
        try:
            _atomic_write_json(self.config_file, default_cfg, indent=4)
        except Exception as e:
            logger.warning(f"Could not write initial config: {e}")
        return default_cfg

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

    def get_output_folder(self, executable_dir: str = "") -> str:
        folder = self.get("output_folder")
        if not folder or not os.path.exists(folder):
            return get_default_output_folder()
        return folder
