from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class AdbError(RuntimeError):
    pass


def find_adb() -> Path | None:
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

    return None


def run_adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    adb = find_adb()
    if adb is None:
        raise AdbError(
            "ADB was not found. Install Android SDK Platform-Tools and make sure "
            "an Android emulator/device with USB debugging is running."
        )

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
    """Read the package name with Android SDK's aapt executable."""
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
            aapt_candidates.extend(sorted(build_tools.glob("*/aapt.exe"), reverse=True))

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
        "Could not determine the APK package name. Install Android SDK Build-Tools "
        "so the launcher can inspect the APK."
    )


def launch(apk: Path, device: str | None = None) -> str:
    package = package_name_from_apk(apk)

    args = []
    if device:
        args.extend(["-s", device])
    args.extend(["shell", "monkey", "-p", package, "1"])

    result = run_adb(*args, timeout=30)
    if result.returncode != 0:
        raise AdbError(
            result.stderr.strip() or result.stdout.strip() or
            f"Could not launch Android package {package}."
        )

    return package
