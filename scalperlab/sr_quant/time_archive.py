"""Evidence-first MT5 bar archive for S/R research only.

This module never changes the live trading timestamp adapter. A bar is archived
only after its forming timestamp was observed against a validated UTC tick and
the same raw timestamp later appears as a closed bar.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..mt5_time import MT5_TIMEFRAME_SECONDS

FRAMES = ("M5", "M15", "H1")
ARCHIVE_VERSION = "sr-forward-time-v1"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def examine_sample(sample: dict[str, Any]) -> dict[str, Any]:
    if not sample.get("ok"):
        return {"ok": False, "code": "sample_unavailable"}
    tick = sample.get("tick") or {}
    time_info = tick.get("time_normalization") or {}
    if not tick.get("ok") or time_info.get("basis") != "UTC":
        return {"ok": False, "code": "tick_utc_unverified"}
    try:
        tick_utc = int(tick["time"])
        clock_offset = int(time_info["server_utc_offset_seconds"])
        m1_open = int(sample["frames"]["M1"]["forming"]["time"])
        candidates = {offset for offset in (0, clock_offset)
                      if 0 <= tick_utc - (m1_open - offset) < 60}
        if len(candidates) != 1:
            return {"ok": False, "code": "m1_anchor_ambiguous"}
        applied = candidates.pop()
        observations = []
        for frame in FRAMES:
            period = MT5_TIMEFRAME_SECONDS[frame]
            forming = sample["frames"][frame]["forming"]
            raw_open = int(forming["time"])
            utc_open = raw_open - applied
            if not 0 <= tick_utc - utc_open < period:
                return {"ok": False, "code": f"{frame.lower()}_anchor_invalid"}
            closed = sample["frames"][frame]["closed"]
            if not closed or int(closed[-1]["time"]) >= raw_open:
                return {"ok": False, "code": f"{frame.lower()}_closed_invalid"}
            observations.append({"frame": frame, "raw_open": raw_open,
                                 "utc_open": utc_open, "offset_seconds": applied,
                                 "forming": forming, "last_closed": closed[-1]})
    except (KeyError, ValueError, TypeError, OverflowError):
        return {"ok": False, "code": "sample_malformed"}
    return {"ok": True, "version": ARCHIVE_VERSION,
            "tick_utc": tick_utc, "m1_open_raw": m1_open,
            "clock_offset_seconds": clock_offset, "bar_offset_seconds": applied,
            "sample_sha256": canonical_hash(sample),
            "observations": observations}
