import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from bridge_components import BridgeState
from bridge_config import load_config
from mc_ai_bridge import MCAIBridge

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "chat_replays.json"


class FixtureInvoker:
    def __init__(self, *, judge_response: dict, reply_text: str | None = None, router_response: dict | None = None):
        self.calls = []
        self.router_response = dict(router_response or {})
        self.responses = [
            (json.dumps(judge_response, ensure_ascii=False), {}),
        ]
        if reply_text is not None:
            self.responses.append((reply_text, {"reply": reply_text}))

    def _is_router_prompt(self, prompt_path):
        return "router_prompt.txt" in str(prompt_path)

    def _synthetic_router_fallback_response(self):
        if self.router_response:
            return json.dumps(self.router_response, ensure_ascii=False), {}
        return json.dumps({
            "mode": "chat",
            "requested_mode": "chat",
            "denied_by_permission": False,
            "confidence": 0.0,
            "enter_or_continue": "none",
            "private_requested": False,
            "topic": "",
            "reason": "synthetic fixture router fallback",
        }), {}

    def call_prompt(self, payload, prompt_path):
        if self._is_router_prompt(prompt_path):
            if self.router_response:
                self.calls.append({"payload": payload, "prompt_path": prompt_path})
            return self._synthetic_router_fallback_response()
        self.calls.append({"payload": payload, "prompt_path": prompt_path})
        if not self.responses:
            raise AssertionError("No fixture responses left for call_prompt")
        return self.responses.pop(0)


class StubDelivery:
    def __init__(self):
        self.sent = []

    def send_reply(self, reply: str):
        self.sent.append(reply)
        return {"sent": True, "stdout": "ok"}


def absolute_timestamp(now: float, entry: dict) -> float:
    if "timestamp" in entry:
        return float(entry["timestamp"])
    return now - float(entry.get("seconds_ago", 0.0))


def materialize_state(raw: dict, *, now: float) -> dict:
    state = {
        "botConsecutiveReplyCount": int(raw.get("botConsecutiveReplyCount", 0)),
    }
    if "lastGlobalReplySecondsAgo" in raw:
        state["lastGlobalReplyTs"] = now - float(raw["lastGlobalReplySecondsAgo"])
    if "lastPlayerReplySecondsAgo" in raw:
        state["lastPlayerReplyTs"] = {
            player: now - float(seconds_ago)
            for player, seconds_ago in dict(raw["lastPlayerReplySecondsAgo"]).items()
        }
    if "recentBotReplies" in raw:
        state["recentBotReplies"] = [
            {
                "text": str(entry.get("text") or ""),
                "timestamp": absolute_timestamp(now, entry),
            }
            for entry in list(raw["recentBotReplies"])
        ]
    if "recentChat" in raw:
        state["recentChat"] = [
            {
                "speaker": str(entry.get("speaker") or ""),
                "text": str(entry.get("text") or ""),
                "type": str(entry.get("type") or "player"),
                "timestamp": absolute_timestamp(now, entry),
            }
            for entry in list(raw["recentChat"])
        ]
    if "playerMessageHistory" in raw:
        state["playerMessageHistory"] = {
            player: [
                {
                    "text": str(entry.get("text") or ""),
                    "timestamp": absolute_timestamp(now, entry),
                }
                for entry in list(entries)
            ]
            for player, entries in dict(raw["playerMessageHistory"]).items()
        }
    return state


class ChatReplayTests(unittest.TestCase):
    def make_config(self):
        config = load_config(Path("__missing_config__.json"))
        config.update({
            "debugLogInputs": False,
            "debugLogScores": False,
            "debugLogSummary": False,
            "globalCooldownSeconds": 0,
            "playerCooldownSeconds": 0,
            "allowAppreciationReplies": True,
            "sendToMinecraft": False,
        })
        return config

    def test_chat_replay_cases(self):
        cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        for case in cases:
            with self.subTest(case=case["name"]):
                config = self.make_config()
                config.update(case.get("config_overrides") or {})

                with tempfile.TemporaryDirectory() as tmpdir:
                    state = BridgeState(Path(tmpdir) / "state.json")
                    state.data.update(materialize_state(case.get("initial_state") or {}, now=time.time()))

                    bridge = MCAIBridge(config=config, state=state)
                    invoker = FixtureInvoker(
                        judge_response=dict(case["judge_response"]),
                        reply_text=case.get("reply_text"),
                        router_response=case.get("router_response"),
                    )
                    delivery = StubDelivery()
                    bridge.invoker = invoker
                    bridge.delivery = delivery

                    event = dict(case["event"])
                    event.setdefault("type", "chat")
                    event.setdefault("raw", f"<{event['player']}> {event['message']}")

                    bridge.handle_event(event)

                    expected = dict(case["expected"])
                    self.assertEqual(delivery.sent, list(expected.get("sent") or []))
                    self.assertEqual(len(invoker.calls), int(expected.get("invoker_calls", len(invoker.calls))))
                    self.assertEqual(state.data["botConsecutiveReplyCount"], int(expected.get("bot_reply_streak", 0)))
                    if "reply_decision_reason" in expected:
                        self.assertGreaterEqual(len(invoker.calls), 2)
                        self.assertEqual(
                            invoker.calls[1]["payload"]["decision"]["reason"],
                            expected["reply_decision_reason"],
                        )


if __name__ == "__main__":
    unittest.main()
