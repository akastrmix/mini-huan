#!/usr/bin/env python3
"""Judge parsing and gating for fallback chat decisions."""

import json
import time

from bridge_shared import (
    ALLOWED_REASONS,
    DEFAULT_GLOBAL_COOLDOWN,
    DEFAULT_PLAYER_COOLDOWN,
)
from bridge_state import BridgeState, active_bot_reply_streak


class JudgePipeline:
    def __init__(self, config: dict, state: BridgeState):
        self.config = config
        self.state = state

    def normalize_decision(
        self,
        event: dict,
        *,
        should_reply: bool,
        confidence: float,
        reason: str,
        topic: str,
        target_player: str | None = None,
        allow_followup_streak: bool = False,
        allow_soft_confidence_pass: bool = False,
    ):
        normalized_reason = str(reason or "not_addressed_to_bot")
        if normalized_reason not in ALLOWED_REASONS:
            normalized_reason = "not_addressed_to_bot"
        try:
            normalized_confidence = float(confidence)
        except (TypeError, ValueError):
            normalized_confidence = 0.0
        return {
            "should_reply": bool(should_reply),
            "confidence": max(0.0, min(1.0, normalized_confidence)),
            "reason": normalized_reason,
            "target_player": str(target_player or event.get("player") or ""),
            "topic": str(topic or "").strip(),
            "allow_followup_streak": bool(allow_followup_streak),
            "allow_soft_confidence_pass": bool(allow_soft_confidence_pass),
        }

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

    def same_player_followup_window_active(self, event: dict, decision: dict, *, now: float):
        if not bool(decision.get("allow_followup_streak", False)):
            return False
        return self.recent_reply_to_player_within_window(str(event.get("player") or ""), now=now)

    def parse(self, raw_text: str, event: dict):
        default_reason = "not_addressed_to_bot"
        raw_text = (raw_text or "").strip()
        if not raw_text:
            return self.normalize_decision(
                event,
                should_reply=False,
                confidence=0.0,
                reason=default_reason,
                topic="",
                allow_soft_confidence_pass=False,
            )
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            decision = self.normalize_decision(
                event,
                should_reply=False,
                confidence=0.0,
                reason=default_reason,
                topic="",
                allow_soft_confidence_pass=False,
            )
            decision["raw"] = raw_text
            return decision
        return self.normalize_decision(
            event,
            should_reply=bool(parsed.get("should_reply", False)),
            confidence=parsed.get("confidence", 0.0),
            reason=str(parsed.get("reason") or default_reason),
            target_player=str(parsed.get("target_player") or event.get("player") or ""),
            topic=str(parsed.get("topic") or "").strip(),
            allow_followup_streak=bool(parsed.get("allow_followup_streak", False)),
            allow_soft_confidence_pass=bool(parsed.get("allow_soft_confidence_pass", False)),
        )

    def gate_delivery_limits(self, event: dict, decision: dict, *, now: float):
        reason = str(decision.get("reason") or "")
        is_appreciation = reason == "appreciation_after_bot_reply"
        if is_appreciation and not self.config.get("allowAppreciationReplies", True):
            return False, "appreciation_disabled"
        max_consecutive = int(self.config.get("maxBotConsecutiveReplies", 1))
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

    def gate(self, event: dict, decision: dict):
        if not decision.get("should_reply"):
            return False, "judge_declined"
        confidence = float(decision.get("confidence", 0.0))
        hard_threshold = float(self.config.get("judgeConfidenceThreshold", 0.72))
        soft_threshold = float(self.config.get("judgeSoftThreshold", 0.58))
        if confidence < soft_threshold:
            return False, "confidence_below_soft_threshold"
        if confidence < hard_threshold and not bool(decision.get("allow_soft_confidence_pass", False)):
            return False, "confidence_below_hard_threshold"
        return self.gate_delivery_limits(event, decision, now=time.time())

    def gate_router_chat(self, event: dict, decision: dict):
        if not decision.get("should_reply"):
            return False, "router_declined"
        return self.gate_delivery_limits(event, decision, now=time.time())
