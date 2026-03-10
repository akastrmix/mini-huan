#!/usr/bin/env python3
"""Summarize bridge quality signals from JSONL runtime logs."""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATTERNS = [str(BASE_DIR / "runtime" / "logs" / "bridge.out*.log")]
DEFAULT_STATE_PATH = BASE_DIR / "runtime" / "mc_ai_bridge_state.json"


def expand_log_patterns(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen = set()
    for pattern in patterns:
        raw = Path(pattern)
        resolved_pattern = raw if raw.is_absolute() else (BASE_DIR / raw)
        matches = glob.glob(str(resolved_pattern))
        if not matches and resolved_pattern.exists():
            matches = [str(resolved_pattern)]
        for match in matches:
            path = Path(match).resolve()
            key = str(path).lower()
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            paths.append(path)
    return sorted(paths, key=lambda item: (item.stat().st_mtime, str(item)))


def load_json_records(paths: list[Path]) -> tuple[list[dict], int]:
    records: list[dict] = []
    invalid_lines = 0
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                invalid_lines += 1
                continue
            if isinstance(payload, dict):
                payload = dict(payload)
                payload["_source"] = str(path)
                records.append(payload)
            else:
                invalid_lines += 1
    return records, invalid_lines


def load_state(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def shorten(text: str, limit: int = 72) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def problem_sample_for_record(record: dict) -> dict | None:
    bridge = str(record.get("bridge") or "")
    event = dict(record.get("event") or {})
    player = str(event.get("player") or "")
    message = str(event.get("message") or "")
    source = Path(str(record.get("_source") or "")).name

    if bridge == "error":
        return {
            "kind": f"error/{record.get('stage') or 'unknown'}",
            "player": player,
            "message": shorten(message),
            "detail": shorten(record.get("error") or ""),
            "source": source,
        }
    if bridge == "judge":
        gate = dict(record.get("gate") or {})
        if gate.get("passed"):
            return None
        decision = dict(record.get("decision") or {})
        return {
            "kind": f"blocked/{gate.get('why') or 'unknown'}",
            "player": player,
            "message": shorten(message),
            "detail": shorten(decision.get("reason") or ""),
            "source": source,
        }
    if bridge == "no_reply":
        return {
            "kind": "no_reply",
            "player": player,
            "message": shorten(message),
            "detail": shorten(record.get("raw") or ""),
            "source": source,
        }
    if bridge == "reply_truncated":
        return {
            "kind": "reply_truncated",
            "player": player,
            "message": shorten(message),
            "detail": f"{record.get('original_length')}->{record.get('sent_length')} chars",
            "source": source,
        }
    return None


def build_quality_summary(
    log_paths: list[Path],
    records: list[dict],
    *,
    invalid_lines: int = 0,
    state: dict | None = None,
    limit_samples: int = 5,
) -> dict:
    state = dict(state or {})
    decision_reasons: Counter[str] = Counter()
    sent_reasons: Counter[str] = Counter()
    gate_reasons: Counter[str] = Counter()
    error_stages: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    confidences: list[float] = []
    reply_lengths: list[int] = []
    problem_samples: list[dict] = []

    judge_total = 0
    judge_passed = 0
    judge_blocked = 0
    replies_sent = 0
    no_reply = 0
    truncations = 0
    errors_total = 0

    for record in records:
        bridge = str(record.get("bridge") or "")
        sample = problem_sample_for_record(record)
        if sample is not None:
            problem_samples.append(sample)

        if bridge == "judge":
            judge_total += 1
            decision = dict(record.get("decision") or {})
            gate = dict(record.get("gate") or {})
            reason = str(decision.get("reason") or "unknown")
            decision_reasons[reason] += 1
            gate_reason = str(gate.get("why") or "unknown")
            gate_reasons[gate_reason] += 1
            try:
                confidences.append(float(decision.get("confidence", 0.0)))
            except (TypeError, ValueError):
                pass
            if gate.get("passed"):
                judge_passed += 1
            else:
                judge_blocked += 1
        elif bridge == "reply":
            replies_sent += 1
            decision = dict(record.get("decision") or {})
            sent_reasons[str(decision.get("reason") or "unknown")] += 1
            reply_lengths.append(len(str(record.get("reply") or "")))
        elif bridge == "error":
            errors_total += 1
            error_stages[str(record.get("stage") or "unknown")] += 1
        elif bridge == "no_reply":
            no_reply += 1
        elif bridge == "reply_truncated":
            truncations += 1
        elif bridge == "skip":
            skip_reasons[str(record.get("reason") or "unknown")] += 1

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    avg_reply_length = sum(reply_lengths) / len(reply_lengths) if reply_lengths else 0.0
    recent_bot_replies = list(state.get("recentBotReplies") or [])[-3:]

    return {
        "log_files": [str(path) for path in log_paths],
        "records_total": len(records),
        "invalid_lines": invalid_lines,
        "judge_total": judge_total,
        "judge_passed": judge_passed,
        "judge_blocked": judge_blocked,
        "judge_pass_rate": (judge_passed / judge_total) if judge_total else 0.0,
        "avg_confidence": avg_confidence,
        "replies_sent": replies_sent,
        "avg_reply_length": avg_reply_length,
        "no_reply": no_reply,
        "reply_truncations": truncations,
        "errors_total": errors_total,
        "decision_reasons": dict(decision_reasons.most_common()),
        "sent_reasons": dict(sent_reasons.most_common()),
        "gate_reasons": dict(gate_reasons.most_common()),
        "error_stages": dict(error_stages.most_common()),
        "skip_reasons": dict(skip_reasons.most_common()),
        "problem_samples": problem_samples[-limit_samples:],
        "state_snapshot": {
            "bot_reply_streak": int(state.get("botConsecutiveReplyCount", 0) or 0),
            "recent_bot_reply_count": len(list(state.get("recentBotReplies") or [])),
            "recent_bot_replies": [
                shorten(entry.get("text") or "", limit=80)
                for entry in recent_bot_replies
            ],
        },
    }


def render_quality_summary(summary: dict) -> str:
    lines = [
        "Bridge Quality Report",
        f"Log files: {len(summary.get('log_files') or [])}",
        f"Records parsed: {summary.get('records_total', 0)}",
        f"Invalid lines: {summary.get('invalid_lines', 0)}",
        "",
        "Judge",
        f"- total: {summary.get('judge_total', 0)}",
        f"- passed: {summary.get('judge_passed', 0)} ({summary.get('judge_pass_rate', 0.0):.1%})",
        f"- blocked: {summary.get('judge_blocked', 0)}",
        f"- avg confidence: {summary.get('avg_confidence', 0.0):.3f}",
        "",
        "Replies",
        f"- sent: {summary.get('replies_sent', 0)}",
        f"- avg length: {summary.get('avg_reply_length', 0.0):.1f}",
        f"- no_reply payloads: {summary.get('no_reply', 0)}",
        f"- truncations: {summary.get('reply_truncations', 0)}",
        "",
        "Errors",
        f"- total: {summary.get('errors_total', 0)}",
    ]

    if summary.get("decision_reasons"):
        lines.extend(["", "Decision reasons"])
        for key, value in summary["decision_reasons"].items():
            lines.append(f"- {key}: {value}")

    if summary.get("gate_reasons"):
        lines.extend(["", "Gate reasons"])
        for key, value in summary["gate_reasons"].items():
            lines.append(f"- {key}: {value}")

    if summary.get("sent_reasons"):
        lines.extend(["", "Sent reply reasons"])
        for key, value in summary["sent_reasons"].items():
            lines.append(f"- {key}: {value}")

    if summary.get("error_stages"):
        lines.extend(["", "Error stages"])
        for key, value in summary["error_stages"].items():
            lines.append(f"- {key}: {value}")

    if summary.get("skip_reasons"):
        lines.extend(["", "Skip reasons"])
        for key, value in summary["skip_reasons"].items():
            lines.append(f"- {key}: {value}")

    snapshot = dict(summary.get("state_snapshot") or {})
    lines.extend([
        "",
        "State snapshot",
        f"- bot streak: {snapshot.get('bot_reply_streak', 0)}",
        f"- stored recent bot replies: {snapshot.get('recent_bot_reply_count', 0)}",
    ])
    for reply in snapshot.get("recent_bot_replies") or []:
        lines.append(f"- recent reply: {reply}")

    samples = list(summary.get("problem_samples") or [])
    if samples:
        lines.extend(["", "Recent problem samples"])
        for sample in samples:
            lines.append(
                f"- {sample.get('kind')} | {sample.get('player') or '?'} | "
                f"{sample.get('message') or '(no message)'} | {sample.get('detail') or ''}"
            )

    return "\n".join(lines)


def generate_report(
    *,
    log_patterns: list[str] | None = None,
    state_path: str | Path | None = None,
    limit_samples: int = 5,
) -> dict:
    log_paths = expand_log_patterns(log_patterns or DEFAULT_LOG_PATTERNS)
    records, invalid_lines = load_json_records(log_paths)
    if state_path is not None:
        resolved_state_path = Path(state_path)
        if not resolved_state_path.is_absolute():
            resolved_state_path = BASE_DIR / resolved_state_path
    else:
        resolved_state_path = DEFAULT_STATE_PATH
    state = load_state(resolved_state_path)
    return build_quality_summary(
        log_paths,
        records,
        invalid_lines=invalid_lines,
        state=state,
        limit_samples=limit_samples,
    )


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Summarize bridge quality signals from runtime logs.")
    parser.add_argument(
        "--log",
        action="append",
        default=[],
        help="Log file path or glob pattern. May be passed multiple times. Defaults to runtime/logs/bridge.out*.log",
    )
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_PATH),
        help="Optional bridge state JSON path.",
    )
    parser.add_argument(
        "--limit-samples",
        type=int,
        default=5,
        help="How many recent problem samples to include.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the summary as JSON instead of text.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = generate_report(
        log_patterns=args.log or None,
        state_path=args.state,
        limit_samples=max(1, int(args.limit_samples)),
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_quality_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
