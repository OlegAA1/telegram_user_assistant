import sys
import types
import unittest


aiohttp = types.ModuleType("aiohttp")
aiohttp.ClientError = Exception
aiohttp.ClientTimeout = lambda total=None: None
sys.modules.setdefault("aiohttp", aiohttp)

from app.handlers.health_command import _model_names, ollama_tags_url


class HealthCommandHelpersTest(unittest.TestCase):
    def test_ollama_tags_url_uses_generate_endpoint_host(self) -> None:
        self.assertEqual(
            ollama_tags_url("http://100.1.2.3:11434/api/generate"),
            "http://100.1.2.3:11434/api/tags",
        )

    def test_ollama_tags_url_falls_back_for_invalid_url(self) -> None:
        self.assertEqual(
            ollama_tags_url("not-a-url"),
            "http://localhost:11434/api/tags",
        )

    def test_model_names_extracts_ollama_names(self) -> None:
        self.assertEqual(
            _model_names({"models": [{"name": "qwen3.5"}, {"name": ""}, {"x": "y"}]}),
            ["qwen3.5"],
        )


if __name__ == "__main__":
    unittest.main()
