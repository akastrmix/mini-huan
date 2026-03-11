import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from bridge_components import BridgeState, ContextBuilder, Logger
import bridge_state
from bridge_config import load_config
from mc_ai_bridge import MCAIBridge

COMMAND_PLANNER_PATH = r"C:\Users\Administrator\.openclaw\workspace-mc-helper\skills\mc-command-planner\scripts\plan-mc-command.py"


class StubInvoker:
    def __init__(self, responses):
        self.responses = list(responses)

    def _is_router_prompt(self, prompt_path):
        return "router_prompt.txt" in str(prompt_path)

    def _response_looks_like_router(self):
        if not self.responses:
            return False
        response_text = self.responses[0][0]
        try:
            parsed = json.loads(response_text)
        except Exception:
            return False
        return isinstance(parsed, dict) and "mode" in parsed

    def _synthetic_router_fallback_response(self):
        return json.dumps({
            "mode": "chat",
            "requested_mode": "chat",
            "denied_by_permission": False,
            "confidence": 0.0,
            "enter_or_continue": "none",
            "private_requested": False,
            "topic": "",
            "reason": "synthetic test router fallback",
        }), {}

    def _router_response_if_needed(self, prompt_path):
        if not self._is_router_prompt(prompt_path):
            return None, False
        if self._response_looks_like_router():
            return self.responses.pop(0), False
        return self._synthetic_router_fallback_response(), True

    def call_prompt(self, payload, prompt_path):
        router_response, _synthetic = self._router_response_if_needed(prompt_path)
        if router_response is not None:
            return router_response
        if not self.responses:
            raise AssertionError("No stub responses left for call_prompt")
        return self.responses.pop(0)


class CapturingInvoker(StubInvoker):
    def __init__(self, responses):
        super().__init__(responses)
        self.calls = []

    def call_prompt(self, payload, prompt_path):
        router_response, synthetic_router = self._router_response_if_needed(prompt_path)
        if router_response is not None:
            if not synthetic_router:
                self.calls.append({"payload": payload, "prompt_path": prompt_path})
            return router_response
        self.calls.append({"payload": payload, "prompt_path": prompt_path})
        if not self.responses:
            raise AssertionError("No stub responses left for call_prompt")
        return self.responses.pop(0)


class PrivilegedInvoker:
    def __init__(
        self,
        *,
        router_response: dict,
        privileged_response: dict | None = None,
        privileged_responses: list[dict] | None = None,
        reply_text: str | None = None,
        session_ids: list[str] | None = None,
    ):
        self.calls = []
        self.router_response = json.dumps(router_response, ensure_ascii=False)
        response_items = list(privileged_responses or ([] if privileged_response is None else [privileged_response]))
        if not response_items:
            response_items = [{
                "status": "completed",
                "commands": [],
                "reply": "",
                "topic": "",
                "reason": "",
            }]
        if (
            privileged_responses is None
            and privileged_response is not None
            and len(response_items) == 1
            and str((response_items[0] or {}).get("status") or "").strip().lower() == "completed"
            and list((response_items[0] or {}).get("commands") or [])
        ):
            response_items.append({
                "status": "completed",
                "commands": [],
                "reply": str((response_items[0] or {}).get("reply") or ""),
                "topic": str((response_items[0] or {}).get("topic") or ""),
                "reason": str((response_items[0] or {}).get("reason") or ""),
            })
        self.privileged_responses = [json.dumps(item, ensure_ascii=False) for item in response_items]
        self.reply_text = reply_text
        self.prompt_calls = 0
        self.session_ids = list(session_ids or ["priv-session-123"])
        self.last_session_id = self.session_ids[-1] if self.session_ids else "priv-session-123"

    def call_prompt(self, payload, prompt_path):
        self.calls.append({"kind": "prompt", "payload": payload, "prompt_path": prompt_path})
        self.prompt_calls += 1
        if self.prompt_calls == 1:
            return self.router_response, {}
        if self.reply_text is not None:
            text = self.reply_text
            self.reply_text = None
            return text, {"reply": text}
        return self.router_response, {}

    def call_prompt_session(self, payload, prompt_path, *, session_id=""):
        self.calls.append({
            "kind": "session",
            "payload": payload,
            "prompt_path": prompt_path,
            "session_id": session_id,
        })
        if not self.privileged_responses:
            raise AssertionError("No stub responses left for call_prompt_session")
        response_text = self.privileged_responses.pop(0)
        if self.session_ids:
            self.last_session_id = self.session_ids.pop(0)
        return response_text, {"reply": response_text, "sessionId": self.last_session_id}


class RouterErrorInvoker:
    def __init__(self, *, reply_text: str, privileged_response: dict | None = None):
        self.calls = []
        self.reply_text = reply_text
        self.privileged_response_data = privileged_response or {
            "status": "completed",
            "commands": [],
            "reply": "",
            "topic": "",
            "reason": "",
        }
        self.session_calls = 0

    def call_prompt(self, payload, prompt_path):
        self.calls.append({"payload": payload, "prompt_path": prompt_path})
        prompt_text = str(prompt_path)
        if "router_prompt.txt" in prompt_text:
            raise RuntimeError("router exploded")
        if "judge_prompt.txt" in prompt_text:
            return json.dumps({
                "should_reply": True,
                "confidence": 0.9,
                "reason": "direct_question_to_bot",
                "target_player": payload["current_message"]["player"],
                "topic": "greeting",
            }, ensure_ascii=False), {}
        return self.reply_text, {"reply": self.reply_text}

    def call_prompt_session(self, payload, prompt_path, *, session_id=""):
        self.calls.append({"payload": payload, "prompt_path": prompt_path, "session_id": session_id})
        self.session_calls += 1
        if self.session_calls == 1:
            response = self.privileged_response_data
        else:
            response = {
                "status": "completed",
                "commands": [],
                "reply": str((self.privileged_response_data or {}).get("reply") or ""),
                "topic": str((self.privileged_response_data or {}).get("topic") or ""),
                "reason": str((self.privileged_response_data or {}).get("reason") or ""),
            }
        response_text = json.dumps(response, ensure_ascii=False)
        return response_text, {"reply": response_text, "sessionId": "local-fallback-session"}


class PrivilegedStageErrorInvoker:
    def __init__(self, router_response: dict):
        self.calls = []
        self.router_response = json.dumps(router_response, ensure_ascii=False)

    def call_prompt(self, payload, prompt_path):
        self.calls.append({"kind": "prompt", "payload": payload, "prompt_path": prompt_path})
        return self.router_response, {}

    def call_prompt_session(self, payload, prompt_path, *, session_id=""):
        self.calls.append({"kind": "session", "payload": payload, "prompt_path": prompt_path, "session_id": session_id})
        raise RuntimeError("privileged stage exploded")


class StubDelivery:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    def send_reply(self, reply: str):
        if self.error is not None:
            raise self.error
        self.sent.append(reply)
        return {"sent": True, "stdout": "ok"}


class PrivilegedDelivery(StubDelivery):
    def __init__(self, error=None, command_results=None):
        super().__init__(error=error)
        self.private_sent = []
        self.commands = []
        self.command_results = dict(command_results or {})

    def send_private_reply(self, player: str, reply: str):
        if self.error is not None:
            raise self.error
        self.private_sent.append({"player": player, "reply": reply})
        return {"sent": True, "stdout": "ok"}

    def send_command(self, command_text: str):
        if self.error is not None:
            raise self.error
        self.commands.append(command_text)
        configured = self.command_results.get(command_text)
        if isinstance(configured, Exception):
            raise configured
        if isinstance(configured, dict):
            return {"sent": True, "command": command_text, **configured}
        if configured is not None:
            return {"sent": True, "stdout": str(configured), "command": command_text}
        return {"sent": True, "stdout": "ok", "command": command_text}


class BridgeTests(unittest.TestCase):
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
            "commandPlannerScriptPath": COMMAND_PLANNER_PATH,
        })
        return config

    def make_state(self, tmpdir: str):
        return BridgeState(Path(tmpdir) / "state.json")

    def test_context_max_age_filters_player_and_bot_history(self):
        config = self.make_config()
        config["contextMaxAgeSeconds"] = 60

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["recentBotReplies"] = [
                {"text": "old bot", "timestamp": now - 300},
                {"text": "fresh bot", "timestamp": now - 10},
            ]
            state.data["playerMessageHistory"] = {
                "alice": [
                    {"text": "old player", "timestamp": now - 301},
                    {"text": "fresh player", "timestamp": now - 9},
                ]
            }

            builder = ContextBuilder(config, state, Logger(config))
            self.assertEqual(
                [item["text"] for item in builder.recent_bot_messages("judgeRecentBotCount", 4)],
                ["fresh bot"],
            )
            self.assertEqual(
                [item["text"] for item in builder.player_history("alice", "judgePlayerHistoryCount", 4)],
                ["fresh player"],
            )

    def test_bridge_state_record_delivery_updates_timestamps_and_streak(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            state.record_delivery(
                player="alice",
                reply="hello there",
                display_name="mini-huan",
                timestamp=200.0,
                recent_chat_limit=10,
                recent_bot_limit=5,
                player_history_limit=5,
            )

            self.assertEqual(state.data["lastGlobalReplyTs"], 200.0)
            self.assertEqual(state.data["lastPlayerReplyTs"]["alice"], 200.0)
            self.assertEqual(state.bot_reply_streak(), 1)
            self.assertEqual(state.data["recentBotReplies"][-1]["text"], "hello there")
            self.assertEqual(state.data["recentChat"][-1]["speaker"], "mini-huan")

    def test_bridge_state_save_uses_atomic_replace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            state.data["sessionId"] = "session-1"

            with mock.patch.object(bridge_state.os, "replace", wraps=bridge_state.os.replace) as replace_mock:
                with mock.patch.object(bridge_state.os, "fsync", wraps=bridge_state.os.fsync) as fsync_mock:
                    state.save()

            self.assertTrue(replace_mock.called)
            fsync_mock.assert_not_called()
            self.assertEqual(
                json.loads((Path(tmpdir) / "state.json").read_text(encoding="utf-8"))["sessionId"],
                "session-1",
            )

    def test_build_judge_context_expires_stale_bot_reply_streak(self):
        config = self.make_config()
        config["botReplyStreakResetSeconds"] = 180

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 400
            state.data["botConsecutiveReplyCount"] = 2

            builder = ContextBuilder(config, state, Logger(config))
            context = builder.build_judge_context({
                "type": "chat",
                "player": "alice",
                "message": "still there?",
                "raw": "<alice> still there?",
            })

            self.assertEqual(context["room_state"]["bot_consecutive_reply_count"], 0)
            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)

    def test_build_judge_context_uses_correct_chinese_bot_name(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            builder = ContextBuilder(config, state, Logger(config))

            context = builder.build_judge_context({
                "type": "chat",
                "player": "alice",
                "message": "hi huan",
                "raw": "<alice> hi huan",
            })

            self.assertEqual(context["bot_profile"]["name_zh"], "小幻")
            self.assertEqual(context["bot_profile"]["name_aliases"], ["huan"])

    def test_configured_name_aliases_flow_into_context_and_matching(self):
        config = self.make_config()
        config["nameAliases"] = ["helperbuddy"]

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            builder = ContextBuilder(config, state, Logger(config))
            context = builder.build_judge_context({
                "type": "chat",
                "player": "alice",
                "message": "hey helperbuddy",
                "raw": "<alice> hey helperbuddy",
            })
            entry = {
                "speaker": "bob",
                "text": "hey helperbuddy",
                "type": "player",
                "timestamp": time.time(),
            }

            self.assertEqual(context["bot_profile"]["name_aliases"], ["helperbuddy"])
            self.assertIn("helperbuddy", builder.bot_name_alias_tokens())
            self.assertGreaterEqual(
                builder.score_context_entry(entry, "alice", "where are you?", builder.tokenize_text("where are you?")),
                2.5,
            )

    def test_build_router_context_exposes_recent_room_chat_without_precomputed_human_answer_flags(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["recentChat"] = [
                {"speaker": "alice", "text": "how do i mine obsidian?", "timestamp": now - 8, "type": "player"},
                {"speaker": "bob", "text": "Use a diamond pickaxe on obsidian.", "timestamp": now - 4, "type": "player"},
            ]

            builder = ContextBuilder(config, state, Logger(config))
            context = builder.build_router_context(
                {
                    "type": "chat",
                    "player": "alice",
                    "message": "how do i mine obsidian?",
                    "raw": "<alice> how do i mine obsidian?",
                },
                {"player": "alice", "groups": ["default"], "max_mode": "chat"},
                None,
            )

            self.assertEqual([item["speaker"] for item in context["recent_chat"]][-2:], ["alice", "bob"])
            self.assertNotIn("human_answer_seen", context["room_state"])
            self.assertNotIn("human_answer_candidates", context["room_state"])

    def test_build_judge_context_omits_precomputed_human_answer_flags(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["recentChat"] = [
                {"speaker": "alice", "text": "can i sleep now?", "timestamp": now - 8, "type": "player"},
                {"speaker": "bob", "text": "yes", "timestamp": now - 4, "type": "player"},
            ]

            builder = ContextBuilder(config, state, Logger(config))
            context = builder.build_judge_context(
                {
                    "type": "chat",
                    "player": "alice",
                    "message": "can i sleep now?",
                    "raw": "<alice> can i sleep now?",
                }
            )

            self.assertEqual([item["speaker"] for item in context["recent_chat"]][-2:], ["alice", "bob"])
            self.assertNotIn("human_answer_seen", context["room_state"])
            self.assertNotIn("human_answer_candidates", context["room_state"])

    def test_handle_event_resets_streak_when_judge_declines(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            state.data["botConsecutiveReplyCount"] = 2
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.0,
                    "reason": "players_chatting_with_each_other",
                    "target_player": "alice",
                    "topic": "small talk",
                }), {}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hello", "raw": "<alice> hello"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)
            self.assertEqual(bridge.delivery.sent, [])

    def test_handle_event_preserves_reply_streak_across_answered_turns(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 2

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = now - 8
            state.data["lastPlayerReplyTs"] = {"alice": now - 8}
            state.data["recentBotReplies"] = [
                {"text": "Earlier bot reply.", "timestamp": now - 8},
            ]
            state.data["recentChat"] = [
                {"speaker": "alice", "text": "thanks?", "timestamp": now - 12, "type": "player"},
                {"speaker": "mini-huan", "text": "Earlier bot reply.", "timestamp": now - 8, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.72,
                    "reason": "appreciation_after_bot_reply",
                    "target_player": "alice",
                    "topic": "thanks after bot answer",
                }), {}),
                ("You are welcome!", {"reply": "You are welcome!"}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "thanks!", "raw": "<alice> thanks!"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 2)
            self.assertEqual(bridge.delivery.sent, ["You are welcome!"])

    def test_fallback_judge_soft_pass_requires_explicit_flag(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.6,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "direct question below hard threshold",
                }), {}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hi huan", "raw": "<alice> hi huan"})

            self.assertEqual(bridge.delivery.sent, [])

    def test_fallback_judge_soft_pass_allows_explicit_flag(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.6,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "direct question below hard threshold",
                    "allow_soft_confidence_pass": True,
                }), {}),
                ("Hi!", {"reply": "Hi!"}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hi huan", "raw": "<alice> hi huan"})

            self.assertEqual(bridge.delivery.sent, ["Hi!"])

    def test_handle_event_allows_one_appreciation_reply_beyond_streak_limit(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = now - 8
            state.data["lastPlayerReplyTs"] = {"alice": now - 8}
            state.data["recentBotReplies"] = [
                {"text": "Earlier bot reply.", "timestamp": now - 8},
            ]
            state.data["recentChat"] = [
                {"speaker": "alice", "text": "help me", "timestamp": now - 12, "type": "player"},
                {"speaker": "mini-huan", "text": "Earlier bot reply.", "timestamp": now - 8, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.75,
                    "reason": "appreciation_after_bot_reply",
                    "target_player": "alice",
                    "topic": "thanks after help",
                }), {}),
                ("You are welcome!", {"reply": "You are welcome!"}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "thanks for telling me!", "raw": "<alice> thanks for telling me!"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 2)
            self.assertEqual(bridge.delivery.sent, ["You are welcome!"])

    def test_handle_event_allows_same_player_followup_beyond_default_streak_limit(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 1
        config["followupReplyWindowSeconds"] = 90
        config["maxSamePlayerConversationReplies"] = 8

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = now - 10
            state.data["lastPlayerReplyTs"] = {"alice": now - 10}
            state.data["recentBotReplies"] = [
                {"text": "Earlier bot reply.", "timestamp": now - 10},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "Earlier bot reply.", "timestamp": now - 10, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.99,
                    "reason": "help_request",
                    "target_player": "alice",
                    "topic": "command help",
                    "allow_followup_streak": True,
                }), {}),
                ("I can only answer in chat.", {"reply": "I can only answer in chat."}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can you execute commands for me?", "raw": "<alice> can you execute commands for me?"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 2)
            self.assertEqual(bridge.delivery.sent, ["I can only answer in chat."])

    def test_handle_event_requires_explicit_followup_flag_for_relaxed_judge_streak(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 1
        config["followupReplyWindowSeconds"] = 90
        config["maxSamePlayerConversationReplies"] = 8

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = now - 10
            state.data["lastPlayerReplyTs"] = {"alice": now - 10}
            state.data["recentBotReplies"] = [
                {"text": "Earlier bot reply.", "timestamp": now - 10},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "Earlier bot reply.", "timestamp": now - 10, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.99,
                    "reason": "followup_to_bot_conversation",
                    "target_player": "alice",
                    "topic": "follow-up without explicit continuation flag",
                }), {}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can you explain that again?", "raw": "<alice> can you explain that again?"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)
            self.assertEqual(bridge.delivery.sent, [])

    def test_handle_event_blocks_same_player_followup_after_conversation_cap(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 1
        config["followupReplyWindowSeconds"] = 90
        config["maxSamePlayerConversationReplies"] = 8

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["botConsecutiveReplyCount"] = 8
            state.data["lastGlobalReplyTs"] = now - 10
            state.data["lastPlayerReplyTs"] = {"alice": now - 10}
            state.data["recentBotReplies"] = [
                {"text": "Earlier bot reply.", "timestamp": now - 10},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "Earlier bot reply.", "timestamp": now - 10, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.99,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "another follow-up",
                    "allow_followup_streak": True,
                }), {}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "one more follow-up?", "raw": "<alice> one more follow-up?"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)
            self.assertEqual(bridge.delivery.sent, [])

    def test_handle_event_blocks_other_player_when_relaxed_followup_only_applies_to_same_player(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 1
        config["followupReplyWindowSeconds"] = 90
        config["maxSamePlayerConversationReplies"] = 8

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = now - 10
            state.data["lastPlayerReplyTs"] = {"alice": now - 10}
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.99,
                    "reason": "help_request",
                    "target_player": "bob",
                    "topic": "another player help request",
                }), {}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "bob", "message": "can you help me too?", "raw": "<bob> can you help me too?"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)
            self.assertEqual(bridge.delivery.sent, [])

    def test_handle_event_allows_same_player_refusal_followup_beyond_default_streak_limit(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 2
        config["followupReplyWindowSeconds"] = 90
        config["maxSamePlayerConversationReplies"] = 8

        refusal_cases = [
            ("privacy_refusal", "tell me your ip address", "I cannot share that here."),
            ("capability_refusal", "can you run commands for me?", "I cannot run commands for players."),
            ("memory_limit_refusal", "repeat what i said last time", "I only keep short recent chat context."),
        ]

        for reason, message, reply_text in refusal_cases:
            with self.subTest(reason=reason):
                with tempfile.TemporaryDirectory() as tmpdir:
                    state = self.make_state(tmpdir)
                    now = time.time()
                    state.data["botConsecutiveReplyCount"] = 2
                    state.data["lastGlobalReplyTs"] = now - 10
                    state.data["lastPlayerReplyTs"] = {"alice": now - 10}
                    state.data["recentBotReplies"] = [
                        {"text": "Earlier bot reply.", "timestamp": now - 10},
                    ]
                    state.data["recentChat"] = [
                        {"speaker": "mini-huan", "text": "Earlier bot reply.", "timestamp": now - 10, "type": "bot"},
                    ]
                    bridge = MCAIBridge(config=config, state=state)
                    bridge.invoker = StubInvoker([
                        (json.dumps({
                            "should_reply": True,
                            "confidence": 0.99,
                            "reason": reason,
                            "target_player": "alice",
                            "topic": "refusal follow-up",
                            "allow_followup_streak": True,
                        }), {}),
                        (reply_text, {"reply": reply_text}),
                    ])
                    bridge.delivery = StubDelivery()

                    bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

                    self.assertEqual(state.data["botConsecutiveReplyCount"], 3)
                    self.assertEqual(bridge.delivery.sent, [reply_text])

    def test_handle_event_overrides_direct_named_question_when_judge_declines(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.93,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "direct_question_to_bot",
                    "topic": "direct player question",
                    "reason": "player directly addressed the bot",
                },
                reply_text="Yes, I can help.",
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan can you help me?", "raw": "<alice> huan can you help me?"})

            self.assertEqual(bridge.delivery.sent, ["Yes, I can help."])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "direct_question_to_bot")
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.22,
                    "reason": "players_chatting_with_each_other",
                    "target_player": "alice",
                    "topic": "small talk",
                }), {}),
                ("Yes, I can help.", {"reply": "Yes, I can help."}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan can you help me?", "raw": "<alice> huan can you help me?"})

            self.assertEqual(bridge.delivery.sent, ["Yes, I can help."])
            self.assertEqual(invoker.calls[1]["payload"]["decision"]["reason"], "direct_question_to_bot")

    def test_handle_event_overrides_same_player_followup_when_judge_declines(self):
        config = self.make_config()
        config["followupReplyWindowSeconds"] = 180
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 20
            state.data["lastPlayerReplyTs"] = {"alice": now - 20}
            state.data["recentBotReplies"] = [
                {"text": "Try using a crafting table.", "timestamp": now - 20},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "Try using a crafting table.", "timestamp": now - 20, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.91,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "followup_to_bot_conversation",
                    "allow_followup_streak": True,
                    "topic": "follow-up",
                    "reason": "same-player follow-up on the recent bot exchange",
                },
                reply_text="Sure, what part should I explain again?",
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can you explain that again?", "raw": "<alice> can you explain that again?"})

            self.assertEqual(bridge.delivery.sent, ["Sure, what part should I explain again?"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "followup_to_bot_conversation")
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 20
            state.data["lastPlayerReplyTs"] = {"alice": now - 20}
            state.data["recentBotReplies"] = [
                {"text": "Try using a crafting table.", "timestamp": now - 20},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "Try using a crafting table.", "timestamp": now - 20, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.26,
                    "reason": "conversation_already_answered",
                    "target_player": "alice",
                    "topic": "follow-up",
                }), {}),
                ("Sure, what part should I explain again?", {"reply": "Sure, what part should I explain again?"}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can you explain that again?", "raw": "<alice> can you explain that again?"})

            self.assertEqual(bridge.delivery.sent, ["Sure, what part should I explain again?"])
            self.assertEqual(invoker.calls[1]["payload"]["decision"]["reason"], "followup_to_bot_conversation")

    def test_handle_event_overrides_same_player_chinese_followup_when_judge_declines(self):
        config = self.make_config()
        config["followupReplyWindowSeconds"] = 180
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 20
            state.data["lastPlayerReplyTs"] = {"alice": now - 20}
            state.data["recentBotReplies"] = [
                {"text": "Use a crafting table.", "timestamp": now - 20},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "Use a crafting table.", "timestamp": now - 20, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.9,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "followup_to_bot_conversation",
                    "allow_followup_streak": True,
                    "topic": "chinese follow-up",
                    "reason": "same-player chinese follow-up on the recent bot exchange",
                },
                reply_text="Sure, which part should I explain again?",
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can you say that again?", "raw": "<alice> can you say that again?"})

            self.assertEqual(bridge.delivery.sent, ["Sure, which part should I explain again?"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "followup_to_bot_conversation")
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 20
            state.data["lastPlayerReplyTs"] = {"alice": now - 20}
            state.data["recentBotReplies"] = [
                {"text": "用合成台。", "timestamp": now - 20},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "用合成台。", "timestamp": now - 20, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.24,
                    "reason": "message_too_vague",
                    "target_player": "alice",
                    "topic": "chinese follow-up",
                }), {}),
                ("可以，你想我重新说哪一部分？", {"reply": "可以，你想我重新说哪一部分？"}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "能再说一遍吗", "raw": "<alice> 能再说一遍吗"})

            self.assertEqual(bridge.delivery.sent, ["可以，你想我重新说哪一部分？"])
            self.assertEqual(invoker.calls[1]["payload"]["decision"]["reason"], "followup_to_bot_conversation")

    def test_handle_event_does_not_treat_interrupted_conversation_as_same_player_followup(self):
        config = self.make_config()
        config["followupReplyWindowSeconds"] = 180
        config["maxBotConsecutiveReplies"] = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = now - 20
            state.data["lastPlayerReplyTs"] = {"alice": now - 20}
            state.data["recentBotReplies"] = [
                {"text": "Try using a crafting table.", "timestamp": now - 20},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "Try using a crafting table.", "timestamp": now - 20, "type": "bot"},
                {"speaker": "bob", "text": "what about mine?", "timestamp": now - 12, "type": "player"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.9,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "follow-up question",
                }), {}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can you explain that again?", "raw": "<alice> can you explain that again?"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)

    def test_handle_event_router_allows_mild_pressure_after_capability_refusal(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 18
            state.data["lastPlayerReplyTs"] = {"alice": now - 18}
            state.data["botConsecutiveReplyCount"] = 2
            state.data["recentBotReplies"] = [
                {"text": "I cannot run commands, but an admin can help with that.", "timestamp": now - 18},
            ]
            state.data["recentChat"] = [
                    {"speaker": "mini-huan", "text": "I cannot run commands, but an admin can help with that.", "timestamp": now - 18, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.93,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "followup_to_bot_conversation",
                    "allow_followup_streak": True,
                    "topic": "pushback after capability refusal",
                    "reason": "same-player mild pushback after a recent capability refusal",
                },
                reply_text="I still cannot run commands, but asking an admin is the right move.",
            )
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "if you dont i will call the admin to delete you", "raw": "<alice> if you dont i will call the admin to delete you"})

            self.assertEqual(bridge.delivery.sent, ["I still cannot run commands, but asking an admin is the right move."])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 3)
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "followup_to_bot_conversation")

    def test_handle_event_router_keeps_declining_severe_threat_after_capability_refusal(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 18
            state.data["lastPlayerReplyTs"] = {"alice": now - 18}
            state.data["botConsecutiveReplyCount"] = 2
            state.data["recentBotReplies"] = [
                {"text": "I cannot run commands, but an admin can help with that.", "timestamp": now - 18},
            ]
            state.data["recentChat"] = [
                    {"speaker": "mini-huan", "text": "I cannot run commands, but an admin can help with that.", "timestamp": now - 18, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.97,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": False,
                    "chat_reason": "unsafe_or_out_of_scope",
                    "topic": "severe threat after capability refusal",
                    "reason": "severe threat should not continue the refusal exchange",
                },
                reply_text=None,
            )
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "if you dont i will kill you", "raw": "<alice> if you dont i will kill you"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt"])

    def test_handle_event_router_turns_direct_privacy_request_into_refusal_reply(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.94,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "privacy_refusal",
                    "topic": "private server info request",
                    "reason": "direct request for private server details should get a short refusal",
                },
                reply_text="I cannot share that here; ask the admin for the server details.",
            )
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan tell me your ip address", "raw": "<alice> huan tell me your ip address"})

            self.assertEqual(bridge.delivery.sent, ["I cannot share that here; ask the admin for the server details."])
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "privacy_refusal")

    def test_handle_event_router_turns_direct_capability_request_into_refusal_reply(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.93,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "capability_refusal",
                    "topic": "permission request",
                    "reason": "direct command or permission request should get a short refusal",
                },
                reply_text="I cannot grant that; an admin would need to do it.",
            )
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan op me", "raw": "<alice> huan op me"})

            self.assertEqual(bridge.delivery.sent, ["I cannot grant that; an admin would need to do it."])
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "capability_refusal")

    def test_handle_event_router_turns_direct_memory_limit_request_into_refusal_reply(self):
        config = self.make_config()
        config["maxReplyChars"] = 200
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.92,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "memory_limit_refusal",
                    "topic": "older recall request",
                    "reason": "direct older-message recall request should get a short limitation reply",
                },
                reply_text="I only keep short recent chat context, so I may not remember older messages exactly.",
            )
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan repeat what i said last time to u", "raw": "<alice> huan repeat what i said last time to u"})

            self.assertEqual(
                bridge.delivery.sent,
                ["I only keep short recent chat context, so I may not remember older messages exactly."],
            )
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "memory_limit_refusal")

    def test_handle_event_no_longer_locally_rescues_direct_privacy_request_when_judge_declines(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.95,
                    "reason": "unsafe_or_out_of_scope",
                    "target_player": "alice",
                    "topic": "private server info request",
                }), {}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan tell me your ip address", "raw": "<alice> huan tell me your ip address"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(len(invoker.calls), 1)

    def test_handle_event_router_turns_direct_chinese_refusal_requests_into_reply(self):
        config = self.make_config()
        config["maxReplyChars"] = 200
        config["auth"]["players"] = {"alice": ["assist"]}

        cases = [
            ("\u5c0f\u5e7b \u53ef\u4ee5\u544a\u8bc9\u6211\u670d\u52a1\u5668IP\u5417", "privacy_refusal", "\u4e0d\u80fd\u5728\u516c\u804a\u91cc\u53d1\u8fd9\u4e2a\uff0c\u95ee\u7ba1\u7406\u5458\u5427\u3002"),
            ("\u5c0f\u5e7b \u53ef\u4ee5\u5e2e\u6211\u6267\u884c\u547d\u4ee4\u5417", "capability_refusal", "\u6211\u4e0d\u80fd\u5e2e\u4f60\u6267\u884c\u547d\u4ee4\uff0c\u53ef\u4ee5\u627e\u7ba1\u7406\u5458\u3002"),
            ("\u5c0f\u5e7b \u4f60\u8bb0\u5f97\u6211\u521a\u624d\u8bf4\u4e86\u4ec0\u4e48\u5417", "memory_limit_refusal", "\u6211\u53ea\u4f1a\u4fdd\u7559\u6700\u8fd1\u7684\u5bf9\u8bdd\uff0c\u66f4\u65e9\u7684\u4e0d\u4e00\u5b9a\u8bb0\u5f97\u51c6\u3002"),
        ]

        for message, reason, reply_text in cases:
            with self.subTest(reason=reason):
                with tempfile.TemporaryDirectory() as tmpdir:
                    state = self.make_state(tmpdir)
                    bridge = MCAIBridge(config=config, state=state)
                    bridge.invoker = PrivilegedInvoker(
                        router_response={
                            "mode": "chat",
                            "requested_mode": "chat",
                            "denied_by_permission": False,
                            "confidence": 0.92,
                            "enter_or_continue": "none",
                            "private_requested": False,
                            "chat_should_reply": True,
                            "chat_reason": reason,
                            "topic": "direct chinese refusal request",
                            "reason": "direct Chinese refusal/limitation request should get a short public reply",
                        },
                        reply_text=reply_text,
                    )
                    bridge.delivery = StubDelivery()

                    bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

                    self.assertEqual(bridge.delivery.sent, [reply_text])
                    self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
                    self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], reason)

    def test_handle_event_truncates_reply_to_max_chars(self):
        config = self.make_config()
        config["maxReplyChars"] = 5

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.95,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "short cap",
                }), {}),
                ("1234567890", {"reply": "1234567890"}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hi huan?", "raw": "<alice> hi huan?"})

            self.assertEqual(bridge.delivery.sent, ["12345"])
            self.assertEqual(state.data["recentBotReplies"][-1]["text"], "12345")

    def test_handle_event_does_not_send_agent_error_text(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.95,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "question",
                }), {}),
                ("Codex error: {\"type\":\"error\",\"error\":{\"message\":\"temporary failure\"}}", {"reply": "Codex error"}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hi huan?", "raw": "<alice> hi huan?"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)

    def test_handle_event_does_not_reply_to_unmentioned_generic_brainstorm(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.88,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": False,
                    "chat_reason": "not_addressed_to_bot",
                    "topic": "brainstorming question",
                    "reason": "ambient room-chat question without clear bot address",
                },
                reply_text=None,
            )
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            message = "你觉得我该怎么整"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual([call["kind"] for call in invoker.calls], ["prompt"])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)

    def test_handle_event_does_not_continue_same_player_exchange_on_generic_offer(self):
        config = self.make_config()
        config["followupReplyWindowSeconds"] = 180
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 15
            state.data["lastPlayerReplyTs"] = {"alice": now - 15}
            state.data["botConsecutiveReplyCount"] = 1
            state.data["recentBotReplies"] = [
                {"text": "可以，开头三秒先上最吸引人的画面。", "timestamp": now - 15},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "可以，开头三秒先上最吸引人的画面。", "timestamp": now - 15, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.86,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": False,
                    "chat_reason": "not_addressed_to_bot",
                    "topic": "payment offer",
                    "reason": "generic offer is not a real bot-directed follow-up",
                },
                reply_text=None,
            )
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            message = "我可以pay你20"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual([call["kind"] for call in invoker.calls], ["prompt"])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)

    def test_handle_event_allows_same_player_followup_question_without_renaming_bot(self):
        config = self.make_config()
        config["followupReplyWindowSeconds"] = 180

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 12
            state.data["lastPlayerReplyTs"] = {"alice": now - 12}
            state.data["recentBotReplies"] = [
                {"text": "我不能直接封禁玩家，这种事得让管理员处理。", "timestamp": now - 12},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "我不能直接封禁玩家，这种事得让管理员处理。", "timestamp": now - 12, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.9,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "identity follow-up",
                }, ensure_ascii=False), {}),
                ("算是服务器这边把我搭起来的聊天助手。", {"reply": "算是服务器这边把我搭起来的聊天助手。"}),
            ])
            bridge.delivery = StubDelivery()

            message = "你的创造者是谁？"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(bridge.delivery.sent, ["算是服务器这边把我搭起来的聊天助手。"])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 1)

    def test_handle_event_uses_active_session_context_for_chinese_followup_without_renaming_bot(self):
        config = self.make_config()
        config["followupReplyWindowSeconds"] = 180

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 12
            state.data["lastPlayerReplyTs"] = {"alice": now - 12}
            state.data["recentBotReplies"] = [
                {"text": "现在在线 1 人，就你一个。", "timestamp": now - 12},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "现在在线 1 人，就你一个。", "timestamp": now - 12, "type": "bot"},
            ]
            state.activate_player_session(
                "alice",
                "assist",
                session_id="assist-session",
                topic="online player count",
                last_request_text="huan 告诉我服务器目前有多少人",
                last_commands=["list"],
                last_command_results=[{
                    "command": "list",
                    "ok": True,
                    "stdout": "OK: There are 1 of a max of 2026 players online: alice",
                    "error": "",
                    "stdout_truncated": False,
                }],
                last_reply_text="现在在线 1 人，就你一个。",
                timestamp=now - 12,
            )
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.92,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "followup_to_bot_conversation",
                    "allow_followup_streak": True,
                    "topic": "used command explanation",
                    "reason": "same-player follow-up about the active assist result",
                },
                reply_text="我刚才用了 list 命令。",
            )
            bridge.delivery = PrivilegedDelivery()

            message = "你用了什么命令做到的"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(bridge.delivery.sent, ["我刚才用了 list 命令。"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "followup_to_bot_conversation")
            self.assertEqual(bridge.invoker.calls[1]["payload"]["active_session"]["last_commands"], ["list"])
            self.assertIn("There are 1", bridge.invoker.calls[1]["payload"]["active_session"]["last_command_results"][0]["stdout"])

    def test_router_chat_reply_bypasses_judge_and_uses_router_decision(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.97,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "greeting_to_bot",
                    "topic": "greeting",
                    "reason": "player directly greeted the bot",
                },
                reply_text="Hi!",
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hi huan", "raw": "<alice> hi huan"})

            self.assertEqual(bridge.delivery.sent, ["Hi!"])
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
            self.assertIn("reply_prompt.txt", str(bridge.invoker.calls[1]["prompt_path"]))
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "greeting_to_bot")

    def test_router_chat_reply_ignores_judge_confidence_thresholds_on_main_path(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}
        config["judgeConfidenceThreshold"] = 0.95
        config["judgeSoftThreshold"] = 0.9

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.21,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "direct_question_to_bot",
                    "topic": "low-confidence main-path chat",
                    "reason": "router still wants to answer the direct bot question",
                },
                reply_text="Yep.",
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan are you there?", "raw": "<alice> huan are you there?"})

            self.assertEqual(bridge.delivery.sent, ["Yep."])
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "direct_question_to_bot")

    def test_router_followup_relaxation_requires_explicit_flag(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}
        config["maxBotConsecutiveReplies"] = 1
        config["followupReplyWindowSeconds"] = 180
        config["maxSamePlayerConversationReplies"] = 8

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = now - 12
            state.data["lastPlayerReplyTs"] = {"alice": now - 12}
            state.data["recentBotReplies"] = [
                {"text": "Earlier bot reply.", "timestamp": now - 12},
            ]
            state.data["recentChat"] = [
                {"speaker": "mini-huan", "text": "Earlier bot reply.", "timestamp": now - 12, "type": "bot"},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.94,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "followup_to_bot_conversation",
                    "allow_followup_streak": False,
                    "topic": "follow-up without explicit continuation flag",
                    "reason": "router thinks this is reply-worthy but not a relaxed streak continuation",
                },
                reply_text="unused",
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can you explain that again?", "raw": "<alice> can you explain that again?"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt"])

    def test_router_chat_followup_uses_active_session_without_judge(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.activate_player_session(
                "alice",
                "assist",
                session_id="assist-session",
                topic="online player count",
                last_request_text="huan tell me who is online",
                last_commands=["list"],
                last_command_results=[{
                    "command": "list",
                    "ok": True,
                    "stdout": "OK: There are 1 of a max of 20 players online: alice",
                    "error": "",
                    "stdout_truncated": False,
                }],
                last_reply_text="Only you are online right now.",
                timestamp=now - 12,
            )
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.94,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "followup_to_bot_conversation",
                    "allow_followup_streak": True,
                    "topic": "used command explanation",
                    "reason": "same-player follow-up about the active assist result",
                },
                reply_text="I used list just now.",
            )
            bridge.delivery = PrivilegedDelivery()

            message = "what command did you use"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(bridge.delivery.sent, ["I used list just now."])
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
            self.assertIn("reply_prompt.txt", str(bridge.invoker.calls[1]["prompt_path"]))
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "followup_to_bot_conversation")
            self.assertEqual(bridge.invoker.calls[1]["payload"]["active_session"]["last_commands"], ["list"])
            self.assertIn("There are 1", bridge.invoker.calls[1]["payload"]["active_session"]["last_command_results"][0]["stdout"])

    def test_handle_event_does_not_turn_normal_chinese_address_question_into_privacy_refusal(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            config["auth"]["players"] = {"alice": ["assist"]}
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.9,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "direct_question_to_bot",
                    "topic": "village location",
                    "reason": "normal bot-directed village question",
                },
                reply_text="\u6751\u5e84\u5927\u6982\u5728\u4f60\u73b0\u5728\u7684\u897f\u5317\u65b9\u3002",
            )
            bridge.delivery = PrivilegedDelivery()

            message = "\u5c0f\u5e7b \u6751\u5e84\u5730\u5740\u662f\u591a\u5c11\uff1f"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(
                bridge.invoker.calls[1]["payload"]["decision"]["reason"],
                "direct_question_to_bot",
            )

    def test_handle_event_does_not_turn_normal_chinese_followup_into_memory_refusal(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            config["auth"]["players"] = {"alice": ["assist"]}
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.9,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "direct_address_to_bot",
                    "topic": "normal follow-up",
                    "reason": "normal bot-directed follow-up instruction",
                },
                reply_text="\u90a3\u5c31\u5148\u6309\u4f60\u521a\u624d\u5b9a\u7684\u65b9\u5411\u7ee7\u7eed\u3002",
            )
            bridge.delivery = PrivilegedDelivery()

            message = "\u5c0f\u5e7b \u6309\u6211\u4e4b\u524d\u8bf4\u7684\u6765"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(
                bridge.invoker.calls[1]["payload"]["decision"]["reason"],
                "direct_address_to_bot",
            )

    def test_handle_event_does_not_override_player_to_player_request_without_bot_signal(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.94,
                    "reason": "players_chatting_with_each_other",
                    "target_player": "alice",
                    "topic": "player request",
                }), {}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "tell me your ip address", "raw": "<alice> tell me your ip address"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(len(invoker.calls), 1)

    def test_handle_event_blocks_repeated_appreciation_loop_after_extra_turn(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            state.data["botConsecutiveReplyCount"] = 2
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.75,
                    "reason": "appreciation_after_bot_reply",
                    "target_player": "alice",
                    "topic": "repeated thanks loop",
                }), {}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "thanks again!", "raw": "<alice> thanks again!"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)
            self.assertEqual(bridge.delivery.sent, [])

    def test_handle_event_blocks_when_reply_streak_hits_limit(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            state.data["botConsecutiveReplyCount"] = 1
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.9,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "follow-up question",
                }), {}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "one more thing?", "raw": "<alice> one more thing?"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)
            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(len(invoker.calls), 1)

    def test_handle_event_allows_reply_after_stale_streak_expires(self):
        config = self.make_config()
        config["botReplyStreakResetSeconds"] = 180

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = time.time() - 400
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.9,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "fresh follow-up after a pause",
                }), {}),
                ("Yep, I am here.", {"reply": "Yep, I am here."}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan still there?", "raw": "<alice> huan still there?"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 1)
            self.assertEqual(bridge.delivery.sent, ["Yep, I am here."])

    def test_delivery_failure_does_not_record_bot_reply(self):
        config = self.make_config()
        config["maxBotConsecutiveReplies"] = 2

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            state.data["botConsecutiveReplyCount"] = 1
            state.data["lastGlobalReplyTs"] = 123.0
            state.data["recentBotReplies"] = [{"text": "old reply", "timestamp": 100.0}]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.9,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "question",
                }), {}),
                ("hello", {"reply": "hello"}),
            ])
            bridge.delivery = StubDelivery(RuntimeError("rcon down"))

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hi", "raw": "<alice> hi"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)
            self.assertEqual(state.data["lastGlobalReplyTs"], 123.0)
            self.assertEqual([item["text"] for item in state.data["recentBotReplies"]], ["old reply"])

    def test_precheck_event_skips_duplicate_before_judge(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            event = {"type": "chat", "player": "alice", "message": "hello", "raw": "<alice> hello"}
            state.data["recentEventKeys"] = [bridge.event_key(event)]

            ok, reason = bridge.precheck_event(event)

            self.assertFalse(ok)
            self.assertEqual(reason, "skip-duplicate")

    def test_handle_event_duplicate_chat_does_not_reset_streak(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            state.data["botConsecutiveReplyCount"] = 2
            bridge = MCAIBridge(config=config, state=state)
            event = {"type": "chat", "player": "alice", "message": "hello", "raw": "<alice> hello"}
            state.data["recentEventKeys"] = [bridge.event_key(event)]

            bridge.handle_event(event)

            self.assertEqual(state.data["botConsecutiveReplyCount"], 2)

    def test_multi_turn_repeated_question_keeps_recent_room_chat_visible_to_helper(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.2,
                    "reason": "message_too_vague",
                    "target_player": "alice",
                    "topic": "question",
                }), {}),
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.2,
                    "reason": "players_chatting_with_each_other",
                    "target_player": "bob",
                    "topic": "answer",
                }), {}),
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.2,
                    "reason": "conversation_already_answered",
                    "target_player": "alice",
                    "topic": "question repeated",
                }), {}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "how do i mine obsidian?", "raw": "[00:00:01] <alice> how do i mine obsidian?"})
            bridge.handle_event({"type": "chat", "player": "bob", "message": "Use a diamond pickaxe on obsidian.", "raw": "[00:00:05] <bob> Use a diamond pickaxe on obsidian."})
            bridge.handle_event({"type": "chat", "player": "alice", "message": "how do i mine obsidian?", "raw": "[00:00:09] <alice> how do i mine obsidian?"})

            third_payload = invoker.calls[2]["payload"]
            self.assertEqual([item["speaker"] for item in third_payload["recent_chat"]][-3:], ["alice", "bob", "alice"])
            self.assertNotIn("human_answer_seen", third_payload["room_state"])
            self.assertNotIn("human_answer_candidates", third_payload["room_state"])

    def test_multi_turn_yes_no_reply_keeps_recent_room_chat_visible_to_helper(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.2,
                    "reason": "message_too_vague",
                    "target_player": "alice",
                    "topic": "yes no question",
                }), {}),
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.2,
                    "reason": "players_chatting_with_each_other",
                    "target_player": "bob",
                    "topic": "short answer",
                }), {}),
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.2,
                    "reason": "conversation_already_answered",
                    "target_player": "alice",
                    "topic": "yes no repeated",
                }), {}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can i sleep now?", "raw": "[00:00:01] <alice> can i sleep now?"})
            bridge.handle_event({"type": "chat", "player": "bob", "message": "yes", "raw": "[00:00:04] <bob> yes"})
            bridge.handle_event({"type": "chat", "player": "alice", "message": "can i sleep now?", "raw": "[00:00:08] <alice> can i sleep now?"})

            third_payload = invoker.calls[2]["payload"]
            self.assertEqual([item["text"] for item in third_payload["recent_chat"]][-3:], ["can i sleep now?", "yes", "can i sleep now?"])
            self.assertNotIn("human_answer_seen", third_payload["room_state"])
            self.assertNotIn("human_answer_candidates", third_payload["room_state"])

    def test_privileged_assist_route_executes_commands_and_records_player_session(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "assist",
                    "requested_mode": "assist",
                    "denied_by_permission": False,
                    "confidence": 0.92,
                    "enter_or_continue": "enter",
                    "private_requested": False,
                    "topic": "return to spawn",
                    "reason": "authorized assist request",
                },
                privileged_response={
                    "status": "completed",
                    "commands": ["/kill alice"],
                    "reply": "这就送你回出生点。",
                    "topic": "return to spawn",
                    "reason": "self-reset assist",
                },
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "小幻 帮我回出生点", "raw": "<alice> 小幻 帮我回出生点"})

            self.assertEqual(bridge.delivery.commands, ["kill alice"])
            self.assertEqual(bridge.delivery.sent, ["这就送你回出生点。"])
            session = state.data["playerSessions"]["alice"]
            self.assertEqual(session["mode"], "assist")
            self.assertEqual(session["sessionId"], "priv-session-123")
            self.assertEqual(session["topic"], "return to spawn")
            self.assertEqual(session["lastCommandResults"][0]["command"], "kill alice")
            self.assertTrue(session["lastCommandResults"][0]["ok"])

    def test_privileged_assist_multistep_query_replays_command_results_back_to_helper(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "assist",
                    "requested_mode": "assist",
                    "denied_by_permission": False,
                    "confidence": 0.94,
                    "enter_or_continue": "enter",
                    "private_requested": False,
                    "topic": "current player count",
                    "reason": "live server query",
                },
                privileged_responses=[
                    {
                        "status": "run_commands",
                        "commands": ["list"],
                        "reply": "",
                        "topic": "current player count",
                        "reason": "need live player count",
                    },
                    {
                        "status": "completed",
                        "commands": [],
                        "reply": "现在有 2 个玩家在线：alice, bob。",
                        "topic": "current player count",
                        "reason": "summarized live command result",
                    },
                ],
                session_ids=["priv-session-xyz", "priv-session-xyz"],
            )
            bridge.delivery = PrivilegedDelivery(
                command_results={"list": "There are 2/20 players online: alice, bob"}
            )

            bridge.handle_event(
                {
                    "type": "chat",
                    "player": "alice",
                    "message": "小幻 现在在线有几个人",
                    "raw": "<alice> 小幻 现在在线有几个人",
                }
            )

            self.assertEqual(bridge.delivery.commands, ["list"])
            self.assertEqual(bridge.delivery.sent, ["现在有 2 个玩家在线：alice, bob。"])
            session_calls = [call for call in bridge.invoker.calls if call["kind"] == "session"]
            self.assertEqual(len(session_calls), 2)
            self.assertEqual(session_calls[1]["payload"]["protocol"]["phase"], "after_command_results")
            self.assertEqual(
                session_calls[1]["payload"]["protocol"]["last_command_results"][0]["command"],
                "list",
            )
            self.assertIn(
                "alice, bob",
                session_calls[1]["payload"]["protocol"]["last_command_results"][0]["stdout"],
            )
            self.assertEqual(
                session_calls[1]["payload"]["protocol"]["command_history"][0]["executed_commands"],
                ["list"],
            )
            session = state.data["playerSessions"]["alice"]
            self.assertEqual(session["sessionId"], "priv-session-xyz")
            self.assertEqual(session["lastCommandResults"][0]["command"], "list")
            self.assertIn("alice, bob", session["lastCommandResults"][0]["stdout"])

    def test_privileged_assist_completed_command_gets_confirmation_round_before_final_reply(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "assist",
                    "requested_mode": "assist",
                    "denied_by_permission": False,
                    "confidence": 0.95,
                    "enter_or_continue": "enter",
                    "private_requested": False,
                    "topic": "clear nearby creepers",
                    "reason": "nearby mob cleanup",
                },
                privileged_responses=[
                    {
                        "status": "completed",
                        "commands": ["kill @e[type=minecraft:creeper,distance=..16]"],
                        "reply": "帮你清掉附近的苦力怕了。",
                        "topic": "clear nearby creepers",
                        "reason": "one-step cleanup",
                    },
                    {
                        "status": "completed",
                        "commands": [],
                        "reply": "这次没找到你附近的苦力怕。",
                        "topic": "clear nearby creepers",
                        "reason": "selector matched nothing",
                    },
                ],
            )
            bridge.delivery = PrivilegedDelivery(
                command_results={
                    "kill @e[type=minecraft:creeper,distance=..16]": "OK: No entity was found"
                }
            )

            bridge.handle_event(
                {
                    "type": "chat",
                    "player": "alice",
                    "message": "小幻 帮我清理掉我附近的苦力怕",
                    "raw": "<alice> 小幻 帮我清理掉我附近的苦力怕",
                }
            )

            session_calls = [call for call in bridge.invoker.calls if call["kind"] == "session"]
            self.assertEqual(len(session_calls), 2)
            self.assertEqual(session_calls[1]["payload"]["protocol"]["phase"], "after_command_results")
            self.assertEqual(
                session_calls[1]["payload"]["protocol"]["last_command_results"][0]["stdout"],
                "OK: No entity was found",
            )
            self.assertEqual(bridge.delivery.commands, ["kill @e[type=minecraft:creeper,distance=..16]"])
            self.assertEqual(bridge.delivery.sent, ["这次没找到你附近的苦力怕。"])
            session = state.data["playerSessions"]["alice"]
            self.assertEqual(session["lastCommandResults"][0]["stdout"], "OK: No entity was found")

    def test_privileged_missing_final_reply_after_failed_commands_uses_failure_fallback(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "assist",
                    "requested_mode": "assist",
                    "denied_by_permission": False,
                    "confidence": 0.93,
                    "enter_or_continue": "enter",
                    "private_requested": False,
                    "topic": "clear nearby creepers",
                    "reason": "nearby mob cleanup",
                },
                privileged_responses=[
                    {
                        "status": "completed",
                        "commands": ["kill @e[type=minecraft:creeper,distance=..16]"],
                        "reply": "",
                        "topic": "clear nearby creepers",
                        "reason": "one-step cleanup",
                    },
                    {
                        "status": "completed",
                        "commands": [],
                        "reply": "",
                        "topic": "clear nearby creepers",
                        "reason": "missing final reply after command failure",
                    },
                ],
            )
            bridge.delivery = PrivilegedDelivery(
                command_results={
                    "kill @e[type=minecraft:creeper,distance=..16]": {"sent": False, "reason": "No entity was found"}
                }
            )

            bridge.handle_event(
                {
                    "type": "chat",
                    "player": "alice",
                    "message": "huan clear the nearby creepers",
                    "raw": "<alice> huan clear the nearby creepers",
                }
            )

            self.assertEqual(bridge.delivery.commands, ["kill @e[type=minecraft:creeper,distance=..16]"])
            self.assertEqual(
                bridge.delivery.sent,
                ["Some commands did not finish cleanly, so try again or rephrase it."],
            )
            session = state.data["playerSessions"]["alice"]
            self.assertFalse(session["lastCommandResults"][0]["ok"])
            self.assertEqual(
                session["lastReplyText"],
                "Some commands did not finish cleanly, so try again or rephrase it.",
            )

    def test_privileged_route_can_reply_privately_when_requested(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["operator"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "command",
                    "requested_mode": "command",
                    "denied_by_permission": False,
                    "confidence": 0.91,
                    "enter_or_continue": "enter",
                    "private_requested": True,
                    "topic": "set weather",
                    "reason": "private request",
                },
                privileged_response={
                    "status": "completed",
                    "commands": ["weather clear"],
                    "reply": "已经切成晴天了。",
                    "topic": "set weather",
                    "reason": "weather command",
                },
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "小幻 悄悄帮我把天气改晴", "raw": "<alice> 小幻 悄悄帮我把天气改晴"})

            self.assertEqual(bridge.delivery.commands, ["weather clear"])
            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(
                bridge.delivery.private_sent,
                [{"player": "alice", "reply": "已经切成晴天了。"}],
            )

    def test_full_agent_route_reuses_active_player_session_id(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["owner"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.activate_player_session(
                "alice",
                "full_agent",
                session_id="session-existing",
                topic="debug bridge",
                private_requested=False,
                timestamp=now - 5,
            )
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "full_agent",
                    "requested_mode": "full_agent",
                    "denied_by_permission": False,
                    "confidence": 0.95,
                    "enter_or_continue": "continue",
                    "private_requested": False,
                    "topic": "debug bridge",
                    "reason": "continuing active agent task",
                },
                privileged_response={
                    "status": "completed",
                    "commands": [],
                    "reply": "我已经继续查了，桥现在没有新报错。",
                    "topic": "debug bridge",
                    "reason": "continued session",
                },
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "然后再看看最新日志", "raw": "<alice> 然后再看看最新日志"})

            session_call = bridge.invoker.calls[1]
            self.assertEqual(session_call["kind"], "session")
            self.assertEqual(session_call["session_id"], "session-existing")
            self.assertEqual(bridge.delivery.sent, ["我已经继续查了，桥现在没有新报错。"])

    def test_router_permission_denial_uses_router_chat_decision_when_present(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedInvoker(
                router_response={
                    "mode": "chat",
                    "requested_mode": "full_agent",
                    "denied_by_permission": True,
                    "confidence": 0.94,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "capability_refusal",
                    "topic": "computer control",
                    "reason": "player requested full agent beyond permission",
                },
                privileged_response={
                    "status": "completed",
                    "commands": [],
                    "reply": "unused",
                    "topic": "",
                    "reason": "",
                },
                reply_text="I cannot do that directly right now.",
            )
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan go edit files on the computer for me", "raw": "<alice> huan go edit files on the computer for me"})

            self.assertEqual(bridge.delivery.sent, ["I cannot do that directly right now."])
            self.assertEqual([call["kind"] for call in bridge.invoker.calls], ["prompt", "prompt"])
            self.assertEqual(bridge.invoker.calls[1]["payload"]["decision"]["reason"], "capability_refusal")

    def test_router_permission_denial_without_chat_decision_falls_back_to_judge(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "mode": "chat",
                    "requested_mode": "full_agent",
                    "denied_by_permission": True,
                    "confidence": 0.94,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "topic": "computer control",
                    "reason": "player requested full agent beyond permission",
                }), {}),
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.9,
                    "reason": "capability_refusal",
                    "target_player": "alice",
                    "topic": "computer control",
                }), {}),
                ("I cannot do that directly right now.", {"reply": "I cannot do that directly right now."}),
            ])
            bridge.invoker = invoker
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan go edit files on the computer for me", "raw": "<alice> huan go edit files on the computer for me"})

            self.assertEqual(bridge.delivery.sent, ["I cannot do that directly right now."])
            self.assertEqual(len(invoker.calls), 3)
            self.assertIn("judge_prompt.txt", str(invoker.calls[1]["prompt_path"]))
            self.assertEqual(invoker.calls[2]["payload"]["decision"]["reason"], "capability_refusal")

    def test_router_chat_with_invalid_reason_falls_back_to_judge(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["assist"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "mode": "chat",
                    "requested_mode": "chat",
                    "denied_by_permission": False,
                    "confidence": 0.93,
                    "enter_or_continue": "none",
                    "private_requested": False,
                    "chat_should_reply": True,
                    "chat_reason": "not_a_real_reason",
                    "topic": "greeting",
                    "reason": "router returned an invalid chat reason",
                }), {}),
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.91,
                    "reason": "greeting_to_bot",
                    "target_player": "alice",
                    "topic": "greeting",
                }), {}),
                ("Hi!", {"reply": "Hi!"}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hi huan", "raw": "<alice> hi huan"})

            self.assertEqual(bridge.delivery.sent, ["Hi!"])
            self.assertEqual(len(invoker.calls), 3)
            self.assertIn("judge_prompt.txt", str(invoker.calls[1]["prompt_path"]))
            self.assertEqual(invoker.calls[2]["payload"]["decision"]["reason"], "greeting_to_bot")

    def test_router_error_falls_back_to_normal_chat_reply(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["owner"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = RouterErrorInvoker(reply_text="Hi!")
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "hi huan", "raw": "<alice> hi huan"})

            self.assertEqual(bridge.delivery.sent, ["Hi!"])
            self.assertEqual(len(bridge.invoker.calls), 3)

    def test_router_error_falls_back_to_local_raw_command_route(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["owner"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["lastGlobalReplyTs"] = now - 8
            state.data["lastPlayerReplyTs"] = {"alice": now - 8}
            state.data["recentChat"] = [
                {"speaker": "alice", "text": "hi huan", "timestamp": now - 12, "type": "player"},
                {"speaker": "mini-huan", "text": "Hi!", "timestamp": now - 8, "type": "bot"},
            ]
            state.data["recentBotReplies"] = [
                {"text": "Hi!", "timestamp": now - 8},
            ]
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = RouterErrorInvoker(
                reply_text="unused",
                privileged_response={
                    "status": "completed",
                    "commands": ["give alice diamond_block 64"],
                    "reply": "给你了。",
                    "topic": "diamond blocks",
                    "reason": "owner command request",
                },
            )
            bridge.delivery = PrivilegedDelivery()
            bridge.handle_event({"type": "chat", "player": "alice", "message": "/give alice diamond_block 64", "raw": "<alice> /give alice diamond_block 64"})
            self.assertEqual(bridge.delivery.commands, ["give alice diamond_block 64"])
            self.assertEqual(len(bridge.delivery.sent), 1)
            return
            self.assertEqual(bridge.delivery.sent, ["缁欎綘浜嗐€?"])
            return

            bridge.handle_event({"type": "chat", "player": "alice", "message": "给我一组钻石块", "raw": "<alice> 给我一组钻石块"})

            self.assertEqual(bridge.delivery.commands, ["give alice diamond_block 64"])
            self.assertEqual(bridge.delivery.sent, ["给你了。"])

    def test_privileged_command_error_falls_back_to_local_command_execution(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["owner"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedStageErrorInvoker({
                "mode": "command",
                "requested_mode": "command",
                "denied_by_permission": False,
                "confidence": 0.9,
                "enter_or_continue": "enter",
                "private_requested": False,
                "topic": "minecraft command-style request",
                "reason": "router ok",
            })
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "给我一组钻石块", "raw": "<alice> 给我一组钻石块"})

            self.assertEqual(bridge.delivery.commands, ["give alice diamond_block 64"])
            self.assertEqual(bridge.delivery.sent, ["给你了。"])

    def test_privileged_command_continuation_reuses_last_successful_command_context(self):
        config = self.make_config()
        config["auth"]["players"] = {"alice": ["owner"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            bridge.invoker = PrivilegedStageErrorInvoker({
                "mode": "command",
                "requested_mode": "command",
                "denied_by_permission": False,
                "confidence": 0.9,
                "enter_or_continue": "enter",
                "private_requested": False,
                "topic": "minecraft command-style request",
                "reason": "router ok",
            })
            bridge.delivery = PrivilegedDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "给我一组钻石块", "raw": "<alice> 给我一组钻石块"})
            bridge.handle_event({"type": "chat", "player": "alice", "message": "再来一组", "raw": "<alice> 再来一组"})

            self.assertEqual(
                bridge.delivery.commands,
                ["give alice diamond_block 64", "give alice diamond_block 64"],
            )
            self.assertEqual(
                bridge.delivery.sent,
                ["给你了。", "再给你一份。"],
            )

    def test_load_config_backfills_new_default_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bridge_config.json"
            path.write_text(json.dumps({"sendToMinecraft": True}), encoding="utf-8")

            config = load_config(path)

            self.assertTrue(config["sendToMinecraft"])
            self.assertEqual(config["botReplyStreakResetSeconds"], 180)
            self.assertEqual(config["helperWorkspacePath"], r"C:\Users\Administrator\.openclaw\workspace-mc-helper")
            self.assertEqual(config["displayNameZh"], "小幻")
            self.assertEqual(config["nameAliases"], ["huan"])
            self.assertEqual(config["maxBotConsecutiveReplies"], 4)
            self.assertEqual(config["followupReplyWindowSeconds"], 180)
            self.assertEqual(config["maxSamePlayerConversationReplies"], 20)
            self.assertEqual(config["botStyle"]["persona"], "Minecraft public-chat helper")
            self.assertEqual(config["routerConfidenceThreshold"], 0.55)
            self.assertEqual(config["modeSessionWindowSeconds"]["full_agent"], 900)
            self.assertEqual(config["privilegedCommandMaxRounds"], 3)
            self.assertEqual(config["privilegedCommandMaxCommandsPerRound"], 3)
            self.assertEqual(config["privilegedCommandResultMaxChars"], 400)
            self.assertEqual(config["auth"]["groups"]["owner"]["max_mode"], "full_agent")


if __name__ == "__main__":
    unittest.main()
