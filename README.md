# code-switcher

**One command to pick between your AI coding agent accounts (Claude Code, Codex, OpenRouter, Grok, Cursor, OpenCode), with each account's live usage limits shown so you can choose the one with headroom.**

```
  code pick an account to launch

 › Claude     work      you@company.com [team]  ★ most headroom
                5h ███░░░░░░░  31% resets 2h14m     wk █████░░░░░  52% resets Fri 5am

   Codex      default   you@company.com [pro] ⚡auto-effort+jev
                wk ██████████ 100% resets Sat 1am   ↺ 3 resets banked

   OpenRouter or-key    anthropic/claude-opus-5.5 [$41.20 credits left]
                bal ██░░░░░░░░  18%

   Grok       personal
                Grok has no usage API; limit hits are still detected

  enter launch  a add  d remove  l re-login  e auto-effort  r refresh  q quit
```

If you hit rate limits on one subscription, you can keep working on another. `code` keeps many logins signed in at the same time and launches whichever one you pick. When an agent runs out of usage mid-task, `code` hands the conversation to another account. For Codex, it also adjusts reasoning effort step by step without breaking the prompt cache.

## Codespace (local first)

Existing Claude/Codex profiles outside Code can be registered without moving credentials:
`code adopt codex api --home ~/.codex-api` or `code adopt claude work --home ~/.claude-work`.
Adoption keeps the existing configuration, detects already-registered homes, and marks the home
as externally owned. Removing its Code entry never deletes that home. Adoption does not verify
credential validity or quota; inspect usage or run a task separately. Supported adopted accounts
are included in discovery and the configured automatic T3 mapping.

Codespace is also available directly inside Code:

```sh
code space on mini t3 providers
code space find "final report pdf"
code dispatch --account codex-yt --model gpt-6-astra --prompt "Review this project"
code space on mini t3 start --account codex-default --model gpt-6-astra --prompt "Review this project"
```

`code space` forwards all Codespace commands; `code dispatch` starts a T3 thread on this machine.
Prompts may use `--prompt -` to read stdin. Remote workspaces must exist on the selected machine.

`codespace` unifies Code and the Space CLI while keeping execution on the Mac where you start it. `codespace`
starts the normal Code picker locally; `codespace on mini` launches Code on a configured Mac over SSH;
`codespace job ask ...` explicitly sends work to a Space worker. `codespace menu` manages the Space menu app,
and `codespace find <query>` searches files through that app's helper. Set trusted Mac aliases in
`~/.config/codespace/config.json`, for example `{"hosts":{"mini":"user@mac-mini.local"}}`.
Space remains a separate optional install for now.

`codespace sync` publishes each machine's provider names and connection alias to
`~/Space/.codespace/machines/`; `codespace sync status` reads the shared catalog. The catalog contains no API
keys, OAuth tokens, emails, or local credential paths. Provider login remains on the machine that runs the agent.
Set `sync_uri` in the same config file to a `gs://.../machines` path to read and write the catalog through GCS
directly when the mounted drive is slow.


### Work placement

```sh
# Explain the decision; upload and execute nothing.
codespace run --plan --portable --workload compute -- python3 analyze.py
# Upload a small script and return a durable Space job ID.
codespace run --portable --workload compute -f analyze.py -- python3 input/analyze.py
# Browser/login-dependent work remains on the Mac hosting that environment.
codespace on mini run --needs browser -- python3 browser_task.py
codespace job status JOB_ID
codespace job result JOB_ID
codespace job cancel JOB_ID
```

Cloud execution requires an explicit `--portable` declaration. Compute, build, test, media, download,
and declared memory needs of at least 4096 MiB select Space when no Mac dependencies are declared.
`--needs browser|desktop|keychain|macos|local-network` keeps work local and rejects a forced cloud target.
The router uses these declarations; it cannot infer every dependency from arbitrary code. Existing
logins and desktop environments stay on their host. Use `--target local` or `--target space` to choose.

Cloud jobs run asynchronously by default; `--wait` waits for the result. `-f` accepts explicit files up to
100 MiB, available as `input/BASENAME`; write deliverables under `out/`. Large inputs should already be
in Space and referenced as `/space/...` in cloud commands. Local execution with attached files creates
a durable workspace under `~/.local/share/codespace/jobs/`; without attachments it uses your current
directory. Commands are passed as argument lists; use `bash -lc '...'` explicitly for shell syntax.

### Reverse access between Macs

When the MacBook can SSH to the mini, enable a reconnecting reverse connection on the MacBook:

```sh
codespace bridge enable mini
codespace bridge status
# On the mini, using the MacBook's configured self_alias:
codespace on macbook t3 providers
# On the MacBook, stop the connection:
codespace bridge disable
```

Set a unique `self_alias` in `~/.config/codespace/config.json` before setup; otherwise the hostname
is used. Setup requires an existing trusted SSH connection to the peer. It generates a dedicated
key on the peer, pins the MacBook host key, and installs two user launch agents on the MacBook.
The SSH listener and reverse port bind only to loopback. The peer gains shell and file access as
your MacBook user through `codespace-ALIAS`; existing SSH configuration is preserved. File transfer
uses the same Codespace host mapping. The connection retries after interruptions while both Macs
are awake and reachable. `status` reports service registration, not an end-to-end connectivity check.
One reverse peer is supported per Mac; use a distinct `--port` for each MacBook sharing a mini.
Disabling stops the services and retains keys and peer configuration for re-enrollment.

Configured GCS machine catalogs also refresh during hourly/login maintenance. New local account
names become discoverable after each machine's next successful refresh. Failed listings or partial
downloads preserve the previous complete local catalog and report an error; token renewal and
CLI updates still run independently. This synchronizes discovery, not provider credentials.

### Managed CLI updates

```sh
codespace update --install
codespace auto-update enable
codespace update --status
codespace update --rollback
codespace auto-update disable
```

Managed installs download `code` and `codespace` from the same pinned GitHub commit, validate both,
and switch one release pointer. Existing development files stay intact; initial entrypoints are backed
up under `~/.local/share/codespace/original-entrypoints`. A failed download leaves the current release
active. Prior releases remain available for rollback. Disable automatic updates before rolling back
if you want to stay on that release. The launchd task checks hourly and at login while your Mac is
awake; logs live under `~/.local/share/codespace/`. Run setup separately on each Mac. This updates
the CLI pair and renews enrolled local T3 connections; T3, the menu app, provider binaries, and cloud
workers retain their own update paths.

### Installed T3 integration

T3 0.0.42 includes native session discovery and project history import. Configure the local
T3 connection with `codespace t3 connect`, then use these commands with the installed app:

```sh
codespace t3 providers          # preview native account mappings
codespace t3 providers --apply  # add missing provider instances on this host
codespace t3 scan
codespace t3 import-project PROJECT_ID
codespace t3 import-cwd /absolute/path/to/project
codespace on mini t3 scan
```

`providers` maps this machine's Code Claude/Codex accounts to T3 provider instances. It reuses matching
homes and adds missing instances without editing existing ones, including their disabled state and
environment settings. T3 reads the existing account credentials locally; this does not copy credentials
between machines. Cursor and OpenRouter mappings are reported as unsupported until their credential
adapters are implemented. Run the same command through `codespace on mini` for the mini's accounts.

Set `"t3_auto_providers": true` in `~/.config/codespace/config.json` to apply this mapping during
hourly/login maintenance. New supported Code accounts then appear in that machine's T3 automatically.
Existing provider instances, including disabled ones, are preserved. T3 must be running; failures are
reported and retried on the next maintenance run without preventing catalog sync or CLI updates.

`scan` returns native projects and their existing T3 project IDs when available. `import-project`
imports recent supported CLI history for an existing T3 project using T3's scanner and resume bindings.
Stop native CLI sessions for that project first. This operation can import multiple sessions across
configured provider instances. It requires Node 22+ for native WebSocket support; credentials travel
through stdin and a single-use WebSocket ticket, not command-line arguments. Discovery can take
several minutes when provider history is stored on a network drive. `t3_timeout_seconds` in the
Codespace config controls the request deadline (default 180 seconds, maximum 1800).

`import-cwd` creates or reuses the T3 project for a local workspace and imports its native CLI
history with a workspace identity guard. It does not start an agent turn. Use it after stopping
CLI sessions for that workspace; this currently remains an explicit operation.
Both workspace import commands reject provider instances whose history directories resolve to the
same location. T3 0.0.42 otherwise imports that history under multiple account identities. Direct
T3 dispatch remains available; automatic CLI-history handoff awaits account-specific import support.

### Dispatch an agent directly into T3

After dispatch, `codespace t3 wait THREAD_ID --timeout 300` polls the saved thread and prints its
snapshot. It exits 0 for a completed turn, 1 for an error or interruption, and 124 when the wait
expires. A timeout leaves the task running; inspect it again or stop it explicitly. Individual HTTP
requests can take up to 60 seconds beyond the polling deadline. Use `codespace on mini t3 wait ...`
for a thread on the mini. Submission alone does not prove provider completion or task correctness.

```sh
codespace t3 start --account codex-yt --model gpt-6-astra --cwd /path/to/repo --prompt 'Inspect the failing test'
codespace on mini t3 start --account codex-default --model gpt-6-astra --cwd /path/on/mini --prompt 'Inspect the failing test'
codespace t3 status THREAD_ID
codespace t3 stop THREAD_ID
```

The thread is created in that host's running T3 server and uses the mapped Code account. Normal T3
clients connected to the host can see it immediately. Dispatch defaults to approval-required mode;
resolve approvals in T3. The returned ID confirms submission, not successful provider execution—use
`status` to inspect completion, quota errors, and the response. `--prompt -` reads the task from stdin.

Use `--request-id YOUR_ID` to retry an interrupted submission without creating another thread or turn.
The same ID must carry the same account, workspace, model, title, and prompt. Local dispatch receipts
are private files under `~/.config/codespace/dispatches/`. Provider usage limits and login requirements
still apply; select another configured account when necessary.

### Renewable local T3 connections

`codespace t3 connect` enrolls this Mac using the installed T3 app's admin CLI and verifies the new token
against its running server. The connection file is private (mode 600) and replaced atomically.
`codespace t3 renew` renews it only when fewer than seven days remain. The hourly macOS maintenance
job runs renewal automatically after `codespace auto-update enable`; run that command again to upgrade
an older update-only task. Expired tokens can recover after a long offline period. A pre-expiry
revocation is respected; explicitly reconnect if you want to authorize access again.

Run `codespace on mini t3 connect` to enroll the Mac mini. Each device administers its own loopback
T3 endpoint; credentials are not sent between hosts. `CODESPACE_T3_TOKEN` remains an external override
and is never rotated. `t3_app` and `t3_base_dir` configure a different installed bundle/data directory.
Provider OAuth/API credentials are separate: vendor revocation or a required interactive login cannot
be made permanent by Codespace.

### Single-session handoff (older bridge preview)

The Codespace T3 server extension is required; stock T3 does not yet expose the import endpoint.
On the machine that owns the native session, configure `t3_url` (default `http://127.0.0.1:3773`)
and `t3_token_file` in the Codespace config. Issue the token with that T3 host's
`auth session issue --token-only` command and store it in a file owned by you with mode `600`.
`CODESPACE_T3_TOKEN` can supply the token for one invocation. Tokens remain subject to T3 expiry and revocation.

```sh
code threads --json
codespace t3 import codex-work SESSION_ID
# Run the import on the machine that owns the provider files and workspace:
codespace on mini t3 import codex-default SESSION_ID
# Inspect the JSON payload without contacting T3:
code thread-export codex-work SESSION_ID --completed
```

Code records completed supervised sessions and verifies the transcript is unchanged before handoff.
`codespace t3 import` defaults to this proof of completion. An account lease prevents supervised Code
sessions from starting while the export and HTTP import are in progress; import also waits for you to
stop any other Code session using that account (it fails promptly rather than blocking the terminal).
For older sessions or provider CLIs launched outside Code, stop that CLI and explicitly use `--stopped`.
External CLI processes are not covered by Code's account leases. Continued editing in T3 and later CLI
resumption still require manual ownership coordination; automatic two-way ownership is not enabled.
T3 must have an enabled Claude or Codex provider instance pointing at the same account home.
History import is retryable and preserves the native session ID for continuation. It currently exports text
and image placeholders from completed sessions recorded by Code (or the 100 most recent sessions per account with `--stopped`); native tool history remains in
provider session files. Use `--model MODEL` when an older transcript has no model metadata.
Automatic session discovery/ownership transfer and provider configuration remain in development.


## Features


- **Six providers, many accounts each.** Every account gets its own isolated login.
- **Live usage limits.** Where the provider exposes them, you see 5-hour, weekly and credit windows with reset times, plus Codex's banked resets. A ★ marks the account with the most room left.
- **Automatic handoff when you run out.** When a supervised agent hits its limit, `code` closes it and asks where to continue. The conversation carries over.
- **Auto-effort for Codex.** Effort goes up when the agent is stuck and down for routine steps, without invalidating the prompt cache. It can optionally be decided by [Jev](#jev). [Details below.](#auto-effort-codex)
- **One-command updates.** `code update` updates code-switcher and every installed agent CLI. The picker tells you when a new version is out.
- **No dependencies.** It's one Python 3 file using only the standard library.

## Install

Requirements: macOS or Linux and Python 3.9+. Python 3.14+ is needed for auto-effort, because Codex compresses its requests with zstd. You also need the CLIs you want to use. `code add` offers to install a missing one.

```sh
curl -fsSL https://raw.githubusercontent.com/RJain12/code-switcher/main/install.sh | sh
```

Or clone the repo:

```sh
git clone https://github.com/RJain12/code-switcher.git
cd code-switcher && ./install.sh
```

This installs to `~/.local/bin/code`. To install somewhere else, set `PREFIX=/usr/local/bin`.

> **Heads up:** VS Code's shell command is also named `code`. If you have it installed, make sure `~/.local/bin` comes earlier on your `PATH`, or rename this script.

## Providers

| Provider | Runs | How accounts are kept apart | Usage shown | Auto-handoff out | Resume |
| --- | --- | --- | --- | --- | --- |
| **Claude** | `claude` | `CLAUDE_CONFIG_DIR` per account (browser login) | 5h / weekly windows | ✅ | native (Claude ↔ Claude/OpenRouter) |
| **Codex** | `codex` | `CODEX_HOME` per account (ChatGPT login) | 5h / weekly windows | ✅ | transcript |
| **OpenRouter** | `claude` against `openrouter.ai` | an API key per account (stored in the Keychain) plus its own `CLAUDE_CONFIG_DIR` | key limit and credit balance | ✅ | native (Claude ↔ OpenRouter) |
| **Grok** | `grok` (xAI Grok Build) | `GROK_HOME` per account | none (xAI has no usage API) | ✅ | native (Grok ↔ Grok) |
| **Cursor** | `cursor-agent` | one browser login per machine; extra accounts use API keys | best-effort, browser login only | ❌ | receives handoffs |
| **OpenCode** | `opencode` | `XDG_DATA_HOME` per account | none | ❌ | receives handoffs |

Notes:
- **OpenRouter** runs Claude Code through OpenRouter's Anthropic-compatible endpoint. Pick any model when you add the account, e.g. `anthropic/claude-opus-5.5`, `openai/gpt-6` or `x-ai/grok-5`, or leave it blank for Claude Code's default.
- **Cursor and OpenCode** store sessions in SQLite databases whose format isn't published, so `code` can't watch them for limit errors yet. You can still launch them, and they can receive a conversation handed off from another agent.

## Everyday use

Run `code`. You'll see every account with its usage. The selected account expands to show its **5 most recent threads**:

```
 › Claude     work      you@company.com [team]
                5h ███░░░░░░░  31% resets 2h14m     wk █████░░░░░  52% resets Fri 5am
        now  Refactor the billing webhooks                               ~/src/api
         2h  Why is the iOS build failing on CI?                         ~/src/app
         1d  Add retries to the fetcher                                  ~/src/api
```

- **Start fresh:** select an account and press **Enter** for a new session on it.
- **Resume:** move down onto a thread and press **Enter**. It reopens in the folder it was started in, with no `--resume <id>` to type.
- **Hand off (continue a thread on a different account):** select a thread, press **`h`**, then choose the target account. Pressing `h` on an account row hands off that account's latest thread.
  - Claude → Claude or OpenRouter reopens the same session with its full history.
  - Anything else starts the target agent with a transcript of the conversation so far and tells it to pick up where it stopped.
- **Automatic handoff:** when an agent launched through `code` runs out of usage mid-task, the same picker opens by itself. [Details below.](#running-out-of-usage-mid-conversation)
- **Jev on/off:** press **`J`** in the picker, or run `code jev on` / `code jev off`. The header shows `jev on` or `jev off`.

## Usage

| Command | What it does |
| --- | --- |
| `code` | Open the picker |
| `code add [provider] [name]` | Link a new account: browser login or API key, depending on the provider |
| `code list [--json]` | Print every account with its current usage |
| `code threads [--json] [--limit N]` | List native session IDs, accounts, transcript paths, and working directories for integrations |
| `code <id> [args…]` | Launch an account directly, e.g. `code claude-work` |
| `code best [provider] [args…]` | Launch the account with the most usage left, e.g. `code best codex` |
| `code login <id>` | Re-run login, or replace the API key |
| `code rm <id>` | Remove an account and delete its stored login or key |
| `code handoff` | Move your most recent session, with its context, to another account (same as `h` in the picker) |
| `code jev on\|off` | Let Jev choose Codex effort (same as `J` in the picker) |
| `code effort` | Auto-effort status: recent decisions, Jev calls and cost, cache hit rate |
| `code effort <id> on\|off` | Toggle auto-effort for a Codex account |
| `code effort <id> range LO HI` | Keep auto-effort within a range, e.g. `low max` (default `low xhigh`) |
| `code effort jev on [<openrouter-id>]` / `off` | Let Jev choose effort ([details](#jev)) |
| `code update [--self\|--providers]` | Update code-switcher and every installed CLI (`claude update`, `codex update`, `grok update`, `cursor-agent update`, `opencode upgrade`) |
| `code doctor` | Check Python, installs, logins, `PATH` conflicts and the Jev key |
| `code config auto-handoff N\|off` | After a limit hit, continue on the best account automatically after N seconds |
| `code -- [args…]` | Open the picker and pass the args to the chosen tool |

Keys in the picker:

| Key | Action |
| --- | --- |
| `↑`/`↓` or `j`/`k` | Move the selection |
| `Enter` | New session on the selected account, or resume the selected thread |
| `h` | Hand off the selected thread (or the account's latest thread) to another account |
| `J` | Turn Jev on or off |
| `1`–`9` | New session on that account |
| `a` | Add an account |
| `l` | Re-login the selected account |
| `d` | Remove the selected account |
| `e` | Toggle auto-effort (Codex) |
| `r` | Refresh usage |
| `q` or `Esc` | Quit |

## Running out of usage mid-conversation

Agents launched through `code` are supervised. `code` tails the session log the agent writes. When a real usage-limit error shows up, `code`:

1. waits a few seconds so you can see the agent's own message, then closes the agent;
2. opens a handoff picker with your other accounts, preselecting the one with the most room left;
3. continues the same conversation on the account you choose.

How the conversation moves depends on where it's going:

| From → to | How the context moves |
| --- | --- |
| Claude or OpenRouter → Claude or OpenRouter | **Native resume.** The session file is copied into the target account and opened with `claude --resume`. |
| Grok → Grok | **Native resume.** The session folder is copied and opened with `grok --resume`. |
| Anything else | **Transcript handoff.** The conversation is written to `~/.code-accounts/handoffs/*.md`: every message and tool call, with long tool outputs trimmed. The new agent is started with a prompt telling it to read that file and pick up where the last one stopped. |

What counts as a usage-limit error:

| Provider | Signal |
| --- | --- |
| Claude / OpenRouter | a `billing_error` API error, or a `rate_limit` error while a plan window is actually full (a brief rate-limit hiccup won't trigger a handoff) |
| Codex | an entry marked `usage_limit_exceeded` |
| Grok | `usage_limit_reached` or `usage_pool_exhausted` |

You also get a desktop notification, so you notice even when you're in another window. If the account that ran out is a Codex account with banked resets, the handoff screen says so; spending a reset in Codex is an alternative to switching. With `code config auto-handoff 20`, the handoff picker continues on the best account after a 20-second countdown unless you press a key.

If you press `q` in the handoff picker, nothing is lost. Run `code handoff` later to move the session then. Agents started outside `code` are never watched.

## Auto-effort (Codex)

Inspired by [Astra-Ares](https://github.com/miuuyy/Astra-Ares). Changing effort mid-conversation is only free when it doesn't invalidate the prompt cache:

| Provider | Effort change mid-conversation |
| --- | --- |
| OpenAI GPT-6 (Codex) | ✅ Cache-safe via `configuration_update` input items ([OpenAI docs](https://developers.openai.com/api/docs/guides/reasoning#change-reasoning-mid-conversation)) |
| Anthropic (Claude Code) | ❌ Changing the effort setting invalidates the messages cache |
| OpenRouter / Grok / Cursor / OpenCode | ❌ or unknown, so effort stays fixed |

So auto-effort applies to **Codex accounts with a ChatGPT login using GPT-6 models**. It's on by default; toggle it with `e` in the picker or `code effort <id> off`. How it works:

- **The proxy.** `code` starts a local proxy and points Codex at it with `-c model_provider=…`. Codex itself is unmodified, and your ChatGPT login passes straight through.
- **The rewrite.** Before each model call, the proxy picks an effort and inserts a `configuration_update` item. The top-level `reasoning.effort` is never changed.
- **Keeping the cache.** Codex resends the full history on every call and doesn't know about the inserted items. So the proxy re-inserts every earlier update at the same position each time. That keeps the request's prefix byte-identical, which is what the prompt cache needs.
- **How it decides:**
  - A new user message resets to your configured effort.
  - A run of 3 read-only steps (`ls`, `cat`, `rg`, `git diff`…) drops one level.
  - Repeated failing tool calls, or the same call returning the same result, raise one level per step, at most two above your setting.
  - Success brings it back.
  - A level is held for at least 2 steps before stepping down.
- **Supported levels** come from Codex's own model catalog: `low` to `ultra` on GPT-6. Choices are clamped to the account's range (`code effort <id> range`), which defaults to `low` to `xhigh` so costly `max`/`ultra` steps are opt-in.
- **Failing safe:**
  - If the backend ever rejects a request with an inserted update, the proxy resends the original and turns auto-effort off for that session.
  - A compaction (history rewritten) resets the tracking.
  - Non-GPT-6 models pass through untouched.
- **Logging.** Every decision, with token and cached-token counts, goes to `~/.code-accounts/effort.log`. Run `code effort` to see the recent ones and confirm the cache is holding.

### Jev

The local rules are simple. [Jev](https://openrouter.ai/typesafe/jev-1.13) is a model trained for this exact decision: which effort is enough for the next step, and for how many steps that stays true. Turn it on with `code effort jev on`. It uses the key from one of your OpenRouter accounts, or `OPENROUTER_API_KEY`.

When Jev is enabled, `code` installs a pinned [Astra-Ares](https://github.com/miuuyy/Astra-Ares) native Codex patch on first use. The first build needs Rust and can take several minutes. Jev sessions run that separate binary with the selected account's existing `CODEX_HOME`; the normal `codex` command is untouched. Confirmed effort changes appear in Codex's chat transcript (for example, `Jev LOW → HIGH ✓ APPLIED`). Turn Jev off to use the normal Codex binary again. An already-running session keeps its current binary until it exits and is resumed through `code`.

How `code` uses it:
- **Leases.** Ares keeps a choice for 1, 2, 5 or 10 generations. New input or a tool failure ends the lease early.
- **Confirmation.** The in-chat `APPLIED` message is emitted only after native Codex confirms the chosen effort.
- **Errors.** Ares reports provider failures visibly; it does not silently use the local heuristic. When Jev is off, `code` uses its own proxy and local heuristic.
- **Logs.** Native decisions are saved under `~/.code-accounts/astra-ares/data/runs/`. `code effort` reports the older proxy's log and cache statistics.

**Privacy:** Jev receives bounded task context, including the current request and recent public tool results. See [Ares's context limits](https://github.com/miuuyy/Astra-Ares/blob/main/docs/architecture.md). This is why Jev is off until you enable it.

## Known limitations

### Benchmark Jev against fixed effort

Run `python3 bench/game_compare.py` to build the same standalone browser game twice: once with fixed medium effort and once with Jev, using the same patched Codex build. Set `BENCH_ACCOUNT=codex-<name>` for a different account. The command saves playable HTML files, raw Codex events, and a JSON metrics table under `bench/artifacts/`. It measures wall time, input/cache/output tokens, Jev charges, and an estimated GPT-6 Sol API-equivalent cost. The API equivalent is not an actual charge for ChatGPT subscription sessions. Play and inspect both games before judging quality; a single pair cannot establish average savings.

- **Codex sessions and the resume picker.** Sessions started with local auto-effort when Jev is off use the provider name `code_switcher`, so they show up when you resume through `code` but not in a plain `codex resume` picker. `codex resume <id>` still works. Jev's native patched Codex uses the normal OpenAI provider.
- **Dynamic effort acceptance.** The local proxy used with Jev off falls back to ordinary Codex if an inserted update is rejected. Jev-on sessions use Ares's native checkpoint instead.
- **Cursor and OpenCode.** They can't auto-hand-off *out* yet; see [Providers](#providers).
- **Usage endpoints are undocumented.** They come from the official apps and may change. Failures show as an error on that account and never break launching.

## How it works

Each account gets its own directory under `~/.code-accounts/<provider>/<name>/` (override the location with `CODE_ACCOUNTS_DIR`), and the CLI is launched with the matching env var set: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GROK_HOME`, `CURSOR_CONFIG_DIR` or `XDG_DATA_HOME`. Shared settings, skills, plugins, `config.toml` and `AGENTS.md` are symlinked from your default directory, so every account behaves the same way. Claude's user-level MCP servers live in `~/.claude.json`, outside the config directory, so they're copied into each account at launch. Account changes are made under a file lock, so several `code` windows can run at once without losing edits.

Logins that already exist on your machine are adopted as **`default`** accounts and used exactly where they live. `code` never copies them, because the tools rotate their saved logins and copies would break. API keys (OpenRouter, Cursor) go in the macOS Keychain under the service `code-switcher`. On Linux they're stored in a `0600` file inside the account directory.

### Where the usage numbers come from

| Provider | Endpoint |
| --- | --- |
| Claude | `GET api.anthropic.com/api/oauth/usage`, using the account's OAuth token |
| Codex | `GET chatgpt.com/backend-api/wham/usage`, using the ChatGPT token from `auth.json` |
| OpenRouter | `GET openrouter.ai/api/v1/key` and `/api/v1/credits` |
| Cursor | `api2.cursor.sh` DashboardService `GetCurrentPeriodUsage` (best-effort; undocumented) |

These are the endpoints the official apps use; most aren't documented public APIs, so they may change. A failing request shows an error for that account and never crashes the picker. Results are cached for 90 seconds.

### Privacy

`code` adds only this network traffic:
- the usage requests above;
- the auto-effort proxy relaying Codex's own traffic to `chatgpt.com`;
- a daily version check against this repo;
- Jev decisions, only if you enable Jev.

Everything goes directly to the provider, using your own credentials.

## Uninstall

```sh
rm ~/.local/bin/code
rm -rf ~/.code-accounts   # also deletes the logins of accounts added through code
```

Your default logins (`~/.claude`, `~/.codex`, `~/.grok`, and so on) are not affected.

## Development

```sh
python3 -m unittest discover -s tests -v
```

The suite covers:
- storage under concurrent writers;
- the cache-prefix invariant across multi-step sessions;
- Jev lease, fallback and breaker logic;
- secret redaction;
- the proxy over real HTTP against a fake upstream, including zstd, 400 fallback and 502;
- limit detection, transcript export and self-update;
- end-to-end handoffs driven through a pseudo-terminal with fake agent CLIs.

CI runs it on macOS and Linux with Python 3.9, 3.12 and 3.14.

## License

MIT
