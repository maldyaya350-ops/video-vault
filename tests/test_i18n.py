import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common import STR  # noqa: E402


class I18nTests(unittest.TestCase):
    def test_languages_have_same_keys(self):
        self.assertEqual(set(STR["en"]), set(STR["ar"]))

    def test_every_used_key_exists(self):
        used = set()
        for f in ("player_app.py", "creator_app.py"):
            src = (ROOT / f).read_text("utf-8")
            used |= set(re.findall(r'\btr\(\s*"([a-z0-9_]+)"', src))
        used |= {f"s{i}" for i in range(5)}  # strength labels are built dynamically
        used |= {"pw_short", "pw_common", "pw_weak"}
        missing = sorted(k for k in used if k not in STR["en"])
        self.assertEqual(missing, [])

    def test_format_placeholders_match(self):
        for key, en in STR["en"].items():
            ph = lambda s: set(re.findall(r"\{(\w+)\}", s))  # noqa: E731
            self.assertEqual(ph(en), ph(STR["ar"][key]), key)


if __name__ == "__main__":
    unittest.main()
