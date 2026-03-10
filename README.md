# MC Bridge

Minecraft log listener + OpenClaw `mc-helper` bridge.

This repo watches a Minecraft Java server `latest.log`, turns selected chat lines into structured events, asks the downstream helper whether to reply, and sends the final message back into Minecraft through RCON.

## Canonical Workspace

- Canonical bridge workspace: `C:\Users\Administrator\.openclaw\workspace-mc-bridge`
- Downstream helper workspace: `C:\Users\Administrator\.openclaw\workspace-mc-helper`
- Legacy compatibility copy: `C:\Users\Administrator\.openclaw\workspace\mc-listener`

If you open the legacy `mc-listener` copy first, switch to `workspace-mc-bridge` unless the user explicitly asks about the legacy files.

## Boundary

This repo is the bridge, not the helper workspace.

Bridge owns:
- Minecraft log parsing
- Short-term runtime state and context selection
- Judge/reply orchestration
- Anti-spam and follow-up gating
- RCON delivery

Helper owns:
- Core persona and identity
- Helper-side instructions and memory
- Answers to direct identity questions about the bot

Rule of thumb:
- If you are changing who the bot is, edit `workspace-mc-helper`
- If you are changing when the bot replies, what context it sees, or what public-chat constraints apply, edit this repo

## Persona And Prompt Ownership

Core persona lives in the helper workspace:
- [AGENTS.md](/C:/Users/Administrator/.openclaw/workspace-mc-helper/AGENTS.md)
- [IDENTITY.md](/C:/Users/Administrator/.openclaw/workspace-mc-helper/IDENTITY.md)
- [SOUL.md](/C:/Users/Administrator/.openclaw/workspace-mc-helper/SOUL.md)
- [USER.md](/C:/Users/Administrator/.openclaw/workspace-mc-helper/USER.md)

Bridge public-chat policy lives here:
- [bridge_config.json](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/bridge_config.json)
- [judge_prompt.txt](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/judge_prompt.txt)
- [reply_prompt.txt](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/reply_prompt.txt)

Bridge project documentation lives here:
- [CONFIG_FIELDS.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/docs/CONFIG_FIELDS.md)
- [CHAT_QUALITY.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/docs/CHAT_QUALITY.md)

Bridge runtime behavior lives in code:
- [mc_ai_bridge.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/mc_ai_bridge.py)
- [bridge_context.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_context.py)
- [bridge_judge.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_judge.py)
- [bridge_delivery.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_delivery.py)
- [bridge_state.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_state.py)
- [bridge_components.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_components.py)
  - compatibility re-exports for older imports

Current bot naming:
- English name: `mini-huan`
- Accepted shorthand: `huan`
- Chinese display name field: `displayNameZh` (current value `\u5c0f\u5e7b`)

## Helper Seed Mirror

This repo mirrors the helper persona files in [helper_seed](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/helper_seed) so the bridge can be uploaded by itself and still bootstrap a helper workspace.

Mirror these files whenever helper persona docs change:
- [helper_seed/AGENTS.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/helper_seed/AGENTS.md)
- [helper_seed/BOOTSTRAP.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/helper_seed/BOOTSTRAP.md)
- [helper_seed/IDENTITY.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/helper_seed/IDENTITY.md)
- [helper_seed/SOUL.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/helper_seed/SOUL.md)
- [helper_seed/USER.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/helper_seed/USER.md)

## Quick Orientation

If you just opened this project and want the fastest path to understanding it, read in this order:

1. [README.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/README.md)
2. [bridge_config.json](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/bridge_config.json)
3. [judge_prompt.txt](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/judge_prompt.txt)
4. [reply_prompt.txt](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/reply_prompt.txt)
5. [mc_ai_bridge.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/mc_ai_bridge.py)

Mental model:
- A Minecraft chat line comes in from `latest.log`
- The bridge stores short-term context in runtime state
- The judge step decides whether the bot should speak
- The reply step generates the final message only if judge passes
- The bridge sends the message back to Minecraft via RCON

Fresh-session defaults:
- Direct asks to `mini-huan`, `huan`, or the configured Chinese display name should usually get a reply
- Same-player follow-ups stay relaxed only while recent chat still looks like an active bot exchange
- Privacy, capability, and short-memory limits should usually get a short refusal reply instead of silence
- The helper owns identity; bridge prompts should stay focused on public-chat behavior

## Runtime Flow

```text
Minecraft latest.log
  -> app/mc_log_listener.py parses log lines
  -> app/mc_ai_bridge.py records short-term context
  -> app/mc_ai_bridge.py calls judge via mc-helper
  -> if approved, app/mc_ai_bridge.py calls reply via mc-helper
  -> app/mc_ai_bridge.py sends the reply via RCON
  -> Minecraft tellraw @a
```

## Important Files

- [bridge_config.json](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/bridge_config.json)
  - thresholds, windows, naming, delivery settings, and style constraints
- [CONFIG_FIELDS.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/docs/CONFIG_FIELDS.md)
  - field-by-field guide to `bridge_config.json`
- [judge_prompt.txt](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/judge_prompt.txt)
  - bridge-owned should-reply policy
- [reply_prompt.txt](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/reply_prompt.txt)
  - bridge-owned reply constraints layered on top of helper persona
- [bridge_context.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_context.py)
  - context scoring, player/bot history selection, and human-answer detection
- [bridge_judge.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_judge.py)
  - judge parsing, refusal/direct overrides, and gating
- [bridge_delivery.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_delivery.py)
  - RCON delivery and tellraw formatting
- [bridge_state.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_state.py)
  - persisted bridge state and atomic saves
- [bridge_components.py](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/app/bridge_components.py)
  - compatibility layer for existing imports
- [mc_ai_bridge_state.json](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/runtime/mc_ai_bridge_state.json)
  - persisted short-term bridge state
- [bridge.out.log](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/runtime/logs/bridge.out.log)
  - first place to inspect live behavior

## What To Edit

Edit the helper workspace when you need to change:
- The bot's core identity, voice, or persona
- Helper-only instructions or memory
- Direct identity answers like creator/owner/background

Edit this bridge repo when you need to change:
- Log parsing
- Short-term context assembly
- Judge/reply payloads and thresholds
- Anti-spam or follow-up behavior
- Public-chat constraints
- RCON delivery

## Current Default Behavior

Current context sizing:
- Judge window: `judgeRecentChatCount=20`, `judgePlayerHistoryCount=6`, `judgeRecentBotCount=4`
- Reply window: `replyRecentChatCount=12`, `replyPlayerHistoryCount=5`, `replyRecentBotCount=3`
- `contextMaxAgeSeconds=900`
- `humanAnswerLookbackCount=8`

Current thresholds:
- Hard pass at `judgeConfidenceThreshold=0.72`
- Soft pass at `judgeSoftThreshold=0.58` only for high-priority direct-address cases

Current cooldowns:
- `globalCooldownSeconds=0`
- `playerCooldownSeconds=0`

Current anti-flood behavior:
- Duplicate-event protection enabled
- `maxBotConsecutiveReplies=4`
- Same-player follow-ups within `followupReplyWindowSeconds=180` can continue only while recent chat still looks like an active bot exchange, up to `maxSamePlayerConversationReplies=20`
- `botReplyStreakResetSeconds=180`
- Appreciation acknowledgments may consume one extra consecutive turn

Current delivery:
- Global `tellraw @a`
- Prefix format: `<mini-huan>`
- `mini-huan` in `aqua`
- Brackets and content in `white`

## Ops

Start in foreground:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_mc_ai_bridge.ps1 "C:\path\to\logs\latest.log"
```

Start in background:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_mc_ai_bridge.ps1 "C:\path\to\logs\latest.log" -Background
```

Stop:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_mc_ai_bridge.ps1
```

Status:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\status_mc_ai_bridge.ps1
```

## Troubleshooting

Check in this order:

1. [status_mc_ai_bridge.ps1](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/scripts/status_mc_ai_bridge.ps1)
2. [bridge.err.log](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/runtime/logs/bridge.err.log)
3. [bridge.out.log](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/runtime/logs/bridge.out.log)
4. [last_invoke_debug.txt](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/runtime/last_invoke_debug.txt)
5. [bridge_config.json](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/config/bridge_config.json)

Quick diagnosis:
- Bot never speaks: inspect judge summaries and errors
- Bot replies oddly: inspect judge/reply inputs and selected context
- Bot uses stale context: inspect age/window settings
- Bot is too noisy or too quiet: adjust `judge_prompt.txt` and thresholds before changing reply style

## Chat Quality Tools

- Quality report:
  `python .\scripts\bridge_quality_report.py`
- Replay regression cases:
  `python -m unittest tests.test_chat_replays -v`
- Details:
  [CHAT_QUALITY.md](/C:/Users/Administrator/.openclaw/workspace-mc-bridge/docs/CHAT_QUALITY.md)
