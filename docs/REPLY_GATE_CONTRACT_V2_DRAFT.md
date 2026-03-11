# Reply Gate / Continuation Contract v2 Draft

This note is a design draft for the next reply-gate contract between the bridge and the helper.
It does not change current runtime behavior by itself.

## Goals

- Keep the bridge thin.
- Keep public-chat semantics in the helper/router or helper/judge contract, not in bridge-local heuristics.
- Make continuation intent explicit enough that the bridge can pick the right gate without guessing from `chat_reason`.
- Separate same-player exchange handling from room-level anti-flood handling.

## Non-goals

- Re-introducing bridge-local chat semantics such as `human_answer_seen`.
- Moving persona or identity policy back into the bridge.
- Solving room flood purely by raising numeric caps again.

## Current v1 Summary

Today the contract is effectively:

- router `chat` returns `chat_should_reply`, `chat_reason`, and `allow_followup_streak`
- fallback judge returns `should_reply`, `reason`, `allow_followup_streak`, and `allow_soft_confidence_pass`
- the bridge only uses `allow_followup_streak` to decide whether a same-player reply can use the relaxed follow-up cap

Current bridge gate shape:

- default room gate: `maxBotConsecutiveReplies`
- same-player relaxed gate: `maxSamePlayerConversationReplies` within `followupReplyWindowSeconds`
- appreciation tail: one extra turn beyond the default streak

## Why v1 Is Running Out Of Room

`allow_followup_streak: bool` is too coarse:

- it must cover active same-player exchange, refusal continuity, and appreciation tail
- `false` conflates first-contact direct asks, stale exchanges, and low-priority tails
- the bridge cannot tell whether a reply is a high-value continuation or a low-value tail without inferring from `chat_reason`

`maxBotConsecutiveReplies` is also an imperfect room-flood proxy:

- it measures uninterrupted streak length, not reply density
- slow sparse replies can still look like a long streak
- a short burst across different players is more like room flood than a single same-player exchange, but pure streak does not express that well

## Option Comparison

| Direction | Good | Limits | Verdict |
| --- | --- | --- | --- |
| Keep current streak + bool | Smallest code change, no new schema | Bool stays ambiguous; appreciation, refusal continuity, and active exchange still share one lane; streak is still a weak room-flood proxy | Useful only as a temporary patch |
| Replace streak with time-window budget only | Better room-flood signal than pure streak; measures density | Still does not tell bridge which replies are active exchange vs. low-priority tail; bridge would be pushed to infer semantics again | Better metric, wrong first move by itself |
| Strengthen helper contract first | Keeps semantics in helper; gives bridge a small explicit gate selector; improves logs/tests without broad bridge heuristics | Requires prompt/parser/test changes | Recommended first move |
| Stronger helper contract plus later room budget | Best long-term shape; helper owns semantics and bridge owns aggregate flood control | Slightly larger rollout, should be phased | Recommended end state |

## Recommended v2 Contract

Keep `chat_reason` as the semantic reason.
Replace the continuation bool with explicit gate metadata.

### Router `chat` output

When `mode == "chat"`, require these fields in addition to the current contract:

- `exchange_state`
- `delivery_priority`

Suggested enums:

- `exchange_state`: `none|active_same_player|post_refusal|post_answer_tail`
- `delivery_priority`: `normal|prefer_reply|tail`

Semantics:

- `exchange_state=none`
  - no active same-player continuation should be assumed by the bridge
- `exchange_state=active_same_player`
  - the same short same-player exchange is still live
  - this includes same-player follow-up questions and a fresh new direct ask that is clearly part of the same live back-and-forth
- `exchange_state=post_refusal`
  - same-player continuation immediately after a privacy/capability/memory refusal
  - examples: "why", "then what can you do", mild pushback, or a repeated prohibited ask
- `exchange_state=post_answer_tail`
  - low-value tail after a helpful answer, usually thanks or a very short acknowledgment-worthy reaction

- `delivery_priority=normal`
  - ordinary direct ask or ordinary chat reply that should pass the normal room gate
- `delivery_priority=prefer_reply`
  - reply is still important even when the default room gate is tight; bridge may use the same-player exchange gate when the recent exchange really is live
- `delivery_priority=tail`
  - lowest-priority tail; bridge should drop this before dropping `normal` or `prefer_reply`

### Fallback judge output

Use the same new fields:

- `exchange_state`
- `delivery_priority`

Keep:

- `allow_soft_confidence_pass`

The fallback judge remains narrow.
These fields tell the bridge which gate profile to use if the fallback reply is accepted.

## Suggested Contract Rules

### Valid combinations

- `none + normal`
  - default for first-contact direct asks and ordinary non-continuation replies
- `active_same_player + prefer_reply`
  - default for real same-player live exchange turns
- `post_refusal + prefer_reply`
  - default for short refusal continuity
- `post_answer_tail + tail`
  - default for appreciation tails

### Invalid or suspicious combinations

- `post_answer_tail + prefer_reply`
- `active_same_player + tail`
- `post_refusal + tail`

Bridge behavior for invalid combinations should stay thin:

- log a contract miss or normalize to the safer lower-priority profile
- prefer fallback to judge over silently inventing a stronger continuation class

## Bridge Gate Mapping

The bridge should only map helper-provided gate metadata onto a small set of gate profiles.

### Gate profile: `default_room`

Used when:

- `exchange_state == none`

Behavior:

- use the normal room-level anti-spam gate
- do not use the relaxed same-player continuation cap

### Gate profile: `same_player_exchange`

Used when:

- `exchange_state in {active_same_player, post_refusal}`
- the current speaker is the same player
- the bridge has a recent reply to that player within `followupReplyWindowSeconds`

Behavior:

- use the same-player relaxed cap
- in the first rollout, `post_refusal` can share the same cap as `active_same_player`
- keep the two states distinct in logs so they can be split later if needed

### Gate profile: `appreciation_tail`

Used when:

- `exchange_state == post_answer_tail`
- `delivery_priority == tail`
- the same player was just answered recently

Behavior:

- allow at most one very short tail turn
- never treat it as reopening a normal conversation
- drop this class before `normal` or `prefer_reply` when room pressure is high

## Room Flood vs. Active Same-Player Exchange

These should be treated as different layers.

### Room flood

Room flood is bridge-owned aggregate delivery pressure, not a helper semantic label.

Typical signs:

- many bot replies in a short time window
- replies spread across multiple players
- low-value tails or ambient room chatter are consuming visible chat space
- from the room's perspective, the bot is occupying the channel

### Active same-player exchange

Active same-player exchange is helper-owned conversation classification.

Typical signs:

- the same player is still clearly talking to the bot
- the turn depends on the immediately previous bot answer, refusal, or privileged result
- the exchange still looks live in raw `recent_chat`
- the player may omit the bot name because the exchange context is already obvious

Important:

- a fresh direct ask can still be `active_same_player` if it arrives inside the same short live back-and-forth
- a direct ask after a long gap should fall back to `none + normal`

## Scenario Classification

| Scenario | `chat_reason` | `exchange_state` | `delivery_priority` | Expected gate |
| --- | --- | --- | --- | --- |
| First-contact direct ask to the bot | `direct_question_to_bot` | `none` | `normal` | `default_room` |
| Same-player follow-up question right after the bot answer | `followup_to_bot_conversation` | `active_same_player` | `prefer_reply` | `same_player_exchange` |
| Same-player new direct ask while the exchange is still clearly live | `direct_question_to_bot` | `active_same_player` | `prefer_reply` | `same_player_exchange` |
| Mild pushback right after a refusal | `followup_to_bot_conversation` or matching refusal reason | `post_refusal` | `prefer_reply` | `same_player_exchange` |
| Repeated prohibited ask right after the refusal | matching refusal reason | `post_refusal` | `prefer_reply` | `same_player_exchange` |
| Immediate thanks after a helpful answer | `appreciation_after_bot_reply` | `post_answer_tail` | `tail` | `appreciation_tail` |
| Repeated praise after an appreciation tail | usually decline | `none` | `normal` | no reply |
| Room question already answered by another player and not directed at the bot | `conversation_already_answered` | `none` | `normal` | no reply |
| Generic room brainstorm without direct address | `not_addressed_to_bot` | `none` | `normal` | no reply |

## Why Time-Window Budget Should Be Phase 2, Not Phase 1

A time-window budget is still a good room-level idea, but only after the helper contract is more explicit.

Without stronger helper gate metadata:

- the bridge still cannot cleanly separate active exchange from appreciation tail
- a budget alone would push semantic guessing back into the bridge
- tests would stay brittle because one budget lane would still serve very different reply classes

With the stronger helper contract in place:

- the bridge can later swap `default_room` from pure streak to a time-window budget without changing helper prompts again
- the same-player exchange profile can stay separate
- low-priority tails can be dropped first when the room budget is tight

## If Phase 2 Adds A Room Budget

Keep it narrow.
Do not turn it into a second semantic engine.

Minimal config shape:

- `roomReplyBudgetWindowSeconds`
- `roomReplyBudgetMaxReplies`

Recommended use:

- apply the budget to `default_room`
- keep same-player exchange handling separate
- optionally let `prefer_reply` consume the last remaining slot before `tail`

Avoid in the first budget rollout:

- many per-reason knobs
- bridge-local heuristics that reinterpret `chat_reason`
- replacing same-player exchange handling with one unified room budget

## Migration Path

### Step 1

Update prompts and parser contract:

- router prompt emits `exchange_state` and `delivery_priority`
- fallback judge prompt emits the same fields
- helper workspace contract docs mention the new fields

### Step 2

Bridge parser and gate mapping:

- accept the new enums
- map them to the existing gate profiles
- keep room-level gating otherwise unchanged for now

### Step 3

Compatibility window:

- for one rollout, the bridge may map `allow_followup_streak=true` to `active_same_player + prefer_reply`
- keep logs noisy enough to detect missing v2 fields
- remove the legacy bool only after replay coverage is stable

### Step 4

Only after the v2 contract is stable:

- evaluate replacing `maxBotConsecutiveReplies` with a time-window room budget for `default_room`

## Minimal Code Path For The Next Implementation Round

1. Update `config/router_prompt.txt` and `config/judge_prompt.txt` to request the new fields.
2. Update bridge parser/normalization to accept the new enums and keep one-round legacy bool compatibility.
3. Map `exchange_state` to the existing bridge gate profiles without adding new bridge-local chat heuristics.
4. Add or update replay/unit cases for:
   - first-contact direct ask
   - active same-player follow-up
   - refusal continuity
   - appreciation tail
   - room question already answered
5. Only after those tests are stable, decide whether room-level flood should move from pure streak to a time-window budget.

## Recommendation

Recommended next move:

- strengthen the helper contract first
- keep the bridge as a small gate mapper
- treat time-window budget as a separate follow-up improvement for room flood, not as the first fix

In short:

- helper should classify the exchange
- bridge should choose the gate profile
- bridge should own aggregate room pressure
