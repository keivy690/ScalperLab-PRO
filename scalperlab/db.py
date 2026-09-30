from __future__ import annotations

import copy
import json
import sqlite3
import zlib
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .config import database_path


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'description',
                    file_name TEXT,
                    source_code TEXT NOT NULL DEFAULT '',
                    validation_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    published_at TEXT,
                    excerpt TEXT NOT NULL DEFAULT '',
                    fetched_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_feeds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trade_audit (
                    correlation_id TEXT PRIMARY KEY,
                    terminal_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    evidence_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_trade_audit_status_updated
                    ON trade_audit(status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS engine_runtime (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    config_json TEXT NOT NULL DEFAULT '{}',
                    state_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analyst_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    config_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replay_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    terminal_id TEXT NOT NULL,
                    account_fingerprint_sha256 TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    data_sha256 TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    dataset_zlib BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_replay_runs_created
                    ON replay_runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS sr_evaluations (
                    account_sha256 TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    trigger_bar_utc INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY(account_sha256, symbol, rule_version, trigger_bar_utc)
                );
                CREATE INDEX IF NOT EXISTS idx_sr_evaluations_created
                    ON sr_evaluations(created_at DESC);
                CREATE TABLE IF NOT EXISTS sr_data_events (
                    account_sha256 TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    code TEXT NOT NULL,
                    event_bucket_utc INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    PRIMARY KEY(account_sha256, symbol, code, event_bucket_utc)
                );
                CREATE INDEX IF NOT EXISTS idx_sr_data_events_created
                    ON sr_data_events(created_at DESC);
                CREATE TABLE IF NOT EXISTS sr_replay_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    terminal_id TEXT NOT NULL,
                    account_sha256 TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    data_sha256 TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    dataset_zlib BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sr_replay_runs_created
                    ON sr_replay_runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS sr_time_observations (
                    account_sha256 TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    raw_open INTEGER NOT NULL,
                    utc_open INTEGER NOT NULL,
                    offset_seconds INTEGER NOT NULL,
                    observed_tick_utc INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL,
                    PRIMARY KEY(account_sha256, symbol, timeframe)
                );
                CREATE TABLE IF NOT EXISTS sr_verified_bars (
                    account_sha256 TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    utc_open INTEGER NOT NULL,
                    raw_open INTEGER NOT NULL,
                    offset_seconds INTEGER NOT NULL,
                    bar_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    PRIMARY KEY(account_sha256, symbol, timeframe, utc_open)
                );
                CREATE INDEX IF NOT EXISTS idx_sr_verified_bars_lookup
                    ON sr_verified_bars(account_sha256, symbol, timeframe, utc_open DESC);
                CREATE TABLE IF NOT EXISTS sr_order_signals (
                    account_sha256 TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    signal_bar_utc INTEGER NOT NULL,
                    reserved_at TEXT NOT NULL,
                    PRIMARY KEY(account_sha256,symbol,rule_version,strategy,signal_bar_utc)
                );
                CREATE TABLE IF NOT EXISTS sr_raw_time_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_sha256 TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    sample_sha256 TEXT NOT NULL,
                    sample_zlib BLOB NOT NULL
                );
                """
            )

    def archive_sr_time_sample(self, *, account_sha256: str, sample: dict[str, Any],
                               save_diagnostic: bool = False) -> dict[str, Any]:
        """Store confirmed forward bars; never reinterpret older server timestamps."""
        from .mt5_time import MT5_TIMEFRAME_SECONDS
        from .sr_quant.time_archive import canonical_hash, examine_sample

        sample = copy.deepcopy(sample)
        if isinstance(sample.get("account"), dict):
            sample["account"].pop("login", None)
        if isinstance(sample.get("terminal"), dict):
            sample["terminal"].pop("data_path", None)
        symbol = str(sample.get("symbol") or "")
        if len(account_sha256) != 64 or not symbol:
            raise ValueError("Identidade S/R inválida.")
        evidence = examine_sample(sample)
        if not evidence["ok"]:
            if save_diagnostic:
                with self.connect() as connection:
                    connection.execute(
                        """INSERT INTO sr_raw_time_samples
                        (account_sha256,symbol,captured_at,sample_sha256,sample_zlib)
                        VALUES (?,?,?,?,?)""",
                        (account_sha256, symbol, now_iso(), canonical_hash(sample),
                         zlib.compress(json.dumps(sample, ensure_ascii=False,
                                                  sort_keys=True, default=str).encode(), level=6)))
                    connection.execute(
                        """DELETE FROM sr_raw_time_samples WHERE id NOT IN
                        (SELECT id FROM sr_raw_time_samples ORDER BY id DESC LIMIT 60)""")
            return {**evidence, "sample_sha256": canonical_hash(sample)}
        current = now_iso()
        archived = []
        with self.connect() as connection:
            for item in evidence["observations"]:
                frame = item["frame"]
                previous = connection.execute(
                    """SELECT * FROM sr_time_observations WHERE account_sha256=?
                    AND symbol=? AND timeframe=?""",
                    (account_sha256, symbol, frame)).fetchone()
                closed = item["last_closed"]
                raw_closed = int(closed["time"])
                if (previous and raw_closed == previous["raw_open"]
                        and previous["offset_seconds"] == item["offset_seconds"]
                        and (previous["utc_open"] + MT5_TIMEFRAME_SECONDS[frame]
                             <= evidence["tick_utc"])
                        and (previous["observed_tick_utc"]
                             < previous["utc_open"] + MT5_TIMEFRAME_SECONDS[frame])):
                    bar = {**closed, "raw_time": raw_closed,
                           "time": previous["utc_open"]}
                    prior_evidence = json.loads(previous["evidence_json"])
                    proof = {"version": evidence["version"],
                             "forming": prior_evidence,
                             "closed_sample_sha256": evidence["sample_sha256"],
                             "closed_tick_utc": evidence["tick_utc"]}
                    existing = connection.execute(
                        """SELECT bar_json FROM sr_verified_bars WHERE account_sha256=?
                        AND symbol=? AND timeframe=? AND utc_open=?""",
                        (account_sha256, symbol, frame, previous["utc_open"])).fetchone()
                    encoded = json.dumps(bar, sort_keys=True, separators=(",", ":"))
                    if existing and existing["bar_json"] != encoded:
                        raise ValueError("Candles MT5 conflitantes; arquivo S/R preservado.")
                    connection.execute(
                        """INSERT OR IGNORE INTO sr_verified_bars
                        (account_sha256,symbol,timeframe,utc_open,raw_open,offset_seconds,
                         bar_json,evidence_json,archived_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                        (account_sha256, symbol, frame, previous["utc_open"], raw_closed,
                         item["offset_seconds"], encoded,
                         json.dumps(proof, sort_keys=True), current))
                    archived.append(frame)
                forming_proof = {"sample_sha256": evidence["sample_sha256"],
                                 "tick_utc": evidence["tick_utc"],
                                 "m1_open_raw": evidence["m1_open_raw"],
                                 "clock_offset_seconds": evidence["clock_offset_seconds"],
                                 "bar_offset_seconds": item["offset_seconds"],
                                 "terminal_build": (sample.get("terminal") or {}).get("build"),
                                 "captured_utc": sample.get("captured_utc")}
                connection.execute(
                    """INSERT INTO sr_time_observations
                    (account_sha256,symbol,timeframe,raw_open,utc_open,offset_seconds,
                     observed_tick_utc,evidence_json) VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(account_sha256,symbol,timeframe) DO UPDATE SET
                    raw_open=excluded.raw_open, utc_open=excluded.utc_open,
                    offset_seconds=excluded.offset_seconds,
                    observed_tick_utc=excluded.observed_tick_utc,
                    evidence_json=excluded.evidence_json""",
                    (account_sha256, symbol, frame, item["raw_open"], item["utc_open"],
                     item["offset_seconds"], evidence["tick_utc"],
                     json.dumps(forming_proof, sort_keys=True)))
            if save_diagnostic:
                packed = zlib.compress(json.dumps(sample, ensure_ascii=False,
                                                   sort_keys=True, default=str).encode(), level=6)
                connection.execute(
                    """INSERT INTO sr_raw_time_samples
                    (account_sha256,symbol,captured_at,sample_sha256,sample_zlib)
                    VALUES (?,?,?,?,?)""",
                    (account_sha256, symbol, current, evidence["sample_sha256"], packed))
                connection.execute(
                    """DELETE FROM sr_raw_time_samples WHERE id NOT IN
                    (SELECT id FROM sr_raw_time_samples ORDER BY id DESC LIMIT 60)""")
        return {"ok": True, "symbol": symbol, "sample_sha256": evidence["sample_sha256"],
                "bar_offset_seconds": evidence["bar_offset_seconds"],
                "archived_frames": archived}

    def sr_time_archive_status(self, *, account_sha256: str, symbol: str) -> dict[str, Any]:
        with self.connect() as connection:
            bars = connection.execute(
                """SELECT timeframe, COUNT(*) AS count, MIN(utc_open) AS first_utc,
                MAX(utc_open) AS last_utc FROM sr_verified_bars
                WHERE account_sha256=? AND symbol=? GROUP BY timeframe""",
                (account_sha256, symbol)).fetchall()
            samples = connection.execute(
                """SELECT id,captured_at,sample_sha256 FROM sr_raw_time_samples
                WHERE account_sha256=? AND symbol=? ORDER BY id DESC LIMIT 10""",
                (account_sha256, symbol)).fetchall()
        return {"bars": [dict(row) for row in bars],
                "diagnostic_samples": [dict(row) for row in samples]}

    def audit_sr_time_sample(self, *, account_sha256: str,
                             sample: dict[str, Any]) -> dict[str, Any]:
        """Compare archived recent bars with broker-raw rates; no conversion inferred."""
        symbol = str(sample.get("symbol") or "")
        if len(account_sha256) != 64 or not symbol:
            raise ValueError("Identidade S/R inválida.")
        report = {}
        with self.connect() as connection:
            for frame in ("M5", "M15", "H1"):
                raw = {int(row["time"]): row
                       for row in sample["frames"][frame]["closed"]}
                if not raw:
                    report[frame] = {"matched": 0, "missing": 0, "conflicts": 0}
                    continue
                rows = connection.execute(
                    """SELECT raw_open,bar_json FROM sr_verified_bars WHERE
                    account_sha256=? AND symbol=? AND timeframe=? AND raw_open BETWEEN ? AND ?""",
                    (account_sha256, symbol, frame, min(raw), max(raw))).fetchall()
                matched = 0
                conflicts = 0
                for row in rows:
                    broker = raw.get(row["raw_open"])
                    if broker is None:
                        continue
                    saved = json.loads(row["bar_json"])
                    if all(saved.get(key) == broker.get(key)
                           for key in ("open", "high", "low", "close", "tick_volume", "spread")):
                        matched += 1
                    else:
                        conflicts += 1
                report[frame] = {"matched": matched, "missing": len(raw) - matched - conflicts,
                                 "conflicts": conflicts}
        return report

    def save_sr_evaluation(self, *, account_sha256: str, result: dict[str, Any]) -> None:
        """Persist one research decision per closed M5 bar; never stores a login."""
        symbol = str(result["symbol"])
        trigger = int(result["frame_last_closed"]["M5"])
        version = str(result["version"])
        if len(account_sha256) != 64 or trigger <= 0 or not symbol or not version:
            raise ValueError("Identidade ou resultado de pesquisa inválido.")
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO sr_evaluations
                (account_sha256, symbol, rule_version, trigger_bar_utc,
                 created_at, status, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_sha256, symbol, rule_version, trigger_bar_utc)
                DO NOTHING""",
                (account_sha256, symbol, version, trigger, now_iso(),
                 str(result.get("status") or "UNKNOWN"), payload),
            )
            connection.execute(
                """DELETE FROM sr_evaluations WHERE rowid NOT IN
                (SELECT rowid FROM sr_evaluations ORDER BY created_at DESC LIMIT 20000)"""
            )

    def reserve_sr_order_signal(self, *, account_sha256: str, symbol: str,
                                rule_version: str, strategy: str,
                                signal_bar_utc: int) -> bool:
        """At most one DEMO intent per setup and closed candle, across restarts."""
        if (len(account_sha256) != 64 or not symbol or not rule_version
                or not strategy or int(signal_bar_utc) <= 0):
            raise ValueError("Identidade do sinal S/R inválida.")
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO sr_order_signals
                (account_sha256,symbol,rule_version,strategy,signal_bar_utc,reserved_at)
                VALUES (?,?,?,?,?,?)""",
                (account_sha256, symbol, rule_version, strategy,
                 int(signal_bar_utc), now_iso()))
        return cursor.rowcount == 1

    def save_sr_data_event(self, *, account_sha256: str, symbol: str,
                           code: str, detail: str) -> None:
        """Keep one diagnostic per reason and five-minute bucket."""
        if len(account_sha256) != 64 or not symbol or not code:
            raise ValueError("Evento de qualidade S/R inválido.")
        bucket = int(datetime.now(UTC).timestamp()) // 300 * 300
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO sr_data_events
                (account_sha256, symbol, code, event_bucket_utc, created_at, detail)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_sha256, symbol, code, event_bucket_utc) DO NOTHING""",
                (account_sha256, symbol[:64], code[:80], bucket, now_iso(), detail[:500]),
            )
            connection.execute(
                """DELETE FROM sr_data_events WHERE rowid NOT IN
                (SELECT rowid FROM sr_data_events ORDER BY created_at DESC LIMIT 5000)"""
            )

    def list_sr_data_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT symbol, code, event_bucket_utc, created_at, detail
                FROM sr_data_events ORDER BY created_at DESC LIMIT ?""",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sr_evaluations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT created_at, symbol, rule_version, trigger_bar_utc,
                status, result_json FROM sr_evaluations
                ORDER BY created_at DESC, trigger_bar_utc DESC LIMIT ?""",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [{**dict(row), "result": json.loads(row["result_json"])}
                for row in rows]

    def save_sr_replay_run(self, *, run_id: str, terminal_id: str,
                           account_sha256: str, symbol: str, result: dict[str, Any],
                           dataset: dict[str, Any]) -> None:
        packed = zlib.compress(json.dumps(dataset, ensure_ascii=False,
                                           sort_keys=True, separators=(",", ":"),
                                           default=str).encode(), level=9)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO sr_replay_runs
                (run_id, created_at, terminal_id, account_sha256, symbol,
                 data_sha256, parameters_json, result_json, dataset_zlib)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, now_iso(), terminal_id, account_sha256, symbol,
                 result["data_sha256"],
                 json.dumps(result["parameters"], ensure_ascii=False, default=str),
                 json.dumps(result, ensure_ascii=False, default=str), packed),
            )
            connection.execute(
                """DELETE FROM sr_replay_runs WHERE run_id NOT IN
                (SELECT run_id FROM sr_replay_runs ORDER BY created_at DESC LIMIT 30)"""
            )

    def list_sr_replay_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT run_id, created_at, terminal_id, symbol, data_sha256
                FROM sr_replay_runs ORDER BY created_at DESC LIMIT ?""",
                (max(1, min(int(limit), 30)),),
            ).fetchall()
        return [{key: row[key] for key in ("run_id", "created_at", "terminal_id",
                                         "symbol", "data_sha256")} for row in rows]

    def get_sr_replay_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT run_id, created_at, terminal_id, symbol, data_sha256,
                parameters_json, result_json, dataset_zlib FROM sr_replay_runs
                WHERE run_id = ?""", (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {"run_id": row["run_id"], "created_at": row["created_at"],
                "terminal_id": row["terminal_id"], "symbol": row["symbol"],
                "data_sha256": row["data_sha256"],
                "parameters": json.loads(row["parameters_json"]),
                "result": json.loads(row["result_json"]),
                "dataset": json.loads(zlib.decompress(row["dataset_zlib"]))}

    def save_replay_run(self, *, run_id: str, terminal_id: str,
                        account_fingerprint_sha256: str, symbol: str,
                        timeframe: str, data_sha256: str,
                        parameters: dict[str, Any], result: dict[str, Any],
                        dataset: dict[str, Any]) -> None:
        packed = zlib.compress(json.dumps(
            dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8"), level=9)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO replay_runs
                (run_id, created_at, terminal_id, account_fingerprint_sha256,
                 symbol, timeframe, data_sha256, parameters_json, result_json, dataset_zlib)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, now_iso(), terminal_id, account_fingerprint_sha256,
                 symbol, timeframe, data_sha256,
                 json.dumps(parameters, ensure_ascii=False, default=str),
                 json.dumps(result, ensure_ascii=False, default=str), packed),
            )
            connection.execute(
                """DELETE FROM replay_runs WHERE run_id NOT IN
                (SELECT run_id FROM replay_runs ORDER BY created_at DESC LIMIT 50)"""
            )

    def list_replay_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT run_id, created_at, terminal_id, account_fingerprint_sha256,
                symbol, timeframe, data_sha256, parameters_json, result_json
                FROM replay_runs ORDER BY created_at DESC LIMIT ?""",
                (max(1, min(limit, 50)),),
            ).fetchall()
        return [self._replay_run(row) for row in rows]

    def get_replay_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM replay_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if not row:
            return None
        item = self._replay_run(row)
        item["dataset"] = json.loads(zlib.decompress(row["dataset_zlib"]).decode("utf-8"))
        return item

    @staticmethod
    def _replay_run(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item.pop("dataset_zlib", None)
        item["parameters"] = json.loads(item.pop("parameters_json"))
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def get_analyst_profile(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT config_json FROM analyst_profile WHERE id = 1").fetchone()
        return json.loads(row["config_json"]) if row else {}

    def save_analyst_profile(self, config: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO analyst_profile(id, config_json, updated_at) VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET config_json = excluded.config_json,
                updated_at = excluded.updated_at""",
                (json.dumps(config), now_iso()),
            )

    def get_engine_runtime(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM engine_runtime WHERE id = 1").fetchone()
        if not row:
            return {"config": {}, "state": {}}
        return {"config": json.loads(row["config_json"]), "state": json.loads(row["state_json"])}

    def save_engine_runtime(self, config: dict[str, Any], state: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO engine_runtime(id, config_json, state_json, updated_at)
                VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
                config_json = excluded.config_json, state_json = excluded.state_json,
                updated_at = excluded.updated_at""",
                (json.dumps(config), json.dumps(state), now_iso()),
            )

    def create_strategy(
        self,
        *,
        name: str,
        description: str,
        source_type: str = "description",
        file_name: str | None = None,
        source_code: str = "",
        validation: dict[str, Any] | None = None,
        status: str = "draft",
    ) -> dict[str, Any]:
        stamp = now_iso()
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO strategies
                (name, description, source_type, file_name, source_code, validation_json,
                 status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, description, source_type, file_name, source_code,
                 json.dumps(validation or {}), status, stamp, stamp),
            )
            row = connection.execute(
                "SELECT * FROM strategies WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._strategy(row)

    def list_strategies(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM strategies ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [self._strategy(row) for row in rows]

    def get_strategy(self, strategy_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategies WHERE id = ?", (strategy_id,)
            ).fetchone()
        return self._strategy(row) if row else None

    def get_strategy_source(self, strategy_id: int) -> dict[str, str] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT file_name, source_code FROM strategies WHERE id = ?", (strategy_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_strategy_status(self, strategy_id: int, status: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE strategies SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), strategy_id),
            )
        return self.get_strategy(strategy_id)

    def save_research_items(self, items: list[dict[str, Any]]) -> int:
        stored = 0
        with self.connect() as connection:
            for item in items:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO research_items
                    (title, url, source, published_at, excerpt, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (item["title"][:300], item["url"][:2000], item["source"][:100],
                     item.get("published_at"), item.get("excerpt", "")[:4000], now_iso()),
                )
                stored += cursor.rowcount
        return stored

    def list_research_items(self, limit: int = 60) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_items ORDER BY fetched_at DESC, id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_feed(self, url: str, label: str) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO research_feeds(url, label, created_at) VALUES (?, ?, ?)",
                (url, label, now_iso()),
            )
            row = connection.execute(
                "SELECT * FROM research_feeds WHERE url = ?", (url,)
            ).fetchone()
        return dict(row)

    def list_feeds(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_feeds ORDER BY label COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_log(self, level: str, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO activity_log(level, message, created_at) VALUES (?, ?, ?)",
                (level[:12], message[:500], now_iso()),
            )

    def list_logs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_trade_audit(self, *, correlation_id: str, terminal_id: str, method: str,
                           started_at: str, request: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO trade_audit
                (correlation_id, terminal_id, method, status, started_at, updated_at, request_json)
                VALUES (?, ?, ?, 'prepared', ?, ?, ?)""",
                (correlation_id, terminal_id, method, started_at, now_iso(),
                 json.dumps(request, ensure_ascii=False, default=str)),
            )

    def update_trade_audit(self, correlation_id: str, *, status: str,
                           result: dict[str, Any] | None = None,
                           evidence: dict[str, Any] | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE trade_audit SET status = ?, updated_at = ?,
                result_json = COALESCE(?, result_json),
                evidence_json = COALESCE(?, evidence_json)
                WHERE correlation_id = ?""",
                (status, now_iso(),
                 json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                 json.dumps(evidence, ensure_ascii=False, default=str) if evidence is not None else None,
                 correlation_id),
            )

    def get_trade_audit(self, correlation_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM trade_audit WHERE correlation_id = ?", (correlation_id,)
            ).fetchone()
        return self._trade_audit(row) if row else None

    def list_trade_audit(self, *, limit: int = 100,
                         statuses: set[str] | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                rows = connection.execute(
                    f"SELECT * FROM trade_audit WHERE status IN ({placeholders}) "
                    "ORDER BY started_at DESC LIMIT ?",
                    (*sorted(statuses), max(1, min(limit, 500))),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM trade_audit ORDER BY started_at DESC LIMIT ?",
                    (max(1, min(limit, 500)),),
                ).fetchall()
        return [self._trade_audit(row) for row in rows]

    @staticmethod
    def _trade_audit(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["request"] = json.loads(item.pop("request_json"))
        item["result"] = json.loads(item.pop("result_json"))
        item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    @staticmethod
    def _strategy(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["validation"] = json.loads(item.pop("validation_json"))
        item.pop("source_code", None)
        return item
