#!/usr/bin/env bash
# muse-cli installer: CLI + agent skill, powered by uv. No browser needed afterwards.
# Usage: curl -fsSL https://raw.githubusercontent.com/nikships/muse-cli/main/install.sh | bash
set -u

REPO_URL="${MUSE_CLI_REPO:-https://github.com/nikships/muse-cli.git}"
DEST="${MUSE_CLI_DIR:-$HOME/muse-cli}"
BIN_DIR="${MUSE_CLI_BIN:-$HOME/bin}"
BIN_NAME="muse-cli"   # 'muse' clashes with Muse Code, don't use it
SKILL_DIR="${MUSE_CLI_SKILLS:-$HOME/.agents/skills}"

fail() { echo "install failed: $1" >&2; exit 1; }

command -v git >/dev/null || fail "git not found"
command -v curl >/dev/null || fail "curl not found"

if ! command -v uv >/dev/null; then
  echo "installing uv"
  curl -fsSL https://astral.sh/uv/install.sh | sh || fail "uv install failed"
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null || fail "uv not found after install"

if [ -d "$DEST/.git" ]; then
  echo "updating existing checkout at $DEST"
  git -C "$DEST" pull --ff-only || fail "git pull failed"
else
  echo "cloning into $DEST"
  git clone "$REPO_URL" "$DEST" || fail "git clone failed"
fi

echo "creating virtualenv and installing dependencies with uv"
uv venv "$DEST/.venv" || fail "uv venv failed"
uv pip install --python "$DEST/.venv/bin/python" -r "$DEST/requirements.txt" \
  || fail "uv pip install failed"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/$BIN_NAME" <<EOF
#!/usr/bin/env bash
exec "$DEST/.venv/bin/python" "$DEST/cli.py" "\$@"
EOF
chmod +x "$BIN_DIR/$BIN_NAME"
echo "launcher installed at $BIN_DIR/$BIN_NAME"

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
