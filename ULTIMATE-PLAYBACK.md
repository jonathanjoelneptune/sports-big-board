# Sports Big Board Milestone 2 — Ultimate Playback

## v4.4.3 — Playback Engine Resilience + Endurance

Milestone 1 is frozen at **v4.3.12 FOUNDATION_CERTIFIED**. v4.4.3 continues Ultimate Playback without weakening the Foundation Tier 1–3 regression suite.

### Goal

Make playback feel prepared rather than reactive across **all enabled competitions** (MLB, NFL, NBA, NHL, EPL, MLS, and future competitions). Content ranking remains sport-aware; playback readiness is deliberately sport-neutral.


### v4.4.3 hardening contract

- Full-recap completion uses the canonical recap classifier, not the legacy raw `overview` flag. A completed short recap cannot automatically roll into a longer alternate recap for the same game.
- Score-card playback expands all attached media versions before ranking, preserving the editorial preference across Quick, Commentary, Extended and Blue options.
- Generic startup/no-first-frame failures are transient. Only evidence that is asset-specific (for example YouTube 101/150, unsupported/decode errors, or 404/410-class failures) permanently removes an asset.
- Three independent startup failures inside 25 seconds open a browser playback-engine incident and reset stale A/B assignments, hidden prepared state and transient blocks.
- The score ribbon owns **zero extra browser decoders**. Predictive score warming is server-side; the canonical A/B player remains the only browser hot-standby path.
- Historical final games from the preceding three days automatically queue recap discovery when their score cards have no playable media.
- Dev Playback Terminal adds a **30-minute automated endurance run**: 5-minute warmup, 15-minute soak and 10-minute hammer.
- The hammer phase deliberately disrupts standby before transitions. The runner watches first-frame proof, tracks engine incidents/resets, exercises next-game transitions, attempts controlled recovery, and fails on unrecoverable no-first-frame behavior.
- The runner also fails if a different full-recap asset for the same canonical game starts immediately after a recap of that game already played, directly guarding the v4.4.2 same-game replay regression.

### Endurance pass criteria

A completed 30-minute run must finish without a playback invariant error, duplicate same-game recap, or unrecoverable no-frame failure, and must prove at least 12 first frames across at least 10 controlled transitions. The terminal exposes live phase, elapsed time, successful starts, transition count, no-frame streak, engine resets and standby disruptions, plus COPY output for the run record.

### Ultimate Playback baseline contract

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

- v4.4.4: expand the terminal endurance contract toward the 100-transition Ultimate Playback certification torture suite.
- v4.4.4+: adaptive delivery/HLS-CMAF for SBB-controlled media where caching/rehosting is permitted.
- Continue cross-device/server readiness ranking and deeper predictive buffer-ahead policy without reintroducing browser decoder pressure.


## v4.4.2 — On-air bandwidth protection + durable readiness hydration
- Server readiness history now hydrates every browser, so a new device does not rediscover known-bad assets from scratch.
- Active playback has bandwidth priority. Browser warm concurrency is one hidden decoder, the prepared pool is small, and server warm neighborhoods are bounded.
- Hot standby preparation pauses whenever the on-air stream is starting/buffering or lacks at least ~5 seconds of safe buffer runway.
- Automatic transitions never intentionally promote an unproven candidate. If no HOT_READY asset exists, the current healthy clip remains on air or the bumper remains visible while off-screen preparation continues.
- Dev Mode adds a persistent Playback Terminal below the player with per-selection play time, cumulative buffer time across multiple stalls, startup time, transport, provider, readiness score and source/title.


## v4.4.2 Transition Authority + Dev Mode Reliability
- Manual NEXT/PREV is authoritative; hot standby is an accelerator, never a gate.
- Background readiness timeout is PENDING, not an asset failure.
- Transition-critical warming may run even when speculative warming is paused.
- Dev Mode is ephemeral and defaults OFF on every page load; opening the certification console enables it.
- Next infrastructure step: controlled direct-media byte-range/prefix cache for sources permitted to be cached/rehosted.
