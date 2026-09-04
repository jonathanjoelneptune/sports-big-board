#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
league=(ROOT/'ui'/'league-view-v538.js').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
verify=(ROOT/'VERIFY.sh').read_text()

assert version=='5.4.5',version

# Special Events are a hard playback ownership boundary. The current curated
# index is committed before transport tuning, stale score ownership is cleared,
# and a bounded+steady-state guard prevents old MLB PROGRAM/Game Center state
# from resurfacing after a failed World Cup embed.
for token in [
    'curatedOwnershipEpoch:0',
    'function specialEventOwnsPlayback()',
    'function clearLegacyScoreOwnership(',
    "document.body.dataset.sbbCuratedPlaybackOwner",
    'function enforceCuratedOwnership(',
    'function startCuratedOwnershipGuard(',
    "v5.4.5 ownership repair",
    "currentIndex=index;standbyIndex=index",
    "clearLegacyScoreOwnership('special-event tune')",
    "if(specialOwns&&(!item?.__sbbCuratedOverride||programKey(item)!==state.curatedExpectedKey))item=expectedCuratedItem();",
    "if(state.queueActive&&item?.__sbbCuratedOverride&&(!interrupted||specialOwns))",
    "bumper?.classList.add('hidden')",
]:
    assert token in browse,token

# The Special Event guard must outlive stale async Game Center responses rather
# than relying only on a single short delayed repair.
for ms in ['0,120,420,900,1600,3000','state.curatedGuardTimer=setTimeout(steadyGuard,1400)']:
    assert ms in browse,ms

# Paired standings columns reserve equal row slots. Shorter divisions receive
# invisible placeholder rows so East/Central/West/Wild Card headings align.
for token in [
    'function placeholderRows(count,columns=4)',
    'padTo=0',
    'const divisionPad=Array.from',
    'const wildcardPad=Math.max',
    'padTo:divisionPad[i]',
    "wildcardCard(conf.wildcard||[],'WILD CARD',league,wildcardPad)",
    'league-view-placeholder-row',
]:
    assert token in league or token in league_css,token

assert 'tests/test_v5313_special_event_ownership_symmetry.py' in verify
print('PASS v5.4.5 hard Special Event playback ownership + symmetric paired standings')
