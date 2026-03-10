#!/usr/bin/env python3
"""Main Minecraft -> mc-helper -> Minecraft bridge loop."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from bridge_config import load_config
from bridge_components import (
    DEFAULT_ASSIST_PROMPT,
    DEFAULT_COMMAND_PROMPT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_FULL_AGENT_PROMPT,
    DEFAULT_JUDGE_PROMPT,
    DEFAULT_MAX_MESSAGE_CHARS,
    DEFAULT_REPLY_PROMPT,
    DEFAULT_ROUTER_PROMPT,
    DEFAULT_STATE_PATH,
    DEFAULT_AGENT,
    AgentInvoker,
    BridgeState,
    ContextBuilder,
    JudgePipeline,
    Logger,
    MinecraftDelivery,
    local_privileged_execution_fallback,
    local_router_fallback,
    parse_execution_response,
    parse_router_response,
    resolve_player_auth,
)
from bridge_privileged import MODE_CHAT, PRIVILEGED_MODES
from mc_log_listener import open_log_file, parse_event

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class MCAIBridge:
    def __init__(self, config: dict, state: BridgeState):
        self.config = config
        self.state = state
        self.logger = Logger(config)
        self.context = ContextBuilder(config, state, self.logger)
        self.invoker = AgentInvoker(config, state)
        self.judge = JudgePipeline(config, state)
        self.delivery = MinecraftDelivery(config)

    def event_key(self, event: dict) -> str:
        return json.dumps({
            "type": event.get("type"),
            "player": event.get("player"),
            "message": event.get("message"),
            "raw": event.get("raw"),
        }, ensure_ascii=False, sort_keys=True)

    def is_duplicate_event(self, event: dict):
        return self.state.remember_event_key(
            self.event_key(event),
            int(self.config.get("recentEventCacheSize", 200)),
        )

    def append_chat_entry(self, speaker: str, text: str, entry_type: str, timestamp: float | None = None):
        self.state.append_chat_entry(
            speaker=speaker,
            text=text,
            entry_type=entry_type,
            recent_chat_limit=int(self.config.get("recentChatStateSize", 60)),
            player_history_limit=int(self.config.get("playerHistoryStateSize", 12)),
            recent_bot_limit=int(self.config.get("recentBotReplyStateSize", 12)),
            timestamp=timestamp,
        )

    def reset_bot_reply_streak(self):
        self.state.reset_bot_reply_streak()

    def mark_turn_without_reply(self):
        self.reset_bot_reply_streak()
        self.state.save()

    def should_attempt_judge(self, event: dict):
        if event.get("type") != "chat":
            return False, "skip-non-chat"
        player = event.get("player", "")
        message = (event.get("message") or "").strip()
        if not player or not message:
            return False, "skip-empty"
        if len(message) > int(self.config.get("maxMessageChars", DEFAULT_MAX_MESSAGE_CHARS)):
            return False, "skip-too-long"
        return True, "ok"

    def emit_summary(self, event: dict, stage: str, decision: dict | None = None, gate_reason: str | None = None):
        if not self.logger.summary_logs_enabled():
            return
        payload = {
            "bridge": f"{stage}_summary",
            "player": event.get("player"),
            "message": event.get("message"),
        }
        if decision is not None:
            payload.update({
                "should_reply": decision.get("should_reply"),
                "confidence": decision.get("confidence"),
                "reason": decision.get("reason"),
                "topic": decision.get("topic"),
            })
        if gate_reason is not None:
            payload["gate"] = gate_reason
        self.logger.emit(payload)

    def precheck_event(self, event: dict):
        if self.is_duplicate_event(event):
            return False, "skip-duplicate"
        ok, reason = self.should_attempt_judge(event)
        if not ok:
            return False, reason
        return True, "ok"

    def record_player_turn(self, event: dict):
        self.append_chat_entry(str(event.get("player") or ""), str(event.get("message") or ""), "player")
        self.state.save()

    def player_auth(self, event: dict):
        return resolve_player_auth(self.config, str(event.get("player") or ""))

    def active_player_session(self, event: dict):
        return self.state.active_player_session(
            self.config,
            str(event.get("player") or ""),
            now=time.time(),
        )

    def should_attempt_router(self, player_auth: dict, active_session: dict | None):
        return bool(active_session) or str((player_auth or {}).get("max_mode") or MODE_CHAT) != MODE_CHAT

    def run_router_stage(self, event: dict, player_auth: dict, active_session: dict | None):
        router_context = self.context.build_router_context(event, player_auth, active_session)
        if self.logger.input_logs_enabled():
            self.logger.emit({"bridge": "router_input", "event": event, "context": router_context})
        try:
            router_text, _ = self.invoker.call_prompt(
                router_context,
                str(self.config.get("routerPromptPath", DEFAULT_ROUTER_PROMPT)),
            )
        except Exception as exc:
            self.logger.emit({"bridge": "error", "stage": "router", "error": str(exc), "event": event})
            fallback_route = local_router_fallback(router_context, player_auth, active_session)
            self.logger.emit({"bridge": "router_local_fallback", "event": event, "route": fallback_route})
            return fallback_route, "ok"

        route = parse_router_response(
            router_text,
            player_auth=player_auth,
            active_session=active_session,
            config=self.config,
        )
        self.logger.emit({"bridge": "router", "event": event, "route": route})
        return route, "ok"

    def run_judge_stage(self, event: dict):
        judge_context = self.context.build_judge_context(event)
        if self.logger.input_logs_enabled():
            self.logger.emit({"bridge": "judge_input", "event": event, "context": judge_context})
        try:
            judge_text, _ = self.invoker.call_prompt(
                judge_context,
                str(self.config.get("judgePromptPath", DEFAULT_JUDGE_PROMPT)),
            )
            decision = self.judge.parse(judge_text, event)
            decision = self.judge.maybe_override_decline(event, decision, judge_context)
            decision = self.judge.apply_public_chat_guard(event, decision, judge_context)
        except Exception as exc:
            self.logger.emit({"bridge": "error", "stage": "judge", "error": str(exc), "event": event}, error=False)
            return None, None, "judge_error"

        passed, gate_reason = self.judge.gate(event, decision)
        self.logger.emit({"bridge": "judge", "event": event, "decision": decision, "gate": {"passed": passed, "why": gate_reason}})
        self.emit_summary(event, "judge", decision, gate_reason)
        if not passed:
            return decision, None, gate_reason
        return decision, judge_context, "passed"

    def run_reply_stage(self, event: dict, decision: dict):
        reply_context = self.context.build_reply_context(event, decision)
        if self.logger.input_logs_enabled():
            self.logger.emit({"bridge": "reply_input", "event": event, "decision": decision, "context": reply_context})
        try:
            reply, raw = self.invoker.call_prompt(
                reply_context,
                str(self.config.get("promptPath", DEFAULT_REPLY_PROMPT)),
            )
        except Exception as exc:
            self.logger.emit({"bridge": "error", "stage": "reply", "error": str(exc), "event": event})
            return None, None, "reply_error"

        reply = (reply or "").strip()
        if not reply or reply == "NO_REPLY":
            self.logger.emit({"bridge": "no_reply", "event": event, "raw": raw})
            return None, raw, "no_reply"
        if self.reply_looks_like_agent_error(reply):
            self.logger.emit({"bridge": "error", "stage": "reply_payload", "error": reply, "event": event})
            return None, raw, "reply_error"
        original_reply_length = len(reply)
        max_reply_chars = int(self.config.get("maxReplyChars", 80))
        if max_reply_chars > 0 and len(reply) > max_reply_chars:
            truncated = reply[:max_reply_chars].rstrip()
            reply = truncated or reply[:max_reply_chars]
            self.logger.emit(
                {
                    "bridge": "reply_truncated",
                    "event": event,
                    "decision": decision,
                    "max_chars": max_reply_chars,
                    "original_length": original_reply_length,
                    "sent_length": len(reply),
                },
                force=self.logger.summary_logs_enabled(),
            )
        return reply, raw, "ok"

    def reply_looks_like_agent_error(self, reply: str):
        text = (reply or "").strip()
        if not text:
            return False
        if text.startswith("Codex error:"):
            return True
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed, dict):
            return False
        if parsed.get("type") == "error" and parsed.get("error"):
            return True
        return bool(parsed.get("error"))

    def fallback_text(self, event: dict, *, chinese: str, english: str):
        message = str(event.get("message") or "")
        if any("\u4e00" <= ch <= "\u9fff" for ch in message):
            return chinese
        return english

    def permission_denied_decision(self, event: dict, route: dict):
        return {
            "should_reply": True,
            "confidence": max(0.84, float(route.get("confidence", 0.0) or 0.0)),
            "reason": "capability_refusal",
            "target_player": str(event.get("player") or ""),
            "topic": str(route.get("topic") or route.get("requested_mode") or "permission restricted"),
        }

    def prompt_path_for_mode(self, mode: str):
        if mode == "assist":
            return str(self.config.get("assistPromptPath", DEFAULT_ASSIST_PROMPT))
        if mode == "command":
            return str(self.config.get("commandPromptPath", DEFAULT_COMMAND_PROMPT))
        return str(self.config.get("fullAgentPromptPath", DEFAULT_FULL_AGENT_PROMPT))

    def finalize_outbound_reply(
        self,
        *,
        event: dict,
        reply: str,
        log_payload: dict,
        private_requested: bool = False,
    ):
        try:
            if private_requested:
                send_result = self.delivery.send_private_reply(str(event.get("player") or ""), reply)
            else:
                send_result = self.delivery.send_reply(reply)
        except Exception as exc:
            self.logger.emit({"bridge": "error", "stage": "delivery", "error": str(exc), "event": event, "reply": reply})
            return False
        now = time.time()
        self.state.record_delivery(
            player=str(event.get("player") or ""),
            reply=reply,
            display_name=str(self.config.get("displayName", "mini-huan")),
            timestamp=now,
            recent_chat_limit=int(self.config.get("recentChatStateSize", 60)),
            recent_bot_limit=int(self.config.get("recentBotReplyStateSize", 12)),
            player_history_limit=int(self.config.get("playerHistoryStateSize", 12)),
        )
        self.state.save()
        self.logger.emit({**dict(log_payload or {}), "delivery": send_result, "private": private_requested})
        return True

    def finalize_reply(self, event: dict, decision: dict, reply: str):
        self.logger.emit({
            "bridge": "reply_prepare",
            "event": event,
            "decision": decision,
            "reply": reply,
            "sessionId": self.state.session_id(),
        })
        success = self.finalize_outbound_reply(
            event=event,
            reply=reply,
            log_payload={
                "bridge": "reply",
                "event": event,
                "decision": decision,
                "reply": reply,
                "sessionId": self.state.session_id(),
            },
        )
        if not success:
            return False
        self.emit_summary(event, "reply", decision, "sent")
        return True

    def handle_permission_denied(self, event: dict, route: dict):
        decision = self.permission_denied_decision(event, route)
        reply, _raw, reply_status = self.run_reply_stage(event, decision)
        if reply_status != "ok":
            return False
        return self.finalize_reply(event, decision, reply)

    def run_privileged_stage(self, event: dict, player_auth: dict, route: dict, active_session: dict | None):
        mode = str(route.get("mode") or "")
        privileged_context = self.context.build_privileged_context(event, player_auth, route, active_session)
        if self.logger.input_logs_enabled():
            self.logger.emit({"bridge": f"{mode}_input", "event": event, "context": privileged_context})

        session_id = ""
        if active_session and str(active_session.get("mode") or "") == mode:
            session_id = str(active_session.get("session_id") or "")

        try:
            raw_text, raw_result = self.invoker.call_prompt_session(
                privileged_context,
                self.prompt_path_for_mode(mode),
                session_id=session_id,
            )
        except Exception as exc:
            self.logger.emit({"bridge": "error", "stage": mode, "error": str(exc), "event": event})
            return None, None, "privileged_error"

        execution = parse_execution_response(raw_text, mode=mode)
        if self.reply_looks_like_agent_error(execution.get("reply") or ""):
            self.logger.emit({"bridge": "error", "stage": f"{mode}_payload", "error": execution.get("reply"), "event": event})
            return None, raw_result, "privileged_error"
        self.logger.emit({"bridge": mode, "event": event, "route": route, "result": execution})
        return execution, raw_result, "ok"

    def finalize_privileged_result(self, event: dict, route: dict, execution: dict, raw_result: dict | None, active_session: dict | None):
        commands = list(execution.get("commands") or [])
        for command in commands:
            try:
                self.delivery.send_command(command)
            except Exception as exc:
                self.logger.emit({
                    "bridge": "error",
                    "stage": "command_delivery",
                    "error": str(exc),
                    "event": event,
                    "route": route,
                    "command": command,
                })
                return False

        session_topic = str(execution.get("topic") or route.get("topic") or "")
        reply = str(execution.get("reply") or "").strip()
        if not reply:
            if execution.get("status") == "completed" and commands:
                reply = self.fallback_text(
                    event,
                    chinese="好了。",
                    english="Done.",
                )
            elif execution.get("status") == "needs_clarification":
                reply = self.fallback_text(
                    event,
                    chinese="你再具体说一点，我再帮你做。",
                    english="Give me a bit more detail and I can do that.",
                )
            elif execution.get("status") == "denied":
                reply = self.fallback_text(
                    event,
                    chinese="这个我不方便直接帮你做。",
                    english="I should not do that directly.",
                )
            else:
                reply = self.fallback_text(
                    event,
                    chinese="这次没执行好，你再说一遍。",
                    english="That did not go through cleanly, try again.",
                )

        should_keep_session = execution.get("status") in {"completed", "denied", "needs_clarification"}
        if should_keep_session:
            self.state.activate_player_session(
                str(event.get("player") or ""),
                str(route.get("mode") or ""),
                session_id=str((raw_result or {}).get("sessionId") or (active_session or {}).get("session_id") or ""),
                topic=session_topic,
                private_requested=bool(route.get("private_requested", False) or ((active_session or {}).get("private_requested") and route.get("enter_or_continue") == "continue")),
                last_request_text=str(event.get("message") or ""),
                last_commands=commands,
                last_reply_text=reply,
                timestamp=time.time(),
            )
            self.state.save()

        private_requested = bool(route.get("private_requested", False) or ((active_session or {}).get("private_requested") and route.get("enter_or_continue") == "continue"))
        success = self.finalize_outbound_reply(
            event=event,
            reply=reply,
            private_requested=private_requested,
            log_payload={
                "bridge": "privileged_reply",
                "event": event,
                "route": route,
                "result": execution,
                "reply": reply,
                "sessionId": str((raw_result or {}).get("sessionId") or (active_session or {}).get("session_id") or ""),
            },
        )
        if not success:
            return False
        self.emit_summary(
            event,
            str(route.get("mode") or "privileged"),
            {
                "should_reply": True,
                "confidence": route.get("confidence", 1.0),
                "reason": str(execution.get("status") or route.get("reason") or ""),
                "topic": str(execution.get("topic") or route.get("topic") or ""),
            },
            "sent",
        )
        return True

    def handle_event(self, event: dict):
        ok, reason = self.precheck_event(event)
        if not ok:
            self.logger.emit({"bridge": "skip", "reason": reason, "event": event})
            if event.get("type") == "chat" and reason != "skip-duplicate":
                self.mark_turn_without_reply()
            return

        self.record_player_turn(event)
        player_auth = self.player_auth(event)
        active_session = self.active_player_session(event)

        if self.should_attempt_router(player_auth, active_session):
            route, router_status = self.run_router_stage(event, player_auth, active_session)
            if router_status != "ok" or route is None:
                self.logger.emit({"bridge": "router_fallback_to_chat", "event": event, "player_auth": player_auth})
            else:
                if route.get("enter_or_continue") == "exit":
                    self.state.clear_player_session(str(event.get("player") or ""))
                    self.state.save()
                    active_session = None
                if route.get("denied_by_permission"):
                    if not self.handle_permission_denied(event, route):
                        self.mark_turn_without_reply()
                    return
                if str(route.get("mode") or "") in PRIVILEGED_MODES:
                    execution, raw_result, privileged_status = self.run_privileged_stage(event, player_auth, route, active_session)
                    if privileged_status != "ok" or execution is None:
                        local_execution = None
                        if str(route.get("mode") or "") in {"assist", "command"}:
                            local_execution = local_privileged_execution_fallback(event, route, player_auth, self.config, active_session)
                        if local_execution is not None:
                            self.logger.emit({"bridge": "privileged_local_execution_fallback", "event": event, "route": route, "result": local_execution})
                            if not self.finalize_privileged_result(event, route, local_execution, {}, active_session):
                                self.mark_turn_without_reply()
                            return
                        self.logger.emit({"bridge": "privileged_fallback_to_chat", "event": event, "route": route})
                    else:
                        if not self.finalize_privileged_result(event, route, execution, raw_result, active_session):
                            self.mark_turn_without_reply()
                        return

        decision, _judge_context, judge_status = self.run_judge_stage(event)
        if judge_status != "passed":
            self.mark_turn_without_reply()
            return

        reply, _raw, reply_status = self.run_reply_stage(event, decision)
        if reply_status != "ok":
            self.mark_turn_without_reply()
            return

        if not self.finalize_reply(event, decision, reply):
            self.mark_turn_without_reply()


def follow_bridge(log_path: str, bridge: MCAIBridge, poll_interval: float, from_start: bool):
    start_from_end = not from_start
    while True:
        try:
            with open_log_file(log_path) as f:
                f.seek(0, os.SEEK_END if start_from_end else os.SEEK_SET)
                last_inode = os.fstat(f.fileno()).st_ino
                while True:
                    line = f.readline()
                    if line:
                        event = parse_event(line)
                        if event:
                            bridge.handle_event(event)
                        continue
                    time.sleep(poll_interval)
                    try:
                        stat = os.stat(log_path)
                    except FileNotFoundError:
                        break
                    if stat.st_ino != last_inode or stat.st_size < f.tell():
                        break
        except FileNotFoundError:
            print(json.dumps({"bridge": "wait", "log": log_path}, ensure_ascii=False), file=sys.stderr, flush=True)
            time.sleep(max(poll_interval, 1.0))
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            safe_error = str(exc).encode("ascii", "backslashreplace").decode("ascii")
            print(json.dumps({"bridge": "fatal", "error": safe_error}, ensure_ascii=True), file=sys.stderr, flush=True)
            time.sleep(max(poll_interval, 1.0))
        start_from_end = True
def main():
    parser = argparse.ArgumentParser(description="Bridge Minecraft chat events into the mc-helper OpenClaw agent.")
    parser.add_argument("logfile", help="Path to Minecraft logs/latest.log")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to bridge config JSON")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="Path to bridge state JSON")
    parser.add_argument("--from-start", action="store_true", help="Read the log from the beginning")
    parser.add_argument("--poll-interval", type=float, default=0.2, help="Polling interval in seconds")
    args = parser.parse_args()
    config = load_config(Path(args.config))
    state = BridgeState(Path(args.state))
    bridge = MCAIBridge(config=config, state=state)
    print(json.dumps({
        "bridge": "listen",
        "log": os.path.abspath(args.logfile),
        "agent": config.get("agentId", DEFAULT_AGENT),
        "helper_workspace": config.get("helperWorkspacePath") or "",
    }, ensure_ascii=False), flush=True)
    follow_bridge(os.path.abspath(args.logfile), bridge, max(args.poll_interval, 0.05), args.from_start)


if __name__ == "__main__":
    main()
