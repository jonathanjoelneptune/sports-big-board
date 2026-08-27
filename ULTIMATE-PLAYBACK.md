# Sports Big Board Milestone 2 — Ultimate Playback

## v4.4.0 — Playback Readiness + Hot Standby

Milestone 1 is frozen at **v4.3.12 FOUNDATION_CERTIFIED**. v4.4.0 begins the next milestone without weakening the Foundation Tier 1–3 regression suite.

### Goal

Make playback feel prepared rather than reactive across **all enabled competitions** (MLB, NFL, NBA, NHL, EPL, MLS, and future competitions). Content ranking remains sport-aware; playback readiness is deliberately sport-neutral.

### v4.4.0 contract

- Every media asset receives a device readiness state: `DISCOVERED`, `VERIFIED`, `PLAYBACK_READY`, `DEGRADED`, or `QUARANTINED`.
- Playback reliability is learned from the canonical playback-session telemetry, not from provider claims alone.
- A single failure degrades an asset but does not globally quarantine it. Repeated independent failures or a very low reliability score are required for quarantine.
- The inactive A/B player is a true hot standby. `canplay` is insufficient; native media must show real playback progress and buffered data before `videoReady=true`.
- YouTube standby must actually enter PLAYING and advance before promotion.
- A failed standby candidate is rejected off-screen and another eligible candidate is warmed while the active video continues.
- Automatic A/B promotion requires an exact HOT_READY media-key claim. Lost/stale claims fall back through PlaybackController rather than blindly swapping.
- Upcoming program items are preflighted, with up to three direct/native candidates warmed ahead of airtime.
- Resolver ranking receives a playback-readiness bonus/penalty, and quarantined assets are removed from in-app eligibility.
- Central backend reliability is persisted in `playback-readiness.sqlite3` via the existing `/api/playback/telemetry` authority.

### Initial performance objectives

These are milestone targets, not hard release blockers until Ultimate Playback Certification:

- Hot-standby hit rate: **>95%**
- Prepared Next transition P95: **<750 ms**
- Startup P95: **<1.5 s**
- Unrecovered playback stalls: **0**
- Failed standby candidate visible to the viewer: **0**
- 100 sequential transitions: **no playback dead end**

### Next phases

- v4.4.1: readiness telemetry dashboard, cross-device/server ranking consumption, deeper predictive buffer-ahead policy.
- v4.4.2: SBB-controlled cache for media sources that may legally be cached/rehosted.
- v4.4.3: adaptive delivery/HLS-CMAF for SBB-controlled media.
- v4.4.4: Ultimate Playback Certification torture suite.
