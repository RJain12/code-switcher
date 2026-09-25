# code-switcher

**One command to pick between your Claude Code and Codex accounts, with each account's live usage limits shown so you can choose the one with headroom.**

```
  code pick an account to launch

 › Claude  work      you@company.com [team]  ★ most headroom
               5h ███░░░░░░░  31% resets 2h14m     wk █████░░░░░  52% resets Fri 5am

   Claude  personal  you@gmail.com [max]
               5h ██████████ 100% resets 41m       wk ████████░░  84% resets Mon 9am

   Codex   default   you@company.com [pro]
               wk ██████████ 100% resets Sat 1am

  enter launch  a add  d remove  l re-login  r refresh  q quit
```

If you hit rate limits on one subscription, you can keep working on another. `code` keeps several Claude and Codex logins signed in at the same time and launches whichever one you pick.

## Features

- **Interactive picker.** Run `code`, use the arrow keys (or `j`/`k`), and press Enter, or press `1`–`9` to launch an account directly.
- **Multiple accounts per tool.** Link as many Claude Code and Codex accounts as you like. They all stay logged in at once.
- **Automatic handoff when you run out.** If an agent launched through `code` hits its usage limit, `code` closes it and asks which account to continue on. The conversation carries over with it.
- **Live usage limits.** Each account shows its 5-hour and weekly windows, the percent used, and when each window resets. A ★ marks the account with the most room left.
- **Shared setup.** New accounts reuse your existing settings, skills, plugins, `config.toml` and `AGENTS.md`, so every account behaves the same way.
- **No dependencies.** It's a single Python 3 file that uses only the standard library.
- **Passthrough.** `code -- --resume` opens the picker, then passes `--resume` to the tool you choose.

## Install

Requirements: macOS or Linux, Python 3.9+, plus [`claude`](https://docs.claude.com/en/docs/claude-code) and/or [`codex`](https://github.com/openai/codex) on your `PATH`.

```sh
curl -fsSL https://raw.githubusercontent.com/RJain12/code-switcher/main/install.sh | sh
```

Or clone the repo:

```sh
git clone https://github.com/RJain12/code-switcher.git
cd code-switcher && ./install.sh
```

This installs to `~/.local/bin/code`. To install somewhere else, set `PREFIX=/usr/local/bin`.

> **Heads up:** VS Code's shell command is also named `code`. If you have it installed, make sure `~/.local/bin` comes earlier on your `PATH`, or rename this script (for example to `ai`).

## Usage

| Command | What it does |
| --- | --- |
| `code` | Open the picker |
| `code add [claude\|codex] [name]` | Link a new account and run that tool's login flow |
| `code list` | Print every account with its current usage |
| `code <id> [args…]` | Launch an account directly, e.g. `code claude-work` |
| `code login <id>` | Re-run login for an account |
| `code rm <id>` | Remove an account and delete its stored login |
| `code handoff` | Move your last session, with its context, to another account |
| `code -- [args…]` | Open the picker and pass the args to the chosen tool |

Keys in the picker:

| Key | Action |
| --- | --- |
| `↑`/`↓` or `j`/`k` | Move the selection |
| `Enter` or `1`–`9` | Launch an account |
| `a` | Add an account |
| `l` | Re-login the selected account |
| `d` | Remove the selected account |
| `r` | Refresh usage |
| `q` or `Esc` | Quit |

## Running out of usage mid-conversation

Agents launched through `code` (from the picker or with `code <id>`) are supervised. `code` tails the session log the agent writes. When a real usage-limit error shows up there, `code`:

1. waits a few seconds so you can see the agent's own message, then closes the agent;
2. opens a handoff picker with your other accounts, preselecting the one with the most room left;
3. continues the same conversation on the account you choose.

What happens to the conversation depends on where it's going:

| From → to | How the context moves |
| --- | --- |
| Claude → Claude (another account) | **Native resume.** The session file is copied into the new account and opened with `claude --resume <id>`, so the full history, tool calls included, is intact. |
| Anything → Codex, or Codex → Claude | **Transcript handoff.** The whole conversation is written to `~/.code-accounts/handoffs/<time>-<account>.md` (every message and tool call, with very long tool outputs trimmed). The new agent is started with a prompt telling it to read that file, plus the raw session log, and pick up where the last one stopped. |

What counts as a usage-limit error:

- **Claude:** an API error entry of type `billing_error`, or a `rate_limit` error while the account's 5-hour or weekly window is actually full. A brief rate-limit hiccup on its own won't trigger a handoff.
- **Codex:** an entry marked `usage_limit_exceeded`.

If you press `q` in the handoff picker, nothing is lost. Run `code handoff` later to move the session then, or any time you want to switch accounts before a limit hits.

Agents you start directly with `claude` or `codex`, outside of `code`, are never watched or touched.

## How it works

Both CLIs can read their state from a custom directory:

| Tool | Env var | Default |
| --- | --- | --- |
| Claude Code | `CLAUDE_CONFIG_DIR` | `~/.claude` |
| Codex | `CODEX_HOME` | `~/.codex` |

Each account you add gets its own directory under `~/.code-accounts/<tool>/<name>/`. `code` launches the tool with the matching env var set, so the logins stay separate. Shared config files are symlinked from your default directory, so each account keeps its own logins and history but uses the same settings.

The logins you already have are listed as the **`default`** accounts and are used exactly where they live. `code` never copies them, because the tools rotate their saved logins when they refresh, and copies would break.

### Where the usage numbers come from

- **Claude:** `GET https://api.anthropic.com/api/oauth/usage`, called with the account's OAuth token. On macOS, Claude stores the token in the Keychain. For a custom config dir the entry is named `Claude Code-credentials-<sha256(dir)[:8]>`. On Linux, the token is in `<dir>/.credentials.json`.
- **Codex:** `GET https://chatgpt.com/backend-api/wham/usage`, called with the ChatGPT token from `<CODEX_HOME>/auth.json`.

These are the same endpoints the official apps use for their own usage displays. They aren't documented public APIs, so they may change. If a request fails, the picker shows the error for that account and keeps working. Results are cached for 90 seconds in `~/.code-accounts/usage-cache.json`. If a token has expired, launch that account once and the tool will refresh it.

### Privacy

Nothing leaves your machine except those two usage requests, sent directly to Anthropic and OpenAI with your own tokens. `code` never writes tokens to its own files. It reads them from where the CLIs keep them.

## Uninstall

```sh
rm ~/.local/bin/code
rm -rf ~/.code-accounts   # also deletes the logins of accounts added through code
```

Your default `~/.claude` and `~/.codex` logins are not affected.

## License

MIT
