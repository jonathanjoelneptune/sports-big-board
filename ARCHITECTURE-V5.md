# Sports Big Board v5 Runtime Architecture

## v5.0.0 scope

v5.0.0 is the control-plane consolidation release. It preserves the proven Sports Big Board UI, catalog, provider/discovery stack, Day State model, media taxonomy, history workers, readiness/quarantine logic, and A/B player implementation while replacing distributed browser ownership with one directional runtime model.

The v5 invariant is:

```text
Selected Event
    |\
    | +--> Game Center
    |
    +--> Playback Intent --> Media Plan --> Playback Transaction --> Player Adapter
```

Nothing points backward. A player callback cannot choose a sporting event. Media readiness cannot erase event selection. Game Center cannot start or change playback. Certification observes the same control plane used by the viewer.

## Canonical browser authorities

### `SBB_APP_STORE`

`architecture/app-store-v5.js` owns the browser application state tree. Event selection and playback-intent creation are one atomic reducer commit. It records browse state, selected event, Game Center ownership, playback transaction state, media plan, active media, recovery state, progress, and an invariant string.

A score click creates `PLAYBACK_INTENT_BEGIN` before media resolution or prewarming. Therefore a cold source can become `UNAVAILABLE`, but the application never falls into the old state where the click happened and no playback transaction exists.

### `SBB_SELECTED_EVENT`

`architecture/selected-event-store.js` remains the event pub/sub boundary used by Game Center and existing UI. Under v5 it mirrors the App Store's event authority. Sparse media metadata and late playback/provider callbacks may not redirect or clear the selected sporting event, including after media becomes unavailable.

### `SBB_PLAYBACK_ORCHESTRATOR`

`architecture/playback-orchestrator-v5.js` owns every playback transaction. It is the only application service that may request activation of a media item. It owns:

- score and program intents;
- media-plan publication;
- prewarm/preparation state;
- candidate selection;
- starting/recovering/unavailable/failed/ended states;
- the single player-adapter binding;
- cold tune and already-prepared A/B promotion requests.

The existing A/B/YouTube/native implementation is retained in v5.0.0 as one legacy adapter beneath this boundary. All normal tune entry points and hot-standby promotions route through the orchestrator.

### `SBB_PLAYBACK_SESSION`

Playback Session advances to contract 2.0. It is transport telemetry below the v5 transaction. `beginIntent()` creates observable playback truth before a concrete media asset is selected. Concrete player attempts continue to emit selection, first-frame, buffering, failure, audible-owner, and transport metadata.

## Transaction states

The primary state progression is:

```text
INTENT
  -> PREPARING
  -> SELECTED
  -> STARTING
  -> PLAYING
  -> ENDED
```

Recovery is explicit:

```text
STARTING / PLAYING
  -> RECOVERING
  -> SELECTED / STARTING
```

A bounded failure ends in `FAILED` or `UNAVAILABLE` while preserving the selected sporting event.

## Compatibility boundary

v5.0.0 is deliberately a strangler migration, not a big-bang rewrite. The following remain in place behind the new authority boundary:

- existing A/B player slots and hot standby;
- native and YouTube adapters;
- v4.8.1 local no-progress containment;
- v4.8.2 cold-upstream preflight/readiness;
- current media resolver and browser candidate indexes;
- current backend Game Center/provider compatibility layers.

These are implementation details under v5. They must not become competing application authorities.

## v5.0.0 blocking invariants

1. A score click creates a v5 playback transaction synchronously before prewarm.
2. Selected Event and playback intent change atomically.
3. A media/prewarm failure cannot clear or redirect Selected Event.
4. Game Center follows Selected Event only.
5. Every normal program tune routes through `tuneProgramIndexV5()` and the orchestrator.
6. Every prepared A/B promotion routes through `promotePreparedV5()` and the orchestrator.
7. Only one legacy player adapter may bind to the orchestrator.
8. The App Store invariant must remain `OK` throughout certification.
9. Comprehensive Certification must report the v5 transaction, adapter binding, selected event, and ownership state.
10. Existing v4.8 readiness and local-recovery protections remain blocking regression contracts.

## Deliberately deferred 5.x migrations

v5.0.0 fixes the browser control plane first. The next architecture stages should be implemented without adding new runtime monkey patches:

- **5.1 canonical backend event identity:** persistent internal Event ID plus provider aliases; eliminate click-time NBA/NHL identity reconstruction.
- **5.2 server-owned MediaPlan:** backend returns one ranked event media plan so rendering, click, fallback and history do not independently rebuild candidate truth.
- **5.3 adapter extraction:** move the legacy A/B implementation out of `app.js` into explicit YouTube/native player adapters and remove remaining playback globals.
- **5.4 compatibility retirement:** remove release-number runtime wrappers/hotfix enrollment once their behavior is incorporated into stable services.
- **5.5 source build modernization:** evaluate TypeScript/Vite after ownership migration is stable; this is not required for the v5 runtime invariant.

No catalog rebuild is required for v5.0.0.

## v5.0.1 — UI-thread and feedback-loop hardening

The unified control plane is **edge-triggered**. Provider/player polling is observation, not an application state transition. Repeated `PLAYING`, identical audibility, or identical adapter metadata must not emit a Playback Session update or create an App Store commit.

The App Store stores a compact canonical event projection in the hot playback tree. Rich provider responses, media collections, Game Center timelines, and other large acquisition payloads remain outside the frequently cloned runtime state. `SelectedEvent` may retain the richer score event needed by Game Center, but the playback transaction carries only identity, teams, date/status, scores, and ownership metadata.

The browser main-thread guard measures event-loop lag independently of playback. Comprehensive Certification yields a browser frame before high-impact interactions and refuses to stack another synthetic interaction while the UI thread remains saturated. Main-thread critical stalls are blocking certification evidence.

The v5.0.1 feedback rule is:

`transport poll → no change → no session emit → no orchestrator mirror → no App Store commit → no DOM work`

Only a material edge such as `STARTING → PLAYING`, a new selection ID, fallback, failure, end, or ownership change propagates upward.

## v5.0.2 — Media-plan continuity and pathological event containment

v5.0.2 strengthens the score-click path without introducing any game-specific
branching. A score playback transaction owns a complete ordered Media Plan. One
failed candidate may be rejected, but it may not terminate the transaction while
another eligible candidate remains.

The transaction-level rule is:

```text
INTENT -> PLAN(candidate 0, 1, 2 ...)
             |
             +-> attempt candidate 0 -> reject
             +-> attempt candidate 1 -> select -> STARTING -> PLAYING
```

`UNAVAILABLE` is valid only after `PLAYBACK_PLAN_EXHAUSTED`. The App Store records
`planAttempted`, `planRejected`, `attemptedMediaKeys`, `rejectedMediaKeys`, and
`planExhausted`; an `UNAVAILABLE` transaction with a non-empty unexhausted plan is
an architecture invariant error.

### Current-session readiness

Durable `PLAYBACK_READY` / verified history improves ranking, but it is no longer
proof that a direct/native asset is ready in this browser session. Native media
must be either `HOT_READY` from the prepared-player pool or `HOT_THIS_SESSION`
from observed advancing playback before automatic activation. Historical proof is
reported as `PROVEN_HISTORY` and is prewarmed again.

### Cooperative score planning

`architecture/score-media-plan-v5.js` owns bounded, cooperative scanning for an
intent-time score media plan. Exact event candidates are retained first. When the
fallback date-wide media pool must be examined, matching is processed in small
chunks and yields to `SBB_MAIN_THREAD_GUARD` / the browser between chunks. A
single unusually dense event therefore cannot monopolize the UI thread while its
media plan is assembled.

### Indexed and bounded recap alternates

The old recap hot path searched the entire recent recap registry from player/UI
metadata code. v5.0.2 replaces that with `RECAP_CANDIDATE_INDEX`, keyed by
canonical event/game identities. The global registry is scanned only when its
membership changes in background work. UI lookups are indexed, short-lived
cached, and bounded to four alternatives per tier / twelve total alternatives.
This prevents one event with an unusually dense or ambiguous media history from
turning metadata or recap-button refresh into a large synchronous workload.

### Game Center completeness

Comprehensive Certification schema 3.2 adds sport-aware final-game payload
quality. A successful HTTP response or `coverage.complete` flag alone is no
longer sufficient. Final MLB/football/basketball/hockey/soccer samples must carry
reasonable sport-specific scoreboard/play-by-play/stat evidence. Sparse shells
are reported as `*_PAYLOAD_TOO_SPARSE` rather than `complete=YES`.

v5.0.2 remains game-agnostic. Known difficult games are regression evidence, not
runtime exceptions.


## v5.0.4 — Score-click authority and pathological-event hardening

v5.0.4 closes the remaining pre-orchestrator score-click bypass. A score-card
click may synchronously create only the v5 event/playback intent. It may not call
`scoreCardPlayableItems()` from the DOM handler, prewarm hidden decoders from
pointer events, recursively expand an unbounded `recapAlternates` graph, or run a
whole-ribbon warm reconciliation before yielding to the browser.

The canonical path is now:

`CLICK -> PLAYBACK_INTENT_BEGIN -> browser yield -> cooperative Media Plan -> candidate attempts -> adapter tune`.

`scoreCardPlayableItemsForIntent()` owns click-time media resolution. Legacy
`scoreCardPlayableItems()` remains a render/read helper only. Media-version graph
expansion is iterative and bounded to 96 assets / depth 2. Visible-card warming is
post-render background work; pointerenter, pointerdown and focus perform no media
or decoder work.

SelectedEvent is also transaction-protected at both the SelectedEvent store and
App Store reducer boundaries. Helpers, certification cleanup and player callbacks
cannot clear an event beneath an active event-owned transaction. Score-session
startup failures remain local Media Plan evidence and cannot trigger the global A/B
engine-reset threshold.

A small `SBB_SCORE_CLICK_TRACE` breadcrumb records the last completed click stage
so a pathological event can be diagnosed after reload without adding a game-specific
production branch. Known difficult games remain regression fixtures only.

## v5.0.4 — Last-known-good score read model

Score inventory is now a durable browser read model rather than a mirror of the
most recent transport result. A provider/network error may record ERROR metadata,
but it cannot replace a previously valid date/league scoreboard with an empty
array. Only a successful authoritative response may establish an empty league.
`SBB_SCORE_DATE.dateHealth(date)` exposes games, authoritative leagues, empty
leagues, and transient errors for certification. This prevents a healthy date from
collapsing to “No games listed” because a later refresh failed.

## v5.0.6 — Curated isolation fast lane

Automated discovery and ranking remain the default media authority. When a human
operator has identified the exact recap that should represent a specific sporting
event, the correction remains data in `architecture/curated-media-overrides.js`;
the application still contains no event-specific playback branch.

The v5.0.5 implementation proved that merely putting a curated asset first was not
enough. A pathological event could still enter the old automated association and
alternate graph during the same click. v5.0.6 therefore establishes a stronger
boundary: **curated media never enters the automated media graph for the active
curated score session.**

A matching score card short-circuits availability from the curated registry. On
click, the v5 transaction and SelectedEvent are created first, the browser yields,
and `CURATED_FAST_LANE` dispatches the exact curated asset as a one-item Media Plan.
The rest of the date is not synchronously built and automated same-event candidates
are not hydrated while that curated session owns playback.

If the exact curated asset cannot embed, `handleCuratedPlaybackFailure` fails closed:
it preserves SelectedEvent and board responsiveness and offers the exact curated
source URL as an external fallback. It does not re-enter `scoreCardPlayableItems`,
historical recovery, or the automated alternate graph. This trades speculative
fallback breadth for deterministic containment on a human-corrected event.

Entries marked as regression fixtures are actively exercised by Comprehensive
Certification schema 3.6. Certification requires the `CURATED_FAST_LANE` breadcrumb,
verifies the configured physical media selection and media-clock advancement, and
checks Game Center ownership, engine-reset count, and the v5 invariant.
