#!/usr/bin/env python3
"""Fail CI when Sports Big Board is assembled from mixed release generations.

Deployment release identity is independent of component/module versions. VERSION,
architecture/VERSION, index metadata/cache generation, frontend handshake callers,
and backend APP_VERSION must all agree on the one deployment release.
"""
from pathlib import Path
import re

root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text(encoding='utf-8').strip()
errors=[]

def text(path):
    p=root/path
    if not p.is_file():
        errors.append(f'missing release-integrity file: {path}')
        return ''
    return p.read_text(encoding='utf-8')

if not re.fullmatch(r'\d+\.\d+\.\d+',version):
    errors.append(f'VERSION is not semantic: {version!r}')

architecture_version=text(Path('architecture')/'VERSION').strip()
if architecture_version!=version:
    errors.append(f'architecture/VERSION={architecture_version!r}; expected {version!r}')

index=text(Path('index.html'))
if f'<title>Sports Big Board — v{version}</title>' not in index:
    errors.append('index title does not match VERSION')
if 'const tabTitle=`Sports Big Board — v${version}`' not in index or "window.addEventListener('pageshow',syncTabTitle)" not in index:
    errors.append('browser tab title is not reasserted from canonical release identity')
if f'<meta name="sbb-release-version" content="{version}"' not in index:
    errors.append('index canonical sbb-release-version meta does not match VERSION')
if 'window.SBB_RELEASE_VERSION=version' not in index or 'window.SBB_RELEASE=Object.freeze' not in index:
    errors.append('index does not establish the canonical frontend release authority')
if 'sbbLegacyCoreReleaseProjection' not in index:
    errors.append('index is missing the compatibility projection for legacy release consumers')

asset_refs=re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index)
for asset,found in asset_refs:
    if found!=version:
        errors.append(f'stale cache generation {found} on {asset}; expected {version}')

settings=text(Path('ui')/'settings-view.js')
if re.search(r"(?:SBB_RELEASE_VERSION\s*=|SBB_CORE\s*=).*?['\"]\d+\.\d+\.\d+['\"]",settings,re.S):
    errors.append('settings-view contains a hard-coded deployment release assignment')
if 'window.SBB_RELEASE_VERSION=' in settings:
    errors.append('settings-view must never assign SBB_RELEASE_VERSION')
if 'window.SBB_CORE=Object.freeze' in settings:
    errors.append('settings-view must never rewrite SBB_CORE release metadata')
if 'window.SBB_RELEASE?.version||window.SBB_RELEASE_VERSION' not in settings:
    errors.append('settings-view does not read canonical release identity')
if '/api/release-identity?frontendVersion=' not in settings:
    errors.append('settings-view does not report canonical frontend identity to backend')

# The tuner must be directly available in Settings. Dev Mode still unlocks the
# remaining diagnostic utilities, but ticker tuning is an operator setting.
if 'class="settings-card sports-ticker-dev-card"' not in index:
    errors.append('Sports Ticker tuning card is not statically present in Settings')
if 'sports-ticker-dev-card sbb-dev-global-card' in index or 'sports-ticker-dev-card" data-sbb-dev-only' in index:
    errors.append('Sports Ticker tuning card is still hidden behind a Dev-only gate')

ticker=text(Path('architecture')/'key-info-current-v520.js')
if ".sports-ticker-dev-card{display:block!important}" not in ticker:
    errors.append('Sports Ticker runtime does not force its tuning utility visible')
if "card.className='settings-card sports-ticker-dev-card'" not in ticker:
    errors.append('runtime Sports Ticker utility injection is still Dev-gated')

release_backend=text(Path('sbb')/'release_identity_v523.py')
if 'VERSION = (ROOT / "VERSION").read_text' not in release_backend:
    errors.append('backend release-identity module is not derived from repository VERSION')
if re.search(r'^VERSION\s*=\s*["\']\d+\.\d+\.\d+["\']',release_backend,re.M):
    errors.append('backend release-identity module contains a hard-coded semantic release')

server=text(Path('server.py'))
if 'APP_VERSION = (ROOT / "VERSION").read_text' not in server:
    errors.append('server APP_VERSION is not derived from VERSION')

verify=text(Path('VERIFY.sh'))
if 'tools/check_release_version.py' not in verify:
    errors.append('VERIFY.sh does not execute the release-integrity checker')
if re.search(r'^exit\s+0\s*$',verify,re.M):
    errors.append('VERIFY.sh contains an unconditional successful exit')

# Release projection must exist after core-model is loaded and before consumers
# such as Settings and History Audit initialize.
try:
    core_pos=index.index(f'<script src="core-model.js?v={version}"')
    projection_pos=index.index('<script id="sbbLegacyCoreReleaseProjection"')
    settings_pos=index.index(f'<script src="ui/settings-view.js?v={version}"')
    history_pos=index.index(f'<script src="ui/history-audit.js?v={version}"')
    if not (core_pos < projection_pos < settings_pos < history_pos):
        errors.append('release authority/projection load order is unsafe')
except ValueError:
    errors.append('index is missing core/release/settings/history release surfaces')


# v5.2.12 scroll/motion integrity. The performance fix must be part of the
# atomic frontend generation and the historical scroll controller may not
# reintroduce permanent blocking gesture listeners.
motion=text(Path('architecture')/'scroll-motion-smoothness-v5210.js')
if f"const VERSION='{version}'" not in motion:
    errors.append('scroll/motion module does not match deployment VERSION')
for required in ['content-visibility:auto','sbb-scroll-active','RUN MOTION TEST','runCertification','SBB_SCROLL_MOTION']:
    if required not in motion:
        errors.append(f'scroll/motion module missing required contract: {required}')

visibility=text(Path('ui')/'player-visibility.js')
if "version:'1.7'" not in visibility:
    errors.append('player visibility controller is not the v1.7 conditional-scroll generation')
if "if(!canUseSticky()){diag.scrollNoops++;return;}" not in visibility:
    errors.append('ordinary page scrolling is not a zero-work path')
if 'bindLockGestures()' not in visibility or 'unbindLockGestures()' not in visibility:
    errors.append('blocking Game Center gestures are not conditionally bound/unbound')
if "stage.style.setProperty('transform',`translate3d(" not in visibility:
    errors.append('sticky-player shrink is not compositor-transform based')
if "document.addEventListener('wheel',onUpperWheel,{passive:false,capture:true});" not in visibility:
    errors.append('locked Game Center reverse-wheel contract missing')
# Those non-passive listeners are legal only inside bindLockGestures, not init.
init_tail=visibility.split('function init(){',1)[-1] if 'function init(){' in visibility else ''
init_body=init_tail.split('}',1)[0]
if "addEventListener('wheel',onUpperWheel" in init_body or "addEventListener('touchmove',onUpperTouchMove" in init_body:
    errors.append('blocking wheel/touch listeners are permanently registered during init')

try:
    visibility_pos=index.index(f'<script src="ui/player-visibility.js?v={version}"')
    motion_pos=index.index(f'<script src="architecture/scroll-motion-smoothness-v5210.js?v={version}"')
    settings_pos2=index.index(f'<script src="ui/settings-view.js?v={version}"')
    if not (visibility_pos < motion_pos < settings_pos2):
        errors.append('scroll/motion module load order is unsafe')
except ValueError:
    errors.append('index is missing synchronized scroll/motion release surfaces')


# v5.2.12 OpenAI Sports Ticker rate-limit integrity. Manual refreshes must not
# fall back to the legacy six-record / three-retry request storm.
ticker_backend=text(Path('sbb')/'current_news_v523.py')
if f'VERSION = "{version}-sports-ticker-4"' not in ticker_backend:
    errors.append('Sports Ticker backend component version does not match deployment VERSION')
for required in [
    '_OPENAI_BATCH_SIZE = 20',
    '_OPENAI_MAX_CANDIDATES_MANUAL = 40',
    'class OpenAITickerRateLimited',
    'class OpenAITickerQuotaError',
    '_openai_request_with_backoff',
    'Retry-After',
    'openaiCooldownUntil',
    'Last-good Sports Ticker retained',
    'EDITORIAL_REFRESH_LOCK',
]:
    if required not in ticker_backend:
        errors.append(f'Sports Ticker OpenAI rate-limit contract missing: {required}')
if 'editor(raw[:160])' in ticker_backend:
    errors.append('Sports Ticker still uses the legacy bursty OpenAI editorial call')
if ticker_backend.count('request_fn("/responses"') != 1:
    errors.append('Sports Ticker OpenAI request path is not centralized through bounded backoff')

ticker_frontend=ticker
if 'attempt<240' not in ticker_frontend or 'OpenAI rate limited • retrying in' not in ticker_frontend:
    errors.append('Sports Ticker UI does not expose bounded OpenAI backoff/cooldown status')


# v5.2.12 splash preload integrity. The splash may warm data/media but must never
# become a second playback authority or bypass the user's audible-play gesture.
splash=text(Path('architecture')/'splash-preload-v5212.js')
if f"const VERSION='{version}'" not in splash:
    errors.append('splash preload module does not match deployment VERSION')
for required in [
    'SBB_SPLASH_PRELOAD',
    'safeStartLiveData',
    'prepareStandby',
    'transitionCritical:true',
    'HOT_STANDBY',
    'cueVideoById',
    "v.preload='auto'",
    'assignmentMatches',
    'experienceStarted',
    'Loading scores and first video',
    'First video prepared',
]:
    if required not in splash:
        errors.append(f'splash preload contract missing: {required}')
# Prelaunch warming may cue or preload, but never start video. The canonical
# launch gesture remains the only audible/play command.
for forbidden in ['.loadVideoById(', '.playVideo(', 'v.play(']:
    if forbidden in splash:
        errors.append(f'splash preload illegally starts playback before launch: {forbidden}')
if '<link rel="preload" href="https://www.youtube.com/iframe_api" as="script" fetchpriority="high">' not in index:
    errors.append('index does not network-preload the YouTube iframe API during splash')
if 'id="launchWarmStatus"' not in index:
    errors.append('splash does not expose preload readiness status')
try:
    app_pos=index.index(f'<script src="app.js?v={version}"></script>')
    splash_pos=index.index(f'<script src="architecture/splash-preload-v5212.js?v={version}"></script>')
    ticker_pos=index.index(f'<script src="architecture/key-info-current-v520.js?v={version}"></script>')
    if not (app_pos < splash_pos < ticker_pos):
        errors.append('splash preload module load order is unsafe')
except ValueError:
    errors.append('index is missing synchronized splash preload release surface')

# v5.2.13 Broadcast Design System. Presentation is isolated in a late-loading
# override stylesheet so the stable playback/data DOM and ownership code remain
# unchanged. Avoid expensive blur/glass effects that would regress motion quality.
design=text(Path('ui')/'broadcast-design-v5213.css')
if f'ui/broadcast-design-v5213.css?v={version}' not in index:
    errors.append('index is missing synchronized Broadcast Design System stylesheet')
for required in ['--sbb-surface:','.top-nav-header{','.key-info-ribbon{','.score-ribbon{','.stage-card{','.info-drawer{','.gc-hero{','.settings-card{']:
    if required not in design:
        errors.append(f'Broadcast Design System missing required contract: {required}')
for forbidden in ['backdrop-filter','filter:blur(','animation:']:
    if forbidden in design:
        errors.append(f'Broadcast Design System contains performance-heavy presentation rule: {forbidden}')
try:
    base_style_pos=index.index(f'styles.css?v={version}')
    design_pos=index.index(f'ui/broadcast-design-v5213.css?v={version}')
    head_end=index.index('</head>')
    if not (base_style_pos < design_pos < head_end):
        errors.append('Broadcast Design System stylesheet load order is unsafe')
except ValueError:
    errors.append('index is missing Broadcast Design System load surface')


# v5.4.9 Premium Masthead + Sports Ticker + Score Ribbon. This remains a
# presentation-only late override. It must not replace native scrolling or add
# animation/blur work that competes with the v5.2.10 motion budget.
premium=text(Path('ui')/'premium-masthead-v5214.css')
if f'ui/premium-masthead-v5214.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 premium masthead stylesheet')
for required in [
    '.top-nav-header{', '.score-filters{', '.key-info-ribbon{',
    '.sbb-sports-ticker-conveyor .key-info-item{', '.score-ribbon{',
    '.score-cell.now-watching,', '.score-team-score{',
    '@media (max-width:760px)', '@media (prefers-reduced-motion:reduce)'
]:
    if required not in premium:
        errors.append(f'Premium masthead missing required contract: {required}')
for forbidden in ['backdrop-filter','filter:blur(','animation:','scroll-snap-type:']:
    if forbidden in premium:
        errors.append(f'Premium masthead contains performance-risk presentation rule: {forbidden}')
try:
    design_pos2=index.index(f'ui/broadcast-design-v5213.css?v={version}')
    premium_pos=index.index(f'ui/premium-masthead-v5214.css?v={version}')
    head_end2=index.index('</head>')
    if not (design_pos2 < premium_pos < head_end2):
        errors.append('Premium masthead stylesheet load order is unsafe')
except ValueError:
    errors.append('index is missing premium masthead load surface')


# v5.4.9 Premium Now Watching Experience. This is a presentation-only late
# override over the already-certified viewing/player/Game Center DOM. It may
# visually join the player and embedded information surface, but may not add a
# second playback owner, scroll controller, or continuously animated effect.
now_watching=text(Path('ui')/'premium-now-watching-v5215.css')
if f'ui/premium-now-watching-v5215.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 Premium Now Watching stylesheet')
for required in [
    '.now-playing-copy::before{', '.transport-play.primary{',
    'body.sbb-info-open.diagnostics-off .layout{', '.gc-hero{',
    '.gc-team-score{', '.gc-section-tabs{', '.gc-play-row.scoring{',
    '.game-center-empty{', '@media (max-width:760px)',
    '@media (prefers-reduced-motion:reduce)'
]:
    if required not in now_watching:
        errors.append(f'Premium Now Watching missing required contract: {required}')
for forbidden in ['backdrop-filter','filter:blur(','animation:','scroll-snap-type:']:
    if forbidden in now_watching:
        errors.append(f'Premium Now Watching contains performance-risk presentation rule: {forbidden}')
try:
    masthead_pos=index.index(f'ui/premium-masthead-v5214.css?v={version}')
    watching_pos=index.index(f'ui/premium-now-watching-v5215.css?v={version}')
    head_end3=index.index('</head>')
    if not (masthead_pos < watching_pos < head_end3):
        errors.append('Premium Now Watching stylesheet load order is unsafe')
except ValueError:
    errors.append('index is missing Premium Now Watching load surface')


# v5.4.9 Editorial Slugs + Integrated Up Next. The visual queue prefers the
# canonical visibleQueueEntries() API; rendered queue rows remain startup fallback.
# NEXT delegates to the established tune owner rather than creating PROGRAM state.
upnext_css=text(Path('ui')/'editorial-slugs-up-next-v5216.css')
upnext_js=text(Path('ui')/'up-next-experience-v5217.js')
if f'ui/editorial-slugs-up-next-v5216.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 editorial/up-next stylesheet')
if f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 integrated Up Next module')
for required in [
    '.key-info-item .key-info-type{', 'border-radius:2px!important',
    'box-shadow:inset 3px 0 0 var(--sbb-slug-accent)!important',
    '.next-up-dock{', '#upNextPane .queue-list{', '#upNextPane .queue-item{',
    '#nextBtn::after{'
]:
    if required not in upnext_css:
        errors.append(f'v5.4.9 visual contract missing: {required}')
for required in [
    'SBB_UP_NEXT_EXPERIENCE', 'sourceRows()', 'canonicalProgramEntries(wanted=3)',
    'visibleQueueEntries(wanted)', 'renderDock()', 'patchRenderQueue()',
    'repairNextButton()', 'canonicalNextRow()', 'row.click()', 'nextVisibleQueueIndex()',
    "reason:'manual next control v5.4.9 fallback'"
    , "const curated=String(item?.queueTitle||'').trim();if(curated)return curated;"
]:
    if required not in upnext_js:
        errors.append(f'v5.4.9 Up Next behavior contract missing: {required}')
for forbidden in ['setInterval(', 'requestAnimationFrame(loop', 'new MutationObserver']:
    if forbidden in upnext_js:
        errors.append(f'v5.4.9 Up Next module adds continuous observation/work: {forbidden}')
try:
    watching_pos2=index.index(f'ui/premium-now-watching-v5215.css?v={version}')
    upnext_css_pos=index.index(f'ui/editorial-slugs-up-next-v5216.css?v={version}')
    app_pos2=index.index(f'<script src="app.js?v={version}"></script>')
    ticker_pos2=index.index(f'<script src="architecture/key-info-current-v520.js?v={version}"></script>')
    upnext_js_pos=index.index(f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>')
    if not (watching_pos2 < upnext_css_pos < index.index('</head>')):
        errors.append('v5.4.9 visual stylesheet load order is unsafe')
    if not (app_pos2 < ticker_pos2 < upnext_js_pos):
        errors.append('v5.4.9 Up Next module must load after app and ticker ownership')
except ValueError:
    errors.append('index is missing v5.4.9 Up Next release surfaces')


# v5.4.9 Drawer Polish + Harmonized Controls. These are late presentation and
# drawer-integration layers; they must be synchronized and load after Up Next.
polish_css=text(Path('ui')/'harmonized-controls-drawer-v5217.css')
polish_js=text(Path('ui')/'harmonized-controls-drawer-v5217.js')
if f'ui/harmonized-controls-drawer-v5217.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 harmonized-controls stylesheet')
if f'<script src="ui/harmonized-controls-drawer-v5217.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 drawer-polish module')
for required in [
    '.player-footer .utility-controls{display:none!important}',
    '#drawerCollapseToggle{', 'body.sbb-drawer-collapsed #infoDrawer{',
    '#gameCenterPane .next-up-dock{',
    '.sbb-sports-ticker-conveyor .key-info-item .key-info-type{',
    '#nextBtn::after{content:none!important;display:none!important}'
]:
    if required not in polish_css:
        errors.append(f'v5.4.9 harmonized-controls visual contract missing: {required}')
for required in [
    'SBB_DRAWER_POLISH', 'setTransportLabels()', 'ensureDrawerToggle()',
    "STORAGE_KEY='sbb.drawer.collapsed.v1'",
    "document.body.classList.toggle('sbb-drawer-collapsed'"
]:
    if required not in polish_js:
        errors.append(f'v5.4.9 drawer-polish behavior contract missing: {required}')
try:
    upnext_js_pos2=index.index(f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>')
    polish_js_pos=index.index(f'<script src="ui/harmonized-controls-drawer-v5217.js?v={version}"></script>')
    old_css_pos=index.index(f'ui/editorial-slugs-up-next-v5216.css?v={version}')
    polish_css_pos=index.index(f'ui/harmonized-controls-drawer-v5217.css?v={version}')
    if not (old_css_pos < polish_css_pos < index.index('</head>')):
        errors.append('v5.4.9 harmonized-controls stylesheet load order is unsafe')
    if not (upnext_js_pos2 < polish_js_pos):
        errors.append('v5.4.9 drawer polish must load after integrated Up Next')
except ValueError:
    errors.append('index is missing v5.4.9 drawer-polish release surfaces')


# v5.4.9 Game Center Workspace Reflow. The final late layer owns the actual
# desktop grid collapse, line-score placement and fixed Coming Up shelf.
workspace_css=text(Path('ui')/'viewing-workspace-v5218.css')
workspace_js=text(Path('ui')/'viewing-workspace-v5218.js')
if f'ui/viewing-workspace-v5218.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 viewing-workspace stylesheet')
if f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 viewing-workspace module')
for required in [
    'body.sbb-game-center-side.sbb-drawer-collapsed .stage-card{',
    'grid-template-columns:minmax(0,1fr) var(--sbb-drawer-collapsed-width)!important',
    '#gameCenterPane #gameCenterContent{',
    'grid-template-rows:auto auto minmax(0,1fr)!important',
    '#gcPersistentSummary{display:none!important}',
    '#gcOverviewBroadcastSummary{',
    '#gameCenterPane .next-up-dock{',
    '.player-footer,.lower-third.player-footer{display:none!important}',
    '#prevBtn::before,#prevBtn::after,#nextBtn::before,#nextBtn::after{content:none!important;display:none!important}'
]:
    if required not in workspace_css:
        errors.append(f'v5.4.9 viewing-workspace visual contract missing: {required}')
for required in [
    'SBB_VIEWING_WORKSPACE', 'setTransportLabels()', 'ensureDrawerToggle()',
    "STORAGE_KEY='sbb.drawer.collapsed.v2'", 'notifyLayout()',
    'renderOverviewEnhancements()', 'SBB_GAME_CENTER_MULTISPORT_VIEW',
    "line=line.replace(/>LINESCORE(?=<|\\s)/,'>LINE SCORE')",
    "window.dispatchEvent(new Event('resize'))"
]:
    if required not in workspace_js:
        errors.append(f'v5.4.9 viewing-workspace behavior contract missing: {required}')
try:
    old_polish_css=index.index(f'ui/harmonized-controls-drawer-v5217.css?v={version}')
    workspace_css_pos=index.index(f'ui/viewing-workspace-v5218.css?v={version}')
    old_polish_js=index.index(f'<script src="ui/harmonized-controls-drawer-v5217.js?v={version}"></script>')
    workspace_js_pos=index.index(f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>')
    if not (old_polish_css < workspace_css_pos < index.index('</head>')):
        errors.append('v5.4.9 viewing-workspace stylesheet must load after v5.2.17 polish')
    if not (old_polish_js < workspace_js_pos):
        errors.append('v5.4.9 viewing-workspace module must load after v5.2.17 polish')
except ValueError:
    errors.append('index is missing v5.4.9 viewing-workspace release surfaces')


# v5.4.9 Game Center Readability + Full Content Scroll. The provider renderer
# already emits all player/team rows. This late layer may only change layout,
# labels, selected-state accessibility and canonical queue presentation.
gc_read_css=text(Path('ui')/'game-center-readability-v5219.css')
gc_read_js=text(Path('ui')/'game-center-readability-v5219.js')
if f'ui/game-center-readability-v5219.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 Game Center readability stylesheet')
if f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 Game Center readability module')
for required in [
    '#gameCenterPane #gameCenterContent>[data-gc-pane]:not(.hidden){',
    'overflow-y:auto!important', 'scrollbar-gutter:stable!important',
    '#gameCenterPane .gc-table-scroll{', 'overflow-y:visible!important',
    '#gameCenterPane>.next-up-dock{', '#gameCenterPane #gcSections .gc-section-tab.active,',
    '#gameCenterPane .gc-player-team-tab{', '#gameCenterPane .gc-player-table th,'
]:
    if required not in gc_read_css:
        errors.append(f'v5.4.9 Game Center readability visual contract missing: {required}')
for required in [
    'SBB_GAME_CENTER_READABILITY', 'STAT_ABBR', 'polishSectionTabs()',
    'polishPlayerTeams()', 'abbreviatePlayerHeaders()', "btn.textContent='KEY PLAYS'",
    "btn.setAttribute('aria-selected',active?'true':'false')"
]:
    if required not in gc_read_js:
        errors.append(f'v5.4.9 Game Center readability behavior contract missing: {required}')
for forbidden in ['setInterval(', 'requestAnimationFrame(loop']:
    if forbidden in gc_read_js:
        errors.append(f'v5.4.9 Game Center readability adds continuous work: {forbidden}')
try:
    workspace_css_pos2=index.index(f'ui/viewing-workspace-v5218.css?v={version}')
    read_css_pos=index.index(f'ui/game-center-readability-v5219.css?v={version}')
    workspace_js_pos2=index.index(f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>')
    read_js_pos=index.index(f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>')
    if not (workspace_css_pos2 < read_css_pos < index.index('</head>')):
        errors.append('v5.4.9 Game Center readability stylesheet must load after workspace reflow')
    if not (workspace_js_pos2 < read_js_pos):
        errors.append('v5.4.9 Game Center readability module must load after workspace reflow')
except ValueError:
    errors.append('index is missing v5.4.9 Game Center readability release surfaces')

# v5.4.9 explicit Game Center scroll owner + score-interrupt queue projection.
# The selected score recap is a temporary playback interrupt; the pre-existing
# programming queue must remain visible and resume after the selected game ends.
gc_scroll_css=text(Path('ui')/'game-center-scroll-v5220.css')
gc_scroll_js=text(Path('ui')/'game-center-scroll-v5220.js')
interrupt_js=text(Path('architecture')/'score-interrupt-queue-v5220.js')
if f'ui/game-center-scroll-v5220.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 Game Center scroll stylesheet')
if f'<script src="architecture/score-interrupt-queue-v5220.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 score-interrupt queue module')
if f'<script src="ui/game-center-scroll-v5220.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 Game Center scroll module')
for required in [
    '#gcContentScroller{', 'overflow-y:scroll!important', 'scrollbar-gutter:stable!important',
    '#gcContentScroller>[data-gc-pane]:not(.hidden){', 'overflow:visible!important',
    '#gameCenterPane>.next-up-dock{'
]:
    if required not in gc_scroll_css:
        errors.append(f'v5.4.9 Game Center hard-scroll visual contract missing: {required}')
for required in [
    'SBB_GAME_CENTER_SCROLL', 'ensureScroller()', "content.querySelectorAll(':scope > [data-gc-pane]')",
    'scroller.appendChild(pane)', 'scroller.scrollTop=0'
]:
    if required not in gc_scroll_js:
        errors.append(f'v5.4.9 Game Center hard-scroll behavior contract missing: {required}')
for required in [
    'SBB_SCORE_INTERRUPT_QUEUE', "event.target?.closest?.('.score-card')", 'program:[...PROGRAM]',
    'resumeItemId', 'resumeGameKey', 'PROGRAM=[...snap.program]',
    'resumeDateProgramAfterSelection=wrapped', 'automatic resume after score-ribbon interrupt'
]:
    if required not in interrupt_js:
        errors.append(f'v5.4.9 score-interrupt queue contract missing: {required}')
for required in [
    "state.source='score-interrupt-projection'", 'window.SBB_SCORE_INTERRUPT_QUEUE?.entries?.(wanted)',
    'entry?.interruptResume&&window.SBB_SCORE_INTERRUPT_QUEUE?.play?.(entry)',
    'renderInterruptQueueList()', 'RESUMES AFTER SELECTED HIGHLIGHT'
]:
    if required not in upnext_js:
        errors.append(f'v5.4.9 Up Next interrupt projection contract missing: {required}')
for forbidden in ['setInterval(', 'requestAnimationFrame(loop', 'new MutationObserver']:
    if forbidden in interrupt_js or forbidden in gc_scroll_js:
        errors.append(f'v5.4.9 scroll/interrupt module adds continuous work: {forbidden}')
try:
    app_pos3=index.index(f'<script src="app.js?v={version}"></script>')
    interrupt_pos=index.index(f'<script src="architecture/score-interrupt-queue-v5220.js?v={version}"></script>')
    upnext_pos3=index.index(f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>')
    read_css_pos2=index.index(f'ui/game-center-readability-v5219.css?v={version}')
    scroll_css_pos=index.index(f'ui/game-center-scroll-v5220.css?v={version}')
    read_js_pos2=index.index(f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>')
    scroll_js_pos=index.index(f'<script src="ui/game-center-scroll-v5220.js?v={version}"></script>')
    if not (app_pos3 < interrupt_pos < upnext_pos3):
        errors.append('v5.4.9 score-interrupt queue must load after app and before Up Next')
    if not (read_css_pos2 < scroll_css_pos < index.index('</head>')):
        errors.append('v5.4.9 hard-scroll stylesheet must load after Game Center readability')
    if not (read_js_pos2 < scroll_js_pos):
        errors.append('v5.4.9 hard-scroll module must load after Game Center readability')
except ValueError:
    errors.append('index is missing v5.4.9 scroll/interrupt release surfaces')


# v5.4.9 Clean Collapse + Viewport Fit. Collapsing the information drawer must
# return its entire desktop grid allocation to the player; the only remaining UI
# is a centered seam handle. The expanded stage is measured against the visible
# viewport so width growth cannot create a new document scrollbar.
collapse_css=text(Path('ui')/'collapse-viewport-fit-v5221.css')
collapse_js=text(Path('ui')/'collapse-viewport-fit-v5221.js')
if f'ui/collapse-viewport-fit-v5221.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 collapse/viewport stylesheet')
if f'<script src="ui/collapse-viewport-fit-v5221.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 collapse/viewport module')
for required in ['grid-template-columns:minmax(0,1fr) 0!important','max-width:0!important','top:50%!important','--sbb-collapsed-stage-height','aspect-ratio:auto!important']:
    if required not in collapse_css:
        errors.append(f'v5.4.9 clean-collapse visual contract missing: {required}')
for required in [f"const VERSION='{version}'",'stage.getBoundingClientRect().top','viewportHeight()-top-bottomGap',"body.style.setProperty('--sbb-collapsed-stage-height'",'SBB_COLLAPSE_VIEWPORT_FIT']:
    if required not in collapse_js:
        errors.append(f'v5.4.9 viewport-fit behavior contract missing: {required}')
try:
    scroll_css_pos=index.index(f'ui/game-center-scroll-v5220.css?v={version}')
    collapse_css_pos=index.index(f'ui/collapse-viewport-fit-v5221.css?v={version}')
    scroll_js_pos=index.index(f'<script src="ui/game-center-scroll-v5220.js?v={version}"></script>')
    collapse_js_pos=index.index(f'<script src="ui/collapse-viewport-fit-v5221.js?v={version}"></script>')
    if not (scroll_css_pos < collapse_css_pos < index.index('</head>')):
        errors.append('v5.4.9 collapse stylesheet must load after Game Center hard-scroll layer')
    if not (scroll_js_pos < collapse_js_pos):
        errors.append('v5.4.9 collapse module must load after Game Center hard-scroll module')
except ValueError:
    errors.append('index is missing v5.4.9 collapse/viewport release surfaces')


# v5.4.9 Browse + Curated Programming. This is a user-facing discovery layer over
# the existing historical audit catalog and canonical playback PROGRAM. It may
# curate/filter media, but may not create a second playback owner or polling loop.
browse_css=text(Path('ui')/'browse-curated-programming-v537.css')
browse_js=text(Path('ui')/'browse-curated-programming-v537.js')
if f'ui/browse-curated-programming-v537.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 Browse stylesheet')
if f'<script src="ui/browse-curated-programming-v537.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 Browse module')
for required in [
    '#sbbBrowseBtn{', '#scoreFilters button[data-score-filter]:has(+ #sbbBrowseSubnav:not(.hidden)){', '.sbb-browse-popover{', '.sbb-curation-ribbon{',
    'body.sbb-curation-active .score-ribbon{display:none!important}',
    '.sbb-curation-card-shell{', '.sbb-curation-date-pill{', '.sbb-curation-card{',
    '.sbb-curation-result{', '.sbb-curation-media-tier.tier-green{',
    '.sbb-curation-media-tier.tier-extended{', '#sbbCurationPlay{', '#sbbBrowseSubnav{',
    '.sbb-browse-popover.hidden,.sbb-browse-popover[hidden]{display:none!important}',
    'body.sbb-curated-no-game-center #gameCenterContent{display:none!important}', ':fullscreen .sbb-browse-popover'
]:
    if required not in browse_css:
        errors.append(f'v5.4.9 Browse visual contract missing: {required}')
for required in [
    "const VERSION='5.4.9'", 'SBB_CURATED_BROWSE',
    "FAVORITES_KEY='sbb.curation.favorites.v1'", '/api/history/audit?',
    'MAX_AUDIT_ROWS=1000', "'RANKED TODAY'", "'SEEDED TODAY'",
    'fetchAuditRows(state.league,state.entity,MAX_AUDIT_ROWS)',
    'scoreCardPlayableItems(match)', 'scoreCardPlaybackSelection(match,candidates)',
    'PROGRAM=[...state.queueItems]', 'GENERAL_PROGRAM=[...state.queueItems]',
    'tuneProgramIndexV5(bounded', 'window.SBB_SCORE_INTERRUPT_QUEUE?.clear?.',
    'placeBrowseControls()', 'positionPopover()', 'primeEntityCatalog()',
    '/api/history/scores?', 'IntersectionObserver', "state.games.slice(index)",
    "'PLAYER BROWSE':'TEAM BROWSE'", 'entityMatchupLabel(', 'const queueTitle=entityMatchupLabel(away,home)',
    "subnav.id='sbbBrowseSubnav'", "active.insertAdjacentElement('afterend',subnav)",
    'pop.hidden=!state.open', 'function playAll()', 'patchRenderQueue()',
    'function ensurePopoverHost()', "document.addEventListener('fullscreenchange'",
    'ribbon.hidden=!active', 'function syncCuratedGameCenterContext(item)',
    "window.SBB_SELECTED_EVENT?.clear?.({reason:'curated competition has no Game Center'",
    'syncCuratedGameCenterContext(state.queueItems[bounded])'
]:
    if required not in browse_js:
        errors.append(f'v5.4.9 Browse behavior contract missing: {required}')
for forbidden in ['setInterval(', 'requestAnimationFrame(loop', 'data-curation-select', '+ QUEUE', '‹ DAY', 'id="sbbBrowseExit"']:
    if forbidden in browse_js:
        errors.append(f'v5.4.9 Browse module contains forbidden work/legacy queue affordance: {forbidden}')
for required in [
    '--sbb-score-ribbon-height', '.sbb-curation-ribbon{', '.sbb-entity-focus-controls{', '#sbbEntityTickerTrack{',
    '#keyInfoTrack.sbb-entity-ticker-hidden{', '.sbb-curation-card.no-media{', 'html[data-sbb-team-theme="on"]',
]:
    if required not in browse_css:
        errors.append(f'v5.4.9 persistent Browse/context visual contract missing: {required}')
for required in [
    "ENTITY_CATALOG_KEY='sbb.browse.entity-catalog.v535'", 'function loadEntityCatalogStore()', 'function persistEntityCatalog(league,names,entities=[]',
    'localStorage.setItem(ENTITY_CATALOG_KEY', 'function captureScoreRibbonHeight()', "style.setProperty('--sbb-score-ribbon-height'",
    "controls.id='sbbEntityFocusControls'", "id=\"sbbFocusPlayAll\"", "id=\"sbbFocusExit\"", 'function curatedEventIdentity(item)',
    "window.SBB_SELECTED_EVENT?.select?.(event,{source:'browse',reason:'curated playback event identity'})",
    'window.SBB_SCORE_INTERRUPT_QUEUE?.active?.()', 'gameCenterEventId:eventId', 'function refreshEntityTickerInsights()',
    "upcoming.forEach(row=>pieces.push(contextInsight('NEXT'", 'contextNews()', 'setEntityTickerActive(true)', 'loadTeamFocusData()', '/api/browse/participants?',
    "TEAM_THEME_KEY='sbb.team-theme.enabled.v1'", 'NO MEDIA YET',
]:
    if required not in browse_js:
        errors.append(f'v5.4.9 persistent Browse/context behavior contract missing: {required}')
try:
    collapse_css_pos2=index.index(f'ui/collapse-viewport-fit-v5221.css?v={version}')
    browse_css_pos=index.index(f'ui/browse-curated-programming-v537.css?v={version}')
    collapse_js_pos2=index.index(f'<script src="ui/collapse-viewport-fit-v5221.js?v={version}"></script>')
    browse_js_pos=index.index(f'<script src="ui/browse-curated-programming-v537.js?v={version}"></script>')
    if not (collapse_css_pos2 < browse_css_pos < index.index('</head>')):
        errors.append('v5.4.9 Browse stylesheet must load after the v5.2 viewing polish stack')
    if not (collapse_js_pos2 < browse_js_pos):
        errors.append('v5.4.9 Browse module must load after score/game-center/viewing ownership modules')
except ValueError:
    errors.append('index is missing v5.4.9 Browse release surfaces')

# v5.4.9 viewport-fit applies to the player whether Game Center is open or closed.
workspace_fit_css=text(Path('ui')/'workspace-viewport-fit-v531.css')
workspace_fit_js=text(Path('ui')/'workspace-viewport-fit-v531.js')
if f'ui/workspace-viewport-fit-v531.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 workspace viewport-fit stylesheet')
if f'<script src="ui/workspace-viewport-fit-v531.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 workspace viewport-fit module')
for required in ['--sbb-workspace-stage-height','body.sbb-game-center-side .stage-card>.stage{','aspect-ratio:auto!important']:
    if required not in workspace_fit_css:
        errors.append(f'v5.4.9 workspace viewport-fit visual contract missing: {required}')
for required in [f"const VERSION='{version}'","body.classList.contains('sbb-game-center-side')",'viewportHeight()-top-bottomGap',"sbb:browse-layout",'SBB_WORKSPACE_VIEWPORT_FIT']:
    if required not in workspace_fit_js:
        errors.append(f'v5.4.9 workspace viewport-fit behavior contract missing: {required}')
try:
    browse_css_pos2=index.index(f'ui/browse-curated-programming-v537.css?v={version}')
    fit_css_pos=index.index(f'ui/workspace-viewport-fit-v531.css?v={version}')
    browse_js_pos2=index.index(f'<script src="ui/browse-curated-programming-v537.js?v={version}"></script>')
    fit_js_pos=index.index(f'<script src="ui/workspace-viewport-fit-v531.js?v={version}"></script>')
    if not (browse_css_pos2 < fit_css_pos < index.index('</head>')):
        errors.append('workspace viewport-fit stylesheet must load after Browse styling')
    if not (browse_js_pos2 < fit_js_pos):
        errors.append('workspace viewport-fit module must load after Browse module')
except ValueError:
    errors.append('index is missing v5.4.9 Browse/viewport-fit release surfaces')

# v5.4.9 persistent participant index + TeamRankings/ESPN Team Focus enrichment.
team_focus=text(Path('sbb')/'team_focus_v537.py')
sbb_init=text(Path('sbb')/'__init__.py')
for required in [
    'PERSISTED_VERIFIED_MEDIA_INDEX', '/api/browse/participants', '/api/team-focus',
    'TEAMRANKINGS_STATS', 'site.api.espn.com/apis/site/v2/sports',
    '_PARTICIPANT_PATH', '_FOCUS_PATH', 'history_catalog_event', 'history_event_media'
]:
    if required not in team_focus:
        errors.append(f'v5.4.9 Team Focus backend contract missing: {required}')
if 'from .team_focus_v537 import install as _install_team_focus_v537' not in sbb_init or '_install_team_focus_v537()' not in sbb_init:
    errors.append('sbb package does not install v5.4.9 Team Focus backend')

# v5.4.9 Focus Integration + Full Team Theme.
for required in [
    'function returnToAll()', "$('sbbFocusExit')?.addEventListener('click',returnToAll)",
    "addEventListener('wheel',event=>", 'hideLegacyCfb()', 'sbb-browse-entity-logo',
    'function themeRoles(entity,palette)', '--sbb-team-bg', 'POWER RANK',
]:
    source=browse_js if required not in ('sbb-browse-entity-logo','--sbb-team-bg') else browse_css
    if required not in source: errors.append(f'v5.4.9 focus integration contract missing: {required}')
for required in ['entities', '_espn_directory', 'POWER RANK', 'browse-participants-v538.json']:
    if required not in team_focus: errors.append(f'v5.4.9 participant/team-focus backend contract missing: {required}')
score_interrupt=text(Path('architecture')/'score-interrupt-queue-v5220.js')
for required in ['shouldPreserveCurrentQueue()', 'date-owned score selection']:
    if required not in score_interrupt: errors.append(f'v5.4.9 date-owned score queue contract missing: {required}')


# v5.4.9 League View, accessible team palette, event-context navigation, and
# bounded early-pause recovery. The old Up Next DOM remains hidden for legacy
# queue/debug ownership but is no longer a user-facing navigation destination.
league_css=text(Path('ui')/'league-view-v538.css')
league_js=text(Path('ui')/'league-view-v538.js')
early_pause=text(Path('architecture')/'playback-early-pause-recovery-v538.js')
league_backend=text(Path('sbb')/'league_view_v538.py')
for required in [
    f'ui/league-view-v538.css?v={version}',
    f'<script src="ui/league-view-v538.js?v={version}"></script>',
    f'<script src="architecture/playback-early-pause-recovery-v538.js?v={version}"></script>',
    'id="leagueViewRoot"', '>LEAGUE VIEW</button>', 'sbb-legacy-up-next-hidden'
]:
    if required not in index: errors.append(f'v5.4.9 League View release surface missing: {required}')
for required in [
    'SBB_LEAGUE_VIEW', '/api/league-view?league=', 'aggregateReason(', 'sbb-daily-recap-context',
    'league-view-conference-grid', 'WILD CARD', 'AP TOP 25', 'BIG BOARD EVENT VIEW'
]:
    if required not in league_js: errors.append(f'v5.4.9 League View behavior missing: {required}')
for required in ['.league-view-root{','.league-view-table{','.sbb-legacy-up-next-hidden{display:none!important}','body.sbb-daily-recap-context #gameCenterContent{display:none!important}']:
    if required not in league_css: errors.append(f'v5.4.9 League View visual contract missing: {required}')
for required in ['SBB_EARLY_PAUSE_RECOVERY','5200','8200','USER_PAUSE_SUPPRESS','SOFT_RESUME','BOUNDED_RECOVERY']:
    if required not in early_pause: errors.append(f'v5.4.9 early-pause recovery missing: {required}')
for forbidden in ['setInterval(', 'requestAnimationFrame(loop']:
    if forbidden in early_pause: errors.append(f'v5.4.9 early-pause recovery contains unbounded work: {forbidden}')
for required in ['/api/league-view','ESPN_COMPETITIONS','playoffRace','conferences','leaders','rankings','specialEvent','league-view-v538.json']:
    if required not in league_backend: errors.append(f'v5.4.9 League View backend contract missing: {required}')
if 'from .league_view_v538 import install as _install_league_view_v538' not in sbb_init or '_install_league_view_v538()' not in sbb_init:
    errors.append('sbb package does not install v5.4.9 League View backend')
for required in [
    '_build_accessible_theme', '_relative_luminance', '_contrast', 'team-theme-v538.json',
    '"surfaceRaised"', '"blackReplacement"', '"wcag"'
]:
    if required not in team_focus: errors.append(f'v5.4.9 accessible team theme backend missing: {required}')
for required in [
    'sbb-browse-entity-logo', 'installLegacyCfbGuard()', 'enterSpecialContext(',
    'auditDate(row)<=todayLocal', "contextInsight('RESULT',`${compactDate(row.date)} · ${row.label} · ${row.result} ${row.score}`"
]:
    if required not in browse_js: errors.append(f'v5.4.9 Browse hardening contract missing: {required}')
for required in ['--sbb-team-black-replacement','--sbb-team-gradient-start','#sbbFocusPlayAll{','#sbbFocusExit{']:
    if required not in browse_css: errors.append(f'v5.4.9 theme polish contract missing: {required}')

# v5.4.9 Team Context + Drawer Sync. Team selection auto-starts the newest playable
# recap, drawer panes are exclusive, event navigation survives score-filter rerenders,
# manual pauses stay paused, and League View follows the active playback league.
for required in [
    'newestPlayable=state.games.findIndex', 'playFrom(newestPlayable)',
    "focusPlay.textContent='Play All'", "state.specialContext?'Exit Event':'Exit League'",
    "'WC2026':'FIFA WC'", "chip.removeAttribute('data-score-filter')", 'requestAnimationFrame(()=>{repairQueued=false'
]:
    if required not in browse_js: errors.append(f'v5.4.9 team-context behavior missing: {required}')
for forbidden in ['sbb-browse-entity-abbr\"', "class='sbb-browse-entity-abbr'", 'userPauseUntil']:
    source=browse_js if 'abbr' in forbidden else early_pause
    if forbidden in source: errors.append(f'v5.4.9 retired UI/pause contract still present: {forbidden}')
for required in [
    '.sbb-browse-entity-abbr{display:none!important}', 'background:#fff!important',
    'font:900 7.5px/1 system-ui,sans-serif', 'min-width:max-content',
    'justify-content:center', 'text-align:center'
]:
    if required not in browse_css: errors.append(f'v5.4.9 team-context visual contract missing: {required}')
for required in [
    '#infoDrawer .drawer-pane.hidden', 'body.sbb-game-center-side #infoDrawer .drawer-pane.hidden',
    'display:none!important'
]:
    if required not in league_css: errors.append(f'v5.4.9 drawer exclusivity contract missing: {required}')
for required in [
    'SBB_SELECTED_EVENT?.get?.()', 'const item=activeProgram()',
    "window.addEventListener('sbb:score-click-selection'", 'SBB_SELECTED_EVENT?.subscribe?.'
]:
    if required not in league_js: errors.append(f'v5.4.9 active-league sync contract missing: {required}')
for required in [
    'manualPause', 'manualPauseKey', 'PROVIDER_CONTROL_INTERACTION',
    "markUserPause('embedded provider pause')", 'setCanonicalManualPause(true)',
    'manualPauseRequested', 'confirmProviderPause', '[80,250,650,1100]', 'clearUserPause(', 'userPaused()'
]:
    if required not in early_pause: errors.append(f'v5.4.9 persistent user-pause contract missing: {required}')
if 'tests/test_v539_team_context_drawer_sync.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 Team Context + Drawer Sync regression')

# v5.4.9 continuity guard replaces the legacy startup watchdog before it installs.
progress_guard=text(Path('architecture')/'playback-progress-watchdog-v5310.js')
for required in [
    f'<script src="architecture/playback-progress-watchdog-v5310.js?v={version}"></script>',
    f'<script src="architecture/playback-progress-watchdog.js?v={version}"></script>',
]:
    if required not in index: errors.append(f'v5.4.9 progress-watchdog surface missing: {required}')
for required in ['SBB_PLAYBACK_PROGRESS_WATCHDOG','positive startup stall','recovery-suppressed','provider reports playing; recovery suppressed']:
    if required not in progress_guard: errors.append(f'v5.4.9 continuity guard missing: {required}')
if index.index('playback-progress-watchdog-v5310.js') > index.index('playback-progress-watchdog.js'):
    errors.append('v5.4.9 continuity guard must load before the legacy progress watchdog')
if 'tests/test_v5310_special_event_playback_league_view.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 regression')

# v5.4.9 playback-context boundary + readable standings. Curated queues must
# relinquish ownership on ALL/TODAY, and League View must derive league from the
# playing item/title before any browse-context fallback.
for required in [
    'function releaseCuratedQueue(', 'state.queueActive=false;state.queueItems=[];state.queueLabel=',
    "$('returnTodayBtn')?.addEventListener('click'", "if(requested==='ALL'||isCoreLeague(requested))releaseCuratedQueue",
    "window.dispatchEvent(new CustomEvent('sbb:curated-queue-release'",
]:
    if required not in browse_js: errors.append(f'v5.4.9 curated queue release contract missing: {required}')
for required in [
    'function leagueFromItem(item)', 'function leagueFromTitle(title=currentTitle())',
    "if(context?.mode&&context.mode!=='daily')", "window.addEventListener('sbb:curated-queue-release'",
    "window.addEventListener('sbb:league-context'", 'if(state.navLeague)', 'clearTimeout(state.syncTimer)',
    'function tableHeaders(league)', "if(league==='MLB'||league==='NFL'||league==='NHL')inner+=wildcardCard",
    "if(['EPL','MLS'].includes(league))return ['CLUB','MP','W-D-L','PTS','FORM']"
]:
    if required not in league_js: errors.append(f'v5.4.9 playback/navigation League View contract missing: {required}')
if 'state.contextPoll=setInterval' in league_js:
    errors.append('v5.4.9 League View must not use the old 1.2s polling refresh loop')
for required in [
    '.league-view-head h2{font-size:18px!important', '.league-view-table{font-size:8.1px!important',
    '.league-view-table td{height:32px!important', '.league-view-conference-head strong{font-size:9px!important'
]:
    if required not in league_css: errors.append(f'v5.4.9 readable standings visual contract missing: {required}')
for required in [
    '"gamesPlayed": _stat_value', '"conferenceRecord": _stat_value',
    'if league in {"MLB", "NFL", "NHL"}:', 'minimum_wildcard_seed = 4 if league == "MLB" else (5 if league == "NFL" else 999)',
    'def _recent_form(payload):', 'def _apply_recent_form(groups, form):'
]:
    if required not in league_backend: errors.append(f'v5.4.9 standings backend contract missing: {required}')
if 'tests/test_v5311_playback_context_league_view.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 playback-context + League View regression')

# v5.4.9 closes the remaining Special Event stale-provider race and exposes
# explicit league navigation + useful tournament/form presentation.
for required in [
    'function clearForeignFallbackPresentation(item)', 'function patchYouTubePlayerError()',
    'bumper.dataset.sbbCuratedFallbackKey=programKey(item)', 'const specialOwned=curated&&!!state.specialContext',
    'id="sbbLeagueTodayBtn"', 'id="sbbLeagueAllBtn"', "window.dispatchEvent(new CustomEvent('sbb:league-context'",
    'eventGames:(state.specialEventGames.length?state.specialEventGames:state.games)'
]:
    if required not in browse_js: errors.append(f'v5.4.9 Special Event/navigation contract missing: {required}')
for required in [
    'function specialEventBoard(', 'function groupStandings(', 'function bracketBoard(',
    'function formMarkup(form=[])'
]:
    if required not in league_js: errors.append(f'v5.4.9 tournament/form League View contract missing: {required}')
for required in ['league-view-event-group-grid','league-view-bracket-grid','league-view-form i.win','.league-view-nhl{gap:5px!important}']:
    if required not in league_css: errors.append(f'v5.4.9 tournament/form visual contract missing: {required}')
if 'tests/test_v5314_league_navigation_event_brackets.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 league navigation + Special Event regression')

# v5.4.9 preserves score-ribbon league/day semantics without doing a dense
# historical projection synchronously inside the click handler. One match is
# projected per browser task and the clicked game's reel remains the queue prefix.
for required in [
    'function scheduleLeagueDayQueueExpansion(sessionOverride=null)',
    'const pump=()=>{',
    'const match=build.rows[build.index++]',
    'setTimeout(pump,BUILD_YIELD_MS)',
    'PROGRAM=merged;',
    'build.session.leagueDayQueue=true;',
    'build.session.queueLeague=build.league;',
    'build.session.queueDate=build.date;',
    'function patchScoreSessionQueue()',
    'beginScorePlaybackSession=wrapped;',
    'expandLeagueDay:scheduleLeagueDayQueueExpansion',
    'leagueDayBuildSnapshot:',
]:
    if required not in score_interrupt:
        errors.append(f'v5.4.9 non-blocking score-ribbon league-day queue contract missing: {required}')
for forbidden in ['programForScoreDate(date)', 'scoreRibbonLeagueFilter=league;', 'setInterval(']:
    if forbidden in score_interrupt:
        errors.append(f'v5.4.9 score-ribbon queue must not use blocking/looping contract: {forbidden}')
if 'tests/test_v5316_score_ribbon_league_day_queue.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 score-ribbon league-day compatibility regression')

# v5.4.9 visually groups the normal-league TODAY / ALL / TEAM BROWSE controls
# and replaces provider-error dead ends with a scoped sport Match Center fallback.
match_center_js=text(Path('ui/sport-match-center-v5317.js'))
match_center_css=text(Path('ui/sport-match-center-v5317.css'))
for required in [
    '#sbbBrowseSubnav:has(#sbbLeagueTodayBtn:not(.hidden)) #sbbBrowseBtn',
    'rgba(31,122,78,.99)',
]:
    if required not in browse_css: errors.append(f'v5.4.9 league subnav visual contract missing: {required}')
for required in [
    "if(window.SBB_SPORT_MATCH_CENTER?.version==='5.4.9')return;",
    'SPORT MATCH CENTER', 'function errorReason()', 'function providerSupported(evt)',
    'window.SBB_SELECTED_EVENT?.subscribe?.', 'state.observer.observe(pane',
]:
    if required not in match_center_js: errors.append(f'v5.4.9 sport Match Center contract missing: {required}')
if 'body.sbb-sport-match-center-active:not(.sbb-special-event-match-center)' not in match_center_css:
    errors.append('v5.4.9 sport Match Center visual isolation contract missing')
if 'tests/test_v5317_queue_performance_match_center.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 queue performance + Match Center regression')


# v5.4.9 makes Play All intentionally conservative: only completed games with
# verified exact media are admitted, database readiness proof survives into the
# queue item, and slow verified sources have a bounded fallback window. Normal
# league scope controls are also smaller pills with horizontal breathing room.
for required in [
    '__sbbDatabaseVerified:true', '__sbbBrowserProven:',
    'runtimeSuccessAt:Number(media?.runtimeSuccessAt||0)||0',
    'function playAllVerified(item)', 'function playAllCandidateRank(item)',
    'function playAllGameComplete(game)', 'function playAllEligibleGames(games=state.games)',
    'const playableCount=playAllEligibleGames(state.games).length',
    'function armPlayAllStartWatchdog(item,index)', 'const timeoutMs=browserProven?5500:7500',
    'v5.4.9 Play All fast same-game fallback', 'v5.4.9 Play All skipped slow verified source',
]:
    if required not in browse_js: errors.append(f'v5.4.9 verified Play All / fast-start contract missing: {required}')
for required in [
    '#sbbBrowseSubnav:has(#sbbLeagueTodayBtn:not(.hidden)){', 'gap:5px;', 'margin-left:6px;',
    'height:25px!important;', 'border-radius:7px!important;', 'font-size:7.1px!important;',
]:
    if required not in browse_css: errors.append(f'v5.4.9 compact league subnav contract missing: {required}')
if 'tests/test_v5318_verified_play_all_fast_start.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 verified Play All + fast-start regression')


# v5.4.9 Controller foundation. The readiness module remains the single semantic
# focus graph while controller input ships in a separate bounded module. Dynamic
# controls remain child-list registered and the runtime coverage audit stays loud.
controller=text(Path('architecture')/'controller-readiness-v540.js')
controller_css=text(Path('ui')/'controller-readiness-v540.css')
controller_map=text(Path('CONTROLLER-REGION-MAP-v5.4.9.md'))
if f'<script src="architecture/controller-readiness-v540.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 controller-readiness module')
if f'ui/controller-readiness-v540.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 controller-readiness stylesheet')
for required in [
    f"const VERSION='{version}'", "mode:'READINESS_ONLY_NO_GAMEPAD_BINDINGS'",
    'REGION_SPECS', 'REGION_GRAPH', "const FALLBACK_REGION='global-utility'",
    "el.dataset.sbbFocusable='1'", 'el.dataset.sbbRegion=region', 'data-sbb-focus-id',
    'directionalScore', 'bestDirectional', 'navigateBack', 'activeModalRoot',
    'SBB_INPUT_OWNERSHIP', 'SBB_INTERACTION_REGIONS', 'SBB_SEMANTIC_NAVIGATION',
    'SBB_CONTROLLER_READINESS', 'uncovered.length===0&&duplicateIds.length===0&&fallback.length===0',
    'mutationObserver.observe(document.body,{childList:true,subtree:true})',
]:
    if required not in controller: errors.append(f'v5.4.9 controller-readiness contract missing: {required}')
for region in [
    'launch','global-header','league-nav','date-nav','sports-ticker','score-ribbon','system-status',
    'left-nav','now-watching','player-alternates','player-transport','soundtrack','player-stage',
    'transition-overlay','playback-terminal','player-utilities','drawer-tabs','game-center',
    'sport-match-center','league-view','settings','coming-up','team-browse','special-events',
    'date-picker','milestone-console','history-audit','developer-tools','modal'
]:
    if f"name:'{region}'" not in controller: errors.append(f'v5.4.9 controller region missing: {region}')
for forbidden in ['navigator.getGamepads','gamepadconnected','gamepaddisconnected','attributes:true','attributeFilter:']:
    if forbidden in controller: errors.append(f'v5.4.9 readiness layer contains premature/unsafe controller observer work: {forbidden}')
for required in ['[data-sbb-controller-focus="1"]','--sbb-focus-accent','outline:2px solid','prefers-reduced-motion']:
    if required not in controller_css: errors.append(f'v5.4.9 focus visual contract missing: {required}')
for forbidden in ['animation:','backdrop-filter','filter:blur(']:
    if forbidden in controller_css: errors.append(f'v5.4.9 controller focus CSS contains performance-risk effect: {forbidden}')
for region in ['league-nav','score-ribbon','player-transport','game-center','league-view','settings','coming-up','team-browse','history-audit']:
    if f'`{region}`' not in controller_map: errors.append(f'v5.4.9 controller region map missing documentation: {region}')
if 'tests/test_v540_controller_readiness.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 controller-readiness regression')
if 'node --check architecture/controller-readiness-v540.js' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not syntax-check v5.4.9 controller-readiness module')
try:
    operator_pos=index.index(f'<script src="architecture/operator-module-loader.js?v={version}"></script>')
    controller_pos=index.index(f'<script src="architecture/controller-readiness-v540.js?v={version}"></script>')
    if not operator_pos < controller_pos:
        errors.append('v5.4.9 controller-readiness module must load after existing UI/operator modules')
except ValueError:
    errors.append('index is missing v5.4.9 controller-readiness load-order surfaces')

# v5.4.9 Controller Radials + Live Input. The v5.4.0 readiness layer remains the
# semantic authority while v5.4.9 owns browser Gamepad discovery, robust raw-input
# diagnostics, RT/LT radial menus and R3 pointer fallback.
controller_core=text(Path('architecture')/'controller-mode-v542.js')
controller_mode_css=text(Path('ui')/'controller-mode-v542.css')
if f'<script src="architecture/controller-mode-v542.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.4.9 controller module')
if f'ui/controller-mode-v542.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.4.9 controller stylesheet')
for required in [
    f"const VERSION='{version}'", "mode:'RADIALS_POINTER_COMMANDS_AUTOMATIC_GAMEPAD'", 'navigator.getGamepads',
    "window.addEventListener('gamepadconnected'", "window.addEventListener('gamepaddisconnected'",
    "ownerApi()?.claim?.('controller'", 'waitingForNeutral', 'controllerNeutral', 'processRawActivity(gamepad)',
    'DISCOVERY_MS=650', 'NEUTRAL_DEADZONE=.28', 'requestAnimationFrame(poll)', 'scheduleDiscovery()',
    'nav()?.activate?.()', 'nav()?.back?.()', 'playPause()', 'toggleGameCenterLeagueView()', 'toggleInfoDrawerVisibility()', 'transport(-1)', 'transport(1)',
    'processRightStick(gamepad,dt)', "openRadial('league')", "openRadial('date')",
    'document.elementFromPoint(pointerX,pointerY)', 'function movePointer(gamepad,dt)',
]:
    if required not in controller_core: errors.append(f'v5.4.9 controller contract missing: {required}')
for forbidden in ['setInterval(', 'new MutationObserver']:
    if forbidden in controller_core: errors.append(f'v5.4.9 controller contains performance-risk loop/observer: {forbidden}')
for required in ['id="controllerModeSelect"','<option value="automatic">Automatic</option>','<option value="disabled">Disabled</option>','id="controllerStatusValue"','id="controllerLiveIndicator"']:
    if required not in index: errors.append(f'v5.4.9 controller surface missing: {required}')
for required in ['.sbb-controller-help','[data-sbb-controller-focus="1"]','.controller-live-indicator','.sbb-controller-radial','.sbb-controller-pointer','prefers-reduced-motion']:
    if required not in controller_mode_css: errors.append(f'v5.4.9 controller presentation contract missing: {required}')
if 'tests/test_v541_core_controller_mode.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.1 compatibility controller regression')
if 'tests/test_v542_controller_radials_live_input.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 controller regression')
if 'node --check architecture/controller-mode-v542.js' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not syntax-check v5.4.9 controller module')
# v5.4.9 controller refinement: Y switches Game Center/League View, L3 owns
# drawer visibility, league/team browsing stays hierarchical, and dense entity
# radials resolve through the same Browse authority as the on-screen Team Browse.
for required in [
    'function toggleGameCenterLeagueView()',
    "if(index===BUTTON.Y){toggleGameCenterLeagueView();return;}",
    'function toggleInfoDrawerVisibility()',
    "if(index===BUTTON.LS){toggleInfoDrawerVisibility();return;}",
    "queueRadial('league-scope'",
    'function leagueScopeOptions(context={})',
    'function specialEventNodes()',
    "#sbbSpecialEventsMenu [data-special-competition]",
    "openRadial('special-league'",
    "queueRadial('special-scope'",
    'function specialScopeOptions(context={})',
    "return playerBrowseLeague(league)?'PLAYER BROWSE':'TEAM BROWSE';",
    'const ENTITY_RADIAL_PAGE_SIZE=16',
    'controllerEntityEntries',
    'controllerBrowseEntity',
    'function radialHost()',
]:
    if required not in controller_core: errors.append(f'v5.4.9 hierarchical controller contract missing: {required}')
if 'tests/test_v546_hierarchical_radials_drawer_fullscreen.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 hierarchical controller/fullscreen regression')
fullscreen546=text(Path('ui')/'fullscreen-controller-v545.js')
for required in [
    f"const VERSION='{version}'",
    "function appTarget(){return document.documentElement;}",
    "return document.querySelector('.stage-card')||$('stage')||activePlayerLayer();",
    "requestFullscreen(appTarget(),{navigationUI:true})",
    "button.addEventListener('click',onClick,true)",
    "nativeCommand('app-fullscreen')",
    "nativeCommand('video-fullscreen')",
    'videoFullscreen',
]:
    if required not in fullscreen546: errors.append(f'v5.4.9 fullscreen repair contract missing: {required}')
browse548=text(Path('ui')/'browse-curated-programming-v537.js')
for required in [
    'async function controllerEntityEntriesForLeague(league)',
    'function controllerBrowseEntity(league,entity',
    'controllerSelectEntityContext(selected',
    'return activateHistorical({entity:name});',
    'controllerBrowseEntity:(league,entity,options={})=>controllerBrowseEntity(league,entity,options)',
]:
    if required not in browse548: errors.append(f'v5.4.9 controller Team/Player Browse parity missing: {required}')
controller_css548=text(Path('ui')/'controller-mode-v542.css')
for required in ['[data-radial-type="entity-browse"]','sbb-controller-entity-mark']:
    if required not in controller_css548: errors.append(f'v5.4.9 dense entity radial visual contract missing: {required}')
fullscreen_css548=text(Path('ui')/'fullscreen-controller-v545.css')
for required in ['.stage-card:fullscreen','#sbbControllerRadial']:
    if required not in fullscreen_css548: errors.append(f'v5.4.9 reversible video fullscreen visual contract missing: {required}')
if 'tests/test_v548_controller_polish.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 controller polish regression')

try:
    readiness_pos=index.index(f'<script src="architecture/controller-readiness-v540.js?v={version}"></script>')
    core_pos=index.index(f'<script src="architecture/controller-mode-v542.js?v={version}"></script>')
    if not readiness_pos < core_pos: errors.append('v5.4.9 controller must load after semantic readiness')
except ValueError:
    errors.append('index is missing v5.4.9 controller load-order surfaces')


# v5.4.9 Cached Team Select + League Logos + Radial History Parity.
browse549=text(Path('ui')/'browse-curated-programming-v537.js')
controller549=text(Path('architecture')/'controller-mode-v542.js')
controller_css549=text(Path('ui')/'controller-mode-v542.css')
team_focus549=text(Path('sbb')/'team_focus_v537.py')
for required in [
    "function radialBrowseLabel(league)", 'LEAGUE_RADIAL_LOGOS', "leagueLogo:!!LEAGUE_RADIAL_LOGOS[value]",
    "openRadial('entity-loading'", "value:'BROWSE',label:radialBrowseLabel(league)",
]:
    if required not in controller549: errors.append(f'v5.4.9 Team Select radial contract missing: {required}')
for required in ['.sbb-controller-league-mark','[data-radial-type="league"]']:
    if required not in controller_css549: errors.append(f'v5.4.9 league-logo radial CSS missing: {required}')
for required in [
    'ENTITY_CATALOG_MAX_STALE_MS=90*24*60*60*1000','CONTROLLER_PREWARM_LEAGUES',
    'if(cached.length&&entityCatalogUsable(selected))','prewarmControllerEntityCatalogs()',
    'async function controllerSelectEntityContext',"try{scoreRibbonLeagueFilter=selected;}",
    "const fullRows=await fetchAuditRows(state.league,'',MAX_ENTITY_AUDIT_ROWS)",
    'await activateHistorical({entity:name,controller:true});',
]:
    if required not in browse549: errors.append(f'v5.4.9 cached Browse parity missing: {required}')
for required in ['_PARTICIPANT_TTL = 6 * 60 * 60','directory_cache={}','for league,spec in ESPN_COMPETITIONS.items()','PERSISTED_FULL_LEAGUE_DIRECTORY']:
    if required not in team_focus549: errors.append(f'v5.4.9 participant cache contract missing: {required}')
if 'tests/test_v549_cached_team_select.py' not in text(Path('VERIFY.sh')):
    errors.append('VERIFY.sh does not run v5.4.9 cached Team Select regression')


if errors:
    print('RELEASE INTEGRITY CHECK FAILED')
    for error in errors:
        print(' -',error)
    raise SystemExit(1)
print(f'PASS: frontend + backend + database-audit release inputs are synchronized at {version}')
