#!/usr/bin/env python3
"""Bridge state persistence helpers."""

import json
import os
import tempfile
import time
from pathlib import Path

from bridge_shared import DEFAULT_BOT_REPLY_STREAK_RESET


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
        serialized = json.dumps(self.data, ensure_ascii=False, indent=2)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                delete=False,
                dir=self.path.parent,
                prefix=f"{self.path.name}.",
                suffix=".tmp",
                encoding="utf-8",
            ) as tmp_file:
                tmp_file.write(serialized)
                tmp_file.flush()
                temp_path = Path(tmp_file.name)
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

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

    def record_delivery(
        self,
        *,
        player: str,
        reply: str,
        display_name: str,
        timestamp: float,
        recent_chat_limit: int,
        recent_bot_limit: int,
        player_history_limit: int,
    ):
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
