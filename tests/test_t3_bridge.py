"""Focused native history export and T3 transport tests; no provider requests."""
import contextlib
import http.server
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import datetime
import threading
import unittest
from unittest.mock import patch, Mock

from test_code import load, ROOT


class T3Bridge(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        self.tmp = tempfile.TemporaryDirectory(prefix="code-t3-test-")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.env.stop)
        self.code = load(home=self.tmp.name)
        self.client = load(path=os.path.join(ROOT, "codespace"), home=self.tmp.name)
        self.account = {"id": "codex-work", "provider": "codex", "home": self.tmp.name}
        self.path = Path(self.tmp.name) / "session.jsonl"
        self.thread = {"id": "native-id", "path": str(self.path), "cwd": self.tmp.name, "title": "Test"}

    def write(self, rows):
        self.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    def test_codex_export_uses_native_identity_and_model_without_duplicate_event_messages(self):
        self.write([
            {"type": "session_meta", "payload": {"id": "native-id"}},
            {"type": "turn_context", "payload": {"model": "model-from-session"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Hi"}},
            {"type": "response_item", "timestamp": "2026-09-25T12:00:00Z", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hi"}]}},
        ])
        first = self.code.session_import_payload(self.account, self.thread)
        second = self.code.session_import_payload(self.account, self.thread)
        self.assertEqual(first, second)
        self.assertEqual(first["model"], "model-from-session")
        self.assertEqual(first["sourceHome"], os.path.realpath(self.tmp.name))
        self.assertEqual([m["text"] for m in first["messages"]], ["Hi"])

    def test_claude_skips_sidechains_and_deduplicates_rows(self):
        self.account["provider"] = "claude"
        row = {"type": "assistant", "uuid": "a1", "sessionId": "native-id", "timestamp": "2026-09-25T12:00:00Z",
               "message": {"role": "assistant", "model": "claude-test", "content": [{"type": "text", "text": "Hello"}]}}
        self.write([dict(row, isSidechain=True, uuid="child"), row, row])
        self.assertEqual(len(self.code.session_import_payload(self.account, self.thread)["messages"]), 1)

    def test_rejects_wrong_identity_missing_model_and_outside_account(self):
        self.write([{"type": "session_meta", "payload": {"id": "another-id"}}])
        with self.assertRaisesRegex(ValueError, "ID does not match"):
            self.code.session_import_payload(self.account, self.thread, "test-model")
        self.write([])
        with self.assertRaisesRegex(ValueError, "specify --model"):
            self.code.session_import_payload(self.account, self.thread)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.code.session_import_payload(dict(self.account, home=str(self.path.parent / "other")), self.thread)

    def test_transport_sends_auth_and_body_and_does_not_follow_redirects(self):
        received = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                received.append((self.path, self.headers.get("Authorization"), self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(302 if len(received) > 1 else 200)
                self.send_header("Location", "/should-not-follow")
                self.end_headers()
                self.wfile.write(b'{"threadId":"imported-thread","imported":2}')
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.client.CONFIG.parent.mkdir(parents=True, exist_ok=True)
        self.client.CONFIG.write_text(json.dumps({"t3_url": f"http://127.0.0.1:{server.server_port}"}))
        os.environ["CODESPACE_T3_TOKEN"] = "test-token"
        with patch.object(self.client.sys, "stdin", Mock(buffer=io.BytesIO(b'{"version":1}'))):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(self.client.t3(["_receive"]), 0)
            self.assertEqual(json.loads(output.getvalue())["threadId"], "imported-thread")
            with self.assertRaisesRegex(SystemExit, "HTTP 302"):
                self.client.t3(["_receive"])
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0], ("/api/codespace/import", "Bearer test-token", b'{"version":1}'))

    def test_transport_rejects_plaintext_remote_url_before_reading_token(self):
        with patch.object(self.client, "config", return_value={"t3_url": "http://remote-machine:3773"}):
            with self.assertRaisesRegex(SystemExit, "HTTPS or a loopback"):
                self.client.t3(["_receive"])

    def record(self):
        self.write([{"type": "session_meta", "payload": {"id": "native-id"}}])
        self.code.record_completed_session(self.account, {
            "session_id": "native-id", "path": str(self.path), "cwd": self.tmp.name,
            "home": self.tmp.name, "ended": 123,
        })

    def test_completed_receipt_rejects_changed_transcript(self):
        self.record()
        self.assertEqual(self.code.completed_session_thread(self.account, "native-id")["path"], str(self.path))
        with self.path.open("a") as f:
            f.write("{}\n")
        with self.assertRaisesRegex(ValueError, "changed since Code"):
            self.code.completed_session_thread(self.account, "native-id")

    def test_account_lease_blocks_import_while_native_session_is_running(self):
        with self.code.account_session_lock(self.account):
            with self.assertRaisesRegex(ValueError, "running Code session"):
                with self.code.account_session_lock(self.account, importing=True):
                    self.fail("exclusive lease must not succeed")
        with self.code.account_session_lock(self.account, importing=True):
            with self.assertRaisesRegex(ValueError, "handoff in progress"):
                with self.code.account_session_lock(self.account):
                    self.fail("native session must not start during delivery")

    def test_delivery_keeps_exclusive_lease_until_http_client_exits(self):
        self.record()
        def deliver(*args, **kwargs):
            with self.assertRaises(ValueError):
                with self.code.account_session_lock(self.account):
                    self.fail("lease released too early")
            self.assertEqual(json.loads(kwargs["input"])["sessionId"], "native-id")
            return subprocess.CompletedProcess(args[0], 0)
        with patch.object(self.code.subprocess, "run", side_effect=deliver):
            self.code.cmd_thread_export({"accounts": [self.account]}, ["codex-work", "native-id", "--completed", "--model", "test-model", "--deliver-t3"])

    def test_import_defaults_to_observed_completion(self):
        with patch.object(self.client, "require", return_value="code"), patch.object(self.client.subprocess, "call", return_value=0) as call:
            self.assertEqual(self.client.t3(["import", "codex-work", "native-id"]), 0)
            self.assertEqual(call.call_args.args[0], ["code", "thread-export", "codex-work", "native-id", "--completed", "--deliver-t3"])

    def test_real_supervised_child_produces_completed_receipt(self):
        path = Path(self.tmp.name) / "sessions" / datetime.date.today().strftime("%Y/%m/%d") / "rollout-fixture.jsonl"
        path.parent.mkdir(parents=True)
        rows = [{"type": "session_meta", "payload": {"id": "observed-native", "cwd": self.tmp.name}}]
        script = Path(self.tmp.name) / "provider.py"
        script.write_text("#!" + sys.executable + "\nfrom pathlib import Path\nPath(" + repr(str(path)) + ").write_text(" + repr(json.dumps(rows[0]) + "\n") + ")\n")
        script.chmod(0o700)
        with patch.object(self.code, "binary_for", return_value=str(script)), patch.object(self.code, "auto_effort_ok", return_value=False), patch.object(self.code, "sync_claude_mcp"):
            rc, _, session = self.code.supervise({"accounts": [self.account]}, self.account, [], cwd=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertEqual(session["session_id"], "observed-native")
        self.assertEqual(self.code.completed_session_thread(self.account, "observed-native")["path"], str(path))

    def test_native_rpc_keeps_token_out_of_process_arguments(self):
        os.environ["CODESPACE_T3_TOKEN"] = "private-test-token"
        with patch.object(self.client, "require", return_value="node"), patch.object(self.client.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(self.client.t3(["scan"]), 0)
            self.assertNotIn("private-test-token", " ".join(run.call_args.args[0]))
            request = json.loads(run.call_args.kwargs["input"])
            self.assertEqual(request["method"], "agentSessions.scan")
            self.assertEqual(request["payload"], {})
            self.assertEqual(request["token"], "private-test-token")
            self.assertEqual(self.client.t3(["import-project", "project-123"]), 0)
            request = json.loads(run.call_args.kwargs["input"])
            self.assertEqual(request["method"], "agentSessions.import")
            self.assertEqual(request["payload"], {"projectId": "project-123"})

    def test_provider_plan_preserves_existing_instances_and_is_idempotent(self):
        accounts = [self.account, {"id": "claude-team", "provider": "claude", "home": "/accounts/team"}, {"id": "cursor-work", "provider": "cursor", "home": "/accounts/cursor"}]
        existing = {"providerInstances": {"my-codex": {"driver": "codex", "enabled": False, "config": {"homePath": self.tmp.name}, "environment": [{"name": "SECRET", "sensitive": True, "valueRedacted": True, "value": ""}]}}}
        original = json.dumps(existing, sort_keys=True)
        plan = self.client.t3_provider_plan(accounts, existing, home=self.tmp.name)
        self.assertEqual(plan["mappings"][0]["instance"], "my-codex")
        self.assertEqual(set(plan["additions"]), {"codespace-claude-team"})
        self.assertEqual(plan["additions"]["codespace-claude-team"]["driver"], "claudeAgent")
        self.assertEqual(plan["skipped"][0]["account"], "cursor-work")
        self.assertEqual(json.dumps(existing, sort_keys=True), original)
        merged = {"providerInstances": {**existing["providerInstances"], **plan["additions"]}}
        self.assertEqual(self.client.t3_provider_plan(accounts, merged, home=self.tmp.name)["additions"], {})

    def test_provider_plan_rejects_collision_instead_of_overwriting_another_account(self):
        existing = {"providerInstances": {"codespace-codex-work": {"driver": "codex", "config": {"homePath": "/different-account"}}}}
        with self.assertRaisesRegex(ValueError, "collision"):
            self.client.t3_provider_plan([self.account], existing)

    def test_provider_plan_matches_default_homes_and_shadow_auth_homes(self):
        home = self.tmp.name
        accounts = [{"id": "codex-default", "provider": "codex", "home": None}, {"id": "claude-default", "provider": "claude", "home": None}, self.account]
        settings = {"providerInstances": {"shadow": {"driver": "codex", "config": {"homePath": "/shared", "shadowHomePath": home}}}}
        plan = self.client.t3_provider_plan(accounts, settings, home=home)
        self.assertEqual([m["instance"] for m in plan["mappings"]], ["codex", "claudeAgent", "shadow"])
        self.assertEqual(plan["additions"], {})


if __name__ == "__main__":
    unittest.main()
