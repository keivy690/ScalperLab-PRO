from __future__ import annotations

import os
from pathlib import Path


def discover_mt5_terminals() -> list[Path]:
    """Find likely terminal executables without launching or modifying them."""
    candidates: set[Path] = set()
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    for root in filter(None, roots):
        base = Path(root)
        candidates.update(base.glob("MetaTrader 5/terminal64.exe"))
        candidates.update(base.glob("MetaTrader 5*/terminal64.exe"))
        candidates.update(base.glob("*/terminal64.exe"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.update(Path(local).glob("Programs/*/terminal64.exe"))
    return sorted((path.resolve() for path in candidates if path.is_file()), key=str.casefold)
