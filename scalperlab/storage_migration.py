"""Explicit, offline migration; legacy stores remain intact for rollback."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from pathlib import Path

from .database_backup import _snapshot
from .single_instance import SingleInstanceLock


def inventory(root: Path) -> dict:
    path = root / "scalperlab.sqlite3"
    result = {"root": str(root), "tables": {}, "files": {}}
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(f"Banco inválido: {path}")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError(f"Referências inválidas no banco: {path}")
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                name = '"' + table.replace('"', '""') + '"'
                rows = db.execute(f"SELECT * FROM {name}").fetchall()
                digest = hashlib.sha256(repr(sorted(rows, key=repr)).encode()).hexdigest()
                result["tables"][table] = {"rows": len(rows), "sha256": digest}
    terminals = root / "terminals.json"
    if terminals.is_file():
        # Parse configuration before publishing it, while preserving original bytes.
        rows = json.loads(terminals.read_text(encoding="utf-8-sig"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("terminal_id") for row in rows):
            raise ValueError("Configuração de terminais inválida.")
        result["files"]["terminals.json"] = hashlib.sha256(terminals.read_bytes()).hexdigest()
    return result


def migrate_storage(source: Path, destination: Path, backup_root: Path,
                    other_legacy: list[Path] | None = None) -> dict:
    source, destination, backup_root = (p.resolve() for p in (source, destination, backup_root))
    if destination.exists():
        raise ValueError("Destino já existe; compare os dados antes de qualquer substituição.")
    if not (source / "scalperlab.sqlite3").is_file():
        raise ValueError("Banco de origem não encontrado.")
    if source == destination or destination.is_relative_to(source) or backup_root.is_relative_to(source):
        raise ValueError("Origem, destino e backup devem ser independentes.")
    roots = list(dict.fromkeys([source] + [p.resolve() for p in (other_legacy or []) if p.exists()]))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup = backup_root / stamp
    staging = destination.with_name(destination.name + ".migration-" + uuid.uuid4().hex[:8])
    with ExitStack() as stack:
        for root in roots:
            lock = SingleInstanceLock(root / "scalperlab.instance.lock")
            if not lock.acquire():
                raise ValueError("Feche todas as instâncias do ScalperLab antes da migração.")
            stack.callback(lock.release)
        inventories = [inventory(root) for root in roots]
        # Legacy alternatives may hold diagnostic logs, but never silently choose
        # between conflicting strategies/profiles/orders/research/configuration.
        baseline = inventories[0]
        for other in inventories[1:]:
            for table, record in other["tables"].items():
                if table not in {"activity_log", "engine_runtime", "sqlite_sequence"} and record["rows"]:
                    if record != baseline["tables"].get(table):
                        raise ValueError(f"Dados divergentes em {table}; migração exige conciliação.")
            if other["files"] and other["files"] != baseline["files"]:
                raise ValueError("Configurações de terminal divergentes; migração exige conciliação.")
        backup.mkdir(parents=True, exist_ok=False)
        for index, root in enumerate(roots):
            copy = backup / f"legacy-{index}"
            copy.mkdir()
            if (root / "scalperlab.sqlite3").is_file():
                _snapshot(root / "scalperlab.sqlite3", copy / "scalperlab.sqlite3")
            if (root / "terminals.json").is_file():
                shutil.copy2(root / "terminals.json", copy / "terminals.json")
        staging.mkdir(parents=True, exist_ok=False)
        _snapshot(source / "scalperlab.sqlite3", staging / "scalperlab.sqlite3")
        if (source / "terminals.json").is_file():
            shutil.copy2(source / "terminals.json", staging / "terminals.json")
        with closing(sqlite3.connect(staging / "scalperlab.sqlite3")) as db:
            if "engine_runtime" in baseline["tables"]:
                for row_id, raw in db.execute("SELECT id, state_json FROM engine_runtime").fetchall():
                    state = json.loads(raw)
                    state.update(running=False, mode="parado", phase="parado", started_at=None,
                                 detail="Dados migrados; execução exige início manual e nova validação UTC.")
                    db.execute("UPDATE engine_runtime SET state_json=? WHERE id=?",
                               (json.dumps(state), row_id))
                db.commit()
        after = inventory(staging)
        for table, value in baseline["tables"].items():
            if table != "engine_runtime" and after["tables"].get(table) != value:
                raise RuntimeError(f"Verificação após cópia falhou: {table}. Originais preservados.")
        if baseline["files"] != after["files"]:
            raise RuntimeError("A configuração de terminais mudou durante a cópia.")
        if inventory(source) != baseline:
            raise RuntimeError("A origem foi alterada durante a migração; originais preservados.")
        report = {"schema": 1, "created_at": stamp, "sources": inventories,
                  "destination": str(destination), "backup": str(backup),
                  "verified_tables": after["tables"], "execution_restored": False}
        for folder in (backup, staging):
            (folder / "migration-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        # Atomic publication into an absent destination; never replace a live store.
        staging.rename(destination)
        return report
