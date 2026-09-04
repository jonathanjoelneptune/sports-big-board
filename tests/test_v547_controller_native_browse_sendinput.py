#!/usr/bin/env python3
"""v5.4.7 controller-native Team/Player Browse and SendInput fullscreen bridge."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.4.7',VERSION
core=(ROOT/'architecture'/'controller-mode-v542.js').read_text()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
bridge=(ROOT/'architecture'/'controller-native-bridge-v544.js').read_text()
fs=(ROOT/'ui'/'fullscreen-controller-v545.js').read_text()
cs=(ROOT/'windows-controller-bridge'/'SportsBigBoardControllerBridge.cs').read_text()
verify=(ROOT/'VERIFY.sh').read_text()
map_txt=(ROOT/'CONTROLLER-REGION-MAP-v5.4.7.md').read_text()

# Team/player selection itself remains inside radial UI and is paginated.
assert 'const ENTITY_RADIAL_PAGE_SIZE=6' in core
assert "openRadial('entity-browse'" in core
assert "else if(type==='entity-browse')options=entityBrowseOptions(context);" in core
assert 'function entityBrowseOptions(context={})' in core
assert "label:'NEXT ▶'" in core and "label:'◀ PREV'" in core and "label:'BACK'" in core
assert 'browseApi()?.controllerEntities?.(league)' in core
assert 'browseApi()?.browseEntity?.(name)' in core
assert "return playerBrowseLeague(league)?'PLAYER BROWSE':'TEAM BROWSE';" in core
assert 'async function controllerEntitiesForLeague(league)' in browse
assert 'controllerEntities:league=>controllerEntitiesForLeague(league)' in browse

# Core leagues and Special Events use the same native browse radial path.
assert "openBrowseForLeague(league,{label:context.label||league,parent:'league-scope'})" in core
assert "openBrowseForLeague(league,{label:context.label||league,parent:'special-scope',special:true})" in core

# Windows fullscreen is injected with SendInput first, with legacy fallback only second.
assert 'private static extern uint SendInput' in cs
assert 'INPUT[] inputs = new INPUT[] { down, up };' in cs
assert 'uint sent = SendInput' in cs
assert 'if (sent == (uint)inputs.Length) return true;' in cs
assert 'keybd_event(key, 0, 0, UIntPtr.Zero);' in cs
assert 'HandleCommand(commandFrame, stream)' in cs
assert r'{\"type\":\"command-result\"' in cs

# Browser receives an explicit command acknowledgement/failure signal.
assert "if(payload.type==='command-result')" in bridge
assert 'lastCommandOk=payload.ok===true' in bridge
assert 'lastCommand,lastCommandOk,lastCommandAt' in bridge
assert 'function bindBridgeResults()' in fs
assert "detail?.reason!=='command-result'" in fs
assert "showToast('Sending app fullscreen…')" in fs

assert 'tests/test_v547_controller_native_browse_sendinput.py' in verify
for token in ['Controller-native Team / Player Browse','SendInput','command-result']:
    assert token in map_txt,token
print('PASS v5.4.7 controller-native team/player browse + SendInput fullscreen bridge acknowledgement')
