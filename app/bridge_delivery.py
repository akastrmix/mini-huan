#!/usr/bin/env python3
"""Minecraft RCON delivery helpers."""

import json
import os
import subprocess

from bridge_shared import DEFAULT_RCON_SCRIPT, DEFAULT_RCON_TIMEOUT


class MinecraftDelivery:
    def __init__(self, config: dict):
        self.config = config

    def send_reply(self, reply: str):
        return self.send_formatted_reply(reply)

    def send_private_reply(self, player: str, reply: str):
        return self.send_formatted_reply(reply, target_player=player)

    def send_command(self, command_text: str):
        rcon_script = self.config.get("rconScriptPath", DEFAULT_RCON_SCRIPT)
        rcon_timeout = max(1.0, float(self.config.get("rconTimeoutSeconds", DEFAULT_RCON_TIMEOUT)))
        if not self.config.get("sendToMinecraft", False):
            return {"sent": False, "reason": "disabled"}
        if not os.path.exists(rcon_script):
            raise RuntimeError(f"rcon script not found: {rcon_script}")
        normalized_command = str(command_text or "").strip()
        if not normalized_command:
            raise RuntimeError("empty RCON command")
        if normalized_command.startswith("/"):
            normalized_command = normalized_command[1:].strip()
        try:
            proc = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", rcon_script, "-Command", normalized_command],
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
        return {"sent": True, "command": normalized_command, "stdout": (proc.stdout or "").strip()}

    def send_formatted_reply(self, reply: str, *, target_player: str | None = None):
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
            target = str(target_player or "").strip() or "@a"
            command_text = "tellraw " + target + " " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        else:
            command_text = f"say {reply}"
        return self.send_command(command_text)
