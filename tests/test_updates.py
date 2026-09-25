"""Paired release activation and failure recovery, using offline release fixtures."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_code import load, ROOT


class Updates(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory(prefix="codespace-update-test-")
        self.addCleanup(tmp.cleanup)
        self.client = load(os.path.join(ROOT, "codespace"), tmp.name)
        self.client.RELEASE_ROOT = Path(tmp.name) / "releases-root"
        self.client.INSTALL_BIN = Path(tmp.name) / "bin"
        self.commit = "a" * 40
        self.bad = False
        def fetch(url):
            if "api.github.com" in url:
                return json.dumps({"sha": self.commit}).encode()
            if self.bad and url.endswith("/codespace"):
                return b"this is not valid python {"
            return ("print(" + repr(self.commit + ":" + url.rsplit("/", 1)[-1]) + ")\n").encode()
        self.fetch = patch.object(self.client, "release_fetch", side_effect=fetch)
        self.fetch.start()
        self.addCleanup(self.fetch.stop)

    def run_update(self, args):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.client.update(args)

    def test_both_entrypoints_switch_together_and_can_roll_back(self):
        self.run_update(["--install"])
        root = self.client.RELEASE_ROOT
        first = (root / "current").resolve()
        self.commit = "b" * 40
        self.run_update([])
        for name in ("code", "codespace"):
            self.assertEqual((self.client.INSTALL_BIN / name).resolve().parent.name, self.commit)
        self.assertEqual((root / "previous").resolve(), first)
        self.run_update(["--rollback"])
        self.assertEqual((root / "current").resolve(), first)
        self.assertEqual((root / "previous").resolve().name, "b" * 40)

    def test_bad_second_file_keeps_current_release_and_cleans_staging(self):
        self.run_update(["--install"])
        before = (self.client.RELEASE_ROOT / "current").resolve()
        self.commit = "b" * 40
        self.bad = True
        with self.assertRaises(SyntaxError):
            self.run_update([])
        self.assertEqual((self.client.RELEASE_ROOT / "current").resolve(), before)
        self.assertFalse(list((self.client.RELEASE_ROOT / "releases").glob(".stage-*")))

    def test_install_preserves_development_symlink_and_source(self):
        self.client.INSTALL_BIN.mkdir(parents=True)
        source = self.client.INSTALL_BIN.parent / "development-code"
        source.write_text("development content")
        (self.client.INSTALL_BIN / "code").symlink_to(source)
        self.run_update(["--install"])
        self.assertEqual(source.read_text(), "development content")
        self.assertEqual((self.client.RELEASE_ROOT / "original-entrypoints/code").resolve(), source.resolve())

    def test_tampered_cached_release_is_not_activated(self):
        self.run_update(["--install"])
        path = self.client.RELEASE_ROOT / "current" / "codespace"
        path.write_text("print('tampered')")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.run_update([])

    def test_repeat_update_repairs_entrypoint_without_losing_rollback(self):
        self.run_update(["--install"])
        first = (self.client.RELEASE_ROOT / "current").resolve()
        self.commit = "b" * 40
        self.run_update([])
        (self.client.INSTALL_BIN / "codespace").unlink()
        self.run_update([])
        self.assertTrue((self.client.INSTALL_BIN / "codespace").is_file())
        self.assertEqual((self.client.RELEASE_ROOT / "previous").resolve(), first)


if __name__ == "__main__":
    unittest.main()
