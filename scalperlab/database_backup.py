from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .config import database_path


def _integrity_check(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"Verificação de integridade falhou para {path.name}.")


def _snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source, timeout=10)) as source_db, closing(
        sqlite3.connect(destination)
    ) as backup_db:
        source_db.backup(backup_db)
        backup_db.commit()
    _integrity_check(destination)


def create_backup() -> Path:
    source = database_path()
    if not source.is_file():
        raise FileNotFoundError("Banco local ainda não foi criado.")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = source.parent / "backups" / f"scalperlab-{stamp}.sqlite3"
    _snapshot(source, destination)
    return destination


def restore_backup(backup: Path) -> Path:
    source = backup.expanduser().resolve(strict=True)
    target = database_path().resolve()
    if source == target or not source.is_file():
        raise ValueError("Selecione um arquivo de backup diferente do banco ativo.")
    _integrity_check(source)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safety_copy = target.parent / "backups" / f"before-restore-{stamp}.sqlite3"
    if target.exists():
        _snapshot(target, safety_copy)
    temporary = target.with_name(target.name + ".restore.tmp")
    try:
        _snapshot(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return safety_copy


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cópia e restauração verificadas do banco ScalperLab."
    )
    parser.add_argument(
        "--restore", type=Path,
        help="Arquivo de backup a restaurar (feche antes o ScalperLab).",
    )
    arguments = parser.parse_args()
    if arguments.restore:
        phrase = input("Feche o ScalperLab e digite RESTAURAR BANCO LOCAL para continuar: ").strip()
        if phrase != "RESTAURAR BANCO LOCAL":
            print("Restauração cancelada.")
            return 2
        safety_copy = restore_backup(arguments.restore)
        print("Backup restaurado e validado.")
        if safety_copy.exists():
            print(f"Cópia de segurança anterior: {safety_copy}")
        return 0
    backup = create_backup()
    print(f"Backup verificado: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
