import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from mc_log_listener import extract_payload, parse_event


class MCLogListenerTests(unittest.TestCase):
    def test_extract_payload_strips_minecraft_log_prefix(self):
        line = "[21:16:01] [Server thread/INFO]: <alice> hello there"

        self.assertEqual(extract_payload(line), "<alice> hello there")

    def test_parse_event_returns_chat_event(self):
        event = parse_event("[21:16:01] [Server thread/INFO]: <alice> hello there")

        self.assertEqual(event["type"], "chat")
        self.assertEqual(event["player"], "alice")
        self.assertEqual(event["message"], "hello there")

    def test_parse_event_returns_join_event(self):
        event = parse_event("[21:16:01] [Server thread/INFO]: bob joined the game")

        self.assertEqual(event["type"], "join")
        self.assertEqual(event["player"], "bob")

    def test_parse_event_returns_leave_event(self):
        event = parse_event("[21:16:01] [Server thread/INFO]: bob left the game")

        self.assertEqual(event["type"], "leave")
        self.assertEqual(event["player"], "bob")

    def test_parse_event_ignores_non_chat_system_line(self):
        self.assertIsNone(parse_event("[21:16:01] [Server thread/INFO]: UUID of player bob is 1234"))


if __name__ == "__main__":
    unittest.main()
