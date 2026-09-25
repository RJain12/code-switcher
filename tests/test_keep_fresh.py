import base64
import datetime
import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch

from test_code import load


def jwt(expires_in):
    body = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + expires_in}).encode()).decode().rstrip("=")
    return "header." + body + ".signature"


class KeepFresh(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.m = load()
        self.claude = {"id": "claude-a", "provider": "claude", "home": "/tmp/a"}
        self.codex = {"id": "codex-b", "provider": "codex", "home": "/tmp/b"}
        self.grok = {"id": "grok-c", "provider": "grok", "home": "/tmp/c"}
        self.db = {"accounts": [self.claude, self.codex, self.grok]}
        idle = patch.object(self.m, "account_in_use", return_value=False)
        idle.start()
        self.addCleanup(idle.stop)

    def creds(self, claude_expired_for, codex_expired_for):
        claude = {"refreshToken": "r", "expiresAt": (time.time() - claude_expired_for) * 1000}
        codex = {"tokens": {"refresh_token": "r", "access_token": jwt(-codex_expired_for)}}
        return patch.multiple(self.m, claude_creds=lambda a: claude, codex_auth=lambda a: codex)

    def test_recently_used_accounts_are_left_alone(self):
        with self.creds(claude_expired_for=3600, codex_expired_for=-4 * 86400):
            for acct in self.db["accounts"]:
                self.assertIsNone(self.m.keep_fresh_reason(acct, time.time()))

    def test_idle_accounts_need_a_refresh_and_other_providers_never_do(self):
        with self.creds(claude_expired_for=13 * 3600, codex_expired_for=13 * 3600):
            now = time.time()
            self.assertIn("expired", self.m.keep_fresh_reason(self.claude, now))
            self.assertIn("expired", self.m.keep_fresh_reason(self.codex, now))
            self.assertIsNone(self.m.keep_fresh_reason(self.grok, now))
            self.assertIsNone(self.m.keep_fresh_reason({**self.claude, "keyed": True}, now))

    def test_dry_run_reports_without_running_or_recording(self):
        with self.creds(13 * 3600, 13 * 3600), patch.object(self.m.subprocess, "run") as run, \
                patch("builtins.print") as out:
            self.assertEqual(self.m.cmd_keep_fresh(self.db, ["--dry-run"]), 0)
        run.assert_not_called()
        report = json.loads(out.call_args.args[0])
        self.assertEqual(report["claude-a"]["status"], "would-refresh")
        self.assertEqual(report["grok-c"]["status"], "fresh")
        self.assertFalse(os.path.exists(self.m.KEEP_FRESH_STATE))

    def test_refresh_uses_official_cli_with_account_env_and_throttles_retries(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs["env"]))
            return subprocess.CompletedProcess(command, 1, "", "network down")

        with self.creds(13 * 3600, 13 * 3600), patch.object(self.m.subprocess, "run", side_effect=fake_run), \
                patch.object(self.m, "env_for", side_effect=lambda a: {"ACCOUNT": a["id"]}), patch("builtins.print"):
            self.assertEqual(self.m.cmd_keep_fresh(self.db, []), 1)
            self.assertEqual(len(calls), 2)
            self.assertIn("haiku", calls[0][0])
            self.assertEqual(calls[0][1], {"ACCOUNT": "claude-a"})
            self.assertEqual(calls[1][0][1:3], ["exec", "--skip-git-repo-check"])
            self.m.cmd_keep_fresh(self.db, [])
            self.assertEqual(len(calls), 2, "failed accounts must wait before another attempt")

    def test_success_is_confirmed_by_rereading_credentials(self):
        state = {"expired": 13 * 3600}
        claude = lambda a: {"refreshToken": "r", "expiresAt": (time.time() - state["expired"]) * 1000}

        def fake_run(command, **kwargs):
            state["expired"] = -8 * 3600
            return subprocess.CompletedProcess(command, 0, "OK", "")

        db = {"accounts": [self.claude]}
        with patch.object(self.m, "claude_creds", side_effect=claude), \
                patch.object(self.m.subprocess, "run", side_effect=fake_run), patch("builtins.print") as out:
            self.assertEqual(self.m.cmd_keep_fresh(db, []), 0)
        self.assertEqual(json.loads(out.call_args.args[0])["claude-a"]["status"], "refreshed")

    def test_accounts_used_by_a_running_cli_are_skipped(self):
        with self.creds(13 * 3600, 13 * 3600), patch.object(self.m, "account_in_use", return_value=True), \
                patch.object(self.m.subprocess, "run") as run, patch("builtins.print") as out:
            self.m.cmd_keep_fresh(self.db, [])
        run.assert_not_called()
        self.assertEqual(json.loads(out.call_args.args[0])["codex-b"]["status"], "in-use")

    def test_in_use_detection_matches_the_account_home(self):
        in_use = load().account_in_use
        listing = "node /opt/bin/codex app-server CODEX_HOME=/tmp/b PATH=/bin\n/bin/zsh HOME=/Users/x\n"
        with patch.object(in_use.__globals__["subprocess"], "run",
                          return_value=subprocess.CompletedProcess([], 0, listing, "")):
            self.assertTrue(in_use({"provider": "codex", "home": "/tmp/b"}))
            self.assertFalse(in_use({"provider": "codex", "home": "/tmp/other"}))
            self.assertFalse(in_use({"provider": "codex", "home": None}))


if __name__ == "__main__":
    unittest.main()
