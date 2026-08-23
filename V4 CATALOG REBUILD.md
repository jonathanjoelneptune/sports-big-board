# Sports Big Board v4.0.1 Historical Catalog Rebuild

v4 uses an offline reconstruction rather than an in-place relationship migration. The old database is evidence; the rebuilt database is the new authority.

## Production flow

```text
stop backend
  -> inspect history.sqlite3 without mutating it
  -> SQLite backup: backups/history-pre-v4-<timestamp>.sqlite3
  -> build: cache/history-v4-rebuild.sqlite3
  -> write reconciliation JSON report
  -> integrity gates
  -> atomic install as cache/history.sqlite3
  -> start v4 backend
  -> backend + public health checks
```

GitHub deployment performs this flow automatically on the first v4 release. If application health later fails, deployment restores the pre-v4 database and previous application release together.

## Interrupted-transition recovery

v4 readiness is not inferred from `catalog_schema_version=4` alone. Preflight also checks normalized source/event/collection structure and then runs the hard catalog integrity gate. Recovery follows this order:

1. Valid, complete v4 catalog -> use it without rebuilding.
2. Incomplete/invalid v4 catalog with preserved legacy rows -> reconstruct from the live database as evidence.
3. Incomplete/invalid v4 catalog without enough legacy evidence -> reconstruct from the newest usable `backups/history-pre-v4-*.sqlite3`.
4. No trustworthy reconstruction source -> refuse the deployment without replacing the catalog.

This specifically protects against interrupted additive-schema transitions where v4 tables/meta exist but normalized `history_source_media` or association rows were never successfully built.

## Manual rebuild

With the backend stopped:

```bash
python3 tools/rebuild_history_v4.py \
  --source /var/lib/sports-big-board/cache/history.sqlite3 \
  --output /var/lib/sports-big-board/cache/history-v4-rebuild.sqlite3 \
  --report /var/lib/sports-big-board/backups/history-v4-manual.report.json \
  --force
```

Inspect the report. Install only after `"passed": true`:

```bash
python3 tools/rebuild_history_v4.py \
  --source /var/lib/sports-big-board/cache/history.sqlite3 \
  --output /var/lib/sports-big-board/cache/history-v4-rebuild.sqlite3 \
  --report /var/lib/sports-big-board/backups/history-v4-manual.report.json \
  --force --install
```

`REBUILD-HISTORY-V4.sh` provides the same safe build/report workflow but deliberately does not install automatically.

## Release-blocking integrity gates

A rebuild cannot install if any of these are nonzero/false:

- Silver asset assigned as GAME
- GAME asset linked into a Silver collection
- assigned GAME relationship below association-confidence threshold
- source GAME asset assigned to multiple canonical events
- low-confidence collection link
- unaccounted source media
- wrong catalog schema generation

Quarantined and unassigned assets are **accounted for**, not failures. They remain in the source reservoir and review queue for future matcher/classifier improvements.

## Post-deployment audit endpoints

```text
/api/history/catalog/integrity
/api/history/catalog/review
/api/history/catalog/attempts
/api/history/catalog/collections
/api/history/audit
/api/history/roundups
```

The event audit uses UNINDEXED, SEARCHED EMPTY, COVERAGE COMPLETE, UPGRADE PENDING, QUALITY COMPLETE, PROVIDER DEGRADED, and CANDIDATE ONLY so migration/index backlog is distinct from a real searched-empty result.
