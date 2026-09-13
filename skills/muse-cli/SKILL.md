---
name: muse-cli
description: Manage a personal muse.ai agent from the terminal (send messages, read chats, watch live events, feed/goals/ideas/sessions). Use when asked to message, check, or automate someone's Muse personal AI, work with muse.ai chats/threads/feed/goals outside the browser, or when the muse-cli tool itself needs installing or auth setup.
---

# muse-cli: drive a muse.ai personal agent from the terminal

The repo ships a CLI (`cli.py`) that talks to the muse.ai personal gateway
directly. No browser needed after the one-time cookie export. Every command
prints JSON.

## 0. Quick check: is it ready?

```bash
command -v muse-cli || ls ~/muse-cli/cli.py            # installed?
python3 -c "import curl_cffi, noise, google.protobuf"  # deps?
test -s ~/.config/muse-cli/cookies.txt && echo auth-ok # auth?
```

- CLI missing → follow **Install** below, then re-run this check.
- Deps missing → `pip install -r <repo>/requirements.txt`.
- Auth missing/expired (commands fail with `auth error`) → follow **Auth**.

## Install

```bash
git clone https://github.com/nikships/muse-cli.git ~/muse-cli
pip install -r ~/muse-cli/requirements.txt
ln -s ~/muse-cli/cli.py ~/bin/muse-cli   # 'muse' clashes with Muse Code, don't use it
muse-cli status                          # verifies install + auth together
```

## Auth

One-time per browser login. The user must be logged in to https://muse.ai/
in Chrome first.

```bash
muse-cli auth export     # pulls muse.ai cookies via agent-browser into ~/.config/muse-cli/cookies.txt (0600)
```

No Chrome or no agent-browser? Copy the `muse.ai` cookies by hand (DevTools →
Application → Cookies; needs `hatch_sess`) into `~/.config/muse-cli/cookies.txt`
as Netscape-jar or `name=value; ...` text. Access and gateway tokens are
fetched fresh on every run; only cookies persist. When commands fail with
`auth error`, cookies expired: re-run `auth export`.

## Everyday commands

```bash
muse-cli status
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

- `send` returns `{"sent": true, "reply": {...}}`. If `reply` is missing after
  `--wait`, the message still landed: confirm with `history`.
- `history` without `--thread` reads the main chat only.
- The gateway API is unversioned. Whole classes of calls failing at once means
  the protocol drifted: see `docs/PROTOCOL.md` for the re-derivation notes,
  don't guess at crypto or framing.
- Respect rate limits. Writes (send, react, execute, session ops) act as the
  user in their agent: announce them before running, never loop them.
