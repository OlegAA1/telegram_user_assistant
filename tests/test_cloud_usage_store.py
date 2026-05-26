from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.services.cloud_usage_store import CloudUsageStore


class CloudUsageStoreTest(unittest.TestCase):
    def test_counts_successful_requests(self) -> None:
        with TemporaryDirectory() as tmp:
            store = CloudUsageStore(Path(tmp) / "usage.sqlite3")
            try:
                self.assertEqual(store.get_used_today(), 0)
                self.assertTrue(store.can_use(1))

                store.record_request()

                self.assertEqual(store.get_used_today(), 1)
                self.assertFalse(store.can_use(1))
                self.assertTrue(store.can_use(2))
                self.assertFalse(store.can_use(0))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
