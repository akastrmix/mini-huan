#!/usr/bin/env python3
"""Context selection and short-term chat analysis."""

import re
import time

from bridge_logging import Logger
from bridge_shared import (
    ANSWER_HINTS,
    CJK_RE,
    EN_CONTENT_STOPWORDS,
    EXPLICIT_ANSWER_START_HINTS_ZH,
    EXPLICIT_ANSWER_START_RE,
    QUESTION_HINTS_ZH,
    QUESTION_START_RE,
    SHORT_YES_NO_ANSWER_RE,
    WORD_RE,
    YES_NO_QUESTION_HINTS_ZH,
    YES_NO_START_RE,
    ZH_CONTENT_STOPWORDS,
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

    def text_contains_any(self, text: str, phrases):
        return any(phrase and phrase in text for phrase in phrases)

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

    def content_tokens(self, text: str, *, current_player: str = ""):
        tokens = set(self.tokenize_text(text))
        stop_tokens = set(EN_CONTENT_STOPWORDS)
        stop_tokens.update(ZH_CONTENT_STOPWORDS)
        stop_tokens.update(self.bot_name_alias_tokens())
        if current_player:
            stop_tokens.update(self.tokenize_text(current_player.lower()))
        return {token for token in tokens if token and token not in stop_tokens}

    def message_has_question_signal(self, text: str):
        text = text or ""
        lower_text = text.lower()
        return (
            any(ch in text for ch in ("?", "\uff1f"))
            or bool(QUESTION_START_RE.search(lower_text))
            or self.text_contains_any(text, QUESTION_HINTS_ZH)
        )

    def is_yes_no_question(self, text: str):
        text = text or ""
        return bool(YES_NO_START_RE.search(text.lower())) or self.text_contains_any(text, YES_NO_QUESTION_HINTS_ZH)

    def looks_like_answer_form(self, text: str):
        text = text or ""
        lower_text = text.lower()
        stripped = text.strip()
        return (
            stripped.startswith("/")
            or bool(SHORT_YES_NO_ANSWER_RE.match(stripped))
            or bool(EXPLICIT_ANSWER_START_RE.search(lower_text))
            or self.text_contains_any(text, EXPLICIT_ANSWER_START_HINTS_ZH)
            or any(hint in lower_text for hint in ANSWER_HINTS)
        )

    def score_human_answer_candidate(
        self,
        *,
        current_message: str,
        current_tokens: set[str],
        focus_tokens: set[str],
        candidate_text: str,
        context_bonus: float = 0.0,
    ):
        candidate_tokens = self.tokenize_text(candidate_text)
        focus_overlap = len(focus_tokens & candidate_tokens)
        broad_overlap = len(current_tokens & candidate_tokens)
        looks_like_answer = self.looks_like_answer_form(candidate_text)
        pure_question = self.message_has_question_signal(candidate_text) and not looks_like_answer
        score = 0.0

        if focus_overlap:
            score += min(4.0, focus_overlap * 2.0)
        elif broad_overlap >= 2:
            score += min(2.0, float(broad_overlap))
        if looks_like_answer:
            score += 2.0
        if self.is_yes_no_question(current_message) and SHORT_YES_NO_ANSWER_RE.match(candidate_text.strip()):
            score += 3.0
        if len(candidate_text.strip()) >= 10:
            score += 0.5
        if re.search(r"\d", candidate_text) and (re.search(r"\d", current_message) or any(op in current_message for op in "+-*/=")):
            score += 1.5
        if pure_question:
            score -= 2.5
        score += context_bonus
        return score

    def prior_same_player_question_context_bonus(
        self,
        entries: list[dict],
        candidate_idx: int,
        *,
        current_player: str,
        current_message: str,
        current_tokens: set[str],
        focus_tokens: set[str],
    ):
        start_idx = max(0, candidate_idx - 3)
        for prev_entry in reversed(entries[start_idx:candidate_idx]):
            if str(prev_entry.get("type") or "player") != "player":
                continue
            if str(prev_entry.get("speaker") or "") != current_player:
                continue
            prev_text = str(prev_entry.get("text") or "")
            if not self.message_has_question_signal(prev_text):
                continue
            if prev_text.strip().lower() == current_message.strip().lower():
                return 2.0
            prev_focus_tokens = self.content_tokens(prev_text, current_player=current_player)
            if prev_focus_tokens & focus_tokens:
                return 1.5
            if len(self.tokenize_text(prev_text) & current_tokens) >= 2:
                return 1.5
        return 0.0

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

    def human_answer_candidates(self, current_player: str, current_message: str, *, max_candidates: int = 2):
        candidates = self.context_candidates()
        if not candidates:
            return []
        if not self.message_has_question_signal(current_message):
            return []
        now = time.time()
        current_tokens = self.tokenize_text(current_message)
        focus_tokens = self.content_tokens(current_message, current_player=current_player)
        lookback = int(self.config.get("humanAnswerLookbackCount", 8))
        selected = []
        scoped_candidates = candidates[-lookback:]
        for idx in range(len(scoped_candidates) - 1, -1, -1):
            entry = scoped_candidates[idx]
            speaker = str(entry.get("speaker") or "")
            text = str(entry.get("text") or "")
            if str(entry.get("type") or "player") != "player" or not speaker or speaker == current_player:
                continue
            context_bonus = self.prior_same_player_question_context_bonus(
                scoped_candidates,
                idx,
                current_player=current_player,
                current_message=current_message,
                current_tokens=current_tokens,
                focus_tokens=focus_tokens,
            )
            score = self.score_human_answer_candidate(
                current_message=current_message,
                current_tokens=current_tokens,
                focus_tokens=focus_tokens,
                candidate_text=text,
                context_bonus=context_bonus,
            )
            if score < 3.0:
                continue
            selected.append({
                "speaker": speaker,
                "text": text,
                "seconds_ago": max(0, int(now - float(entry.get("timestamp", now)))),
            })
            if len(selected) >= max_candidates:
                break
        return list(reversed(selected))

    def detect_human_answer_seen(self, current_player: str, current_message: str):
        return bool(self.human_answer_candidates(current_player, current_message))

    def build_judge_context(self, event: dict):
        player = str(event.get("player") or "")
        message = str(event.get("message") or "")
        now = time.time()
        last_global = float(self.state.data.get("lastGlobalReplyTs", 0.0))
        human_answers = self.human_answer_candidates(player, message)
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
            "room_state": {
                "seconds_since_bot_last_reply": None if last_global <= 0 else max(0, int(now - last_global)),
                "bot_consecutive_reply_count": active_bot_reply_streak(self.config, self.state, now=now),
                "human_answer_seen": bool(human_answers),
                "human_answer_candidates": human_answers,
            },
        }

    def build_reply_context(self, event: dict, decision: dict):
        player = str(event.get("player") or "")
        message = str(event.get("message") or "")
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
            "max_reply_chars": int(self.config.get("maxReplyChars", 80)),
            "language_hint": self.config.get("languageHint") or "",
        }

    def build_router_context(self, event: dict, player_auth: dict, active_session: dict | None):
        player = str(event.get("player") or "")
        message = str(event.get("message") or "")
        now = time.time()
        session_payload = None
        if active_session:
            session_payload = {
                "mode": str(active_session.get("mode") or ""),
                "topic": str(active_session.get("topic") or ""),
                "seconds_since_active": max(0, int(now - float(active_session.get("last_active_ts") or now))),
                "private_requested": bool(active_session.get("private_requested", False)),
                "last_request_text": str(active_session.get("last_request_text") or ""),
                "last_commands": list(active_session.get("last_commands") or []),
                "last_reply_text": str(active_session.get("last_reply_text") or ""),
            }
        return {
            "bot_profile": self.bot_profile(),
            "player_auth": dict(player_auth or {}),
            "current_message": {
                "player": player,
                "text": message,
                "timestamp": int(now),
            },
            "active_session": session_payload,
            "recent_chat": self.select_recent_chat("judgeRecentChatCount", 10, player, message),
            "recent_bot_messages": self.recent_bot_messages("judgeRecentBotCount", 2),
            "player_recent_messages": self.player_history(player, "judgePlayerHistoryCount", 3),
        }

    def build_privileged_context(
        self,
        event: dict,
        player_auth: dict,
        route: dict,
        active_session: dict | None,
    ):
        player = str(event.get("player") or "")
        message = str(event.get("message") or "")
        now = time.time()
        session_payload = None
        if active_session:
            session_payload = {
                "mode": str(active_session.get("mode") or ""),
                "topic": str(active_session.get("topic") or ""),
                "seconds_since_active": max(0, int(now - float(active_session.get("last_active_ts") or now))),
                "private_requested": bool(active_session.get("private_requested", False)),
                "last_request_text": str(active_session.get("last_request_text") or ""),
                "last_commands": list(active_session.get("last_commands") or []),
                "last_reply_text": str(active_session.get("last_reply_text") or ""),
            }
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
            "active_session": session_payload,
            "recent_chat": self.select_recent_chat("replyRecentChatCount", 12, player, message),
            "recent_bot_messages": self.recent_bot_messages("replyRecentBotCount", 3),
            "player_recent_messages": self.player_history(player, "replyPlayerHistoryCount", 5),
            "max_reply_chars": int(self.config.get("maxReplyChars", 80)),
            "language_hint": self.config.get("languageHint") or "",
        }
