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
- `config/router_prompt.txt`
- `config/assist_prompt.txt`
- `config/command_prompt.txt`
- `config/full_agent_prompt.txt`

Supporting docs:
- Keep project documentation in `docs/` instead of scattering markdown files inside `config/`.

Boundary:
- This repo owns the Minecraft listener, short-term context, judge/reply orchestration, anti-spam behavior, and RCON delivery.
- The downstream helper agent lives in `C:\Users\Administrator\.openclaw\workspace-mc-helper`.
- Agent calls from this repo must stay grounded in `helperWorkspacePath`, not this bridge workspace.
- Core persona belongs in `workspace-mc-helper`; keep bridge prompts focused on public-chat policy and delivery constraints.
- `helper_seed/` is the bridge-side mirror of helper persona files; if you change helper-side persona docs, mirror the same files there in the same change.
- The helper-local Minecraft command planning skill lives under the helper workspace, not this bridge repo.
- The single bridge-side source of truth for the local planner path is `config/bridge_config.json` -> `commandPlannerScriptPath`.
- If the helper-local planner skill moves or is renamed, update `commandPlannerScriptPath` in this repo and the OpenClaw runtime skill registration in `C:\Users\Administrator\.openclaw\openclaw.json`.

Current defaults to keep in mind:
- Direct asks to `mini-huan`, `huan`, or the configured Chinese display name should usually get a reply.
- Short privacy, capability, or memory-limit refusals should usually reply instead of staying silent.
- Same-player follow-up relaxations only apply while the recent chat still looks like an active bot exchange.

Working rules:
- Keep changes scoped to the Minecraft listener, judge/reply orchestration, config, and RCON delivery.
- After code changes, run the relevant tests you can and restart the bridge so the live process picks up the new code.
- If behavior looks wrong, inspect `runtime/logs/bridge.out.log`, `runtime/logs/bridge.err.log`, and `runtime/last_invoke_debug.txt` before changing logic.
- Keep bridge docs in sync with behavior changes. If you change privileged routing, helper-local planner wiring, or continuation behavior, update `README.md` and `docs/CONFIG_FIELDS.md` in the same change.
- Keep helper docs in sync with planner changes. If you change helper-side Minecraft command planning guidance, update `C:\Users\Administrator\.openclaw\workspace-mc-helper\AGENTS.md` and the mirrored `helper_seed/AGENTS.md` in the same change.
