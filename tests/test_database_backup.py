import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scalperlab.database_backup import _integrity_check, _snapshot, restore_backup


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "scalperlab.sqlite3"
        self.backup = self.root / "backup.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _make_database(path: Path, table: str, value: str) -> None:
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(f"CREATE TABLE {table} (value TEXT NOT NULL)")
            connection.execute(f"INSERT INTO {table} VALUES (?)", (value,))
            connection.commit()

    def test_snapshot_is_consistent_and_passes_integrity_check(self):
        self._make_database(self.database, "sample", "kept")
        _snapshot(self.database, self.backup)
        _integrity_check(self.backup)
        with closing(sqlite3.connect(self.backup)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM sample").fetchone()[0], "kept")

    def test_restore_keeps_a_verified_copy_of_current_database(self):
        self._make_database(self.database, "before_restore", "preserved")
        self._make_database(self.backup, "restored", "loaded")
        with patch("scalperlab.database_backup.database_path", return_value=self.database):
            rollback = restore_backup(self.backup)
        self.assertTrue(rollback.is_file())
        _integrity_check(self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            value = connection.execute("SELECT value FROM restored").fetchone()[0]
            self.assertEqual(value, "loaded")
        with closing(sqlite3.connect(rollback)) as connection:
            value = connection.execute("SELECT value FROM before_restore").fetchone()[0]
            self.assertEqual(value, "preserved")


if __name__ == "__main__":
    unittest.main()
