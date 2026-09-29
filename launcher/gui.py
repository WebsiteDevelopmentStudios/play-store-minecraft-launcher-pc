from __future__ import annotations

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

from .adb import AdbError, devices, find_adb, install, launch, optimize_android, run_adb
from .apk import inspect_apk
from .runtime import RuntimeErrorBase, is_ready, prepare, start, wait_for_boot


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Blemm Bedrock Launcher")
        self.resize(900, 560)

        self.apk_path: Path | None = None
        self.android_process = None

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
            "Import your own Minecraft Bedrock APK. "
            "Blemm can automatically prepare its Android runtime "
            "the first time you play."
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

    def set_status(self, message: str) -> None:
        self.status.setText(message)
        QApplication.processEvents()

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
            "Press Play Bedrock to prepare Android automatically."
        )
        self.play_button.setEnabled(True)

    def play(self) -> None:
        if self.apk_path is None:
            return

        self.play_button.setEnabled(False)

        try:
            adb = find_adb(auto_install=True)
            if adb is None:
                raise AdbError(
                    "Android Platform-Tools (ADB) could not be installed."
                )

            self.set_status("ADB is ready.")

            connected = devices()

            if not connected:
                if not is_ready():
                    self.set_status(
                        "Android runtime not found. Setting it up automatically..."
                    )
                    prepare(self.set_status)

                self.android_process = start(self.set_status)

                # ADB may need a few seconds to notice the newly started emulator.
                self.set_status("Connecting ADB to Android...")
                device = wait_for_boot(run_adb, self.set_status)
            else:
                device = connected[0]

            self.set_status(
                f"Android runtime connected: {device}\n"
                "Optimizing Android for gaming..."
            )
            optimize_android(device)

            self.set_status(
                "Android gaming mode enabled.\n"
                "Installing Minecraft APK..."
            )
            install(self.apk_path, device)

            self.set_status(
                "Minecraft APK installed. Launching Minecraft..."
            )
            package = launch(self.apk_path, device)

            self.set_status(
                f"Minecraft launched successfully.\n\n"
                f"Package: {package}\n"
                f"Android device: {device}\n\n"
                "Sign in through Minecraft's normal Microsoft account screen."
            )

        except (AdbError, RuntimeErrorBase, OSError, ValueError) as exc:
            self.set_status("Launch failed.")
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


if __name__ == "__main__":
    raise SystemExit(run())
