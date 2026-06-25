import importlib
import sys
import types
import unittest


class ConfigSourceKeywordRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda: None
        sys.modules["dotenv"] = dotenv
        sys.modules.pop("app.config", None)
        self.config = importlib.import_module("app.config")

    def test_sources_expands_to_individual_rules(self) -> None:
        rules = self.config._parse_source_keyword_rules_value(
            [
                {
                    "sources": ["channel_a", "-100123"],
                    "keywords": ["testnet"],
                    "targets": ["-100999"],
                },
            ],
            source_name="TEST",
        )

        self.assertEqual([r.source for r in rules], ["channel_a", "-100123"])
        self.assertEqual([r.keywords for r in rules], [("testnet",), ("testnet",)])
        self.assertEqual([r.targets for r in rules], [("-100999",), ("-100999",)])

    def test_source_still_works(self) -> None:
        rules = self.config._parse_source_keyword_rules_value(
            [
                {
                    "source": "channel_a",
                    "keywords": ["release"],
                    "targets": ["me"],
                },
            ],
            source_name="TEST",
        )

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].source, "channel_a")


if __name__ == "__main__":
    unittest.main()
