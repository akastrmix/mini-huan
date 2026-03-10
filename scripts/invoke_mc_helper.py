#!/usr/bin/env python3
"""Python-only helper for calling the mc-helper OpenClaw agent.

Why this exists:
- keeps the core agent invocation path out of PowerShell
- flattens the prompt into a single line before CLI handoff
- records the last raw stdout/stderr capture for debugging
"""

import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OPENCLAW_CMD = r"C:\Users\Administrator\AppData\Roaming\npm\openclaw.cmd"
DEBUG_PATH = BASE_DIR / "runtime" / "last_invoke_debug.txt"
PROCESS_TIMEOUT_BUFFER_SECONDS = 15


def parse_json_maybe(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def extract_agent_error_message(raw_text: str):
    text = (raw_text or "").strip()
    if not text:
        return ""
    parsed = parse_json_maybe(text)
    if isinstance(parsed, dict):
        if parsed.get("type") == "error" and parsed.get("error"):
            message = ((parsed.get("error") or {}).get("message") or "").strip()
            return message or text
        if parsed.get("error"):
            message = ((parsed.get("error") or {}).get("message") or "").strip()
            return message or text
    if text.startswith("Codex error:"):
        suffix = text.split(":", 1)[1].strip()
        parsed_suffix = parse_json_maybe(suffix)
        if isinstance(parsed_suffix, dict) and parsed_suffix.get("error"):
            message = ((parsed_suffix.get("error") or {}).get("message") or "").strip()
            return message or text
        return text
    return ""


def write_debug(
    prompt_path: str,
    task_payload: dict,
    proc: subprocess.CompletedProcess[str] | None,
    *,
    helper_workspace: str = "",
    stderr: str = "",
):
    rc = "" if proc is None else str(proc.returncode)
    stdout = "" if proc is None else (proc.stdout or "")
    stderr_text = stderr or ("" if proc is None else (proc.stderr or ""))
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.write_text(
        "RC="
        + rc
        + "\nPROMPT_PATH=\n"
        + str(prompt_path)
        + "\n\nHELPER_WORKSPACE=\n"
        + str(helper_workspace or "")
        + "\n\nTASK=\n"
        + json.dumps(task_payload, ensure_ascii=False, indent=2)
        + "\n\nSTDOUT=\n"
        + stdout
        + "\n\nSTDERR=\n"
        + stderr_text,
        encoding="utf-8",
    )


def resolve_helper_workspace(config: dict):
    helper_workspace = str(config.get("helperWorkspacePath") or "").strip()
    if not helper_workspace:
        return None
    workspace_path = Path(helper_workspace)
    if not workspace_path.exists():
        raise SystemExit(f"helper workspace not found: {workspace_path}")
    return str(workspace_path)


def main():
    if len(sys.argv) not in {7, 8}:
        raise SystemExit(
            "usage: invoke_mc_helper.py <agentId> <timeoutSeconds> <taskJsonFile> <configFile> <outFile> <promptPath> [sessionId]"
        )

    agent_id, timeout_seconds, task_json_file, config_file, out_file, prompt_path = sys.argv[1:7]
    session_id = sys.argv[7] if len(sys.argv) == 8 else ""
    task_payload = json.loads(Path(task_json_file).read_text(encoding="utf-8"))
    config = json.loads(Path(config_file).read_text(encoding="utf-8"))
    prompt_text = Path(prompt_path).read_text(encoding="utf-8")
    prompt_text = " ".join(prompt_text.split())
    helper_workspace = resolve_helper_workspace(config)

    prompt = f"{prompt_text} TASK=" + json.dumps(task_payload, ensure_ascii=False, separators=(",", ":"))
    timeout_seconds_int = max(1, int(timeout_seconds))

    cmd = [
        OPENCLAW_CMD,
        "agent",
        "--agent",
        agent_id,
        "--message",
        prompt,
        "--json",
        "--timeout",
        str(timeout_seconds_int),
    ]
    if session_id:
        cmd.extend(["--session-id", session_id])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds_int + PROCESS_TIMEOUT_BUFFER_SECONDS,
            cwd=helper_workspace,
        )
    except subprocess.TimeoutExpired:
        write_debug(
            prompt_path,
            task_payload,
            None,
            helper_workspace=helper_workspace or "",
            stderr=f"openclaw agent timed out after {timeout_seconds_int + PROCESS_TIMEOUT_BUFFER_SECONDS}s",
        )
        raise SystemExit(f"openclaw agent timed out after {timeout_seconds_int + PROCESS_TIMEOUT_BUFFER_SECONDS}s")

    write_debug(prompt_path, task_payload, proc, helper_workspace=helper_workspace or "")
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout or f"openclaw agent failed: {proc.returncode}")

    raw = (proc.stdout or "").strip()
    text = ""
    session = ""
    data = parse_json_maybe(raw)
    if data is None:
        text = raw
    else:
        error_message = extract_agent_error_message(raw)
        if error_message:
            raise SystemExit(f"openclaw agent returned an error payload: {error_message}")
        payloads = ((data.get("result") or {}).get("payloads") or [])
        text = ((payloads[0].get("text") if payloads else "") or "").strip()
        session = (((data.get("result") or {}).get("meta") or {}).get("agentMeta") or {}).get("sessionId") or ""

    error_message = extract_agent_error_message(text)
    if error_message:
        raise SystemExit(f"openclaw agent returned an error reply: {error_message}")

    Path(out_file).write_text(json.dumps({"reply": text, "sessionId": session}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
