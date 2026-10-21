import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
import time
try:
    from .config_manager import ConfigManager
except ImportError:
    from config_manager import ConfigManager

def setup_logger(config: ConfigManager):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    # Only add console handler if stdout is available
    if sys.stdout:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    if config.get("enable_logging"):
        log_dir = os.path.join(config.appdata_dir, "applogs")
        os.makedirs(log_dir, exist_ok=True)
        
        # Clear logs older than 2 days
        current_time = time.time()
        for f in os.listdir(log_dir):
            file_path = os.path.join(log_dir, f)
            if os.path.isfile(file_path):
                # 2 days = 172800 seconds
                if os.stat(file_path).st_mtime < current_time - 172800:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                        
        kaggle_log_dir = os.path.join(log_dir, "kaggle_logs")
        if os.path.exists(kaggle_log_dir):
            for f in os.listdir(kaggle_log_dir):
                file_path = os.path.join(kaggle_log_dir, f)
                if os.path.isfile(file_path):
                    if os.stat(file_path).st_mtime < current_time - 172800:
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass

        log_file = os.path.join(log_dir, "earpurifier.log")
        # Rotating log every midnight
        fh = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=2)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
