---
name: muse-cli
description: Manage a personal muse.ai agent from the terminal (send messages, read chats, watch live events, feed/goals/ideas/sessions). Use when asked to message, check, or automate someone's Muse personal AI, work with muse.ai chats/threads/feed/goals outside the browser, or when the muse-cli tool itself needs installing or auth setup.
---

# muse-cli: drive a muse.ai personal agent from the terminal

Assume a bare machine: only this skill is present. No repo clone, no
dependencies, no auth. Work top to bottom; stop at the first step that
fails and report it.

The `muse-cli` package (on PyPI) talks to the muse.ai personal gateway
directly. No browser needed after the one-time cookie export. Every command
prints JSON.

## 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/nikships/muse-cli/main/install.sh | bash
```

This installs the CLI from PyPI with `uv tool install muse-cli` (its own
isolated environment) and this skill (to `~/.agents/skills/muse-cli`). CLI
only? `uv tool install muse-cli`, `pipx install muse-cli`, or
`pip install muse-cli` all work. The command is `muse-cli` (`muse` clashes
with Muse Code, don't use it). Verify before continuing:

```bash
command -v muse-cli
muse-cli --help >/dev/null && echo cli-ok   # proves the install + deps resolve
```

## 2. Auth

The user must be logged in to https://muse.ai/ in Chrome first. Then:

```bash
muse-cli auth export     # saves muse.ai cookies to ~/.config/muse-cli/cookies.txt (0600)
test -s ~/.config/muse-cli/cookies.txt && echo auth-ok
```

`auth export` pulls cookies from a running Chrome via
[agent-browser](https://github.com/nikships/foundry) (`npm i -g agent-browser`
if it is missing). No Chrome? Copy the `muse.ai` cookies by hand (DevTools →
Application → Cookies; needs `hatch_sess`) into
`~/.config/muse-cli/cookies.txt` as Netscape-jar or `name=value; ...` text.

Access and gateway tokens are fetched fresh on every run; only cookies
persist. When commands later fail with `auth error`, cookies expired:
re-run `auth export`.

## 3. Verify end to end

```bash
muse-cli status    # VM id, chat count, unread, identity: install + auth proven
```

## Everyday commands

```bash
muse-cli threads                                        # main chat + side chats (session_ids)
muse-cli history --limit 5                              # recent main-chat messages
muse-cli history --thread <session-id> --limit 5        # one side chat
muse-cli send "message" --wait 120                      # send + wait for the reply
muse-cli send "message" --thread <session-id> --wait 0  # fire and forget to a side chat
muse-cli watch --timeout 60                             # tail live agent events
muse-cli feed --limit 5
muse-cli goals
muse-cli ideas
muse-cli unread
muse-cli seen <thread-id>
```

Management (visible side effects, confirm with the user first when destructive):

```bash
muse-cli feed-react <unit-id> love
muse-cli idea-exec <idea-id>          # the agent acts on the idea (real work)
muse-cli session-start --title "x"    # new side chat
muse-cli session-rename <id> "title"  # also: pin, unpin, archive, unarchive, delete
muse-cli wake
```

## Escape hatch

`muse-cli raw <method> --body '{...}' [--param k=v]` calls any of the 258
gateway methods in `routes.json`. Prefer the named commands above; use raw
only for methods with no wrapper.

## Gotchas

- `send` returns `{"sent": true, "reply": {...}}`, polling history until the
  reply lands (up to `--wait`). If `reply` is missing, the agent was slower
  than the wait: the message still landed, confirm with `history`. The reply
  is matched as a genuine answer, not background chatter.
- `send --wait 0` is fire-and-forget (no polling).
- `history` without `--thread` reads the main chat only.
- The gateway API is unversioned. Whole classes of calls failing at once means
  the protocol drifted: see `docs/PROTOCOL.md` for the re-derivation notes,
  don't guess at crypto or framing.
- Respect rate limits. Writes (send, react, execute, session ops) act as the
  user in their agent: announce them before running, never loop them.
