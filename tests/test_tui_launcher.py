import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from muse_cli import cli, tui


def done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


def make_app(root):
    app = Path(root) / "app"
    (app / "src").mkdir(parents=True)
    (app / "src" / "main.tsx").write_text("console.log('hi')\n")
    (app / "package.json").write_text("{}\n")
    (app / "bun.lock").write_text("lock\n")
    return app


class BunDiscoveryTest(unittest.TestCase):
    def test_path_first_then_home(self):
        with patch.object(tui.shutil, "which", return_value="/opt/bun"):
            self.assertEqual(tui.find_bun(), "/opt/bun")
        with tempfile.TemporaryDirectory() as tmp:
            home_bun = Path(tmp) / ".bun" / "bin" / ("bun.exe" if os.name == "nt" else "bun")
            with patch.object(tui.shutil, "which", return_value=None), \
                    patch.object(tui.Path, "home", return_value=Path(tmp)):
                self.assertIsNone(tui.find_bun())
                home_bun.parent.mkdir(parents=True)
                home_bun.write_text("#!/bin/sh\n")
                home_bun.chmod(0o755)
                self.assertEqual(tui.find_bun(), str(home_bun))

    def test_version_parse(self):
        with patch.object(tui.subprocess, "run", return_value=done(out="1.3.14\n")):
            self.assertEqual(tui.bun_version("bun"), (1, 3, 14))
        with patch.object(tui.subprocess, "run", return_value=done(out="1.4.0-canary.12+abc\n")):
            self.assertEqual(tui.bun_version("bun"), (1, 4, 0))
        with patch.object(tui.subprocess, "run", return_value=done(1, "", "boom")):
            self.assertIsNone(tui.bun_version("bun"))
        with patch.object(tui.subprocess, "run", side_effect=OSError("gone")):
            self.assertIsNone(tui.bun_version("bun"))

    def test_version_gate(self):
        with patch.object(tui, "find_bun", return_value="/b"):
            for version, ok in [("1.3.13", False), ("1.3.14", True), ("1.10.0", True), ("0.9.9", False)]:
                with patch.object(tui.subprocess, "run", return_value=done(out=version)):
                    self.assertEqual(tui.usable_bun(), "/b" if ok else None, version)
        with patch.object(tui, "find_bun", return_value=None):
            self.assertIsNone(tui.usable_bun())


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = make_app(self.root)
        self.env = patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")})
        self.env.start()
        os.environ.pop("MUSE_CLI_TUI_DIR", None)
        self.quiet = patch("sys.stderr")
        self.quiet.start()

    def tearDown(self):
        self.quiet.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_hash_covers_files_but_not_node_modules(self):
        h = tui.app_hash(self.app)
        self.assertEqual(len(h), 12)
        (self.app / "node_modules" / "x").mkdir(parents=True)
        (self.app / "node_modules" / "x" / "index.js").write_text("big")
        self.assertEqual(tui.app_hash(self.app), h)
        (self.app / "src" / "main.tsx").write_text("changed")
        self.assertNotEqual(tui.app_hash(self.app), h)

    def test_copies_installs_once_and_marks(self):
        (self.app / "node_modules").mkdir()
        (self.app / "node_modules" / "junk").write_text("x")
        with patch.object(tui.subprocess, "run", return_value=done()) as run:
            d = tui.prepare("/b", src=self.app)
            self.assertEqual(d, self.root / "cache" / "muse-cli" / "tui" / tui.app_hash(self.app))
            self.assertTrue((d / "src" / "main.tsx").is_file())
            self.assertFalse((d / "node_modules").exists())
            self.assertTrue((d / tui.MARKER).is_file())
            run.assert_called_once()
            self.assertEqual(run.call_args[0][0], ["/b", "install", "--frozen-lockfile"])
            self.assertEqual(run.call_args[1]["cwd"], str(d))
            self.assertEqual(tui.prepare("/b", src=self.app), d)
            run.assert_called_once()
        leftovers = [p.name for p in d.parent.iterdir() if p.name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_failed_install_is_retried(self):
        with patch.object(tui.subprocess, "run", return_value=done(1, "", "error: lockfile had changes")):
            with self.assertRaises(tui.SetupError) as cm:
                tui.prepare("/b", src=self.app)
        self.assertIn("lockfile had changes", str(cm.exception))
        dest = tui.cache_root() / tui.app_hash(self.app)
        self.assertFalse((dest / tui.MARKER).exists())
        with patch.object(tui.subprocess, "run", return_value=done()) as run:
            self.assertEqual(tui.prepare("/b", src=self.app), dest)
            run.assert_called_once()
        self.assertTrue((dest / tui.MARKER).exists())

    def test_new_version_prunes_stale_copies(self):
        root = tui.cache_root()
        old = root / "aaaaaaaaaaaa"
        busy = root / "bbbbbbbbbbbb"
        for d in (old, busy):
            (d / "src").mkdir(parents=True)
        stale = tui.time.time() - tui.STALE_AFTER - 60
        os.utime(old, (stale, stale))
        with patch.object(tui.subprocess, "run", return_value=done()):
            d = tui.prepare("/b", src=self.app)
        self.assertTrue(d.is_dir())
        self.assertFalse(old.exists())
        self.assertTrue(busy.exists())

    def test_tui_dir_runs_in_place(self):
        with patch.dict(os.environ, {"MUSE_CLI_TUI_DIR": str(self.app)}), \
                patch.object(tui.subprocess, "run", return_value=done()) as run:
            self.assertEqual(tui.prepare("/b", src=self.root / "nowhere"), self.app.resolve())
            run.assert_called_once()
            (self.app / "node_modules").mkdir()
            tui.prepare("/b")
            run.assert_called_once()
        self.assertFalse((self.root / "cache").exists())

    def test_shipped_app_is_complete(self):
        names = {p.as_posix() for p in tui.app_files(tui.APP_DIR)}
        for name in ("package.json", "bun.lock", "tsconfig.json", "src/main.tsx"):
            self.assertIn(name, names)
        self.assertFalse(any(n.startswith("node_modules") for n in names))


class RunAppTest(unittest.TestCase):
    def test_env_and_exit_codes(self):
        proc = MagicMock()
        proc.wait.return_value = -2
        with patch.object(tui.subprocess, "Popen", return_value=proc) as popen:
            self.assertEqual(tui.run_app("/b", "/app", demo=True), 130)
        argv = popen.call_args[0][0]
        env = popen.call_args[1]["env"]
        self.assertEqual(argv, ["/b", str(Path("/app") / "src" / "main.tsx")])
        self.assertEqual(env["MUSE_CLI_PYTHON"], tui.sys.executable)
        self.assertEqual(env["MUSE_CLI_DEMO"], "1")
        self.assertEqual(env["NODE_ENV"], "production")
        proc.wait.return_value = 3
        with patch.dict(os.environ, {}, clear=False), \
                patch.object(tui.subprocess, "Popen", return_value=proc) as popen:
            os.environ.pop("MUSE_CLI_DEMO", None)
            self.assertEqual(tui.run_app("/b", "/app", demo=False), 3)
            self.assertNotIn("MUSE_CLI_DEMO", popen.call_args[1]["env"])


class LaunchTest(unittest.TestCase):
    def test_runs_app(self):
        with patch.object(tui, "prepare", return_value="/app"), \
                patch.object(tui, "run_app", return_value=0) as run:
            self.assertEqual(tui.launch(None, bun="/b"), 0)
        run.assert_called_once_with("/b", "/app", False)

    def test_bun_missing_falls_back_to_plain_chat(self):
        with patch.object(tui, "usable_bun", return_value=None), \
                patch.object(tui, "offer_bun_install", return_value=None) as offer, \
                patch("muse_cli.chat.cmd_chat") as chat, \
                patch("sys.stderr") as err:
            self.assertIsNone(tui.launch("ARGS"))
        offer.assert_called_once()
        chat.assert_called_once_with("ARGS")
        self.assertIn("plain chat", "".join(c.args[0] for c in err.write.call_args_list))

    def test_demo_never_falls_back_to_real_chat(self):
        with patch.object(tui, "usable_bun", return_value=None), \
                patch.object(tui, "offer_bun_install", return_value=None), \
                patch("muse_cli.chat.cmd_chat") as chat, patch("sys.stderr"):
            self.assertEqual(tui.launch(None, demo=True), 1)
        chat.assert_not_called()

    def test_install_failure_falls_back(self):
        with patch.object(tui, "prepare", side_effect=tui.SetupError("bun install failed")), \
                patch("muse_cli.chat.cmd_chat") as chat, patch("sys.stderr"):
            self.assertIsNone(tui.launch(None, bun="/b"))
        chat.assert_called_once()

    def test_no_prompt_when_asked_not_to(self):
        with patch.object(tui, "usable_bun", return_value=None), \
                patch.object(tui, "offer_bun_install") as offer, \
                patch("muse_cli.chat.cmd_chat"), patch("sys.stderr"):
            tui.launch(None, ask=False)
        offer.assert_not_called()


class OfferBunTest(unittest.TestCase):
    def test_not_a_terminal(self):
        with patch.object(tui, "is_tty", return_value=False), \
                patch("builtins.input") as ask:
            self.assertIsNone(tui.offer_bun_install())
        ask.assert_not_called()

    def test_declined(self):
        with patch.object(tui, "is_tty", return_value=True), \
                patch("builtins.input", return_value="n"), \
                patch.object(tui.subprocess, "run") as run:
            self.assertIsNone(tui.offer_bun_install())
        run.assert_not_called()

    def test_accepted_runs_official_installer(self):
        with patch.object(tui, "is_tty", return_value=True), \
                patch("builtins.input", return_value=""), \
                patch.object(tui.subprocess, "run", return_value=done()) as run, \
                patch.object(tui, "usable_bun", return_value="/home/.bun/bin/bun"):
            self.assertEqual(tui.offer_bun_install(), "/home/.bun/bin/bun")
        argv = run.call_args[0][0]
        if os.name == "nt":
            self.assertEqual(argv, ["powershell", "-c", "irm bun.sh/install.ps1 | iex"])
        else:
            self.assertEqual(argv, ["bash", "-c", "curl -fsSL https://bun.sh/install | bash"])

    def test_installer_failure(self):
        with patch.object(tui, "is_tty", return_value=True), \
                patch("builtins.input", return_value="y"), \
                patch.object(tui.subprocess, "run", return_value=done(1)), \
                patch.object(tui, "usable_bun") as usable:
            self.assertIsNone(tui.offer_bun_install())
        usable.assert_not_called()


class RoutingTest(unittest.TestCase):
    def setUp(self):
        patches = [patch.object(cli, "start_update_check", return_value=None),
                   patch.object(cli, "finish_update_check")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_should_open(self):
        with patch.object(tui, "is_tty", return_value=True), \
                patch.object(tui, "usable_bun", return_value="/b"):
            with patch.dict(os.environ, {"MUSE_CLI_UI": ""}):
                self.assertEqual(tui.should_open(), "/b")
            with patch.dict(os.environ, {"MUSE_CLI_UI": "plain"}):
                self.assertIsNone(tui.should_open())
        with patch.object(tui, "is_tty", return_value=False), \
                patch.object(tui, "usable_bun", return_value="/b"):
            self.assertIsNone(tui.should_open())
        with patch.object(tui, "is_tty", return_value=True), \
                patch.object(tui, "usable_bun", return_value=None):
            self.assertIsNone(tui.should_open())

    def test_bare_opens_app_without_prompting(self):
        with patch.object(tui, "should_open", return_value="/b"), \
                patch.object(tui, "launch", return_value=0) as launch, \
                patch.object(cli, "_chat") as chat:
            cli.main([])
        chat.assert_not_called()
        self.assertEqual(launch.call_args[1], {"demo": False, "bun": "/b", "ask": False})

    def test_bare_falls_back_to_plain_chat(self):
        with patch.object(tui, "should_open", return_value=None), \
                patch.object(tui, "launch") as launch, \
                patch("muse_cli.chat.cmd_chat") as chat:
            cli.main([])
        launch.assert_not_called()
        chat.assert_called_once()

    def test_chat_command_unchanged(self):
        with patch.object(tui, "should_open") as should, \
                patch("muse_cli.chat.cmd_chat") as chat:
            cli.main(["chat"])
        should.assert_not_called()
        chat.assert_called_once()

    def test_tui_command_and_exit_code(self):
        with patch.object(tui, "launch", return_value=4) as launch:
            with self.assertRaises(SystemExit) as cm:
                cli.main(["tui", "--demo"])
        self.assertEqual(cm.exception.code, 4)
        self.assertEqual(launch.call_args[1], {"demo": True, "bun": None, "ask": True})
        with patch.object(tui, "launch", return_value=0):
            cli.main(["tui"])


if __name__ == "__main__":
    unittest.main()
