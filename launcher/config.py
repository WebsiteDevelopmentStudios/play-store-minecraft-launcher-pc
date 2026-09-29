from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "Blemm Bedrock Launcher"
APP_VERSION = "0.1.0"

ROOT_DIR = Path(os.environ.get("BLEMM_BEDROCK_DIR", Path.home() / "BlemmBedrock"))
APK_DIR = ROOT_DIR / "apks"
INSTANCES_DIR = ROOT_DIR / "instances"
RUNTIME_DIR = ROOT_DIR / "runtime"
LOG_DIR = ROOT_DIR / "logs"

for directory in (ROOT_DIR, APK_DIR, INSTANCES_DIR, RUNTIME_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)
