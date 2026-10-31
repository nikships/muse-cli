"""Install and refresh the muse-cli agent skill (SKILL.md).

The skill ships inside the wheel, so it always matches the installed version.
`install.sh` puts it in the same default location.
"""
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def skill_path():
    """Where coding agents look for the skill. MUSE_CLI_SKILLS matches install.sh."""
    root = os.environ.get("MUSE_CLI_SKILLS") or os.path.expanduser("~/.agents/skills")
    return os.path.join(root, "muse-cli", "SKILL.md")


def bundled_skill():
    """Path of the SKILL.md that belongs to this version, or None."""
    candidates = (
        os.path.join(HERE, "SKILL.md"),  # built wheel
        os.path.join(HERE, "..", "..", "skills", "muse-cli", "SKILL.md"),  # source checkout
    )
    for path in candidates:
        if os.path.isfile(path):
            return os.path.normpath(path)
    return None


def sync_skill(create=False):
    """Copy the bundled skill over the installed one.

    Returns (status, path). Status is one of "updated", "installed", "current",
    "absent" (not installed and create is False) or "no-source".
    """
    src = bundled_skill()
    dest = skill_path()
    if src is None:
        return "no-source", dest
    with open(src, "rb") as fh:
        data = fh.read()
    exists = os.path.exists(dest)
    if exists:
        with open(dest, "rb") as fh:
            if fh.read() == data:
                return "current", dest
    elif not create:
        return "absent", dest
    directory = os.path.dirname(dest)
    os.makedirs(directory, exist_ok=True)
    mode = os.stat(dest).st_mode & 0o777 if exists else 0o644
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".SKILL.md.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return ("updated" if exists else "installed"), dest
