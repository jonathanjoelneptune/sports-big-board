from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8')
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
SERVER=(ROOT/'server.py').read_text(encoding='utf-8')
STYLES=(ROOT/'styles.css').read_text(encoding='utf-8')
GC=(ROOT/'ui/game-center-view.js').read_text(encoding='utf-8')
INFO=(ROOT/'ui/info-drawer.js').read_text(encoding='utf-8')
PREFS=(ROOT/'ui/player-visibility.js').read_text(encoding='utf-8')
SETTINGS=(ROOT/'ui/settings-view.js').read_text(encoding='utf-8')
AUDIT=(ROOT/'ui/history-audit.js').read_text(encoding='utf-8')
CONTRACT=(ROOT/'architecture/game-center-contract.js').read_text(encoding='utf-8')

class RegressionGuards(unittest.TestCase):

    def test_history_console_render_declares_association_payload(self):
        start=AUDIT.index('function renderConsole(data){')
        end=AUDIT.index('async function loadConsole()',start)
        block=AUDIT[start:end]
        self.assertIn('const assoc=data.associations||{};',block)
        self.assertIn('assoc.assignedLinks',block)
        self.assertLess(block.index('const assoc=data.associations||{};'),block.index('assoc.assignedLinks'))

    def test_architecture_loaded_before_app(self):
        ordered=['core-model.js?v=4.1.12','architecture/score-date-store.js?v=4.1.12','architecture/event-identity.js?v=4.1.12','architecture/media-scope.js?v=4.1.12','architecture/media-classifier.js?v=4.1.12','architecture/playback-transports.js?v=4.1.12','architecture/provider-health.js?v=4.1.12','architecture/sport-media-policy.js?v=4.1.12','architecture/media-manifest.js?v=4.1.12','architecture/media-resolver.js?v=4.1.12','architecture/game-center-policy.js?v=4.1.12','architecture/selected-event-store.js?v=4.1.12','architecture/game-center-contract.js?v=4.1.12','architecture/media-work-priorities.js?v=4.1.12','architecture/editorial-packages.js?v=4.1.12','ui/player-visibility.js?v=4.1.12','ui/info-drawer.js?v=4.1.12','ui/settings-view.js?v=4.1.12','ui/history-audit.js?v=4.1.12','ui/game-center-view.js?v=4.1.12','app.js?v=4.1.12']
        positions=[INDEX.index(x) for x in ordered]
        self.assertEqual(positions,sorted(positions))

    def test_playback_ownership_survives(self):
        for token in ['const PlaybackController={','slotClaimIsCurrent','configurePreparedNativeSlot','takePreparedNativeEntry','window.SBB_PLAYBACK_CONTROLLER=PlaybackController']:
            self.assertIn(token,APP)
        self.assertNotIn('clearGameFocus(',APP)
        self.assertNotIn('PlaybackController',GC+INFO+PREFS+SETTINGS)

    def test_single_media_classifier_boundary(self):
        self.assertIn('SBB_MEDIA_CLASSIFIER?.tier?.(item)',APP)
        self.assertIn('SBB_MEDIA_CLASSIFIER?.commentary?.(item)',APP)
        self.assertIn('SBB_MEDIA_CLASSIFIER?.extended?.(item)',APP)
        self.assertIn('SBB_MEDIA_CLASSIFIER?.quick?.(item)',APP)

    def test_director_ttl_not_multiplied_twice(self):
        self.assertNotIn('DIRECTOR_MODE_TTL*60*1000',APP)

    def test_score_click_remains_authoritative(self):
        self.assertRegex(APP,r"PlaybackController\.tuneProgramIndex\(0,\{userInitiated:true,reason:'score-card selection'\}\)")
        self.assertIn('gameCenterEventId',APP)
        self.assertIn('scoreEventId',APP)
        self.assertIn('gameCenterSelectionFromScoreMatch',APP)


    def test_score_selection_keeps_game_center_identity_on_score_event(self):
        start=APP.index('const resolvedSelection=scoreCardPlaybackSelection(match,items);')
        end=APP.index('PlaybackController.tuneProgramIndex(0',start)
        block=APP[start:end]
        self.assertIn('syncSelectedEvent(gameCenterSelectionFromScoreMatch(match)',block)
        self.assertNotIn('selectionItems.find(x=>x?.gamePk)',block)
        self.assertNotIn('primary?.gamePk',block)
        helper=APP[APP.index('function gameCenterSelectionFromScoreMatch'):APP.index('function scheduleLaunchGameCenterPopulate')]
        self.assertIn("const scoreGamePk=competitionId==='MLB'?String(match.gamePk||''):''",helper)
        self.assertIn('gameCenterEventId',helper)
        self.assertIn('scoreEventId',helper)
        self.assertLess(block.index('let primary=resolvedSelection.primary'),block.index('syncSelectedEvent('))

    def test_game_center_identity_hints_resolve_provider_ids(self):
        for token in ["qs.set('date',date)","qs.set('away',away)","qs.set('home',home)","qs.set('start',start)","eventHints"]:
            self.assertIn(token,CONTRACT)
        self.assertIn('_resolve_game_center_event_id',SERVER)
        self.assertIn('_index_game_center_events',SERVER)
        self.assertIn('put_alias',SERVER)

    def test_shrink_runway_keeps_game_center_attached_until_minimum(self):
        self.assertIn('const flowTravel=Math.min(consumed,travel)',PREFS)
        self.assertIn('height+flowTravel+workspaceExtent',PREFS)
        self.assertNotIn("info.style.setProperty('transform'",PREFS)
        self.assertIn('sbb-stage-minimized',PREFS)
        self.assertIn('body.sbb-stage-sticky-active .stage-card>.player-footer{display:none!important}',STYLES)
        self.assertIn('lockWorkspace(info,videoBottom+workspaceExtent)',PREFS)
        self.assertIn("window.SBB_VIEW_PREFS?.reset?.()",INFO)

    def test_core_event_ids_skip_empty_provider_fields(self):
        core=(ROOT/'core-model.js').read_text(encoding='utf-8')
        self.assertIn('clean(input.eventId)||clean(input.matchId)||clean(input.gamePk)||clean(input.id)',core)

    def test_game_center_never_trusts_unresolved_score_provider_id(self):
        self.assertIn('Never fall back to an unverified score id',SERVER)
        self.assertIn('_game_center_payload_valid',SERVER)
        self.assertIn('GAME_CENTER_REPOSITORY.delete',SERVER)
        self.assertIn('provider identity did not match selected teams',SERVER)
        self.assertIn('Aliases written by older builds may have been poisoned',SERVER)

    def test_live_day_not_process_utc(self):
        self.assertNotIn('time.strftime("%Y-%m-%d")',SERVER)
        self.assertIn('_reconcile_scoreboard_authority',SERVER)
        self.assertIn('otherSportsNeedTransitionRefresh',APP)
        self.assertIn('scheduledTransitionImminent',APP)

    def test_browser_clock_fallback_is_sent_to_server(self):
        self.assertIn('utcOffsetMinutes=-new Date().getTimezoneOffset()', APP)
        self.assertIn('clientDate=${encodeURIComponent(today)}', APP)
        self.assertIn('_remember_client_clock', SERVER)

    def test_minimum_player_hands_scroll_to_game_center(self):
        js=(ROOT/'ui/player-visibility.js').read_text()
        css=(ROOT/'styles.css').read_text()
        self.assertIn('sbb-gc-scroll-locked',js)
        self.assertIn('lockWorkspace',js)
        self.assertIn('gameCenterScroller',js)
        self.assertIn('if(minLocked){',js)
        self.assertIn('overflow-y:auto!important',css)
        self.assertIn('--sbb-gc-lock-top',css)
        self.assertNotIn("document.documentElement.style.setProperty('overflow','hidden'",js)

    def test_big_board_fullscreen_can_use_sticky_player(self):
        js=(ROOT/'ui/player-visibility.js').read_text()
        self.assertIn('fullscreenContainsInfo',js)
        self.assertNotIn("&&!document.fullscreenElement",js)
        self.assertIn("fs&&fs.id==='app-shell'",js)

    def test_game_center_all_day_coverage_worker_exists(self):
        server=(ROOT/'server.py').read_text()
        self.assertIn('def _game_center_coverage_pass',server)
        self.assertIn('def game_center_coverage_worker',server)
        self.assertIn('/api/game-center/prewarm',server)
        self.assertIn('workers=8, name="sbb-game-center-work"',server)

    def test_score_media_gamepk_cannot_override_game_center_identity(self):
        app=(ROOT/'app.js').read_text()
        contract=(ROOT/'architecture/game-center-contract.js').read_text()
        helper=app[app.index('function gameCenterSelectionFromScoreMatch'):app.index('function scheduleLaunchGameCenterPopulate')]
        self.assertIn("const scoreGamePk=competitionId==='MLB'?String(match.gamePk||''):''",helper)
        self.assertNotIn("String(primary?.gamePk",app)
        self.assertIn('eventLike?.gameCenterEventId||eventLike?.scoreEventId||eventLike?.gamePk',contract)

    def test_launch_play_repopulates_current_game_center_after_warmup(self):
        self.assertIn('function scheduleLaunchGameCenterPopulate()',APP)
        self.assertIn('const delays=[120,900,2400,5200]',APP)
        self.assertIn("reason:'launch game-center populate'",APP)
        self.assertIn("open?.('game-center',{automatic:true})",APP)
        self.assertIn("SBB_GAME_CENTER_VIEW?.load?.(selected,{force:true,background:true})",APP)
        start=APP.index('function startSportsBigBoardExperience()')
        end=APP.index('function wireLaunchScreen()',start)
        self.assertIn('scheduleLaunchGameCenterPopulate();',APP[start:end])

    def test_nfl_recap_discovery_accepts_official_week_title_and_long_package(self):
        self.assertIn("if league=='NFL':",SERVER)
        self.assertIn("f'{away} vs {home} {year} preseason week'",SERVER)
        self.assertIn("max_duration=1500 if league in ('NFL','NBA','NHL')",SERVER)
        self.assertIn('nfl_official_package=',SERVER)
        self.assertIn('YouTube search is',SERVER)
        self.assertIn("out.extend(_espn_search_video_results(league,away,home,max_items=8))",SERVER)

    def test_verify_node_is_optional(self):
        verify=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
        self.assertIn('command -v node',verify)
        self.assertIn('python -m unittest discover',verify)

    def test_game_center_and_priority_scheduler_routes_exist(self):
        self.assertIn('/game-center",parsed.path',SERVER)
        self.assertIn('MEDIA_WORK_SCHEDULER',SERVER)
        self.assertIn('/api/architecture',SERVER)
        self.assertIn('priorityClass',APP)
        self.assertNotIn('MEDIA_FILE_CACHE_STAGE_EXECUTOR',SERVER)

    def test_live_authority_has_android_cdn_fallback(self):
        self.assertIn('cdn.espn.com/core/',SERVER)
        self.assertIn('_espn_fetch_json',SERVER)
        self.assertIn('_espn_event_rows',SERVER)
        self.assertIn('Mozilla/5.0 (Linux; Android 10)',SERVER)
        self.assertIn('nxt["espnEventId"]',SERVER)

    def test_soccer_buckets_are_reclassified_by_actual_event_date(self):
        self.assertIn('canonicalizeMatchBuckets(markedYesterday,markedToday,yesterday,today)',APP)
        self.assertIn('/api/soccer/schedule?league=',APP)

    def test_game_center_surface_is_decoupled_from_playback(self):
        self.assertIn('id="infoDrawer"',INDEX)
        self.assertIn('id="gameCenterDrawerBtn"',INDEX)
        self.assertIn('id="upNextDrawerBtn"',INDEX)
        self.assertIn('id="settingsDrawerBtn"',INDEX)
        self.assertIn('SBB_SELECTED_EVENT?.subscribe',INFO)
        self.assertIn('SBB_SELECTED_EVENT?.subscribe',GC)
        self.assertIn('SBB_GAME_CENTER.get',GC)
        self.assertNotIn('SBB_PLAYBACK_CONTROLLER',INFO+GC+PREFS+SETTINGS)

    def test_game_center_is_inside_stage_card_below_video(self):
        stage=INDEX.index('<section class="stage-card">')
        drawer=INDEX.index('<aside id="infoDrawer"')
        stage_close=INDEX.index('</section>\n    </main>',drawer)
        self.assertLess(stage,drawer)
        self.assertLess(drawer,stage_close)
        self.assertIn('.info-drawer{\n  position:static!important',STYLES)

    def test_mobile_cannot_activate_side_layout(self):
        self.assertIn("matchMedia?.('(pointer:fine)').matches",PREFS)
        self.assertIn('window.innerWidth>=1100',PREFS)
        self.assertIn('@media(max-width:820px),(pointer:coarse)',STYLES)

    def test_keep_video_visible_is_presentation_only_and_persistent(self):
        self.assertIn("sbb.keepVideoVisible.v1",PREFS)
        self.assertIn('sbb-stage-placeholder',STYLES)
        self.assertIn("setProperty('position','fixed'",PREFS)
        self.assertIn("window.addEventListener('scroll',onRootScroll,{passive:true})",PREFS)
        self.assertIn('bindScrollRoot',PREFS)
        self.assertIn('setKeepVideoVisible',PREFS)
        self.assertNotIn('play(',PREFS)
        self.assertNotIn('pause(',PREFS)

    def test_game_center_layout_defaults_to_embedded_side_on_pc(self):
        self.assertIn("localStorage.getItem(LAYOUT_KEY)||'side'",PREFS)
        self.assertIn("const side=sideEligible()",PREFS)
        self.assertIn('body.sbb-game-center-side .stage-card',STYLES)
        self.assertIn('grid-template-columns:minmax(0,1fr) clamp(390px,34vw,560px)',STYLES)
        self.assertIn('body.sbb-game-center-side .player-topbar #playBtn{display:none!important}',STYLES)
        self.assertIn("content:'‹  PREV'",STYLES)

    def test_key_info_initialization_is_independent_and_retries_empty_cache(self):
        self.assertIn('// Key Info is an independent editorial lane.',APP)
        self.assertIn('refreshKeyInformation(true);',APP)
        self.assertIn('KEY_INFO_STARTUP_RETRY_MAX=10',APP)
        self.assertIn("setTimeout(()=>{keyInfoStartupRetryTimer=null;refreshKeyInformation(false,true);},3000)",APP)

    def test_nfl_has_keyless_official_channel_feed_fallback(self):
        self.assertIn('NFL_YOUTUBE_CHANNEL_ID = "UCDVYQ4Zhbm3S2dlz7P1GBDg"',SERVER)
        self.assertIn('def _official_nfl_feed_videos',SERVER)
        self.assertIn("for raw in _official_nfl_feed_videos(date,away,home):",SERVER)
        self.assertIn("out.extend(_nfl_public_video_results(date,away,home,max_items=4,validate_native=True,allow_historical=True,objective='quick'))",SERVER)
        self.assertIn("out.extend(_nfl_team_video_results(date,away,home,max_items=4,validate_native=True,objective='extended'))",SERVER)
        self.assertIn('team_v418_',SERVER)

    def test_nfl_has_event_scoped_espn_and_club_site_fallbacks(self):
        self.assertIn('def _espn_event_video_results(event_id, league',SERVER)
        self.assertIn('def _nfl_team_site_video_results(date, away, home',SERVER)
        self.assertIn("out.extend(_espn_event_video_results(event_id,league,away,home,max_items=16))",SERVER)
        self.assertIn("out.extend(_nfl_team_site_video_results(date,away,home,max_items=8))",SERVER)
        self.assertIn("event_id=(qs.get('eventId') or [''])[-1]",SERVER)
        self.assertIn('&eventId=${encodeURIComponent(rapidEventId)}',APP)

    def test_game_center_client_aborts_obsolete_requests(self):
        self.assertIn('requestAbort=new AbortController()',GC)
        self.assertIn('requestAbort.abort()',GC)
        self.assertIn('signal:requestAbort.signal',GC)
        self.assertIn('timeoutMs:30000',GC)
        self.assertIn('signal:requestAbort.signal',GC)
        self.assertIn('response.status===202||payload?.pending',CONTRACT)
        self.assertIn('Game Center is still preparing',CONTRACT)

    def test_game_center_client_uses_resident_cache_before_loading_shell(self):
        self.assertIn('SBB_GAME_CENTER?.peek?.(evt)',GC)
        self.assertRegex(GC,r'if\(resident\)render\(resident\)')

    def test_game_center_prefers_score_provider_detail_when_available(self):
        self.assertIn('_highlightly_game_center',SERVER)
        self.assertIn('provider_hint=="highlightly"',SERVER)
        self.assertIn('hl_id=f"hl-{_highlightly_provider_key(requested_id)}"',SERVER)
        self.assertIn('known and time.time()<float(known.get("expiresAt") or 0)',SERVER)
        self.assertIn('gameCenterProviderHint',APP)
        self.assertIn("qs.set('provider',provider)",CONTRACT)

    def test_partial_game_centers_recheck_browser_and_server_quickly(self):
        self.assertIn("hitPartial",CONTRACT)
        self.assertIn("const ttl=hitPartial?1500",CONTRACT)
        self.assertIn("partial?2200",GC)
        self.assertIn("_game_center_needs_enrichment",SERVER)
        self.assertIn('state="PARTIAL" if partial',SERVER)

    def test_compact_sticky_workspace_repositions_title_and_transport(self):
        self.assertIn('body.sbb-stage-sticky-active .stage-card>.player-topbar',STYLES)
        self.assertIn('visibility:hidden!important',STYLES)
        self.assertIn('sbbCompactChrome',PREFS)
        self.assertIn('data-proxy=\"playBtn\"',PREFS)
        self.assertIn('setCompactChrome(left,width,videoBottom,p)',PREFS)
        self.assertIn('.sbb-compact-chrome{',STYLES)
        self.assertIn('.sbb-compact-transport',STYLES)

    def test_minimum_upper_page_scroll_reverses_shrink_and_blocks_root_drift(self):
        self.assertIn('onUpperWheel',PREFS)
        self.assertIn('onUpperTouchMove',PREFS)
        self.assertIn("document.addEventListener('touchmove',onUpperTouchMove,{passive:false,capture:true})",PREFS)
        self.assertIn('Math.abs(y-lockScroll)>1',PREFS)
        self.assertIn('setRootScroll(lockScroll)',PREFS)
        self.assertIn('clearLockGeometry();upperReverseGesture=true',PREFS)

    def test_provider_indexes_do_not_clobber_each_other(self):
        self.assertIn('existing=[r for r in existing if str(r.get("provider") or "official")!=provider]',SERVER)
        self.assertIn('GAME_CENTER_EVENT_INDEX[(competition,day)]=existing+rows',SERVER)
        self.assertIn('preferred_provider="official"',SERVER)

    def test_nfl_nba_nhl_and_soccer_game_center_adapters_are_enabled(self):
        self.assertIn('GAME_CENTER_SUPPORTED = {"MLB","NFL","NBA","NHL","MLS","EPL"}',SERVER)
        self.assertIn('fetch_espn_game_center',SERVER)
        core=(ROOT/'core-model.js').read_text(encoding='utf-8')
        for league in ('NFL','NBA','NHL','MLS','EPL'):
            self.assertRegex(core,rf"{league}:\{{[^\n]+gameCenterProvider:'highlightly'[^\n]+gameCenterFallback:'espn'")

    def test_score_selected_event_cannot_be_overwritten_by_sparse_playback_item(self):
        self.assertIn("current.selectionSource==='score-ribbon'",APP)
        self.assertIn("window.SBB_EVENT_IDENTITY?.same?.(current,eventLike)",APP)
        self.assertIn("source!=='score-ribbon'",APP)

    def test_game_center_contract_preserves_top_level_identity(self):
        core=(ROOT/'core-model.js').read_text(encoding='utf-8')
        self.assertIn('competitionId:upper(input.competitionId||ev.competitionId||parent.competitionId)',core)
        self.assertIn('eventId:clean(input.eventId||ev.eventId||parent.eventId)',core)

    def test_game_center_repository_is_sqlite_and_centrally_refreshed(self):
        self.assertIn('GameCenterRepository(GAME_CENTER_DB)',SERVER)
        self.assertIn('game-centers.sqlite3',SERVER)
        self.assertIn('def game_center_refresh_worker():',SERVER)
        self.assertIn('GAME_CENTER_REPOSITORY.due',SERVER)
        self.assertIn('name="sbb-game-center-refresh"',SERVER)
        self.assertNotIn('GAME_CENTER_CACHE = {}',SERVER)

    def test_game_center_startup_prewarms_all_detailed_adapters(self):
        self.assertIn('for competition in ("NFL","NBA","NHL","MLS","EPL")',SERVER)
        self.assertIn('prewarm_espn_game_centers(competition,date,is_today)',SERVER)
        self.assertIn('prewarm_game_centers_for_games(games,date,is_today)',SERVER)

    def test_api_settings_are_machine_local_and_never_echo_secrets(self):
        self.assertIn('/api/settings/secrets',SERVER)
        self.assertIn('SECRETS_FILE',SERVER)
        self.assertIn('settingsHighlightlyStatus',INDEX)
        self.assertIn('settingsYoutubeStatus',INDEX)
        self.assertIn('settingsOpenaiStatus',INDEX)
        self.assertNotIn('value="sk-',INDEX)
        self.assertNotIn('payload?.key',SETTINGS)

    def test_windows_and_android_use_one_time_setup(self):
        bat=(ROOT/'START SPORTS BIG BOARD.bat').read_text(encoding='utf-8')
        android=(ROOT/'START-ANDROID.sh').read_text(encoding='utf-8')
        setup=(ROOT/'setup_credentials.py').read_text(encoding='utf-8')
        self.assertIn('setup_credentials.py',bat)
        self.assertIn('setup_credentials.py',android)
        self.assertIn('YOUTUBE_API_KEY',setup)
        self.assertIn('Future Sports Big Board versions',setup)

    def test_queue_is_secondary_information_surface(self):
        self.assertIn('class="queue-panel drawer-queue-panel"',INDEX)
        self.assertEqual(INDEX.count('id="queueList"'),1)

    def test_launch_screen_requires_deliberate_play_before_broadcast_autoplay(self):
        self.assertIn('id="launchScreen"',INDEX)
        self.assertIn('id="launchPlayBtn"',INDEX)
        self.assertIn('YOUR SPORTS. ONE BIG BOARD.',INDEX)
        self.assertIn('let sportsBigBoardStarted = false;',APP)
        self.assertIn("btn.addEventListener('click',startSportsBigBoardExperience)",APP)
        self.assertIn('autoplay=!!autoplay && sportsBigBoardStarted',APP)
        self.assertIn('if(sportsBigBoardStarted){',APP)
        self.assertIn("window.SBB_INFO_DRAWER?.close?.({manual:false})",APP)
        self.assertIn('.sbb-launch-screen{',STYLES)

    def test_score_date_browser_loads_arbitrary_days_from_espn(self):
        self.assertIn('const SCORE_DATE_STORE=window.SBB_SCORE_DATE||null',APP)
        self.assertIn('function setScoreBrowseDate(value,{animate=true,hold=9000,load=true}={})',APP)
        self.assertIn('async function ensureScoreDateLoaded(date,{force=false}={})',APP)
        self.assertIn('/api/espn/scoreboard?league=${encodeURIComponent(lg)}&date=${encodeURIComponent(date)}',APP)
        self.assertIn('schedule identity is fetched from ESPN directly',APP)
        self.assertIn('query several ESPN transports in parallel and UNION matching events',SERVER)

    def test_game_center_uses_inset_page_surface_not_glass_overlay(self):
        self.assertIn('Game Center is an inset continuation of the page, not glass',STYLES)
        self.assertIn('background:#070d12!important;',STYLES)
        self.assertIn('box-shadow:inset 0 2px 10px rgba(0,0,0,.31)',STYLES)
        self.assertIn('body.sbb-game-center-below .info-drawer{margin-top:5px!important}',STYLES)


    def test_launch_click_uses_single_playback_owner_and_provider_playing_reveals_video(self):
        self.assertNotIn("queueMicrotask(()=>waitForFirstPlayback(activeSlot,{timeoutMs:8000,userInitiated:true}))",APP)
        self.assertIn("reconcileActiveSlot({autoplay:true,userInitiated:true,reason:'launch screen play'})",APP)
        self.assertIn('confirmLaunchVisualPlayback(activeSlot,8000)',APP)
        self.assertIn('Observation only: never start, skip or recover media',APP)
        self.assertIn("setTimeout(()=>{ if(slot===activeSlot && youtubeEventMatchesClaim(slot)){ hideBumper(); swapRequestedAt=0; } },remaining)",APP)
        self.assertIn("setTimeout(()=>{ if(slot===activeSlot && !v.paused){ hideBumper(); swapRequestedAt=0; } },remaining)",APP)

    def test_score_ribbon_has_arbitrary_date_controls_on_both_edges(self):
        self.assertIn('id="scoreDayPager"',INDEX)
        self.assertIn('id="scoreDayPagerRight"',INDEX)
        self.assertIn('id="scoreDayIndicator"',INDEX)
        self.assertIn('id="scoreDatePicker"',INDEX)
        self.assertIn('data-score-date-step="-1"',INDEX)
        self.assertIn('data-score-date-step="1"',INDEX)
        self.assertIn("const btn=e.target.closest('[data-score-date-step]')",APP)
        self.assertIn('function stepScoreRibbonDate(delta)',APP)
        self.assertIn('date>today) date=today',APP)
        self.assertIn('v4.1.12 — score ribbon recovery',STYLES)
        self.assertIn('v4.1.12 — historical Date Browser',STYLES)
        self.assertIn('.score-day-pager-right{right:3px!important',STYLES)
        self.assertIn('pointer-events:auto!important',STYLES)

    def test_v302_desktop_ribbon_scroll_and_large_full_surface_date_arrows(self):
        self.assertIn('function wireScoreRibbonDesktopBrowse()',APP)
        self.assertIn("host.addEventListener('wheel',e=>",APP)
        self.assertIn("host.addEventListener('pointermove',e=>",APP)
        self.assertIn("host.classList.add('is-dragging')",APP)
        self.assertIn('v4.1.12 — desktop score-ribbon browsing + full-surface date arrows',STYLES)
        self.assertIn('.score-ribbon>.score-cells{cursor:grab!important}',STYLES)
        self.assertIn('width:40px!important;',STYLES)
        self.assertIn('min-height:68px!important;',STYLES)
        self.assertIn('.score-day-arrow:hover,.score-day-arrow:focus-visible{',STYLES)

    def test_v302_final_media_prefers_gold_then_green_then_extended_then_blue(self):
        self.assertIn('Gold commentary → Green quick recap → Purple extended → Blue reel',APP)
        self.assertIn('window.SBB_MEDIA_RESOLVER?.resolveBest?.(match||{}',APP)
        resolver=(ROOT/'architecture/media-resolver.js').read_text()
        self.assertIn('[REQ.COMMENTARY,REQ.QUICK,REQ.EXTENDED,REQ.MOMENTS]',resolver)
        self.assertIn("['gold','green','extended']",resolver)
        self.assertIn('HISTORY_TIER_PRIORITY = {"gold":4,"green":3,"extended":2,"blue":1}',SERVER)
        self.assertIn('catalogComplete',SERVER)
        self.assertIn("state='VERIFIED_UPGRADE_PENDING'",SERVER)
        self.assertIn('HISTORY_QUALITY_TARGET_TIER = "gold"',SERVER)
        self.assertIn('qualityComplete',SERVER)
        self.assertIn('upgradeEligible',SERVER)

    def test_pc_readability_pass_increases_microtype_without_blanket_bold(self):
        self.assertIn('desktop readability without turning the UI into bold display type',STYLES)
        self.assertIn('.key-info-item strong{font-size:11.5px!important',STYLES)
        self.assertIn('.score-team-abbr{font-size:14px!important;font-weight:650!important}',STYLES)
        self.assertIn('body.sbb-game-center-side .gc-play-row strong{font-size:10.5px!important',STYLES)
        self.assertIn('font-weight:550!important',STYLES)

    def test_nfl_day_inventory_is_independent_of_highlightly_and_rejects_weekly_envelopes(self):
        self.assertIn('Score inventory is not Highlightly-dependent',APP)
        self.assertIn('schedule identity is fetched from ESPN directly',APP)
        self.assertIn('const loadLeagueDay=async(date,day)=>',APP)
        self.assertIn("if(!rows.length && apiConfigured)",APP)
        self.assertIn("if league_key=='NFL' and target.month in (7,8)",SERVER)
        self.assertIn("'seasontype':1,'week':week",SERVER)
        self.assertIn("sport=='soccer' or league_key=='NFL'",SERVER)

    def test_us_score_authority_scopes_historical_inventory(self):
        self.assertIn('Build the result from the ESPN day inventory',SERVER)
        self.assertIn('provider=next((row for row in rows if _same_team_pair(row,auth)),None)',SERVER)
        self.assertNotIn('if not auth: merged.append(row); continue',SERVER)

    def test_loading_states_are_user_friendly_and_animated(self):
        self.assertIn('Loading Game Center…',GC)
        self.assertNotIn('Preparing Game Center locally',GC)
        self.assertIn('sbb-loading-spinner',GC)
        self.assertIn('id="videoLoadingOverlay"',INDEX)
        self.assertIn("setVideoLoadingOverlay(mode==='buffering'||mode==='starting'",APP)
        self.assertIn('@keyframes sbb-loading-spin',STYLES)

    def test_playback_waits_for_player_and_retries_exact_media_once(self):
        self.assertIn('function waitForYouTubeSlotReady(slot,item,epoch,timeoutMs=12000)',APP)
        self.assertIn('exact-media retry',APP)
        self.assertIn("setPlaybackUi('buffering')",APP)

    def test_scoreboard_deep_dive_has_preseason_and_soccer_rescue_paths(self):
        self.assertIn('Collect ESPN event rows across Site API, CDN and multi-league envelopes',SERVER)
        self.assertIn("for week in range(1,6)",SERVER)
        self.assertIn("'soccer-season'",SERVER)
        self.assertIn("'soccer-all'",SERVER)
        self.assertIn('fresh_for=45 if target>=viewer_today else 12*3600',SERVER)

    def test_mobile_recovery_tap_reloads_exact_youtube_media(self):
        self.assertIn('recovery tap: exact YouTube reload/play',APP)
        self.assertIn("if(actual!==wanted) p.loadVideoById({videoId:wanted,startSeconds:0})",APP)
        self.assertIn("if(playbackRecovery){ setVideoLoadingOverlay(false); return; }",APP)
        self.assertIn('forceReload=false',APP)
        self.assertIn('forceReload:true,epoch',APP)

    def test_ribbon_click_uses_muted_first_youtube_start_and_automatic_same_game_fallback(self):
        self.assertIn('start every YouTube tune muted first',APP)
        self.assertIn('const restoreAudio=!!(userInitiated || mediaInteractionUnlocked)',APP)
        self.assertIn('muted-first exact YouTube play',APP)
        self.assertIn('function tryScoreMediaFallback(failedItem,reason=',APP)
        self.assertIn('fallbackItems:resolvedSelection.ranked',APP)
        self.assertIn("tryScoreMediaFallback(item,'startup timeout after exact-media retry')",APP)
        self.assertIn('YouTube error ${code}',APP)
        self.assertIn('feed embed validation failed',SERVER)
        self.assertIn("row['embedValidated']=True",SERVER)

    def test_cold_youtube_player_keeps_score_click_claim_until_iframe_is_ready(self):
        self.assertIn('let youtubeStartAwaitingReady = { A:false, B:false }',APP)
        self.assertIn('youtubeStartAwaitingReady[slot]=true',APP)
        self.assertIn('const pendingControllerTune=!!youtubeStartAwaitingReady[slot]',APP)
        self.assertIn('pending controller tune retained',APP)
        self.assertIn("if(userPlaybackSession?.source==='score')",APP)
        self.assertIn('No playable recap source is available for this game right now.',APP)
        self.assertIn("bool(x.get('mediaUrl')) or bool(x.get('embedValidated'))",SERVER)

    def test_score_card_footer_has_non_overlapping_recap_button_geometry(self):
        self.assertIn('score-card geometry owns enough room for its footer controls',STYLES)
        self.assertIn('grid-template-columns:minmax(34px,1fr) auto 20px!important',STYLES)
        self.assertIn('height:102px!important;',STYLES)
        self.assertIn('height:84px!important',STYLES)
        self.assertIn('typeTag.dataset.short=',APP)
        self.assertIn('content:attr(data-short)',STYLES)
        self.assertIn('.score-ribbon{height:94px!important;min-height:94px!important}',STYLES)

    def test_game_center_player_stats_are_split_by_team_with_logos(self):
        self.assertIn('class="gc-team-logo-wrap"',INDEX)
        self.assertIn('gc-player-team-tabs',GC)
        self.assertIn('data-gc-player-side',GC)
        self.assertIn("activePlayerSide='away'",GC)
        self.assertIn("'teamSide':team_side",(ROOT/'sbb/game_center.py').read_text(encoding='utf-8'))
        self.assertIn("'teamSide':side",(ROOT/'sbb/game_center.py').read_text(encoding='utf-8'))
        self.assertIn('.gc-player-team-tab.active',STYLES)

    def test_score_ribbon_media_rail_has_vertical_safety_room(self):
        self.assertIn('leave real vertical room for the media-availability rail',STYLES)
        self.assertIn('.score-ribbon{height:96px!important;min-height:96px!important}',STYLES)
        self.assertIn('padding:2px 38px 0 38px!important',STYLES)
        self.assertIn('.media-availability-rail{height:3px!important;opacity:.78!important}',STYLES)
        self.assertIn('.score-ribbon{height:84px!important;min-height:84px!important}',STYLES)

    def test_full_recap_identity_and_runtime_playback_truth_drive_score_rail(self):
        self.assertIn('const RUNTIME_UNPLAYABLE_MEDIA=new Set()',APP)
        self.assertIn('function markRuntimeMediaFailed(item,reason=',APP)
        self.assertIn('function mediaMatchesScoreGame(item,match)',APP)
        self.assertIn('mediaMatchesScoreGame(x,match)',APP)
        self.assertIn('SBB_MEDIA_MANIFEST?.ingest?.(match,discovered)',APP)
        self.assertIn('SBB_MEDIA_MANIFEST?.playable?.(match)',APP)
        self.assertIn('SBB_MEDIA_MANIFEST?.markFailed?.(manifestEvent,item,reason)',APP)
        self.assertIn('if(!mediaMatchesKnownGame(item))',APP)
        self.assertIn("markRuntimeMediaFailed(failedItem,reason)",APP)
        self.assertIn("markRuntimeMediaFailed(failed,err?.message||'score playback failed')",APP)
        self.assertIn('tryHistoricalScoreMediaRecovery(failed',APP)
        self.assertIn('White Sox-Cubs attached to Braves-White Sox',APP)
        self.assertIn("String($('bumperKicker')?.textContent||'').trim()==='VIDEO UNAVAILABLE'",APP)

    def test_mlb_team_youtube_full_recaps_require_both_teams_and_cache_is_flushed(self):
        self.assertIn('if overview and match_strength<2:',SERVER)
        self.assertIn('mlb_rapid_v267_',SERVER)
        self.assertIn('team_v418_',SERVER)
        self.assertIn('_youtube_video_available_in_us(vd)',SERVER)

    def test_league_editorial_packages_are_first_class(self):
        editorial=(ROOT/'architecture/editorial-packages.js').read_text(encoding='utf-8')
        self.assertIn('MLB_TOP_PLAYS_DAILY',editorial)
        self.assertIn('NBA_TOP_PLAYS_NIGHTLY',editorial)
        self.assertIn('NFL_TOP_PLAYS_WEEKLY',editorial)
        self.assertIn("scope:'league'",editorial)
        self.assertIn('editorialScope',APP)
        self.assertIn('/api/editorial/series',SERVER)

    def test_youtube_embed_identity_uses_referrer_policy_and_153_is_not_media_poison(self):
        self.assertIn('<meta name="referrer" content="strict-origin-when-cross-origin"',INDEX)
        self.assertIn('self.send_header("Referrer-Policy","strict-origin-when-cross-origin")',SERVER)
        self.assertIn('widget_referrer:location.href',APP)
        start=APP.index('if(Number(code)===153)')
        end=APP.index('// 101/150 are video-specific',start)
        self.assertNotIn('markRuntimeMediaFailed',APP[start:end])

    def test_score_ribbon_centers_and_highlights_current_game_without_fighting_manual_browse(self):
        self.assertIn('function focusScoreRibbonForGame(eventLike,{force=false}={})',APP)
        self.assertIn('function scoreRibbonStableGameKey(item)',APP)
        self.assertIn('scoreRibbonFocusStableKey',APP)
        self.assertIn("card.dataset.sbbGameKey",APP)
        self.assertIn("card.classList.toggle('now-playing-game',active)",APP)
        self.assertIn("host.scrollTo({left,behavior:'smooth'})",APP)
        self.assertIn('cell.dataset.sbbGameKey=scoreRibbonStableGameKey(m)',APP)
        self.assertIn('.score-card.now-playing-game{',STYLES)
        self.assertIn('inset 0 0 0 2px',STYLES)
        self.assertIn("content:'NOW WATCHING'",STYLES)
        self.assertIn('if(changed&&resolved?.date&&resolved.date!==scoreBrowseDate)',APP)
        self.assertIn('manually browses away while the SAME game keeps playing',APP)
        self.assertNotIn('\\n\\n/* v4.1.12',STYLES)

    def test_unvalidated_official_nfl_feed_is_archived_but_never_hijacks_score_card(self):
        self.assertIn("'verifiedPlayable':False,'embedValidated':False,'externalOnly':True",SERVER)
        self.assertIn("row['verifiedPlayable']=True",SERVER)
        self.assertIn("row['externalOnly']=False",SERVER)
        self.assertIn('const EXTERNAL_MEDIA_BY_MATCH=new Map()',APP)
        self.assertIn('function externalMediaItemsForGame(match)',APP)
        self.assertIn("const type=selection.primary?highlightType(items,selection.primary):'none'",APP)
        self.assertIn('archivedExternal:!selection.primary&&!!externalPrimary',APP)
        self.assertNotIn("cell.onclick=()=>openExternalGameHighlights",APP)
        self.assertIn("cell.onclick=()=>playGameHighlights",APP)
        self.assertIn("syncSelectedEvent(gameCenterSelectionFromScoreMatch(match),{reason:'score-card selection',source:'score-ribbon'})",APP)

    def test_v417_nfl_dot_com_game_highlights_is_first_class_primary_lane(self):
        self.assertIn('NFL_GAME_HIGHLIGHTS_CHANNEL_URL = "https://www.nfl.com/videos/channel/game-highlights-vc"',SERVER)
        self.assertIn('def _nfl_game_highlights_results',SERVER)
        self.assertIn('def _nfl_public_video_results',SERVER)
        self.assertIn('def _nfl_team_video_results',SERVER)
        discover=SERVER[SERVER.index('def _history_discover_event'):SERVER.index('def _history_discover_day',SERVER.index('def _history_discover_event'))]
        public_quick="lane('nfl-public-video-quick',lambda:_nfl_public_video_results(date,away,home,max_items=6,validate_native=False,allow_historical=True,objective='quick'),'primary')"
        team_quick="lane('nfl-team-video-quick',lambda:_nfl_team_video_results(date,away,home,max_items=6,validate_native=False,objective='quick'),'primary')"
        public_extended="lane('nfl-public-video-extended',lambda:_nfl_public_video_results(date,away,home,max_items=6,validate_native=False,allow_historical=True,objective='extended'),'primary')"
        team_extended="lane('nfl-team-video-extended',lambda:_nfl_team_video_results(date,away,home,max_items=6,validate_native=False,objective='extended'),'primary')"
        for lane in (public_quick,team_quick,public_extended,team_extended):
            self.assertIn(lane,discover); self.assertLess(discover.index(lane),discover.index("lane('official-native'"))
        self.assertIn("'nfl-public-video-quick','nfl-public-video-extended','nfl-team-video-quick','nfl-team-video-extended'",SERVER)

    def test_v419_official_source_catchup_is_versioned_recent_first_and_official_only(self):
        self.assertIn('HISTORY_OFFICIAL_CATCHUP_SOURCES = {',SERVER)
        for source in ('nfl-game-highlights','nhl-official-video','premierleague-official','nbc-epl-extended','mls-official-web'):
            self.assertIn(source,SERVER)
        self.assertIn('def _history_official_source_catchup_event',SERVER)
        self.assertIn("query_type='OFFICIAL_SOURCE_CATCHUP'",SERVER)
        self.assertIn('source_enrichment_events(HISTORY_OFFICIAL_CATCHUP_SOURCES',SERVER)
        self.assertIn("target_kind='official-catchup'",SERVER)
        self.assertIn("phase=f'official-catchup:{league.lower()}'",SERVER)
        catch=SERVER[SERVER.index('def _history_official_source_catchup_event'):SERVER.index('def _history_official_catchup_snapshot')]
        self.assertNotIn('youtube-public-page',catch); self.assertNotIn('youtube-public-index',catch); self.assertNotIn('youtube-official-day-search',catch)
        source_call=SERVER[SERVER.index('def _history_official_catchup_source_call'):SERVER.index('def _history_mark_normal_discovery_enrichments')]
        self.assertIn("allow_historical=True",source_call)
        ui=Path(ROOT/'ui'/'history-audit.js').read_text()
        self.assertIn('[OFFICIAL SOURCE CATCH-UP]',ui); self.assertIn('officialCatchupLine',ui)

    def test_v418_official_content_sources_are_primary_and_round_aware(self):
        self.assertIn('NHL_GAME_RECAPS_URL = "https://www.nhl.com/video/topic/game-recaps/"',SERVER)
        self.assertIn('NHL_CONDENSED_GAMES_URL = "https://www.nhl.com/video/topic/condensed-games/"',SERVER)
        self.assertIn('PREMIER_LEAGUE_VIDEO_URL = "https://www.premierleague.com/en/video/"',SERVER)
        self.assertIn('NBC_EPL_VIDEO_URL = "https://www.nbcsports.com/soccer/premier-league"',SERVER)
        self.assertIn('MLS_MATCH_HIGHLIGHTS_URL = "https://www.mlssoccer.com/video/topics/match-highlights/"',SERVER)
        self.assertIn('MLS_ALL_GOALS_URL = "https://www.mlssoccer.com/video/topics/all-goals/"',SERVER)
        discover=SERVER[SERVER.index('def _history_discover_event'):SERVER.index('def _history_discover_day',SERVER.index('def _history_discover_event'))]
        for lane in ("lane('nhl-official-video'","lane('premierleague-official'","lane('nbc-epl-extended'","lane('mls-match-snapshot'","lane('mls-match-highlights'"):
            self.assertIn(lane,discover)
            self.assertLess(discover.index(lane),discover.index("lane('official-native'"))
        self.assertIn("lane('nhl-official-roundups'",discover)
        self.assertIn("lane('premierleague-roundups'",discover)
        self.assertIn("lane('mls-roundups'",discover)
        self.assertIn("ROUND_LEAGUE",Path(ROOT/'sbb'/'media_scope.py').read_text())
        self.assertIn("SCORING_ROUNDUP",Path(ROOT/'sbb'/'media_scope.py').read_text())
        self.assertIn('team_v418_',SERVER)

    def test_official_nfl_keyless_matchup_packages_surface_as_extended_with_direct_link(self):
        start=SERVER.index('def _official_nfl_feed_videos')
        end=SERVER.index('def generic_rapid_team_videos',start)
        block=SERVER[start:end]
        self.assertIn("'recapTier':'extended'",block)
        self.assertIn("'externalUrl':f'https://www.youtube.com/watch?v={vid}'",block)

    def test_v290_historical_scores_and_media_share_one_server_owned_event_inventory(self):
        self.assertIn('def _history_get_league_scores',SERVER)
        self.assertIn('parsed.path == "/api/history/scores"',SERVER)
        loader=APP[APP.index('async function loadScoreDateLeagueMatches'):APP.index('async function rapidHistoricalGameMedia')]
        self.assertIn('/api/history/scores?date=',loader)
        self.assertNotIn('/api/sports/',loader)
        self.assertNotIn('/api/mlb/fallback-matches',loader)

    def test_v290_historical_media_is_server_owned_event_catalog_with_runtime_truth(self):
        self.assertIn('from sbb.youtube_gateway import YouTubeGateway, YouTubeRateLimited',SERVER)
        self.assertIn('def _official_youtube_day_activity_catalog',SERVER)
        self.assertIn('def _official_youtube_day_search_catalog',SERVER)
        self.assertIn('def _history_discover_event',SERVER)
        self.assertIn('def _history_playback_plan',SERVER)
        self.assertIn('/api/history/event/discover',SERVER)
        self.assertIn('/api/history/event/media',SERVER)
        self.assertIn('/api/history/media/runtime',SERVER)
        self.assertIn('HISTORY_DISCOVERY_VERSION = 15',SERVER)
        self.assertIn('_touch_history_focus(date',SERVER)
        self.assertIn('team_v418_',SERVER)
        self.assertIn("apiJson('/api/history/event/discover'",APP)
        self.assertIn("fetch('/api/history/media/runtime'",APP)
        hist=APP[APP.index('async function rapidHistoricalGameMedia'):APP.index('async function loadScoreDateLeagueMedia')]
        self.assertNotIn('/api/rapid-team-videos',hist)
        self.assertNotIn('/api/mlb/rapid-highlights',hist)


    def test_v304_history_audit_is_visible_and_exportable(self):
        self.assertIn('id="openHistoryAuditBtn"',INDEX)
        self.assertIn('id="historyAuditModal"',INDEX)
        self.assertIn('/api/history/audit',SERVER)
        self.assertIn('/api/history/audit.csv',SERVER)
        self.assertIn('/api/history/audit.xlsx',SERVER)
        self.assertIn('Gold, Green, Purple and Blue',INDEX)
        self.assertIn('historyAuditTableBody',AUDIT)
        self.assertIn("exportFile('xlsx')",AUDIT)
        self.assertIn('BEST_GOALS',INDEX); self.assertIn('BEST_SAVES',INDEX)
        self.assertIn('[MEDIA OBJECTIVES]',AUDIT); self.assertIn('[MEDIA NORMALIZATION]',AUDIT)

    def test_v4111_rule_catchup_reopens_nfl_mls_epl_and_tracks_silver_replay(self):
        self.assertIn('HISTORY_RULE_CATCHUP_LEAGUES = ("NFL","MLS","EPL")',SERVER)
        self.assertIn('"nfl-public-video-quick","version":1,"objective":"quick"',SERVER)
        self.assertIn('"nfl-team-video-quick","version":1,"objective":"quick"',SERVER)
        self.assertIn('"nfl-public-video-extended","version":1,"objective":"extended"',SERVER)
        self.assertIn('"nfl-team-video-extended","version":1,"objective":"extended"',SERVER)
        self.assertIn('"mls-match-snapshot","version":2,"objective":"quick"',SERVER)
        self.assertIn('"mls-match-highlights","version":2,"objective":"extended"',SERVER)
        self.assertIn('"premierleague-official","version":4,"objective":"quick"',SERVER)
        self.assertIn('"nbc-epl-extended","version":3,"objective":"extended"',SERVER)
        self.assertIn('HISTORY_RULE_CATCHUP_VERSION = 2',SERVER)
        self.assertIn('def _history_rule_game_catchup_snapshot',SERVER)
        self.assertIn("preferred_rule_league={1:'NFL',2:'MLS',3:'EPL'}.get(worker_index,'')",SERVER)
        self.assertIn('def history_rule_collection_catchup_worker',SERVER)
        self.assertIn('sbb-history-rule-collections',SERVER)
        self.assertIn('[RULE GAME CATCH-UP]',AUDIT)
        self.assertIn('[RULE COLLECTION CATCH-UP]',AUDIT)

    def test_v305_audit_projects_unknown_into_actionable_statuses(self):
        self.assertIn('UNINDEXED',INDEX); self.assertIn('SEARCHED EMPTY',INDEX); self.assertIn('COVERAGE COMPLETE',INDEX)
        self.assertIn('historyAuditStatusSummary',INDEX)
        self.assertIn('effectiveStatus',AUDIT)
        self.assertIn('Discovery v',AUDIT)
        self.assertIn("'Audit Status'",SERVER)
        self.assertIn("'Discovery Pending'",SERVER)
        self.assertIn('current_discovery_version=HISTORY_DISCOVERY_VERSION',SERVER)

    def test_v304_green_recap_discovery_uses_official_uploads_playlist(self):
        self.assertIn('def _official_youtube_uploads_index',SERVER)
        self.assertIn('/playlistItems?',SERVER)
        self.assertIn("lane('youtube-official-uploads'",SERVER)
        self.assertIn('youtube-official-uploads',SERVER)
        self.assertIn('HISTORY_DISCOVERY_VERSION = 15',SERVER)

    def test_historical_date_session_keeps_browse_playback_and_game_center_separate(self):
        date_store=(ROOT/'architecture/score-date-store.js').read_text(encoding='utf-8')
        self.assertIn('let browseDate=localDateISO(0)',date_store)
        self.assertIn('let playbackDate=localDateISO(0)',date_store)
        self.assertIn('function programForScoreDate(date)',APP)
        self.assertIn('activatePlaybackDateContext(playbackDate',APP)
        self.assertIn('PROGRAM=dateProgramWithSelectionFirst(playbackDate,selectionItems)',APP)
        self.assertIn('resumeDateProgramAfterSelection()',APP)
        self.assertIn("syncSelectedEvent(gameCenterSelectionFromScoreMatch(match)",APP)
        self.assertIn('scoreMatchesForDate(itemDate)',APP)

    def test_return_to_today_is_full_session_action(self):
        self.assertIn('id="returnTodayBtn"',INDEX)
        self.assertIn('async function returnToToday()',APP)
        block=APP[APP.index('async function returnToToday()'):APP.index('function beginScorePlaybackSession',APP.index('async function returnToToday()'))]
        self.assertIn('setScoreBrowseDate(today',block)
        self.assertIn('activatePlaybackDateContext(today',block)
        self.assertIn('const todayProgram=programForScoreDate(today)',block)
        self.assertIn('PlaybackController.tuneProgramIndex',block)
        self.assertIn("You're back to Today",block)
        self.assertIn('.top-nav-header .return-today-btn',STYLES)

    def test_historical_game_center_cache_is_long_lived_only_when_final(self):
        self.assertIn('historicalFinal',CONTRACT)
        self.assertIn('historicalFinal?24*60*60*1000',CONTRACT)
        self.assertIn('hitPartial?1500',CONTRACT)

    def test_nfl_quick_recap_prefers_three_minute_window_but_keeps_short_fallback(self):
        policy=(ROOT/'architecture/sport-media-policy.js').read_text(encoding='utf-8')
        self.assertIn("'american-football'",policy)
        self.assertIn('quick:{ideal:[150,300],accept:[45,390],target:210}',policy)
        self.assertIn('extended:{ideal:[720,1080],accept:[540,1800],target:900}',policy)
        self.assertIn('SBB_SPORT_MEDIA_POLICY?.durationScore',APP)

    def test_native_media_buffering_uses_larger_startup_cache_and_balanced_espn_encode(self):
        self.assertIn('str(16*1024*1024)',SERVER)
        source_block=SERVER[SERVER.index('def _espn_video_media_url'):SERVER.index('def _espn_video_allowed_us')]
        self.assertIn("for key in ('full','SD','sd','mobile','HD','hd','mezzanine')",source_block)
        self.assertLess(source_block.index("'full'"),source_block.index("'mezzanine'"))

    def test_score_click_primes_exact_native_asset_without_new_playback_owner(self):
        self.assertIn("priority:4,priorityClass:(window.SBB_MEDIA_WORK?.PRIORITY.TOUCH_INTENT||'TOUCH_INTENT')",APP)
        self.assertIn("fetch('/api/media/prepare'",APP)
        self.assertIn('it only makes the proxy cache fill ahead of the active decoder',APP)


    def test_v27_media_resolver_manifest_and_transport_are_provider_independent(self):
        manifest=(ROOT/'architecture/media-manifest.js').read_text(encoding='utf-8')
        resolver=(ROOT/'architecture/media-resolver.js').read_text(encoding='utf-8')
        transports=(ROOT/'architecture/playback-transports.js').read_text(encoding='utf-8')
        health=(ROOT/'architecture/provider-health.js').read_text(encoding='utf-8')
        self.assertIn("DIRECT_VIDEO:'DIRECT_VIDEO'",transports)
        self.assertIn("YOUTUBE_EMBED:'YOUTUBE_EMBED'",transports)
        self.assertIn('function playable(eventLike)',manifest)
        self.assertIn('function markBuffering(eventLike,asset)',manifest)
        self.assertIn('function resolve(eventLike,request',resolver)
        self.assertIn('SBB_PROVIDER_HEALTH?.score?.(provider(asset))',resolver)
        self.assertIn('bufferingCount',resolver)
        self.assertIn('function failure(provider,reason=',health)
        self.assertNotIn('MLB_NATIVE',APP)

    def test_v27_sport_media_policy_owns_recap_duration_preferences(self):
        policy=(ROOT/'architecture/sport-media-policy.js').read_text(encoding='utf-8')
        server_policy=(ROOT/'sbb/media_policy.py').read_text(encoding='utf-8')
        self.assertIn("'american-football'",policy)
        self.assertIn('ideal:[150,300]',policy)
        self.assertIn('ideal:[720,1080]',policy)
        self.assertIn('accept:[45,390]',policy)
        self.assertIn('window.SBB_SPORT_MEDIA_POLICY?.durationScore?.(d,policy?.quick)',APP)
        self.assertIn('"american-football"',server_policy)

    def test_v27_generic_direct_video_uses_event_scoped_local_cache(self):
        self.assertIn("transportForAsset?.(item)==='DIRECT_VIDEO'",APP)
        self.assertIn('&eventId=${encodeURIComponent(eventId)}',APP)
        self.assertIn('eventId:x.item?.eventId||x.item?.matchId||x.item?.gamePk',APP)
        self.assertIn('event_id=(qs.get("eventId") or qs.get("gamePk")',SERVER)
        self.assertIn('selected upstream source',SERVER)

    def test_v27_generic_paths_do_not_default_missing_league_to_mlb(self):
        core=(ROOT/'core-model.js').read_text(encoding='utf-8')
        identity=(ROOT/'architecture/event-identity.js').read_text(encoding='utf-8')
        self.assertNotRegex(APP,r"\|\|['\"]MLB['\"]")
        self.assertNotRegex(identity,r"\|\|['\"]MLB['\"]")
        self.assertIn("'SPORTS'",core)

    def test_v27_game_center_sections_preserve_explicit_team_and_category(self):
        core=(ROOT/'core-model.js').read_text(encoding='utf-8')
        policy=(ROOT/'architecture/game-center-policy.js').read_text(encoding='utf-8')
        self.assertIn('teamSide:clean(input.teamSide).toLowerCase()',core)
        self.assertIn('category:clean(input.category)',core)
        self.assertIn('function categoryFromTitle',policy)
        self.assertIn('teamAbbreviation',policy)

    def test_v27_server_exposes_competition_media_adapter_architecture(self):
        providers=(ROOT/'sbb/provider_registry.py').read_text(encoding='utf-8')
        competitions=(ROOT/'sbb/competition_registry.py').read_text(encoding='utf-8')
        self.assertIn('MEDIA_ADAPTERS={',providers)
        self.assertIn('"nfl-public-video"',providers); self.assertIn('"nfl-team-video"',providers)
        self.assertIn('"nfl-club"',providers)
        self.assertIn('"espn"',providers)
        self.assertIn('"mediaManifest":"browser persistent event manifest"',SERVER)
        self.assertIn('"mediaResolver":"provider-independent package resolver"',SERVER)
        self.assertIn('"NFL"',competitions)

    def test_youtube_asset_embed_failure_does_not_poison_provider_health(self):
        self.assertIn("markRuntimeMediaFailed(failed,`YouTube error ${code}`,{providerFailure:false})",APP)
        self.assertIn("SBB_PROVIDER_HEALTH?.failure?.('YOUTUBE','embed identity 153'",APP)


    def test_v281_top_date_selector_is_always_available_and_return_today_is_separate(self):
        self.assertIn('id="topDateSelectBtn"',INDEX)
        self.assertIn('id="topDateSelectLabel"',INDEX)
        self.assertIn("return 'SELECT DATE'",APP)
        self.assertIn("dateBtn.dataset.historical=scoreBrowseDate===today?'false':'true'",APP)
        self.assertIn("topDateBtn.addEventListener('click',openScoreDatePicker)",APP)
        self.assertIn('.top-date-controls',STYLES)

    def test_v281_historical_scores_hydrate_from_persistent_catalog_and_render_progressively(self):
        self.assertIn('async function hydrateScoreDateFromHistory(date)',APP)
        self.assertIn('/api/history/day?date=',APP)
        block=APP[APP.index('async function ensureScoreDateLoaded(date,{force=false}={})'):APP.index('async function selectHistoricalGameWithoutMedia',APP.index('async function ensureScoreDateLoaded(date,{force=false}={})'))]
        self.assertIn('renderScoresFromMatchesCombined(false)',block)
        self.assertIn('const needed=force?',block)
        self.assertIn('hasLeagueMatchesSnapshot',block)

    def test_v282_historical_date_automatically_searches_every_missing_game(self):
        self.assertIn('HISTORICAL_MEDIA_DISCOVERY_CONCURRENCY=3',APP)  # touch-priority fallback remains bounded
        self.assertIn('startHistoricalDateDiscovery(date)',APP)
        self.assertIn("fetch('/api/history/discover'",APP)
        self.assertNotIn('HISTORICAL_RAPID_SEED_PER_LEAGUE',APP)
        historical_loader=APP[APP.index('async function loadScoreDateLeagueMedia'):APP.index('async function ensureScoreDateLoaded',APP.index('async function loadScoreDateLeagueMedia'))]
        self.assertNotIn('const jobs=missing.map',historical_loader)
        self.assertNotIn('Promise.allSettled(jobs)',historical_loader)
        self.assertIn("queueHistoricalGameMedia(match,{priority:true})",APP)

    def test_v281_history_catalog_persists_scores_media_and_backfills_in_background(self):
        history=(ROOT/'sbb/history_repository.py').read_text(encoding='utf-8')
        self.assertIn('class HistoryRepository',history)
        self.assertIn('CREATE TABLE IF NOT EXISTS history_day',history)
        self.assertIn('HISTORY_REPOSITORY = HistoryRepository',SERVER)
        self.assertIn('def history_backfill_worker():',SERVER)
        self.assertIn('target=history_backfill_worker',SERVER)
        self.assertIn('parsed.path == "/api/history/day"',SERVER)
        self.assertIn("parsed.path == '/api/history/media'",SERVER)
        self.assertIn('allow_youtube=True',SERVER)
        self.assertIn('no-search-quota media backfill',SERVER)
        self.assertIn('def _history_server_idle():',SERVER)
        self.assertIn('while not _history_server_idle():',SERVER)

    def test_v281_historical_game_center_selection_does_not_claim_now_watching_before_media_exists(self):
        block=APP[APP.index('async function selectHistoricalGameWithoutMedia(match){'):APP.index('async function refreshSoccerLeague',APP.index('async function selectHistoricalGameWithoutMedia(match){'))]
        self.assertNotIn('focusScoreRibbonForGame(selected||match',block)
        self.assertIn('if(playable.length) playGameHighlights',block)
    def test_historical_media_pipeline_is_date_scoped_and_server_owned(self):
        self.assertIn("startHistoricalDateDiscovery(date)",APP)
        self.assertIn("/api/history/discover",APP)
        self.assertIn("HISTORY DB •",APP)
        self.assertIn("renderHistoricalDateDiagnostics",APP)
        self.assertIn("needsRefresh",SERVER)
        historical_loader=APP[APP.index('async function loadScoreDateLeagueMedia'):APP.index('async function ensureScoreDateLoaded',APP.index('async function loadScoreDateLeagueMedia'))]
        self.assertNotIn("const missing=(matches||[]).filter(isHighlightEligible)",historical_loader)

    def test_historical_diagnostics_are_not_overwritten_by_today_background_status(self):
        self.assertIn("historical?'LIVE API RATE LIMITED':'API RATE LIMITED'",APP)
        self.assertIn('candidates',APP)
        self.assertIn("'archivedOnlyMedia':len(archived_only)",SERVER)

    def test_v290_historical_foreground_pauses_today_discovery_and_search_traffic(self):
        self.assertIn('function historicalForegroundActive()',APP)
        self.assertIn('if(historicalForegroundActive()) return;',APP)
        self.assertIn('if(!first && historicalForegroundActive()) return;',APP)
        rapid=APP[APP.index('async function rapidEnrichOtherSport'):APP.index('const SBB_SOCCER_SNAPSHOT_PREFIX',APP.index('async function rapidEnrichOtherSport'))]
        self.assertIn('{force=false}={}',rapid)
        self.assertIn('if(historicalForegroundActive()) return [];',rapid)
        self.assertIn('if(historicalForegroundActive()) break;',rapid)

    def test_historical_cards_reflect_full_date_discovery_progress(self):
        self.assertIn("const dateDiscovery=historicalDiscoveryState(scoreBrowseDate)",APP)
        self.assertIn("['QUEUED','SEARCHING']",APP)
        self.assertIn("historical-searching-media",APP)

    def test_editorial_malformed_response_is_softened_and_retried(self):
        self.assertIn("OpenAI retry pending",APP)
        self.assertNotIn("?'OpenAI response malformed'",APP)
        self.assertIn("_openai_json_object",SERVER)
        self.assertIn("for offset in range(0,len(candidates),6)",SERVER)

    def test_v291_api_json_preserves_post_request_options(self):
        self.assertIn('async function apiJson(url,options={})',APP)
        block=APP[APP.index('async function apiJson(url,options={})'):APP.index('function setCoverageStep',APP.index('async function apiJson(url,options={})'))]
        self.assertIn("const init={cache:'no-store',...(options||{})}",block)
        self.assertIn('fetch(url, init)',block)
        hist=APP[APP.index('async function rapidHistoricalGameMedia'):APP.index('async function loadScoreDateLeagueMedia',APP.index('async function rapidHistoricalGameMedia'))]
        self.assertIn("method:'POST'",hist)
        self.assertIn('/api/history/event/media?date=',hist)

    def test_v291_normalized_catalog_media_hydrates_even_without_legacy_media_saved_at(self):
        block=APP[APP.index('async function hydrateScoreDateFromHistory(date)'):APP.index('function pumpHistoricalMediaSearchQueue',APP.index('async function hydrateScoreDateFromHistory(date)'))]
        self.assertIn('if(Array.isArray(state.media))',block)
        self.assertNotIn('if(Number(state.mediaSavedAt||0)>0)',block)
        self.assertIn('storeScoreDateMedia(lg,date,rows)',block)

    def test_v291_history_diagnostics_distinguish_catalog_assets_from_ribbon_ready_games(self):
        block=APP[APP.index('function renderHistoricalDateDiagnostics'):APP.index('async function refreshHistoricalDiscoverySnapshot',APP.index('function renderHistoricalDateDiagnostics'))]
        self.assertIn('ribbon-ready',block)
        self.assertIn('verified assets',block)
        self.assertIn('RIBBON ${Number(browserInv.playableGames||0)}',block)

    def test_v291_history_focus_suppresses_today_search_list_noise(self):
        self.assertIn("if _history_focus_active() and str(date or '')[:10] >= _date_iso(-1): return []",SERVER)
        self.assertIn("if not YOUTUBE_GATEWAY.operation_available('search'): return []",SERVER)
        self.assertIn("allow_youtube=False",SERVER)


    def test_v306_open_browser_does_not_disable_background_history_workers(self):
        self.assertIn("siteOpenDoesNotPause",SERVER)
        self.assertIn("CLIENT_ACTIVITY_STATE['lastPassive']=time.time()",SERVER)
        self.assertIn("def _history_background_status():",SERVER)
        self.assertIn("BACKGROUND_MEDIA_PAUSE_SECONDS",SERVER)
        get_block=SERVER[SERVER.index('    def do_GET(self):'):SERVER.index('        if parsed.path == "/api/history/scores":',SERVER.index('    def do_GET(self):'))]
        self.assertNotIn("elif parsed.path.startswith('/api/'): CLIENT_ACTIVITY_STATE['lastInteractive']=time.time()",get_block)

    def test_v306_green_gap_queue_targets_games_not_blue_asset_volume(self):
        repo=(ROOT/'sbb/history_repository.py').read_text(encoding='utf-8')
        self.assertIn('def green_gap_events',repo)
        self.assertIn("has_green",repo)
        self.assertIn("has_blue",repo)
        self.assertIn('def history_green_gap_worker(worker_index=1):',SERVER)
        self.assertIn('target=history_green_gap_worker,args=(worker_index,)',SERVER)
        self.assertIn("_history_console_log(worker_name",SERVER)
        self.assertIn('allow_search_rescue=allow_rescue',SERVER)

    def test_v306_authoritative_event_story_can_promote_to_green(self):
        self.assertIn('def _history_promote_authoritative_recap',SERVER)
        self.assertIn("'espn-event-video','mlb-game-content'",SERVER)
        self.assertIn("90 <= dur <= 420",SERVER)
        self.assertIn('\"sourceType\":\"mlb-game-content\"',SERVER)
        self.assertIn('authoritativeRecapPromotion',SERVER)

    def test_v307_live_search_console_exposes_worker_health_and_release_mismatch(self):
        repo=(ROOT/'sbb/history_repository.py').read_text(encoding='utf-8')
        workflow=(ROOT/'.github/workflows/deploy-pages.yml').read_text(encoding='utf-8')
        deploy=(ROOT/'cloud/gcp/DEPLOY-FROM-GITHUB.sh').read_text(encoding='utf-8')
        self.assertIn('id="historySearchConsoleOutput"',INDEX)
        self.assertIn('/api/history/worker-console',SERVER)
        self.assertIn('green_gap_summary',repo)
        self.assertIn('historyDiscoveryVersion',SERVER)
        self.assertIn('RELEASE MISMATCH',AUDIT)
        self.assertIn('Search Console endpoint missing',AUDIT)
        self.assertIn('Expected backend:',workflow)
        self.assertIn('Version mismatch: expected backend',deploy)

    def test_v410_bounded_green_pool_and_audit_worker_observability(self):
        self.assertIn('SBB_GREEN_WORKERS',SERVER)
        self.assertIn('def claim_event', (ROOT/'sbb/history_repository.py').read_text(encoding='utf-8'))
        self.assertIn('HISTORY_PROVIDER_SEMAPHORES',SERVER)
        self.assertIn('target=history_green_gap_worker,args=(worker_index,)',SERVER)
        self.assertIn('id="historySearchWorkerGrid"',INDEX)
        self.assertIn('greenPool',AUDIT); self.assertIn('providerConcurrency',AUDIT); self.assertIn('[SILVER]',AUDIT)

    def test_v307_green_gap_worker_accepts_legacy_historical_rows_and_mlb_rescue(self):
        self.assertIn('def _history_gap_event_ready',SERVER)
        self.assertIn('event_date < today',SERVER)
        self.assertIn("allow_rescue=bool(before in ('blue','none','extended')",SERVER)
        discover=SERVER[SERVER.index('def _history_discover_event'):SERVER.index('def _history_discover_day')]
        self.assertIn("lane('youtube-official-day-search'",discover)
        self.assertIn("lane('youtube-public-page'",discover)

    def test_v412_backfill_is_one_time_fixed_floor_seed(self):
        self.assertIn('SBB_HISTORY_BACKFILL_FLOOR_DATE',SERVER)
        self.assertIn('2025-08-01',SERVER)
        worker=SERVER[SERVER.index('def history_backfill_worker():'):SERVER.index('def game_center_refresh_worker():')]
        self.assertIn('_history_backfill_seed_dates(base)',worker)
        self.assertIn('_history_backfill_seed_date_complete(date)',worker)
        self.assertIn('_history_mark_backfill_seed_complete()',worker)
        self.assertIn("'complete:historical-seed'",SERVER)
        self.assertNotIn('range(1,HISTORY_BACKFILL_DAYS+1)',worker)
        self.assertIn('SEED COMPLETE through',AUDIT)

    def test_v411_tier_aware_short_circuit_and_efficiency_observability(self):
        discover=SERVER[SERVER.index('def _history_discover_event'):SERVER.index('def _history_discover_day')]
        self.assertIn("pass_target_tier='green'",SERVER)
        self.assertIn('def primary_checkpoint',discover)
        self.assertIn('def fallback_checkpoint',discover)
        self.assertIn("if not primary_target_hit",discover)
        self.assertIn("if not fallback_target_hit and allow_search_rescue",discover)
        self.assertIn('HISTORY_DISCOVERY_EFFICIENCY',SERVER)
        self.assertIn("'discoveryEfficiency':_history_efficiency_snapshot()",SERVER)
        self.assertIn('[DISCOVERY EFFICIENCY]',AUDIT)
        self.assertIn('[QUARANTINE REASONS]',AUDIT)
        self.assertIn('quarantineReasons',(ROOT/'sbb/history_repository.py').read_text(encoding='utf-8'))
        self.assertIn('known games / +',SERVER)

    def test_v416_history_audit_shows_coverage_complete_and_semantic_color_badges(self):
        repo=(ROOT/'sbb/history_repository.py').read_text(encoding='utf-8')
        styles=(ROOT/'styles.css').read_text(encoding='utf-8')
        self.assertIn('historyAuditCoverageCompleteSummary',INDEX)
        self.assertIn('historyAuditCoverageComplete',INDEX)
        self.assertIn('coverageCompleteByLeague',repo)
        self.assertIn('coverageCompleteGames',repo)
        self.assertIn('Coverage complete (Gold / Green / Purple)',AUDIT)
        for token in ('league-mlb','league-nfl','league-nba','league-nhl','league-epl','league-mls','kind-daily-recap','kind-weekly-recap','kind-top-plays','scope-daily','scope-weekly'):
            self.assertIn(token,styles)
        self.assertIn('leagueBadge(row.league)',AUDIT)
        self.assertIn('silverKindBadge(row.collectionKind)',AUDIT)

    def test_v306_history_audit_is_live_and_shows_green_game_coverage(self):
        self.assertIn('historyAuditGreenCoverageSummary',INDEX)
        self.assertIn('greenCoverageByLeague', (ROOT/'sbb/history_repository.py').read_text(encoding='utf-8'))
        self.assertIn('auto-refresh 30s',AUDIT)
        self.assertIn('setInterval',AUDIT)
        self.assertIn('BACKGROUND SEARCH ACTIVE',AUDIT)

    def test_v308_search_console_is_copyable_and_distinguishes_yield_from_error(self):
        self.assertIn('historySearchConsoleCopyIssues', INDEX)
        self.assertIn('historySearchConsoleCopyAll', INDEX)
        self.assertIn('historySearchConsoleDownload', INDEX)
        self.assertIn('consoleIssuesReport', AUDIT)
        self.assertIn('consoleFullReport', AUDIT)
        self.assertIn('navigator.clipboard.writeText', AUDIT)
        self.assertIn('limit=320', AUDIT)
        self.assertIn('QUOTA EXHAUSTED', AUDIT)
        self.assertIn('EXHAUSTED ${used}/${limit}', AUDIT)
        self.assertIn("not in ('media-playback','foreground-history-discovery','foreground-request','playback-priority')", SERVER)
        self.assertIn('Historical YouTube search budget exhausted', SERVER)

    def test_v309_operator_priority_modes_suspend_the_opposite_resource(self):
        repo=(ROOT/'sbb/history_repository.py').read_text(encoding='utf-8')
        self.assertIn('historyModeSearch', INDEX)
        self.assertIn('historyModeBalanced', INDEX)
        self.assertIn('historyModePlayback', INDEX)
        self.assertIn('/api/history/work-mode', SERVER)
        self.assertIn('HISTORY_WORK_MODES = ("search","balanced","playback")', SERVER)
        self.assertIn("if mode=='playback':", SERVER)
        self.assertIn("elif mode=='search':", SERVER)
        self.assertIn('PLAYBACK_SUSPENDED_BY_SEARCH_PRIORITY', SERVER)
        self.assertIn('SEARCH_PAUSED_BY_PRIORITY', SERVER)
        self.assertIn('searchPriorityPlaybackLock', INDEX)
        self.assertIn('sbbPlaybackAllowed', APP)
        self.assertIn("window.addEventListener('sbb:workmode'", APP)
        self.assertIn("recent_cutoff", repo)
        self.assertIn('recent_no_media', repo)
        self.assertIn('recent_gaps', repo)


if __name__=='__main__': unittest.main()
