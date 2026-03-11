#!/usr/bin/env python3
"""Judge parsing, overrides, and gating."""

import json
import time

from bridge_shared import (
    ALLOWED_REASONS,
    CAPABILITY_REFUSAL_MARKERS,
    CAPABILITY_REFUSAL_MARKERS_ZH,
    CAPABILITY_REQUEST_MARKERS,
    CAPABILITY_REQUEST_MARKERS_ZH,
    DEFAULT_GLOBAL_COOLDOWN,
    DEFAULT_PLAYER_COOLDOWN,
    DIRECT_REQUEST_HINTS_ZH,
    DIRECT_REQUEST_PREFIXES,
    FOLLOWUP_STREAK_REASONS,
    MEMORY_LIMIT_REQUEST_MARKERS,
    MEMORY_LIMIT_REQUEST_MARKERS_ZH,
    MILD_PRESSURE_MARKERS,
    PRIVATE_REQUEST_MARKERS,
    PRIVATE_REQUEST_MARKERS_ZH,
    PROACTIVE_DIRECT_OVERRIDE_BLOCK_REASONS,
    QUESTION_HINTS_ZH,
    QUESTION_START_RE,
    SEVERE_THREAT_MARKERS,
    SOFT_PASS_REASONS,
)
from bridge_state import BridgeState, active_bot_reply_streak


class JudgePipeline:
    def __init__(self, config: dict, state: BridgeState):
        self.config = config
        self.state = state

    def text_contains_markers(self, message: str, english_markers, *, zh_markers=()):
        lower_text = (message or "").lower()
        return any(marker in lower_text for marker in english_markers) or any(marker.lower() in lower_text for marker in zh_markers)

    def recent_bot_capability_refusal(self, judge_context: dict):
        recent_bot_messages = list((judge_context or {}).get("recent_bot_messages") or [])
        if not recent_bot_messages:
            return False
        last_bot_message = recent_bot_messages[-1]
        if int(last_bot_message.get("seconds_ago") or 999999) > 90:
            return False
        text = str(last_bot_message.get("text") or "")
        return self.text_contains_markers(
            text,
            CAPABILITY_REFUSAL_MARKERS,
            zh_markers=CAPABILITY_REFUSAL_MARKERS_ZH,
        )

    def looks_like_mild_pressure_after_refusal(self, message: str):
        lower_text = (message or "").lower()
        if not lower_text:
            return False
        if any(marker in lower_text for marker in SEVERE_THREAT_MARKERS):
            return False
        return any(marker in lower_text for marker in MILD_PRESSURE_MARKERS)

    def message_mentions_bot_name(self, message: str, judge_context: dict):
        lower_text = (message or "").lower()
        bot_profile = dict((judge_context or {}).get("bot_profile") or {})
        names = [
            str(bot_profile.get("name") or "").strip().lower(),
            str(bot_profile.get("name_zh") or "").strip().lower(),
            *[str(item or "").strip().lower() for item in (bot_profile.get("name_aliases") or [])],
        ]
        return any(name and name in lower_text for name in names)

    def has_direct_request_shape(self, message: str):
        raw_text = message or ""
        lower_text = raw_text.lower()
        return (
            any(ch in raw_text for ch in ("?", "\uff1f"))
            or QUESTION_START_RE.search(lower_text)
            or any(lower_text.startswith(prefix) for prefix in DIRECT_REQUEST_PREFIXES)
        )

    def recent_reply_to_player_within_window(self, player: str, *, now: float | None = None, min_window: float = 0.0):
        player = str(player or "").strip()
        if not player:
            return False
        ref_now = time.time() if now is None else now
        window_seconds = max(min_window, float(self.config.get("followupReplyWindowSeconds", 90)))
        if window_seconds <= 0:
            return False
        last_player_reply_ts = float((self.state.data.get("lastPlayerReplyTs", {}) or {}).get(player, 0.0))
        if last_player_reply_ts <= 0:
            return False
        return (ref_now - last_player_reply_ts) <= window_seconds

    def has_direct_request_shape_for_override(self, message: str):
        raw_text = message or ""
        return (
            self.has_direct_request_shape(message)
            or any(hint in raw_text for hint in DIRECT_REQUEST_HINTS_ZH)
            or any(hint in raw_text for hint in QUESTION_HINTS_ZH)
        )

    def recent_same_player_bot_exchange(self, player: str, *, now: float | None = None, min_window: float = 0.0):
        player = str(player or "").strip()
        if not self.recent_reply_to_player_within_window(player, now=now, min_window=min_window):
            return False
        ref_now = time.time() if now is None else now
        window_seconds = max(min_window, float(self.config.get("followupReplyWindowSeconds", 90)))
        display_name = str(self.config.get("displayName", "mini-huan")).strip()
        recent_entries = []
        for entry in list(self.state.data.get("recentChat", [])):
            timestamp = float(entry.get("timestamp", 0.0) or 0.0)
            if timestamp <= 0 or (ref_now - timestamp) > window_seconds:
                continue
            recent_entries.append(entry)
        if not recent_entries:
            return False

        seen_current_player = False
        for entry in reversed(recent_entries):
            speaker = str(entry.get("speaker") or "").strip()
            entry_type = str(entry.get("type") or "player")
            if not seen_current_player:
                if entry_type == "player" and speaker == player:
                    seen_current_player = True
                continue
            if entry_type == "bot" or (display_name and speaker == display_name):
                return True
            if entry_type == "player" and speaker and speaker != player:
                return False
        return False

    def directed_or_direct_request(self, event: dict, message: str, judge_context: dict):
        if self.message_mentions_bot_name(message, judge_context):
            return True
        if not self.has_direct_request_shape_for_override(message):
            return False
        return self.recent_same_player_bot_exchange(
            str(event.get("player") or ""),
            min_window=30.0,
        )

    def classify_refusal_override(self, event: dict, judge_context: dict):
        message = str(event.get("message") or "")
        lower_text = message.lower()
        if not self.directed_or_direct_request(event, message, judge_context):
            return None
        if any(marker in lower_text for marker in SEVERE_THREAT_MARKERS):
            return None
        if self.text_contains_markers(message, PRIVATE_REQUEST_MARKERS, zh_markers=PRIVATE_REQUEST_MARKERS_ZH):
            return ("privacy_refusal", "private server details request")
        if self.text_contains_markers(message, MEMORY_LIMIT_REQUEST_MARKERS, zh_markers=MEMORY_LIMIT_REQUEST_MARKERS_ZH):
            return ("memory_limit_refusal", "older message recall request")
        if self.text_contains_markers(message, CAPABILITY_REQUEST_MARKERS, zh_markers=CAPABILITY_REQUEST_MARKERS_ZH):
            return ("capability_refusal", "permission or command request")
        return None

    def classify_proactive_direct_override(self, event: dict, decision: dict, judge_context: dict):
        reason = str(decision.get("reason") or "")
        if reason in PROACTIVE_DIRECT_OVERRIDE_BLOCK_REASONS:
            return None
        message = str(event.get("message") or "")
        lower_text = message.lower()
        if any(marker in lower_text for marker in SEVERE_THREAT_MARKERS):
            return None
        named = self.message_mentions_bot_name(message, judge_context)
        direct_request = self.has_direct_request_shape_for_override(message)
        followup = direct_request and self.recent_same_player_bot_exchange(
            str(event.get("player") or ""),
            min_window=30.0,
        )
        if not named and not followup:
            return None
        if followup and not named:
            return ("followup_to_bot_conversation", "same-player follow-up question")
        if direct_request:
            return ("direct_question_to_bot", "direct player question")
        return ("direct_address_to_bot", "direct address to bot")

    def decision_has_public_chat_signal(self, event: dict, decision: dict, judge_context: dict):
        message = str(event.get("message") or "")
        player = str(event.get("player") or "")
        reason = str(decision.get("reason") or "")
        named = self.message_mentions_bot_name(message, judge_context)
        if named:
            return True

        followup = self.recent_same_player_bot_exchange(player, min_window=30.0)
        direct_request = self.has_direct_request_shape_for_override(message)
        mild_pressure = self.looks_like_mild_pressure_after_refusal(message)

        if reason in {"direct_address_to_bot", "greeting_to_bot"}:
            return False
        if reason == "appreciation_after_bot_reply":
            return followup
        if reason == "followup_to_bot_conversation":
            return followup and (direct_request or mild_pressure)
        if reason in {
            "direct_question_to_bot",
            "help_request",
            "privacy_refusal",
            "capability_refusal",
            "memory_limit_refusal",
            "server_assistant_relevant",
        }:
            return followup and direct_request
        return followup and (direct_request or mild_pressure)

    def apply_public_chat_guard(self, event: dict, decision: dict, judge_context: dict):
        if not decision.get("should_reply"):
            return decision
        if self.decision_has_public_chat_signal(event, decision, judge_context):
            return decision
        updated = dict(decision)
        updated["should_reply"] = False
        updated["confidence"] = min(float(updated.get("confidence", 0.0)), 0.35)
        updated["reason"] = "not_addressed_to_bot"
        updated["topic"] = "missing explicit bot signal"
        return updated

    def maybe_override_decline(self, event: dict, decision: dict, judge_context: dict):
        if decision.get("should_reply"):
            return decision
        refusal_override = self.classify_refusal_override(event, judge_context)
        if refusal_override is not None:
            override_reason, override_topic = refusal_override
            updated = dict(decision)
            updated["should_reply"] = True
            updated["confidence"] = max(float(updated.get("confidence", 0.0)), 0.84)
            updated["reason"] = override_reason
            updated["topic"] = override_topic
            return updated
        direct_override = self.classify_proactive_direct_override(event, decision, judge_context)
        if direct_override is not None:
            override_reason, override_topic = direct_override
            updated = dict(decision)
            updated["should_reply"] = True
            updated["confidence"] = max(float(updated.get("confidence", 0.0)), 0.84)
            updated["reason"] = override_reason
            updated["topic"] = override_topic
            return updated
        if str(decision.get("reason") or "") != "unsafe_or_out_of_scope":
            return decision
        if not self.recent_bot_capability_refusal(judge_context):
            return decision
        if not self.looks_like_mild_pressure_after_refusal(str(event.get("message") or "")):
            return decision
        updated = dict(decision)
        updated["should_reply"] = True
        updated["confidence"] = max(float(updated.get("confidence", 0.0)), 0.84)
        updated["reason"] = "followup_to_bot_conversation"
        updated["topic"] = "pushback after capability refusal"
        return updated

    def same_player_followup_window_active(self, event: dict, decision: dict, *, now: float):
        reason = str(decision.get("reason") or "")
        if reason not in FOLLOWUP_STREAK_REASONS:
            return False
        return self.recent_same_player_bot_exchange(str(event.get("player") or ""), now=now)

    def parse(self, raw_text: str, event: dict):
        default_reason = "not_addressed_to_bot"
        raw_text = (raw_text or "").strip()
        if not raw_text:
            return {
                "should_reply": False,
                "confidence": 0.0,
                "reason": default_reason,
                "target_player": event.get("player") or "",
                "topic": "",
            }
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return {
                "should_reply": False,
                "confidence": 0.0,
                "reason": default_reason,
                "target_player": event.get("player") or "",
                "topic": "",
                "raw": raw_text,
            }
        reason = str(parsed.get("reason") or default_reason)
        if reason not in ALLOWED_REASONS:
            reason = default_reason
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "should_reply": bool(parsed.get("should_reply", False)),
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": reason,
            "target_player": str(parsed.get("target_player") or event.get("player") or ""),
            "topic": str(parsed.get("topic") or "").strip(),
        }

    def gate(self, event: dict, decision: dict):
        if not decision.get("should_reply"):
            return False, "judge_declined"
        confidence = float(decision.get("confidence", 0.0))
        hard_threshold = float(self.config.get("judgeConfidenceThreshold", 0.72))
        soft_threshold = float(self.config.get("judgeSoftThreshold", 0.58))
        reason = str(decision.get("reason") or "")
        is_appreciation = reason == "appreciation_after_bot_reply"
        if confidence < soft_threshold:
            return False, "confidence_below_soft_threshold"
        if confidence < hard_threshold and reason not in SOFT_PASS_REASONS:
            return False, "confidence_below_hard_threshold"
        if is_appreciation and not self.config.get("allowAppreciationReplies", True):
            return False, "appreciation_disabled"
        max_consecutive = int(self.config.get("maxBotConsecutiveReplies", 1))
        now = time.time()
        active_streak = active_bot_reply_streak(self.config, self.state, now=now)
        streak_limit = max_consecutive + 1 if is_appreciation and max_consecutive >= 0 else max_consecutive
        if self.same_player_followup_window_active(event, decision, now=now) and max_consecutive >= 0:
            streak_limit = max(
                streak_limit,
                int(self.config.get("maxSamePlayerConversationReplies", 4)),
            )
        if streak_limit >= 0 and active_streak >= streak_limit:
            return False, "max_bot_consecutive_replies"
        global_cd = float(self.config.get("globalCooldownSeconds", DEFAULT_GLOBAL_COOLDOWN))
        if global_cd > 0 and now - float(self.state.data.get("lastGlobalReplyTs", 0.0)) < global_cd:
            return False, "global_cooldown"
        player_cd = float(self.config.get("playerCooldownSeconds", DEFAULT_PLAYER_COOLDOWN))
        player = str(event.get("player") or "")
        if player_cd > 0 and now - float(self.state.data.get("lastPlayerReplyTs", {}).get(player, 0.0)) < player_cd:
            return False, "player_cooldown"
        return True, "passed"
