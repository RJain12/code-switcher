#!/usr/bin/env python3
"""Run one visual game build with fixed medium and one with native Jev."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bench" / "fixtures" / "orbit_game"
ACCOUNT = os.environ.get("BENCH_ACCOUNT", "codex-yt")
MODEL = os.environ.get("BENCH_MODEL", "gpt-6-sol")
HOME = Path.home()
DATA = HOME / ".code-accounts"
ARES = DATA / "astra-ares"
RUNS = ARES / "data" / "runs"
DEST = ROOT / "bench" / "artifacts" / ("orbit-" + time.strftime("%Y%m%d-%H%M%S"))
PROMPT = "Implement the complete playable Orbit Courier game in SPEC.md. Work only in this directory. Keep SPEC.md unchanged. Deliver a polished, responsive interface and fully working game controls. Test your work."


def price(usage, jev_cost):
    """GPT-6 Sol Standard API equivalent, short-context rates; not a ChatGPT bill."""
    input_tokens = usage.get("input_tokens", 0)
    cached = usage.get("cached_input_tokens", 0)
    written = usage.get("cache_write_input_tokens", 0)
    output = usage.get("output_tokens", 0)
    return round(((input_tokens - cached) * 2 + cached * .2 + written * 2.5 + output * 10) / 1e6 + jev_cost, 6)


def run(mode):
    folder = DEST / mode
    shutil.copytree(SOURCE, folder)
    if mode == "jev":
        cmd = [str(ROOT / "code"), ACCOUNT, "exec", "--json", "--skip-git-repo-check", PROMPT]
    else:
        cmd = ["node", str(ARES / "source" / "bin" / "astra-ares.mjs"), "-m", MODEL,
               "-c", 'model_reasoning_effort="medium"', "exec", "--json",
               "--skip-git-repo-check", PROMPT]
    account_home = DATA / "codex" / ACCOUNT.removeprefix("codex-")
    env = dict(os.environ, CODEX_HOME=str(account_home), ARES_HOME=str(ARES / "data"),
               ARES_CONFIG=str(ARES / f"{ACCOUNT}.json"))
    before = set(RUNS.glob("*/decisions.jsonl"))
    started = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=folder, env=env, capture_output=True, text=True, timeout=900)
        exit_code, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        exit_code = 124
        stdout = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else e.stdout or ""
        stderr = (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else e.stderr or ""
    seconds = round(time.monotonic() - started, 2)
    (folder / "codex-events.jsonl").write_text(stdout)
    (folder / "codex-stderr.log").write_text(stderr)
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    usage = next((x.get("usage", {}) for x in reversed(events) if x.get("type") == "turn.completed"), {})
    costs, decisions = [], []
    for path in set(RUNS.glob("*/decisions.jsonl")) - before:
        for line in path.read_text().splitlines():
            item = json.loads(line)
            if item.get("type") == "decision":
                costs.append(float(item.get("cost") or 0))
                decisions.append({"step": item.get("step"), "effort": item.get("effort"),
                                  "lease": item.get("leaseSteps")})
    js = subprocess.run(["node", "--check", "game.js"], cwd=folder, capture_output=True, text=True)
    complete = all((folder / name).stat().st_size > (SOURCE / name).stat().st_size
                   for name in ("style.css", "game.js"))
    result = {"mode": mode, "seconds": seconds, "exit": exit_code, "usage": usage,
              "jev_cost_usd": round(sum(costs), 8), "api_equivalent_usd": price(usage, sum(costs)),
              "js_syntax_ok": js.returncode == 0, "files_implemented": complete,
              "spec_unchanged": (folder / "SPEC.md").read_bytes() == (SOURCE / "SPEC.md").read_bytes(),
              "jev_decisions": decisions, "artifact": str(folder / "index.html")}
    (folder / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    DEST.mkdir(parents=True)
    print(f"Artifacts: {DEST}", flush=True)
    results = []
    for mode in ("fixed", "jev"):
        print(f"Starting {mode}...", flush=True)
        row = run(mode)
        results.append(row)
        print(json.dumps(row), flush=True)
    (DEST / "results.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
