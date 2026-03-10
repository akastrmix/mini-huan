#!/usr/bin/env python3
"""Bridge logging helpers."""

import json
import sys


class Logger:
    def __init__(self, config: dict):
        self.config = config

    def enabled(self, key: str, default: bool = False) -> bool:
        return bool(self.config.get(key, default))

    def emit(self, payload: dict, *, error: bool = False, force: bool = True):
        if not force:
            return
        target = sys.stderr if error else sys.stdout
        print(json.dumps(payload, ensure_ascii=False), file=target, flush=True)

    def input_logs_enabled(self) -> bool:
        return self.enabled("debugLogInputs", True)

    def score_logs_enabled(self) -> bool:
        return self.enabled("debugLogScores", False)

    def summary_logs_enabled(self) -> bool:
        return self.enabled("debugLogSummary", True)
