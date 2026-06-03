"""
Knowledge Manager - Entry Point
"""
import os
import sys
import faulthandler
from PySide6.QtWidgets import QApplication

from core.database import init_db
from core.logger import setup_logging, install_exception_hook, LOG_DIR
from ui.main_window import MainWindow


def main():
    logger = setup_logging()
    install_exception_hook()
    # Enable C-level crash dump (segfaults, aborts) to a dedicated log file
    os.makedirs(LOG_DIR, exist_ok=True)
    crash_log_path = os.path.join(LOG_DIR, "crash.log")
    crash_log = open(crash_log_path, "a", buffering=1, encoding="utf-8")
    faulthandler.enable(file=crash_log)
    logger.info("Knowledge Manager starting...")
    init_db()
    app = QApplication(sys.argv)
    # Let MainWindow apply its own dark theme/palette
    window = MainWindow()
    window.show()
    logger.info("MainWindow shown")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
