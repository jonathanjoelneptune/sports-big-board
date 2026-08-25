# Sports Big Board v4.1.24

> v4.1.24 is the **Historical Ribbon Recovery + Cache-Bust** release. It preserves the v4.1.23 catalog-first runtime, rolling schedule sync, interactive playlist manager, Android audit repair, five-worker recovery pool, Discovery v15, Matcher v7, Rule Game Catch-up v10, and Rule Collection Catch-up v8 while replacing the historical score-ribbon first paint with an explicit lightweight SQLite contract.

## v4.1.24 — historical ribbon recovery + cache-bust

- **New static asset generation:** every Pages script/style URL advances to `?v=4.1.24`, so Android Chrome and GitHub Pages cannot keep executing an older `app.js?v=4.1.23` after deployment.
- **Compact historical ribbon endpoint:** `/api/history/ribbon?date=YYYY-MM-DD` returns canonical score rows plus compact exact-event playable-media plans without the full audit/source-media payload. Historical score cards can paint before deeper media hydration finishes.
- **Persisted historical authority:** historical seed completeness is read from SQLite catalog metadata, not only the delayed in-memory worker heartbeat. A backend restart cannot temporarily turn a seeded date back into a provider-dependent date.
- **Bounded mobile load:** the compact historical ribbon read has a 6.5-second deadline and the full history hydration has a 10-second deadline. A stalled mobile/network request cannot leave the ribbon in `Loading games…` forever; the UI surfaces an explicit catalog error instead.
- **Score-first, media-second:** canonical games and known primary recap availability render first; the full `/api/history/day` media/diagnostic payload hydrates asynchronously after the ribbon exists.
- **Today Key Info recovery:** returning to Today paints cached current Key Info immediately and then requests the forced editorial refresh, preventing a historical empty message from remaining visible during a slow refresh.
- **Cumulative v4.1.23 fixes retained:** selective startup relationship repair, longer bounded deploy health grace, Android Historical Database Audit scrolling, rolling schedule sync, interactive playlist ingestion, and canonical event/media playback remain intact.

## v4.1.24 — catalog-first runtime + interactive source management

- **Rolling schedule sync:** a new `sbb-history-schedule-sync` worker refreshes yesterday, today, and the next 14 days into `history_day` / `history_catalog_event`. A full horizon refresh runs at startup and periodically; a smaller rolling refresh runs every 10 minutes. Today/future events are cataloged immediately but remain ineligible for recap discovery until live/final state makes them eligible.
- **Manual schedule refresh:** Game Media Playlists now includes **SYNC SCHEDULE NOW**, which triggers the same canonical schedule ingestion without rebuilding the catalog.
- **Interactive Game Media Playlists:** operators can add, edit, enable/disable, remove, or crawl a YouTube playlist from the audit UI. Adding a playlist validates its ID/metadata, persists it in `operator-media-playlists.json`, and starts a background crawl.
- **Crawl first, associate second:** every playable item in an operator playlist is hydrated into normalized `SOURCE_MEDIA` as unassigned/orphaned media. Event Matcher v7 then attempts canonical GAME associations using team/date evidence. Ambiguous/non-game items remain orphaned rather than being forced onto an event.
- **Automatic recrawl:** enabled operator playlists can recrawl on a configurable interval (default 60 minutes). New videos are reused by identity, newly available schedule events can absorb prior orphans, and disabling/removing a playlist never deletes already-discovered media.
- **Playlist status:** custom rows report playlist items, hydrated assets, assigned assets, orphans, quarantines, last crawl, and last error. The worker console adds `[PLAYLIST CRAWLER]`.
- **Catalog-first day response:** `/api/history/day` now returns canonical `eventPlans` keyed by `LEAGUE:eventId`, including already-associated media, playable media, and primary playback selection.
- **Catalog-first ribbon/playback:** browsing a historical day no longer automatically launches a whole-date `/api/history/discover` job. The browser hydrates canonical event→media plans from SQLite first. `FIND RECAP` is reserved for a true catalog gap; an explicit click can still run exact-event discovery.
- **Today is catalog-first too:** today's persisted schedule/media can paint immediately from SQLite, then live score providers refresh authoritative score/status state in the background. This avoids waiting on providers before known media becomes clickable.
- **Single media relationship authority:** score cards prefer exact canonical event keys from the server instead of reconstructing associations client-side. Provider search, curated playlists, generic recovery, and rolling schedules all write to the catalog; the frontend reads that resolved catalog.
- **Version boundary:** Frontend/Backend v4.1.24; Discovery v15; Event Matcher v7; Rule Game Catch-up v10; Rule Collection Catch-up v8. No catalog rebuild and no automatic global replay.

# Sports Big Board v4.1.22

> v4.1.22 is the **Curated Playlist Recovery + Source Registry** release. It keeps the five-worker v4.1.21 recovery engine and Discovery v15, but adds operator-pinned NHL/MLS/MLB/NFL playlist inventories, reopens only the affected source ledgers, makes Operator Recovery collapsible, and adds a Game Media Playlists tab that exposes the active source strategy for every league.

## v4.1.22 — curated playlist recovery + source registry

- **NHL playlist-first recovery:** `2025-2026 NHL Full Game Highlights` (`PL1NbHSfosBuFyu867mbHHhB2G6fx7jtiH`) is now the primary NHL Extended/Purple historical lane. It uses playlistItems.list + videos.list, exact team/date association, and no YouTube Search. NHL.com recap/condensed pages remain secondary.
- **MLS pinned match-highlight playlists:** the operator-supplied 2026 primary/alternate and 2025 Match Highlights playlists are active Extended/Purple sources before the slower MLSsoccer.com fallback. Exact teams + date are still required.
- **MLB pinned season playlists:** 2026 and 2025 MLB Game Highlights playlists are now a fast GAME-coverage lane ahead of expensive generic web fallbacks. Green/Extended tier is derived from the actual video package.
- **NFL recap anchors expanded:** all supplied 2025 weekly/playoff recap playlists are pinned. NFL playlist Quick/Extended source versions advance to v2 so previously exhausted games can be reconsidered against the complete pinned inventory.
- **EPL 2025-26 source surfaced:** `PLXEMPXZ3PY1hMzinDc1TvSm8U2NUyz-0E` was already active; v4.1.22 exposes it in the new source registry alongside the existing Premier League and NBC playlist lanes.
- **Game Media Playlists tab:** Historical Database Audit now has a third tab listing Primary / Secondary / Fallback / Silver sources for MLB, NFL, NBA, NHL, EPL, and MLS, with direct links, season scope, objective, collector key, trust level, and notes.
- **Collapsible Operator Recovery:** the recovery panel is collapsed by default, remembers its state locally, and can be expanded only when cursor/source/database recovery is needed.
- **No search-list dependency for the new playlists:** all new playlist collectors use playlistItems.list + videos.list and share the existing bounded YouTube provider semaphore.
- **Version boundary:** Frontend/Backend v4.1.22; Discovery remains v15; Event Matcher remains v7; Rule Game Catch-up v10; Rule Collection Catch-up remains v8. No catalog rebuild.

# Sports Big Board v4.1.21

> v4.1.21 is the **Parallel Catalog Recovery + Operator Controls** release. It preserves Discovery v15, matcher v7, Rule Game Catch-up v9, Rule Collection Catch-up v8, and all proven NFL/MLS/EPL source adapters while increasing recovery throughput, starting NHL/general recovery concurrently, and making cursor/source/database-audit recovery an explicit operator workflow.

## v4.1.21 — parallel catalog recovery + operator controls

- **Five-worker Green pool:** SEARCH mode defaults to 5 workers. Workers 1–3 retain NFL/MLS/EPL first refusal, Worker 4 is a floating NHL-first worker, and Worker 5 is a floating general-coverage worker. Provider semaphores are unchanged.
- **No queue can hold the catalog hostage:** affinity is first refusal, not reservation. If a preferred league has remaining but no claimable work, that worker assists another claimable rule backlog, then NHL, then generic coverage. Floating capacity may work NHL and generic gaps while EPL replay is still active.
- **Coverage-opportunity scheduling:** generic floating work favors games with no verified media, then Blue-only gaps, recency, and high-value league deficits before optional Purple quality upgrades.
- **Operator Recovery Controls:** GAME MEDIA audit now exposes three intentionally separate operations: Restart Catch-up Cursor, Reopen Source Audit, and Restart Database Audit Cursor. Each operation has a dry-run preview and confirmation token; existing media is always preserved. Source reopen can be scoped by league/source/objective.
- **Restartable local database audit:** a read-only database-audit worker scans for no-verified-media events, stale discovery metadata, quarantined links, and catalog integrity issues. Its cursor/generation are persistent and can be restarted explicitly.
- **Every Goal identity audit:** one YouTube video identity remains one source asset. The console reports unique YouTube IDs, assets, collections, links, and duplicate identities. Rule Collection Catch-up stays at v8 so the previous Every Goal replay is not automatically repeated.
- **Clearer operator vocabulary:** the UI distinguishes Verified Catalog Coverage, Media Objectives, and Source Catch-up. `UNINDEXED` is displayed as **Index Pass Pending**, `SEARCHED_EMPTY` as **Source Exhausted Empty**, and rule `checked` is displayed as **source-complete**.
- **Catch-up position + utilization telemetry:** console reports upper/floor/oldest-attempted position by league, worker jobs/hour, busy %, provider-wait %, scheduler roles, DB-audit progress, and Silver identity health.
- **Preserved discovery behavior:** NFL playlist Extended, EPL NBC playlist matching (44/44 invariant), MLS Snapshot/Highlights, NHL official adapter, event matcher v7, source versions, and provider limits are unchanged. No catalog rebuild and no global catch-up reset.
- **Versions:** Frontend/Backend v4.1.21; Discovery v15; Rule Game Catch-up v9; Rule Collection Catch-up v8; EPL YouTube sources remain v6.

Verification covers worker-role scheduling, recovery preview/apply safety, source-ledger reopening without media deletion, database-audit restart state, Silver identity accounting, browser operator controls, plus the complete existing cloud/browser/catalog regression suite.

## v4.1.8 — official content-source adapters

Recent NFL discovery now starts with the league's own `https://www.nfl.com/videos/channel/game-highlights-vc` inventory and the two participating teams' NFL.com pages. The adapter accepts only canonical matchup-level pages whose URL/title prove both teams and a `team-vs-team-highlights` package. Individual plays, player `best plays`, Can't-Miss clips, interviews, press conferences, previews, and other one-off videos are deliberately rejected from the recap lane.

For each accepted NFL.com matchup page, the backend reads standards-based OpenGraph/JSON-LD video metadata. When NFL.com exposes a direct HTTPS MP4/HLS rendition, Sports Big Board range-probes it before marking it playable; otherwise the official NFL.com page is retained as an external fallback rather than falsely claiming in-app playback. Duration flows through the existing Gold/Green/Purple/Blue classifier, so the roughly five-minute official packages naturally become Green while longer packages can remain legitimate Purple Coverage Complete media.

The historical worker exposes this source as its own `nfl-game-highlights` primary lane **before** generic `official-native`, YouTube activity/feed, and public-web fallbacks. The adapter is intentionally recent-window scoped (default 21 days, configurable with `SBB_NFL_GAME_HIGHLIGHTS_RECENT_DAYS`) because NFL.com's channel/team pages are current-content surfaces; the one-time deep archive continues to use the existing historical source stack. The shared provider semaphore and short-lived page catalog prevent the three Green workers from re-fetching the same NFL.com inventory independently.

## v4.1.6 — coverage-complete statistics + semantic audit colors

The GAME MEDIA audit now reports **Coverage Complete** as a first-class statistic, both as a summary card and as an overall/per-league percentage line. Coverage Complete follows the v4.1.5 policy exactly: verified Gold, Green, or Purple (`extended`) counts as complete watchable coverage; Blue or None remains incomplete. Quick Recap coverage remains a separate Green-focused metric, so the audit can show both how often the preferred short recap exists and how often the database already satisfies the practical watchability goal.

The audit tables also use stable semantic badges to improve scanning. League pills are color-coded consistently across GAME MEDIA and SILVER ROUNDUPS (MLB blue, NFL red, NBA orange, NHL ice/cyan, EPL purple, MLS teal). Silver scope pills distinguish Daily from Weekly, and collection-kind pills distinguish Daily Recap, Weekly Recap, Top Plays, and generic Roundup. Text labels remain visible, so color is supplemental rather than the only identifier.

## v4.1.5 — strict Silver classifier + Purple coverage completeness

Silver promotion is fail-closed. A source asset becomes `DAY_LEAGUE` or `WEEK_LEAGUE` Silver only when its title proves league-wide roundup semantics **and** its publisher is a verified league source or trusted major broadcaster. Verified league YouTube channel IDs rank above broadcaster fallbacks. Team/club publishers, self-described “official” channels, player packages, single-game clips, interviews, features, historical lists, series packages, and season retrospectives remain in `SOURCE_MEDIA` but do not become Silver. `SEASON_LEAGUE` is retained as source taxonomy only and is excluded from the Silver Roundups surface.

Daily Silver identity is derived from the content period rather than the crawler encounter date. Explicit title dates win, including compact official formats such as `8/21`; publication chronology is the fallback. One daily asset therefore resolves to one canonical day instead of being smeared across overlapping backfill windows. Weekly identity is **league season + season week**, not calendar/ISO week: `The TOP Plays of Week 24 | 2025-26 NBA Season` becomes `WEEK_LEAGUE:NBA:2025-26:W24:TOP_PLAYS`, while `Every Touchdown from Week 18 | 2025 NFL Season` becomes `WEEK_LEAGUE:NFL:2025:W18:WEEKLY_RECAP`. Player-specific `Week N` videos are not weekly Silver.

On the first v4.1.5 startup, `collection_association_repair_version=5` rebuilds **only Silver collection relationships** from the preserved source-media reservoir. Old duplicated/day-smeared links and old calendar-week keys are discarded, high-confidence assets are re-promoted under the strict classifier, and rejected items remain available in `SOURCE_MEDIA`. Event associations, Discovery v15 progress, verification/runtime history, the Aug. 1, 2025 historical-seed state, and the discovery-attempt ledger are untouched.

Game coverage completeness is also independent from editorial quality. A verified **Gold, Green, or Purple/extended** game package counts as `COVERAGE_COMPLETE`; **Blue or None** remains a coverage gap. Purple still remains eligible for an optional Green/Gold quality upgrade, and the Green-gap worker selection/propagation rules are unchanged. This lets sports such as soccer correctly count a legitimate 10–15 minute official Purple package as a complete watchable game record without pretending it is the preferred final tier.

The Silver audit/export exposes source authority, canonical resolved period, season ID/week, and classifier evidence so official-vs-broadcast fallback and repaired collection identity can be audited directly.

## v4.1.2 — fixed historical seed floor

v4.1.2 changes chronological history ingestion from a rolling day-count job into a one-time seed. The date-backfill worker seeds every calendar date from yesterday back through **August 1, 2025, inclusive**. The floor can be overridden with `SBB_HISTORY_BACKFILL_FLOOR_DATE`, but the production default is intentionally fixed at `2025-08-01`.

Seed completion is based on persisted score/media inventory, not on eventually reaching Gold/Green quality for every game. The three Green-gap workers remain responsible for quality improvement of already-seeded events. Once every date in the seed range has score/media inventory, the backend persists `historical_seed_complete=1`, records the exact floor and completion time, and the chronological worker transitions to `complete:historical-seed`. It stays alive only for health/heartbeat reporting and never walks earlier than the seed floor or restarts the seed after a reboot. If the configured floor is intentionally changed later, the completion marker no longer matches and the seed worker resumes only for the newly requested range.

## v4.0.1 reindex scheduling correction

v4.1.8 fixes the post-reconstruction state boundary exposed by the first production v4 catalog. Catalog import/rebuild bookkeeping is no longer recorded as a provider discovery attempt. Rebuilt events begin with `last_discovery_at = 0` and `next_retry_at = 0`, stale discovery generations bypass cooldown immediately, and the server performs a narrow idempotent startup repair for v4.0.0 rows marked `PENDING_CURRENT_DISCOVERY`. Current-generation attempts still obey the normal recent/archive cooldowns. No database rebuild is required for the v4.0.0 → v4.1.8 update.

The operator queue also drops the ambiguous legacy `noMedia`/`no_media` aliases. `UNINDEXED` remains distinct from `SEARCHED EMPTY`, while the combined diagnostic is exposed explicitly as `unindexedOrEmpty`.

## v4 normalized historical media catalog baseline

v4 is a schema-generation change from v3, not an in-place patch to the old catalog. The historical database is rebuilt around independent source-media, event-association, and collection-association truths so a discovery bug cannot make a league/day harvest authoritative for every game on that date.

### Normalized catalog

- `history_source_media` stores each discovered media asset once using a provider-stable identity. It owns provider metadata, canonical URL, title, duration, publish/discovery timestamps, scope/intent classification, classifier confidence/reason/version, validation, and runtime health.
- `history_catalog_event` stores canonical sporting events under `LEAGUE:EventID`; date is metadata rather than identity. It owns current discovery state/retry scheduling and captures a durable `final_at` timestamp when the provider supplies one.
- `history_event_media` is the only way GAME media can affect an event. Every link stores association state, confidence, method, evidence, and matcher version. Unproven relationships fail closed and enter the review queue.
- `history_collection` + `history_collection_media` own **Silver** daily/weekly recap collections independently from game quality. Collection links also preserve classification confidence/evidence.
- `history_media_segment` is available for optional future chapter/timestamp slices without making segmentation a prerequisite for roundups.
- `history_media_verification` and `history_discovery_attempt` are append-only operational ledgers for playback/embed truth, queries, provider lanes, result counts, accepted counts, before/after tier, quota cost, and failures.
- `history_assignment_review` retains quarantined and unassigned media instead of deleting uncertain assets. Future classifier/matcher versions can reconsider those rows without re-spending discovery quota.

### Scope, intent, and Silver

Media scope is independent from game quality. `GAME`, `DAY_LEAGUE`, `WEEK_LEAGUE`, `PLAYER`, `SEASON_LEAGUE`, and `OTHER` are classified before association. Gold/Green/Purple/Blue are valid only for `GAME`. Daily/nightly league recaps and Top Plays become Silver collection media and can never satisfy an individual game's tier.

The Silver Roundup card is the first ribbon item when roundup media exists. Daily Recap outranks Top Plays; entering a day/league may begin with Silver in normal playback modes. SEARCH PRIORITY still suppresses all playback.

### v3 → v4 reconstruction

v4 never converts the old relationship tables destructively at server startup. `tools/ensure_history_v4.py` performs an **offline reconstruction**:

1. detect the catalog generation without modifying the database;
2. make an immutable pre-v4 SQLite backup;
3. create a second v4 database beside production;
4. preserve score/event skeletons and source/runtime evidence;
5. strip legacy event stamps from generic harvested media;
6. reclassify scope/intent under the v4 classifier;
7. re-prove every GAME association from authoritative provider identity or exact matchup evidence;
8. move daily/weekly content into Silver collections;
9. quarantine ambiguous/unproven media instead of deleting it;
10. reset stale v3 discovery bookkeeping while retaining the already discovered source reservoir;
11. run reconciliation/integrity checks; and
12. atomically install the rebuilt catalog only when the audit passes.

Cloud deployment stops the backend before reconstruction. If the new v4 release later fails health checks, deployment restores **both** the previous application release and the pre-v4 database backup. Android/Termux and Windows launchers run the same preflight before starting the server.

`HISTORY_DISCOVERY_VERSION = 14` starts fresh discovery bookkeeping on top of the reconstructed source catalog. Existing candidates are validated before new search, queue identity is `LEAGUE:EventID`, repeated no-improvement attempts back off, and YouTube Search quota is partitioned among recent games, true-empty rescue, Blue upgrades, and archive rescue.

The historical console uses explicit states: **UNINDEXED**, **SEARCHED EMPTY**, **COVERAGE COMPLETE**, **UPGRADE PENDING**, **QUALITY COMPLETE**, **PROVIDER DEGRADED**, and **CANDIDATE ONLY**. Unindexed migration work is no longer mislabeled as “no media.”

## v3.0.9 Search / Mix / Playback resource control + recent-game guard

v3.0.9 added a persistent three-way resource mode directly to **Settings → Historical Database → Live Search Console**:

- **SEARCH PRIORITY** dedicates the cloud server to historical discovery. Browser playback, direct-media proxying, native prewarming and score-card video launches are suspended until the mode changes.
- **MIX** is the normal behavior: historical workers run continuously but yield briefly to active playback and foreground discovery.
- **PLAYBACK PRIORITY** pauses the Green-gap and date-backfill search workers, and rejects explicit historical discovery requests, while known scores/Game Centers/catalog media remain available for playback.

The selected mode is stored on the persistent cloud data disk, so page refreshes and application deployments do not silently reset it. The Search Console and copyable diagnostics include the active mode and whether playback/search is suspended.

v3.0.9 also added a **recent-slate safeguard**. The Green-gap queue gives completed games from the newest three calendar days with no verified recap a cursory pass before spending long stretches deep in the archive. After that safeguard, the normal Blue-only → no-media → Purple-only archive priority continues. The console reports `recent gaps` and `recent no-media` separately so current coverage cannot be hidden by a large December backlog.

Those resource controls, worker heartbeat/watchdog, copy issues/full console controls, version mismatch protection, and recent-slate scheduling remain intact in v4.1.8. Historical discovery advances to `HISTORY_DISCOVERY_VERSION = 14` for the scope/association migration described above.

## Cloud Stage 1

The production path remains the GitHub Pages frontend backed by the always-on Google Compute Engine server and persistent historical SQLite catalog. The cloud backend owns score/media discovery, Game Center hydration, runtime playback truth, and the one-time historical seed through August 1, 2025. Local Termux/Windows mode remains supported for development and fallback.

### Normal release workflow

After the one-time `cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh` setup, a release is just a push to `main`: upload the complete unzipped repository contents at the GitHub repository root. The GitHub Action verifies the build, deploys the Compute Engine backend with automatic rollback/health checking, then publishes the matching GitHub Pages frontend. No Cloud Shell command is required for normal releases.

## v3.0.1 historical playback foundation

v3.0.1 established the server-owned historical event/media catalog used by v4.1.8:

`selected date → canonical score events → event catalog → validated media assets → playback plan → PlaybackController → runtime feedback`

v4 replaces the old event-centric media table with `history_source_media` plus evidence-bearing `history_event_media` and `history_collection_media` relationships. Runtime playback success/failure survives browser reloads, score-ribbon hydration uses the same normalized event associations as playback, and historical Game Center remains independent of media selection.

### Historical discovery lanes

1. Official/native event media such as ESPN event packages and MLB official media.
2. Official YouTube channel activity indexing with exact-ID validation.
3. One shared official-channel `search.list` rescue per league/date during foreground historical browsing.
4. Public YouTube/search-engine discovery as candidate metadata only until positively validated.
5. League/team-specific free lanes where available, including the NFL feed.

The chronological date-backfill worker intentionally does not spend the scarce YouTube `search.list` bucket. In v4.1.8, a bounded three-worker Green-gap pool runs in SEARCH mode (one worker in BALANCED). Every worker must atomically lease a canonical Event ID before discovery, while provider-specific semaphores and same-day single-flight locks prevent concurrency from multiplying API pressure. YouTube Search remains globally serialized and quota-brokered.

## v2.7.0 provider-independent media + Game Center architecture

This release turns the NFL reliability work into a general cross-sport architecture rather than another league-specific patch.

- Adds an **Event Media Manifest** for each canonical game. The score ribbon, recap alternatives and runtime player now read the same media truth.
- Adds a provider-independent **EventMediaResolver**. The application asks for `QUICK`, `EXTENDED`, `COMMENTARY` or `MOMENTS`; ESPN, official league/team sources, Highlightly, YouTube and MLB Stats compete behind that contract.
- Adds sport-aware recap policies. NFL Quick targets about **2.5–5 minutes**, keeps ~1 minute as a fallback, and keeps ~15 minute packages as optional Extended media. Other sports have their own duration policy without changing PlaybackController.
- Separates **media discovery**, **runtime asset health**, **provider health**, and **transport**. One failed YouTube embed no longer means the game has no highlights, and a provider outage does not erase already discovered assets.
- Replaces the MLB-specific native-player concept with generic **DIRECT_VIDEO** transport. All allow-listed direct sources can use the same localhost range proxy, 16 MB startup cache and prioritized prewarming.
- Records direct-video buffering per asset and lowers repeatedly stalling assets in future resolver decisions.
- Removes generic browser fallbacks that silently treated missing competition identity as MLB.
- Makes Game Center player-stat team ownership/category explicit and enables the shared ESPN Game Center adapter for **NBA and NHL** in addition to NFL/EPL/MLS, while MLB retains its richer official Stats API adapter.
- Keeps the persistent **NOW WATCHING** ribbon focus and all existing mobile/desktop sticky-player behavior.

## v2.7.0 selected-game focus + honest NFL external playback

This release fixes the two issues exposed by v2.6.4.8 testing: the selected score card was not visibly highlighted, and official NFL packages discovered from the league channel could still be routed into the embedded player when YouTube API validation was unavailable.

- **NOW WATCHING is intentionally obvious.** The currently selected/playing game gets a bright cyan 3 px focus frame, stronger inset/background treatment, and a dedicated **NOW WATCHING** pill in place of the day label. A malformed escaped-newline CSS append in v2.6.4.8 prevented the intended focus styles from parsing at all; that is removed.
- **The ribbon follows the broadcast once, then respects the viewer.** Changing to a different game recenters on that game's actual calendar date and scrolls its card into view. After that, manual historical browsing stays independent and does not snap back until playback actually changes games.
- **Official NFL feed discovery is separated from embed permission.** A keyless NFL Atom-feed result proves that the official extended highlights exist, but it no longer claims the item is playable inside Sports Big Board. Only a positive YouTube `videos.list` validation promotes that item into the embedded-player pool.
- **YouTube 429/cooldown is no longer treated as permission to guess.** When embed validation cannot run because YouTube is rate-limited, the official NFL package stays **external-only** instead of entering PlaybackController and producing an avoidable 101/150 error.
- **External official highlights remain visible.** If the only known package is external-only, the card keeps its purple extended-highlight rail and uses an **↗** action. Clicking it opens the exact official YouTube package. If a playable ESPN/team/broadcast fallback exists, that source remains the in-app click target while the purple rail still advertises the extended package.
- **Runtime embed failures become external truth.** If a source passes metadata validation but the browser later receives an owner-policy embed failure, that asset is removed from the in-app playable pool but preserved as an external official link.
- **External fallback no longer shows a contradictory loading spinner.** Once the player has switched to an external-only state, late player callbacks cannot re-show `Loading video…`.

## v2.6.4.4 schedule + playback reliability deep dive

This release addresses the root architecture behind the fragile non-MLB score feeds rather than adding another league-specific patch.

- **ESPN is now the first schedule authority for NFL/NBA/NHL.** Highlightly is a fallback/enrichment/media provider, so its latency, quota or empty match response cannot hide a league day.
- **NFL preseason has redundant schedule views.** The server unions viewer-day date windows, exact neighboring UTC dates, CDN state, the season-type board, and preseason Weeks 1–5. Every candidate is finally filtered back to the viewer's local Today/Yesterday date.
- **EPL/MLS get redundant soccer schedule views.** League-specific day windows, an exact-date transport, a season-wide league board, CDN, and a guarded `soccer/all` rescue path are unioned before local-day filtering.
- **The ESPN envelope parser now collects every event list.** The prior first-list behavior could make `soccer/all` find another competition first, filter it out, and incorrectly report no EPL game even when a later event list contained the fixture.
- **Known non-empty days persist locally.** A short current-day cache and longer historical cache prevent a temporary provider/network blank from erasing games already discovered.
- **The old two-face Today/Yesterday toggle has been superseded in v3.0.9 by explicit calendar-day navigation.** The underlying viewer-day date authority and ESPN fallback behavior remain in place.
- **Playback waits longer for the exact YouTube player and retries the exact media once** before falling back to a user tap. This preserves the single PlaybackController ownership model while making normal iframe/network startup hiccups less visible.
- **Friendly loading states.** Game Center now says **Loading Game Center…** with a spinner. Video startup/buffering shows **Loading video…** or **Buffering video…** with the same lightweight animation instead of developer-oriented status text.

Sports Big Board is a local, personalized sports television system: live scores and game state feed a direct-tune ribbon, official highlights and recaps feed the player, Game Center adds the live/final statistical context, and Around the League provides unattended programming.

v4.1.8 builds on the stabilized score inventory and Game Center work by adding arbitrary historical date context without coupling ribbon browsing to playback.

## Launch experience

A fresh page load now opens on a full-screen **Sports Big Board** splash instead of immediately starting the channel. Scores, news and media discovery may warm in the background, but active playback is launch-gated until the viewer presses **START SPORTS BIG BOARD**. The pre-launch page stays clean. After Play is pressed, the current program is selected into Game Center and the local resolver runs several short follow-up passes while score inventory finishes warming, so the first game's statistics populate automatically instead of requiring a second score-card click.

## Legacy Today / Yesterday score authority

NFL, NBA and NHL score inventory retains its ESPN fallback whenever Highlightly is empty. In v4.1.8 the league filter no longer changes the date automatically: the viewer-selected calendar date remains authoritative. ESPN historical lookups keep trying alternate transports when a non-empty endpoint response contains only the wrong calendar day, preventing a weekly/current board from masking the requested date.

## NFL recap discovery

NFL recap discovery now accounts for the way the official NFL channel actually titles preseason packages. Official uploads may use a title such as `Team A vs. Team B | 2026 Preseason Week 2` without the words `game highlights` in the title itself, and those packages frequently run longer than eight minutes. Sports Big Board now searches that title pattern directly, accepts trusted NFL packages up to 25 minutes, and classifies longer packages through the existing extended-recap tier. ESPN video discovery is also independent of the YouTube Data API path, so a missing or rate-limited YouTube search key no longer prevents the ESPN fallback from running.

## Game Center layout

Game Center and Up Next share the same embedded information surface rather than floating over the broadcast.

- Portrait/mobile: below the video.
- Mobile landscape: below the video. Side mode is intentionally disabled on coarse-pointer/mobile devices.
- Desktop/wide PC: Game Center is the permanent right-hand column while the video keeps a complete 16:9 picture in the left column. The divider and inset surface make it read as one workspace instead of an overlay.

Selecting a score still tunes the game's media through PlaybackController and independently updates `SelectedEvent`. Game Center subscribes to `SelectedEvent`; it never manipulates playback.

## Keep Video Visible

Settings includes **Keep Video Visible**.

When ON, scrolling into Game Center keeps the player near the top of the page and smoothly reduces its size as more statistics take over the screen. As the video shrinks, a compact Now Playing + previous/play-next strip grows in directly beneath it, so the title and playback controls stay attached to the smaller player instead of disappearing or popping back into their full-size layout. Game Center remains mathematically attached below that compact player workspace throughout the transition.

At minimum size, the layout switches to a bounded workspace: the minimum-size video and compact controls stay pinned and the active Game Center pane becomes the only scroll surface below them. The root is not put into `overflow:hidden`; instead its exact handoff coordinate is held while the Game Center is active. A swipe/wheel upward that begins in the upper-page real estate releases that handoff and drives the same shrink runway in reverse, expanding the player smoothly back toward its original size. This prevents the score ribbon from scrolling behind a still-minimized video. The actual video element stays in the same DOM node, keeps its aspect ratio and never reloads.

When OFF, the page scrolls normally and the video can move completely off screen.

The preference is stored in browser local storage and survives reloads.

## Game Center data

The normalized Game Center contract remains:

`GET /api/events/{competition}/{eventId}/game-center`

Detailed adapters in v3.0.9:

- **MLB** — score/status, inning linescore, R/H/E, team stats, batting, pitching, scoring plays and full play-by-play.
- **NFL** — score/quarter/clock, team stats, player stat sections, scoring plays and play-by-play/drives when ESPN provides them.
- **MLS** — score/match state, team statistics, player sections when available, goals/key events and timeline/commentary when provided.
- **EPL** — same normalized soccer contract as MLS using the EPL ESPN adapter.

NBA and NHL now use the same normalized ESPN summary adapter as the other non-MLB detailed sports. Their data richness depends on what ESPN exposes for a given game, but no Game Center UI or PlaybackController branch is league-specific.

## Persistent GameCenterRepository

Game Center is now a server-prepared data plane backed by SQLite:

`~/.sports-big-board/cache/game-centers.sqlite3`

Sports Big Board continuously inventories today's and yesterday's relevant MLB/NFL/NBA/NHL/MLS/EPL events and prepares their Game Centers in the background. For events sourced from Highlightly, the same score-provider match id is now the preferred detailed-stat identity instead of translating through MLB Stats/ESPN first.

- Browser resident Game Center = HOT.
- SQLite Game Center = WARM.
- Provider fetch = COLD fallback.
- Completed games are retained as long-lived final snapshots.
- Live games are centrally refreshed by the server.
- Stale data can be returned immediately while a refresh occurs in the background.
- Provider indexes are isolated by source, so Highlightly inventory can no longer replace the MLB Stats/ESPN event index for the same day.
- A teams/score-only shell is explicitly **PARTIAL**, not a completed cache hit. Partial finals get a short server TTL, a short browser HOT TTL, and continue background enrichment.
- Normalized snapshots from multiple providers are merged section-by-section; richer linescore, team stats, player sections and play-by-play can fill gaps without discarding already-correct event identity.

The browser uses request generations and AbortController so obsolete selections cannot update the current panel. v3.0.9 also made repository misses asynchronous: localhost returns PREPARING immediately, promotes the selected game to touch-intent priority on a dedicated Game Center worker pool, and the browser polls localhost until the prepared snapshot is available. A slow MLB/ESPN socket therefore no longer blocks the browser request.

Provider identity is verified against the sporting event (competition + date + away/home teams + optional start/game number). If the score came from Highlightly, Sports Big Board first asks Highlightly for detailed match data using that exact score match id. For MLB it also requests Highlightly match statistics and player box scores where available. MLB Stats and ESPN remain official-provider fallbacks when the score provider does not expose enough detail. Any returned identity is still rejected if the teams do not match the selected score card. Legacy `Unknown` rows and mismatched aliases are invalidated automatically on read.

## Game Center / Up Next / Settings

The information surface has three tabs. Its background now uses the same dark page surface as the player area, with inset section wells and no floating glass/shadow treatment, so Game Center reads as a continuation of Sports Big Board:

- **GAME CENTER** — scoreboard, stats, players and plays for `SelectedEvent`.
- **UP NEXT** — the existing queue, watched state, shuffle and programming visibility.
- **SETTINGS** — player-layout preferences and API connection status.

The queue is intentionally secondary; it no longer needs permanent screen space.

## API credentials: configure once per machine

Sports Big Board no longer relies on release-local environment variables for normal setup. Credentials live outside extracted version folders in:

`~/.sports-big-board/secrets.env`

The same location is used by Python on Android/Termux and Windows (`%USERPROFILE%\.sports-big-board\secrets.env`).

Supported keys:

- Highlightly API key
- YouTube Data API key
- OpenAI API key

`setup_credentials.py` automatically migrates recognized legacy Sports Big Board key files when possible. It then asks only for keys that are still missing. If a key is intentionally skipped, startup does not nag for it on every launch; it can be added later from **Settings**.

API status shown in the browser exposes only `CONFIGURED / NOT SET`. Secret values are never sent back to JavaScript.

A key entered on Android is not automatically copied to a different PC. Enter or securely copy it once on that PC; every future Sports Big Board version on that machine will then reuse it automatically.

## Android

```bash
cd ~/storage/downloads/sports-big-board-v4.1.21/sports-big-board-v4.1.21
bash VERIFY.sh
bash START-ANDROID.sh
```

Open `http://localhost:8080` and keep Termux running.

## Windows / PC

Double-click:

`START SPORTS BIG BOARD.bat`

On first use it runs the one-time credential setup and asks for any missing Highlightly, YouTube and OpenAI keys. Later releases reuse the same machine-level file automatically.

You can also run:

```text
python setup_credentials.py --status
python server.py
```

See `WINDOWS SETUP.md` for details.

## Verification

From Android shared storage:

```bash
bash VERIFY.sh
```

Node is optional. When Node is unavailable, the permanent Python suite still verifies the browser architecture/UI boundaries and all server contracts.

The v4.1.8 regression suite covers, among other things:

- authoritative score-card playback and epoch ownership
- HOT/WARM media prewarming separation
- live-day/timezone and ESPN live-state authority
- soccer date bucketing
- centralized Gold/Green/Purple/Blue media classification
- below-video mobile Game Center layout
- optional PC-only side mode
- Android-safe bounded sticky workspace with no root-overflow scroll lock
- compact sticky title/playback strip attached to the shrinking video
- reverse-scroll expansion from upper-page real estate with outer-scroll drift protection
- launch-screen playback gate plus post-launch current-game Game Center synchronization
- NFL/NBA/NHL off-day ESPN score fallback plus yesterday-first league filtering
- ESPN historical transport retry when the first envelope is for the wrong viewer day
- inset non-glass Game Center presentation
- score-selected event ownership (sparse playback media cannot overwrite it)
- asynchronous Game Center PREPARING/poll/retry behavior
- dedicated Game Center worker pool independent of media prewarm
- SQLite Game Center persistence plus continuous today/yesterday coverage
- Highlightly score-id → direct Game Center detail fast path with MLB Stats/ESPN fallback
- MLB/NFL/MLS/EPL Game Center normalization
- machine-local API secrets and Windows/Android one-time setup

## Silver roundup collections

League/day/week programming is deliberately separate from individual games. The canonical examples are:

- NBA/NHL/MLB/soccer — nightly or daily recap plus daily Top Plays (`DAY_LEAGUE`)
- NFL and other week-oriented competitions — weekly recap / Top Plays (`WEEK_LEAGUE`)

These assets are presented as **Silver**. They may lead the score ribbon and date program, but they never mutate `SelectedEvent` and never contribute Gold/Green/Purple/Blue availability to a game. A future trusted chapter/timestamp segment may point from a Silver parent video to one game without changing the parent video's collection scope.

## v3.0.9 historical playback reconciliation

v3.0.9 fixed the first integration issues revealed by the canonical v2.9 history catalog:

- Browser JSON requests now preserve HTTP method/body, so exact-event historical discovery reaches the POST endpoint instead of falling through to a GET 404.
- Normalized `history_source_media` + assigned `history_event_media` rows hydrate the score-date store even when the legacy league-day `media_saved_at` field is empty. Server `playable` counts and score-card rails therefore derive from the same relationship truth.
- A historical game click checks the existing event playback plan before launching discovery, making revisited dates instant when verified assets already exist.
- Historical diagnostics separately expose verified catalog assets and ribbon-ready games.
- Current-day YouTube search work yields while a historical date is foregrounded, and exhausted `search.list` cooldowns no longer produce one error per game.
- ESPN/network postgame analysis and press-room coverage classify as Gold commentary instead of Blue highlight reels when appropriate.

## v3.0.9 audit-status reconciliation

The Historical Database Audit now separates the raw persisted discovery state from the user-facing **effective audit status**. Legacy or not-yet-reindexed `UNKNOWN` event rows no longer imply that Sports Big Board has no information. The audit projects current catalog truth into actionable states:

- **UNINDEXED** — the event exists but has not completed the current discovery-version pass. Existing assigned GAME media remains visible while current-version discovery is pending.
- **UPGRADE PENDING** — current-version discovery is catalog-complete but the best verified tier remains below Gold.
- **PARTIAL** — verified media exists but applicable provider lanes are not yet exhausted.
- **QUALITY COMPLETE** — Gold exists or the current-version quality target is explicitly complete.
- **NO MEDIA FOUND / PROVIDER DEGRADED / CANDIDATE ONLY** — current-version search outcomes with no verified playable asset.

CSV/XLSX exports now include both **Audit Status** and the raw **Discovery State**, plus discovery version, current discovery version, discovery-pending, catalog-complete, quality-complete, and inferred upgrade-pending columns. This keeps operational debugging available without presenting stale bookkeeping as catalog truth.

## v3.0.9 Historical Database Audit

Open **Settings → Historical Database → Open Database Audit** to inspect the persistent cloud catalog in a spreadsheet-like game view. Each game has separate **Gold / Green / Purple / Blue** columns with the stored source links, duration, provider and validation/runtime state. Filters cover date range, league, best available tier, upgrade status and free-text matchup/title search. The same filtered data can be exported as CSV or XLSX.

v3.0.9 also added a persistent official YouTube **uploads-playlist index** for NFL, NBA, NHL, EPL and MLS. This is separate from the limited `search.list` bucket and is specifically intended to improve historical full-recap discovery. The server incrementally walks each official channel backward and reuses that index across every game/date, while Blue-only games are prioritized for quality upgrades. Discovery version 9 automatically reconsiders the existing catalog without deleting scores or previously found media.

### v3.0.9 diagnostic-copy update

The Historical Database Audit live search console now provides **COPY ISSUES**, **COPY FULL CONSOLE**, and **SAVE TXT** controls. The full report includes worker heartbeats, Green-gap queue counts, background scheduler state, YouTube gateway cooldown/quota details, the historical search budget, Highlightly status, active discovery jobs, and the full in-memory terminal buffer. Normal short scheduler yields for media playback are shown as **YIELDING** instead of being mislabeled as worker errors.


## Sports Big Board v4.1.1

v4.1.1 keeps the v4.1 bounded worker pool but makes discovery **tier-aware and stage-aware**. Green-gap and one-game chronological backfill passes target Green: existing candidates are validated first, then authoritative/native providers run in stages and the event tier is recalculated after every major lane. As soon as Green (or better) is proven, the pass stops and skips the remaining primary lanes plus public-page, public-index, and YouTube Search rescue. Full foreground discovery can still target Gold, so short-circuiting improves historical throughput without removing the long-term editorial quality path.

Public-page, public-index, and `search.list` are now true fallbacks. The free public lanes are only entered when authoritative sources remain below the pass target, and `search.list` is last; a public fallback hit is re-evaluated before the next fallback so it can avoid spending quota. The live audit exposes primary passes, primary-target hits, short-circuits, fallback attempts/hits, average fallback time, estimated time saved, and current quarantine-reason counts. Backfill logging also distinguishes known games from newly inserted games.


## v4.1.0 Concurrent historical discovery

- SEARCH: 3 Green-gap workers plus the chronological date-backfill worker.
- BALANCED: 1 Green-gap worker plus date-backfill, with normal playback yielding.
- PLAYBACK: historical workers pause.
- SQLite event leases prevent duplicate processing and expire after crashes/restarts.
- Provider limits are centralized: native/ESPN 3, MLB official 2, YouTube metadata 2, YouTube Search 1, NFL feeds 2, Highlightly 1.
- Official same-day MLB/YouTube catalogs single-flight so concurrent workers reuse the first fetch/cache fill.
- The Historical Database Audit displays each worker, active lease, provider wait, pool throughput, provider concurrency, and Silver daily/weekly collection totals.
- Silver collection detail is available through the dedicated **Silver Roundups** tab, backed by the normalized collection audit API, with daily/weekly filters, integrity flags, pagination, and CSV/XLSX export.

## v4.1.8 official content sources

Sports Big Board now treats structured league-owned recap libraries as primary discovery sources instead of forcing generic web search to rediscover known programming patterns:

- **NFL:** NFL.com Game Highlights matchup packages (from v4.1.7) remain the first-class NFL recap lane.
- **NHL:** NHL.com **5-Minute Recaps** are the preferred concise game recap source; NHL.com **Condensed Games** provide a Purple coverage-complete fallback. NHL.com weekly Top Goals / Top Saves / Top Plays can populate Silver.
- **Premier League:** PremierLeague.com official match highlights are primary. **NBC Sports Premier League Extended Highlights** are a trusted-broadcaster Purple fallback when official concise media is unavailable.
- **MLS:** MLSsoccer.com Match Highlights are a first-class official GAME source.

The source order remains **league official → trusted broadcaster → existing native/official-channel inventory → generic public fallback**. New direct media still has to pass the normal native playback probe and Event Matcher v5; source discovery never bypasses association or tier truth.

Soccer collection programming now has a first-class `ROUND_LEAGUE` scope instead of being forced into calendar weeks. EPL Matchweek and MLS Matchday identities are season-relative (`2025-26:MW38`, `2026:MD21`). Silver also supports `SCORING_ROUNDUP` for complete scoring packages such as **Every Goal from Matchday N**. These remain separate from individual GAME media and never affect Gold/Green/Purple/Blue game tiers.


2025-26 EPL historical backfill additionally pins NBC playlist `PLXEMPXZ3PY1hMzinDc1TvSm8U2NUyz-0E` and applies the same `PREMIER LEAGUE HIGHLIGHTS` event matcher.
