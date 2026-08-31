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
