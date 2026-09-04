#!/usr/bin/env python3
"""v5.4.6 controller navigation, fullscreen, commands, and playback-follow regression."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.4.6',VERSION
index=(ROOT/'index.html').read_text()
core=(ROOT/'architecture'/'controller-mode-v542.js').read_text()
nav=(ROOT/'architecture'/'controller-readiness-v540.js').read_text()
bridge=(ROOT/'architecture'/'controller-native-bridge-v544.js').read_text()
cs=(ROOT/'windows-controller-bridge'/'SportsBigBoardControllerBridge.cs').read_text()
fs=(ROOT/'ui'/'fullscreen-controller-v545.js').read_text()
follow=(ROOT/'ui'/'score-ribbon-playback-follow-v545.js').read_text()
follow_css=(ROOT/'ui'/'score-ribbon-playback-follow-v545.css').read_text()
map_txt=(ROOT/'CONTROLLER-REGION-MAP-v5.4.6.md').read_text()

# Release wiring.
for asset in [
 'ui/fullscreen-controller-v545.css','ui/score-ribbon-playback-follow-v545.css',
 'ui/score-ribbon-playback-follow-v545.js','ui/fullscreen-controller-v545.js',
 'architecture/controller-mode-v542.js','architecture/controller-readiness-v540.js'
]:
    assert f'{asset}?v={VERSION}' in index, asset

# D-pad score-ribbon -> league lane and deterministic horizontal traversal.
assert "region==='score-ribbon'&&direction==='up'" in nav
assert "candidate=preferredEntry('league-nav')" in nav
assert 'function orderedLeagueNeighbor' in nav
assert "region==='league-nav'" in nav
assert "focusables('league-nav'" in nav

# X/Square is now play/pause, not Play All.
assert '<b>${g.x}</b> Play / Pause' in core
assert 'if(index===BUTTON.X){playPause();return;}' in core
assert 'function playPause()' in core
assert 'if(index===BUTTON.X){playAll();return;}' not in core

# Both triggers open the special commands radial and mute is an explicit action.
assert "openRadial('commands')" in core
assert "radial?.type==='commands'" in core
for token in ["APP FULLSCREEN","VIDEO FULLSCREEN","EXIT FULLSCREEN","PLAY / PAUSE","MUTE / UNMUTE","GAME CENTER","LEAGUE VIEW","SETTINGS"]:
    assert token in core,token
assert 'function toggleActiveMute()' in core
assert "v.muted=!v.muted" in core and 'p.isMuted' in core and 'p.unMute' in core and 'p.mute' in core

# Fullscreen app button and controller fullscreen commands.
assert 'bigBoardFullscreenBtn' in fs and 'fullscreenBtn' in fs
assert 'requestFullscreen(appTarget(),{navigationUI:true})' in fs
assert "nativeCommand('app-fullscreen')" in fs and "nativeCommand('video-fullscreen')" in fs
assert "new Set(['app-fullscreen','video-fullscreen'])" in bridge
assert 'KeyboardCommand.Tap(0x7A)' in cs and 'KeyboardCommand.Tap(0x46)' in cs
# Retain compile hotfix.
assert 'new Thread(new ThreadStart(delegate { HandleClient(client); }))' in cs

# ALL/score ribbon follows the actual playing event and keeps it near third visible.
assert 'sbb-program-now-watching' in follow and 'sbb-program-now-watching' in follow_css
assert 'Math.max(0,idx-2)' in follow
assert "return clean(active?.dataset?.scoreFilter).toUpperCase()==='ALL';" in follow
assert 'requestAnimationFrame(run)' in follow
assert 'setInterval(' not in follow
assert 'NOW WATCHING' in follow_css

for token in ['X — Play / Pause','LT + RT — Special Commands radial','MUTE / UNMUTE','D-pad Up from the Score Ribbon']:
    assert token in map_txt,token

print('PASS v5.4.6 D-pad league navigation + X play/pause + special commands + fullscreen + playback-follow')
