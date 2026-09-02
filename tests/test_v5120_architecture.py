from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
date=(ROOT/'architecture/date-transition-coordinator.js').read_text(encoding='utf-8')
tennis=(ROOT/'architecture/tennis-presentation.js').read_text(encoding='utf-8')
gc=(ROOT/'ui/game-center-view.js').read_text(encoding='utf-8')
index=(ROOT/'index.html').read_text(encoding='utf-8')
version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()

assert version=='5.1.20'
assert 'Sports Big Board — v5.1.20' in index
assert 'architecture/tennis-presentation.js?v=5.1.20' in index
assert 'architecture/date-transition-coordinator.js?v=5.1.20' in index
assert 'ui/game-center-view.js?v=5.1.20' in index
assert '5.1.19' not in index

# Historical date convergence: pending/slow is loading, only complete zero inventory is empty.
assert "const CONVERGENCE_DELAYS=" in date
assert 'authoritativeEmpty:complete&&games===0' in date
assert "state.firstPaintSource='DAY_STATE_LOADING'" in date
assert "paintPendingRibbon(date,generation,'Loading games…')" in date
assert 'void converge(date,generation,payload)' in date
assert 'timeoutMs:2200' in date

# Game Center: same identity joins; different identity/explicit retry aborts; UI has a terminal watchdog.
assert 'activeRequest&&activeRequest.key===key' in gc
assert "abortActive(force?'Explicit Game Center retry':'Different Game Center selected')" in gc
assert 'const UI_WATCHDOG_MS=12000' in gc
assert 'Game Center did not finish loading within 12 seconds' in gc

# Tennis is prepared before card creation, and no requestAnimationFrame presentation mutation remains.
assert '__sbbTennisProjectionV5120' in tennis
assert 'return original.call(this,league,date,prepareRows(league,rows));' in tennis
assert 'requestAnimationFrame(' not in tennis
for label in ('ROUND 1','ROUND 2','ROUND 3','R16','SEMIS','FINAL'):
    assert label in tennis
assert 'flagEmoji' in tennis and 'countryCodeOf' in tennis
print('PASS v5.1.20 architecture invariants')
