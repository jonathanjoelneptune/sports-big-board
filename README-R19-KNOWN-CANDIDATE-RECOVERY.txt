Sports Big Board v5.5.0 — R19 Known Candidate Recovery

Purpose
-------
Fix the Repair Engine behavior observed after R18 where existing event media was counted as "known" and skipped even when it was an eligible Green/Purple repair candidate.

Runtime behavior
----------------
1. For every actionable repair job, R19 first ranks and recertifies eligible known event media.
2. DEGRADED -> PREFERRED tests only known Green/Purple (extended) candidates.
3. Definitive hard failures remain excluded. Soft/inconclusive media remains eligible.
4. The initial known-candidate pass is bounded to 3 candidates by default (SBB_MEDIA_REPAIR_KNOWN_CANDIDATE_LIMIT).
5. A candidate is tested at most once per repair attempt unless registered-provider discovery changes its browser-facing transport.
6. Same assetKey + changed transport is explicitly allowed one fresh recertification.
7. New discovery remains the fallback after known candidates fail.
8. R18-exhausted WAITING_RETRY jobs receive one immediate R19 pass, then normal cooldowns resume.
9. Operator telemetry now separates "eligible known" candidates and transport refreshes.

Repository files
----------------
media_audit_service.py
media-audit.html
ui/media-audit-v550.js
tests/test_v550_media_health_audit.py
tests/test_r18_media_repair_transport.py
tests/test_r19_known_candidate_recovery.py

No VERSION bump: semantic website version remains 5.5.0.
