# Sports Big Board v4.3.1 — Three-Tier Foundation Certification

v4.3.1 changes Foundation Certification from the short v4.3.0 stress certificate into a three-tier release gate. The prior v4.3.0 certificate is retained as Tier 1 baseline evidence only; it is not sufficient for overall Foundation Certification.

## Tier 1 — Functional / Stress Hardening

Runs the release, playback, historical-read, operator-load, resource-mode, Game Center, soundtrack and responsiveness procedures plus a dedicated regression-hardening procedure.

The hardening procedure specifically verifies:

- production startup has no legacy NBA/demo seed programming;
- browsing dates or league filters never autoplays Silver roundup media;
- Game Center follows the active game video after direct selection, Next and automatic A/B promotion;
- a manual pause remains latched for at least 25 seconds under background refresh;
- background programming refresh cannot silently replace/restart the active media selection.

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
