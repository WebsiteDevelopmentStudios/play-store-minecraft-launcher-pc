from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .config import RUNTIME_DIR


class RuntimeErrorBase(RuntimeError):
    """Raised when the managed Android runtime cannot be prepared."""


SDK_DIR = RUNTIME_DIR / "android-sdk"
CMDLINE_DIR = SDK_DIR / "cmdline-tools" / "latest"
SDKMANAGER = CMDLINE_DIR / "bin" / "sdkmanager.bat"
AVDMANAGER = CMDLINE_DIR / "bin" / "avdmanager.bat"
EMULATOR = SDK_DIR / "emulator" / "emulator.exe"
AVD_NAME = "BlemmBedrock"

# Official Google Android command-line tools archive.
COMMAND_LINE_TOOLS_URL = (
    "https://dl.google.com/android/repository/"
    "commandlinetools-win-11076708_latest.zip"
)

# The Play Store image provides Google Play services for normal Android app
# authentication flows. The user's Minecraft APK is still supplied separately.
SYSTEM_IMAGE = "system-images;android-35;google_apis_playstore;x86_64"
SDK_PACKAGES = [
    "platform-tools",
    "emulator",
    "platforms;android-35",
    SYSTEM_IMAGE,
]

Progress = Callable[[str], None]


def _run(
    command: list[str],
    *,
    timeout: int = 300,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as exc:
        raise RuntimeErrorBase(
            f"Could not start Android runtime tool: {command[0]}"
        ) from exc


def _download(url: str, destination: Path, progress: Progress) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")

    try:
        progress("Downloading Android runtime tools...")
        with urllib.request.urlopen(url, timeout=60) as response:
            total = int(response.headers.get("Content-Length", "0"))
            downloaded = 0

            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break

                    handle.write(chunk)
                    downloaded += len(chunk)

                    if total:
                        percent = downloaded * 100 // total
                        progress(
                            f"Downloading Android runtime tools... {percent}%"
                        )

        partial.replace(destination)

    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeErrorBase(
            "Could not download the official Android command-line tools. "
            "Check your internet connection and try again."
        ) from exc


def _install_command_line_tools(progress: Progress) -> None:
    if SDKMANAGER.is_file() and AVDMANAGER.is_file():
        return

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    archive = RUNTIME_DIR / "commandlinetools-windows.zip"

    _download(COMMAND_LINE_TOOLS_URL, archive, progress)

    temp_root = RUNTIME_DIR / "cmdline-extract"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    progress("Extracting Android runtime tools...")

    try:
        with zipfile.ZipFile(archive) as archive_file:
            archive_file.extractall(temp_root)
    except zipfile.BadZipFile as exc:
        raise RuntimeErrorBase(
            "The downloaded Android command-line tools archive is invalid."
        ) from exc

    extracted = temp_root / "cmdline-tools"
    if not extracted.is_dir():
        raise RuntimeErrorBase(
            "Android command-line tools were downloaded, but the expected "
            "cmdline-tools directory was not found."
        )

    CMDLINE_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(CMDLINE_DIR, ignore_errors=True)
    shutil.move(str(extracted), str(CMDLINE_DIR))

    shutil.rmtree(temp_root, ignore_errors=True)
    archive.unlink(missing_ok=True)


def _sdk_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["ANDROID_HOME"] = str(SDK_DIR)
    env["ANDROID_SDK_ROOT"] = str(SDK_DIR)

    path_parts = [
        str(CMDLINE_DIR / "bin"),
        str(SDK_DIR / "platform-tools"),
        str(SDK_DIR / "emulator"),
    ]

    env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])
    return env


def _ensure_java(progress: Progress) -> Path:
    existing = os.environ.get("JAVA_HOME")
    if existing and (Path(existing) / "bin" / "java.exe").is_file():
        return Path(existing)

    java = shutil.which("java")
    if java:
        return Path(java).resolve().parent.parent

    # Android command-line tools require a Java runtime. Use the official
    # Eclipse Adoptium API to obtain a local JDK without requiring a manual
    # Java installation.
    java_dir = RUNTIME_DIR / "jdk-17"
    java_exe = java_dir / "bin" / "java.exe"

    if java_exe.is_file():
        return java_dir

    url = (
        "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/"
        "jdk/hotspot/normal/eclipse"
    )
    archive = RUNTIME_DIR / "jdk17.zip"
    _download(url, archive, progress)

    extract_root = RUNTIME_DIR / "jdk17-extract"
    shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True, exist_ok=True)

    progress("Installing Java for Android tools...")

    try:
        with zipfile.ZipFile(archive) as archive_file:
            archive_file.extractall(extract_root)
    except zipfile.BadZipFile as exc:
        raise RuntimeErrorBase("The downloaded Java archive is invalid.") from exc

    candidates = list(extract_root.glob("*/bin/java.exe"))
    if not candidates:
        raise RuntimeErrorBase(
            "Java was downloaded, but java.exe was not found."
        )

    shutil.rmtree(java_dir, ignore_errors=True)
    shutil.move(str(candidates[0].parent.parent), str(java_dir))

    shutil.rmtree(extract_root, ignore_errors=True)
    archive.unlink(missing_ok=True)

    if not java_exe.is_file():
        raise RuntimeErrorBase("Java installation did not complete.")

    return java_dir


def _accept_licenses(env: dict[str, str], progress: Progress) -> None:
    progress("Checking Android SDK licenses...")

    result = _run(
        [str(SDKMANAGER), "--licenses"],
        timeout=120,
        env=env,
        input_text=("y\n" * 30),
    )

    if result.returncode != 0:
        raise RuntimeErrorBase(
            result.stderr.strip()
            or "Android SDK license setup failed."
        )


def _install_sdk_packages(env: dict[str, str], progress: Progress) -> None:
    progress("Installing Android emulator components...")

    result = _run(
        [str(SDKMANAGER), *SDK_PACKAGES],
        timeout=1800,
        env=env,
        input_text=("y\n" * 30),
    )

    if result.returncode != 0:
        raise RuntimeErrorBase(
            result.stderr.strip()
            or result.stdout.strip()
            or "Android SDK component installation failed."
        )


def _create_avd(env: dict[str, str], progress: Progress) -> None:
    avd_home = RUNTIME_DIR / "avd"
    avd_home.mkdir(parents=True, exist_ok=True)

    env["ANDROID_AVD_HOME"] = str(avd_home)

    existing = _run(
        [str(AVDMANAGER), "list", "avd"],
        timeout=60,
        env=env,
    )

    if f"Name: {AVD_NAME}" in existing.stdout:
        return

    progress("Creating the Blemm Android device...")

    result = _run(
        [
            str(AVDMANAGER),
            "create",
            "avd",
            "--name",
            AVD_NAME,
            "--package",
            SYSTEM_IMAGE,
            "--device",
            "pixel_6",
            "--force",
        ],
        timeout=300,
        env=env,
        input_text="no\n",
    )

    if result.returncode != 0:
        raise RuntimeErrorBase(
            result.stderr.strip()
            or result.stdout.strip()
            or "Could not create the Android virtual device."
        )


def prepare(progress: Progress | None = None) -> None:
    progress = progress or (lambda _message: None)

    if os.name != "nt":
        raise RuntimeErrorBase(
            "The managed Android runtime currently targets Windows 10/11 x64."
        )

    progress("Preparing Android runtime...")

    _install_command_line_tools(progress)
    java_home = _ensure_java(progress)

    env = _sdk_environment()
    env["JAVA_HOME"] = str(java_home)

    _accept_licenses(env, progress)
    _install_sdk_packages(env, progress)
    _create_avd(env, progress)

    if not EMULATOR.is_file():
        raise RuntimeErrorBase(
            "Android emulator installation completed, but emulator.exe was not found."
        )

    progress("Android runtime is ready.")


def is_ready() -> bool:
    return EMULATOR.is_file() and SDKMANAGER.is_file()


def start(progress: Progress | None = None) -> subprocess.Popen[str]:
    progress = progress or (lambda _message: None)

    if not is_ready():
        prepare(progress)

    avd_home = RUNTIME_DIR / "avd"
    avd_home.mkdir(parents=True, exist_ok=True)

    env = _sdk_environment()
    env["ANDROID_AVD_HOME"] = str(avd_home)

    progress("Starting Android...")

    process = subprocess.Popen(
        [
            str(EMULATOR),
            "-avd",
            AVD_NAME,
            "-no-snapshot",
            "-no-boot-anim",
            "-gpu",
            "swiftshader_indirect",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    return process


def wait_for_boot(
    adb_runner: Callable[..., subprocess.CompletedProcess[str]],
    progress: Progress | None = None,
    timeout: int = 180,
) -> str:
    progress = progress or (lambda _message: None)
    deadline = time.monotonic() + timeout

    progress("Waiting for Android to finish booting...")

    while time.monotonic() < deadline:
        result = adb_runner("devices", timeout=15)

        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                device = parts[0]

                boot = adb_runner(
                    "-s",
                    device,
                    "shell",
                    "getprop",
                    "sys.boot_completed",
                    timeout=15,
                )

                if boot.returncode == 0 and boot.stdout.strip() == "1":
                    progress(f"Android is ready: {device}")
                    return device

        time.sleep(2)

    raise RuntimeErrorBase(
        "Android started, but it did not finish booting within 180 seconds."
    )
