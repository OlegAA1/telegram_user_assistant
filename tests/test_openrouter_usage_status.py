import sys
import types
import unittest
from types import SimpleNamespace


aiohttp = types.ModuleType("aiohttp")
aiohttp.ClientError = Exception
aiohttp.ContentTypeError = Exception
aiohttp.ClientTimeout = lambda total=None: SimpleNamespace(total=total)
sys.modules.setdefault("aiohttp", aiohttp)

config = types.ModuleType("app.config")
config.Settings = object
sys.modules.setdefault("app.config", config)

from app.services.openrouter_service import OpenRouterService


class FakeUsageStore:
    def __init__(self, used_today: int) -> None:
        self.used_today = used_today

    def get_used_today(self) -> int:
        return self.used_today


class OpenRouterUsageStatusTest(unittest.TestCase):
    def test_usage_status_shows_remaining_requests(self) -> None:
        service = OpenRouterService(
            SimpleNamespace(max_cloud_requests_per_day=30),
            usage_store=FakeUsageStore(7),
        )

        self.assertEqual(
            service.usage_status(),
            "used today `7/30`, remaining `23`",
        )

    def test_usage_status_reports_disabled_limit(self) -> None:
        service = OpenRouterService(
            SimpleNamespace(max_cloud_requests_per_day=0),
            usage_store=FakeUsageStore(2),
        )

        self.assertEqual(
            service.usage_status(),
            "disabled by daily limit `0`, used today `2`",
        )


if __name__ == "__main__":
    unittest.main()
