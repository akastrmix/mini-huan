#!/usr/bin/env python3
"""Shared bridge components for context building, agent calls, and delivery."""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = BASE_DIR / "runtime" / "mc_ai_bridge_state.json"
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "bridge_config.json"
DEFAULT_AGENT = "mc-helper"
DEFAULT_GLOBAL_COOLDOWN = 8.0
DEFAULT_PLAYER_COOLDOWN = 15.0
DEFAULT_MAX_MESSAGE_CHARS = 120
DEFAULT_TIMEOUT = 90
DEFAULT_SUBPROCESS_TIMEOUT_BUFFER = 15
DEFAULT_RCON_TIMEOUT = 15.0
DEFAULT_BOT_REPLY_STREAK_RESET = 180.0
DEFAULT_HELPER_SCRIPT = str(BASE_DIR / "scripts" / "invoke_mc_helper.py")
DEFAULT_RCON_SCRIPT = r"C:\Users\Administrator\.openclaw\workspace\skills\mc-rcon-exec\scripts\send-rcon.ps1"
DEFAULT_PYTHON = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
DEFAULT_JUDGE_PROMPT = str(BASE_DIR / "config" / "judge_prompt.txt")
DEFAULT_REPLY_PROMPT = str(BASE_DIR / "config" / "reply_prompt.txt")
WORD_RE = re.compile(r"\w+", re.UNICODE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
QUESTION_START_RE = re.compile(
    r"^\s*(who|what|what's|whats|where|when|why|how|can|could|should|would|do|does|did|is|are|am|was|were|will|have|has|had)\b",
    re.IGNORECASE,
)
YES_NO_START_RE = re.compile(
    r"^\s*(can|could|should|would|do|does|did|is|are|am|was|were|will|have|has|had)\b",
    re.IGNORECASE,
)
SHORT_YES_NO_ANSWER_RE = re.compile(
    r"^\s*(yes|yeah|yep|no|nope|nah|true|false|correct|wrong|是|不是|对|不对|可以|不可以|能|不能|有|没有|行|不行|会|不会)\W*$",
    re.IGNORECASE,
)
EXPLICIT_ANSWER_START_RE = re.compile(
    r"^\s*(it('?s| is)|you('?re| are)|they('?re| are)|he('?s| is)|she('?s| is)|use|try|just|because|first|then)\b",
    re.IGNORECASE,
)
ALLOWED_REASONS = {
    "direct_question_to_bot",
    "direct_address_to_bot",
    "help_request",
    "followup_to_bot_conversation",
    "privacy_refusal",
    "capability_refusal",
    "memory_limit_refusal",
    "greeting_to_bot",
    "server_assistant_relevant",
    "appreciation_after_bot_reply",
    "players_chatting_with_each_other",
    "message_too_vague",
    "not_addressed_to_bot",
    "conversation_already_answered",
    "spam_or_noise",
    "cooldown_recommended",
    "unsafe_or_out_of_scope",
}
SOFT_PASS_REASONS = {
    "direct_question_to_bot",
    "direct_address_to_bot",
    "followup_to_bot_conversation",
    "privacy_refusal",
    "capability_refusal",
    "memory_limit_refusal",
}
FOLLOWUP_STREAK_REASONS = {
    "direct_question_to_bot",
    "direct_address_to_bot",
    "help_request",
    "followup_to_bot_conversation",
    "privacy_refusal",
    "capability_refusal",
    "memory_limit_refusal",
    "greeting_to_bot",
    "server_assistant_relevant",
}
PROACTIVE_DIRECT_OVERRIDE_BLOCK_REASONS = {
    "spam_or_noise",
    "unsafe_or_out_of_scope",
}
MILD_PRESSURE_MARKERS = (
    "if you dont",
    "if you don't",
    "or else",
    "call the admin",
    "ask the admin",
    "report you",
    "delete you",
    "remove you",
    "kick you",
    "ban you",
)
SEVERE_THREAT_MARKERS = (
    "kill you",
    "hurt you",
    "attack you",
    "doxx you",
    "swat you",
)
CAPABILITY_REFUSAL_MARKERS = (
    "i cannot",
    "i can't",
    "cannot run",
    "can't run",
    "cannot execute",
    "can't execute",
    "i can only",
    "admin can help",
    "ask an admin",
)
DIRECT_REQUEST_PREFIXES = (
    "tell me",
    "can you",
    "could you",
    "would you",
    "will you",
    "repeat",
    "show me",
    "give me",
    "what did",
    "do you remember",
    "remind me",
)
DIRECT_REQUEST_HINTS_ZH = {
    "你能",
    "你可以",
    "能不能",
    "可不可以",
    "帮我",
    "告诉我",
    "再说一遍",
    "重复",
    "记得",
    "记不记得",
    "是什么",
    "是谁",
    "怎么",
    "如何",
    "为什么",
    "多少",
    "哪里",
    "哪儿",
}
PRIVATE_REQUEST_MARKERS = (
    "ip address",
    "server ip",
    "your ip",
    "server address",
    "your address",
    "server port",
    "your port",
)
MEMORY_LIMIT_REQUEST_MARKERS = (
    "repeat what i said",
    "what did i say",
    "what was my last message",
    "do you remember what i said",
    "repeat my last message",
    "repeat what i said last time",
)
CAPABILITY_REQUEST_MARKERS = (
    "run commands",
    "run command",
    "execute commands",
    "execute command",
    "give me op",
    "op me",
    "give me admin",
    "make me admin",
    "give me creative",
    "make me creative",
    "tp me",
    "teleport me",
)
ANSWER_HINTS = {
    "是", "可以", "应该", "因为", "直接", "先", "然后", "需要", "用", "去", "在",
    "就是", "叫", "拿", "you", "can", "use", "need", "just", "try", "go", "because", "then", "first",
}
QUESTION_HINTS_ZH = {
    "什么", "怎么", "怎样", "如何", "谁", "哪", "哪里", "哪儿", "几", "多少", "吗", "呢", "嘛", "么",
    "是不是", "有没有", "能不能", "可不可以", "要不要", "行不行", "对吗",
}
YES_NO_QUESTION_HINTS_ZH = {
    "是不是", "有没有", "能不能", "可不可以", "要不要", "行不行", "对吗", "吗",
}
EXPLICIT_ANSWER_START_HINTS_ZH = {
    "是", "不是", "就是", "你是", "叫", "用", "先", "然后", "因为", "直接",
}
EN_CONTENT_STOPWORDS = {
    "a", "an", "the", "to", "of", "for", "in", "on", "at", "is", "are", "am", "was", "were",
    "be", "being", "been", "do", "does", "did", "can", "could", "should", "would", "will",
    "have", "has", "had", "what", "whats", "what's", "who", "where", "when", "why", "how",
    "which", "tell", "me", "my", "your", "you", "i", "we", "they", "it", "this", "that",
    "please", "hey", "hi", "hello",
}
ZH_CONTENT_STOPWORDS = {
    "什么", "怎么", "怎样", "如何", "吗", "呢", "嘛", "么", "是不是", "有没有", "能不能",
    "可不可以", "要不要", "行不行", "一下",
}


class BridgeState:
    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "sessionId": None,
            "lastGlobalReplyTs": 0.0,
            "lastPlayerReplyTs": {},
            "recentEventKeys": [],
            "recentChat": [],
            "recentBotReplies": [],
            "playerMessageHistory": {},
            "botConsecutiveReplyCount": 0,
        }
        self.load()

    def load(self):
        if not self.path.exists():
            return
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass
        self.data.setdefault("recentChat", [])
        self.data.setdefault("recentBotReplies", [])
        self.data.setdefault("playerMessageHistory", {})
        self.data.setdefault("botConsecutiveReplyCount", 0)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def session_id(self):
        return self.data.get("sessionId")

    def set_session_id(self, session_id: str):
        if session_id:
            self.data["sessionId"] = session_id

    def bot_reply_streak(self, *, reset_after_seconds: float | None = None, now: float | None = None):
        streak = int(self.data.get("botConsecutiveReplyCount", 0))
        if streak <= 0:
            return 0
        if reset_after_seconds is None or reset_after_seconds <= 0:
            return streak
        last_reply_ts = float(self.data.get("lastGlobalReplyTs", 0.0))
        ref_now = time.time() if now is None else now
        if last_reply_ts <= 0:
            return streak
        if (ref_now - last_reply_ts) >= reset_after_seconds:
            self.data["botConsecutiveReplyCount"] = 0
            return 0
        return streak

    def reset_bot_reply_streak(self):
        self.data["botConsecutiveReplyCount"] = 0

    def remember_event_key(self, event_key: str, max_recent: int):
        recent = list(self.data.get("recentEventKeys", []))
        if event_key in recent:
            return True
        recent.append(event_key)
        self.data["recentEventKeys"] = recent[-max_recent:]
        return False

    def append_chat_entry(
        self,
        *,
        speaker: str,
        text: str,
        entry_type: str,
        recent_chat_limit: int,
        player_history_limit: int,
        recent_bot_limit: int,
        timestamp: float | None = None,
    ):
        if not speaker or text is None:
            return
        now = float(timestamp if timestamp is not None else time.time())
        recent_chat = list(self.data.get("recentChat", []))
        recent_chat.append({"speaker": speaker, "text": text, "timestamp": now, "type": entry_type})
        self.data["recentChat"] = recent_chat[-recent_chat_limit:]

        if entry_type == "player":
            player_history = dict(self.data.get("playerMessageHistory", {}))
            entries = list(player_history.get(speaker, []))
            entries.append({"text": text, "timestamp": now})
            player_history[speaker] = entries[-player_history_limit:]
            self.data["playerMessageHistory"] = player_history
            return

        if entry_type == "bot":
            recent_bot = list(self.data.get("recentBotReplies", []))
            recent_bot.append({"text": text, "timestamp": now})
            self.data["recentBotReplies"] = recent_bot[-recent_bot_limit:]
            self.data["botConsecutiveReplyCount"] = self.bot_reply_streak() + 1

    def record_delivery(self, *, player: str, reply: str, display_name: str, timestamp: float, recent_chat_limit: int, recent_bot_limit: int, player_history_limit: int):
        self.data["lastGlobalReplyTs"] = timestamp
        self.data.setdefault("lastPlayerReplyTs", {})[player] = timestamp
        self.append_chat_entry(
            speaker=display_name,
            text=reply,
            entry_type="bot",
            recent_chat_limit=recent_chat_limit,
            player_history_limit=player_history_limit,
            recent_bot_limit=recent_bot_limit,
            timestamp=timestamp,
        )


def active_bot_reply_streak(config: dict, state: BridgeState, *, now: float | None = None):
    reset_after = float(config.get("botReplyStreakResetSeconds", DEFAULT_BOT_REPLY_STREAK_RESET))
    return state.bot_reply_streak(reset_after_seconds=reset_after, now=now)


class Logger:
    def __init__(self, config: dict):
        self.config = config

    def enabled(self, key: str, default: bool = False) -> bool:
        return bool(self.config.get(key, default))

    def emit(self, payload: dict, *, error: bool = False, force: bool = True):
        if not force:
            return
        target = sys.stderr if error else sys.stdout
        print(json.dumps(payload, ensure_ascii=False), file=target, flush=True)

    def input_logs_enabled(self) -> bool:
        return self.enabled("debugLogInputs", True)

    def score_logs_enabled(self) -> bool:
        return self.enabled("debugLogScores", False)

    def summary_logs_enabled(self) -> bool:
        return self.enabled("debugLogSummary", True)


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

    def text_contains_any(self, text: str, phrases: set[str]):
        return any(phrase and phrase in text for phrase in phrases)

    def bot_name_alias_tokens(self):
        aliases = set()
        configured_aliases = self.config.get("nameAliases") or []
        for raw_name in (
            str(self.config.get("displayName", "mini-huan")),
            str(self.config.get("displayNameZh", "小幻")),
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
            any(ch in text for ch in ("?", "？"))
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
            str(self.config.get("displayNameZh", "小幻")).lower(),
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
            "bot_profile": {
                "name": str(self.config.get("displayName", "mini-huan")),
                "name_zh": str(self.config.get("displayNameZh", "小幻")),
                "name_aliases": self.configured_name_aliases(),
                "persona": ((self.config.get("botStyle") or {}).get("persona") or "Minecraft public-chat helper"),
            },
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
                "name": str(self.config.get("displayName", "mini-huan")),
                "name_zh": str(self.config.get("displayNameZh", "小幻")),
                "name_aliases": self.configured_name_aliases(),
                "persona": ((self.config.get("botStyle") or {}).get("persona") or "Minecraft public-chat helper"),
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


class AgentInvoker:
    def __init__(self, config: dict, state: BridgeState):
        self.config = config
        self.state = state

    def call_prompt(self, payload: dict, prompt_path: str):
        helper_script = self.config.get("helperScriptPath", DEFAULT_HELPER_SCRIPT)
        python_exe = self.config.get("pythonPath", DEFAULT_PYTHON)
        config_path = self.config.get("configPath", str(DEFAULT_CONFIG_PATH))
        timeout_seconds = max(1, int(self.config.get("agentTimeoutSeconds", DEFAULT_TIMEOUT)))
        process_timeout = timeout_seconds + DEFAULT_SUBPROCESS_TIMEOUT_BUFFER
        if not os.path.exists(helper_script):
            raise RuntimeError(f"helper script not found: {helper_script}")
        if not os.path.exists(python_exe):
            raise RuntimeError(f"python not found: {python_exe}")
        if not os.path.exists(prompt_path):
            raise RuntimeError(f"prompt file not found: {prompt_path}")

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp_task:
            json.dump(payload, tmp_task, ensure_ascii=False)
            task_json_path = tmp_task.name
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp_out:
            out_json_path = tmp_out.name
        try:
            command = [
                python_exe,
                helper_script,
                self.config.get("agentId", DEFAULT_AGENT),
                str(timeout_seconds),
                task_json_path,
                config_path,
                out_json_path,
                prompt_path,
            ]
            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=process_timeout,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"mc-helper invoke timed out after {process_timeout}s")
            if proc.returncode != 0:
                stderr = (proc.stderr or "").encode("ascii", "backslashreplace").decode("ascii")
                stdout = (proc.stdout or "").encode("ascii", "backslashreplace").decode("ascii")
                raise RuntimeError(stderr.strip() or stdout.strip() or f"mc-helper invoke failed: {proc.returncode}")
            result = json.loads(Path(out_json_path).read_text(encoding="utf-8").strip())
            new_session_id = result.get("sessionId")
            self.state.set_session_id(new_session_id or "")
            return (result.get("reply") or "").strip(), result
        finally:
            for path in (task_json_path, out_json_path):
                try:
                    os.remove(path)
                except OSError:
                    pass


class JudgePipeline:
    def __init__(self, config: dict, state: BridgeState):
        self.config = config
        self.state = state

    def recent_bot_capability_refusal(self, judge_context: dict):
        recent_bot_messages = list((judge_context or {}).get("recent_bot_messages") or [])
        if not recent_bot_messages:
            return False
        last_bot_message = recent_bot_messages[-1]
        if int(last_bot_message.get("seconds_ago") or 999999) > 90:
            return False
        text = str(last_bot_message.get("text") or "").lower()
        return any(marker in text for marker in CAPABILITY_REFUSAL_MARKERS)

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
            any(ch in raw_text for ch in ("?", "？"))
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
        return self.has_direct_request_shape(message) or any(
            hint in (message or "")
            for hint in DIRECT_REQUEST_HINTS_ZH
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
        if any(marker in lower_text for marker in PRIVATE_REQUEST_MARKERS):
            return ("privacy_refusal", "private server details request")
        if any(marker in lower_text for marker in MEMORY_LIMIT_REQUEST_MARKERS):
            return ("memory_limit_refusal", "older message recall request")
        if any(marker in lower_text for marker in CAPABILITY_REQUEST_MARKERS):
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
            return {"should_reply": False, "confidence": 0.0, "reason": default_reason, "target_player": event.get("player") or "", "topic": ""}
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return {"should_reply": False, "confidence": 0.0, "reason": default_reason, "target_player": event.get("player") or "", "topic": "", "raw": raw_text}
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


class MinecraftDelivery:
    def __init__(self, config: dict):
        self.config = config

    def send_reply(self, reply: str):
        rcon_script = self.config.get("rconScriptPath", DEFAULT_RCON_SCRIPT)
        rcon_timeout = max(1.0, float(self.config.get("rconTimeoutSeconds", DEFAULT_RCON_TIMEOUT)))
        if not self.config.get("sendToMinecraft", False):
            return {"sent": False, "reason": "disabled"}
        if not os.path.exists(rcon_script):
            raise RuntimeError(f"rcon script not found: {rcon_script}")
        reply_mode = str(self.config.get("replyMode", "say"))
        display_name = str(self.config.get("displayName", "mini-huan"))
        name_color = str(self.config.get("nameColor", "aqua"))
        content_color = str(self.config.get("contentColor", "white"))
        if reply_mode == "tellraw_all":
            payload = [
                {"text": "<", "color": content_color},
                {"text": display_name, "color": name_color},
                {"text": "> ", "color": content_color},
                {"text": reply, "color": content_color},
            ]
            command_text = "tellraw @a " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        else:
            command_text = f"say {reply}"
        try:
            proc = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", rcon_script, "-Command", command_text],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=rcon_timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"RCON send timed out after {rcon_timeout:g}s")
        if proc.returncode != 0:
            stderr = (proc.stderr or "").encode("ascii", "backslashreplace").decode("ascii")
            stdout = (proc.stdout or "").encode("ascii", "backslashreplace").decode("ascii")
            raise RuntimeError(stderr.strip() or stdout.strip() or f"RCON send failed: {proc.returncode}")
        return {"sent": True, "stdout": (proc.stdout or "").strip()}
