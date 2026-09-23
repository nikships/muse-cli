#!/usr/bin/env bash
# muse-cli installer: CLI (from PyPI, via uv) + agent skill. No browser needed afterwards.
# Usage: curl -fsSL https://raw.githubusercontent.com/nikships/muse-cli/main/install.sh | bash
set -u

REPO_URL="${MUSE_CLI_REPO:-https://github.com/nikships/muse-cli.git}"
RAW_URL="${MUSE_CLI_RAW:-https://raw.githubusercontent.com/nikships/muse-cli/main}"
SKILL_DIR="${MUSE_CLI_SKILLS:-$HOME/.agents/skills}"
BIN_NAME="muse-cli"   # 'muse' clashes with Muse Code, don't use it
LEGACY_BIN="${MUSE_CLI_BIN:-$HOME/bin}/$BIN_NAME"

fail() { echo "install failed: $1" >&2; exit 1; }

command -v curl >/dev/null || fail "curl not found"

if ! command -v uv >/dev/null; then
  echo "installing uv"
  curl -fsSL https://astral.sh/uv/install.sh | sh || fail "uv install failed"
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null || fail "uv not found after install"

echo "installing $BIN_NAME with uv"
if ! uv tool install --upgrade muse-cli; then
  echo "PyPI install failed, installing from $REPO_URL"
  uv tool install --upgrade "git+$REPO_URL" || fail "uv tool install failed"
fi

# Older installers wrote a launcher into ~/bin that runs a git checkout's
# cli.py; it would shadow the new command and break once the checkout updates.
if [ -f "$LEGACY_BIN" ] && grep -q "cli.py" "$LEGACY_BIN" 2>/dev/null; then
  rm -f "$LEGACY_BIN"
  echo "removed old launcher at $LEGACY_BIN"
fi

mkdir -p "$SKILL_DIR/muse-cli"
curl -fsSL "$RAW_URL/skills/muse-cli/SKILL.md" -o "$SKILL_DIR/muse-cli/SKILL.md" \
  || fail "skill download failed"
echo "skill installed at $SKILL_DIR/muse-cli"

BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
# uv prints the bin dir with a literal ".." inside; normalize it so the PATH
# check below compares real paths.
[ -d "$BIN_DIR" ] && BIN_DIR="$(cd "$BIN_DIR" && pwd)"
echo
echo "muse-cli is installed. Log in once before any other command."
echo "Chrome shares its cookies after you turn on remote debugging"
echo "in the window where you are logged in to muse.ai."
echo
if command -v agent-browser >/dev/null 2>&1; then
  ab_ver="$(agent-browser --version 2>/dev/null || echo found)"
  echo "agent-browser: already installed ($ab_ver)"
else
  echo "agent-browser: not installed. auth export needs it to read Chrome."
  if command -v npm >/dev/null 2>&1; then
    echo "  npm is available. Run:"
    echo "    npm i -g agent-browser"
    echo "    agent-browser --version"
  else
    echo "  Node.js is not on PATH (no npm)."
    echo "    1. Install Node.js LTS from https://nodejs.org"
    echo "    2. Open a new terminal"
    echo "    3. npm i -g agent-browser"
    echo "    4. agent-browser --version"
  fi
  echo "  If npm says EACCES, it cannot write to its global bin directory."
  echo "  Use an npm prefix you own, or the same rights you use for other global npm tools."
fi
echo
echo "Then, in the Google Chrome window you already use for muse.ai:"
echo "  1. Paste this in the address bar and open it:"
echo "       chrome://inspect/#remote-debugging"
echo "     Turn on remote debugging"
echo "     (\"Allow remote debugging for this browser instance\")."
echo "     Needs Chrome 144 or newer. Leave Chrome open."
echo "  2. Open https://muse.ai/ in that same window and log in."
echo "     Leave that tab in front. The export reads the active tab."
echo "  3. $BIN_NAME auth export"
echo "     If Chrome asks to allow the connection, click Allow."
echo "     If the command failed before that click, run it again."
echo "     Success looks like:"
echo "       saved N muse.ai cookies to ~/.config/muse-cli/cookies.txt"
echo "  4. $BIN_NAME status"
echo
echo "Stay in that Chrome. A second Chrome started with --remote-debugging-port"
echo "is a different profile and does not have your muse.ai login."
echo
echo "The export command prints this same fix when it fails. Two other cases:"
echo "  - \"daemon already running\": agent-browser close && $BIN_NAME auth export"
echo "  - no Node, or you do not want remote debugging on: copy cookies by hand"
echo "    DevTools (F12) → Application → Cookies → https://muse.ai"
echo "    One line in ~/.config/muse-cli/cookies.txt (hatch_sess is required):"
echo "      hatch_sess=VALUE; other_name=other_value"
echo "    chmod 600 ~/.config/muse-cli/cookies.txt"
echo "    $BIN_NAME status"
echo
echo "Full write-up: https://github.com/nikships/muse-cli#log-in-once"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: $BIN_DIR is not on your PATH; run 'uv tool update-shell' or use $BIN_DIR/$BIN_NAME" ;;
esac
