from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from .config import RUNTIME_DIR


class AdbError(RuntimeError):
    pass


PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
PLATFORM_TOOLS_DIR = RUNTIME_DIR / "platform-tools"
BUNDLED_ADB = PLATFORM_TOOLS_DIR / "adb.exe"


def _download_platform_tools() -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    archive = RUNTIME_DIR / "platform-tools-windows.zip"
    temp_archive = RUNTIME_DIR / "platform-tools-windows.zip.part"

    try:
        with urllib.request.urlopen(PLATFORM_TOOLS_URL, timeout=30) as response:
            with temp_archive.open("wb") as handle:
                shutil.copyfileobj(response, handle)

        with zipfile.ZipFile(temp_archive) as archive_file:
            archive_file.extractall(RUNTIME_DIR)

        temp_archive.unlink(missing_ok=True)
    except Exception as exc:
        temp_archive.unlink(missing_ok=True)
        raise AdbError(
            "Could not download Android Platform-Tools (ADB). "
            "Check your internet connection and try again."
        ) from exc

    if not BUNDLED_ADB.is_file():
        raise AdbError(
            "Platform-Tools downloaded, but adb.exe was not found after extraction."
        )

    return BUNDLED_ADB


def find_adb(auto_install: bool = True) -> Path | None:
    if BUNDLED_ADB.is_file():
        return BUNDLED_ADB

    candidates = [
        shutil.which("adb"),
        Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools/adb.exe",
        Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "platform-tools/adb.exe",
    ]

    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path

    if auto_install and os.name == "nt":
        return _download_platform_tools()

    return None


def run_adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    adb = find_adb()
    if adb is None:
        raise AdbError("ADB could not be found or installed.")

    return subprocess.run(
        [str(adb), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def devices() -> list[str]:
    run_adb("start-server", timeout=15)
    result = run_adb("devices")
    if result.returncode != 0:
        raise AdbError(result.stderr.strip() or "ADB failed.")

    found: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            found.append(parts[0])
    return found


def optimize_android(device: str) -> None:
    """Reduce Android UI overhead and request a high refresh rate for gaming."""
    settings = [
        ("global", "window_animation_scale", "0"),
        ("global", "transition_animation_scale", "0"),
        ("global", "animator_duration_scale", "0"),
        ("system", "peak_refresh_rate", "120.0"),
        ("system", "min_refresh_rate", "60.0"),
    ]

    for namespace, key, value in settings:
        result = run_adb(
            "-s", device, "shell", "settings", "put", namespace, key, value,
            timeout=15,
        )
        if result.returncode != 0:
            # Refresh-rate settings vary between Android images. Animation
            # settings are also non-essential, so don't prevent Minecraft
            # from launching if one isn't supported.
            continue


def install(apk: Path, device: str | None = None) -> None:
    if not apk.is_file():
        raise AdbError(f"APK not found: {apk}")

    args = ["install", "-r"]
    if device:
        args[0:0] = ["-s", device]
    args.append(str(apk))

    result = run_adb(*args, timeout=300)
    if result.returncode != 0:
        raise AdbError(
            result.stderr.strip() or result.stdout.strip() or "APK installation failed."
        )


def package_name_from_apk(apk: Path) -> str:
    sdk_roots = [
        Path(os.environ.get("ANDROID_HOME", "")),
        Path(os.environ.get("ANDROID_SDK_ROOT", "")),
        Path.home() / "AppData/Local/Android/Sdk",
    ]

    aapt_candidates: list[Path] = []
    for root in sdk_roots:
        if not root:
            continue
        build_tools = root / "build-tools"
        if build_tools.is_dir():
            aapt_candidates.extend(
                sorted(build_tools.glob("*/aapt.exe"), reverse=True)
            )

    which_aapt = shutil.which("aapt")
    if which_aapt:
        aapt_candidates.insert(0, Path(which_aapt))

    for aapt in aapt_candidates:
        result = subprocess.run(
            [str(aapt), "dump", "badging", str(apk)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("package: name="):
                    marker = "package: name='"
                    start = line.find(marker)
                    if start >= 0:
                        start += len(marker)
                        end = line.find("'", start)
                        if end > start:
                            return line[start:end]

    raise AdbError(
        "ADB is ready, but Android SDK Build-Tools are still needed to read "
        "the APK package name."
    )


def launch(apk: Path, device: str | None = None) -> str:
    package = package_name_from_apk(apk)
    target = ["-s", device] if device else []

    # Resolve the real launcher activity. This is more reliable than monkey,
    # which can return success even when no activity was actually started.
    resolve = run_adb(
        *target,
        "shell",
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        package,
        timeout=30,
    )

    if resolve.returncode != 0:
        details = (resolve.stderr or resolve.stdout).strip()
        raise AdbError(
            f"Could not find Minecraft's launcher activity for package {package}."
            + (f"\n\nADB: {details}" if details else "")
        )

    activity = ""
    for line in reversed(resolve.stdout.splitlines()):
        line = line.strip()
        if "/" in line and not line.startswith("priority="):
            activity = line
            break

    if not activity:
        raise AdbError(
            f"Android installed {package}, but no launcher activity was found."
        )

    result = run_adb(
        *target,
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        activity,
        timeout=60,
    )

    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )

    if result.returncode != 0:
        raise AdbError(
            f"Android could not start Minecraft ({activity}).\n\n"
            + (output or "adb am start returned a non-zero exit code.")
        )

    if "Error type" in output or "Exception occurred" in output:
        raise AdbError(
            f"Android reported an error while starting Minecraft ({activity}).\n\n"
            + output
        )

    return package
