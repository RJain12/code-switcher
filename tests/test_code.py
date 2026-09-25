"""Tests for code-switcher. Run: python3 -m unittest discover -s tests -v"""
import http.server
import importlib.machinery
import importlib.util
import json
import os
import pty
import re
import select
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "code")


def load(path=SCRIPT, home=None):
    """Import the script as a module, pointed at a throwaway HOME / data dir."""
    home = home or tempfile.mkdtemp(prefix="code-home-")
    os.environ["HOME"] = home
    os.environ["CODE_ACCOUNTS_DIR"] = os.path.join(home, ".code-accounts")
    loader = importlib.machinery.SourceFileLoader(f"codeapp{time.time_ns()}", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    m.EFFORT_LOG = os.path.join(home, "effort.log")
    return m


def user(t):
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": t}]}


def call(i, cmd):
    return {"type": "function_call", "name": "exec_command", "call_id": f"c{i}", "arguments": json.dumps({"cmd": cmd})}


def out(i, o):
    return {"type": "function_call_output", "call_id": f"c{i}", "output": o}


def request(inp, key="s1", model="gpt-6-astra", effort="medium"):
    return json.dumps({"model": model, "reasoning": {"effort": effort}, "prompt_cache_key": key,
                       "input": inp, "stream": True}).encode()


HAS_ZSTD = True
try:
    from compression import zstd  # noqa: F401
except ImportError:
    HAS_ZSTD = False


class Storage(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_concurrent_writers_do_not_lose_changes(self):
        a, b = self.m.load_db(), self.m.load_db()  # two `code` processes holding stale copies
        self.m.mutate(a, lambda d: d["accounts"].append({"id": "claude-x", "provider": "claude", "name": "x", "home": "/h"}))
        self.m.mutate(b, lambda d: d["accounts"].append({"id": "codex-y", "provider": "codex", "name": "y", "home": "/h2"}))
        ids = {x["id"] for x in self.m.read_db()["accounts"]}
        self.assertTrue({"claude-x", "codex-y"} <= ids)
        self.m.update_acct(a, "codex-y", auto_effort=False)
        self.assertFalse(self.m.find(self.m.read_db(), "codex-y")["auto_effort"])

    def test_corrupt_file_is_backed_up_not_lost(self):
        os.makedirs(self.m.DATA, exist_ok=True)
        with open(self.m.DB, "w") as f:
            f.write("{not json")
        db = self.m.read_db()
        self.assertEqual(db["accounts"], [])
        self.assertTrue(any(n.startswith("accounts.json.corrupt-") for n in os.listdir(self.m.DATA)))

    def test_find_prefers_id_and_rejects_ambiguous_names(self):
        db = {"accounts": [{"id": "claude-default", "name": "default"}, {"id": "codex-default", "name": "default"}]}
        self.assertEqual(self.m.find(db, "codex-default")["id"], "codex-default")
        self.assertIsNone(self.m.find(db, "default"))


class Heuristic(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.p = self.m.EffortProxy("t")
        self.p.model_levels["gpt-6-astra"] = ["low", "medium", "high", "xhigh", "max", "ultra"]

    def tearDown(self):
        self.p.close()

    def run_script(self, script, key="s1"):
        hist = [{"type": "message", "role": "developer", "content": []}, user("<environment_context/>"),
                user("fix the failing test")]
        prev, efforts = None, []
        for i, (cmd, o) in enumerate(script):
            sent = json.loads(self.p.rewrite(request(list(hist), key))[0])["input"]
            if prev is not None:
                self.assertEqual(sent[:len(prev)], prev, f"cached prefix changed at step {i}")
            ups = [x["reasoning"]["effort"] for x in sent if x.get("type") == "configuration_update"]
            efforts.append(ups[-1] if ups else "medium")
            prev = sent
            hist += [call(i, cmd), out(i, o)]
        return efforts, hist

    def test_prefix_is_stable_and_effort_moves_sensibly(self):
        script = [("ls", "a"), ("cat a", "."), ("rg x", "."), ("sed -n 1p a", "."),
                  ("pytest", "FAILED t\nExit code: 1"), ("pytest", "FAILED t2\nExit code: 1"),
                  ("python x.py", "Traceback (most recent call last):\nExit code: 1"),
                  ("apply_patch", "Success"), ("pytest", "1 passed\nExit code: 0"), ("git diff", "."),
                  ("git status", "."), ("ls", ".")]
        efforts, _ = self.run_script(script)
        self.assertEqual(efforts[3], "low", "read-only run should drop effort")
        self.assertIn("high", efforts, "repeated failures should raise effort")
        self.assertLessEqual(max(self.m.EFFORTS.index(e) for e in efforts), self.m.EFFORTS.index("xhigh"),
                             "never more than two levels above the configured effort")
        self.assertEqual(efforts[-1], "medium", "should come back down after success")

    def test_rerunning_a_test_after_a_fix_is_not_a_loop(self):
        turn = [call(1, "pytest"), out(1, "FAILED\nExit code: 1"), call(2, "pytest"), out(2, "1 passed")]
        self.assertFalse(self.m.loop_signal(turn))
        turn = [call(1, "pytest"), out(1, "FAILED"), call(2, "pytest"), out(2, "FAILED")]
        self.assertTrue(self.m.loop_signal(turn))

    def test_retry_is_byte_identical(self):
        _, hist = self.run_script([("pytest", "FAILED\nExit code: 1"), ("pytest", "FAILED again\nExit code: 1")] * 2)
        body = request(hist)
        self.assertEqual(self.p.rewrite(body)[0], self.p.rewrite(body)[0])

    def test_compaction_resets_ledger(self):
        self.run_script([("pytest", "FAILED\nExit code: 1"), ("make", "error: x"), ("make", "error: y")])
        self.p.rewrite(request([user("summary of earlier work"), user("continue")]))
        self.assertEqual(self.p.sessions["s1"]["ledger"], [])

    def test_non_gpt6_and_non_list_input_untouched(self):
        body = request([user("hi")], model="gpt-5.5")
        self.assertEqual(self.p.rewrite(body), (body, None))
        body = json.dumps({"model": "gpt-6-astra", "input": "hi"}).encode()
        self.assertEqual(self.p.rewrite(body), (body, None))

    def test_range_limits_levels(self):
        p = self.m.EffortProxy("t", effort_range=["medium", "high"])
        p.model_levels["gpt-6-astra"] = ["low", "medium", "high", "xhigh", "max"]
        p.rewrite(request([user("go")], key="r"))
        self.assertEqual(p.sessions["r"]["levels"], ["medium", "high"])
        p.close()

    def test_unknown_base_effort_disables(self):
        self.p.rewrite(request([user("go")], key="n", effort="none"))
        self.assertTrue(self.p.sessions["n"]["disabled"])


class Jev(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.p = self.m.EffortProxy("t", jev_key="sk-or-test")
        self.p.model_levels["gpt-6-astra"] = ["low", "medium", "high", "xhigh", "max"]
        self.calls = []

    def tearDown(self):
        self.p.close()

    def fake(self, effort="high", lease=5, fail=False):
        def jev(key, state, timeout=10):
            self.calls.append(state)
            if fail:
                raise TimeoutError("slow")
            return effort, lease, 0.0004
        self.m.jev_decide = jev

    def step(self, hist):
        return json.loads(self.p.rewrite(request(list(hist)))[0])["input"]

    def test_lease_reuses_decision_and_new_failure_ends_it(self):
        self.fake("high", 5)
        hist = [user("refactor the parser")]
        self.step(hist)
        for i in range(3):
            hist += [call(i, f"cat f{i}"), out(i, "ok")]
            self.step(hist)
        self.assertEqual(len(self.calls), 1, "lease of 5 should cover the next steps")
        hist += [call(9, "pytest"), out(9, "FAILED\nExit code: 1")]
        self.step(hist)
        self.assertEqual(len(self.calls), 2, "a new tool failure must trigger re-evaluation")
        self.assertEqual(self.calls[-1]["newToolFailures"], 1)

    def test_jev_choice_outside_range_is_ignored(self):
        self.fake("ultra", 1)  # not in this session's allowed levels
        sent = self.step([user("x")])
        self.assertFalse(any(i.get("type") == "configuration_update" for i in sent))

    def test_failures_fall_back_and_trip_breaker(self):
        self.fake(fail=True)
        hist = [user("x")]
        for i in range(5):
            self.step(hist)
            hist += [call(i, "ls"), out(i, "a")]
        self.assertEqual(len(self.calls), 3, "breaker should stop calling Jev after 3 straight failures")
        self.assertGreater(self.p.jev_off_until, time.time())

    def test_state_is_bounded_and_redacted(self):
        secret_out = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456\n" + "x" * 50000
        hist = [user("deploy with token ghp_abcdefghijklmnopqrstuvwxyz0123"), call(1, "env"), out(1, secret_out)]
        s = {"levels": ["low", "medium", "high"], "step": 1}
        state = self.m.jev_state({"model": "gpt-6-astra"}, hist, s, "medium", 0)
        blob = json.dumps(state)
        self.assertNotIn("sk-abcdefghijklmnop", blob)
        self.assertNotIn("ghp_abcdefghijklmnop", blob)
        self.assertLess(len(blob), 20000)

    def test_decide_validates_response(self):
        replies = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                body = json.dumps(replies.pop(0)).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.m.JEV_URL = f"http://127.0.0.1:{srv.server_address[1]}/decisions"
        m = load()  # fresh module so jev_decide isn't the fake
        m.JEV_URL = self.m.JEV_URL
        state = {"supportedEfforts": ["low", "medium", "high"]}
        replies.append({"model": "typesafe/jev-1.13", "answers": {"effort": {"choice": "high"}, "lease": {"choice": "2"}},
                        "usage": {"cost": 0.0003}})
        self.assertEqual(m.jev_decide("k", state), ("high", 2, 0.0003))
        replies.append({"model": "someone/else", "answers": {"effort": {"choice": "high"}, "lease": {"choice": "2"}}})
        with self.assertRaises(ValueError):
            m.jev_decide("k", state)
        replies.append({"model": "typesafe/jev-1.13", "answers": {"effort": {"choice": "ultra"}, "lease": {"choice": "2"}}})
        with self.assertRaises(ValueError):
            m.jev_decide("k", state)
        srv.shutdown()


class ProxyWire(unittest.TestCase):
    """Real HTTP through the proxy to a fake upstream."""

    def setUp(self):
        self.m = load()
        self.seen = []
        seen = self.seen
        self.reject_updates = False
        test = self

        class Upstream(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"models": [{"slug": "gpt-6-astra", "supported_reasoning_levels": [
                    {"effort": e} for e in ("low", "medium", "high", "xhigh", "max")]}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                seen.append((dict(self.headers), raw))
                if test.reject_updates and b"configuration_update" in raw:
                    self.send_response(400)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"no")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for ev in (b'data: {"type":"response.created"}\n\n',
                           b'data: {"type":"response.completed","usage":{"input_tokens":900,"input_tokens_details":{"cached_tokens":800}}}\n\n'):
                    self.wfile.write(f"{len(ev):x}\r\n".encode() + ev + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")

        self.up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.p = self.m.EffortProxy("t")
        self.p.UPSTREAM = f"127.0.0.1:{self.up.server_address[1]}"
        self.p.UPSTREAM_TLS = False
        self.base = f"http://127.0.0.1:{self.p.port}/backend-api/codex"

    def tearDown(self):
        self.p.close()
        self.up.shutdown()

    def post(self, body, compress=False):
        headers = {"Content-Type": "application/json", "Authorization": "Bearer tok"}
        if compress:
            from compression import zstd
            body = zstd.compress(body)
            headers["Content-Encoding"] = "zstd"
        req = urllib.request.Request(self.base + "/responses", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()

    def reads_then_fail_history(self):
        hist = [user("go")]
        for i, cmd in enumerate(["ls", "cat a", "rg b"]):
            hist += [call(i, cmd), out(i, "ok")]
        return hist

    def test_catalog_learned_and_sse_relayed(self):
        urllib.request.urlopen(self.base + "/models", timeout=10).read()
        self.assertIn("max", self.p.model_levels["gpt-6-astra"])
        self.post(request([user("go")]))
        status, data = self.post(request(self.reads_then_fail_history()))
        self.assertEqual(status, 200)
        self.assertIn(b"response.completed", data)
        self.assertEqual(self.seen[-1][0].get("Authorization"), "Bearer tok", "auth must pass through")
        self.assertIn(b"configuration_update", self.seen[-1][1])
        with open(self.m.EFFORT_LOG) as f:
            self.assertIn("cached=800", f.read())

    @unittest.skipUnless(HAS_ZSTD, "needs Python 3.14 zstd")
    def test_zstd_request_is_rewritten_and_sent_plain(self):
        self.post(request([user("go")]), compress=True)
        self.post(request(self.reads_then_fail_history()), compress=True)
        headers, raw = self.seen[-1]
        self.assertNotIn("Content-Encoding", headers)
        self.assertIn("configuration_update", json.loads(raw)["input"][-1]["type"])

    def test_backend_rejecting_updates_falls_back_to_original(self):
        self.reject_updates = True
        self.post(request([user("go")]))
        status, _ = self.post(request(self.reads_then_fail_history()))
        self.assertEqual(status, 200, "original request should be retried transparently")
        self.assertNotIn(b"configuration_update", self.seen[-1][1])
        self.assertTrue(self.p.sessions["s1"]["disabled"])

    def test_upstream_down_returns_502(self):
        self.up.shutdown()
        self.up.server_close()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post(request([user("go")]))
        self.assertEqual(cm.exception.code, 502)


class Signals(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_limit_signals(self):
        L = self.m.limit_signal
        self.assertEqual(L("claude", {"isApiErrorMessage": True, "error": "billing_error"}), "billing_error")
        self.assertIsNone(L("claude", {"isApiErrorMessage": True, "error": "server_error"}))
        self.assertIsNone(L("claude", {"type": "assistant", "error": "billing_error"}))
        codex = {"type": "event_msg", "payload": {"type": "task_complete", "error": {
            "message": "You've hit your usage limit", "codex_error_info": "usage_limit_exceeded"}}}
        self.assertEqual(L("codex", codex), "usage_limit_exceeded")
        self.assertIsNone(L("codex", {"type": "event_msg", "payload": {"type": "error", "message": "boom"}}))

    def test_transient_rate_limit_does_not_switch(self):
        self.m.fetch_usage = lambda a: {"windows": [{"label": "5h", "pct": 40}]}
        self.assertFalse(self.m.confirm_exhausted({"provider": "claude"}, "rate_limit"))
        self.m.fetch_usage = lambda a: {"windows": [{"label": "5h", "pct": 100}]}
        self.assertTrue(self.m.confirm_exhausted({"provider": "claude"}, "rate_limit"))
        self.assertTrue(self.m.confirm_exhausted({"provider": "grok"}, "usage_limit_reached"))

    def test_codex_usage_parses_windows_and_banked_resets(self):
        with open(os.path.join(os.environ["HOME"], "auth.json"), "w") as f:
            json.dump({"tokens": {"access_token": "t", "account_id": "a"}}, f)
        self.m.http_json = lambda url, headers, body=None: {
            "plan_type": "pro", "email": "e@x", "rate_limit": {"primary_window": {
                "used_percent": 100, "limit_window_seconds": 604800, "reset_at": 1}},
            "rate_limit_reset_credits": {"available_count": 3, "applicable_available_count": 2}}
        info = self.m.fetch_codex({"provider": "codex", "home": os.environ["HOME"]})
        self.assertEqual(info["resets"], 2)
        self.assertEqual(info["windows"][0]["label"], "wk")

    def test_cursor_usage_parses_plan_usage(self):
        self.m.keychain_get = lambda service, account: "tok"
        self.m.cursor_email = lambda a: "me@x"
        replies = {
            "GetCurrentPeriodUsage": {"billingCycleEnd": "1790550000000", "planUsage": {
                "remaining": 500, "limit": 2000, "totalPercentUsed": 75}},
            "GetPlanInfo": {"planInfo": {"planName": "Pro"}},
            "GetCreditGrantsBalance": {"hasCreditGrants": True, "creditBalanceCents": "1250"},
        }
        self.m.cursor_rpc = lambda token, method: replies[method]
        info = self.m.fetch_cursor({"id": "cursor-default", "provider": "cursor", "home": None})
        self.assertEqual(info["windows"], [{"label": "mo", "pct": 75.0, "reset": 1790550000.0}])
        self.assertEqual(info["plan"], "Pro, $12.50 credits")
        replies["GetCurrentPeriodUsage"] = {"planUsage": {"remaining": 500, "limit": 2000}}
        self.assertEqual(self.m.fetch_cursor({"id": "c", "provider": "cursor", "home": None})["windows"][0]["pct"], 75.0)

    def test_existing_browser_login_is_not_adopted_twice(self):
        self.m.keychain_get = lambda service, account: "tok"
        db = {"accounts": [{"id": "cursor-work", "provider": "cursor", "name": "work", "home": None}], "last": None}
        self.m.detect_defaults(db)
        self.assertEqual([a["id"] for a in db["accounts"] if a["provider"] == "cursor"], ["cursor-work"])

    def test_redact(self):
        r = self.m.redact
        self.assertEqual(r("key sk-proj-abcdefghijklmnop1234"), "key [redacted]")
        self.assertIn("[redacted]", r('{"password": "hunter2hunter2"}'))
        self.assertEqual(r("plain text with no secrets"), "plain text with no secrets")


class Transcripts(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.dir = tempfile.mkdtemp()

    def write(self, name, rows):
        p = os.path.join(self.dir, name)
        with open(p, "w") as f:
            for r in rows:
                f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
        return p

    def export(self, provider, path):
        out = self.m.export_transcript({"provider": provider, "account": "a", "cwd": "/w", "path": path}, provider)
        with open(out) as f:
            return f.read()

    def test_claude(self):
        p = self.write("c.jsonl", [
            {"type": "user", "message": {"content": "<system-reminder>hidden</system-reminder>refactor it"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "On it"},
                                                          {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "a.py"}]}},
            "not json at all",
            {"type": "user", "isSidechain": True, "message": {"content": "subagent noise"}},
        ])
        md = self.export("claude", p)
        self.assertIn("refactor it", md)
        self.assertNotIn("hidden", md)
        self.assertNotIn("subagent noise", md)
        self.assertIn('Bash {"command": "ls"}', md)

    def test_codex(self):
        p = self.write("r.jsonl", [
            {"type": "session_meta", "payload": {"id": "x", "cwd": "/w"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                  "content": [{"type": "input_text", "text": "<environment_context>e"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                  "content": [{"type": "input_text", "text": "add retries"}]}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "output": "y" * 10000}},
        ])
        md = self.export("codex", p)
        self.assertIn("add retries", md)
        self.assertNotIn("environment_context", md)
        self.assertIn("more characters trimmed", md)

    def test_unknown_format_embeds_raw_log(self):
        p = self.write("updates.jsonl", ['{"weird": "shape"}'])
        md = self.export("grok", p)
        self.assertIn("raw session log", md)


class SelfUpdate(unittest.TestCase):
    def test_replaces_only_with_valid_newer_script(self):
        tmp = tempfile.mkdtemp()
        copy = os.path.join(tmp, "code")
        shutil.copy(SCRIPT, copy)
        m = load(copy)
        original = open(copy).read()

        class Resp:
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        m.urllib.request.urlopen = lambda *a, **k: Resp(b"def broken(:\n")
        with self.assertRaises(SyntaxError):
            m.self_update()
        self.assertEqual(open(copy).read(), original)
        newer = original.replace(f'VERSION = "{m.VERSION}"', 'VERSION = "99.0.0"').encode()
        m.urllib.request.urlopen = lambda *a, **k: Resp(newer)
        self.assertTrue(m.self_update())
        self.assertIn('VERSION = "99.0.0"', open(copy).read())
        self.assertTrue(os.access(copy, os.X_OK))


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import sys, os, json, time, re, datetime
home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
open(os.environ["E2E_LOG"], "a").write(json.dumps({"bin": "claude", "home": home, "argv": sys.argv[1:]}) + "\n")
if "--resume" in sys.argv or "auth" in sys.argv or "--session-id" not in sys.argv or os.environ.get("E2E_QUIET"):
    sys.exit(0)
sid = sys.argv[sys.argv.index("--session-id") + 1]
d = os.path.join(home, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())); os.makedirs(d, exist_ok=True)
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
with open(os.path.join(d, sid + ".jsonl"), "a") as f:
    f.write(json.dumps({"type": "user", "timestamp": now(), "message": {"content": "refactor the parser"}}) + "\n")
    f.flush(); time.sleep(1)
    f.write(json.dumps({"type": "assistant", "timestamp": now(), "isApiErrorMessage": True, "error": "billing_error",
                        "message": {"content": [{"type": "text", "text": "limit"}]}}) + "\n")
time.sleep(60)
'''

FAKE_CODEX = r'''#!/usr/bin/env python3
import sys, os, json
open(os.environ["E2E_LOG"], "a").write(json.dumps({"bin": "codex", "home": os.environ.get("CODEX_HOME"), "argv": sys.argv[1:]}) + "\n")
'''


class EndToEnd(unittest.TestCase):
    """Drive the real picker through a pseudo-terminal with fake agent CLIs."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="code-e2e-")
        self.bin = os.path.join(self.home, "bin")
        self.work = os.path.join(self.home, "work")
        os.makedirs(self.bin)
        os.makedirs(self.work)
        for name, src in (("claude", FAKE_CLAUDE), ("codex", FAKE_CODEX)):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(src)
            os.chmod(p, 0o755)
        data = os.path.join(self.home, ".code-accounts")
        os.makedirs(data)
        self.log = os.path.join(self.home, "log.jsonl")
        accts = [{"id": "claude-a", "provider": "claude", "name": "a", "home": os.path.join(data, "claude", "a")},
                 {"id": "claude-b", "provider": "claude", "name": "b", "home": os.path.join(data, "claude", "b")},
                 {"id": "codex-default", "provider": "codex", "name": "default", "home": None}]
        for a in accts:
            if a["home"]:
                os.makedirs(a["home"])
        with open(os.path.join(data, "accounts.json"), "w") as f:
            json.dump({"accounts": accts, "last": None, "seen_defaults": list(("claude", "codex", "grok", "cursor", "opencode"))}, f)
        with open(os.path.join(data, "usage-cache.json"), "w") as f:
            json.dump({"_update": {"checked": time.time(), "latest": None}}, f)

    def drive(self, args, keys, extra_env=None, wait=8):
        env = dict(os.environ, HOME=self.home, CODE_ACCOUNTS_DIR=os.path.join(self.home, ".code-accounts"),
                   PATH=self.bin + os.pathsep + os.environ["PATH"], E2E_LOG=self.log, TERM="xterm-256color",
                   LINES="20", COLUMNS="120", CODE_NO_NOTIFY="1", **(extra_env or {}))
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(self.work)
            os.execvpe(sys.executable, [sys.executable, SCRIPT] + args, env)
        buf = b""

        def pump(t):
            nonlocal buf
            end = time.time() + t
            while time.time() < end:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        buf += os.read(fd, 65536)
                    except OSError:
                        return

        pump(wait)
        screen = buf
        for k in keys:
            try:
                os.write(fd, k)
            except OSError:
                break
            pump(1.5)
        pump(2)
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        os.waitpid(pid, 0)
        return screen.decode("utf-8", "replace"), buf.decode("utf-8", "replace")

    def calls(self):
        with open(self.log) as f:
            return [json.loads(l) for l in f]

    def test_limit_hit_hands_off_natively_to_other_claude_account(self):
        screen, _ = self.drive(["claude-a"], [b"\r"])
        self.assertIn("hit its usage limit", screen)
        calls = self.calls()
        self.assertEqual(calls[0]["argv"][0], "--session-id")
        sid = calls[0]["argv"][1]
        self.assertEqual(calls[1]["argv"][:2], ["--resume", sid])
        self.assertTrue(calls[1]["home"].endswith("claude/b"))
        copied = [f for _, _, fs in os.walk(calls[1]["home"]) for f in fs]
        self.assertIn(sid + ".jsonl", copied)

    def test_handoff_to_codex_gets_transcript_prompt(self):
        self.drive(["claude-a"], [b"j", b"\r"])
        codex = [c for c in self.calls() if c["bin"] == "codex"][0]
        self.assertIn("You are taking over a conversation", codex["argv"][-1])
        path = re.search(r"transcript is in (\S+\.md)", codex["argv"][-1]).group(1)
        with open(path) as f:
            self.assertIn("refactor the parser", f.read())

    def test_auto_handoff_countdown_picks_best_without_input(self):
        path = os.path.join(self.home, ".code-accounts", "accounts.json")
        db = json.load(open(path))
        db["auto_handoff_seconds"] = 2
        json.dump(db, open(path, "w"))
        cache = os.path.join(self.home, ".code-accounts", "usage-cache.json")
        c = json.load(open(cache))
        c["codex-default"] = {"windows": [{"label": "wk", "pct": 10}], "fetched": time.time() + 3600}
        json.dump(c, open(cache, "w"))
        screen, _ = self.drive(["claude-a"], [], wait=10)
        self.assertIn("Continuing on codex-default", screen)
        self.assertTrue(any(c["bin"] == "codex" for c in self.calls()))

    def seed_thread(self, title="fix the parser bug"):
        sid = "11111111-2222-3333-4444-555555555555"
        d = os.path.join(self.home, ".code-accounts", "claude", "a", "projects", re.sub(r"[^A-Za-z0-9]", "-", self.work))
        os.makedirs(d)
        with open(os.path.join(d, sid + ".jsonl"), "w") as f:
            f.write(json.dumps({"type": "user", "cwd": self.work, "message": {"content": title}}) + "\n")
            f.write(json.dumps({"type": "assistant", "cwd": self.work, "message": {"content": [{"type": "text", "text": "ok"}]}}) + "\n")
        return sid

    def test_enter_on_thread_resumes_it_in_its_folder(self):
        sid = self.seed_thread()
        screen, _ = self.drive([], [b"j", b"\r"], extra_env={"E2E_QUIET": "1"}, wait=4)
        self.assertIn("fix the parser bug", screen)
        c = self.calls()[0]
        self.assertEqual(c["argv"][:2], ["--resume", sid])
        self.assertTrue(c["home"].endswith("claude/a"))

    def test_h_hands_a_thread_to_another_account(self):
        sid = self.seed_thread()
        screen, full = self.drive([], [b"j", b"h", b"\r"], extra_env={"E2E_QUIET": "1"}, wait=4)
        self.assertIn("Continue", full)
        c = self.calls()[0]
        self.assertTrue(c["home"].endswith("claude/b"), "should launch on the other Claude account")
        self.assertEqual(c["argv"][:2], ["--resume", sid])
        copied = [f for _, _, fs in os.walk(c["home"]) for f in fs]
        self.assertIn(sid + ".jsonl", copied)

    def test_normal_exit_does_not_open_picker(self):
        screen, full = self.drive(["claude-a"], [], extra_env={"E2E_QUIET": "1"}, wait=4)
        self.assertNotIn("hit its usage limit", full)

    def test_picker_scrolls_with_many_accounts(self):
        path = os.path.join(self.home, ".code-accounts", "accounts.json")
        db = json.load(open(path))
        for i in range(12):
            db["accounts"].append({"id": f"claude-x{i}", "provider": "claude", "name": f"x{i}",
                                   "home": os.path.join(self.home, f"x{i}")})
        json.dump(db, open(path, "w"))
        screen, _ = self.drive([], [b"q"], wait=4)
        self.assertIn("more", screen)

    def test_list_json(self):
        import subprocess
        env = dict(os.environ, HOME=self.home, CODE_ACCOUNTS_DIR=os.path.join(self.home, ".code-accounts"),
                   PATH=self.bin + os.pathsep + os.environ["PATH"])
        out = subprocess.run([sys.executable, SCRIPT, "list", "--json"], env=env, capture_output=True, text=True, timeout=60)
        rows = json.loads(out.stdout)
        self.assertEqual({r["id"] for r in rows}, {"claude-a", "claude-b", "codex-default"})
        self.assertTrue(all("home" not in r for r in rows))

    def test_picker_refuses_without_tty(self):
        import subprocess
        env = dict(os.environ, HOME=self.home, CODE_ACCOUNTS_DIR=os.path.join(self.home, ".code-accounts"))
        r = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("interactive terminal", r.stderr)


if __name__ == "__main__":
    unittest.main()
