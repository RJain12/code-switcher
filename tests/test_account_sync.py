import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_code import load, ROOT


def account(id, provider, identity, login="ok", keyed=False):
    return {"id": id, "provider": provider, "name": id.split("-", 1)[1], "keyed": keyed,
            "identity": identity, "login": login, "expires_in": None}


class AccountPlan(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = load(os.path.join(ROOT, "codespace"), self.tmp.name)

    def test_keys_are_copied_and_oauth_logins_need_their_own_sign_in(self):
        manifests = {
            "macbook": {"accounts": [account("claude-adi", "claude", "adi@x"),
                                     account("codex-default", "codex", "r@x/1"),
                                     account("openrouter-jev", "openrouter", "key:abc", keyed=True)]},
            "mini": {"accounts": [account("codex-default", "codex", "r@x/1")]},
            "space": {"error": "TimeoutExpired"},
        }
        plan = self.app.account_plan(manifests)
        actions = {(a["action"], a["machine"], a["account"]) for a in plan["actions"]}
        self.assertEqual(actions, {("copy-key", "mini", "openrouter-jev"), ("sign-in", "mini", "claude-adi")})
        self.assertEqual(plan["machines"]["space"], {"error": "TimeoutExpired"})

    def test_unverifiable_keychain_logins_are_not_reported_missing(self):
        manifests = {
            "macbook": {"accounts": [account("claude-default", "claude", "r@x")]},
            "mini": {"accounts": [account("claude-default", "claude", None, login="unknown")]},
        }
        self.assertEqual(self.app.account_plan(manifests)["actions"], [])

    def test_lapsed_logins_are_flagged_for_sign_in_again(self):
        manifests = {"mini": {"accounts": [account("codex-api", "codex", "y@x/2", login="idle")]}}
        [action] = self.app.account_plan(manifests)["actions"]
        self.assertEqual((action["action"], action["command"]),
                         ("sign-in-again", "codespace accounts link mini codex-api"))

    def test_cached_manifest_fills_only_unknown_entries(self):
        live = {"accounts": [account("claude-default", "claude", None, login="unknown"),
                             account("codex-api", "codex", "y@x/2", login="idle")]}
        cached = {"generated_at": 5, "accounts": [account("claude-default", "claude", "r@x"),
                                                  account("codex-api", "codex", "y@x/2")]}
        merged = self.app.merge_cached_manifest(live, cached)["accounts"]
        self.assertEqual((merged[0]["identity"], merged[0]["login"], merged[0]["as_of"]), ("r@x", "ok", 5))
        self.assertEqual(merged[1]["login"], "idle")

    def test_sync_copies_keys_through_stdin_only(self):
        manifests = {
            "macbook": {"accounts": [account("openrouter-jev", "openrouter", "key:abc", keyed=True)]},
            "mini": {"accounts": []},
        }
        calls = []
        def run_code_on(alias, args, stdin=None):
            calls.append((alias, args, stdin))
            out = '{"provider": "openrouter", "name": "jev", "key": "sk-1"}' if args[0] == "key-export" \
                else '{"id": "openrouter-jev", "status": "added"}'
            return subprocess.CompletedProcess(args, 0, out, "")
        with patch.object(self.app, "gather_manifests", return_value=manifests), \
                patch.object(self.app, "run_code_on", side_effect=run_code_on):
            report = self.app.accounts_sync()
        self.assertEqual(report["copied"][0]["status"], "added")
        self.assertEqual([(a, args) for a, args, _ in calls],
                         [("macbook", ["key-export", "openrouter-jev"]), ("mini", ["key-import"])])
        self.assertNotIn("sk-1", json.dumps([args for _, args, _ in calls]))
        self.assertIn("sk-1", calls[1][2])


class KeyTransfer(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.m = load(home=self.tmp.name)
        real_run = self.m.subprocess.run
        def locked_keychain(cmd, *args, **kwargs):
            if cmd[0] == "security":
                return subprocess.CompletedProcess(cmd, 36, "", "User interaction is not allowed.")
            return real_run(cmd, *args, **kwargs)
        keychain = patch.object(self.m.subprocess, "run", side_effect=locked_keychain)
        keychain.start()
        self.addCleanup(keychain.stop)

    def run_import(self, spec):
        out = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(spec))), patch("sys.stdout", out):
            self.assertEqual(self.m.cmd_key_import(self.m.load_db(), []), 0)
        return json.loads(out.getvalue())

    def test_locked_keychain_stores_the_key_in_a_private_file_and_reimport_is_idempotent(self):
        spec = {"provider": "openrouter", "name": "jev", "model": None, "key": "sk-or-1"}
        self.assertEqual(self.run_import(spec), {"id": "openrouter-jev", "status": "added"})
        db = self.m.load_db()
        acct = self.m.find(db, "openrouter-jev")
        path = self.m.key_path(acct)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(self.m.key_get(acct), "sk-or-1")
        self.assertEqual(self.run_import(spec)["status"], "exists")
        out = io.StringIO()
        with patch("sys.stdout", out):
            self.m.cmd_key_export(self.m.load_db(), ["openrouter-jev"])
        self.assertEqual(json.loads(out.getvalue())["key"], "sk-or-1")

    def test_a_different_key_with_the_same_name_gets_its_own_account(self):
        self.run_import({"provider": "openrouter", "name": "jev", "key": "sk-or-1"})
        self.assertEqual(self.run_import({"provider": "openrouter", "name": "jev", "key": "sk-or-2"})["id"],
                         "openrouter-jev-2")

    def test_only_api_key_providers_are_accepted(self):
        with patch("sys.stdin", io.StringIO(json.dumps({"provider": "codex", "name": "x", "key": "k"}))), \
                self.assertRaises(SystemExit):
            self.m.cmd_key_import(self.m.load_db(), [])


if __name__ == "__main__":
    unittest.main()
