from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .adb import AdbError, devices, install, launch
from .apk import inspect_apk


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Blemm Bedrock Launcher")
        self.resize(900, 560)

        self.apk_path: Path | None = None

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(18)

        title = QLabel("Blemm Bedrock")
        title.setStyleSheet("font-size: 34px; font-weight: 700;")

        subtitle = QLabel(
            "Run your own Minecraft Bedrock Android APK on Windows."
        )
        subtitle.setStyleSheet("font-size: 16px;")

        self.status = QLabel(
            "Minecraft APK required\n\n"
            "Import your own Minecraft Bedrock APK, then launch it "
            "through a running Android emulator."
        )
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 15px; padding: 20px;")

        import_button = QPushButton("Import Minecraft APK")
        import_button.setMinimumHeight(52)
        import_button.clicked.connect(self.import_apk)

        self.play_button = QPushButton("Play Bedrock")
        self.play_button.setMinimumHeight(52)
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.play)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(20)
        layout.addWidget(self.status)
        layout.addStretch()
        layout.addWidget(import_button)
        layout.addWidget(self.play_button)

        self.setCentralWidget(root)

        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #101318;
                color: #f3f5f7;
            }
            QPushButton {
                background: #242a33;
                border: 1px solid #39424f;
                border-radius: 12px;
                padding: 12px 18px;
                font-size: 15px;
            }
            QPushButton:hover {
                background: #303846;
            }
            QPushButton:disabled {
                color: #707985;
                background: #191d23;
            }
            """
        )

    def import_apk(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Minecraft Bedrock APK",
            str(Path.home()),
            "Android APK (*.apk)",
        )

        if not filename:
            return

        try:
            info = inspect_apk(filename)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Invalid APK", str(exc))
            return

        self.apk_path = info.path

        self.status.setText(
            f"APK imported successfully.\n\n"
            f"File: {info.path.name}\n"
            f"Size: {info.size / (1024 * 1024):.1f} MB\n"
            f"SHA-256: {info.sha256}\n\n"
            "Click Play Bedrock with an Android emulator already running."
        )
        self.play_button.setEnabled(True)

    def play(self) -> None:
        if self.apk_path is None:
            return

        self.play_button.setEnabled(False)
        self.status.setText("Starting Android runtime connection...")

        try:
            connected = devices()
            if not connected:
                raise AdbError(
                    "No Android device/emulator is connected to ADB.\n\n"
                    "Start an Android emulator with ADB enabled, then click "
                    "Play Bedrock again."
                )

            device = connected[0]
            self.status.setText(
                f"Android runtime connected: {device}\n"
                "Installing Minecraft APK..."
            )

            install(self.apk_path, device)

            self.status.setText(
                "Minecraft APK installed. Launching Minecraft..."
            )
            package = launch(self.apk_path, device)

            self.status.setText(
                f"Minecraft launched successfully.\n\n"
                f"Package: {package}\n"
                f"Android device: {device}\n\n"
                "Sign in through Minecraft's normal Microsoft account screen."
            )

        except (AdbError, OSError, ValueError) as exc:
            self.status.setText("Launch failed.")
            QMessageBox.critical(
                self,
                "Could not launch Minecraft",
                str(exc),
            )
        finally:
            self.play_button.setEnabled(True)


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
