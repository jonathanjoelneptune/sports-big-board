# Sports Big Board v3.1.0 Architecture

## Product model

Sports Big Board is a local sports television system:

`providers → canonical Event → MediaManifest → EventMediaResolver(package request) → MediaAsset → transport adapter → PlaybackController → viewer`

The score ribbon is the direct-tune/channel guide. PlaybackController owns media activation. `SelectedEvent` owns the sporting-event context. Game Center consumes that context. Around the League is the unattended scheduler.

## Non-negotiable ownership rules

1. **PlaybackController alone activates media.**
2. Browser HOT and server WARM systems prepare resources only.
3. Prepared-player promotion requires exact media identity plus a current assignment epoch. A YouTube `onReady` callback must preserve an existing controller-owned pending claim rather than creating a competing epoch.
4. `SelectedEvent` is independent of the active A/B video slot.
5. Game Center subscribes to `SelectedEvent`; it never calls PlaybackController.
6. Sticky/shrinking player behavior changes presentation only and never reloads/reassigns media.
7. Game Center caching/refreshing cannot change playback or `SelectedEvent`.
8. Silver roundup collections are programming objects, not games, and never mutate `SelectedEvent`.
9. Collection media cannot enter a game MediaManifest or satisfy a Gold/Green/Purple/Blue tier.
10. Provider-specific response shapes terminate at adapters/contracts.
11. Browser code never receives stored API secret values.

## Browser boundaries

- `core-model.js` — Sport / Competition / Event / MediaPackage / MediaAsset / Moment / GameCenter / EditorialPackage shapes
- `architecture/score-date-store.js` — independent browse/playback dates plus session-resident per-date score/media snapshots
- `architecture/event-identity.js` — canonical event identity; missing competition identity is never silently coerced to MLB
- `architecture/media-scope.js` — GAME vs day/week/player/season/other scope classification and Silver collection semantics
- `architecture/media-classifier.js` — Gold / Green / Purple / Blue taxonomy for GAME media only
- `architecture/playback-transports.js` — `DIRECT_VIDEO`, `YOUTUBE_EMBED`, `EXTERNAL`, and `CONTEXT`; transport is independent of league/provider
- `architecture/provider-health.js` — adaptive provider health/cooldown, independent of whether an individual asset exists
- `architecture/sport-media-policy.js` — QUICK / EXTENDED / COMMENTARY / MOMENTS duration policy by sport
- `architecture/media-manifest.js` — persistent per-event discovered/runtime media truth used by the ribbon and player
- `architecture/media-resolver.js` — provider-independent ranking/failover for a requested package
- `architecture/game-center-policy.js` — explicit team ownership and stat-category normalization
- `architecture/selected-event-store.js` — selected-event pub/sub
- `architecture/game-center-contract.js` — HOT browser Game Center cache, cancellation, timeout and localhost contract
- `architecture/media-work-priorities.js` — semantic prewarm priorities
- `architecture/editorial-packages.js` — league-level Top Plays registry/identity
- `ui/game-center-view.js` — normalized Game Center rendering and current-request ownership
- `ui/info-drawer.js` — Game Center / Up Next / Settings information surface
- `ui/player-visibility.js` — below/side preference and Keep Video Visible presentation controller
- `ui/settings-view.js` — safe API status/replacement UI
- `app.js` — programming plus the proven PlaybackController implementation

The Game Center/settings/player-visibility modules have no dependency on PlaybackController or `SBB_PLAYBACK_CONTROLLER`.

## v2.8 date-context ownership

Date navigation is deliberately split from media ownership:

`ScoreDateStore.browseDate → score ribbon + Key Info date context`

`ScoreDateStore.playbackDate → date-locked program queue`

`SelectedEvent → Game Center`

`PlaybackController → active media only`

Changing `browseDate` can fetch and render another day's slate but cannot call PlaybackController. Starting media from a score card establishes `playbackDate`, builds a program from that date's eligible MediaManifests and keeps autoplay on that date after the selected game's package finishes. Game Center continues to resolve from the selected/playing canonical event, including its date/team/provider fingerprint.

`returnToToday()` is the intentional synchronization point. It sets both date contexts to the viewer's local Today, replaces the historical program with a Today-only program, updates selection/Game Center, and tunes playback through PlaybackController. No other date-navigation action performs that full reset.

Past-day score and media snapshots remain resident in the browser session. Final historical Game Centers may remain HOT for 24 hours in browser memory while partial shells retain the short retry TTL; the server's persistent repository remains the WARM authority.

### v3.1.0 media scope, Silver collections, and historical discovery

v3.1.0 inserts a scope boundary before event association:

`discovered media → MediaScopeClassifier → GAME association OR Silver collection → validation → playback truth`

Gold/Green/Purple/Blue are valid only for `GAME` media. `DAY_LEAGUE` and `WEEK_LEAGUE` assets are persisted as Silver collections. `PLAYER`, `SEASON_LEAGUE`, and `OTHER` remain outside an individual game's tier calculation unless a future explicit product surface consumes them. Generic channel metadata cannot become event authority merely because it was discovered while searching that event.

The canonical queue identity is `LEAGUE:EventID`; date is event metadata rather than identity. This prevents local/UTC date aliases from creating duplicate gap work. Existing candidate media is validated before any new rescue search, and per-event cooldown/backoff suppresses repeated no-improvement attempts. YouTube Search quota is partitioned by recent/empty/Blue-upgrade/archive purpose.

Historical media now uses three independent truths:

`playable = at least one positively validated in-app asset exists`

`catalogComplete = every applicable discovery lane for that event has been attempted/exhausted`

`qualityComplete = the preferred Gold historical package has been found`

The playback preference is **Gold → Green → Purple/Extended → Blue**. A lower-tier asset never blocks playback and is never discarded, but it remains upgrade-eligible after source exhaustion. Source-complete lower-tier events persist as `VERIFIED_UPGRADE_PENDING` with a future `nextRetryAt`. Recent dates retry more aggressively; older archive dates retry gently. The idle cloud worker re-enters a date when one of those quality retries becomes due.

`HISTORY_DISCOVERY_VERSION = 12` provides a non-destructive soft reindex: old scores/assets remain authoritative, while older completion/retry metadata cannot suppress the Green-gap and quality reassessment.

### HistoricalEventCatalog

Historical media has one server-side authority backed by SQLite:

`~/.sports-big-board/cache/history.sqlite3`

The browser read path for an arbitrary date is:

`ScoreDateStore HOT → /api/history/day WARM → /api/history/scores canonical fetch → score-provider COLD`

Media discovery is separate from score hydration and is normalized around the sporting event:

`history_event(date, league, event_id)`

`history_media_asset(date, league, event_id, asset_key)`

`history_collection_media(scope, league, period_key, asset_key)`

`history_event` owns discovery state, last attempt/success, retry time and provider-lane diagnostics. `history_media_asset` owns durable **GAME** asset identity, provider validation, verification time and browser runtime PLAYED/FAILED state. `history_collection_media` owns Silver daily/weekly recap assets independently from game truth. The older `history_day` date/league JSON row is retained as a fast hydration/cache compatibility tier, not as playback authority.

Historical score misses are fetched through `/api/history/scores`, which coalesces concurrent league/date requests and writes the same canonical events consumed by media discovery. Opening a historical date then triggers one server-owned `POST /api/history/discover` job. That job walks the final canonical score events and invokes the same event service used by a touch-priority FIND action. The browser does not call league-specific YouTube/ESPN discovery routes for historical games.

The event endpoint is:

`POST /api/history/event/discover {date, league, eventId, force}`

and returns an authoritative playback plan:

`event → discovery → media[] → playable[] → primary`

The browser can also read that plan through `GET /api/history/event/media`. Runtime playback feedback is written through `POST /api/history/media/runtime`, so a source that fails after provider validation is demoted persistently for that exact event/asset.

Historical discovery states are explicit: `VERIFIED`, `CANDIDATE_ONLY`, `DEGRADED_PROVIDER`, and `SEARCHED_EMPTY`. Provider/network failure is not equivalent to a successful empty search. Retry timestamps determine when incomplete events become eligible again.

The idle `history_backfill_worker` walks backward through prior calendar days, caches scoreboards and advances canonical event discovery one game at a time. It never consumes `search.list`; foreground interaction may use the shared date-level search rescue described below.


## v2.7 provider-independent media plane

The application no longer asks a provider to play a game. It asks for a package:

- `QUICK` — concise complete recap, with sport-specific duration targets
- `EXTENDED` — longer optional package
- `COMMENTARY` — postgame analysis/talk
- `MOMENTS` — live/short highlight moments

Each source adapter may contribute assets to the Event Media Manifest. The resolver scores those assets by package fit, sport duration policy, source quality, current provider health, transport type, runtime failures and observed buffering. A provider-specific failure therefore cannot erase the fact that a game exists or that another provider may have usable media.

`MediaManifest` is the source of truth for score-ribbon availability. A green/purple/blue/gold rail is derived from the manifest rather than from a provider response that may later fail. Runtime playback failures are written back to that same manifest so the ribbon and player cannot disagree. External-only packages remain discoverable without being advertised as internally playable.

Direct HTTP video is now a generic transport. ESPN, NFL/club, MLB Stats and future direct-video adapters share the same localhost range proxy, event-scoped cache, 16 MB startup runway and prewarm scheduler. The legacy concept of `MLB_NATIVE` no longer exists.

Provider health and asset health are deliberately separate. A YouTube 101/150 failure invalidates that video, not YouTube globally. A provider-level outage/rate limit affects source ranking/cooldown without destroying already discovered media. Repeated direct-video buffering is recorded per asset and lowers that asset's future resolver preference.

## Information-surface layout

**Below** is the canonical default on all devices. The information surface is in normal document flow immediately after the player.

Mobile/coarse-pointer devices always remain below-video, including landscape.

On wide fine-pointer PCs only, Settings may opt into **Side** mode. The preference is UI-only and cannot alter playback state.

With **Keep Video Visible** enabled, `ui/player-visibility.js` uses scroll + `requestAnimationFrame` plus an Android-safe fixed presentation layer and dynamic in-flow placeholder. While the player shrinks, placeholder geometry keeps the Game Center edge exactly beneath the visible video. At minimum size it enters a bounded workspace: the player remains fixed, the information surface is fixed below it, and only the active Game Center pane scrolls. The controller does not toggle root `overflow` or synthesize window scroll positions, avoiding Android Chromium snap-back. The player DOM node is never recreated or reassigned. With the preference disabled, normal document scrolling applies.


### Provider identity rule

The selected score event is the canonical sporting-event fingerprint. When the score provider also exposes detailed match data, its exact match id is the preferred Game Center identity. For Highlightly-sourced events, Sports Big Board first uses that same match id for detailed match data and, for MLB, the provider's statistics and box-score resources. MLB Stats/ESPN resolution is fallback only. Browser requests still carry date, away/home teams, start time and game number, and every provider response is verified against those teams before SQLite is written. Cached `Unknown` placeholders and mismatched legacy aliases are rejected rather than reused.

## Game Center contract

`GET /api/events/{competition}/{eventId}/game-center`

All detailed sport adapters emit the same structural contract while retaining sport-specific stat meanings:

- `event`
- `scoreboard`
- `teamStats[]`
- `playerStatSections[]`
- `timeline[]`
- `scoringPlays[]`
- `live`
- `updatedAt`
- `source`

Implemented adapters:

- MLB — Highlightly detailed match + statistics + box score first; MLB Stats API live feed/v1 components fallback
- NFL — Highlightly detailed match first; ESPN summary fallback
- NBA — Highlightly score identity with ESPN basketball summary fallback
- NHL — Highlightly score identity with ESPN hockey summary fallback
- MLS — Highlightly detailed match first; ESPN summary fallback
- EPL — Highlightly detailed match first; ESPN summary fallback

Player-stat sections carry explicit `teamSide`, team identity and `category`. The UI no longer needs to infer team ownership from a title such as `San Francisco 49ers passing`; inference exists only as a legacy fallback.

A StatSection renderer does not need to know what RBI, receiving yards or possession mean; adapters provide labels/columns/rows.

## GameCenterRepository

Game Center state is persistent application data stored in SQLite:

`~/.sports-big-board/cache/game-centers.sqlite3`

`GameCenterRepository` owns normalized snapshots keyed by `(competition, event_id)` and records status/live/scheduled/provider/update/expiry metadata.

Preparation flow:

`continuous today/yesterday score inventory → same-provider detail when available → official-provider fallback → dedicated GameCenterWorkScheduler → normalize → SQLite`

A selected-game repository miss never performs a provider fetch on the browser HTTP request thread. The server returns `202 PREPARING`, promotes that event to `TOUCH_INTENT`, and the browser polls localhost. This keeps MLB/ESPN latency isolated from UI responsiveness.

Read path:

`browser HOT → localhost SQLite WARM → provider COLD`

Completed/final snapshots receive long retention. Live snapshots are centrally refreshed by `game_center_refresh_worker`. Expired-but-present data can be returned immediately while refresh is scheduled, avoiding click-time stalls.

The repository also migrates best-effort legacy v2.6.2 JSON snapshots.

## Game Center request ownership

Browser Game Center requests use a generation token and AbortController:

`SelectedEvent changes → generation++ → abort previous request → render resident cache if present → fetch localhost → accept response only if generation is still current`

A timeout changes the UI to an explicit unavailable/retry state rather than leaving an infinite loading state.

## API credential architecture

Machine-local secrets are stored outside release directories:

`~/.sports-big-board/secrets.env`

` sbb/secrets.py ` is the sole credential persistence boundary. Environment variables may override the stored file, but normal launchers run `setup_credentials.py` and persist missing values once.

Browser endpoints expose configuration status only:

- `GET /api/settings`
- `POST /api/settings/secrets`

Responses never echo secret values.

Windows and Android launchers share the same per-machine model. Different physical machines do not automatically share secrets.

## Server boundaries

- `sbb/competition_registry.py`
- `sbb/provider_registry.py`
- `sbb/media_classifier.py`
- `sbb/media_policy.py`
- `sbb/media_work_scheduler.py`
- `sbb/game_center.py`
- `sbb/game_center_repository.py`
- `sbb/history_repository.py`
- `sbb/editorial_registry.py`
- `sbb/secrets.py`
- `server.py` — composition / HTTP boundary

Useful diagnostics:

- `GET /api/status`
- `GET /api/architecture`
- `GET /api/game-center/repository`
- `GET /api/settings`

## League editorial packages

League-wide roundup media remains separate from events:

- `editorialScope: league`
- `editorialType: top_plays`
- `competitionId`
- `cadence`
- `editorialPeriodKey`

Initial registered series: MLB daily, NBA nightly and NFL weekly Top Plays.

## Game Center completeness and provider isolation

Game Center caching is completeness-driven rather than first-response-driven. Each normalized snapshot receives sport-aware coverage metadata. A final MLB shell with only teams and score is **partial** until linescore, team statistics, player sections and play-by-play/scoring data have been collected. Partial rows receive short TTLs and remain eligible for touch-intent/background enrichment.

Provider event indexes are stored independently by source. Highlightly score inventory never replaces the official MLB Stats/ESPN inventory for the same competition/date. The server can merge normalized provider snapshots while preserving the score-card event fingerprint as authority, and only publishes a provider identity when its teams match the selected event.

The browser mirrors this rule: partial Game Centers have a short resident-cache lifetime and periodically re-read localhost, so an early shell cannot mask a richer SQLite snapshot that arrives seconds later.

## Compact workspace chrome

When Keep Video Visible reaches the compact sticky workspace, the normal page-level Now Playing/title/transport bar remains in layout for stable geometry but is visually and interactively suppressed. This prevents duplicate controls from appearing behind the pinned video while keeping PlaybackController and the actual media element untouched.

## Historical embedded-media validation

Historical YouTube discovery is day-indexed rather than game-searched. For supported official league channels the primary path is:

`activities.list(channelId + date window) → upload IDs → videos.list(batch) → verified league/day catalog → exact matchup association`

`activities.list` and `videos.list` live in independent gateway failure domains from `search.list`. A search-bucket 429 therefore cannot disable historical upload indexing or exact-ID validation. If the activity catalog is unavailable or incomplete during an interactive historical session, localhost may spend at most **one `search.list` call per league/date**, cache that official-channel day result, batch-validate it with `videos.list`, and share it across all games on the date. Idle backfill never invokes that rescue.

Public YouTube HTML, Bing/DuckDuckGo indexing and oEmbed are discovery/metadata lanes only. oEmbed does **not** prove iframe permission and can never by itself produce a green historical score card. A YouTube asset becomes internally playable only after positive `videos.list` embed/US-region validation or a previously recorded successful runtime playback. Direct ESPN/team/league media must pass a range/content-type probe and receives an item-level verification timestamp because signed URLs can expire.

The IFrame API remains final runtime authority. Error 101/150 demotes only the exact YouTube asset and triggers same-game fallback/recovery; 153 is treated as client-identification/referrer failure rather than content unavailability. Sports Big Board serves `strict-origin-when-cross-origin` and supplies `origin`/`widget_referrer` to the player. Runtime failures are persisted into `history_media_asset`, preventing stale green rails after reload.

`HISTORY_DISCOVERY_VERSION = 7` ensures older v3.0.1 and v2.8.x discovery records are reconsidered under the playable-vs-catalog-complete model without deleting the historical SQLite database.


## v3.0.9 success condition

Adding a league no longer requires teaching PlaybackController how that league works. The integration path is: register the competition, add/enable score inventory, contribute media assets through provider adapters, configure sport media policy, and use the shared Game Center contract. Existing providers may fail independently without collapsing the event inventory or forcing a league-specific playback branch.

A user can select and play a game, fail over among same-game sources, scroll normalized Game Center data while optionally keeping the video visible, switch games rapidly, restart the server and reuse prepared final Game Centers, and configure APIs once per machine — all while PlaybackController remains the sole media activation authority.

## v3.0.9 catalog-to-ribbon reconciliation

A verified asset is only useful when the browser actually hydrates it. v3.0.9 removed the remaining legacy `history_day.media_saved_at` dependency from browser hydration. `history_media_asset` is authoritative and is always projected into `ScoreDateStore` for the selected historical date. This guarantees that server inventory, ribbon availability, event playback plans, and PlaybackController all consume the same asset truth.

Historical click flow is now cache-first: `GET /api/history/event/media` -> play if verified -> otherwise `POST /api/history/event/discover` -> rehydrate date -> play. `apiJson()` preserves RequestInit so POST semantics cannot silently degrade to GET.


## v3.0.9 Cloud Stage 1 deployment boundary

The browser and backend are now independently deployable. `config.js` selects the API origin at runtime and `api-runtime.js` rewrites `/api/*` requests to the configured HTTPS backend. Local mode leaves `apiBase` empty and remains same-origin. GitHub Pages builds inject `SBB_API_BASE_URL` and publish static assets only.

Cloud state is release-independent. `SBB_STATE_DIR` points the server at `/var/lib/sports-big-board`, mounted from a Google persistent disk. Historical SQLite, Game Center SQLite, provider caches, runtime playback truth, and daily backups therefore survive application upgrades and VM service restarts.

The VM remains the single discovery owner. GitHub Pages contains no API keys and no database. Caddy terminates HTTPS and proxies to the Python service on `127.0.0.1:8080`. Cloud mode disables browser mutation of API credentials.

The Stage 1 invariant is: **frontend deployments are disposable; historical state is persistent.**


## v3.0.9 audit-state projection

`history_event.discovery_state` remains a raw durable pipeline marker. The audit API no longer displays raw `UNKNOWN` as if it means no data. It combines current discovery-version metadata with the normalized verified media catalog to derive `effectiveStatus`, `discoveryPending`, `catalogComplete`, `qualityComplete`, and inferred `upgradeEligible`. This projection is read-only and therefore cannot accidentally mark stale events current or suppress the version-driven reindex scheduler.
