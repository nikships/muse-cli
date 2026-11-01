import unittest
from unittest.mock import MagicMock, patch

from muse_cli import chat


class ChatReadLineTest(unittest.TestCase):
    def test_readline_imported(self):
        # On POSIX systems with standard python readline/libedit,
        # readline should be available.
        try:
            import readline as sys_readline
            self.assertIs(chat.readline, sys_readline)
        except ImportError:
            self.assertIsNone(chat.readline)

    @patch("muse_cli.chat.start")
    @patch("muse_cli.chat.input", side_effect=["/exit"])
    def test_cmd_chat_history_handled(self, mock_input, mock_start):
        mock_chat = MagicMock()
        mock_chat.st = {"title": "test chat"}
        mock_start.return_value = mock_chat

        with patch("muse_cli.chat.readline") as mock_rl:
            chat.cmd_chat(None)
            mock_rl.read_history_file.assert_called_once()
            mock_rl.write_history_file.assert_called_once()
from muse_cli.gateway import GatewayError


class DeletedSideChatRecoveryTest(unittest.TestCase):
    def test_is_not_found(self):
        err_404 = GatewayError(404, '{"ok":false,"error":{"code":"not_found","message":"session not found"}}')
        self.assertTrue(chat.is_not_found(err_404))

        err_msg = GatewayError(400, '{"error":"session not found"}')
        self.assertTrue(chat.is_not_found(err_msg))

        err_other = GatewayError(500, '{"error":"internal server error"}')
        self.assertFalse(chat.is_not_found(err_other))

        self.assertFalse(chat.is_not_found(RuntimeError("something else")))

    @patch("muse_cli.chat.save_state")
    def test_show_history_deleted_sidechat_recovers(self, mock_save_state):
        c = chat.Chat.__new__(chat.Chat)
        c.st = {"session_id": "deleted-uuid", "title": "side3"}
        c.gw = MagicMock()

        # First call to call_json (for deleted sidechat) raises 404
        # Second call to call_json (for main chat after switch) succeeds
        c.gw.call_json.side_effect = [
            GatewayError(404, '{"ok":false,"error":{"code":"not_found","message":"session not found"}}'),
            {"chat_events": []},
        ]

        c.show_history(3)

        # Should have switched to main chat
        self.assertIsNone(c.st["session_id"])
        self.assertEqual(c.st["title"], "main chat")
        mock_save_state.assert_called_with({"session_id": None, "title": "main chat"})

    @patch("muse_cli.chat.save_state")
    def test_send_deleted_sidechat_recovers(self, mock_save_state):
        c = chat.Chat.__new__(chat.Chat)
        c.st = {"session_id": "deleted-uuid", "title": "side3"}
        c.cfg = {"node_id": "test-node"}
        c.gw = MagicMock()

        # events(1) inside last_seq() raises 404
        c.gw.call_json.side_effect = [
            GatewayError(404, '{"ok":false,"error":{"code":"not_found","message":"session not found"}}'),
            {"chat_events": []},
        ]

        c.send("hello")

        # Should switch to main chat
        self.assertIsNone(c.st["session_id"])
        self.assertEqual(c.st["title"], "main chat")

    @patch("muse_cli.chat.start")
    @patch("muse_cli.chat.input", side_effect=["/exit"])
    def test_cmd_chat_startup_with_deleted_chat(self, mock_input, mock_start):
        mock_chat = MagicMock()
        mock_chat.st = {"session_id": "deleted-uuid", "title": "side3"}
        err = GatewayError(404, '{"ok":false,"error":{"code":"not_found","message":"session not found"}}')
        mock_chat.show_history.side_effect = err
        mock_start.return_value = mock_chat

        # Should not crash, should call switch(None, "main chat"), then proceed to /exit
        chat.cmd_chat(None)
        mock_chat.switch.assert_called_with(None, "main chat")
        mock_chat.gw.close.assert_called_once()


class ChatSubcommandsTest(unittest.TestCase):
    def setUp(self):
        self.c = chat.Chat.__new__(chat.Chat)
        self.c.st = {"session_id": None, "title": "main chat"}
        self.c.gw = MagicMock()

    @patch("muse_cli.cli.cmd_status")
    def test_run_cli_subcommand(self, mock_cmd_status):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        handled = self.c.run_cli("/status")
        self.assertTrue(handled)
        mock_cmd_status.assert_called_once()

    @patch("muse_cli.cli.cmd_files")
    def test_run_cli_injects_thread(self, mock_cmd_files):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        self.c.st["session_id"] = "side-123"
        self.c.run_cli("/files --limit 5")
        mock_cmd_files.assert_called_once()
        args = mock_cmd_files.call_args[0][0]
        self.assertEqual(args.thread, "side-123")
        self.assertEqual(args.limit, 5)

    @patch("muse_cli.cli.cmd_files")
    def test_run_cli_respects_explicit_thread(self, mock_cmd_files):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        self.c.st["session_id"] = "side-123"
        self.c.run_cli("/files --thread custom-thread")
        mock_cmd_files.assert_called_once()
        args = mock_cmd_files.call_args[0][0]
        self.assertEqual(args.thread, "custom-thread")

    def test_run_cli_handles_help_without_exit(self):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        # --help raises SystemExit internally in argparse; run_cli must catch it
        with patch("sys.stdout"):
            handled = self.c.run_cli("/status --help")
        self.assertTrue(handled)

    def test_run_cli_handles_invalid_flags_without_exit(self):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        with patch("sys.stderr"):
            handled = self.c.run_cli("/status --nonexistent-flag-123")
        self.assertTrue(handled)

    @patch("muse_cli.cli.cmd_download", side_effect=SystemExit(1))
    def test_run_cli_handles_handler_system_exit(self, mock_cmd_download):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        with patch("builtins.print") as mock_print:
            handled = self.c.run_cli("/download nope")
            self.assertTrue(handled)
            mock_print.assert_called_with()

    @patch("muse_cli.cli.cmd_status", side_effect=KeyboardInterrupt)
    def test_run_cli_handles_handler_keyboard_interrupt(self, mock_cmd_status):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        with patch("builtins.print") as mock_print:
            handled = self.c.run_cli("/status")
            self.assertTrue(handled)
            mock_print.assert_called_with()

    @patch("muse_cli.cli.cmd_status", side_effect=chat.AuthError("expired"))
    def test_run_cli_propagates_auth_error(self, mock_cmd_status):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        with self.assertRaises(chat.AuthError):
            self.c.run_cli("/status")

    @patch("muse_cli.cli.cmd_status", side_effect=GatewayError(404, "session not found"))
    def test_run_cli_propagates_gateway_error(self, mock_cmd_status):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        with self.assertRaises(GatewayError):
            self.c.run_cli("/status")

    def test_handle_rejects_unknown_command(self):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        with patch("builtins.print") as mock_print:
            self.c.handle("/notarealcommand")
            mock_print.assert_called_with("Unknown command. Type /help.")

    def test_handle_chat_subcommand_in_chat(self):
        from muse_cli.cli import build_parser
        self.c.parser = build_parser()
        with patch("builtins.print") as mock_print:
            self.c.handle("/chat")
            mock_print.assert_called_with("Already in chat.")


class ChatCompletionTest(unittest.TestCase):
    @patch("muse_cli.chat.connect")
    @patch("muse_cli.chat.load_config")
    @patch("muse_cli.chat.load_state")
    def test_completer_matches_slash_commands(self, mock_state, mock_cfg, mock_connect):
        mock_state.return_value = {"session_id": None, "title": "main chat"}
        mock_cfg.return_value = {}
        c = chat.Chat()
        if chat.readline is None:
            self.skipTest("readline not available")

        # Exact match
        self.assertEqual(c.complete("/status", 0), "/status")
        self.assertIsNone(c.complete("/status", 1))

        # Prefix match
        self.assertEqual(c.complete("/st", 0), "/status")

        # Goal commands
        matches = []
        i = 0
        while True:
            m = c.complete("/goa", i)
            if not m:
                break
            matches.append(m)
            i += 1
        self.assertIn("/goal", matches)
        self.assertIn("/goals", matches)

        # REPL-specific navigation commands
        self.assertEqual(c.complete("/ch", 0), "/chats")

        # Multi-word hyphenated commands
        self.assertEqual(c.complete("/feed-p", 0), "/feed-prompt")
        matches = []
        i = 0
        while True:
            m = c.complete("/session-", i)
            if not m:
                break
            matches.append(m)
            i += 1
        self.assertIn("/session-archive", matches)
        self.assertIn("/session-start", matches)

        # Non-slash text should return no matches
        self.assertIsNone(c.complete("hello", 0))

        # Check delimiter configuration
        delims = chat.readline.get_completer_delims()
        self.assertNotIn("/", delims)
        self.assertNotIn("-", delims)


if __name__ == "__main__":
    unittest.main()
