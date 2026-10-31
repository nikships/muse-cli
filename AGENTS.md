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
  `protobuf`. The build backend is hatchling.
- The gateway API is unversioned and reverse engineered. `docs/PROTOCOL.md`
  holds the protocol notes and server quirks. Read it before touching
  `gateway.py`, and do not guess at crypto or framing.

## Repository map

- `src/muse_cli/cli.py`: argparse setup (`main()`), every `cmd_*` command,
  config loading, and `auth export` (drives Chrome through `agent-browser`).
- `src/muse_cli/gateway.py`: `Gateway` client (auth tokens, Noise transport,
  request/subscribe/download), `AuthError`, `GatewayError`, `load_cookies`.
- `src/muse_cli/chat.py`: the interactive REPL (`muse-cli` with no command).
- `src/muse_cli/update.py`: once-a-day PyPI update notice and `muse-cli update`.
- `src/muse_cli/routes.json`: the 258 gateway methods extracted from the web
  client. `desc0.bin` / `desc1.bin` are protobuf descriptors for the framing.
  These three are generated data, so do not hand-edit them.
- `src/muse_cli/__init__.py`: holds `__version__`, the only place the version
  lives. `pyproject.toml` reads it.
- `tests/`: `unittest` tests, no network needed.
- `scripts/bump_version.py`: release version bump used by CI.
- `skills/muse-cli/SKILL.md`: the agent skill that `install.sh` copies to
  `~/.agents/skills/muse-cli`.
- `install.sh`: installs the CLI with `uv tool` and the skill.
- `site/` + `firebase.json` + `.firebaserc`: static landing page for Firebase
  Hosting project `muse-cli-site`. No workflow deploys it.
- `assets/`: README artwork. `docs/PROTOCOL.md`: protocol reference.

## Setup and run

- Run the CLI from a checkout: `uv run muse-cli --help`
- Run a command: `uv run muse-cli status`
- `uv run` writes an untracked `uv.lock`. The repo does not track one, so do
  not commit it.
- Real commands need a logged-in muse.ai cookie file at
  `~/.config/muse-cli/cookies.txt`. Without it they exit with an
  `auth error`. Use the unit tests and `--help` for checks that must not touch
  the user's account.
- Config and state live in `~/.config/muse-cli/` (`config.json`,
  `cookies.txt`, `chat.json`, `chat_history`, `update.json`). The cookie file
  is mode 600 and is a secret. Never print it, log it, or commit it.
- Environment variables: `MUSE_VM_ID` (skip VM discovery), `MUSE_NODE_ID`
  (fixed device id), `MUSE_NO_UPDATE_CHECK=1` (silence the update notice).

## Testing

- Run everything: `uv run python -m unittest discover -s tests -v`
- Run one file: `uv run python -m unittest tests.test_media -v`
- Run one test:
  `uv run python -m unittest tests.test_chat.DeletedSideChatRecoveryTest.test_is_not_found -v`
- Tests use `unittest` and `unittest.mock`. They never call muse.ai. Keep it
  that way: mock `Gateway` and the network.
- `tests/test_release.py` builds throwaway git repos to test
  `scripts/bump_version.py` and the atomic version-and-tag push. It needs
  `git` on PATH.
- There is no linter, formatter, or type checker configured. Do not add one
  in an unrelated change.
- Add or update a test for each behavior change, even if nobody asks.
- The CI smoke test also runs `muse-cli --version`, `--help`, and
  `chat --help` from a built wheel. Run those yourself after touching
  argument parsing or packaging.

## Code style

- Match the surrounding code. It is plain, standard-library-first Python with
  no type annotations and short docstrings or comments only where the reason
  is not obvious.
- Commands live in `cli.py` as `cmd_<name>(args)` and are registered in
  `main()`. Every command prints JSON through `out()` (`ensure_ascii=False`).
  The exception is the interactive chat, which prints plain text one message
  per line so screen readers work.
- Keep stdout for machine-readable output and stderr for notices and errors,
  because users pipe the output into `jq` and other agents.
- Exit codes come from `main()`: `2` for `AuthError` or bad arguments, `3` for
  `GatewayError`, `4` for `TimeoutError`. Raise those exceptions rather than
  calling `sys.exit` from deep helpers.
- Keep exactly one consumer of the WebSocket at a time. Concurrent
  `_read_frame` calls corrupt the Noise decrypt state (see PROTOCOL.md).
- `send` polls `chat.history` for the reply instead of using the live stream.
  This is deliberate. See the quirks in PROTOCOL.md before changing it.
- The package must stay installable from the sdist and wheel. New data files
  need to be inside `src/muse_cli` so hatchling includes them.

## Docs to keep in sync

When a command, flag, or behavior changes, update all that apply in the same
change:

- `README.md` (Usage section and the Development tree)
- `skills/muse-cli/SKILL.md` (command list and gotchas)
- the `--help` text in `cli.py`
- `docs/PROTOCOL.md` if you learn a new server quirk
- the method count (258) in the README and skill if `routes.json` changes

## Pull requests

- Branch from `main` and open a PR against `main`. Never push to `main`
  directly unless the user asks.
- Before opening a PR, run the full unit tests and the `--help` smoke checks
  above.
- PR jobs run the `Build and check` job in `publish.yml`: install, unit tests,
  `python -m build`, `twine check --strict`, and the wheel smoke test. They
  have read-only permissions and never publish.
- Write PR descriptions to a temp file and pass it with `gh --body-file`.
- Do not bump `__version__` in a PR. Releases bump it automatically.
- Never commit or push without the user's authorization.

## Releases

Every push to `main` triggers `.github/workflows/publish.yml`. It bumps the
patch version, runs the tests, builds, smoke-tests, commits the version and
tag atomically, publishes to PyPI, and creates a GitHub release. So merging a
PR is releasing it.

- Do not manually bump or tag a routine patch release.
- Release runs queue (up to GitHub's 100-pending-run limit) and check out
  current `main`. If `main` moves during validation, the atomic push fails
  without publishing or tagging. Rerun the failed workflow from the start. Never
  force-push to get around this.
- Bot pushes use `GITHUB_TOKEN`, so they do not start another release.
  Publishing runs in the same workflow, not in a second tag-triggered run.
- `scripts/bump_version.py` picks the next patch above both the source version
  and the existing stable `v*` tags. For an explicit major or minor release,
  agree on the version first. Setting the source to `X.Y.Z` before the push
  produces at least `X.Y.(Z+1)`.
- Manual `v*` tag pushes still work for recovery or explicitly requested
  releases. The tag must match `__version__`, be unused on PyPI, and point at
  the intended tested source. Never push both `main` and a manual tag for the
  same change, because that schedules two releases. `v0.1.0` is a historical
  GitHub-only tag. PyPI releases start at 0.2.0.
- After publishing, check `https://pypi.org/pypi/muse-cli/json`, then install
  the exact version into an isolated environment with `uv` and verify
  `muse-cli --version` and `muse-cli chat --help`. PyPI can take a minute to
  show the release. Report the PyPI and GitHub release links.

### If a release goes wrong

- **Failed before the version/tag push:** nothing was published. Fix the
  problem and rerun the workflow from the beginning.
- **Version/tag pushed, but PyPI failed:** rerun only the failed jobs to reuse
  the tested artifacts. Do not rerun the successful version-commit job or
  delete and re-push the tag.
- **Failed after the PyPI upload** (for example the GitHub release step): the
  version is live. Do not delete the tag. Fix the workflow, and create the
  missing GitHub release by hand if the user wants it.
- **A bad version reached PyPI:** PyPI never allows re-uploading a version.
  Fix forward with a new patch version. The user can yank the bad one on
  pypi.org. Do not try to delete it.

### Do not change without the user's say-so

PyPI trusts this repo through a trusted publisher tied to the workflow file
name `publish.yml` and the GitHub environment `pypi`. Renaming either breaks
publishing until the PyPI settings are updated to match.

## Security

- Cookies (`hatch_sess` and friends), access tokens, and gateway tokens are
  the user's login. Access and gateway tokens are fetched fresh on every run;
  only cookies persist, in `~/.config/muse-cli/cookies.txt` with mode 600.
- `auth export` must never overwrite a working cookie file with one that lacks
  `hatch_sess`. Keep that guard.
- `auth export` reads the user's own Chrome through `agent-browser`
  `--auto-connect`. Never fall back to a freshly launched browser, because it
  has no login.
- `.gitignore` covers `cookies.txt`, `agent-cookies.json`, `config.json`, and
  `*.har`. HAR captures contain live credentials, so never commit one.
- Commands that write (`send`, `feed-react`, `idea-exec`, session ops, `raw`
  POSTs) act as the user inside their agent. Do not run them against a real
  account to "try things out" unless the user asked, and never loop them.

## Troubleshooting

- `auth error: no cookies at ...`: run `muse-cli auth export` and follow the
  printed steps (Chrome remote debugging on at
  `chrome://inspect/#remote-debugging`, a logged-in muse.ai tab in front).
  Copying cookies by hand is covered in the README.
- `/api/session` returns `status: unavailable` while the VM restarts. Retry,
  or run `MUSE_VM_ID=<id> muse-cli wake`.
- Many calls failing at once usually means the protocol drifted. Re-derive
  from a fresh web bundle and record new quirks in `docs/PROTOCOL.md`.
- A stderr line `A new release of muse-cli is available` is an upgrade notice,
  not a failure.
