import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self):
        self.appdata_dir = os.path.join(os.environ.get('APPDATA', ''), 'EarPurifier')
        os.makedirs(self.appdata_dir, exist_ok=True)
        self.config_file = os.path.join(self.appdata_dir, 'config.json')
        self.default_config = {
            "kaggle_username": "",
            "kaggle_api_key": "",
            "output_folder": "",
            "enable_logging": False,
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
                    return data
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                return self.default_config.copy()
        return self.default_config.copy()

    def save_config(self, new_config: dict):
        self.config.update(new_config)
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value
        self.save_config({}) # Triggers a save

    def get_output_folder(self, executable_dir: str) -> str:
        folder = self.get("output_folder")
        if not folder or not os.path.exists(folder):
            import sys
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
