import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bridge_quality_report


class BridgeQualityReportTests(unittest.TestCase):
    def test_build_quality_summary_counts_judge_reply_and_errors(self):
        records = [
            {
                "bridge": "judge",
                "event": {"player": "alice", "message": "hi huan?"},
                "decision": {"reason": "direct_question_to_bot", "confidence": 0.95},
                "gate": {"passed": True, "why": "passed"},
            },
            {
                "bridge": "reply",
                "event": {"player": "alice", "message": "hi huan?"},
                "decision": {"reason": "direct_question_to_bot"},
                "reply": "我在，咋啦？",
            },
            {
                "bridge": "judge",
                "event": {"player": "bob", "message": "你觉得我该怎么整"},
                "decision": {"reason": "not_addressed_to_bot", "confidence": 0.35},
                "gate": {"passed": False, "why": "judge_declined"},
            },
            {
                "bridge": "error",
                "stage": "reply_payload",
                "event": {"player": "alice", "message": "hi huan?"},
                "error": "Codex error: boom",
            },
            {
                "bridge": "reply_truncated",
                "event": {"player": "alice", "message": "hi huan?"},
                "original_length": 12,
                "sent_length": 5,
            },
            {
                "bridge": "skip",
                "reason": "skip-duplicate",
                "event": {"player": "alice", "message": "hello"},
            },
        ]
        state = {
            "botConsecutiveReplyCount": 1,
            "recentBotReplies": [{"text": "我在，咋啦？", "timestamp": 123.0}],
        }

        summary = bridge_quality_report.build_quality_summary(
            [],
            records,
            invalid_lines=1,
            state=state,
            limit_samples=3,
        )

        self.assertEqual(summary["records_total"], 6)
        self.assertEqual(summary["invalid_lines"], 1)
        self.assertEqual(summary["judge_total"], 2)
        self.assertEqual(summary["judge_passed"], 1)
        self.assertEqual(summary["judge_blocked"], 1)
        self.assertEqual(summary["replies_sent"], 1)
        self.assertEqual(summary["reply_truncations"], 1)
        self.assertEqual(summary["errors_total"], 1)
        self.assertEqual(summary["decision_reasons"]["direct_question_to_bot"], 1)
        self.assertEqual(summary["decision_reasons"]["not_addressed_to_bot"], 1)
        self.assertEqual(summary["error_stages"]["reply_payload"], 1)
        self.assertEqual(summary["skip_reasons"]["skip-duplicate"], 1)
        self.assertEqual(summary["state_snapshot"]["bot_reply_streak"], 1)
        self.assertEqual(summary["state_snapshot"]["recent_bot_replies"], ["我在，咋啦？"])
        self.assertEqual(len(summary["problem_samples"]), 3)

    def test_generate_report_reads_multiple_logs_from_glob(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log1 = tmp / "bridge.out.log"
            log2 = tmp / "bridge.out.20260310-220000.log"
            state_path = tmp / "state.json"

            log1.write_text(
                json.dumps({
                    "bridge": "judge",
                    "event": {"player": "alice", "message": "hi huan?"},
                    "decision": {"reason": "direct_question_to_bot", "confidence": 0.9},
                    "gate": {"passed": True, "why": "passed"},
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            log2.write_text(
                json.dumps({
                    "bridge": "reply",
                    "event": {"player": "alice", "message": "hi huan?"},
                    "decision": {"reason": "direct_question_to_bot"},
                    "reply": "hello",
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            state_path.write_text(json.dumps({
                "botConsecutiveReplyCount": 2,
                "recentBotReplies": [{"text": "hello", "timestamp": 100.0}],
            }, ensure_ascii=False), encoding="utf-8")

            summary = bridge_quality_report.generate_report(
                log_patterns=[str(tmp / "bridge.out*.log")],
                state_path=state_path,
                limit_samples=2,
            )

            self.assertEqual(len(summary["log_files"]), 2)
            self.assertEqual(summary["judge_total"], 1)
            self.assertEqual(summary["replies_sent"], 1)
            self.assertEqual(summary["state_snapshot"]["bot_reply_streak"], 2)
            rendered = bridge_quality_report.render_quality_summary(summary)
            self.assertIn("Bridge Quality Report", rendered)
            self.assertIn("direct_question_to_bot", rendered)


if __name__ == "__main__":
    unittest.main()
