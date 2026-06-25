import unittest
from types import SimpleNamespace

from app.handlers.health_command import health_command_predicate, health_status_text


class FakeMessage:
    out = False

    def __init__(self, message: str) -> None:
        self.message = message


class FakeEvent:
    is_private = True

    def __init__(self, message: str) -> None:
        self.message = FakeMessage(message)


class FakeRouter:
    def provider_status(self) -> str:
        return "Провайдеры:\n- openrouter: configured"


class HealthCommandTest(unittest.IsolatedAsyncioTestCase):
    def test_health_command_predicate(self) -> None:
        self.assertTrue(health_command_predicate(FakeEvent("/health")))
        self.assertTrue(health_command_predicate(FakeEvent("/llmhealth")))
        self.assertFalse(health_command_predicate(FakeEvent("/ask hi")))

    async def test_health_status_uses_provider_status(self) -> None:
        text = await health_status_text(settings=SimpleNamespace(), router=FakeRouter())

        self.assertIn("Health:", text)
        self.assertIn("openrouter: configured", text)


if __name__ == "__main__":
    unittest.main()
