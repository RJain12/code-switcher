#!/usr/bin/env python3
"""Small reproducible Jev vs fixed-medium Codex coding benchmark."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HOME = Path.home()
ACCOUNT = os.environ.get("BENCH_ACCOUNT", "codex-yt")
CODEX_HOME = HOME / ".code-accounts" / "codex" / ACCOUNT.removeprefix("codex-")
ROOT = Path(__file__).resolve().parents[1]
RUNS = HOME / ".code-accounts" / "astra-ares" / "data" / "runs"
ARES = HOME / ".code-accounts" / "astra-ares"

TASKS = {
    "quoted_csv": {
        "files": {
            "parser.py": 'def fields(line):\n    return line.strip().split(",")\n',
            "test_parser.py": """import unittest
from parser import fields

class Tests(unittest.TestCase):
    def test_plain(self): self.assertEqual(fields('a,b,c'), ['a', 'b', 'c'])
    def test_quoted_comma(self): self.assertEqual(fields('a,"b,c",d'), ['a', 'b,c', 'd'])
""",
        },
        "prompt": "Fix fields() so the two tests pass. Do not edit tests. Keep the public function name. Run python -m unittest discover -q.",
    },
    "retry": {
        "files": {
            "retry.py": 'def retry(fn, attempts=3):\n    for _ in range(attempts - 1):\n        try:\n            return fn()\n        except ValueError:\n            pass\n    raise ValueError("failed")\n',
            "test_retry.py": """import unittest
from retry import retry

class Tests(unittest.TestCase):
    def test_last_attempt_succeeds(self):
        calls = [0]
        def fn():
            calls[0] += 1
            if calls[0] < 3: raise ValueError('again')
            return 42
        self.assertEqual(retry(fn, 3), 42)
        self.assertEqual(calls[0], 3)
""",
        },
        "prompt": "Fix retry() so the test passes. Do not edit tests. Preserve ValueError after all attempts fail. Run python -m unittest discover -q.",
    },
}


def launch(task, mode, folder):
    for name, content in task["files"].items():
        (folder / name).write_text(content)
    if mode == "jev":
        cmd = [str(ROOT / "code"), ACCOUNT, "exec", "--json", "--skip-git-repo-check", task["prompt"]]
    else:
        cmd = ["node", str(ARES / "source" / "bin" / "astra-ares.mjs"),
               "-m", "gpt-6-sol", "-c", 'model_reasoning_effort="medium"',
               "exec", "--json", "--skip-git-repo-check", task["prompt"]]
    env = dict(os.environ, CODEX_HOME=str(CODEX_HOME))
    env.update(ARES_HOME=str(ARES / "data"), ARES_CONFIG=str(ARES / f"{ACCOUNT}.json"))
    before = set(RUNS.glob("*/decisions.jsonl")) if RUNS.exists() else set()
    start = time.monotonic()
    result = subprocess.run(cmd, cwd=folder, env=env, capture_output=True, text=True, timeout=240)
    seconds = round(time.monotonic() - start, 2)
    events = []
    for line in result.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    usage = next((e.get("usage", {}) for e in reversed(events) if e.get("type") == "turn.completed"), {})
    jev_cost = 0.0
    for path in (set(RUNS.glob("*/decisions.jsonl")) - before) if RUNS.exists() else []:
        for line in path.read_text().splitlines():
            event = json.loads(line)
            if event.get("type") == "decision":
                jev_cost += float(event.get("cost") or 0)
    test = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=folder, capture_output=True, text=True)
    tests_unchanged = all((folder / name).read_text() == content for name, content in task["files"].items()
                          if name.startswith("test_"))
    return {"mode": mode, "seconds": seconds, "exit": result.returncode,
            "tests_pass": test.returncode == 0, "tests_unchanged": tests_unchanged,
            "usage": usage, "jev_cost_usd": round(jev_cost, 8),
            "stderr_tail": result.stderr[-500:] if result.returncode else ""}


def main():
    results = []
    for name, task in TASKS.items():
        for mode in ("fixed", "jev"):
            with tempfile.TemporaryDirectory(prefix=f"code-bench-{name}-{mode}-") as d:
                row = {"task": name, **launch(task, mode, Path(d))}
                results.append(row)
                print(json.dumps(row), flush=True)
    out = ROOT / "bench" / "last-results.json"
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
