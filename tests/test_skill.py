import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from muse_cli import skill, update


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)


def read(path):
    with open(path) as fh:
        return fh.read()


class SyncSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "bundled", "SKILL.md")
        write(self.src, "new skill")
        self.root = os.path.join(self.tmp.name, "skills")
        env = patch.dict(os.environ, {"MUSE_CLI_SKILLS": self.root})
        env.start()
        self.addCleanup(env.stop)
        bundled = patch.object(skill, "bundled_skill", return_value=self.src)
        bundled.start()
        self.addCleanup(bundled.stop)
        self.dest = os.path.join(self.root, "muse-cli", "SKILL.md")

    def test_default_location_matches_installer(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(skill.skill_path(),
                             os.path.expanduser("~/.agents/skills/muse-cli/SKILL.md"))

    def test_absent_skill_is_not_created_unless_asked(self):
        self.assertEqual(skill.sync_skill(), ("absent", self.dest))
        self.assertFalse(os.path.exists(self.dest))
        self.assertEqual(skill.sync_skill(create=True), ("installed", self.dest))
        self.assertEqual(read(self.dest), "new skill")

    def test_stale_skill_is_replaced_and_keeps_its_mode(self):
        write(self.dest, "old skill", mode=0o600)
        self.assertEqual(skill.sync_skill(), ("updated", self.dest))
        self.assertEqual(read(self.dest), "new skill")
        self.assertEqual(stat.S_IMODE(os.stat(self.dest).st_mode), 0o600)
        self.assertEqual(os.listdir(os.path.dirname(self.dest)), ["SKILL.md"])

    def test_current_skill_is_left_alone(self):
        write(self.dest, "new skill")
        before = os.stat(self.dest).st_mtime_ns
        self.assertEqual(skill.sync_skill(), ("current", self.dest))
        self.assertEqual(os.stat(self.dest).st_mtime_ns, before)

    def test_missing_source(self):
        with patch.object(skill, "bundled_skill", return_value=None):
            self.assertEqual(skill.sync_skill(create=True)[0], "no-source")

class BundledSkillTest(unittest.TestCase):
    def test_bundled_skill_is_the_muse_cli_skill(self):
        path = skill.bundled_skill()
        self.assertIsNotNone(path)
        self.assertIn("name: muse-cli", read(path))


class UpdateCommandTest(unittest.TestCase):
    def args(self, skill_only=False):
        return type("Args", (), {"skill": skill_only})()

    def test_upgrade_then_refresh_installed_skill_in_new_interpreter(self):
        with patch.object(update, "upgrade_argv", return_value=["uv", "tool", "upgrade", "muse-cli"]), \
                patch.object(update.shutil, "which", return_value="/usr/bin/uv"), \
                patch.object(update, "skill_path", return_value=__file__), \
                patch("subprocess.call", return_value=0) as call:
            with self.assertRaises(SystemExit) as ctx:
                update.cmd_update(self.args())
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(call.call_args_list[0].args[0], ["uv", "tool", "upgrade", "muse-cli"])
        self.assertEqual(call.call_args_list[1].args[0][1:],
                         ["-m", "muse_cli", "update", "--skill"])

    def test_no_skill_refresh_when_not_installed_or_upgrade_failed(self):
        for exists_path, code in (("/nonexistent/SKILL.md", 0), (__file__, 1)):
            with patch.object(update, "upgrade_argv", return_value=["uv", "tool", "upgrade", "muse-cli"]), \
                    patch.object(update.shutil, "which", return_value="/usr/bin/uv"), \
                    patch.object(update, "skill_path", return_value=exists_path), \
                    patch("subprocess.call", return_value=code) as call:
                with self.assertRaises(SystemExit) as ctx:
                    update.cmd_update(self.args())
            self.assertEqual(ctx.exception.code, code)
            self.assertEqual(call.call_count, 1)

    def test_skill_flag_only_syncs_the_skill(self):
        with patch("muse_cli.skill.sync_skill", return_value=("installed", "/x/SKILL.md")) as sync, \
                patch("subprocess.call") as call:
            with self.assertRaises(SystemExit) as ctx:
                update.cmd_update(self.args(skill_only=True))
        self.assertEqual(ctx.exception.code, 0)
        sync.assert_called_once_with(create=True)
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
