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
echo "Next steps:"
echo "  1. npm i -g agent-browser   # auth export reads Chrome cookies through it"
echo "  2. Log in to https://muse.ai/ in Chrome"
echo "  3. $BIN_NAME auth export"
echo "  4. $BIN_NAME status"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: $BIN_DIR is not on your PATH; run 'uv tool update-shell' or use $BIN_DIR/$BIN_NAME" ;;
esac
