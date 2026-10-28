"""Exercise the pack release gate with valid and deliberately broken catalogues."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "tools/ko/check_port_translations.mjs"


class ValidationGate(unittest.TestCase):
    def validate(self, en, ko):
        with tempfile.TemporaryDirectory() as directory:
            english, korean = (Path(directory) / name for name in ("en.csv", "ko.csv"))
            english.write_text(en, encoding="utf-8")
            korean.write_text(ko, encoding="utf-8")
            return subprocess.run(["node", str(CHECKER), "--english", str(english),
                                   "--korean", str(korean)], cwd=ROOT,
                                  capture_output=True, text=True, encoding="utf-8")

    def test_valid_korean_plural_and_multiline_quotes(self):
        en = 'Key,Value\nx.a,"{n, plural, one {# item} other {# items}} for {name}"\nx.b,"Line one\nSay ""yes"""\n'
        ko = 'Key,Value\nx.a,"{name}: {n, plural, other {#개}}"\nx.b,"첫 줄\n""예""라고 말하기"\n'
        result = self.validate(en, ko)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_rejects_duplicate(self):
        self.assertNotEqual(self.validate('Key,Value\nx.a,"Hello"\n',
                                         'Key,Value\nx.a,"안녕"\nx.a,"안녕하세요"\n').returncode, 0)

    def test_rejects_broken_quote(self):
        self.assertNotEqual(self.validate('Key,Value\nx.a,"Hello"\n',
                                         'Key,Value\nx.a,"안녕\n').returncode, 0)

    def test_rejects_quoted_keys_unreadable_by_game(self):
        self.assertNotEqual(self.validate('Key,Value\nx.a,"Hello"\n',
                                         'Key,Value\n"x.a","안녕"\n').returncode, 0)

    def test_rejects_missing_variable(self):
        self.assertNotEqual(self.validate('Key,Value\nx.a,"Hello {name}"\n',
                                         'Key,Value\nx.a,"안녕하세요"\n').returncode, 0)

    def test_rejects_changed_number_format(self):
        self.assertNotEqual(self.validate('Key,Value\nx.a,"{n, number}"\n',
                                         'Key,Value\nx.a,"{n}"\n').returncode, 0)

    def test_rejects_plural_without_other(self):
        self.assertNotEqual(self.validate('Key,Value\nx.a,"{n, plural, other {# items}}"\n',
                                         'Key,Value\nx.a,"{n, plural, one {#개}}"\n').returncode, 0)

    def test_rejects_missing_key(self):
        self.assertNotEqual(self.validate('Key,Value\nx.a,"Hello"\nx.b,"Bye"\n',
                                         'Key,Value\nx.a,"안녕"\n').returncode, 0)


if __name__ == "__main__":
    unittest.main()
