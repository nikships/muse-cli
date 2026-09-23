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

The CLI stores the user's muse.ai browser login at
`~/.config/muse-cli/cookies.txt` (mode 0600). Chrome hides those cookies
until remote debugging is on. Walk the user through the steps below and wait
for them. Do not run `muse-cli auth export` before they say the Chrome
switch is on and a logged-in muse.ai tab is open.

Access and gateway tokens are fetched fresh on every run; only cookies
persist. When a later command fails with `auth error`, the cookies expired:
repeat 2b (or 2c).

### 2a. Cookie reader

```bash
command -v node >/dev/null && node --version
command -v npm >/dev/null && npm --version
command -v agent-browser >/dev/null && agent-browser --version
```

If `agent-browser` is missing and `npm` works:

```bash
npm i -g agent-browser
agent-browser --version   # must print a version
command -v agent-browser  # must print a path
```

`EACCES` from `npm i -g` means npm cannot write its global bin directory.
Stop and tell the user. They fix it with an npm prefix they own
(https://docs.npmjs.com/resolving-eacces-permissions-errors-when-installing-packages-globally)
or by installing with the same rights they use for other global npm tools.
Do not sudo unless they tell you to.

If `node` or `npm` is missing, stop. Tell them to install Node.js LTS from
https://nodejs.org, open a new terminal, and come back. Offer 2c if they
would rather not install Node.

### 2b. Chrome, then export

Tell the user to do all of this in the Google Chrome window they already
use for muse.ai. Needs Chrome 144 or newer. Wait until they confirm:

1. Address bar: `chrome://inspect/#remote-debugging`
2. Turn on remote debugging ("Allow remote debugging for this browser instance").
3. Open https://muse.ai/ and log in. Leave that tab in front. The export
   reads the active tab.

Then:

```bash
muse-cli auth export
test -s ~/.config/muse-cli/cookies.txt && echo auth-ok
```

If Chrome shows an Allow prompt, they click Allow. If the command failed
before that click, run it once more.

Success is a line like `saved N muse.ai cookies to ~/.config/muse-cli/cookies.txt`.

If it fails, the CLI prints the next step. Map it like this, and do not retry
in a loop:

- "No running Chrome" or "remote-debugging-port": the switch in step 2 is
  off, or they are in a different Chrome. Send them back to the steps above.
  Do not tell them to launch Chrome with `--remote-debugging-port`. That
  opens another profile, and it does not have their muse.ai login.
- "no muse.ai tab": Chrome connected. They still need https://muse.ai/ open
  and in front in that same window.
- "no hatch_sess" / "do not include hatch_sess": the tab is open and they
  are logged out. The cookies file on disk was kept.
- "daemon already running": `agent-browser close`, then `muse-cli auth export` once.
- `agent-browser` not found: back to 2a.

### 2c. Copy cookies by hand

Use this when Node is unavailable, or the user does not want remote debugging on.

1. They are logged in at https://muse.ai/ in Chrome.
2. DevTools (F12) → Application → Cookies → `https://muse.ai`.
3. Write one line to `~/.config/muse-cli/cookies.txt`. `hatch_sess` is required.
   Separate cookies with `; `:

```
hatch_sess=VALUE; other_name=other_value
```

A Netscape jar or `{"hatch_sess": "..."}` JSON also works.

4. `chmod 600 ~/.config/muse-cli/cookies.txt`
5. `test -s ~/.config/muse-cli/cookies.txt && echo auth-ok`, then `muse-cli status`.
   Stop if status fails and report the error text.

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
