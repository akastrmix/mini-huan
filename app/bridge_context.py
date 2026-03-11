#!/usr/bin/env python3
"""Context selection and short-term chat analysis."""

import re
import time

from bridge_logging import Logger
from bridge_shared import (
    CJK_RE,
    WORD_RE,
)
from bridge_state import BridgeState, active_bot_reply_streak


class ContextBuilder:
    def __init__(self, config: dict, state: BridgeState, logger: Logger):
        self.config = config
        self.state = state
        self.logger = logger

    def tokenize_text(self, text: str):
        tokens = {token.lower() for token in WORD_RE.findall(text or "") if len(token) >= 2}
        for chunk in CJK_RE.findall(text or ""):
            if len(chunk) == 1:
                tokens.add(chunk)
                continue
            tokens.update(chunk[idx: idx + 2] for idx in range(len(chunk) - 1))
        return tokens

    def bot_name_alias_tokens(self):
        aliases = set()
        configured_aliases = self.config.get("nameAliases") or []
        for raw_name in (
            str(self.config.get("displayName", "mini-huan")),
            str(self.config.get("displayNameZh", "\u5c0f\u5e7b")),
            *[str(item) for item in configured_aliases],
        ):
            name = (raw_name or "").strip().lower()
            if not name:
                continue
            aliases.add(name)
            aliases.update(self.tokenize_text(name))
            aliases.update(part for part in re.split(r"[\s_-]+", name) if part)
        return aliases

    def configured_name_aliases(self):
        aliases = []
        seen = set()
        for raw_alias in self.config.get("nameAliases") or []:
            alias = str(raw_alias or "").strip()
            if not alias:
                continue
            alias_key = alias.lower()
            if alias_key in seen:
                continue
            seen.add(alias_key)
            aliases.append(alias)
        return aliases

    def bot_profile(self):
        return {
            "name": str(self.config.get("displayName", "mini-huan")),
            "name_zh": str(self.config.get("displayNameZh", "\u5c0f\u5e7b")),
            "name_aliases": self.configured_name_aliases(),
            "persona": ((self.config.get("botStyle") or {}).get("persona") or "Minecraft public-chat helper"),
        }

    def session_payload(self, active_session: dict | None, *, now: float | None = None):
        if not active_session:
            return None
        ref_now = time.time() if now is None else now
        return {
            "mode": str(active_session.get("mode") or ""),
            "topic": str(active_session.get("topic") or ""),
            "seconds_since_active": max(0, int(ref_now - float(active_session.get("last_active_ts") or ref_now))),
            "private_requested": bool(active_session.get("private_requested", False)),
            "last_request_text": str(active_session.get("last_request_text") or ""),
            "last_commands": list(active_session.get("last_commands") or []),
            "last_command_results": list(active_session.get("last_command_results") or []),
            "last_reply_text": str(active_session.get("last_reply_text") or ""),
        }

    def within_context_age(self, timestamp: float | None, *, now: float | None = None):
        max_age = int(self.config.get("contextMaxAgeSeconds", 900))
        if max_age <= 0:
            return True
        if timestamp is None:
            return False
        ref_now = time.time() if now is None else now
        return (ref_now - float(timestamp)) <= max_age

    def filter_entries_by_age(self, entries: list[dict], *, now: float | None = None):
        ref_now = time.time() if now is None else now
        return [
            item for item in entries
            if self.within_context_age(item.get("timestamp"), now=ref_now)
        ]

    def context_candidates(self):
        return self.filter_entries_by_age(list(self.state.data.get("recentChat", [])))

    def score_context_entry(self, entry: dict, current_player: str, current_message: str, current_tokens: set[str]):
        score = 0.0
        speaker = str(entry.get("speaker") or "")
        text = str(entry.get("text") or "")
        entry_type = str(entry.get("type") or "player")
        lower_text = text.lower()
        current_message_lower = current_message.lower()
        bot_name_matches = [
            str(self.config.get("displayName", "mini-huan")).lower(),
            str(self.config.get("displayNameZh", "\u5c0f\u5e7b")).lower(),
            *[alias.lower() for alias in self.configured_name_aliases()],
        ]

        if speaker == current_player:
            score += 6.0
        if entry_type == "bot":
            score += 2.0
        if speaker == str(self.config.get("displayName", "mini-huan")):
            score += 1.0
        if current_player and current_player.lower() in lower_text:
            score += 2.5
        if any(alias and alias in lower_text for alias in bot_name_matches):
            score += 2.5
        if current_message_lower and current_message_lower == lower_text:
            score += 1.0

        overlap = len(current_tokens & self.tokenize_text(text))
        if overlap:
            score += min(4.0, overlap * 1.5)

        age_seconds = max(0.0, time.time() - float(entry.get("timestamp", time.time())))
        if age_seconds <= 30:
            score += 2.0
        elif age_seconds <= 120:
            score += 1.0
        return score

    def select_recent_chat(self, config_key: str, default_count: int, current_player: str = "", current_message: str = ""):
        count = int(self.config.get(config_key, default_count))
        now = time.time()
        candidates = self.context_candidates()
        if not candidates:
            return []
        if len(candidates) <= count:
            selected = candidates
        else:
            current_tokens = self.tokenize_text(current_message)
            tail_reserve = max(4, min(count // 2, int(self.config.get("contextRecentTailReserve", 6))))
            tail = candidates[-tail_reserve:]
            tail_ids = {id(item) for item in tail}
            scored = []
            for idx, item in enumerate(candidates):
                base_score = self.score_context_entry(item, current_player, current_message, current_tokens)
                recency_bonus = idx / max(1, len(candidates))
                total = base_score + recency_bonus
                scored.append((total, idx, item))
            scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
            selected = list(tail)
            selected_ids = set(tail_ids)
            for total, idx, item in scored:
                if id(item) in selected_ids:
                    continue
                selected.append(item)
                selected_ids.add(id(item))
                if len(selected) >= count:
                    break
            selected.sort(key=lambda item: float(item.get("timestamp", 0.0)))
            selected = selected[-count:]
            if self.logger.score_logs_enabled():
                self.logger.emit({
                    "bridge": "context_scores",
                    "for": config_key,
                    "player": current_player,
                    "message": current_message,
                    "top": [
                        {
                            "speaker": item.get("speaker", ""),
                            "text": item.get("text", ""),
                            "score": round(total, 3),
                            "idx": idx,
                        }
                        for total, idx, item in scored[: min(12, len(scored))]
                    ],
                })
        return [
            {
                "speaker": item.get("speaker", ""),
                "text": item.get("text", ""),
                "type": item.get("type", "player"),
                "seconds_ago": max(0, int(now - float(item.get("timestamp", now)))),
            }
            for item in selected
        ]

    def recent_bot_messages(self, config_key: str, default_count: int):
        count = int(self.config.get(config_key, default_count))
        now = time.time()
        entries = self.filter_entries_by_age(list(self.state.data.get("recentBotReplies", [])), now=now)
        return [
            {
                "text": item.get("text", ""),
                "seconds_ago": max(0, int(now - float(item.get("timestamp", now)))),
            }
            for item in entries[-count:]
        ]

    def player_history(self, player: str, config_key: str, default_count: int):
        count = int(self.config.get(config_key, default_count))
        now = time.time()
        entries = self.filter_entries_by_age(
            list((self.state.data.get("playerMessageHistory", {}) or {}).get(player, [])),
            now=now,
        )
        return [
            {
                "text": item.get("text", ""),
                "seconds_ago": max(0, int(now - float(item.get("timestamp", now)))),
            }
            for item in entries[-count:]
        ]

    def build_judge_context(self, event: dict, active_session: dict | None = None):
        player = str(event.get("player") or "")
        message = str(event.get("message") or "")
        now = time.time()
        last_global = float(self.state.data.get("lastGlobalReplyTs", 0.0))
        return {
            "bot_profile": self.bot_profile(),
            "current_message": {
                "player": player,
                "text": message,
                "timestamp": int(now),
            },
            "recent_chat": self.select_recent_chat("judgeRecentChatCount", 10, player, message),
            "recent_bot_messages": self.recent_bot_messages("judgeRecentBotCount", 2),
            "player_recent_messages": self.player_history(player, "judgePlayerHistoryCount", 3),
            "active_session": self.session_payload(active_session, now=now),
            "room_state": {
                "seconds_since_bot_last_reply": None if last_global <= 0 else max(0, int(now - last_global)),
                "bot_consecutive_reply_count": active_bot_reply_streak(self.config, self.state, now=now),
            },
        }

    def build_reply_context(self, event: dict, decision: dict, active_session: dict | None = None):
        player = str(event.get("player") or "")
        message = str(event.get("message") or "")
        now = time.time()
        return {
            "bot_profile": {
                **self.bot_profile(),
                "style": self.config.get("botStyle") or {},
            },
            "decision": decision,
            "current_message": {"player": player, "text": message},
            "recent_chat": self.select_recent_chat(
                "replyRecentChatCount",
                int(self.config.get("judgeRecentChatCount", 10)),
                player,
                message,
            ),
            "recent_bot_messages": self.recent_bot_messages(
                "replyRecentBotCount", int(self.config.get("judgeRecentBotCount", 2))
            ),
            "player_recent_messages": self.player_history(
                player,
                "replyPlayerHistoryCount",
                int(self.config.get("judgePlayerHistoryCount", 3)),
            ),
            "active_session": self.session_payload(active_session, now=now),
            "max_reply_chars": int(self.config.get("maxReplyChars", 80)),
            "language_hint": self.config.get("languageHint") or "",
        }

    def build_router_context(self, event: dict, player_auth: dict, active_session: dict | None):
        player = str(event.get("player") or "")
        message = str(event.get("message") or "")
        now = time.time()
        last_global = float(self.state.data.get("lastGlobalReplyTs", 0.0))
        return {
            "bot_profile": self.bot_profile(),
            "player_auth": dict(player_auth or {}),
            "current_message": {
                "player": player,
                "text": message,
                "timestamp": int(now),
            },
            "active_session": self.session_payload(active_session, now=now),
            "recent_chat": self.select_recent_chat("judgeRecentChatCount", 10, player, message),
            "recent_bot_messages": self.recent_bot_messages("judgeRecentBotCount", 2),
            "player_recent_messages": self.player_history(player, "judgePlayerHistoryCount", 3),
            "room_state": {
                "seconds_since_bot_last_reply": None if last_global <= 0 else max(0, int(now - last_global)),
                "bot_consecutive_reply_count": active_bot_reply_streak(self.config, self.state, now=now),
            },
        }

    def build_privileged_context(
        self,
        event: dict,
        player_auth: dict,
        route: dict,
        active_session: dict | None,
        protocol_state: dict | None = None,
    ):
        player = str(event.get("player") or "")
        message = str(event.get("message") or "")
        now = time.time()
        return {
            "bot_profile": {
                **self.bot_profile(),
                "style": self.config.get("botStyle") or {},
            },
            "player_auth": dict(player_auth or {}),
            "route": dict(route or {}),
            "current_message": {
                "player": player,
                "text": message,
                "timestamp": int(now),
            },
            "active_session": self.session_payload(active_session, now=now),
            "recent_chat": self.select_recent_chat("replyRecentChatCount", 12, player, message),
            "recent_bot_messages": self.recent_bot_messages("replyRecentBotCount", 3),
            "player_recent_messages": self.player_history(player, "replyPlayerHistoryCount", 5),
            "max_reply_chars": int(self.config.get("maxReplyChars", 80)),
            "language_hint": self.config.get("languageHint") or "",
            "protocol": dict(protocol_state or {
                "version": 1,
                "phase": "initial_request",
                "command_round": 0,
                "max_command_rounds": int(self.config.get("privilegedCommandMaxRounds", 3)),
                "last_command_results": [],
                "command_history": [],
            }),
        }
