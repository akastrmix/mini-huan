# bridge_config.json field guide

This file explains the fields in `bridge_config.json` as the bridge works today.

## Core paths

- `helperScriptPath`
  - Python helper used by the bridge to call `mc-helper`
- `pythonPath`
  - Python executable used for the helper
- `configPath`
  - Path to this config file itself; passed through to the helper
- `rconScriptPath`
  - PowerShell script used to send commands to Minecraft via RCON
- `promptPath`
  - Reply-stage prompt file
- `judgePromptPath`
  - Fallback judge-stage prompt file used when the primary router path is unavailable, skipped, or does not return a usable chat decision
- `routerPromptPath`
  - Primary turn-orchestration prompt file for capability routing plus main-path `chat` reply/no-reply, refusal, and permission-denied decisions
- `assistPromptPath`
  - Privileged in-game assist prompt file
- `commandPromptPath`
  - Privileged Minecraft command prompt file
- `commandPlannerScriptPath`
  - Bridge-side local privileged-execution fallback planner script for the helper-local Minecraft command planning skill
  - This is the bridge-side single source of truth for the local planner path
  - If the helper-local planner skill moves or is renamed, update this field instead of hardcoding the new path in prompts or code
- `fullAgentPromptPath`
  - Full-agent prompt file for fully authorized players
- `helperWorkspacePath`
  - Workspace root where the downstream `mc-helper` agent should run; the bridge uses it as the `openclaw agent` subprocess `cwd`
  - This does not guarantee the resolved OpenClaw session stays inside that workspace if an existing stored session is resumed; verify `runtime/last_invoke_debug.txt` when the helper workspace or skills summary looks wrong

## Delivery

- `sendToMinecraft`
  - `true` = actually send replies into Minecraft
  - `false` = judge/draft only
- `replyMode`
  - Current supported mode: `tellraw_all`
- `displayName`
  - Visible bot name used in the in-game prefix
- `displayNameZh`
  - Chinese identity metadata passed into prompts; default is `\u5c0f\u5e7b`
- `nameAliases`
  - Extra names that should count as addressing the bot, such as `huan` for `mini-huan`
- `nameColor`
  - Color for the visible bot name in the prefix
- `contentColor`
  - Color for angle brackets and reply content
- `rconTimeoutSeconds`
  - Hard timeout for a single RCON delivery attempt

## Agent

- `agentId`
  - OpenClaw agent id to call, currently `mc-helper`
- `agentTimeoutSeconds`
  - Timeout passed to the agent call itself; the bridge also adds a small local buffer around the helper process
- `routerConfidenceThreshold`
  - Minimum confidence required before a privileged route above `chat` is trusted
- `privilegedCommandMaxRounds`
  - Maximum number of bridge-executed command/result loop rounds allowed inside one privileged player turn
- `privilegedCommandMaxCommandsPerRound`
  - Maximum number of Minecraft commands the bridge will execute in a single privileged loop round before marking the extras as skipped
- `privilegedCommandResultMaxChars`
  - Max characters of command stdout/error that the bridge will send back to the helper in the next privileged loop round

## Privileged routing / auth

- `auth.groups`
  - Named permission groups; each group exposes a `max_mode`
- `auth.players`
  - Player-to-groups mapping; this is where you grant players access to `assist`, `command`, or `full_agent`
- `modeSessionWindowSeconds`
  - Per-mode active-session windows for natural-language follow-ups; supports `assist`, `command`, `full_agent`, and optional `default`

Mode meanings:
- `chat`
  - normal public chat only
- `assist`
  - model-judged Minecraft assistance with command execution
- `command`
  - stronger Minecraft command execution
- `full_agent`
  - full OpenClaw-style agent work with tools/computer control plus optional Minecraft commands

Behavior notes:
- Every chat turn now enters the router first; player auth and active-session state only decide whether the router can stay in `chat` or escalate above it
- Public reply is still the default; private reply only happens when the player explicitly asks for it
- Privileged sessions are tracked per player, not globally
- The router is now the main decider for both privileged mode selection and whether a routed `chat` turn should speak at all, including most refusal/limitation and permission-denied chat replies
- Live Minecraft state questions that require real command output should route through the prompt into `assist` or `command`, not stay in `chat`
- `assist` and `command` now support a bridge-managed multi-step loop: helper returns commands, bridge executes them, helper receives actual results, then helper decides the next step or final reply
- Same-player follow-up questions can reuse the stored active privileged session context even when the player does not rename the bot, and those follow-ups now stay on the router/helper path before judge fallback is considered
- Same-player natural boundary continuations right after a recent refusal should also prefer the router-owned `chat` path before judge fallback is considered
- The bridge-local router fallback is now intentionally minimal: it mainly preserves active-session continuation, exit, and explicit raw command fallback after router failure
- Continuation phrases such as `again`, `one more`, or `再来一组` can reuse the player's last successful privileged command context

## Helper-local planner wiring

The helper-local Minecraft command planner is outside this repo's `docs/` tree, but bridge behavior depends on it.

Current moving parts:
- Helper-local skill directory:
  `C:\Users\Administrator\.openclaw\workspace-mc-helper\skills\mc-command-planner`
- Bridge-side planner script path:
  `commandPlannerScriptPath`
- OpenClaw skill discovery registration:
  `C:\Users\Administrator\.openclaw\openclaw.json`
  `skills.load.extraDirs`

Pitfalls:
- If you rename or move the helper-local planner skill without updating `commandPlannerScriptPath`, privileged fallback planning will silently stop working
- If you move the helper-local skill directory without updating `skills.load.extraDirs`, the skill may disappear from the Control UI and runtime skill list
- If OpenClaw resumes a stored session outside `helperWorkspacePath`, the helper-side skill summary and injected workspace files may not match the bridge's intended helper workspace
- If you assume `commandPlannerScriptPath` controls all privileged routing decisions, you may miss that the router prompt owns the main path, while the bridge-local router fallback only keeps minimal continuity and raw-command behavior after router failure
- If you change the multi-step command protocol shape in prompts or code, keep the bridge-side protocol payload and helper expectations in sync
- Do not duplicate the planner path in multiple prompt or doc files; keep the path authoritative in `bridge_config.json`

## Message filtering

- `maxMessageChars`
  - Ignore chat messages longer than this
- `maxReplyChars`
  - Hard ceiling for delivered replies; also passed into the reply payload as guidance
- `languageHint`
  - Human-readable hint about reply language selection

## Context windows

- `judgeRecentChatCount`
  - Max recent-chat entries sent to the judge stage
- `judgePlayerHistoryCount`
  - Max per-player history entries sent to the judge stage
- `judgeRecentBotCount`
  - Max recent bot replies sent to the judge stage
- `replyRecentChatCount`
  - Max recent-chat entries sent to the reply stage
- `replyPlayerHistoryCount`
  - Max per-player history entries sent to the reply stage
- `replyRecentBotCount`
  - Max recent bot replies sent to the reply stage
- `contextRecentTailReserve`
  - How much of the newest tail is always kept before relevance scoring fills the rest
- `contextMaxAgeSeconds`
  - Hard age cutoff applied to selected chat context, player history, and recent bot replies
- `humanAnswerLookbackCount`
  - How many recent entries to scan when estimating whether another player already answered

## Judge / anti-noise

- `judgeConfidenceThreshold`
  - Hard confidence pass threshold
- `judgeSoftThreshold`
  - Lower threshold that only passes for the allowed soft-pass reasons
- `globalCooldownSeconds`
  - Global cooldown between replies
- `playerCooldownSeconds`
  - Per-player cooldown between replies
- `maxBotConsecutiveReplies`
  - Caps extended reply streaks; the streak resets when a player turn ends without a bot reply
- `followupReplyWindowSeconds`
  - If the same player was replied to within this many seconds and the recent chat still looks like an active bot exchange, a direct follow-up can use the relaxed same-player conversation cap, including short refusal/limitation replies
- `maxSamePlayerConversationReplies`
  - Total consecutive replies allowed during a short same-player follow-up exchange before the normal streak gate starts blocking again
- `botReplyStreakResetSeconds`
  - If the bot has been silent this long, the stored reply streak expires and the next chat turn starts fresh
- `allowAppreciationReplies`
  - Whether short thanks/compliment acknowledgments are allowed

Behavior note:
- Direct asks that the bot cannot fulfill because of privacy, permissions/capabilities, or short-memory limits should usually still receive a short refusal/limitation reply; only clearly unsafe or non-directed content should stay silent
- If a player clearly addresses the bot by `mini-huan`, `huan`, or the configured `displayNameZh`, or clearly continues a recent same-player bot exchange, the bridge should usually prefer replying over silently treating it as background chatter
- On the main routed path, those public-chat reply/no-reply calls now come from the router first; the judge prompt mainly serves as a fallback gate instead of a second opinion on every privileged-capable turn
- On that main routed path, refusal/limitation calls and permission-denied chat refusals should also normally come from the router rather than from bridge-local override logic
- In that fallback judge path, the bridge no longer adds an extra public-chat signal suppression pass after the helper's judge response
- That fallback judge path now mainly keeps minimal refusal/boundary continuity, rather than rescuing ordinary bot-directed chat that the router should have handled
- If a helper-router `chat` route omits or invalidates the chat decision, the bridge now logs a router contract miss and falls back to judge instead of silently repairing it
- The bridge itself no longer rewrites declined judge outputs into refusal/boundary replies
- If the router omits or invalidates a permission-denied chat decision, the bridge now logs a router contract miss and falls back to judge instead of synthesizing its own `capability_refusal`

## Runtime state sizing

- `recentEventCacheSize`
  - How many event fingerprints to remember for duplicate suppression
- `recentChatStateSize`
  - How many chat entries to keep in persisted state
- `recentBotReplyStateSize`
  - How many bot replies to keep in persisted state
- `playerHistoryStateSize`
  - How many recent messages to keep per player in persisted state

Additional persisted state:
- `playerSessions`
  - Per-player active privileged session metadata, including current mode, session id, topic, private-reply preference, and the most recent command results
  - The bridge reuses this state for conversational follow-ups about the last privileged action and for command-result confirmation rounds

## Debug logging

- `debugLogInputs`
  - Emit full judge/reply input payloads
- `debugLogScores`
  - Emit context relevance scoring details
- `debugLogSummary`
  - Emit compact judge/reply summary lines

## Reply style

- `botStyle`
  - High-level speaking style object passed into the reply stage

### `botStyle` fields

- `persona`
- `tone`
- `maxSentences`
- `preferDirectIdentityAnswers`
- `greetingStyle`
- `avoid`

## Safe edits vs risky edits

### Usually safe to edit

- `judgePromptPath` and `promptPath`
- Thresholds and window sizes
- `displayName`, `displayNameZh`, `nameAliases`, `nameColor`, `contentColor`
- `maxReplyChars`, `languageHint`, `botStyle`
- Debug toggles

### Edit carefully

- `helperScriptPath`
- `pythonPath`
- `configPath`
- `rconScriptPath`
- `replyMode`
- `sendToMinecraft`

Changing core paths or delivery settings can break the bridge entirely.
