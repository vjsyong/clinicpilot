"""CLI-level tests: config discovery terminates, findings gate the exit code."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lint"))

from triage_lint import load_config, main  # noqa: E402


class TestCli(unittest.TestCase):
    def test_config_discovery_terminates(self):
        cfg = load_config("/tmp")
        self.assertIsInstance(cfg, dict)

    def _run(self, args):
        with contextlib.redirect_stdout(io.StringIO()):
            return main(args)

    def test_clean_file_exits_zero(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "ok.css"), "w") as fh:
            fh.write(".a{color:var(--fg);padding:8px;border-radius:0}\n")
        self.assertEqual(self._run([d]), 0)

    def test_violation_exits_one(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "bad.css"), "w") as fh:
            fh.write(".a{border-radius:4px}\n")
        self.assertEqual(self._run([d]), 1)

    def test_strict_warning_exits_one(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "warn.css"), "w") as fh:
            fh.write(".a{color:#123456}\n")
        self.assertEqual(self._run([d]), 0)
        self.assertEqual(self._run([d, "--strict"]), 1)


if __name__ == "__main__":
    unittest.main()
