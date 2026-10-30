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
        mock_chat.gw.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
