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
  - Judge-stage prompt file
- `helperWorkspacePath`
  - Workspace root where the downstream `mc-helper` agent should run; the bridge uses it as the `openclaw agent` subprocess `cwd`

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

## Message filtering

- `maxMessageChars`
  - Ignore chat messages longer than this
- `maxReplyChars`
  - Soft ceiling passed into the reply payload
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

## Runtime state sizing

- `recentEventCacheSize`
  - How many event fingerprints to remember for duplicate suppression
- `recentChatStateSize`
  - How many chat entries to keep in persisted state
- `recentBotReplyStateSize`
  - How many bot replies to keep in persisted state
- `playerHistoryStateSize`
  - How many recent messages to keep per player in persisted state

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
