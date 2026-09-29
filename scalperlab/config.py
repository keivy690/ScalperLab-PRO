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
    """Use the same explicit directory in Store Python and the frozen executable.

    LOCALAPPDATA is virtualized by Store Python. A directory directly under the
    user profile avoids silently creating a second database in the executable.
    """
    explicit = os.environ.get("SCALPERLAB_DATA_DIR")
    directory = (Path(explicit).expanduser() if explicit else
                 Path(os.environ.get("USERPROFILE") or Path.home()) / "ScalperLabData")
    if not directory.is_absolute():
        raise ValueError("SCALPERLAB_DATA_DIR deve ser um caminho absoluto.")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def database_path() -> Path:
    return data_directory() / "scalperlab.sqlite3"
