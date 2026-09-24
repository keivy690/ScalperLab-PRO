import tempfile
import unittest
from pathlib import Path

from scalperlab.single_instance import SingleInstanceLock


class SingleInstanceTests(unittest.TestCase):
    def test_lock_rejects_second_instance_and_releases_for_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()


if __name__ == "__main__":
    unittest.main()
