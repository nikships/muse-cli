import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "bump_version", Path(__file__).resolve().parents[1] / "scripts/bump_version.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseVersionTest(unittest.TestCase):
    def test_patch_bump(self):
        self.assertEqual(release.next_version("0.3.2", []), "0.3.3")

    def test_existing_tags_are_not_reused(self):
        self.assertEqual(
            release.next_version("0.3.2", ["v0.3.3", "v0.3.10"]), "0.3.11"
        )

    def test_numeric_order_and_unrelated_tags(self):
        self.assertEqual(
            release.next_version("0.3.9", ["v0.3.10", "v0.4.0rc1", "other"]),
            "0.3.11",
        )

    def test_manual_minor_bump_is_preserved(self):
        self.assertEqual(release.next_version("0.4.0", ["v0.3.9"]), "0.4.1")

    def test_bumps_only_version_in_real_git_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            path = root / "src/muse_cli/__init__.py"
            path.parent.mkdir(parents=True)
            path.write_text('"""Package."""\n\n__version__ = "0.3.2"\n')
            self.assertEqual(release.bump_version(root), "0.3.3")
            self.assertEqual(
                path.read_text(), '"""Package."""\n\n__version__ = "0.3.3"\n'
            )

    def test_invalid_version_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "src/muse_cli/__init__.py"
            path.parent.mkdir(parents=True)
            source = '__version__ = "0.4.0rc1"\n'
            path.write_text(source)
            with self.assertRaises(ValueError):
                release.bump_version(root)
            self.assertEqual(path.read_text(), source)

class AtomicReleasePushTest(unittest.TestCase):
    def git(self, root, *args, check=True):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=check, capture_output=True, text=True,
        )

    def exercise_push(self, advance_main):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote, checkout = root / "remote.git", root / "checkout"
            self.git(root, "init", "--bare", str(remote))
            self.git(root, "init", "-b", "main", str(checkout))
            self.git(checkout, "config", "user.name", "Release test")
            self.git(checkout, "config", "user.email", "test@example.invalid")
            (checkout / "file").write_text("original")
            self.git(checkout, "add", ".")
            self.git(checkout, "commit", "-m", "Initial")
            self.git(checkout, "remote", "add", "origin", str(remote))
            self.git(checkout, "push", "origin", "main")
            original = self.git(checkout, "rev-parse", "HEAD").stdout.strip()
            if advance_main:
                (checkout / "file").write_text("concurrent change")
                self.git(checkout, "commit", "-am", "Concurrent main push")
                self.git(checkout, "push", "origin", "main")
                self.git(checkout, "checkout", "--detach", original)
            (checkout / "version").write_text("0.3.3")
            self.git(checkout, "add", ".")
            self.git(checkout, "commit", "-m", "Release v0.3.3")
            self.git(checkout, "tag", "-a", "v0.3.3", "-m", "Release")
            result = self.git(
                checkout, "push", "--atomic", "origin",
                "HEAD:refs/heads/main", "refs/tags/v0.3.3", check=False,
            )
            tag = self.git(
                remote, "show-ref", "--verify", "refs/tags/v0.3.3", check=False,
            )
            remote_head = self.git(remote, "rev-parse", "main").stdout.strip()
            release_head = self.git(checkout, "rev-parse", "HEAD").stdout.strip()
            if advance_main:
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(tag.returncode, 0)
                self.assertNotEqual(remote_head, release_head)
                self.assertEqual(
                    self.git(remote, "show", "main:file").stdout,
                    "concurrent change",
                )
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(tag.returncode, 0)
                self.assertEqual(remote_head, release_head)

    def test_version_commit_and_tag_push_together(self):
        self.exercise_push(advance_main=False)

    def test_concurrent_main_push_rejects_tag_too(self):
        self.exercise_push(advance_main=True)


if __name__ == "__main__":
    unittest.main()
