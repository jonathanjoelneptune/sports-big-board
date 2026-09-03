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


# v5.3.6 Premium Masthead + Sports Ticker + Score Ribbon. This remains a
# presentation-only late override. It must not replace native scrolling or add
# animation/blur work that competes with the v5.2.10 motion budget.
premium=text(Path('ui')/'premium-masthead-v5214.css')
if f'ui/premium-masthead-v5214.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 premium masthead stylesheet')
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


# v5.3.6 Premium Now Watching Experience. This is a presentation-only late
# override over the already-certified viewing/player/Game Center DOM. It may
# visually join the player and embedded information surface, but may not add a
# second playback owner, scroll controller, or continuously animated effect.
now_watching=text(Path('ui')/'premium-now-watching-v5215.css')
if f'ui/premium-now-watching-v5215.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 Premium Now Watching stylesheet')
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


# v5.3.6 Editorial Slugs + Integrated Up Next. The visual queue prefers the
# canonical visibleQueueEntries() API; rendered queue rows remain startup fallback.
# NEXT delegates to the established tune owner rather than creating PROGRAM state.
upnext_css=text(Path('ui')/'editorial-slugs-up-next-v5216.css')
upnext_js=text(Path('ui')/'up-next-experience-v5217.js')
if f'ui/editorial-slugs-up-next-v5216.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 editorial/up-next stylesheet')
if f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 integrated Up Next module')
for required in [
    '.key-info-item .key-info-type{', 'border-radius:2px!important',
    'box-shadow:inset 3px 0 0 var(--sbb-slug-accent)!important',
    '.next-up-dock{', '#upNextPane .queue-list{', '#upNextPane .queue-item{',
    '#nextBtn::after{'
]:
    if required not in upnext_css:
        errors.append(f'v5.3.6 visual contract missing: {required}')
for required in [
    'SBB_UP_NEXT_EXPERIENCE', 'sourceRows()', 'canonicalProgramEntries(wanted=3)',
    'visibleQueueEntries(wanted)', 'renderDock()', 'patchRenderQueue()',
    'repairNextButton()', 'canonicalNextRow()', 'row.click()', 'nextVisibleQueueIndex()',
    "reason:'manual next control v5.3.6 fallback'"
    , "const curated=String(item?.queueTitle||'').trim();if(curated)return curated;"
]:
    if required not in upnext_js:
        errors.append(f'v5.3.6 Up Next behavior contract missing: {required}')
for forbidden in ['setInterval(', 'requestAnimationFrame(loop', 'new MutationObserver']:
    if forbidden in upnext_js:
        errors.append(f'v5.3.6 Up Next module adds continuous observation/work: {forbidden}')
try:
    watching_pos2=index.index(f'ui/premium-now-watching-v5215.css?v={version}')
    upnext_css_pos=index.index(f'ui/editorial-slugs-up-next-v5216.css?v={version}')
    app_pos2=index.index(f'<script src="app.js?v={version}"></script>')
    ticker_pos2=index.index(f'<script src="architecture/key-info-current-v520.js?v={version}"></script>')
    upnext_js_pos=index.index(f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>')
    if not (watching_pos2 < upnext_css_pos < index.index('</head>')):
        errors.append('v5.3.6 visual stylesheet load order is unsafe')
    if not (app_pos2 < ticker_pos2 < upnext_js_pos):
        errors.append('v5.3.6 Up Next module must load after app and ticker ownership')
except ValueError:
    errors.append('index is missing v5.3.6 Up Next release surfaces')


# v5.3.6 Drawer Polish + Harmonized Controls. These are late presentation and
# drawer-integration layers; they must be synchronized and load after Up Next.
polish_css=text(Path('ui')/'harmonized-controls-drawer-v5217.css')
polish_js=text(Path('ui')/'harmonized-controls-drawer-v5217.js')
if f'ui/harmonized-controls-drawer-v5217.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 harmonized-controls stylesheet')
if f'<script src="ui/harmonized-controls-drawer-v5217.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 drawer-polish module')
for required in [
    '.player-footer .utility-controls{display:none!important}',
    '#drawerCollapseToggle{', 'body.sbb-drawer-collapsed #infoDrawer{',
    '#gameCenterPane .next-up-dock{',
    '.sbb-sports-ticker-conveyor .key-info-item .key-info-type{',
    '#nextBtn::after{content:none!important;display:none!important}'
]:
    if required not in polish_css:
        errors.append(f'v5.3.6 harmonized-controls visual contract missing: {required}')
for required in [
    'SBB_DRAWER_POLISH', 'setTransportLabels()', 'ensureDrawerToggle()',
    "STORAGE_KEY='sbb.drawer.collapsed.v1'",
    "document.body.classList.toggle('sbb-drawer-collapsed'"
]:
    if required not in polish_js:
        errors.append(f'v5.3.6 drawer-polish behavior contract missing: {required}')
try:
    upnext_js_pos2=index.index(f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>')
    polish_js_pos=index.index(f'<script src="ui/harmonized-controls-drawer-v5217.js?v={version}"></script>')
    old_css_pos=index.index(f'ui/editorial-slugs-up-next-v5216.css?v={version}')
    polish_css_pos=index.index(f'ui/harmonized-controls-drawer-v5217.css?v={version}')
    if not (old_css_pos < polish_css_pos < index.index('</head>')):
        errors.append('v5.3.6 harmonized-controls stylesheet load order is unsafe')
    if not (upnext_js_pos2 < polish_js_pos):
        errors.append('v5.3.6 drawer polish must load after integrated Up Next')
except ValueError:
    errors.append('index is missing v5.3.6 drawer-polish release surfaces')


# v5.3.6 Game Center Workspace Reflow. The final late layer owns the actual
# desktop grid collapse, line-score placement and fixed Coming Up shelf.
workspace_css=text(Path('ui')/'viewing-workspace-v5218.css')
workspace_js=text(Path('ui')/'viewing-workspace-v5218.js')
if f'ui/viewing-workspace-v5218.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 viewing-workspace stylesheet')
if f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 viewing-workspace module')
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
        errors.append(f'v5.3.6 viewing-workspace visual contract missing: {required}')
for required in [
    'SBB_VIEWING_WORKSPACE', 'setTransportLabels()', 'ensureDrawerToggle()',
    "STORAGE_KEY='sbb.drawer.collapsed.v2'", 'notifyLayout()',
    'renderOverviewEnhancements()', 'SBB_GAME_CENTER_MULTISPORT_VIEW',
    "line=line.replace(/>LINESCORE(?=<|\\s)/,'>LINE SCORE')",
    "window.dispatchEvent(new Event('resize'))"
]:
    if required not in workspace_js:
        errors.append(f'v5.3.6 viewing-workspace behavior contract missing: {required}')
try:
    old_polish_css=index.index(f'ui/harmonized-controls-drawer-v5217.css?v={version}')
    workspace_css_pos=index.index(f'ui/viewing-workspace-v5218.css?v={version}')
    old_polish_js=index.index(f'<script src="ui/harmonized-controls-drawer-v5217.js?v={version}"></script>')
    workspace_js_pos=index.index(f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>')
    if not (old_polish_css < workspace_css_pos < index.index('</head>')):
        errors.append('v5.3.6 viewing-workspace stylesheet must load after v5.2.17 polish')
    if not (old_polish_js < workspace_js_pos):
        errors.append('v5.3.6 viewing-workspace module must load after v5.2.17 polish')
except ValueError:
    errors.append('index is missing v5.3.6 viewing-workspace release surfaces')


# v5.3.6 Game Center Readability + Full Content Scroll. The provider renderer
# already emits all player/team rows. This late layer may only change layout,
# labels, selected-state accessibility and canonical queue presentation.
gc_read_css=text(Path('ui')/'game-center-readability-v5219.css')
gc_read_js=text(Path('ui')/'game-center-readability-v5219.js')
if f'ui/game-center-readability-v5219.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 Game Center readability stylesheet')
if f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 Game Center readability module')
for required in [
    '#gameCenterPane #gameCenterContent>[data-gc-pane]:not(.hidden){',
    'overflow-y:auto!important', 'scrollbar-gutter:stable!important',
    '#gameCenterPane .gc-table-scroll{', 'overflow-y:visible!important',
    '#gameCenterPane>.next-up-dock{', '#gameCenterPane #gcSections .gc-section-tab.active,',
    '#gameCenterPane .gc-player-team-tab{', '#gameCenterPane .gc-player-table th,'
]:
    if required not in gc_read_css:
        errors.append(f'v5.3.6 Game Center readability visual contract missing: {required}')
for required in [
    'SBB_GAME_CENTER_READABILITY', 'STAT_ABBR', 'polishSectionTabs()',
    'polishPlayerTeams()', 'abbreviatePlayerHeaders()', "btn.textContent='KEY PLAYS'",
    "btn.setAttribute('aria-selected',active?'true':'false')"
]:
    if required not in gc_read_js:
        errors.append(f'v5.3.6 Game Center readability behavior contract missing: {required}')
for forbidden in ['setInterval(', 'requestAnimationFrame(loop']:
    if forbidden in gc_read_js:
        errors.append(f'v5.3.6 Game Center readability adds continuous work: {forbidden}')
try:
    workspace_css_pos2=index.index(f'ui/viewing-workspace-v5218.css?v={version}')
    read_css_pos=index.index(f'ui/game-center-readability-v5219.css?v={version}')
    workspace_js_pos2=index.index(f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>')
    read_js_pos=index.index(f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>')
    if not (workspace_css_pos2 < read_css_pos < index.index('</head>')):
        errors.append('v5.3.6 Game Center readability stylesheet must load after workspace reflow')
    if not (workspace_js_pos2 < read_js_pos):
        errors.append('v5.3.6 Game Center readability module must load after workspace reflow')
except ValueError:
    errors.append('index is missing v5.3.6 Game Center readability release surfaces')

# v5.3.6 explicit Game Center scroll owner + score-interrupt queue projection.
# The selected score recap is a temporary playback interrupt; the pre-existing
# programming queue must remain visible and resume after the selected game ends.
gc_scroll_css=text(Path('ui')/'game-center-scroll-v5220.css')
gc_scroll_js=text(Path('ui')/'game-center-scroll-v5220.js')
interrupt_js=text(Path('architecture')/'score-interrupt-queue-v5220.js')
if f'ui/game-center-scroll-v5220.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 Game Center scroll stylesheet')
if f'<script src="architecture/score-interrupt-queue-v5220.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 score-interrupt queue module')
if f'<script src="ui/game-center-scroll-v5220.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 Game Center scroll module')
for required in [
    '#gcContentScroller{', 'overflow-y:scroll!important', 'scrollbar-gutter:stable!important',
    '#gcContentScroller>[data-gc-pane]:not(.hidden){', 'overflow:visible!important',
    '#gameCenterPane>.next-up-dock{'
]:
    if required not in gc_scroll_css:
        errors.append(f'v5.3.6 Game Center hard-scroll visual contract missing: {required}')
for required in [
    'SBB_GAME_CENTER_SCROLL', 'ensureScroller()', "content.querySelectorAll(':scope > [data-gc-pane]')",
    'scroller.appendChild(pane)', 'scroller.scrollTop=0'
]:
    if required not in gc_scroll_js:
        errors.append(f'v5.3.6 Game Center hard-scroll behavior contract missing: {required}')
for required in [
    'SBB_SCORE_INTERRUPT_QUEUE', "event.target?.closest?.('.score-card')", 'program:[...PROGRAM]',
    'resumeItemId', 'resumeGameKey', 'PROGRAM=[...snap.program]',
    'resumeDateProgramAfterSelection=wrapped', 'automatic resume after score-ribbon interrupt'
]:
    if required not in interrupt_js:
        errors.append(f'v5.3.6 score-interrupt queue contract missing: {required}')
for required in [
    "state.source='score-interrupt-projection'", 'window.SBB_SCORE_INTERRUPT_QUEUE?.entries?.(wanted)',
    'entry?.interruptResume&&window.SBB_SCORE_INTERRUPT_QUEUE?.play?.(entry)',
    'renderInterruptQueueList()', 'RESUMES AFTER SELECTED HIGHLIGHT'
]:
    if required not in upnext_js:
        errors.append(f'v5.3.6 Up Next interrupt projection contract missing: {required}')
for forbidden in ['setInterval(', 'requestAnimationFrame(loop', 'new MutationObserver']:
    if forbidden in interrupt_js or forbidden in gc_scroll_js:
        errors.append(f'v5.3.6 scroll/interrupt module adds continuous work: {forbidden}')
try:
    app_pos3=index.index(f'<script src="app.js?v={version}"></script>')
    interrupt_pos=index.index(f'<script src="architecture/score-interrupt-queue-v5220.js?v={version}"></script>')
    upnext_pos3=index.index(f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>')
    read_css_pos2=index.index(f'ui/game-center-readability-v5219.css?v={version}')
    scroll_css_pos=index.index(f'ui/game-center-scroll-v5220.css?v={version}')
    read_js_pos2=index.index(f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>')
    scroll_js_pos=index.index(f'<script src="ui/game-center-scroll-v5220.js?v={version}"></script>')
    if not (app_pos3 < interrupt_pos < upnext_pos3):
        errors.append('v5.3.6 score-interrupt queue must load after app and before Up Next')
    if not (read_css_pos2 < scroll_css_pos < index.index('</head>')):
        errors.append('v5.3.6 hard-scroll stylesheet must load after Game Center readability')
    if not (read_js_pos2 < scroll_js_pos):
        errors.append('v5.3.6 hard-scroll module must load after Game Center readability')
except ValueError:
    errors.append('index is missing v5.3.6 scroll/interrupt release surfaces')


# v5.3.6 Clean Collapse + Viewport Fit. Collapsing the information drawer must
# return its entire desktop grid allocation to the player; the only remaining UI
# is a centered seam handle. The expanded stage is measured against the visible
# viewport so width growth cannot create a new document scrollbar.
collapse_css=text(Path('ui')/'collapse-viewport-fit-v5221.css')
collapse_js=text(Path('ui')/'collapse-viewport-fit-v5221.js')
if f'ui/collapse-viewport-fit-v5221.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 collapse/viewport stylesheet')
if f'<script src="ui/collapse-viewport-fit-v5221.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 collapse/viewport module')
for required in ['grid-template-columns:minmax(0,1fr) 0!important','max-width:0!important','top:50%!important','--sbb-collapsed-stage-height','aspect-ratio:auto!important']:
    if required not in collapse_css:
        errors.append(f'v5.3.6 clean-collapse visual contract missing: {required}')
for required in [f"const VERSION='{version}'",'stage.getBoundingClientRect().top','viewportHeight()-top-bottomGap',"body.style.setProperty('--sbb-collapsed-stage-height'",'SBB_COLLAPSE_VIEWPORT_FIT']:
    if required not in collapse_js:
        errors.append(f'v5.3.6 viewport-fit behavior contract missing: {required}')
try:
    scroll_css_pos=index.index(f'ui/game-center-scroll-v5220.css?v={version}')
    collapse_css_pos=index.index(f'ui/collapse-viewport-fit-v5221.css?v={version}')
    scroll_js_pos=index.index(f'<script src="ui/game-center-scroll-v5220.js?v={version}"></script>')
    collapse_js_pos=index.index(f'<script src="ui/collapse-viewport-fit-v5221.js?v={version}"></script>')
    if not (scroll_css_pos < collapse_css_pos < index.index('</head>')):
        errors.append('v5.3.6 collapse stylesheet must load after Game Center hard-scroll layer')
    if not (scroll_js_pos < collapse_js_pos):
        errors.append('v5.3.6 collapse module must load after Game Center hard-scroll module')
except ValueError:
    errors.append('index is missing v5.3.6 collapse/viewport release surfaces')


# v5.3.6 Browse + Curated Programming. This is a user-facing discovery layer over
# the existing historical audit catalog and canonical playback PROGRAM. It may
# curate/filter media, but may not create a second playback owner or polling loop.
browse_css=text(Path('ui')/'browse-curated-programming-v536.css')
browse_js=text(Path('ui')/'browse-curated-programming-v536.js')
if f'ui/browse-curated-programming-v536.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 Browse stylesheet')
if f'<script src="ui/browse-curated-programming-v536.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 Browse module')
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
        errors.append(f'v5.3.6 Browse visual contract missing: {required}')
for required in [
    "const VERSION='5.3.6'", 'SBB_CURATED_BROWSE',
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
        errors.append(f'v5.3.6 Browse behavior contract missing: {required}')
for forbidden in ['new MutationObserver', 'setInterval(', 'requestAnimationFrame(loop', 'data-curation-select', '+ QUEUE', '‹ DAY', 'id="sbbBrowseExit"']:
    if forbidden in browse_js:
        errors.append(f'v5.3.6 Browse module contains forbidden work/legacy queue affordance: {forbidden}')
for required in [
    '--sbb-score-ribbon-height', '.sbb-curation-ribbon{', '.sbb-entity-focus-controls{', '#sbbEntityTickerTrack{',
    '#keyInfoTrack.sbb-entity-ticker-hidden{', '.sbb-curation-card.no-media{', 'html[data-sbb-team-theme="on"]',
]:
    if required not in browse_css:
        errors.append(f'v5.3.6 persistent Browse/context visual contract missing: {required}')
for required in [
    "ENTITY_CATALOG_KEY='sbb.browse.entity-catalog.v535'", 'function loadEntityCatalogStore()', 'function persistEntityCatalog(league,names)',
    'localStorage.setItem(ENTITY_CATALOG_KEY', 'function captureScoreRibbonHeight()', "style.setProperty('--sbb-score-ribbon-height'",
    "controls.id='sbbEntityFocusControls'", "id=\"sbbFocusPlayAll\"", "id=\"sbbFocusExit\"", 'function curatedEventIdentity(item)',
    "window.SBB_SELECTED_EVENT?.select?.(event,{source:'browse',reason:'curated playback event identity'})",
    'window.SBB_SCORE_INTERRUPT_QUEUE?.active?.()', 'gameCenterEventId:eventId', 'function refreshEntityTickerInsights()',
    "contextInsight('NEXT 3'", 'contextNews()', 'setEntityTickerActive(true)', 'loadTeamFocusData()', '/api/browse/participants?',
    "TEAM_THEME_KEY='sbb.team-theme.enabled.v1'", 'NO MEDIA YET',
]:
    if required not in browse_js:
        errors.append(f'v5.3.6 persistent Browse/context behavior contract missing: {required}')
try:
    collapse_css_pos2=index.index(f'ui/collapse-viewport-fit-v5221.css?v={version}')
    browse_css_pos=index.index(f'ui/browse-curated-programming-v536.css?v={version}')
    collapse_js_pos2=index.index(f'<script src="ui/collapse-viewport-fit-v5221.js?v={version}"></script>')
    browse_js_pos=index.index(f'<script src="ui/browse-curated-programming-v536.js?v={version}"></script>')
    if not (collapse_css_pos2 < browse_css_pos < index.index('</head>')):
        errors.append('v5.3.6 Browse stylesheet must load after the v5.2 viewing polish stack')
    if not (collapse_js_pos2 < browse_js_pos):
        errors.append('v5.3.6 Browse module must load after score/game-center/viewing ownership modules')
except ValueError:
    errors.append('index is missing v5.3.6 Browse release surfaces')

# v5.3.6 viewport-fit applies to the player whether Game Center is open or closed.
workspace_fit_css=text(Path('ui')/'workspace-viewport-fit-v531.css')
workspace_fit_js=text(Path('ui')/'workspace-viewport-fit-v531.js')
if f'ui/workspace-viewport-fit-v531.css?v={version}' not in index:
    errors.append('index is missing synchronized v5.3.6 workspace viewport-fit stylesheet')
if f'<script src="ui/workspace-viewport-fit-v531.js?v={version}"></script>' not in index:
    errors.append('index is missing synchronized v5.3.6 workspace viewport-fit module')
for required in ['--sbb-workspace-stage-height','body.sbb-game-center-side .stage-card>.stage{','aspect-ratio:auto!important']:
    if required not in workspace_fit_css:
        errors.append(f'v5.3.6 workspace viewport-fit visual contract missing: {required}')
for required in [f"const VERSION='{version}'","body.classList.contains('sbb-game-center-side')",'viewportHeight()-top-bottomGap',"sbb:browse-layout",'SBB_WORKSPACE_VIEWPORT_FIT']:
    if required not in workspace_fit_js:
        errors.append(f'v5.3.6 workspace viewport-fit behavior contract missing: {required}')
try:
    browse_css_pos2=index.index(f'ui/browse-curated-programming-v536.css?v={version}')
    fit_css_pos=index.index(f'ui/workspace-viewport-fit-v531.css?v={version}')
    browse_js_pos2=index.index(f'<script src="ui/browse-curated-programming-v536.js?v={version}"></script>')
    fit_js_pos=index.index(f'<script src="ui/workspace-viewport-fit-v531.js?v={version}"></script>')
    if not (browse_css_pos2 < fit_css_pos < index.index('</head>')):
        errors.append('workspace viewport-fit stylesheet must load after Browse styling')
    if not (browse_js_pos2 < fit_js_pos):
        errors.append('workspace viewport-fit module must load after Browse module')
except ValueError:
    errors.append('index is missing v5.3.6 Browse/viewport-fit release surfaces')

# v5.3.6 persistent participant index + TeamRankings/ESPN Team Focus enrichment.
team_focus=text(Path('sbb')/'team_focus_v536.py')
sbb_init=text(Path('sbb')/'__init__.py')
for required in [
    'PERSISTED_VERIFIED_MEDIA_INDEX', '/api/browse/participants', '/api/team-focus',
    'TEAMRANKINGS_STATS', 'site.api.espn.com/apis/site/v2/sports',
    '_PARTICIPANT_PATH', '_FOCUS_PATH', 'history_catalog_event', 'history_event_media'
]:
    if required not in team_focus:
        errors.append(f'v5.3.6 Team Focus backend contract missing: {required}')
if 'from .team_focus_v536 import install as _install_team_focus_v536' not in sbb_init or '_install_team_focus_v536()' not in sbb_init:
    errors.append('sbb package does not install v5.3.6 Team Focus backend')

if errors:
    print('RELEASE INTEGRITY CHECK FAILED')
    for error in errors:
        print(' -',error)
    raise SystemExit(1)
print(f'PASS: frontend + backend + database-audit release inputs are synchronized at {version}')
