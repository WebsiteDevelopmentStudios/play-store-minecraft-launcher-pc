from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApkInfo:
    path: Path
    size: int
    sha256: str
    has_android_manifest: bool


def inspect_apk(path: str | Path) -> ApkInfo:
    apk = Path(path)

    if not apk.is_file():
        raise FileNotFoundError(f"APK not found: {apk}")

    if apk.suffix.lower() != ".apk":
        raise ValueError("The selected file is not an APK.")

    digest = hashlib.sha256()
    with apk.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    try:
        with zipfile.ZipFile(apk) as archive:
            has_manifest = "AndroidManifest.xml" in archive.namelist()
    except zipfile.BadZipFile as exc:
        raise ValueError("The selected APK is not a valid Android package archive.") from exc

    if not has_manifest:
        raise ValueError("The APK does not contain AndroidManifest.xml.")

    return ApkInfo(
        path=apk,
        size=apk.stat().st_size,
        sha256=digest.hexdigest(),
        has_android_manifest=True,
    )
