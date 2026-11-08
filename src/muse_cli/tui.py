"""Launcher for the full-screen app: `muse-cli tui` (and bare `muse-cli`).

The app itself is TypeScript (muse_cli/tui, OpenTUI on Bun). This module finds
Bun, copies the app into a cache directory with its dependencies installed,
and runs it. The app starts `python -m muse_cli.bridge` for everything that
talks to muse.ai. See docs/TUI.md.
"""
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

MIN_BUN = (1, 3, 14)
APP_DIR = Path(__file__).parent / "tui"
SKIP = {"node_modules", ".DS_Store", "__pycache__"}
MARKER = ".muse-cli-installed"


class SetupError(RuntimeError):
    pass


def find_bun():
    found = shutil.which("bun")
    if found:
        return found
    home = Path.home() / ".bun" / "bin" / ("bun.exe" if os.name == "nt" else "bun")
    return str(home) if home.is_file() and os.access(home, os.X_OK) else None


def bun_version(bun):
    try:
        r = subprocess.run([bun, "--version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"\s*(\d+)\.(\d+)\.(\d+)", r.stdout or "")
    return tuple(int(x) for x in m.groups()) if r.returncode == 0 and m else None


def usable_bun():
    """Path of a Bun new enough for the app, else None."""
    bun = find_bun()
    if bun is None:
        return None
    version = bun_version(bun)
    return bun if version and version >= MIN_BUN else None


def app_files(src):
    """Every shipped file of the app, relative to src, without node_modules."""
    files = []
    for root, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in names:
            if name not in SKIP:
                files.append(Path(root, name).relative_to(src))
    return sorted(files, key=lambda p: p.as_posix())


def app_hash(src):
    h = hashlib.sha256()
    for rel in app_files(src):
        h.update(rel.as_posix().encode() + b"\0")
        h.update((Path(src) / rel).read_bytes() + b"\0")
    return h.hexdigest()[:12]


def cache_root():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    return Path(base) / "muse-cli" / "tui"


def bun_install(bun, directory):
    print("Setting up the muse-cli app (one time)...", file=sys.stderr, flush=True)
    try:
        r = subprocess.run([bun, "install", "--frozen-lockfile"], cwd=str(directory),
                           capture_output=True, text=True)
    except OSError as e:
        raise SetupError(f"could not run bun install: {e}")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
        raise SetupError("bun install failed" + (": " + " / ".join(tail) if tail else ""))


def copy_app(src, dest):
    """Copy the app to dest atomically: a partial copy never sits at dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=str(dest.parent)))
    try:
        for rel in app_files(src):
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(src) / rel, tmp / rel)
        try:
            os.replace(tmp, dest)
        except OSError:
            # Another launch finished the same copy first.
            if not dest.is_dir():
                raise
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def prepare(bun, src=APP_DIR):
    """Return a directory where `bun src/main.tsx` can run."""
    override = os.environ.get("MUSE_CLI_TUI_DIR")
    if override:
        d = Path(override).expanduser().resolve()
        if not (d / "src" / "main.tsx").is_file():
            raise SetupError(f"MUSE_CLI_TUI_DIR={override} has no src/main.tsx")
        if not (d / "node_modules").is_dir():
            bun_install(bun, d)
        return d
    if not (Path(src) / "src" / "main.tsx").is_file():
        raise SetupError(f"the app is missing from {src}")
    dest = cache_root() / app_hash(src)
    marker = dest / MARKER
    if marker.is_file():
        return dest
    try:
        if not dest.is_dir():
            copy_app(src, dest)
    except OSError as e:
        raise SetupError(f"could not copy the app to {dest}: {e}")
    bun_install(bun, dest)
    # Written last, so an interrupted install runs again next time.
    marker.write_text("ok\n")
    return dest


def is_tty():
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def should_open():
    """Bun path when bare `muse-cli` should open the app, else None."""
    if os.environ.get("MUSE_CLI_UI") == "plain" or not is_tty():
        return None
    return usable_bun()


def offer_bun_install():
    """Ask to install Bun on a terminal; return a usable Bun or None."""
    if not is_tty():
        return None
    try:
        answer = input("The full-screen app needs Bun (https://bun.sh). Install it now? [Y/n] ")
    except EOFError:
        return None
    if answer.strip().lower() not in ("", "y", "yes"):
        return None
    if os.name == "nt":
        argv = ["powershell", "-c", "irm bun.sh/install.ps1 | iex"]
    else:
        argv = ["bash", "-c", "curl -fsSL https://bun.sh/install | bash"]
    try:
        if subprocess.run(argv).returncode != 0:
            return None
    except OSError:
        return None
    return usable_bun()


def run_app(bun, directory, demo):
    env = dict(os.environ, MUSE_CLI_PYTHON=sys.executable)
    if demo:
        env["MUSE_CLI_DEMO"] = "1"
    proc = subprocess.Popen([bun, str(Path(directory) / "src" / "main.tsx")], env=env)
    # The app owns the terminal and handles Ctrl-C itself. Killing it from
    # here would leave the terminal in raw mode.
    old = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        code = proc.wait()
    finally:
        signal.signal(signal.SIGINT, old)
    return 128 - code if code < 0 else code


def plain_notice(why):
    print(f"{why}; opening the plain chat (`muse-cli chat`).", file=sys.stderr)


def launch(args, demo=False, bun=None, ask=True):
    """Run the app and return its exit code, or fall back to the plain chat.

    Returns None after a plain-chat fallback.
    """
    bun = bun or usable_bun()
    if bun is None and ask:
        bun = offer_bun_install()
    if bun is None:
        why = "The full-screen app needs Bun 1.3.14 or later (https://bun.sh)"
        if demo:
            # The plain chat would talk to the real account.
            print(why + ".", file=sys.stderr)
            return 1
        plain_notice(why)
        return fallback(args)
    try:
        directory = prepare(bun)
    except SetupError as e:
        if demo:
            print(f"Could not set up the full-screen app: {e}", file=sys.stderr)
            return 1
        plain_notice(f"Could not set up the full-screen app ({e})")
        return fallback(args)
    return run_app(bun, directory, demo)


def fallback(args):
    from .chat import cmd_chat
    cmd_chat(args)
    return None
