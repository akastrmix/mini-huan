#!/usr/bin/env python3
"""Config defaults and loading helpers for the Minecraft bridge."""

import json
from pathlib import Path

from bridge_components import (
    BASE_DIR,
    DEFAULT_AGENT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_GLOBAL_COOLDOWN,
    DEFAULT_JUDGE_PROMPT,
    DEFAULT_MAX_MESSAGE_CHARS,
    DEFAULT_PLAYER_COOLDOWN,
    DEFAULT_REPLY_PROMPT,
    DEFAULT_RCON_SCRIPT,
    DEFAULT_RCON_TIMEOUT,
    DEFAULT_TIMEOUT,
)


def default_config():
    return {
        "helperScriptPath": str(BASE_DIR / "scripts" / "invoke_mc_helper.py"),
        "pythonPath": r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe",
        "configPath": str(DEFAULT_CONFIG_PATH),
        "rconScriptPath": DEFAULT_RCON_SCRIPT,
        "promptPath": DEFAULT_REPLY_PROMPT,
        "judgePromptPath": DEFAULT_JUDGE_PROMPT,
        "helperWorkspacePath": r"C:\Users\Administrator\.openclaw\workspace-mc-helper",
        "sendToMinecraft": False,
        "replyMode": "tellraw_all",
        "displayName": "mini-huan",
        "displayNameZh": "\u5c0f\u5e7b",
        "nameAliases": ["huan"],
        "nameColor": "aqua",
        "contentColor": "white",
        "agentId": DEFAULT_AGENT,
        "globalCooldownSeconds": DEFAULT_GLOBAL_COOLDOWN,
        "playerCooldownSeconds": DEFAULT_PLAYER_COOLDOWN,
        "maxMessageChars": DEFAULT_MAX_MESSAGE_CHARS,
        "maxReplyChars": 80,
        "agentTimeoutSeconds": DEFAULT_TIMEOUT,
        "rconTimeoutSeconds": DEFAULT_RCON_TIMEOUT,
        "languageHint": "reply in Chinese when the player speaks Chinese, otherwise match the player's language",
        "recentEventCacheSize": 200,
        "judgeRecentChatCount": 20,
        "judgePlayerHistoryCount": 6,
        "judgeRecentBotCount": 4,
        "replyRecentChatCount": 12,
        "replyPlayerHistoryCount": 5,
        "replyRecentBotCount": 3,
        "contextRecentTailReserve": 8,
        "contextMaxAgeSeconds": 900,
        "humanAnswerLookbackCount": 8,
        "judgeConfidenceThreshold": 0.72,
        "judgeSoftThreshold": 0.58,
        "maxBotConsecutiveReplies": 4,
        "followupReplyWindowSeconds": 180,
        "maxSamePlayerConversationReplies": 20,
        "botReplyStreakResetSeconds": 180,
        "recentChatStateSize": 60,
        "recentBotReplyStateSize": 12,
        "playerHistoryStateSize": 12,
        "allowAppreciationReplies": True,
        "debugLogInputs": True,
        "debugLogScores": False,
        "debugLogSummary": True,
        "botStyle": {
            "persona": "Minecraft public-chat helper",
            "tone": "casual, concise, useful",
            "maxSentences": 1,
            "preferDirectIdentityAnswers": True,
            "greetingStyle": "short and natural",
            "avoid": [
                "markdown",
                "bullet points",
                "roleplay narration",
                "overly long replies",
            ],
        },
    }


def load_config(path: Path):
    config = default_config()
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config
