"""Increment the package patch version beyond existing release tags."""

import re
import subprocess
from pathlib import Path

VERSION = re.compile(r'__version__ = "(\d+\.\d+\.\d+)"')


def next_version(current, tags):
    versions = [tuple(map(int, current.split(".")))]
    for tag in tags:
        if re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            versions.append(tuple(map(int, tag[1:].split("."))))
    major, minor, patch = max(versions)
    return f"{major}.{minor}.{patch + 1}"


def bump_version(root):
    path = root / "src/muse_cli/__init__.py"
    source = path.read_text()
    match = VERSION.search(source)
    if match is None:
        raise ValueError("Expected a stable X.Y.Z __version__")
    tags = subprocess.check_output(
        ["git", "tag", "--list", "v*"], cwd=root, text=True
    ).splitlines()
    version = next_version(match[1], tags)
    path.write_text(VERSION.sub(f'__version__ = "{version}"', source, count=1))
    return version


if __name__ == "__main__":
    print(bump_version(Path(__file__).resolve().parents[1]))
