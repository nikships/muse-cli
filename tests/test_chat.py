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


if __name__ == "__main__":
    unittest.main()
