import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SEED_DIR = BASE_DIR / "helper_seed"
LIVE_HELPER_DIR = Path(r"C:\Users\Administrator\.openclaw\workspace-mc-helper")
MIRRORED_FILES = [
    "AGENTS.md",
    "BOOTSTRAP.md",
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
]


class HelperSeedTests(unittest.TestCase):
    def test_seed_files_exist(self):
        for name in MIRRORED_FILES:
            self.assertTrue((SEED_DIR / name).exists(), f"missing seed file: {name}")

    def test_seed_files_match_live_helper_workspace_when_present(self):
        if not LIVE_HELPER_DIR.exists():
            self.skipTest("live helper workspace not present")
        for name in MIRRORED_FILES:
            expected = (LIVE_HELPER_DIR / name).read_text(encoding="utf-8")
            actual = (SEED_DIR / name).read_text(encoding="utf-8")
            self.assertEqual(actual, expected, f"seed file out of sync: {name}")


if __name__ == "__main__":
    unittest.main()
