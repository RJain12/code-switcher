"""Focused native history export and T3 transport tests; no provider requests."""
import contextlib
import http.server
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

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
        with patch.object(self.client, "require", return_value="code"), patch.object(self.client.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b'{"version":1}'
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(self.client.t3(["import", "codex-work", "native-id", "--stopped"]), 0)
            self.assertEqual(json.loads(output.getvalue())["threadId"], "imported-thread")
            with self.assertRaisesRegex(SystemExit, "HTTP 302"):
                self.client.t3(["import", "codex-work", "native-id", "--stopped"])
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0], ("/api/codespace/import", "Bearer test-token", b'{"version":1}'))

    def test_transport_rejects_plaintext_remote_url_before_reading_token(self):
        with patch.object(self.client, "config", return_value={"t3_url": "http://remote-machine:3773"}):
            with self.assertRaisesRegex(SystemExit, "HTTPS or a loopback"):
                self.client.t3(["import", "account", "session", "--stopped"])


if __name__ == "__main__":
    unittest.main()
