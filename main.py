"""
EarPurifier - AI Audio Isolation Desktop Application
Main application entry point, OS integration, and IPC single-instance orchestrator.
"""

import sys
import os
import ctypes
import logging
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QIcon

# Ensure current directory is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from ui.theme import get_asset_path
from ui.main_window import MainWindow

# ─── Windows Taskbar AppUserModelID (Ensures icon appears in Taskbar) ─────────
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EarPurifier.SproutAudio.Studio.2.0")
except Exception:
    pass


# ─── Global Uncaught Exception Trap ───────────────────────────────────────────
def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """Logs unhandled exceptions and displays a user-friendly error dialog."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logging.critical(f"Uncaught exception:\n{err_msg}")
    
    if QApplication.instance():
        try:
            QMessageBox.critical(
                None,
                "Unexpected Error - EarPurifier",
                f"An unexpected error occurred:\n\n{exc_value}\n\nPlease check the application log for details."
            )
        except Exception:
            pass


sys.excepthook = handle_uncaught_exception


# ─── Main Application Bootstrap ───────────────────────────────────────────────
def main():
    # ── High-DPI Display Attributes ──
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # ── Single-Instance Enforcement via Qt Local IPC ──
    server_name = "EarPurifier_SingleInstance_IPC"
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(500):
        # A primary instance is already running. Signal it to activate its window and exit.
        socket.write(b"ACTIVATE\n")
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        sys.exit(0)

    # Clean up any stale pipe registration from an earlier abrupt crash
    QLocalServer.removeServer(server_name)
    local_server = QLocalServer()
    if not local_server.listen(server_name):
        logging.warning(f"Could not bind single-instance server: {local_server.errorString()}")

    # ── Window & App Icon ──
    logo_ico = get_asset_path("logo.ico")
    logo_png = get_asset_path("logo.png")
    if os.path.exists(logo_ico):
        app.setWindowIcon(QIcon(logo_ico))
    elif os.path.exists(logo_png):
        app.setWindowIcon(QIcon(logo_png))

    # ── Main Window Instantiation ──
    window = MainWindow()

    def handle_ipc_activation():
        client = local_server.nextPendingConnection()
        if client:
            window.showNormal()
            window.raise_()
            window.activateWindow()
            client.deleteLater()

    local_server.newConnection.connect(handle_ipc_activation)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
