from __future__ import annotations

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
                """
            )

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
