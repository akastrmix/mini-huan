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
