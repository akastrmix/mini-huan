import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import invoke_mc_helper


class InvokeMCHelperTests(unittest.TestCase):
    def test_main_runs_openclaw_from_helper_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            helper_workspace = tmp / "workspace-mc-helper"
            helper_workspace.mkdir()
            prompt_path = tmp / "prompt.txt"
            task_path = tmp / "task.json"
            config_path = tmp / "config.json"
            out_path = tmp / "out.json"
            debug_path = tmp / "debug.txt"

            prompt_path.write_text("say hello", encoding="utf-8")
            task_path.write_text(json.dumps({"question": "hi"}, ensure_ascii=False), encoding="utf-8")
            config_path.write_text(json.dumps({
                "helperWorkspacePath": str(helper_workspace),
            }, ensure_ascii=False), encoding="utf-8")

            observed = {}

            def fake_run(cmd, **kwargs):
                observed["cmd"] = cmd
                observed["cwd"] = kwargs.get("cwd")
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout=json.dumps({
                        "result": {
                            "payloads": [{"text": "hello from helper"}],
                            "meta": {"agentMeta": {"sessionId": "session-123"}},
                        }
                    }, ensure_ascii=False),
                    stderr="",
                )

            argv = [
                "invoke_mc_helper.py",
                "mc-helper",
                "30",
                str(task_path),
                str(config_path),
                str(out_path),
                str(prompt_path),
            ]

            with mock.patch.object(invoke_mc_helper, "DEBUG_PATH", debug_path):
                with mock.patch.object(sys, "argv", argv):
                    with mock.patch.object(invoke_mc_helper.subprocess, "run", side_effect=fake_run):
                        invoke_mc_helper.main()

            self.assertEqual(observed["cwd"], str(helper_workspace))
            self.assertEqual(observed["cmd"][0], invoke_mc_helper.OPENCLAW_CMD)
            self.assertTrue(debug_path.exists())
            self.assertEqual(
                json.loads(out_path.read_text(encoding="utf-8")),
                {"reply": "hello from helper", "sessionId": "session-123"},
            )

    def test_main_exits_when_payload_contains_agent_error_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            helper_workspace = tmp / "workspace-mc-helper"
            helper_workspace.mkdir()
            prompt_path = tmp / "prompt.txt"
            task_path = tmp / "task.json"
            config_path = tmp / "config.json"
            out_path = tmp / "out.json"
            debug_path = tmp / "debug.txt"

            prompt_path.write_text("say hello", encoding="utf-8")
            task_path.write_text(json.dumps({"question": "hi"}, ensure_ascii=False), encoding="utf-8")
            config_path.write_text(json.dumps({
                "helperWorkspacePath": str(helper_workspace),
            }, ensure_ascii=False), encoding="utf-8")

            def fake_run(cmd, **kwargs):
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout=json.dumps({
                        "result": {
                            "payloads": [{
                                "text": "Codex error: {\"type\":\"error\",\"error\":{\"message\":\"temporary failure\"}}"
                            }],
                            "meta": {"agentMeta": {"sessionId": "session-123"}},
                        }
                    }, ensure_ascii=False),
                    stderr="",
                )

            argv = [
                "invoke_mc_helper.py",
                "mc-helper",
                "30",
                str(task_path),
                str(config_path),
                str(out_path),
                str(prompt_path),
            ]

            with mock.patch.object(invoke_mc_helper, "DEBUG_PATH", debug_path):
                with mock.patch.object(sys, "argv", argv):
                    with mock.patch.object(invoke_mc_helper.subprocess, "run", side_effect=fake_run):
                        with self.assertRaises(SystemExit) as ctx:
                            invoke_mc_helper.main()

            self.assertIn("openclaw agent returned an error reply", str(ctx.exception))
            self.assertFalse(out_path.exists())
            self.assertTrue(debug_path.exists())

    def test_main_exits_when_stdout_is_error_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            helper_workspace = tmp / "workspace-mc-helper"
            helper_workspace.mkdir()
            prompt_path = tmp / "prompt.txt"
            task_path = tmp / "task.json"
            config_path = tmp / "config.json"
            out_path = tmp / "out.json"
            debug_path = tmp / "debug.txt"

            prompt_path.write_text("say hello", encoding="utf-8")
            task_path.write_text(json.dumps({"question": "hi"}, ensure_ascii=False), encoding="utf-8")
            config_path.write_text(json.dumps({
                "helperWorkspacePath": str(helper_workspace),
            }, ensure_ascii=False), encoding="utf-8")

            def fake_run(cmd, **kwargs):
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout=json.dumps({
                        "type": "error",
                        "error": {"message": "transport failed"},
                    }, ensure_ascii=False),
                    stderr="",
                )

            argv = [
                "invoke_mc_helper.py",
                "mc-helper",
                "30",
                str(task_path),
                str(config_path),
                str(out_path),
                str(prompt_path),
            ]

            with mock.patch.object(invoke_mc_helper, "DEBUG_PATH", debug_path):
                with mock.patch.object(sys, "argv", argv):
                    with mock.patch.object(invoke_mc_helper.subprocess, "run", side_effect=fake_run):
                        with self.assertRaises(SystemExit) as ctx:
                            invoke_mc_helper.main()

            self.assertIn("openclaw agent returned an error payload", str(ctx.exception))
            self.assertFalse(out_path.exists())
            self.assertTrue(debug_path.exists())


if __name__ == "__main__":
    unittest.main()
