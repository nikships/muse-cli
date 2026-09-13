#!/usr/bin/env bash
# muse-cli installer: CLI + agent skill, no browser needed afterwards.
# Usage: curl -fsSL https://raw.githubusercontent.com/nikships/muse-cli/main/install.sh | bash
set -u

REPO_URL="${MUSE_CLI_REPO:-https://github.com/nikships/muse-cli.git}"
DEST="${MUSE_CLI_DIR:-$HOME/muse-cli}"
BIN_DIR="${MUSE_CLI_BIN:-$HOME/bin}"
BIN_NAME="muse-cli"   # 'muse' clashes with Muse Code, don't use it
SKILL_DIR="${MUSE_CLI_SKILLS:-$HOME/.agents/skills}"

fail() { echo "install failed: $1" >&2; exit 1; }

command -v git >/dev/null || fail "git not found"
command -v python3 >/dev/null || fail "python3 not found"

if [ -d "$DEST/.git" ]; then
  echo "updating existing checkout at $DEST"
  git -C "$DEST" pull --ff-only || fail "git pull failed"
else
  echo "cloning into $DEST"
  git clone "$REPO_URL" "$DEST" || fail "git clone failed"
fi

echo "installing python dependencies"
if ! python3 -m pip install -r "$DEST/requirements.txt" 2>/dev/null; then
  echo "(system python is protected, retrying with --user)"
  python3 -m pip install --user -r "$DEST/requirements.txt" 2>/dev/null \
  || python3 -m pip install --user --break-system-packages -r "$DEST/requirements.txt" \
  || fail "pip install failed"
fi

mkdir -p "$BIN_DIR"
ln -sf "$DEST/cli.py" "$BIN_DIR/$BIN_NAME"
echo "linked $BIN_DIR/$BIN_NAME"

mkdir -p "$SKILL_DIR"
cp -r "$DEST/skills/muse-cli" "$SKILL_DIR/muse-cli"
echo "skill installed at $SKILL_DIR/muse-cli"

echo
echo "Next steps:"
echo "  1. Log in to https://muse.ai/ in Chrome"
echo "  2. $BIN_NAME auth export"
echo "  3. $BIN_NAME status"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: $BIN_DIR is not on your PATH; add it or run $BIN_DIR/$BIN_NAME" ;;
esac
