import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from muse_cli import cli


def read(path):
    with open(path) as fh:
        return fh.read()


class LocalNameTest(unittest.TestCase):
    def test_plain_and_encoded_names(self):
        self.assertEqual(cli._local_name("sandbox://workspace/a/cat.mp4", "out"),
                         os.path.join("out", "cat.mp4"))
        self.assertEqual(cli._local_name("https://x.metaaivm.com/media/raw/workspace/cat%201.mp4?v=2", "out"),
                         os.path.join("out", "cat 1.mp4"))

    def test_never_escapes_directory(self):
        self.assertEqual(cli._local_name("sandbox://workspace/..%2F..%2Fevil.sh", "out"),
                         os.path.join("out", "evil.sh"))
        for path in ("sandbox://workspace/..", "sandbox://workspace/%2E%2E", "/.."):
            self.assertEqual(cli._local_name(path, "out"), os.path.join("out", "download"))


class AuthExportTest(unittest.TestCase):
    def test_cookie_file_is_private_and_old_one_is_backed_up(self):
        jar = [{"name": "hatch_sess", "value": "secret", "domain": ".muse.ai"}]
        with tempfile.TemporaryDirectory() as tmp:
            cookies = os.path.join(tmp, "cookies.txt")
            with open(cookies, "w") as fh:
                fh.write("hatch_sess=old")
            old_umask = os.umask(0)
            try:
                with patch.object(cli, "CONFIG_DIR", tmp), \
                        patch.object(cli, "COOKIES_FILE", cookies), \
                        patch.object(cli.shutil, "which", return_value="/bin/agent-browser"), \
                        patch.object(cli, "_browser_cookies", return_value=(jar, None)):
                    cli.cmd_auth_export(None)
            finally:
                os.umask(old_umask)
            self.assertEqual(stat.S_IMODE(os.stat(cookies).st_mode), 0o600)
            self.assertIn("hatch_sess\tsecret", read(cookies))
            self.assertEqual(read(cookies + ".bak"), "hatch_sess=old")

    def test_logged_out_jar_leaves_existing_cookies(self):
        jar = [{"name": "other", "value": "x", "domain": ".muse.ai"}]
        with tempfile.TemporaryDirectory() as tmp:
            cookies = os.path.join(tmp, "cookies.txt")
            with open(cookies, "w") as fh:
                fh.write("hatch_sess=keep")
            with patch.object(cli, "CONFIG_DIR", tmp), \
                    patch.object(cli, "COOKIES_FILE", cookies), \
                    patch.object(cli.shutil, "which", return_value="/bin/agent-browser"), \
                    patch.object(cli, "_browser_cookies", return_value=(jar, None)):
                with self.assertRaises(SystemExit) as ctx:
                    cli.cmd_auth_export(None)
            self.assertEqual(ctx.exception.code, 1)
            self.assertEqual(read(cookies), "hatch_sess=keep")
            self.assertFalse(os.path.exists(cookies + ".bak"))


if __name__ == "__main__":
    unittest.main()
