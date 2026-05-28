import unittest

from app.services.script_run_parser import parse_script_run


class ScriptRunParserTest(unittest.TestCase):
    def test_parses_run_with_wallet(self) -> None:
        run = parse_script_run(
            """✅ OK | ZKCodex Arc Testnet
Действие: GM
51 - 0xA8AD6b...4BDc18 - 2026-05-28 16:15""",
            timezone_name="Europe/Moscow",
        )

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "OK")
        self.assertEqual(run.script_name, "ZKCodex Arc Testnet")
        self.assertEqual(run.action, "GM")
        self.assertEqual(run.profile_number, 51)
        self.assertEqual(run.wallet, "0xA8AD6b...4BDc18")
        self.assertEqual(run.details, "")

    def test_parses_run_without_wallet(self) -> None:
        run = parse_script_run(
            """✅ OK | Catena Waitlist
Действие: Waitlist Registration
31 - 2026-05-28 16:16""",
            timezone_name="Europe/Moscow",
        )

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "OK")
        self.assertEqual(run.script_name, "Catena Waitlist")
        self.assertEqual(run.action, "Waitlist Registration")
        self.assertEqual(run.profile_number, 31)
        self.assertEqual(run.wallet, "")
        self.assertEqual(run.details, "")

    def test_parses_run_with_details(self) -> None:
        run = parse_script_run(
            """✅ OK | InfinityName Arc Testnet
Действие: InfinityName
2 - 0x8a8d2C...b9eF5e - 2026-05-28 16:30
Детали: CyberNights.arc""",
            timezone_name="Europe/Moscow",
        )

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "OK")
        self.assertEqual(run.script_name, "InfinityName Arc Testnet")
        self.assertEqual(run.action, "InfinityName")
        self.assertEqual(run.profile_number, 2)
        self.assertEqual(run.wallet, "0x8a8d2C...b9eF5e")
        self.assertEqual(run.details, "CyberNights.arc")


if __name__ == "__main__":
    unittest.main()
