#!/usr/bin/env python3
"""Privilege routing, auth resolution, and structured result parsing."""

import json
import re
import subprocess

from bridge_shared import (
    DEFAULT_MODE_SESSION_WINDOWS,
    DEFAULT_ROUTER_CONFIDENCE_THRESHOLD,
    MODE_ASSIST,
    MODE_CHAT,
    MODE_COMMAND,
    MODE_FULL_AGENT,
    MODE_ORDER,
    PRIVILEGED_MODES,
)

ALLOWED_ROUTER_ACTIONS = {"none", "enter", "continue", "exit"}
ALLOWED_EXECUTION_STATUSES = {"completed", "denied", "needs_clarification", "failed"}
CAPABILITY_TO_MODE = {
    "chat": MODE_CHAT,
    "light_assist": MODE_ASSIST,
    "assist": MODE_ASSIST,
    "mc_command_exec": MODE_COMMAND,
    "command": MODE_COMMAND,
    "privileged_agent": MODE_FULL_AGENT,
    "full_agent": MODE_FULL_AGENT,
}
PRIVATE_REQUEST_HINTS_EN = (
    "private",
    "dm me",
    "pm me",
    "tell me privately",
    "whisper",
    "quietly",
)
PRIVATE_REQUEST_HINTS_ZH = (
    "私聊",
    "悄悄",
    "偷偷",
    "别让别人看见",
    "小窗",
)
EXIT_HINTS_EN = (
    "stop",
    "cancel",
    "never mind",
    "end this",
    "that's all",
)
EXIT_HINTS_ZH = (
    "停下",
    "停止",
    "算了",
    "结束",
    "先这样",
    "不用了",
)
FULL_AGENT_HINTS_EN = (
    "file",
    "files",
    "log",
    "logs",
    "script",
    "scripts",
    "code",
    "browser",
    "website",
    "folder",
    "directory",
    "computer",
    "terminal",
    "shell",
    "process",
    "workspace",
    "openclaw",
)
FULL_AGENT_HINTS_ZH = (
    "文件",
    "日志",
    "脚本",
    "代码",
    "浏览器",
    "网页",
    "文件夹",
    "目录",
    "电脑",
    "终端",
    "进程",
    "工作区",
    "配置",
    "重启bridge",
    "重启桥",
)
COMMAND_HINTS_EN = (
    "/",
    "gamemode",
    "creative",
    "survival",
    "spectator",
    "op ",
    " give ",
    "give me",
    "diamond",
    "diamonds",
    "netherite",
    "weather",
    "time set",
    "teleport",
    "tp ",
    "ban ",
    "whitelist",
    "summon",
    "setblock",
    "fill ",
)
COMMAND_HINTS_ZH = (
    "创造",
    "生存",
    "旁观",
    "给我",
    "来一组",
    "一组",
    "钻石",
    "下界合金",
    "天气",
    "时间",
    "传送",
    "封禁",
    "白名单",
    "召唤",
    "方块",
)
ASSIST_HINTS_EN = (
    "help me",
    "bring me",
    "tp me",
    "teleport me",
    "kill me",
    "clear nearby",
    "kill nearby",
    "give me",
    "feed me",
    "heal me",
    "spawn",
    "home",
    "nearby",
    "zombie",
    "skeleton",
    "creeper",
)
ASSIST_HINTS_ZH = (
    "帮我",
    "给我",
    "把我",
    "传送我",
    "送我",
    "杀我",
    "附近",
    "僵尸",
    "骷髅",
    "苦力怕",
    "回出生点",
    "回家",
    "回到",
    "吃的",
    "清一下",
)
GREETING_HINTS_EN = ("hi", "hello", "hey", "yo")
GREETING_HINTS_ZH = ("你好", "嗨", "在吗", "小幻")
RAW_COMMAND_RE = re.compile(r"^\s*/([^\s].*)$")


def normalize_mode(value: str | None):
    text = str(value or "").strip().lower()
    if text in MODE_ORDER:
        return text
    return MODE_CHAT


def mode_rank(mode: str | None):
    return int(MODE_ORDER.get(normalize_mode(mode), 0))


def clamp_mode(mode: str | None, max_mode: str | None):
    mode_name = normalize_mode(mode)
    max_mode_name = normalize_mode(max_mode)
    if mode_rank(mode_name) <= mode_rank(max_mode_name):
        return mode_name
    return max_mode_name


def group_max_mode(group_config):
    if not isinstance(group_config, dict):
        return MODE_CHAT
    explicit_mode = group_config.get("max_mode")
    if explicit_mode:
        return normalize_mode(explicit_mode)

    highest = MODE_CHAT
    for capability in list(group_config.get("capabilities") or []):
        capability_mode = CAPABILITY_TO_MODE.get(str(capability or "").strip().lower())
        if capability_mode and mode_rank(capability_mode) > mode_rank(highest):
            highest = capability_mode
    return highest


def resolve_player_auth(config: dict, player: str):
    auth_config = dict(config.get("auth") or {})
    groups_config = dict(auth_config.get("groups") or {})
    players_config = dict(auth_config.get("players") or {})

    assigned_groups = list(players_config.get(player) or players_config.get(str(player or "").lower()) or [])
    if not assigned_groups:
        assigned_groups = ["default"]

    max_mode = MODE_CHAT
    normalized_groups = []
    for raw_group in assigned_groups:
        group_name = str(raw_group or "").strip()
        if not group_name:
            continue
        normalized_groups.append(group_name)
        group_mode = group_max_mode(groups_config.get(group_name))
        if mode_rank(group_mode) > mode_rank(max_mode):
            max_mode = group_mode

    if not normalized_groups:
        normalized_groups = ["default"]
    return {
        "player": str(player or ""),
        "groups": normalized_groups,
        "max_mode": max_mode,
    }


def session_window_seconds(config: dict, mode: str):
    configured = dict(config.get("modeSessionWindowSeconds") or {})
    if mode in configured:
        try:
            return max(0, int(configured[mode]))
        except (TypeError, ValueError):
            return 0
    if configured.get("default") is not None:
        try:
            return max(0, int(configured["default"]))
        except (TypeError, ValueError):
            return 0
    return int(DEFAULT_MODE_SESSION_WINDOWS.get(mode, 0))


def parse_router_response(raw_text: str, *, player_auth: dict, active_session: dict | None, config: dict):
    default_mode = MODE_CHAT
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return {
            "mode": default_mode,
            "requested_mode": default_mode,
            "denied_by_permission": False,
            "confidence": 0.0,
            "enter_or_continue": "none",
            "private_requested": False,
            "topic": "",
            "reason": "",
        }

    parsed = None
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = None

    if not isinstance(parsed, dict):
        return {
            "mode": default_mode,
            "requested_mode": default_mode,
            "denied_by_permission": False,
            "confidence": 0.0,
            "enter_or_continue": "none",
            "private_requested": False,
            "topic": "",
            "reason": raw_text,
        }

    max_mode = normalize_mode((player_auth or {}).get("max_mode"))
    requested_mode = normalize_mode(parsed.get("requested_mode") or parsed.get("mode"))
    allowed_mode = clamp_mode(parsed.get("mode"), max_mode)
    denied_by_permission = bool(parsed.get("denied_by_permission"))
    if mode_rank(requested_mode) > mode_rank(max_mode):
        denied_by_permission = True
        allowed_mode = MODE_CHAT
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    threshold = float(config.get("routerConfidenceThreshold", DEFAULT_ROUTER_CONFIDENCE_THRESHOLD))
    if confidence < threshold and allowed_mode in PRIVILEGED_MODES:
        allowed_mode = MODE_CHAT

    action = str(parsed.get("enter_or_continue") or "none").strip().lower()
    if action not in ALLOWED_ROUTER_ACTIONS:
        action = "continue" if active_session and allowed_mode in PRIVILEGED_MODES else "none"

    if allowed_mode not in PRIVILEGED_MODES and action in {"enter", "continue"}:
        action = "none"

    return {
        "mode": allowed_mode,
        "requested_mode": requested_mode,
        "denied_by_permission": denied_by_permission,
        "confidence": confidence,
        "enter_or_continue": action,
        "private_requested": bool(parsed.get("private_requested", False)),
        "topic": str(parsed.get("topic") or "").strip(),
        "reason": str(parsed.get("reason") or "").strip(),
    }


def parse_execution_response(raw_text: str, *, mode: str):
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return {
            "status": "failed",
            "commands": [],
            "reply": "",
            "topic": "",
            "reason": "empty response",
            "mode": normalize_mode(mode),
        }

    parsed = None
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = None

    if not isinstance(parsed, dict):
        return {
            "status": "failed",
            "commands": [],
            "reply": raw_text,
            "topic": "",
            "reason": "non-json response",
            "mode": normalize_mode(mode),
        }

    status = str(parsed.get("status") or "failed").strip().lower()
    if status not in ALLOWED_EXECUTION_STATUSES:
        status = "failed"

    raw_commands = parsed.get("commands") or parsed.get("mc_commands") or []
    if isinstance(raw_commands, str):
        raw_commands = [raw_commands]
    commands = []
    for raw_command in list(raw_commands):
        command_text = str(raw_command or "").strip()
        if not command_text:
            continue
        if command_text.startswith("/"):
            command_text = command_text[1:].strip()
        if command_text:
            commands.append(command_text)

    return {
        "status": status,
        "commands": commands,
        "reply": str(parsed.get("reply") or "").strip(),
        "topic": str(parsed.get("topic") or "").strip(),
        "reason": str(parsed.get("reason") or "").strip(),
        "mode": normalize_mode(mode),
    }


def text_contains_any(message: str, english_markers=(), *, zh_markers=()):
    raw_text = str(message or "")
    lower_text = raw_text.lower()
    return any(marker in lower_text for marker in english_markers) or any(marker in raw_text for marker in zh_markers)


def message_mentions_bot_name(message: str, bot_profile: dict):
    lower_text = str(message or "").lower()
    names = [
        str(bot_profile.get("name") or "").strip().lower(),
        str(bot_profile.get("name_zh") or "").strip().lower(),
        *[str(item or "").strip().lower() for item in list(bot_profile.get("name_aliases") or [])],
    ]
    return any(name and name in lower_text for name in names)


def looks_like_followup(context: dict):
    current_player = str(((context or {}).get("current_message") or {}).get("player") or "")
    if not current_player:
        return False
    recent_chat = list((context or {}).get("recent_chat") or [])
    seen_current = False
    for entry in reversed(recent_chat):
        speaker = str(entry.get("speaker") or "")
        entry_type = str(entry.get("type") or "player")
        if not seen_current:
            if entry_type == "player" and speaker == current_player:
                seen_current = True
            continue
        if entry_type == "bot":
            return True
        if entry_type == "player" and speaker and speaker != current_player:
            return False
    return False


def local_router_fallback(context: dict, player_auth: dict, active_session: dict | None):
    message = str(((context or {}).get("current_message") or {}).get("text") or "")
    player_max_mode = normalize_mode((player_auth or {}).get("max_mode"))
    bot_profile = dict((context or {}).get("bot_profile") or {})
    named = message_mentions_bot_name(message, bot_profile)
    followup = looks_like_followup(context)
    private_requested = text_contains_any(message, PRIVATE_REQUEST_HINTS_EN, zh_markers=PRIVATE_REQUEST_HINTS_ZH)

    if text_contains_any(message, EXIT_HINTS_EN, zh_markers=EXIT_HINTS_ZH):
        requested_mode = normalize_mode((active_session or {}).get("mode") or player_max_mode)
        return {
            "mode": MODE_CHAT,
            "requested_mode": requested_mode,
            "denied_by_permission": False,
            "confidence": 0.95,
            "enter_or_continue": "exit",
            "private_requested": private_requested,
            "topic": "end active privileged session",
            "reason": "local router exit phrase",
        }

    if active_session:
        current_mode = normalize_mode((active_session or {}).get("mode"))
        if current_mode in PRIVILEGED_MODES:
            return {
                "mode": clamp_mode(current_mode, player_max_mode),
                "requested_mode": current_mode,
                "denied_by_permission": mode_rank(current_mode) > mode_rank(player_max_mode),
                "confidence": 0.92,
                "enter_or_continue": "continue",
                "private_requested": private_requested or bool((active_session or {}).get("private_requested", False)),
                "topic": str((active_session or {}).get("topic") or ""),
                "reason": "local router continued active session",
            }

    addressed = named or followup
    if not addressed and not str(message or "").strip().startswith("/"):
        return {
            "mode": MODE_CHAT,
            "requested_mode": MODE_CHAT,
            "denied_by_permission": False,
            "confidence": 0.72,
            "enter_or_continue": "none",
            "private_requested": private_requested,
            "topic": "",
            "reason": "local router no clear bot signal",
        }

    if text_contains_any(message, FULL_AGENT_HINTS_EN, zh_markers=FULL_AGENT_HINTS_ZH):
        requested_mode = MODE_FULL_AGENT
        allowed_mode = clamp_mode(requested_mode, player_max_mode)
        return {
            "mode": MODE_CHAT if allowed_mode != requested_mode else allowed_mode,
            "requested_mode": requested_mode,
            "denied_by_permission": allowed_mode != requested_mode,
            "confidence": 0.88,
            "enter_or_continue": "enter" if allowed_mode != MODE_CHAT else "none",
            "private_requested": private_requested,
            "topic": "external or computer-side task",
            "reason": "local router full-agent keywords",
        }

    if text_contains_any(message, COMMAND_HINTS_EN, zh_markers=COMMAND_HINTS_ZH):
        requested_mode = MODE_COMMAND if mode_rank(player_max_mode) >= mode_rank(MODE_COMMAND) else MODE_ASSIST
        allowed_mode = clamp_mode(requested_mode, player_max_mode)
        return {
            "mode": allowed_mode,
            "requested_mode": requested_mode,
            "denied_by_permission": False,
            "confidence": 0.84,
            "enter_or_continue": "enter" if allowed_mode in PRIVILEGED_MODES else "none",
            "private_requested": private_requested,
            "topic": "minecraft command-style request",
            "reason": "local router command keywords",
        }

    if text_contains_any(message, ASSIST_HINTS_EN, zh_markers=ASSIST_HINTS_ZH):
        requested_mode = MODE_ASSIST
        allowed_mode = clamp_mode(requested_mode, player_max_mode)
        return {
            "mode": allowed_mode,
            "requested_mode": requested_mode,
            "denied_by_permission": False,
            "confidence": 0.8,
            "enter_or_continue": "enter" if allowed_mode in PRIVILEGED_MODES else "none",
            "private_requested": private_requested,
            "topic": "minecraft assist request",
            "reason": "local router assist keywords",
        }

    if text_contains_any(message, GREETING_HINTS_EN, zh_markers=GREETING_HINTS_ZH):
        return {
            "mode": MODE_CHAT,
            "requested_mode": MODE_CHAT,
            "denied_by_permission": False,
            "confidence": 0.86,
            "enter_or_continue": "none",
            "private_requested": private_requested,
            "topic": "greeting",
            "reason": "local router greeting",
        }

    return {
        "mode": MODE_CHAT,
        "requested_mode": MODE_CHAT,
        "denied_by_permission": False,
        "confidence": 0.7,
        "enter_or_continue": "none",
        "private_requested": private_requested,
        "topic": "",
        "reason": "local router default chat",
    }


def local_privileged_execution_fallback(event: dict, route: dict, player_auth: dict, config: dict, active_session: dict | None = None):
    player = str(event.get("player") or "").strip()
    message = str(event.get("message") or "").strip()
    if not player or not message:
        return None

    raw_command_match = RAW_COMMAND_RE.match(message)
    if raw_command_match:
        return {
            "status": "completed",
            "commands": [raw_command_match.group(1).strip()],
            "reply": "好了。",
            "topic": "raw minecraft command",
            "reason": "local raw command fallback",
            "mode": normalize_mode(route.get("mode")),
        }

    planner_script = str(config.get("commandPlannerScriptPath") or "").strip()
    python_exe = str(config.get("pythonPath") or "").strip()
    if not planner_script or not python_exe:
        return None

    payload = {
        "player": player,
        "message": message,
        "mode": normalize_mode(route.get("mode")),
        "player_auth": dict(player_auth or {}),
        "last_execution": {
            "request_text": str((active_session or {}).get("last_request_text") or ""),
            "commands": list((active_session or {}).get("last_commands") or []),
            "reply_text": str((active_session or {}).get("last_reply_text") or ""),
            "topic": str((active_session or {}).get("topic") or ""),
        },
    }
    try:
        proc = subprocess.run(
            [python_exe, planner_script],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None

    planned = parse_execution_response(proc.stdout or "", mode=route.get("mode"))
    if planned.get("status") == "failed" and not planned.get("commands"):
        return None
    return planned
