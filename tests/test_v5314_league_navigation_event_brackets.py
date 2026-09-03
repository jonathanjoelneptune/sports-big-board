#!/usr/bin/env python3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
browse_css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
league=(ROOT/'ui'/'league-view-v538.js').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
backend_path=ROOT/'sbb'/'league_view_v538.py'
backend=backend_path.read_text()
verify=(ROOT/'VERIFY.sh').read_text()
assert version=='5.3.15',version

# Special Event stale YouTube/MLB callbacks cannot paint an old external card.
for token in [
    'function clearForeignFallbackPresentation(item)',
    'bumper.dataset.sbbCuratedFallbackKey=programKey(item)',
    'function patchYouTubePlayerError()',
    'onPlayerError.__sbbBrowseV5314',
    'Date.now()-start<12000',
    "handlePlaybackFailure(slot,new Error(`YouTube player error ${code}`),false)",
    'const specialOwned=curated&&!!state.specialContext',
    "document.body?.classList.add('sbb-special-event-match-center')",
]: assert token in browse,token
for token in ['body.sbb-special-event-match-center #gameCenterContent','body.sbb-special-event-match-center #gameCenterEmpty']:
    assert token in browse_css,token

# League selection exposes TODAY + ALL + Team Browse and drives League View before playback.
for token in [
    'id="sbbLeagueTodayBtn"', 'id="sbbLeagueAllBtn"',
    "window.dispatchEvent(new CustomEvent('sbb:league-context'",
    "$('sbbLeagueTodayBtn')?.addEventListener('click'",
    "$('sbbLeagueAllBtn')?.addEventListener('click'",
]: assert token in browse,token
for token in ["if(state.navLeague)","window.addEventListener('sbb:league-context'","window.addEventListener('sbb:score-click-selection',()=>{state.navLeague='';"]:
    assert token in league,token
assert 'state.contextPoll=setInterval' not in league

# Special Events have local bracket/group views; soccer tables carry last-five form.
for token in ['function specialEventBoard(','function groupStandings(','function bracketBoard(','eventGames:(state.specialEventGames.length?state.specialEventGames:state.games)']:
    assert token in browse+league,token
for token in ['function formMarkup(form=[])',"['CLUB','MP','W-D-L','PTS','FORM']",'league-view-form i.win','league-view-event-group-grid','league-view-bracket-grid','.league-view-nhl{gap:5px!important}']:
    assert token in league+league_css,token
for token in ['def _recent_form(payload):','def _apply_recent_form(groups, form):','if league in {"EPL", "MLS"}:','dates={start_day}-{end_day}']:
    assert token in backend,token

# Prove recent-form helper keeps the newest five outcomes.
spec=spec_from_file_location('sbb_test_lv5314',backend_path);mod=module_from_spec(spec);spec.loader.exec_module(mod)
payload={'events':[]}
for i,result in enumerate([(2,0),(1,1),(0,1),(3,1),(0,2),(4,2)]):
    a,b=result
    payload['events'].append({'date':f'2026-08-{20+i:02d}T00:00:00Z','status':{'type':{'state':'post','completed':True}},'competitions':[{'competitors':[{'team':{'id':'A','abbreviation':'AAA'},'score':a},{'team':{'id':'B','abbreviation':'BBB'},'score':b}]}]})
form=mod._recent_form(payload)
assert form['AAA']==['D','L','W','L','W'],form['AAA']
assert 'tests/test_v5314_league_navigation_event_brackets.py' in verify
print('PASS v5.3.15 league navigation + Special Event bracket/Match Center + stable refresh + soccer form + NHL width')
