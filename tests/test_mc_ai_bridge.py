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


class StubInvoker:
    def __init__(self, responses):
        self.responses = list(responses)

    def call_prompt(self, payload, prompt_path):
        if not self.responses:
            raise AssertionError("No stub responses left for call_prompt")
        return self.responses.pop(0)


class CapturingInvoker(StubInvoker):
    def __init__(self, responses):
        super().__init__(responses)
        self.calls = []

    def call_prompt(self, payload, prompt_path):
        self.calls.append({"payload": payload, "prompt_path": prompt_path})
        return super().call_prompt(payload, prompt_path)


class StubDelivery:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    def send_reply(self, reply: str):
        if self.error is not None:
            raise self.error
        self.sent.append(reply)
        return {"sent": True, "stdout": "ok"}


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

    def test_detect_human_answer_seen_handles_chinese_overlap(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["recentChat"] = [
                {"speaker": "bob", "text": "你可以用钻石镐挖黑曜石。", "timestamp": now - 5, "type": "player"},
            ]

            builder = ContextBuilder(config, state, Logger(config))
            self.assertTrue(builder.detect_human_answer_seen("alice", "黑曜石怎么挖？"))

    def test_detect_human_answer_seen_handles_short_natural_chinese_answer(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["recentChat"] = [
                {"speaker": "alice", "text": "黑曜石怎么挖？", "timestamp": now - 8, "type": "player"},
                {"speaker": "bob", "text": "用钻石镐挖。", "timestamp": now - 4, "type": "player"},
            ]

            builder = ContextBuilder(config, state, Logger(config))
            self.assertTrue(builder.detect_human_answer_seen("alice", "黑曜石怎么挖？"))

    def test_detect_human_answer_seen_handles_short_yes_no_answer(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["recentChat"] = [
                {"speaker": "bob", "text": "yes", "timestamp": now - 4, "type": "player"},
            ]

            builder = ContextBuilder(config, state, Logger(config))
            self.assertTrue(builder.detect_human_answer_seen("alice", "can i sleep now?"))

    def test_human_answer_candidates_capture_recent_player_answer(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            now = time.time()
            state.data["recentChat"] = [
                {"speaker": "alice", "text": "how do i mine obsidian?", "timestamp": now - 8, "type": "player"},
                {"speaker": "bob", "text": "Use a diamond pickaxe on obsidian.", "timestamp": now - 4, "type": "player"},
            ]

            builder = ContextBuilder(config, state, Logger(config))
            candidates = builder.human_answer_candidates("alice", "how do i mine obsidian?")

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["speaker"], "bob")
            self.assertIn("diamond pickaxe", candidates[0]["text"])

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
                }), {}),
                ("I can only answer in chat.", {"reply": "I can only answer in chat."}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "can you execute commands for me?", "raw": "<alice> can you execute commands for me?"})

            self.assertEqual(state.data["botConsecutiveReplyCount"], 2)
            self.assertEqual(bridge.delivery.sent, ["I can only answer in chat."])

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
                        }), {}),
                        (reply_text, {"reply": reply_text}),
                    ])
                    bridge.delivery = StubDelivery()

                    bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

                    self.assertEqual(state.data["botConsecutiveReplyCount"], 3)
                    self.assertEqual(bridge.delivery.sent, [reply_text])

    def test_handle_event_overrides_direct_named_question_when_judge_declines(self):
        config = self.make_config()

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

    def test_handle_event_allows_mild_pressure_after_capability_refusal(self):
        config = self.make_config()

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
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.96,
                    "reason": "unsafe_or_out_of_scope",
                    "target_player": "alice",
                    "topic": "threat after command refusal",
                }), {}),
                ("I still cannot run commands, but asking an admin is the right move.", {"reply": "I still cannot run commands, but asking an admin is the right move."}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "if you dont i will call the admin to delete you", "raw": "<alice> if you dont i will call the admin to delete you"})

            self.assertEqual(bridge.delivery.sent, ["I still cannot run commands, but asking an admin is the right move."])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 3)

    def test_handle_event_keeps_declining_severe_threat_after_capability_refusal(self):
        config = self.make_config()

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
            bridge.invoker = StubInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.96,
                    "reason": "unsafe_or_out_of_scope",
                    "target_player": "alice",
                    "topic": "severe threat after command refusal",
                }), {}),
            ])
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "if you dont i will kill you", "raw": "<alice> if you dont i will kill you"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)

    def test_handle_event_turns_direct_privacy_request_into_refusal_reply(self):
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
                ("I cannot share that here; ask the admin for the server details.", {"reply": "I cannot share that here; ask the admin for the server details."}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan tell me your ip address", "raw": "<alice> huan tell me your ip address"})

            self.assertEqual(bridge.delivery.sent, ["I cannot share that here; ask the admin for the server details."])
            self.assertEqual(invoker.calls[1]["payload"]["decision"]["reason"], "privacy_refusal")

    def test_handle_event_turns_direct_capability_request_into_refusal_reply(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.91,
                    "reason": "unsafe_or_out_of_scope",
                    "target_player": "alice",
                    "topic": "permission request",
                }), {}),
                ("I cannot grant that; an admin would need to do it.", {"reply": "I cannot grant that; an admin would need to do it."}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan op me", "raw": "<alice> huan op me"})

            self.assertEqual(bridge.delivery.sent, ["I cannot grant that; an admin would need to do it."])
            self.assertEqual(invoker.calls[1]["payload"]["decision"]["reason"], "capability_refusal")

    def test_handle_event_turns_direct_memory_limit_request_into_refusal_reply(self):
        config = self.make_config()
        config["maxReplyChars"] = 200

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.89,
                    "reason": "message_too_vague",
                    "target_player": "alice",
                    "topic": "older recall request",
                }), {}),
                ("I only keep short recent chat context, so I may not remember older messages exactly.", {"reply": "I only keep short recent chat context, so I may not remember older messages exactly."}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            bridge.handle_event({"type": "chat", "player": "alice", "message": "huan repeat what i said last time to u", "raw": "<alice> huan repeat what i said last time to u"})

            self.assertEqual(
                bridge.delivery.sent,
                ["I only keep short recent chat context, so I may not remember older messages exactly."],
            )
            self.assertEqual(invoker.calls[1]["payload"]["decision"]["reason"], "memory_limit_refusal")

    def test_handle_event_turns_direct_chinese_refusal_requests_into_reply(self):
        config = self.make_config()
        config["maxReplyChars"] = 200

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
                    invoker = CapturingInvoker([
                        (json.dumps({
                            "should_reply": False,
                            "confidence": 0.9,
                            "reason": "unsafe_or_out_of_scope",
                            "target_player": "alice",
                            "topic": "declined",
                        }, ensure_ascii=False), {}),
                        (reply_text, {"reply": reply_text}),
                    ])
                    bridge.invoker = invoker
                    bridge.delivery = StubDelivery()

                    bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

                    self.assertEqual(bridge.delivery.sent, [reply_text])
                    self.assertEqual(invoker.calls[1]["payload"]["decision"]["reason"], reason)

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

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.88,
                    "reason": "direct_question_to_bot",
                    "target_player": "alice",
                    "topic": "brainstorming question",
                }, ensure_ascii=False), {}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            message = "你觉得我该怎么整"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(len(invoker.calls), 1)
            self.assertEqual(state.data["botConsecutiveReplyCount"], 0)

    def test_handle_event_does_not_continue_same_player_exchange_on_generic_offer(self):
        config = self.make_config()
        config["followupReplyWindowSeconds"] = 180

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
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": True,
                    "confidence": 0.86,
                    "reason": "followup_to_bot_conversation",
                    "target_player": "alice",
                    "topic": "payment offer",
                }, ensure_ascii=False), {}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            message = "我可以pay你20"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(bridge.delivery.sent, [])
            self.assertEqual(len(invoker.calls), 1)
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

    def test_handle_event_does_not_turn_normal_chinese_address_question_into_privacy_refusal(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.9,
                    "reason": "players_chatting_with_each_other",
                    "target_player": "alice",
                    "topic": "village location",
                }, ensure_ascii=False), {}),
                ("\u6751\u5e84\u5927\u6982\u5728\u4f60\u73b0\u5728\u7684\u897f\u5317\u65b9\u3002", {"reply": "\u6751\u5e84\u5927\u6982\u5728\u4f60\u73b0\u5728\u7684\u897f\u5317\u65b9\u3002"}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            message = "\u5c0f\u5e7b \u6751\u5e84\u5730\u5740\u662f\u591a\u5c11\uff1f"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(
                invoker.calls[1]["payload"]["decision"]["reason"],
                "direct_question_to_bot",
            )

    def test_handle_event_does_not_turn_normal_chinese_followup_into_memory_refusal(self):
        config = self.make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self.make_state(tmpdir)
            bridge = MCAIBridge(config=config, state=state)
            invoker = CapturingInvoker([
                (json.dumps({
                    "should_reply": False,
                    "confidence": 0.9,
                    "reason": "players_chatting_with_each_other",
                    "target_player": "alice",
                    "topic": "normal follow-up",
                }, ensure_ascii=False), {}),
                ("\u90a3\u5c31\u5148\u6309\u4f60\u521a\u624d\u5b9a\u7684\u65b9\u5411\u7ee7\u7eed\u3002", {"reply": "\u90a3\u5c31\u5148\u6309\u4f60\u521a\u624d\u5b9a\u7684\u65b9\u5411\u7ee7\u7eed\u3002"}),
            ])
            bridge.invoker = invoker
            bridge.delivery = StubDelivery()

            message = "\u5c0f\u5e7b \u6309\u6211\u4e4b\u524d\u8bf4\u7684\u6765"
            bridge.handle_event({"type": "chat", "player": "alice", "message": message, "raw": f"<alice> {message}"})

            self.assertEqual(
                invoker.calls[1]["payload"]["decision"]["reason"],
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

    def test_multi_turn_repeated_question_sets_human_answer_context(self):
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
            self.assertTrue(third_payload["room_state"]["human_answer_seen"])
            self.assertEqual(third_payload["room_state"]["human_answer_candidates"][0]["speaker"], "bob")

    def test_multi_turn_yes_no_reply_sets_human_answer_context(self):
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
            self.assertTrue(third_payload["room_state"]["human_answer_seen"])
            self.assertEqual(third_payload["room_state"]["human_answer_candidates"][0]["text"], "yes")

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


if __name__ == "__main__":
    unittest.main()
