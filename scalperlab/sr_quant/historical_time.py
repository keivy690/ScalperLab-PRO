"""Versioned, research-only conversion of documented broker history.

There is deliberately no bundled policy for any broker. A current offset cannot
establish a historical DST schedule. The caller must supply dated independent
anchors on both sides of each claimed transition.
"""
from __future__ import annotations

import re
from typing import Any


class HistoricalTimeUnverified(ValueError):
    pass


def convert_documented_history(rows: list[dict[str, Any]], *, server: str,
                               policy: dict[str, Any]) -> list[dict[str, Any]]:
    if (policy.get("version") != "sr-broker-history-v1"
            or policy.get("server") != server or not server
            or not policy.get("source_url")
            or not re.fullmatch(r"[0-9a-f]{64}", str(policy.get("source_sha256", "")))):
        raise HistoricalTimeUnverified("Regra versionada e fonte específica do servidor ausentes.")
    intervals = policy.get("intervals") or []
    if not isinstance(intervals, list) or not intervals:
        raise HistoricalTimeUnverified("Intervalos históricos documentados ausentes.")
    clean = []
    for interval in intervals:
        try:
            begin, end = int(interval["start_utc"]), int(interval["end_utc"])
            offset = int(interval["offset_seconds"])
        except (KeyError, ValueError, TypeError) as exc:
            raise HistoricalTimeUnverified("Intervalo histórico inválido.") from exc
        if begin >= end or abs(offset) > 14 * 3600 or offset % 900:
            raise HistoricalTimeUnverified("Limites ou offset histórico inválidos.")
        clean.append((begin, end, offset))
    clean.sort()
    if any(a[1] > b[0] for a, b in zip(clean, clean[1:], strict=False)):
        raise HistoricalTimeUnverified("Intervalos históricos UTC sobrepostos.")
    anchors = policy.get("anchors") or []
    if not isinstance(anchors, list):
        raise HistoricalTimeUnverified("Âncoras históricas inválidas.")
    try:
        anchors = [{"raw": int(anchor["raw_time"]), "utc": int(anchor["utc_time"]),
                    "source": anchor["source"], "evidence": anchor["evidence_url"]}
                   for anchor in anchors]
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalTimeUnverified("Âncoras históricas inválidas.") from exc
    for begin, end, offset in clean:
        if not any(anchor["source"] == "independent_utc_evidence"
                   and str(anchor["evidence"]).startswith("https://")
                   and anchor["raw"] == anchor["utc"] + offset
                   and begin <= anchor["utc"] < end
                   for anchor in anchors):
            raise HistoricalTimeUnverified("Falta âncora UTC independente para um intervalo.")
    for left, right in zip(clean, clean[1:], strict=False):
        if left[1] != right[0]:
            continue
        boundary = left[1]
        if not any(a["raw"] == a["utc"] + left[2]
                   and boundary - 7 * 86400 <= a["utc"] < boundary for a in anchors):
            raise HistoricalTimeUnverified("Falta evidência anterior à transição sazonal.")
        if not any(a["raw"] == a["utc"] + right[2]
                   and boundary <= a["utc"] < boundary + 7 * 86400 for a in anchors):
            raise HistoricalTimeUnverified("Falta evidência posterior à transição sazonal.")
    converted = []
    for row in rows:
        raw = int(row["time"])
        candidates = [raw - offset for begin, end, offset in clean
                      if begin <= raw - offset < end]
        if len(candidates) != 1:
            raise HistoricalTimeUnverified(
                "Candle fora da regra ou ambíguo na transição sazonal.")
        converted.append({**row, "raw_time": raw, "time": candidates[0]})
    if any(a["time"] >= b["time"]
           for a, b in zip(converted, converted[1:], strict=False)):
        raise HistoricalTimeUnverified("Sequência UTC convertida duplicada ou invertida.")
    return converted
