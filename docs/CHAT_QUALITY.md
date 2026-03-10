# Chat Quality

Use these tools when reply quality feels too noisy, too quiet, or otherwise off.

## Replay Tests

- Replay fixtures live in `tests/fixtures/chat_replays.json`.
- Add real incidents there as compact cases with:
  - recent state
  - the triggering player message
  - the mocked judge output
  - the expected public-chat result
- Run:
  `python -m unittest tests.test_chat_replays -v`

This is the fastest way to lock a bad chat incident into regression coverage before tweaking prompts or code.

## Quality Report

- Run:
  `python .\scripts\bridge_quality_report.py`
- JSON output:
  `python .\scripts\bridge_quality_report.py --json`
- Specific files or archived logs:
  `python .\scripts\bridge_quality_report.py --log runtime\logs\bridge.out*.log`

The report summarizes:
- judge pass/block rates
- decision and gate reasons
- reply/error counts
- recent problem samples
- current bridge state snapshot

## Log Retention

Starting the bridge now rotates existing `bridge.out.log` and `bridge.err.log` into timestamped files before each new start, including both foreground and background runs.
That keeps previous sessions available for quality reports and incident review.
