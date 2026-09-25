import datetime
import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch

from test_code import load


def iso(seconds_ago):
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return moment.isoformat().replace("+00:00", "Z")


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

    def creds(self, claude_expired_for, codex_age):
        claude = {"refreshToken": "r", "expiresAt": (time.time() - claude_expired_for) * 1000}
        codex = {"tokens": {"refresh_token": "r"}, "last_refresh": iso(codex_age)}
        return patch.multiple(self.m, claude_creds=lambda a: claude, codex_auth=lambda a: codex)

    def test_recently_used_accounts_are_left_alone(self):
        with self.creds(claude_expired_for=3600, codex_age=86400):
            for acct in self.db["accounts"]:
                self.assertIsNone(self.m.keep_fresh_reason(acct, time.time()))

    def test_idle_accounts_need_a_refresh_and_other_providers_never_do(self):
        with self.creds(claude_expired_for=13 * 3600, codex_age=9 * 86400):
            now = time.time()
            self.assertIn("expired", self.m.keep_fresh_reason(self.claude, now))
            self.assertIn("refreshed", self.m.keep_fresh_reason(self.codex, now))
            self.assertIsNone(self.m.keep_fresh_reason(self.grok, now))
            self.assertIsNone(self.m.keep_fresh_reason({**self.claude, "keyed": True}, now))

    def test_dry_run_reports_without_running_or_recording(self):
        with self.creds(13 * 3600, 9 * 86400), patch.object(self.m.subprocess, "run") as run, \
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

        with self.creds(13 * 3600, 9 * 86400), patch.object(self.m.subprocess, "run", side_effect=fake_run), \
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


if __name__ == "__main__":
    unittest.main()
