# Sports Big Board v4.3.0 — Foundation Certification

v4.3.0 is a certification release for the hardened v4.2.x platform. It intentionally does **not** add another feature layer, rebuild the historical catalog, re-upload soundtrack assets, or change the ownership model for playback, discovery, Game Center, or background workers.

## Why v4.3.0 exists

The final v4.2.2 dev stress run demonstrated that the repaired platform can pass the complete live exercise, but the Milestone Release Console could still remain in an overall ERROR state because its observation window retained pre-fix errors and old latency samples. That is useful for diagnostics but unsuitable as a formal release verdict.

Foundation Certification separates those two concerns:

1. Diagnostic telemetry may remain cumulative during normal development.
2. A certification run begins by resetting only the in-memory milestone observation window.
3. The existing eight release procedures run unchanged.
4. A formal gate evaluator produces CERTIFIED or NOT_CERTIFIED from evidence created after that reset.
5. The result can be copied or saved as JSON.

The reset does not delete or rebuild durable sports, media, historical, settings, or soundtrack data.

## Blocking runtime gates

- Release handshake: frontend and backend must both report v4.3.0.
- Stress suite: the existing stress suite must finish PASS.
- Eight procedures: release handshake, playback cycle, historical read, operator load, resource modes, Game Center, soundtrack, and UI responsiveness must all pass.
- No step debt: no recorded stress step may be WARN, FAIL, or SKIP.
- Platform checks: every server-supplied platform check must pass.
- Clean-window errors: no ERROR-class release problems may be created in the certification window. Warnings remain visible as non-blocking observations unless they fail another gate.
- Playback ownership: the one-audio playback invariant must remain OK.
- Worker health: all registered historical/background workers must be healthy.
- State restoration: the stress runner must restore playback, date, drawer, soundtrack, and resource mode without a restoration error.
- Legacy read isolation: `/api/history/day` must not be used in the certification window. Date-scoped ribbon, roundup, discovery, and audit APIs remain the interactive path.

## Build-time gates

`VERIFY.sh` runs both the existing release-generation checker and `tools/check_foundation_certification.py` before the full Python regression suite. The normal deployment workflow therefore refuses to deploy a mixed or incomplete Foundation Certification build.

## Acceptance procedure after deployment

1. Open Sports Big Board normally and allow the app to reach a stable state.
2. Open Settings → Foundation Certification Console.
3. Click **RUN FOUNDATION CERTIFICATION**.
4. Allow the suite to finish without manually changing playback or resource mode.
5. Confirm the result reads **FOUNDATION CERTIFIED** and every gate is PASS.
6. Use **SAVE JSON** to retain the release certificate with the stress run ID and gate evidence.
7. The normal GitHub production smoke and 15-minute deployment watchdog remain responsible for frontend/backend deployment convergence.

## Certification boundary

The v4.3.0 certificate proves the foundation at the time and observation window in which it is run. Historical diagnostic errors from before the clean-window boundary remain useful in prior logs, but they do not contaminate the new certificate.
