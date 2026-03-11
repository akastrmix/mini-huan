#!/usr/bin/env python3
"""Config defaults and loading helpers for the Minecraft bridge."""

import copy
import json
from pathlib import Path

from bridge_components import (
    BASE_DIR,
    DEFAULT_AGENT,
    DEFAULT_ASSIST_PROMPT,
    DEFAULT_COMMAND_PROMPT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_GLOBAL_COOLDOWN,
    DEFAULT_FULL_AGENT_PROMPT,
    DEFAULT_JUDGE_PROMPT,
    DEFAULT_MAX_MESSAGE_CHARS,
    DEFAULT_MODE_SESSION_WINDOWS,
    DEFAULT_PLAYER_COOLDOWN,
    DEFAULT_PRIVILEGED_COMMAND_MAX_COMMANDS_PER_ROUND,
    DEFAULT_PRIVILEGED_COMMAND_MAX_ROUNDS,
    DEFAULT_PRIVILEGED_COMMAND_RESULT_MAX_CHARS,
    DEFAULT_REPLY_PROMPT,
    DEFAULT_RCON_SCRIPT,
    DEFAULT_RCON_TIMEOUT,
    DEFAULT_ROUTER_CONFIDENCE_THRESHOLD,
    DEFAULT_ROUTER_PROMPT,
    DEFAULT_TIMEOUT,
    DEFAULT_AUTH,
)


def default_config():
    return {
        "helperScriptPath": str(BASE_DIR / "scripts" / "invoke_mc_helper.py"),
        "pythonPath": r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe",
        "configPath": str(DEFAULT_CONFIG_PATH),
        "rconScriptPath": DEFAULT_RCON_SCRIPT,
        "promptPath": DEFAULT_REPLY_PROMPT,
        "judgePromptPath": DEFAULT_JUDGE_PROMPT,
        "routerPromptPath": DEFAULT_ROUTER_PROMPT,
        "assistPromptPath": DEFAULT_ASSIST_PROMPT,
        "commandPromptPath": DEFAULT_COMMAND_PROMPT,
        "fullAgentPromptPath": DEFAULT_FULL_AGENT_PROMPT,
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
        "routerConfidenceThreshold": DEFAULT_ROUTER_CONFIDENCE_THRESHOLD,
        "modeSessionWindowSeconds": dict(DEFAULT_MODE_SESSION_WINDOWS),
        "privilegedCommandMaxRounds": DEFAULT_PRIVILEGED_COMMAND_MAX_ROUNDS,
        "privilegedCommandMaxCommandsPerRound": DEFAULT_PRIVILEGED_COMMAND_MAX_COMMANDS_PER_ROUND,
        "privilegedCommandResultMaxChars": DEFAULT_PRIVILEGED_COMMAND_RESULT_MAX_CHARS,
        "recentEventCacheSize": 200,
        "judgeRecentChatCount": 20,
        "judgePlayerHistoryCount": 6,
        "judgeRecentBotCount": 4,
        "replyRecentChatCount": 12,
        "replyPlayerHistoryCount": 5,
        "replyRecentBotCount": 3,
        "contextRecentTailReserve": 8,
        "contextMaxAgeSeconds": 900,
        "judgeConfidenceThreshold": 0.72,
        "judgeSoftThreshold": 0.58,
        "maxBotConsecutiveReplies": 8,
        "followupReplyWindowSeconds": 180,
        "maxSamePlayerConversationReplies": 20,
        "botReplyStreakResetSeconds": 180,
        "recentChatStateSize": 60,
        "recentBotReplyStateSize": 12,
        "playerHistoryStateSize": 12,
        "allowAppreciationReplies": True,
        "auth": copy.deepcopy(DEFAULT_AUTH),
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


def merge_config(base: dict, overrides: dict):
    merged = dict(base)
    for key, value in dict(overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path):
    config = default_config()
    if path.exists():
        config = merge_config(config, json.loads(path.read_text(encoding="utf-8")))
    return config
