import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scalperlab.config import data_directory
from scalperlab.db import Database
from scalperlab.storage_migration import inventory, migrate_storage
from scalperlab.single_instance import SingleInstanceLock


class StorageMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.target = self.root / "destination"
        self.backup = self.root / "backup"
        self.db = Database(self.source / "scalperlab.sqlite3")
        self.db.save_analyst_profile({"symbols": ["BTCUSD#"], "timeframe": "M2"})
        self.db.save_engine_runtime({}, {"running": True, "mode": "real", "phase": "executando"})
        (self.source / "terminals.json").write_text('[{"terminal_id":"default"}]', encoding="utf-8")

    def test_preserves_data_and_backup_but_not_execution(self):
        before = inventory(self.source)
        report = migrate_storage(self.source, self.target, self.backup)
        self.assertEqual(inventory(self.source), before)
        after = inventory(self.target)
        self.assertEqual(after["tables"]["analyst_profile"], before["tables"]["analyst_profile"])
        self.assertEqual(after["files"], before["files"])
        migrated = Database(self.target / "scalperlab.sqlite3")
        self.assertFalse(migrated.get_engine_runtime()["state"]["running"])
        self.assertEqual(migrated.get_engine_runtime()["state"]["mode"], "parado")
        self.assertTrue((Path(report["backup"]) / "legacy-0/scalperlab.sqlite3").is_file())

    def test_existing_destination_is_never_overwritten(self):
        self.target.mkdir()
        (self.target / "sentinel").write_text("keep")
        with self.assertRaisesRegex(ValueError, "Destino já existe"):
            migrate_storage(self.source, self.target, self.backup)
        self.assertEqual((self.target / "sentinel").read_text(), "keep")

    def test_active_source_refuses_migration(self):
        lock = SingleInstanceLock(self.source / "scalperlab.instance.lock")
        self.assertTrue(lock.acquire())
        try:
            with self.assertRaisesRegex(ValueError, "Feche todas"):
                migrate_storage(self.source, self.target, self.backup)
        finally:
            lock.release()
        self.assertFalse(self.target.exists())

    def test_conflicting_profiles_require_reconciliation(self):
        alternative = self.root / "alternative"
        alternative.mkdir()
        other = Database(alternative / "scalperlab.sqlite3")
        other.save_analyst_profile({"symbols": ["OTHER"]})
        with self.assertRaisesRegex(ValueError, "Dados divergentes"):
            migrate_storage(self.source, self.target, self.backup, [alternative])
        self.assertFalse(self.target.exists())

    def test_empty_alternative_is_backed_up(self):
        alternative = self.root / "alternative"
        alternative.mkdir()
        Database(alternative / "scalperlab.sqlite3").add_log("INFO", "pilot")
        report = migrate_storage(self.source, self.target, self.backup, [alternative])
        self.assertTrue((Path(report["backup"]) / "legacy-1/scalperlab.sqlite3").is_file())

    def test_explicit_storage_ignores_store_localappdata_redirect(self):
        with patch.dict(os.environ, {"SCALPERLAB_DATA_DIR": str(self.target), "LOCALAPPDATA": "wrong"}):
            self.assertEqual(data_directory(), self.target)


if __name__ == "__main__":
    unittest.main()
