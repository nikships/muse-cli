<div align="center">

# muse-cli

Talk to your personal muse.ai AI agent from the terminal.

[![PyPI](https://img.shields.io/pypi/v/muse-cli?style=for-the-badge)](https://pypi.org/project/muse-cli/)
[![Python](https://img.shields.io/pypi/pyversions/muse-cli?style=for-the-badge)](https://pypi.org/project/muse-cli/)
[![Downloads](https://img.shields.io/pepy/dt/muse-cli?style=for-the-badge)](https://pepy.tech/project/muse-cli)
[![License: MIT](https://img.shields.io/github/license/nikships/muse-cli?style=for-the-badge)](https://github.com/nikships/muse-cli/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/nikships/muse-cli?style=for-the-badge)](https://github.com/nikships/muse-cli/stargazers)

![muse-cli hero](https://raw.githubusercontent.com/nikships/muse-cli/main/assets/hero.webp)

</div>

## What is this?

A command-line client for your personal muse.ai AI agent: chat from the terminal, automate it with scripts, and manage side chats, feed, goals, ideas, and sessions without opening a browser. It speaks the app's own gateway protocol directly: HTTPS auth, then an encrypted Noise-XX WebSocket to your personal VM.

- **Chat from the shell:** send a message and get the agent's reply back as JSON.
- **Script it:** every command prints JSON, so it pipes into `jq`, cron jobs, and other AI agents.
- **Full coverage:** named commands for the common tasks, plus a `raw` escape hatch for all 258 gateway methods.
- **Agent-ready:** ships an agent skill so coding agents can drive your muse.ai agent for you.

## Quick Start

```bash
uv tool install muse-cli      # or: pipx install muse-cli   /   pip install muse-cli
```

Then log in and check the connection:

```bash
# 1. Install agent-browser (reads cookies from Chrome):
npm i -g agent-browser
# 2. Log in to https://muse.ai/ in Chrome
# 3. Export your session (one time; re-run when it expires):
muse-cli auth export

muse-cli status
```

Want the agent skill too? The installer sets up the CLI and copies the skill
to `~/.agents/skills/muse-cli`:

```bash
curl -fsSL https://raw.githubusercontent.com/nikships/muse-cli/main/install.sh | bash
```

Upgrade with `uv tool upgrade muse-cli`, remove with `uv tool uninstall muse-cli`.

The command is `muse-cli`, not `muse`, because `muse` clashes with Muse Code
on many machines.

## Usage

```bash
muse-cli threads                                  # main chat + side chats
muse-cli history --limit 5                        # recent messages
muse-cli history --thread <session-id> --limit 5  # one side chat
muse-cli send "summarize my unread" --wait 120    # send + wait for the reply
muse-cli watch --timeout 60                       # tail live agent events

muse-cli feed --limit 5
muse-cli feed-react <unit-id> love
muse-cli goals
muse-cli ideas
muse-cli idea-exec <idea-id>                      # agent acts on the idea

muse-cli session-start --title "trip planning"    # new side chat
muse-cli session-rename <id> "new title"
muse-cli session-archive <id>                     # also: pin, unpin, unarchive, delete
muse-cli seen <thread-id>
muse-cli wake
muse-cli raw <method> --body '{}'                 # escape hatch: any of 258 gateway methods
```

Every command prints JSON. Your VM is auto-discovered from your session, and a
random device id is generated on first run.

Pipe it into other tools:

```bash
muse-cli send "what's on my calendar today?" | jq -r .reply.text
```

## How it works

![how muse-cli connects](https://raw.githubusercontent.com/nikships/muse-cli/main/assets/how-it-works.webp)

![muse-cli connection flow](https://raw.githubusercontent.com/nikships/muse-cli/main/assets/flow.webp)

See [docs/PROTOCOL.md](https://github.com/nikships/muse-cli/blob/main/docs/PROTOCOL.md)
for the full protocol notes, including the method table and the server quirks
found during reverse engineering.

## Documentation

| Resource | Description |
|----------|-------------|
| [skills/muse-cli/SKILL.md](https://github.com/nikships/muse-cli/blob/main/skills/muse-cli/SKILL.md) | Agent skill: install check, auth setup, command reference |
| [docs/PROTOCOL.md](https://github.com/nikships/muse-cli/blob/main/docs/PROTOCOL.md) | Gateway protocol reference: auth chain, Noise transport, framing, method quirks |
| [routes.json](https://github.com/nikships/muse-cli/blob/main/src/muse_cli/routes.json) | All 258 gateway methods with paths and services |
| `muse-cli raw --help` | Escape hatch for calling any gateway method directly |

## Development

```bash
git clone https://github.com/nikships/muse-cli.git
cd muse-cli
uv run muse-cli --help
```

```
muse-cli/
assets/              README artwork (generated with Muse Image)
docs/PROTOCOL.md     protocol reference for re-derivation
skills/muse-cli/     agent skill
src/muse_cli/
  cli.py             argument parsing and all commands
  gateway.py         gateway client (auth, Noise transport, subscriptions)
  routes.json        258 gateway methods extracted from the web client
  desc0.bin          protobuf descriptors for the wire framing
  desc1.bin
install.sh           CLI + skill installer
pyproject.toml
```

## Setup notes

- `auth export` reads cookies from a running Chrome via
  [agent-browser](https://github.com/nikships/foundry) (`npm i -g agent-browser`).
  No Chrome? Copy your `muse.ai` cookies into `~/.config/muse-cli/cookies.txt`
  by hand (Netscape jar or `name=value; ...` format, needs `hatch_sess`).
- Cookies live at `~/.config/muse-cli/cookies.txt` (mode 600). Access and
  gateway tokens are fetched fresh on every run, nothing long-lived is stored.
- Respect muse.ai's terms and rate limits. Internal APIs are unversioned and
  can change; if calls fail, re-derive from a fresh app bundle.

## Contributing

Issues and PRs welcome. If the protocol drifts, the most useful contribution
is a note of which method broke and the new server error text.

<a href="https://github.com/nikships/muse-cli/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=nikships/muse-cli" />
</a>

## License

MIT. See [LICENSE](https://github.com/nikships/muse-cli/blob/main/LICENSE).

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=nikships/muse-cli&type=Date)](https://star-history.com/#nikships/muse-cli&Date)

</div>
