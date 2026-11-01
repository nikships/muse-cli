import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from muse_cli import browsers, cli


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
                        patch.object(cli.browsers, "supported", return_value=False), \
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
                    patch.object(cli.browsers, "supported", return_value=False), \
                    patch.object(cli.shutil, "which", return_value="/bin/agent-browser"), \
                    patch.object(cli, "_browser_cookies", return_value=(jar, None)):
                with self.assertRaises(SystemExit) as ctx:
                    cli.cmd_auth_export(None)
            self.assertEqual(ctx.exception.code, 1)
            self.assertEqual(read(cookies), "hatch_sess=keep")
            self.assertFalse(os.path.exists(cookies + ".bak"))

    def export(self, tmp, browser, direct, which="/bin/agent-browser", agent=None):
        cookies = os.path.join(tmp, "cookies.txt")
        args = MagicMock(browser=browser)
        ctx = [patch.object(cli, "CONFIG_DIR", tmp), patch.object(cli, "COOKIES_FILE", cookies),
               patch.object(cli.browsers, "supported", return_value=True),
               patch.object(cli.browsers, "read_cookies", side_effect=direct),
               patch.object(cli.shutil, "which", return_value=which),
               patch.object(cli, "_browser_cookies", return_value=agent or (None, "no agent"))]
        for c in ctx:
            c.start()
        self.addCleanup(patch.stopall)
        return cookies, args

    def test_auto_prefers_reading_the_browser_directly(self):
        jar = [{"name": "hatch_sess", "value": "direct", "domain": ".muse.ai"}]
        with tempfile.TemporaryDirectory() as tmp:
            cookies, args = self.export(tmp, "auto", [(jar, "chrome (Default)")])
            cli.cmd_auth_export(args)
            self.assertIn("hatch_sess\tdirect", read(cookies))
            cli._browser_cookies.assert_not_called()

    def test_auto_falls_back_to_agent_browser(self):
        jar = [{"name": "hatch_sess", "value": "agent", "domain": ".muse.ai"}]
        with tempfile.TemporaryDirectory() as tmp:
            cookies, args = self.export(tmp, "auto", [browsers.BrowserCookieError("no login")],
                                        agent=(jar, None))
            cli.cmd_auth_export(args)
            self.assertIn("hatch_sess\tagent", read(cookies))

    def test_auto_without_agent_browser_explains_how_to_log_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookies, args = self.export(tmp, "auto", [browsers.BrowserCookieError("no login")], which=None)
            with patch("sys.stderr", new_callable=io.StringIO) as err, \
                    self.assertRaises(SystemExit):
                cli.cmd_auth_export(args)
            self.assertIn("Log in at https://muse.ai/", err.getvalue())
            self.assertNotIn("npm i -g", err.getvalue())
            self.assertFalse(os.path.exists(cookies))

    def test_named_browser_failure_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookies, args = self.export(tmp, "brave", [browsers.BrowserCookieError("no brave profile found")])
            with patch("sys.stderr", new_callable=io.StringIO) as err, \
                    self.assertRaises(SystemExit):
                cli.cmd_auth_export(args)
            self.assertIn("no brave profile found", err.getvalue())
            cli._browser_cookies.assert_not_called()

    def test_invalid_session_leaves_existing_cookies_unchanged(self):
        for value, expires in (("", 0), ("expired", 1)):
            for browser in ("auto", "agent-browser"):
                with self.subTest(value=value, browser=browser), tempfile.TemporaryDirectory() as tmp:
                    jar = [{"name": "hatch_sess", "value": value, "expires": expires,
                            "domain": ".muse.ai"}]
                    cookies, args = self.export(tmp, browser, [(jar, "chrome (Default)")],
                                                agent=(jar, None))
                    with open(cookies, "w") as fh:
                        fh.write("hatch_sess=keep")
                    with patch("sys.stderr", new_callable=io.StringIO), \
                            self.assertRaises(SystemExit):
                        cli.cmd_auth_export(args)
                    self.assertEqual(read(cookies), "hatch_sess=keep")
                    self.assertFalse(os.path.exists(cookies + ".bak"))

    def test_agent_browser_accepts_session_cookie_without_expiration(self):
        jar = [{"name": "hatch_sess", "value": "session", "expires": -1,
                "domain": ".muse.ai"}]
        with tempfile.TemporaryDirectory() as tmp:
            cookies, args = self.export(tmp, "agent-browser", [], agent=(jar, None))
            cli.cmd_auth_export(args)
            self.assertIn("hatch_sess\tsession", read(cookies))
            cli.browsers.read_cookies.assert_not_called()

    def test_named_browser_is_rejected_off_macos(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookies, args = self.export(tmp, "chrome", [])
            cli.browsers.supported.return_value = False
            with patch("sys.stderr", new_callable=io.StringIO) as err, \
                    self.assertRaises(SystemExit):
                cli.cmd_auth_export(args)
            self.assertIn("macOS-only", err.getvalue())
            cli.browsers.read_cookies.assert_not_called()
            cli._browser_cookies.assert_not_called()
            self.assertFalse(os.path.exists(cookies))

    def test_missing_cookie_error_does_not_require_remote_debugging(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(cli.AuthError) as cm:
                cli.connect({"cookies_file": os.path.join(tmp, "missing")})
        self.assertIn("muse-cli auth export", str(cm.exception))
        self.assertNotIn("remote debugging", str(cm.exception))


@unittest.skipIf(os.name == "nt", "a closed pipe is not a BrokenPipeError on Windows")
class BrokenPipeTest(unittest.TestCase):
    def run_with_closed_reader(self, rows, close_first):
        src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
        code = ("import sys; from muse_cli import cli; "
                f"cli.cmd_threads = lambda a: cli.out(['x' * 100] * {rows}); "
                "sys.argv = ['muse-cli', 'threads']; cli.main()")
        env = dict(os.environ, PYTHONPATH=src, MUSE_NO_UPDATE_CHECK="1")
        env.pop("PYTHONUNBUFFERED", None)
        proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if close_first:
            proc.stdout.close()
        else:
            proc.stdout.read(10)
            proc.stdout.close()
        err = proc.stderr.read()
        proc.stderr.close()
        return proc.wait(), err

    def test_reader_closing_mid_write_exits_quietly(self):
        self.assertEqual(self.run_with_closed_reader(100000, False), (141, b""))

    def test_small_output_flushed_after_reader_left_exits_quietly(self):
        self.assertEqual(self.run_with_closed_reader(3, True), (141, b""))


class SendDownloadTest(unittest.TestCase):
    def test_waits_for_media_that_lands_after_the_text_reply(self):
        reply = {"seq": 5, "event_name": "message.assistant",
                 "payload": {"display_text": "hi", "status": "completed", "message_id": "m1"}}
        image = {"seq": 6, "event_name": "message.assistant",
                 "payload": {"data": {"images": [
                     {"path": "sandbox://workspace/dog.webp", "mime": "image/webp"}]}}}
        calls = []

        class FakeGateway:
            def call_json(self, method, body=None):
                calls.append(method)
                n = len(calls)
                if n == 1:
                    return {"chat_events": []}
                return {"chat_events": [reply] if n < 5 else [reply, image]}

            def _open(self, method, body=None):
                return 1

            def close(self):
                pass

        saved = []
        args = cli.argparse.Namespace(text="x", thread=None, wait=30, download="out")
        with patch.object(cli, "load_config", return_value={"node_id": "n"}), \
                patch.object(cli, "connect", return_value=FakeGateway()), \
                patch.object(cli, "save_resources",
                             side_effect=lambda gw, res, d: saved.extend(res) or []), \
                patch.object(cli, "POLL", 0.02), patch.object(cli, "SETTLE", 0.2), \
                patch.object(cli, "out"):
            cli.cmd_send(args)
        self.assertEqual([r["path"] for r in saved], ["sandbox://workspace/dog.webp"])

    def test_notes_when_the_wait_ends_before_the_thread_is_quiet(self):
        reply = {"seq": 5, "event_name": "message.assistant",
                 "payload": {"display_text": "hi", "status": "completed", "message_id": "m1"}}
        gw = MagicMock()
        gw.call_json.side_effect = lambda method, body=None: {
            "chat_events": [] if gw.call_json.call_count == 1 else [reply]}
        gw._open.return_value = 1
        args = cli.argparse.Namespace(text="x", thread=None, wait=1, download="out")
        results = []
        with patch.object(cli, "load_config", return_value={"node_id": "n"}), \
                patch.object(cli, "connect", return_value=gw), \
                patch.object(cli, "save_resources", return_value=[]), \
                patch.object(cli, "POLL", 0.02), patch.object(cli, "SETTLE", 60), \
                patch.object(cli, "out", side_effect=results.append):
            cli.cmd_send(args)
        self.assertIn("download_note", results[0])
        self.assertEqual(results[0]["reply"]["seq"], 5)


class StartSessionTest(unittest.TestCase):
    def test_title_is_applied_with_a_rename(self):
        gw = MagicMock()
        gw.call_json.side_effect = [{"created": True, "session_id": "s1"}, {"updated": True}]
        res = cli.start_session(gw, "hot dog court")
        self.assertEqual(res["title"], "hot dog court")
        method, kwargs = gw.call_json.call_args_list[1][0][0], gw.call_json.call_args_list[1][1]
        self.assertEqual(method, "session.rename")
        self.assertEqual(kwargs["body"], {"session_id": "s1", "title": "hot dog court"})

    def test_failed_rename_still_reports_the_created_chat(self):
        gw = MagicMock()
        gw.call_json.side_effect = [{"created": True, "session_id": "s1"},
                                    cli.GatewayError(500, "boom")]
        with patch.object(sys, "stderr", io.StringIO()):
            res = cli.start_session(gw, "hot dog court")
        self.assertEqual(res["session_id"], "s1")
        self.assertNotIn("title", res)
        self.assertIn("boom", res["title_error"])

    def test_no_title_means_no_rename(self):
        gw = MagicMock()
        gw.call_json.return_value = {"created": True, "session_id": "s1"}
        cli.start_session(gw)
        self.assertEqual(gw.call_json.call_count, 1)


class InterruptTest(unittest.TestCase):
    def test_ctrl_c_exits_130_without_traceback(self):
        def interrupted(args):
            raise KeyboardInterrupt

        with patch.object(cli, "cmd_threads", interrupted), \
                patch.object(sys, "argv", ["muse-cli", "threads"]), \
                patch.dict(os.environ, {"MUSE_NO_UPDATE_CHECK": "1"}), \
                patch.object(sys, "stderr", io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                cli.main()
        self.assertEqual(cm.exception.code, 130)
        self.assertNotIn("Traceback", err.getvalue())


class BuildParserTest(unittest.TestCase):
    def test_build_parser_registers_all_commands(self):
        ap = cli.build_parser()
        sub_actions = [a for a in ap._actions if a.dest == "cmd"]
        self.assertTrue(sub_actions)
        choices = sub_actions[0].choices
        expected = {"auth", "chat", "status", "threads", "history", "send", "files",
                    "download", "watch", "feed", "goals", "ideas", "unread", "raw"}
        self.assertTrue(expected.issubset(set(choices.keys())))


if __name__ == "__main__":
    unittest.main()
