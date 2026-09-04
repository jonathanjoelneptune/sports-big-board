#!/usr/bin/env python3
"""Static controller-readiness invariants for Sports Big Board v5.4.7."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
index=(ROOT/'index.html').read_text(encoding='utf-8')
module=(ROOT/'architecture'/'controller-readiness-v540.js').read_text(encoding='utf-8')
css=(ROOT/'ui'/'controller-readiness-v540.css').read_text(encoding='utf-8')
region_map=(ROOT/'CONTROLLER-REGION-MAP-v5.4.7.md').read_text(encoding='utf-8')

parts=tuple(int(x) for x in VERSION.split('.'))
assert parts >= (5,4,0),VERSION
assert f'ui/controller-readiness-v540.css?v={VERSION}' in index
assert f'architecture/controller-readiness-v540.js?v={VERSION}' in index
assert index.index(f'architecture/operator-module-loader.js?v={VERSION}') < index.index(f'architecture/controller-readiness-v540.js?v={VERSION}')
assert f"const VERSION='{VERSION}'" in module
assert "mode:'READINESS_ONLY_NO_GAMEPAD_BINDINGS'" in module

# The readiness module remains a pure semantic foundation even after controller
# bindings ship in a separate module. It must never poll/bind the Gamepad API itself.
for forbidden in ['navigator.getGamepads','gamepadconnected','gamepaddisconnected','requestAnimationFrame(gamepad','setInterval(pollGamepad']:
    assert forbidden not in module, forbidden

required_regions=[
    'launch','global-header','league-nav','date-nav','sports-ticker','score-ribbon','system-status',
    'left-nav','now-watching','player-alternates','player-transport','soundtrack','player-stage',
    'transition-overlay','playback-terminal','player-utilities','drawer-tabs','game-center',
    'sport-match-center','league-view','settings','coming-up','team-browse','special-events',
    'date-picker','milestone-console','history-audit','developer-tools','modal','global-utility'
]
for region in required_regions:
    assert f"name:'{region}'" in module or f"name:FALLBACK_REGION" in module and region=='global-utility', region
    assert f'`{region}`' in region_map or f'| `{region}` |' in region_map, f'region map: {region}'

# All current control primitives and dynamic card controls are part of the generic
# registry. Any future unmatched actionable remains reachable via global-utility
# but causes the runtime audit to WARN until a semantic mapping is added.
for token in [
    "'button'","'a[href]'","'input:not([type=\"hidden\"])'","'select'","'textarea'",
    "'video[controls]'","'[role=\"button\"]'","'[role=\"tab\"]'","'.score-cell'","'.score-card'",
    "'.queue-item'","'.next-up-dock-card'","'[data-curation-index]'",
    "const FALLBACK_REGION='global-utility'",'dataset.sbbRegionFallback','fallbackSamples'
]:
    assert token in module,token

# Stable semantic focus identity, custom keyboard bridging, region memory and
# geometry navigation are mandatory foundation pieces.
for token in [
    "el.dataset.sbbFocusable='1'","el.dataset.sbbRegion=region",'data-sbb-focus-id',
    "el.dataset.sbbKeyboardBridge='1'","event.key==='Enter'||event.key===' '",
    'REGION_MEMORY_KEY','focusMemory[region]','directionalScore','bestDirectional',
    "move(direction",'preferredEntry','activeModalRoot','ensureVisible','navigateBack',
    'SBB_SEMANTIC_NAVIGATION','SBB_INTERACTION_REGIONS','SBB_INPUT_OWNERSHIP'
]:
    assert token in module,token

# One dynamic observer is allowed only for child insertion. Registration adds
# attributes, so observing attributes would risk recreating the v5.3.19 feedback loop.
assert module.count('new MutationObserver')==1
assert "mutationObserver.observe(document.body,{childList:true,subtree:true})" in module
assert 'attributes:true' not in module
assert 'attributeFilter:' not in module

# Last meaningful input wins foundation. Pointer jitter cannot take ownership.
for token in [
    'POINTER_MOVE_THRESHOLD=10',"claimInput('pointer',{reason:'pointer down'})",
    "claimInput('pointer',{reason:'wheel'})",'Math.hypot(',
    "claimInput('keyboard',{reason:`key:${event.key}`})","['pointer','keyboard','controller']"
]:
    assert token in module,token

# Back behavior covers all current deep contexts before leaving a league/root.
for token in [
    '#milestoneConsoleClose','#historyAuditClose','#sbbBrowseClose','#sbbSpecialEventsBtn',
    '#sbbFocusExit','#sbbSpecialExitBtn','#infoDrawerClose','[data-score-filter="ALL"]'
]:
    assert token in module,token

# Focus treatment is high contrast, team-theme compatible, and non-animated.
for token in ['[data-sbb-controller-focus="1"]','--sbb-focus-accent','outline:2px solid','box-shadow:0 0 0 5px','prefers-reduced-motion']:
    assert token in css,token
for forbidden in ['animation:','backdrop-filter','filter:blur(']:
    assert forbidden not in css,forbidden

# Index has a large static interaction surface; the generic registry must remain
# present rather than relying on a hand-maintained list of button ids.
static_controls=len(re.findall(r'<(?:button|input|select|textarea)\b',index,re.I))+len(re.findall(r'<a\b[^>]*href=',index,re.I))
assert static_controls>=80,static_controls
assert 'querySelectorAll(ACTIONABLE_SELECTOR)' in module
assert 'uncovered.length===0&&duplicateIds.length===0&&fallback.length===0' in module


# Static markup coverage audit using only Python stdlib. Dynamic controls are
# covered by ACTIONABLE_SELECTOR + child-list registration; this proves that every
# actionable control shipped directly in index.html already lives in a specific
# semantic region rather than depending on the global fallback.
from html.parser import HTMLParser
class StaticRegionAudit(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.controls=[]; self.unmapped=[]
    @staticmethod
    def region_for(tag,attrs,parent_region):
        a=dict(attrs); ident=a.get('id',''); classes=set(a.get('class','').split())
        if ident in {'launchScreen','localFileWarning'}: return 'launch'
        if ident=='sbbSpecialEventsMenu': return 'special-events'
        if ident=='milestoneConsoleModal': return 'milestone-console'
        if ident=='historyAuditModal': return 'history-audit'
        if ident=='leagueViewRoot': return 'league-view'
        if ident=='settingsPane': return 'settings'
        if ident in {'gameCenterPane','gameCenterContent'}: return 'game-center'
        if ident=='upNextPane' or 'drawer-queue-panel' in classes: return 'coming-up'
        if 'info-drawer-head' in classes or 'info-drawer-tabs' in classes: return 'drawer-tabs'
        if ident in {'bumper','videoLoadingOverlay','searchPriorityPlaybackLock'}: return 'transition-overlay'
        if ident=='playbackTerminal': return 'playback-terminal'
        if ident in {'soundtrackControls','soundtrackVolumePopover'}: return 'soundtrack'
        if ident=='recapAltButtons': return 'player-alternates'
        if 'transport' in classes: return 'player-transport'
        if 'utility-controls' in classes: return 'player-utilities'
        if ident=='stage' or 'stage' in classes: return 'player-stage'
        if 'now-playing-copy' in classes: return 'now-watching'
        if 'left-rail' in classes: return 'left-nav'
        if 'top-date-controls' in classes or ident in {'scoreDayPager','scoreDayIndicator','scoreDatePicker','scoreDayPagerRight'}: return 'date-nav'
        if ident=='scoreFilters': return 'league-nav'
        if 'top-nav-header' in classes: return 'global-header'
        if 'key-info-ribbon' in classes or ident=='keyInfoTrack': return 'sports-ticker'
        if 'score-ribbon' in classes or ident in {'scoreCells','sbbCurationCards'}: return 'score-ribbon'
        if 'mobile-live-bar' in classes or 'sport-feed-diagnostics' in classes or ident=='coveragePipeline' or 'coverage-pipeline' in classes: return 'system-status'
        if ident=='playbackDebug' or 'sbb-dev-global-card' in classes: return 'developer-tools'
        if a.get('role')=='dialog' or 'modal' in classes or 'popover' in classes: return 'modal'
        return parent_region
    @staticmethod
    def actionable(tag,attrs):
        a=dict(attrs)
        if tag=='a': return bool(a.get('href'))
        if tag=='input': return a.get('type','').lower()!='hidden'
        if tag in {'button','select','textarea','summary'}: return True
        if tag in {'video','audio'}: return 'controls' in a
        role=a.get('role','')
        return role in {'button','tab','menuitem','option','link'}
    def handle_starttag(self,tag,attrs):
        parent=self.stack[-1] if self.stack else None
        region=self.region_for(tag,attrs,parent)
        self.stack.append(region)
        if self.actionable(tag,attrs):
            a=dict(attrs); label=a.get('id') or a.get('aria-label') or f'<{tag}>'
            self.controls.append((label,region))
            if not region:self.unmapped.append(label)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs); self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if self.stack:self.stack.pop()

static_audit=StaticRegionAudit(); static_audit.feed(index)
assert len(static_audit.controls)>=80,len(static_audit.controls)
assert not static_audit.unmapped,static_audit.unmapped

print(f'PASS v{VERSION} controller readiness: complete semantic regions + stable focus ids + geometry/back/input foundation')
