"""
Logging setup for Knowledge Manager.
Logs to both file (logs/app.log) and console.
File rotates daily, keeps 7 days of history.
"""
import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler

if getattr(sys, 'frozen', False):
    # exe is at 项目根目录/dist/KnowledgeManager/KnowledgeManager.exe
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOG_DIR = os.path.join(_BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")


def setup_logging() -> logging.Logger:
    """Configure root logger with file and console handlers."""
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger("KnowledgeManager")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler: rotate at midnight, keep 7 days
    file_handler = TimedRotatingFileHandler(
        LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def _uncaught_exception_hook(exc_type, exc_value, exc_traceback):
    """Log uncaught exceptions before the app crashes."""
    logger = logging.getLogger("KnowledgeManager")
    if issubclass(exc_type, KeyboardInterrupt):
        # Don't log keyboard interrupt
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def install_exception_hook():
    """Install global exception hook to catch crashes."""
    sys.excepthook = _uncaught_exception_hook


def get_logger() -> logging.Logger:
    """Get the application logger."""
    return logging.getLogger("KnowledgeManager")
