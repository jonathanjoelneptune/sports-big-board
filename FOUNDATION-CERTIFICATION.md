# Sports Big Board v4.3.8 — Foundation Certification / Soak Progress Closure

v4.3.6 changes Foundation Certification from the short v4.3.0 stress certificate into a three-tier release gate. The prior v4.3.0 certificate is retained as Tier 1 baseline evidence only; it is not sufficient for overall Foundation Certification.

## Tier 1 — Functional / Stress Hardening

Runs the release, playback, historical-read, operator-load, resource-mode, Game Center, soundtrack and responsiveness procedures plus a dedicated regression-hardening procedure.

The hardening procedure specifically verifies:

- production startup has no legacy NBA/demo seed programming;
- browsing dates or league filters never autoplays Silver roundup media;
- Game Center follows the active game video after direct selection, Next and automatic A/B promotion;
- a manual pause remains latched for at least 25 seconds under background refresh;
- background programming refresh cannot silently replace/restart the active media selection.

### Tier 1 post-first-frame stall recovery

v4.3.6 adds a bounded playback-stall watchdog for media that has already produced a first frame and later becomes stuck buffering. After 8 seconds of sustained post-first-frame buffering, the active asset is treated as unhealthy for the current browser session and the existing playback-failure controller advances to the next eligible media (or same-game fallback for an explicit score-card session). The same stalled clip is not restarted. Tier 1 allows up to 20 seconds for the complete failover/recovery sequence and fails if playback does not recover within that bound.

## Tier 2 — Extended Soak

Default duration: **15 minutes**, sampled every 15 seconds.

The soak holds the real deployed application under live playback and background work, periodically checking playback ownership, active-video/Game Center identity, worker health, platform errors, event-loop/runtime state, same-media current-time regressions and browser heap growth when heap telemetry is available. It periodically advances to another game to ensure ownership remains correct across multiple transitions.

## Tier 3 — Controlled Chaos / Recovery

Tier 3 deliberately disturbs non-destructive runtime surfaces and then verifies recovery. It includes a background rerank storm, an aborted concurrent request storm, an expected invalid-route failure, standby-player disruption/re-preparation, repeated resource-mode turbulence, repeated game transitions, and API pressure while playback is manually paused.

Tier 3 is followed by a fresh milestone observation window. Frontend/backend handshake, workers, platform checks, clean errors and playback ownership must all recover before Tier 3 can contribute to overall certification.

## Overall certification rule

The UI may display **FOUNDATION CERTIFIED** only when:

1. Tier 1 = PASS;
2. Tier 2 = PASS for at least the configured 15-minute minimum;
3. Tier 3 = PASS; and
4. the post-chaos recovery window = PASS.

Otherwise overall status remains **CERTIFICATION IN PROGRESS** or **NOT CERTIFIED**.

No certification tier rebuilds or deletes the durable historical catalog and no soundtrack/media upload is required.


## v4.3.6 resilience closure

- MLB extra-inning linescores reconcile a blank decisive extra-inning cell from the final authoritative run total without mutating the source Game Center payload.
- Game Center background work has a scheduler-level 429 circuit breaker. A provider rate limit stops already-queued background jobs for that competition; explicit touch intent remains permitted.
- Tier 3 records provider-circuit boundedness and preserves the complete chaos evidence through the clean post-chaos recovery window.

## v4.3.6 advisory-warning semantics

Tier 3 distinguishes an advisory timing WARN from a failed resilience assertion. A chaos phase that completes all assertions but exceeds its `warnAboveMs` performance target remains visible as WARN evidence and is listed in the exported certificate. It does not by itself fail Tier 3. Any `FAIL` step, failed recovery gate, playback ownership violation, worker-health failure, or other assertion failure still blocks certification. Tier 2 remains strict and does not automatically accept WARN evidence.

This change does not raise the aborted-request-storm 5-second warning target. The threshold remains useful telemetry; the certification gate now interprets it according to its intended severity.

## v4.3.6 soak / playback-progress closure

Tier 2 no longer passes on wall-clock duration alone. A 15-minute run must maintain continuous 15-second telemetry, capture at least 90% of expected samples, keep the maximum sampling gap below 37.5 seconds, and cover essentially the full soak window.

While an active clip reports `playing`, its playback position must continue to advance. More than 45 seconds without forward progress fails Tier 2. More than 45 seconds of sustained buffering also fails Tier 2. Game-to-game transition calls are bounded so a hung transition cannot silently consume the remainder of the soak window.

Unattended playback now treats native/provider playback failure as a recoverable channel event: the failed media asset is marked unusable for the runtime and the board automatically tunes the next eligible item. Explicit score-card sessions preserve their existing exact-game fallback behavior.

The Tier 2 certificate now records sample coverage, observed sample span, maximum sample gap, longest no-progress interval, longest buffering interval, transition timeouts, and observed decode recoveries.


### v4.3.6 startup recovery closure
Tier 1 requires provider-neutral startup recovery: selected media that never reaches a first frame must fail over automatically rather than remain indefinitely in `starting`. The watchdog is assignment-scoped and may not restart the same stalled asset.

### v4.3.8 launch bootstrap recovery closure

The launch button now always enters the canonical PlaybackController path, including when a YouTube iframe exists but has not fired `onReady`. This creates playback-session identity immediately and places cold iframe readiness under the existing bounded 12-second readiness wait and unattended failover controller. The previous launch-only readiness branch could display `starting` without a session, timeout, or watchdog if the iframe never became ready.


### v4.3.8 certification error-evidence closure

Tier 1 no longer fails on an unexplained numeric error count alone. Every error that can block certification is retained in the exported certificate with its timestamp, category/code, source, message, details, recent browser event payload, playback context when available, and browser/runtime identity. If the backend reports a nonzero error count but provides no corresponding error record, the mismatch is preserved as an advisory and cannot by itself fail the tier.

Browser/media interruptions are not broadly whitelisted. Only a known transient media interruption (for example an interrupted browser `play()` promise) may be downgraded to `RECOVERED_ADVISORY`, and only when the same Tier 1 run proves a later successful playback step and ends in a `PLAYING` session with playback ownership invariant `OK`. Any other captured error remains actionable and blocks Tier 1. The post-chaos recovery gate uses the same explicit-record rule but does not downgrade errors without Tier 1 recovery evidence.

The Milestone Console now records browser identity (user agent/client-hints brands, platform, vendor, language, visibility, online state, and available hardware hints) with error events and exposes that identity in the saved certification evidence.
