from __future__ import annotations

import os
import re
from pathlib import Path

APP_NAME = "ScalperLab"
MAX_IMPORT_BYTES = 1_000_000
HTTP_TIMEOUT_SECONDS = 8
MAX_HTTP_BYTES = 2_000_000
MAX_SEARCH_RESULTS = 12
MAX_RESEARCH_FEEDS = 12
RESEARCH_TOTAL_TIMEOUT_SECONDS = 35
MAX_REQUEST_BYTES = 3_000_000
ALLOWED_STRATEGY_EXTENSIONS = {".mq5", ".py", ".txt"}
MT5_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._#-]{0,31}$")


def data_directory() -> Path:
    """Return per-user storage outside the installed application directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    directory = base / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def database_path() -> Path:
    return data_directory() / "scalperlab.sqlite3"
