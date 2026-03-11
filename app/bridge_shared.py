#!/usr/bin/env python3
"""Shared bridge constants and text markers."""

import re
from pathlib import Path

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
DEFAULT_PRIVILEGED_COMMAND_MAX_ROUNDS = 3
DEFAULT_PRIVILEGED_COMMAND_MAX_COMMANDS_PER_ROUND = 3
DEFAULT_PRIVILEGED_COMMAND_RESULT_MAX_CHARS = 400
DEFAULT_HELPER_SCRIPT = str(BASE_DIR / "scripts" / "invoke_mc_helper.py")
DEFAULT_RCON_SCRIPT = r"C:\Users\Administrator\.openclaw\workspace\skills\mc-rcon-exec\scripts\send-rcon.ps1"
DEFAULT_PYTHON = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
DEFAULT_JUDGE_PROMPT = str(BASE_DIR / "config" / "judge_prompt.txt")
DEFAULT_REPLY_PROMPT = str(BASE_DIR / "config" / "reply_prompt.txt")
DEFAULT_ROUTER_PROMPT = str(BASE_DIR / "config" / "router_prompt.txt")
DEFAULT_ASSIST_PROMPT = str(BASE_DIR / "config" / "assist_prompt.txt")
DEFAULT_COMMAND_PROMPT = str(BASE_DIR / "config" / "command_prompt.txt")
DEFAULT_FULL_AGENT_PROMPT = str(BASE_DIR / "config" / "full_agent_prompt.txt")
DEFAULT_ROUTER_CONFIDENCE_THRESHOLD = 0.55
MODE_CHAT = "chat"
MODE_ASSIST = "assist"
MODE_COMMAND = "command"
MODE_FULL_AGENT = "full_agent"
MODE_ORDER = {
    MODE_CHAT: 0,
    MODE_ASSIST: 1,
    MODE_COMMAND: 2,
    MODE_FULL_AGENT: 3,
}
PRIVILEGED_MODES = {
    MODE_ASSIST,
    MODE_COMMAND,
    MODE_FULL_AGENT,
}
DEFAULT_MODE_SESSION_WINDOWS = {
    MODE_ASSIST: 180,
    MODE_COMMAND: 300,
    MODE_FULL_AGENT: 900,
}
DEFAULT_AUTH = {
    "groups": {
        "default": {"max_mode": MODE_CHAT},
        "assist": {"max_mode": MODE_ASSIST},
        "operator": {"max_mode": MODE_COMMAND},
        "owner": {"max_mode": MODE_FULL_AGENT},
    },
    "players": {},
}

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
    "^\\s*(yes|yeah|yep|no|nope|nah|true|false|correct|wrong|\u662f|\u4e0d\u662f|\u5bf9|\u4e0d\u5bf9|\u53ef\u4ee5|\u4e0d\u53ef\u4ee5|\u80fd|\u4e0d\u80fd|\u6709|\u6ca1\u6709|\u884c|\u4e0d\u884c|\u4f1a|\u4e0d\u4f1a)\\W*$",
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
CAPABILITY_REFUSAL_MARKERS_ZH = (
    "\u6211\u4e0d\u80fd",
    "\u6211\u4e0d\u53ef\u4ee5",
    "\u4e0d\u80fd\u6267\u884c",
    "\u4e0d\u80fd\u8fd0\u884c",
    "\u53ea\u80fd",
    "\u627e\u7ba1\u7406\u5458",
    "\u95ee\u7ba1\u7406\u5458",
    "\u7ba1\u7406\u5458\u53ef\u4ee5\u5e2e",
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
    "\u4f60\u80fd",
    "\u4f60\u53ef\u4ee5",
    "\u80fd\u4e0d\u80fd",
    "\u53ef\u4e0d\u53ef\u4ee5",
    "\u5e2e\u6211",
    "\u7ed9\u6211",
    "\u6765\u4e00\u4e2a",
    "\u6765\u4e00\u7ec4",
    "\u7ed9\u6211\u4e00\u4e2a",
    "\u7ed9\u6211\u4e00\u7ec4",
    "\u544a\u8bc9\u6211",
    "\u518d\u8bf4\u4e00\u904d",
    "\u91cd\u590d",
    "\u8bb0\u5f97",
    "\u8bb0\u4e0d\u8bb0\u5f97",
    "\u662f\u4ec0\u4e48",
    "\u662f\u8c01",
    "\u600e\u4e48",
    "\u5982\u4f55",
    "\u4e3a\u4ec0\u4e48",
    "\u591a\u5c11",
    "\u54ea\u91cc",
    "\u54ea\u513f",
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
PRIVATE_REQUEST_MARKERS_ZH = (
    "\u670d\u52a1\u5668ip",
    "\u670d\u52a1\u5668\u5730\u5740",
    "\u670d\u52a1\u5668\u7aef\u53e3",
)
MEMORY_LIMIT_REQUEST_MARKERS = (
    "repeat what i said",
    "what did i say",
    "what was my last message",
    "do you remember what i said",
    "repeat my last message",
    "repeat what i said last time",
)
MEMORY_LIMIT_REQUEST_MARKERS_ZH = (
    "\u91cd\u590d\u6211\u8bf4\u7684",
    "\u6211\u4e0a\u4e00\u53e5\u8bf4\u4e86\u4ec0\u4e48",
    "\u6211\u4e0a\u6b21\u8bf4\u4e86\u4ec0\u4e48",
    "\u4f60\u8bb0\u5f97\u6211\u8bf4\u8fc7\u4ec0\u4e48",
    "\u8bb0\u5f97\u6211\u521a\u624d\u8bf4\u7684",
    "\u4f60\u8bb0\u5f97\u6211\u521a\u624d\u8bf4\u4e86\u4ec0\u4e48",
    "\u6211\u521a\u624d\u8bf4\u4e86\u4ec0\u4e48",
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
CAPABILITY_REQUEST_MARKERS_ZH = (
    "\u8fd0\u884c\u547d\u4ee4",
    "\u6267\u884c\u547d\u4ee4",
    "\u7ed9\u6211op",
    "\u7ed9\u6211\u7ba1\u7406",
    "\u8ba9\u6211\u5f53\u7ba1\u7406",
    "\u7ed9\u6211\u521b\u9020",
    "\u4f20\u9001\u6211",
    "tp\u6211",
)
ANSWER_HINTS = {
    "\u662f",
    "\u53ef\u4ee5",
    "\u5e94\u8be5",
    "\u56e0\u4e3a",
    "\u76f4\u63a5",
    "\u5148",
    "\u7136\u540e",
    "\u9700\u8981",
    "\u7528",
    "\u53bb",
    "\u5728",
    "\u5c31\u662f",
    "\u53ef",
    "\u62ff",
    "you",
    "can",
    "use",
    "need",
    "just",
    "try",
    "go",
    "because",
    "then",
    "first",
}
QUESTION_HINTS_ZH = {
    "\u4ec0\u4e48",
    "\u600e\u4e48",
    "\u600e\u6837",
    "\u5982\u4f55",
    "\u8c01",
    "\u54ea",
    "\u54ea\u91cc",
    "\u54ea\u513f",
    "\u51e0",
    "\u591a\u5c11",
    "\u5417",
    "\u5462",
    "\u5427",
    "\u4e48",
    "\u662f\u4e0d\u662f",
    "\u6709\u6ca1\u6709",
    "\u80fd\u4e0d\u80fd",
    "\u53ef\u4e0d\u53ef\u4ee5",
    "\u8981\u4e0d\u8981",
    "\u884c\u4e0d\u884c",
    "\u5bf9\u5417",
}
YES_NO_QUESTION_HINTS_ZH = {
    "\u662f\u4e0d\u662f",
    "\u6709\u6ca1\u6709",
    "\u80fd\u4e0d\u80fd",
    "\u53ef\u4e0d\u53ef\u4ee5",
    "\u8981\u4e0d\u8981",
    "\u884c\u4e0d\u884c",
    "\u5bf9\u5417",
    "\u5417",
}
EXPLICIT_ANSWER_START_HINTS_ZH = {
    "\u662f",
    "\u4e0d\u662f",
    "\u5c31\u662f",
    "\u4f60\u662f",
    "\u5148",
    "\u7528",
    "\u53bb",
    "\u7136\u540e",
    "\u56e0\u4e3a",
    "\u76f4\u63a5",
}
EN_CONTENT_STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "for",
    "in",
    "on",
    "at",
    "is",
    "are",
    "am",
    "was",
    "were",
    "be",
    "being",
    "been",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "will",
    "have",
    "has",
    "had",
    "what",
    "whats",
    "what's",
    "who",
    "where",
    "when",
    "why",
    "how",
    "which",
    "tell",
    "me",
    "my",
    "your",
    "you",
    "i",
    "we",
    "they",
    "it",
    "this",
    "that",
    "please",
    "hey",
    "hi",
    "hello",
}
ZH_CONTENT_STOPWORDS = {
    "\u4ec0\u4e48",
    "\u600e\u4e48",
    "\u600e\u6837",
    "\u5982\u4f55",
    "\u5417",
    "\u5462",
    "\u5427",
    "\u4e48",
    "\u662f\u4e0d\u662f",
    "\u6709\u6ca1\u6709",
    "\u80fd\u4e0d\u80fd",
    "\u53ef\u4e0d\u53ef\u4ee5",
    "\u8981\u4e0d\u8981",
    "\u884c\u4e0d\u884c",
    "\u4e00\u4e2a",
}
