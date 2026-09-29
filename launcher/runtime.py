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

COMMAND_LINE_TOOLS_URLS = [
    "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip",
    "https://dl.google.com/android/repository/commandlinetools-win-9477386_latest.zip",
]

SYSTEM_IMAGE = "system-images;android-35;google_apis_playstore;x86_64"
SDK_PACKAGES = [
    "platform-tools",
    "emulator",
    "platforms;android-35",
    "build-tools;35.0.0",
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
        if os.name == "nt" and command and command[0].lower().endswith(".bat"):
            command = ["cmd.exe", "/d", "/s", "/c", *command]

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
    last_error = ""

    try:
        progress("Downloading Android runtime tools...")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "BlemmBedrockLauncher/0.1"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
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
                        progress(
                            f"Downloading Android runtime tools... "
                            f"{downloaded * 100 // total}%"
                        )
        partial.replace(destination)
        return
    except Exception as exc:
        last_error = str(exc)
        partial.unlink(missing_ok=True)

    if os.name == "nt" and shutil.which("curl.exe"):
        progress("Retrying Android runtime download with Windows curl...")
        result = subprocess.run(
            [
                "curl.exe",
                "-L",
                "--fail",
                "--retry",
                "3",
                "--retry-delay",
                "2",
                "--connect-timeout",
                "20",
                "--max-time",
                "600",
                "-A",
                "BlemmBedrockLauncher/0.1",
                "-o",
                str(partial),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=660,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and partial.is_file() and partial.stat().st_size > 0:
            partial.replace(destination)
            return

        curl_error = (result.stderr or result.stdout).strip()
        if curl_error:
            last_error = f"{last_error}; curl: {curl_error}".strip("; ")

    raise RuntimeErrorBase(
        "Could not download the official Android command-line tools. "
        "Check your internet connection, firewall, or antivirus settings.\n\n"
        f"Download error: {last_error or 'unknown download error'}"
    )


def _install_command_line_tools(progress: Progress) -> None:
    if SDKMANAGER.is_file() and AVDMANAGER.is_file():
        return

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    archive = RUNTIME_DIR / "commandlinetools-windows.zip"

    last_error = ""
    for url in COMMAND_LINE_TOOLS_URLS:
        try:
            _download(url, archive, progress)
            break
        except RuntimeErrorBase as exc:
            last_error = str(exc)
            archive.unlink(missing_ok=True)
    else:
        raise RuntimeErrorBase(last_error)

    temp_root = RUNTIME_DIR / "cmdline-extract"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    progress("Extracting Android runtime tools...")

    try:
        with zipfile.ZipFile(archive) as archive_file:
            archive_file.extractall(temp_root)
    except zipfile.BadZipFile as exc:
        raise RuntimeErrorBase(
            "The Android command-line tools download was not a valid ZIP archive."
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
    env["PATH"] = os.pathsep.join(
        [
            str(CMDLINE_DIR / "bin"),
            str(SDK_DIR / "platform-tools"),
            str(SDK_DIR / "emulator"),
            env.get("PATH", ""),
        ]
    )
    return env


def _ensure_java(progress: Progress) -> Path:
    existing = os.environ.get("JAVA_HOME", "").strip().strip('"')
    if existing:
        existing_path = Path(existing)
        if (existing_path / "bin" / "java.exe").is_file():
            return existing_path

    clean_env = os.environ.copy()
    clean_env.pop("JAVA_HOME", None)

    java = shutil.which("java", path=clean_env.get("PATH"))
    if java:
        java_path = Path(java).resolve()
        if java_path.name.lower() == "java.exe":
            java_home = java_path.parent.parent
            if (java_home / "bin" / "java.exe").is_file():
                return java_home

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
        raise RuntimeErrorBase("Java was downloaded, but java.exe was not found.")

    shutil.rmtree(java_dir, ignore_errors=True)
    shutil.move(str(candidates[0].parent.parent), str(java_dir))
    shutil.rmtree(extract_root, ignore_errors=True)
    archive.unlink(missing_ok=True)

    if not java_exe.is_file():
        raise RuntimeErrorBase("Java installation did not complete.")
    return java_dir


def _tool_env(java_home: Path) -> dict[str, str]:
    env = _sdk_environment()
    env["JAVA_HOME"] = str(java_home)
    env["CLASSPATH"] = ""
    return env


def _accept_licenses(env: dict[str, str], progress: Progress) -> None:
    progress("Checking Android SDK licenses...")
    result = _run(
        [str(SDKMANAGER), "--licenses"],
        timeout=180,
        env=env,
        input_text=("y\n" * 100),
    )

    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    if result.returncode != 0:
        raise RuntimeErrorBase(
            "Android SDK license setup failed.\n\n"
            + (output or "sdkmanager returned a non-zero exit code.")
        )

    if "not accepted" in output.lower():
        raise RuntimeErrorBase(
            "Android SDK license setup failed.\n\n" + output
        )


def _install_sdk_packages(env: dict[str, str], progress: Progress) -> None:
    progress("Installing Android emulator components...")
    result = _run(
        [str(SDKMANAGER), *SDK_PACKAGES],
        timeout=1800,
        env=env,
        input_text=("y\n" * 100),
    )

    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    if result.returncode != 0:
        raise RuntimeErrorBase(
            "Android SDK component installation failed.\n\n"
            + (output or "sdkmanager returned a non-zero exit code.")
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

    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    if result.returncode != 0:
        raise RuntimeErrorBase(
            "Could not create the Android virtual device.\n\n"
            + (output or "avdmanager returned a non-zero exit code.")
        )


def _configure_gaming_avd(progress: Progress) -> None:
    config = RUNTIME_DIR / "avd" / f"{AVD_NAME}.avd" / "config.ini"
    if not config.is_file():
        return

    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeErrorBase("Could not read the Android device configuration.") from exc

    cpu_count = os.cpu_count() or 4
    # Keep some CPU available for Windows and Minecraft's launcher/UI.
    cores = max(4, min(8, cpu_count - 2))
    ram_mb = 6144 if (os.cpu_count() or 4) >= 8 else 4096

    overrides = {
        "hw.cpu.ncore": str(cores),
        "hw.ramSize": str(ram_mb),
        "vm.heapSize": "512",
        "hw.gpu.enabled": "yes",
        "hw.gpu.mode": "host",
        "hw.lcd.refreshRate": "120",
        "hw.lcd.density": "420",
        "hw.audioInput": "yes",
        "hw.audioOutput": "yes",
        "fastboot.forceColdBoot": "no",
    }

    updated: list[str] = []
    seen: set[str] = set()

    for line in lines:
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in overrides:
                updated.append(f"{key}={overrides[key]}")
                seen.add(key)
                continue
        updated.append(line)

    for key, value in overrides.items():
        if key not in seen:
            updated.append(f"{key}={value}")

    try:
        config.write_text("\n".join(updated) + "\n", encoding="utf-8")
    except OSError as exc:
        raise RuntimeErrorBase("Could not save Android gaming configuration.") from exc

    progress(
        f"Gaming mode enabled: {cores} CPU cores, {ram_mb} MB RAM, "
        "hardware GPU, 120 Hz target."
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
    env = _tool_env(java_home)

    _accept_licenses(env, progress)
    _install_sdk_packages(env, progress)
    _create_avd(env, progress)
    _configure_gaming_avd(progress)

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
    else:
        _configure_gaming_avd(progress)

    avd_home = RUNTIME_DIR / "avd"
    avd_home.mkdir(parents=True, exist_ok=True)
    env = _sdk_environment()
    env["ANDROID_AVD_HOME"] = str(avd_home)

    progress("Starting Android in gaming mode...")
    return subprocess.Popen(
        [
            str(EMULATOR),
            "-avd",
            AVD_NAME,
            "-gpu",
            "host",
            "-accel",
            "auto",
            "-cores",
            str(max(4, min(8, (os.cpu_count() or 4) - 2))),
            "-memory",
            "6144" if (os.cpu_count() or 4) >= 8 else "4096",
            "-no-boot-anim",
            "-camera-back",
            "none",
            "-camera-front",
            "none",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


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
                    "-s", device, "shell", "getprop", "sys.boot_completed",
                    timeout=15,
                )
                if boot.returncode == 0 and boot.stdout.strip() == "1":
                    progress(f"Android is ready: {device}")
                    return device
        time.sleep(2)

    raise RuntimeErrorBase(
        "Android started, but it did not finish booting within 180 seconds."
    )
