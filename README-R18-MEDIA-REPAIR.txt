Sports Big Board — R18 Media Repair Transport

This is a targeted implementation bundle for the zero-promotion repair problem observed in R17.

Root fixes:
1. ESPN generic search now reuses the existing nested direct-media resolver.
2. ESPN search no longer emits image/article-only rows as playable repair candidates.
3. ESPN search IDs are deterministic across process restarts.
4. Repair URL selection prefers real video transport fields before external URLs.
5. Existing R17 WAITING_RETRY degraded/unplayable/no-media jobs receive one immediate R18 retry.
6. History canonical URL normalization recognizes videoUrl/videoURL/streamUrl/playbackUrl.
7. Regression guards cover all of the above.

Recommended application:
  python tools/apply_r18_media_repair.py --dry-run .
  python tools/apply_r18_media_repair.py .
  python -m unittest tests.test_r18_media_repair_transport

The patcher is fail-closed: it only edits the exact R17 source shapes verified against the live main repository.
