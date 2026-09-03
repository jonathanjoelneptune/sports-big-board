#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'game-center-scroll-v5220.css').read_text()
gcjs=(ROOT/'ui'/'game-center-scroll-v5220.js').read_text()
interrupt=(ROOT/'architecture'/'score-interrupt-queue-v5220.js').read_text()
upnext=(ROOT/'ui'/'up-next-experience-v5217.js').read_text()

assert version=='5.3.0', version
assert f'ui/game-center-scroll-v5220.css?v={version}' in index
assert f'<script src="architecture/score-interrupt-queue-v5220.js?v={version}"></script>' in index
assert f'<script src="ui/game-center-scroll-v5220.js?v={version}"></script>' in index

for token in [
    '#gcContentScroller{',
    'overflow-y:scroll!important',
    'scrollbar-gutter:stable!important',
    '#gcContentScroller>[data-gc-pane]:not(.hidden){',
    'overflow:visible!important',
    '#gameCenterPane>.next-up-dock{',
]:
    assert token in css, token

for token in [
    'SBB_GAME_CENTER_SCROLL',
    'ensureScroller()',
    "content.querySelectorAll(':scope > [data-gc-pane]')",
    'scroller.appendChild(pane)',
    'scroller.scrollTop=0',
]:
    assert token in gcjs, token

for token in [
    'SBB_SCORE_INTERRUPT_QUEUE',
    "event.target?.closest?.('.score-card')",
    'program:[...PROGRAM]',
    'resumeItemId',
    'resumeGameKey',
    'PROGRAM=[...snap.program]',
    'resumeDateProgramAfterSelection=wrapped',
    'automatic resume after score-ribbon interrupt',
]:
    assert token in interrupt, token

for token in [
    "state.source='score-interrupt-projection'",
    'window.SBB_SCORE_INTERRUPT_QUEUE?.entries?.(wanted)',
    'entry?.interruptResume&&window.SBB_SCORE_INTERRUPT_QUEUE?.play?.(entry)',
    'renderInterruptQueueList()',
    'RESUMES AFTER SELECTED HIGHLIGHT',
]:
    assert token in upnext, token

for forbidden in ['setInterval(', 'requestAnimationFrame(loop', 'new MutationObserver']:
    assert forbidden not in interrupt, forbidden
    assert forbidden not in gcjs, forbidden

app=index.index(f'<script src="app.js?v={version}"></script>')
interrupt_pos=index.index(f'<script src="architecture/score-interrupt-queue-v5220.js?v={version}"></script>')
upnext_pos=index.index(f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>')
read_css=index.index(f'ui/game-center-readability-v5219.css?v={version}')
scroll_css=index.index(f'ui/game-center-scroll-v5220.css?v={version}')
read_js=index.index(f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>')
scroll_js=index.index(f'<script src="ui/game-center-scroll-v5220.js?v={version}"></script>')
assert app < interrupt_pos < upnext_pos
assert read_css < scroll_css < index.index('</head>')
assert read_js < scroll_js

for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset}: {found} != {version}'

print('PASS v5.3.0 explicit Game Center scrollbar + preserved score-interrupt programming queue')
