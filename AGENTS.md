# AGENTS.md - workspace-mc-bridge

This repo is a bridge/integration project, not an agent workspace.

Canonical workspace root:
- `C:\Users\Administrator\.openclaw\workspace-mc-bridge`

Legacy compatibility path:
- `C:\Users\Administrator\.openclaw\workspace\mc-listener`
- If a session starts there, switch your mental model and file references to this repo unless the user explicitly asks about the legacy copy.

Read in this order:
- `README.md`
- `config/bridge_config.json`
- `config/judge_prompt.txt`
- `config/reply_prompt.txt`

Supporting docs:
- Keep project documentation in `docs/` instead of scattering markdown files inside `config/`.

Boundary:
- This repo owns the Minecraft listener, short-term context, judge/reply orchestration, anti-spam behavior, and RCON delivery.
- The downstream helper agent lives in `C:\Users\Administrator\.openclaw\workspace-mc-helper`.
- Agent calls from this repo must stay grounded in `helperWorkspacePath`, not this bridge workspace.
- Core persona belongs in `workspace-mc-helper`; keep bridge prompts focused on public-chat policy and delivery constraints.
- `helper_seed/` is the bridge-side mirror of helper persona files; if you change helper-side persona docs, mirror the same files there in the same change.

Current defaults to keep in mind:
- Direct asks to `mini-huan`, `huan`, or the configured Chinese display name should usually get a reply.
- Short privacy, capability, or memory-limit refusals should usually reply instead of staying silent.
- Same-player follow-up relaxations only apply while the recent chat still looks like an active bot exchange.

Working rules:
- Keep changes scoped to the Minecraft listener, judge/reply orchestration, config, and RCON delivery.
- After code changes, run the relevant tests you can and restart the bridge so the live process picks up the new code.
- If behavior looks wrong, inspect `runtime/logs/bridge.out.log`, `runtime/logs/bridge.err.log`, and `runtime/last_invoke_debug.txt` before changing logic.
