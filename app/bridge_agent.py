#!/usr/bin/env python3
"""Agent invocation helpers."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from bridge_shared import (
    DEFAULT_AGENT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_HELPER_SCRIPT,
    DEFAULT_PYTHON,
    DEFAULT_SUBPROCESS_TIMEOUT_BUFFER,
    DEFAULT_TIMEOUT,
)
from bridge_state import BridgeState


class AgentInvoker:
    def __init__(self, config: dict, state: BridgeState):
        self.config = config
        self.state = state

    def call_prompt(self, payload: dict, prompt_path: str):
        return self._call_prompt(payload, prompt_path)

    def call_prompt_session(self, payload: dict, prompt_path: str, *, session_id: str = ""):
        return self._call_prompt(payload, prompt_path, session_id=session_id)

    def _call_prompt(self, payload: dict, prompt_path: str, *, session_id: str = ""):
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
            if session_id:
                command.append(str(session_id))
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
            return (result.get("reply") or "").strip(), result
        finally:
            for path in (task_json_path, out_json_path):
                try:
                    os.remove(path)
                except OSError:
                    pass
