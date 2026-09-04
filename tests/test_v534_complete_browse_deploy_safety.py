#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
js=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
deploy=(ROOT/'cloud'/'gcp'/'DEPLOY-FROM-GITHUB.sh').read_text()

assert version=='5.4.9', version
assert f'ui/browse-curated-programming-v537.css?v={version}' in index
assert f'<script src="ui/browse-curated-programming-v537.js?v={version}"></script>' in index

# Browse inventory is competition-wide and independent from the selected date.
for token in [
    'const MAX_ENTITY_AUDIT_ROWS=10000;',
    'entityCatalogInflight:new Map()',
    'async function fetchFullEntityCatalog(league,',
    "bestMediaForAuditRow(row).items.length",
    "while(offset<total&&rows.length<MAX_ENTITY_AUDIT_ROWS)",
    'persistEntityCatalog(league,names,entities=[]',
    "Building complete ${state.entityType==='player'?'player':'team'} library once; future opens are instant.",
    'host.innerHTML=merged.map(name=>',
    "reason:'league-change'",
    'async function searchSuggestions(value)',
    'const names=await primeEntityCatalog({render:false})',
]:
    assert token in js, token

# The old current-day-only / first-page shortcuts must not own the list.
for forbidden in [
    'Math.min(MAX_AUDIT_ROWS,500)',
    'merged.slice(0,60)',
    'fetchAuditPage({league:state.league,q:query,offset:0,limit:100,token})',
]:
    assert forbidden not in js, forbidden

# Deployment must reclaim the stale rollback copies that caused disk exhaustion,
# avoid making another full relationship-only snapshot, and make audit-only
# dispatch pure before server startup.
for token in [
    "history-pre-relation-repair-v*.sqlite3",
    '[storage] Reclaiming stale deployment-only storage before upload',
    '--check-only',
    'Structurally healthy normalized catalog preserved in place',
    'database-authority audit-only contract not found',
    '"event": _event_audit(self), "collection": _collection_audit(self)',
    'less than 256 MiB free after safe cleanup',
]:
    assert token in deploy, token

print('PASS v5.4.9 complete competition Browse inventory + disk-safe audit-only deployment')
