from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AdbError(RuntimeError):
    pass


def find_adb() -> Path | None:
    candidates = [
        shutil.which("adb"),
        Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
    ]

    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path

    return None


def run_adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    adb = find_adb()
    if adb is None:
        raise AdbError(
            "ADB was not found. Install Android SDK Platform-Tools or configure an Android runtime."
        )

    return subprocess.run(
        [str(adb), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def devices() -> list[str]:
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
    args = ["-s", device, "install", "-r", str(apk)] if device else ["install", "-r", str(apk)]
    result = run_adb(*args, timeout=180)
    if result.returncode != 0:
        raise AdbError(result.stderr.strip() or result.stdout.strip() or "APK installation failed.")
