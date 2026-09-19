import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import List

# Force stdout / stderr to UTF-8 on Windows to avoid UnicodeEncodeError
if sys.platform.startswith("win"):
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, "app.log")

class SafeStreamHandler(logging.StreamHandler):
    """
    Console StreamHandler an toàn trên Windows, tự động thay thế ký tự không mã hóa được
    thay vì throw UnicodeEncodeError làm dừng chương trình.
    """
    def emit(self, record):
        if not self.stream:
            return
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                msg = self.format(record)
                safe_msg = msg.encode("ascii", errors="replace").decode("ascii")
                self.stream.write(safe_msg + self.terminator)
                self.flush()
            except Exception:
                pass
        except Exception:
            pass

def setup_logger():
    logger = logging.getLogger("PCAuxCleaner")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # File handler with rotation (max 5MB, 3 backups) - UTF-8 encoded
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_format = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

        # Safe stream handler for console (only if running with a console / not pythonw)
        if sys.stdout is not None:
            console_handler = SafeStreamHandler(sys.stdout)
            console_format = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%H:%M:%S"
            )
            console_handler.setFormatter(console_format)
            logger.addHandler(console_handler)

    # Log uncaught exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        try:
            logger.critical("Uncaught Exception xảy ra:", exc_info=(exc_type, exc_value, exc_traceback))
        except Exception:
            pass

    sys.excepthook = handle_exception
    return logger

logger = setup_logger()

def get_recent_logs(max_lines: int = 50) -> str:
    """
    Đọc các dòng log gần nhất từ file app.log
    """
    if not os.path.exists(LOG_FILE):
        return "Chưa có file nhật ký (app.log)."
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-max_lines:])
    except Exception as e:
        return f"Không thể đọc file log: {e}"
