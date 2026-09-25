# code-switcher

**One command to pick between your AI coding agent accounts (Claude Code, Codex, OpenRouter, Grok, Cursor, OpenCode), with each account's live usage limits shown so you can choose the one with headroom.**

```
  code pick an account to launch

 › Claude     work      you@company.com [team]  ★ most headroom
                5h ███░░░░░░░  31% resets 2h14m     wk █████░░░░░  52% resets Fri 5am

   Codex      default   you@company.com [pro] ⚡auto-effort
                wk ██████████ 100% resets Sat 1am

   OpenRouter or-key    anthropic/claude-opus-5.5 [$41.20 credits left]
                bal ██░░░░░░░░  18%

   Grok       personal
                Grok has no usage API; limit hits are still detected

  enter launch  a add  d remove  l re-login  e auto-effort  r refresh  q quit
```

If you hit rate limits on one subscription, you can keep working on another. `code` keeps many logins signed in at the same time and launches whichever one you pick. When an agent runs out of usage mid-task, `code` hands the conversation to another account. For Codex, it also adjusts reasoning effort step by step without breaking the prompt cache.

## Features

- **Six providers, many accounts each.** Every account gets its own isolated login.
- **Live usage limits.** Where the provider exposes them, you see 5-hour, weekly and credit windows with reset times. A ★ marks the account with the most room left.
- **Automatic handoff when you run out.** When a supervised agent hits its limit, `code` closes it and asks where to continue. The conversation carries over.
- **Auto-effort for Codex.** Effort goes up when the agent is stuck and down for routine steps, without invalidating the prompt cache. [Details below.](#auto-effort-codex)
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

## Usage

| Command | What it does |
| --- | --- |
| `code` | Open the picker |
| `code add [provider] [name]` | Link a new account: browser login or API key, depending on the provider |
| `code list` | Print every account with its current usage |
| `code <id> [args…]` | Launch an account directly, e.g. `code claude-work` |
| `code login <id>` | Re-run login, or replace the API key |
| `code rm <id>` | Remove an account and delete its stored login or key |
| `code handoff` | Move your last session, with its context, to another account |
| `code effort [<id> on\|off]` | Show recent auto-effort decisions, or toggle auto-effort for a Codex account |
| `code -- [args…]` | Open the picker and pass the args to the chosen tool |

Keys in the picker:

| Key | Action |
| --- | --- |
| `↑`/`↓` or `j`/`k` | Move the selection |
| `Enter` or `1`–`9` | Launch an account |
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
- **Supported levels** come from Codex's own model catalog: `low` to `ultra` on GPT-6.
- **Failing safe:**
  - If the backend ever rejects a request with an inserted update, the proxy resends the original and turns auto-effort off for that session.
  - A compaction (history rewritten) resets the tracking.
  - Non-GPT-6 models pass through untouched.
- **Logging.** Every decision, with token and cached-token counts, goes to `~/.code-accounts/effort.log`. Run `code effort` to see the recent ones and confirm the cache is holding.

## How it works

Each account gets its own directory under `~/.code-accounts/<provider>/<name>/`, and the CLI is launched with the matching env var set: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GROK_HOME`, `CURSOR_CONFIG_DIR` or `XDG_DATA_HOME`. Shared settings, skills, plugins, `config.toml` and `AGENTS.md` are symlinked from your default directory, so every account behaves the same way.

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

The only network traffic `code` adds is those usage requests, and the auto-effort proxy relaying Codex's own traffic to `chatgpt.com`. Everything goes directly to the provider, using your own credentials.

## Uninstall

```sh
rm ~/.local/bin/code
rm -rf ~/.code-accounts   # also deletes the logins of accounts added through code
```

Your default logins (`~/.claude`, `~/.codex`, `~/.grok`, and so on) are not affected.

## License

MIT
