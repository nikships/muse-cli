# AGENTS.md

## Project overview

`muse-cli` is a Python command-line client for a personal muse.ai AI agent. It
chats with the agent, tails its events, downloads files it makes, and manages
side chats, feed, goals, ideas, and sessions. It speaks muse.ai's own gateway
protocol directly: HTTPS auth with browser cookies, then an encrypted
Noise-XX WebSocket to the user's personal VM, carrying protobuf envelopes.

- Published on PyPI as `muse-cli`. The command is `muse-cli` (never `muse`,
  which clashes with Muse Code).
- Python 3.10+. Runtime dependencies: `curl_cffi`, `noiseprotocol`,
  `protobuf`. Build backend: hatchling.
- The gateway API is unversioned and reverse engineered. Read
  `docs/PROTOCOL.md` before touching `gateway.py`, and do not guess at crypto
  or framing.

## Repository map

- `src/muse_cli/cli.py`: argparse setup (`main()`), every `cmd_*` command,
  config loading, and `auth export` (drives Chrome through `agent-browser`).
- `src/muse_cli/gateway.py`: `Gateway` client (tokens, Noise transport,
  request/subscribe/download), `AuthError`, `GatewayError`, `load_cookies`.
- `src/muse_cli/chat.py`: the interactive REPL (`muse-cli` with no command).
- `src/muse_cli/update.py`: daily PyPI update notice and `muse-cli update`,
  which also refreshes an installed skill.
- `src/muse_cli/skill.py`: copies the bundled `SKILL.md` to
  `~/.agents/skills/muse-cli` (`MUSE_CLI_SKILLS` overrides the root). The wheel
  carries `skills/muse-cli/SKILL.md` as `muse_cli/SKILL.md` via
  `force-include` in `pyproject.toml`, so keep that mapping.
- `src/muse_cli/routes.json`, `desc0.bin`, `desc1.bin`: the 258 gateway
  methods and the protobuf descriptors for the framing. Generated data, so do
  not hand-edit.
- `src/muse_cli/__init__.py`: holds `__version__`, the only place the version
  lives. `pyproject.toml` reads it.
- `tests/`: `unittest` tests, no network needed.
- `scripts/bump_version.py`: release version bump used by CI.
- `skills/muse-cli/SKILL.md`: the agent skill that `install.sh` copies to
  `~/.agents/skills/muse-cli`.
- `install.sh`: installs the CLI with `uv tool` plus the skill.
- `site/`, `firebase.json`, `.firebaserc`: static landing page for Firebase
  Hosting project `muse-cli-web`. No workflow deploys it.

## Setup and run

- Run from a checkout: `uv run muse-cli --help`
- `uv run` writes a `uv.lock`. It is gitignored because the repo does not
  track one, so do not force-add it.
- Real commands need a logged-in cookie file at
  `~/.config/muse-cli/cookies.txt`. Without it they exit with an
  `auth error`. Use unit tests and `--help` for checks that must not touch the
  user's account.
- State lives in `~/.config/muse-cli/` (`config.json`, `cookies.txt`,
  `chat.json`, `chat_history`, `update.json`).
- Environment variables: `MUSE_VM_ID` (skip VM discovery), `MUSE_NODE_ID`
  (fixed device id), `MUSE_NO_UPDATE_CHECK=1` (silence the update notice),
  `MUSE_CLI_SKILLS` (skills root used by `update`, same as `install.sh`).

## Testing

- All tests: `uv run python -m unittest discover -s tests -v`
- One file: `uv run python -m unittest tests.test_media -v`
- One test:
  `uv run python -m unittest tests.test_chat.DeletedSideChatRecoveryTest.test_is_not_found -v`
- Tests use `unittest` and `unittest.mock` and never call muse.ai. Keep it
  that way: mock `Gateway` and the network.
- `tests/test_release.py` builds throwaway git repos, so it needs `git` on PATH.
- No linter, formatter, or type checker is configured. Do not add one in an
  unrelated change.
- Add or update a test for each behavior change.
- After touching argument parsing or packaging, also run
  `uv run muse-cli --version`, `--help`, and `chat --help`. CI smoke-tests the
  built wheel with the same three commands.

## Code style

- Match the surrounding code: plain, standard-library-first Python, no type
  annotations, comments only where the reason is not obvious.
- Commands live in `cli.py` as `cmd_<name>(args)` and are registered in
  `main()`. They print JSON through `out()`. The interactive chat is the
  exception: it prints plain text, one message per line, for screen readers.
- Keep stdout for machine-readable output and stderr for notices and errors.
  Users pipe the output into `jq` and other agents.
- Exit codes come from `main()`: `2` for `AuthError` or bad arguments, `3` for
  `GatewayError`, `4` for `TimeoutError`. Raise those exceptions instead of
  calling `sys.exit` from deep helpers.
- Keep exactly one consumer of the WebSocket at a time. Concurrent
  `_read_frame` calls corrupt the Noise decrypt state.
- `send` polls `chat.history` for the reply instead of using the live stream.
  This is deliberate. See PROTOCOL.md before changing it.
- New data files must live inside `src/muse_cli` so hatchling packages them.

## Keep docs in sync

When a command, flag, or behavior changes, update all that apply in the same
change:

- `README.md` (Usage section and the Development tree)
- `skills/muse-cli/SKILL.md` (command list and gotchas)
- the `--help` text in `cli.py`
- `docs/PROTOCOL.md`, if you learn a new server quirk
- the route count (258) in the README and skill, if `routes.json` changes

## Pull requests and releases

- Branch from `main` and open a PR against `main`. Never push to `main`
  directly unless the user asks. Never commit or push without the user's
  authorization.
- Before opening a PR, run the full unit tests and the `--help` checks above.
  PR CI (`publish.yml`) installs, runs the tests, builds, runs
  `twine check --strict`, and smoke-tests the wheel. It never publishes.
- Write PR descriptions to a temp file and pass it with `gh --body-file`.
- Every push to `main` automatically bumps the patch version, tags it,
  publishes to PyPI, and creates a GitHub release. So merging a PR is
  releasing it. Do not bump `__version__` or tag a routine release by hand.
- For an explicit major or minor release, agree on the version with the user
  first. Never force-push to get around a failed release push; rerun the
  failed workflow instead.
- After a release, check `https://pypi.org/pypi/muse-cli/json` and install the
  exact version in an isolated `uv` environment to verify `muse-cli --version`.
- Do not rename `publish.yml` or the GitHub environment `pypi` without the
  user's say-so. PyPI's trusted publisher is tied to both names.

## Security

- Cookies (`hatch_sess` and friends) are the user's login. They persist in
  `~/.config/muse-cli/cookies.txt` with mode 600. Never print, log, or commit
  them. Access and gateway tokens are fetched fresh on every run.
- `auth export` must never overwrite a working cookie file with one that lacks
  `hatch_sess`. It reads the user's own Chrome through `agent-browser
  --auto-connect`; never fall back to a fresh browser, which has no login.
- `.gitignore` covers `cookies.txt`, `agent-cookies.json`, `config.json`, and
  `*.har`. HAR captures hold live credentials, so never commit one.
- Commands that write (`send`, `feed-react`, `idea-exec`, session ops, `raw`
  POSTs) act as the user inside their agent. Do not run them against a real
  account to try things out unless the user asked, and never loop them.

## Troubleshooting

- `auth error: no cookies at ...`: run `muse-cli auth export` and follow the
  steps it prints (Chrome remote debugging on, a logged-in muse.ai tab in
  front). The README also covers copying cookies by hand.
- `/api/session` returns `status: unavailable` while the VM restarts. Retry, or
  run `MUSE_VM_ID=<id> muse-cli wake`.
- Many calls failing at once usually means the protocol drifted. Re-derive from
  a fresh web bundle and record new quirks in `docs/PROTOCOL.md`.
- A stderr line `A new release of muse-cli is available` is an upgrade notice,
  not a failure.
