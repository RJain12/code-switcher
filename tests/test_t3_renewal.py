"""Managed T3 token rotation: fake issuer, real private file replacement."""
import datetime
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_code import load, ROOT


class Renewal(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CODESPACE_T3_TOKEN", None)
        self.tmp = tempfile.TemporaryDirectory(prefix="codespace-renew-")
        self.addCleanup(self.tmp.cleanup)
        self.client = load(os.path.join(ROOT, "codespace"), self.tmp.name)
        self.home = Path(self.tmp.name)
        self.token = self.client.CONFIG.parent / "t3-token"
        self.data = (self.home / ".t3").resolve()
        (self.data / "userdata").mkdir(parents=True)
        (self.data / "userdata/server-runtime.json").write_text(json.dumps({"port": 3773}))
        self.app = self.home / "T3.app"
        (self.app / "Contents").mkdir(parents=True)
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "T3"}))
        self.client.CONFIG.parent.mkdir(parents=True)
        self.client.CONFIG.write_text(json.dumps({"t3_app": str(self.app)}))
        self.now = datetime.datetime.now(datetime.timezone.utc)
        self.fresh = {"token": "new-private-token", "sessionId": "new-session", "expiresAt": (self.now + datetime.timedelta(days=30)).isoformat()}

    def seed(self, days):
        self.client.private_json_write(self.token, {"version": 1, "managedBy": "codespace", "token": "old-private-token", "sessionId": "old-session", "expiresAt": (self.now + datetime.timedelta(days=days)).isoformat(), "baseDir": str(self.data), "baseUrl": "http://127.0.0.1:3773"})

    def test_current_token_does_not_launch_issuer(self):
        self.seed(20)
        with patch.object(self.client.subprocess, "run") as run:
            self.assertEqual(self.client.renew_t3_connection(True)["status"], "current")
            run.assert_not_called()

    def test_due_token_is_verified_replaced_privately_and_old_session_revoked(self):
        self.seed(2)
        issued = subprocess.CompletedProcess([], 0, stdout=json.dumps(self.fresh))
        revoked = subprocess.CompletedProcess([], 0, stdout=b"")
        with patch.object(self.client.subprocess, "run", side_effect=[issued, revoked]) as run, patch.object(self.client, "verify_t3_token") as verify:
            result = self.client.renew_t3_connection(True)
            self.assertEqual(result["status"], "renewed")
            self.assertEqual(result["previousSession"], "revoked")
            self.assertEqual([call.args[1] for call in verify.call_args_list], ["old-private-token", "new-private-token"])
            self.assertIn("old-session", run.call_args_list[-1].args[0])
        self.assertEqual(self.client.read_t3_token(self.token)[0], "new-private-token")
        self.assertEqual(self.token.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("private-token", json.dumps(result))

    def test_issuer_failure_preserves_working_token(self):
        self.seed(1)
        before = self.token.read_bytes()
        with patch.object(self.client, "verify_t3_token"), patch.object(self.client.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout="")):
            with self.assertRaisesRegex(ValueError, "could not issue"):
                self.client.renew_t3_connection(True)
        self.assertEqual(self.token.read_bytes(), before)

    def test_revoked_token_is_not_automatically_reissued(self):
        self.seed(1)
        with patch.object(self.client, "verify_t3_token", side_effect=ValueError("revoked")), patch.object(self.client.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "revoked"):
                self.client.renew_t3_connection(True)
            run.assert_not_called()

    def test_unmanaged_credentials_are_not_replaced_by_maintenance(self):
        self.token.write_text("external-token")
        self.token.chmod(0o600)
        self.assertEqual(self.client.renew_t3_connection(True)["status"], "unmanaged")
        self.assertEqual(self.token.read_text(), "external-token")


if __name__ == "__main__":
    unittest.main()
