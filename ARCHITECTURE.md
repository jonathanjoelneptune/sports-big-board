# Sports Big Board v4.2.2 — Milestone 1 Final Hardening

The v4.2.2 boundary keeps the v4.2 ownership model but makes five invariants explicit: Dev Test visually owns the screen while open; collection media cannot become a game identity; foreground playback can force background full-cache work to yield; worker health is phase-aware; and historical UI hydration uses bounded date-scoped contracts rather than the legacy all-in-one day aggregate. Game Center background coverage also observes provider cooldown and avoids duplicate fallback prewarming when authoritative coverage exists.

# Sports Big Board v4.2.2 Architecture


## v4.2.2 — Milestone 1 Hardening

Milestone 1 read-side architecture is hardened around **foreground work first**. SQLite remains in WAL mode, but hot operator/audit reads now use independent query-only connections instead of the repository writer lock. Historical discovery bulk-loads the date's event state and avoids nested catalog-integrity scans. Operator telemetry is a cache of independently refreshed components with staggered TTLs rather than one continuously repeating full snapshot. Startup schedule sync covers only the near-term window before background expansion and emits a heartbeat around each provider step. Director ranking is deterministic on the request path; optional AI enrichment is serialized and cached in the background. Milestone telemetry records component refresh errors, scheduler error categories, and the same repeatable stress procedures used for release acceptance.

## v4.2.0 Milestone 1 reliability boundary

Milestone 1 adds an explicit **Playback Session** above provider-specific A/B/native/YouTube adapters. The adapters still perform the actual player API calls, but selection identity, transport assignment, playback state, first-frame time, stalls, failures, source URL and audible ownership are emitted into `SBB_PLAYBACK_SESSION`. Dev Mode, the milestone console, soundtrack ownership reporting and diagnostics consume this single session snapshot rather than independently reconstructing playback truth.

The observable pipeline is now:

`Selected Event / Media → PlaybackController transport action → Playback Session truth → Dev + Milestone telemetry`

A/B player slots report their audible state into the session. Two simultaneously audible video slots are an invariant failure and are logged immediately. The soundtrack remains a separate application audio service, but it also reports audible state to the same session so diagnostic output can distinguish site music from source-video audio. Player Debug exposes the exact external source URL for the active clip.

The backend `MilestoneConsole` is a bounded in-memory operational ledger, not durable product state. It records API latency/error aggregates, playback telemetry, browser heartbeats/errors, stress/procedure results, background-thread exceptions and release problems. `/api/milestone/console` joins this ledger with inexpensive live truth: worker heartbeats, operator snapshot age, history singleflight/provider concurrency, database audit status, scheduler snapshots and media-cache state. The console deliberately avoids a new whole-catalog synchronous scan.

`MediaWorkScheduler` now exposes keyed job reuse/supersession, queue age, active workers and aggregate wait/run/error counts. Foreground `/api/media` streaming never enters this scheduler and retains priority over background full-cache completion. Historical discovery continues to use its durable event claims, provider semaphores and existing singleflight protections; v4.2.0 makes those coordination layers visible rather than replacing proven recovery logic during the milestone.

The browser stress harness talks only through `SBB_DEV_TEST_HOOKS`, a narrow test boundary over official UI/controller actions. It can run release handshake, playback ownership, historical reads, concurrent operator load, resource-mode transitions, Game Center, soundtrack and event-loop procedures. It snapshots user-visible state before the run and logs restoration failures explicitly. The harness is diagnostic only and never becomes a second PlaybackController.

Release generation is fail-closed. `VERSION` must match the core model and every cache-busted local JS/CSS asset. GitHub Actions deploys the backend first, verifies its public version, publishes Pages only after that succeeds, then verifies the live Pages generation and `/api/milestone/console` handshake. This prevents a new frontend from silently operating against an old backend contract.

## v4.1.26 operator/read and playback boundary

The interactive operator surfaces are no longer allowed to perform expensive whole-catalog work synchronously. A background telemetry worker refreshes green-gap, association, claim, Silver, media-objective, and Silver-identity summaries into an in-memory snapshot. The Live Search Console only combines that snapshot with inexpensive live thread/worker state, so its frequent polling does not compete with discovery or playback.

The common Historical Database Audit path is SQL-paged. SQLite selects the requested event page first and only hydrates media relationships belonging to those events. This preserves the established audit row semantics while removing the initial full-catalog materialization. Advanced semantic filters retain the exhaustive compatibility path where necessary. Silver daily roundups use query-only WAL readers and normalized verification/runtime columns as playback authority.

Native direct-video playback extends the v4.1.25 cache with fixed 8 MB follow-on chunks after the 16 MB startup head. Hybrid responses write every already-cached contiguous chunk to the browser before opening the upstream CDN remainder. Full-file completion remains lower priority. Playback diagnostics record first-frame time and distinguish browser-hot adoption, server cache hits, hybrid chunk delivery, and cold-upstream transport.

## v4.1.22 curated playlist recovery + source registry

v4.1.22 keeps the five-worker v4.1.21 scheduler and adds an operator-curated, playlist-first GAME acquisition layer for leagues whose generic/web recovery was producing long provider waits. The new playlist lanes use `playlistItems.list + videos.list` only; they do not depend on YouTube `search.list`. Event Matcher v7 remains fail-closed: playlist membership establishes source provenance, while a GAME assignment still requires both teams plus explicit-title or publication-date evidence.

Pinned GAME inventories now include the official NHL `2025-2026 NHL Full Game Highlights` playlist, operator-supplied 2025/2026 soccer Match Highlights playlists, official MLB 2025/2026 Game Highlights playlists, and the complete operator-supplied set of 2025 NFL weekly/playoff recap playlist anchors. The existing EPL 2025-26 NBC season playlist remains active and is exposed alongside the current Premier League/NBC playlists. NHL/MLS trusted Match Highlights are Extended/Purple lanes; MLB derives Green/Extended from the actual package; NFL retains separate Quick and Extended objectives.

Rule Game Catch-up advances to **v10**. Only the affected source ledgers are versioned/reopened: NFL playlist Quick/Extended move to v2, while new NHL/MLS/MLB playlist source keys begin at v1. Discovery remains **v15**, Event Matcher remains **v7**, Rule Collection Catch-up remains **v8**, provider semaphores remain unchanged, and no catalog rebuild is required. Existing media and associations are preserved.

Historical Database Audit gains a **GAME MEDIA PLAYLISTS** tab backed by `/api/history/media-sources`. It is the operator-facing source registry for MLB/NFL/NBA/NHL/EPL/MLS and displays Primary, Secondary, Fallback, and Silver sources with direct URLs, season scope, objective, collector key, trust level, and notes. Operator Recovery is collapsed by default and remembers its local expanded/collapsed state so recovery controls no longer dominate the audit surface.

## v4.1.21 parallel recovery and operator-control boundary

The historical scheduler is now a five-worker recovery pool rather than a three-lane migration gate. Worker 1/2/3 retain NFL/MLS/EPL first refusal, Worker 4 is NHL-first floating capacity, and Worker 5 is general-coverage-first floating capacity. An affinity worker only reserves itself while its own league has claimable work; retry-delayed leftovers cannot park compute. All workers still share the existing provider semaphores, so increasing scheduling concurrency does not automatically increase external-provider concurrency.

Floating generic work uses a small opportunity score: no verified media outranks Blue-only gaps, recent games outrank old games, and league deficit/source confidence biases high-value recovery before optional quality upgrades. NHL official-source work can therefore proceed in parallel with EPL replay instead of waiting for the specialized migration to finish.

Operator recovery has three separate state transitions:

1. **Cursor restart** changes traversal upper date/direction and releases leases; it preserves source-completion ledgers and media.
2. **Source audit reopen** removes only selected source-enrichment ledger rows (league/source/objective/date scope), making those provider checks eligible again while preserving all media and associations.
3. **Database audit restart** resets only the local read-only audit generation/cursor. It does not trigger network discovery.

Both reset operations expose a dry-run preview and require its confirmation token before apply. Existing media is never deleted by these controls.

A restartable database-audit worker scans catalog events in bounded batches and persists its generation/cursor. It reports no-verified-media events, stale discovery metadata, quarantined links, catalog integrity, and EPL Every Goal identity health. Silver identity is audited as unique YouTube IDs → unique source assets → collection links; Rule Collection Catch-up remains v8 and is not automatically replayed.

Operator terminology is presentation-safe: catalog media coverage, media objectives, and source-completion progress are separate dimensions. Internal legacy states remain backward compatible, but the UI displays `UNINDEXED` as **Index Pass Pending** and rule completion as **source-complete**.

Discovery v15, matcher v7, Rule Game Catch-up v9, EPL source v6, current media collectors, and provider concurrency limits remain unchanged. v4.1.21 requires no catalog rebuild.


## v4.1.32 soundtrack boundary

The soundtrack remains an application-level service rather than a MediaAsset or PlaybackController transport, but v4.1.32 intentionally makes its lifecycle **clip-scoped**. `architecture/site-soundtrack.js` owns exactly one browser `Audio` element and receives both coarse playback state and the canonical current media key from `app.js`. A changed media key hard-stops the old soundtrack song, chooses one new shuffle-bag track, and assigns it to the new highlight. Repeated `ready / starting / buffering / playing` transitions for the same media key cannot select additional songs.

Before the red launch action, soundtrack is disabled and cannot autoplay during player warmup. `startExperience()` explicitly enables soundtrack for the first clip, which keeps the button state and audible state synchronized. Video pause/resume pauses/resumes the current clip song. If that song ends while the clip is still active, the engine advances to another song without changing the clip identity. Search Priority and tab hiding still suspend audio.

Soundtrack audio never enters MediaManifest, GAME/Silver classification, historical SQLite, provider health, or media-prewarm queues. GitHub Pages ships the manifest but not the MP3 payload. The private bucket and signed-GCS/private-proxy transport are unchanged.

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

## v4.1.21 EPL playlist acquisition boundary

Rule Game Catch-up v6 preserves strict affinity: `green-gap-1 → NFL`, `green-gap-2 → MLS`, `green-gap-3 → EPL`. Discovery remains v15, so v4.1.21 does not globally invalidate unrelated historical discovery. Rule Collection Catch-up v5 is narrowly reopened for the official EPL Every Goal playlist and does not replay the already-completed MLS/legacy Silver migration.

EPL GAME discovery now prefers curated YouTube playlist graphs:

`canonical EPL event → season playlist → playlistItems.list → videos.list → exact two-club/date/duration objective → persisted GAME media`

The official Premier League `Club highlights` family can satisfy Quick or Extended depending on duration. Green/Quick is 2–7 minutes; Purple/Extended is 8–20 minutes. Both require both clubs and event-date consistency. The NBC Sports season-playlist lane is Extended-only and additionally requires the literal `PREMIER LEAGUE HIGHLIGHTS` title signature; an explicit title date must exactly match the canonical event date.

Known 2026-27 Premier League/NBC playlist IDs and the pinned NBC 2025-26 season playlist are bootstrap anchors. Trusted Premier League/NBC channel catalogs are enumerated only for pin repair or future-season discovery. No EPL playlist lane calls `search.list`.

`Every Goal ... Matchweek N` videos from the official Premier League channel are collection media, never GAME media. They resolve to `ROUND_LEAGUE`, `SCORING_ROUNDUP`, and a season-aware key such as `2026-27:MW1`. Rule Collection Catch-up v3 samples the fixed historical floor newest-first and persists only new source assets/collection links; repeats are reused/idempotently suppressed.

EPL source/objective ledgers are independent and ordered: `epl-youtube-pl-quick@v1`, `epl-youtube-pl-extended@v1`, `epl-youtube-nbc-extended@v1`, then the existing PremierLeague.com Quick and NBC webpage Extended fallback lanes. `[EPL PLAYLISTS]` exposes playlist persistence/health while `[EPL CANDIDATES]` retains explicit rejection dispositions.

The NFL playlist architecture from v4.1.14 is unchanged and remains the primary NFL Extended path. MLS Snapshot/Highlights, association matcher v7, Silver relationship semantics, and persistence tracing are unchanged.

## v4.1.6 audit coverage visibility and semantic color coding

Historical audit presentation now exposes the coverage axis directly: `coverageCompleteGames` and `coverageCompleteByLeague` are computed independently from Green-focused Quick Recap coverage. The browser displays both metrics and uses stable semantic badge classes for leagues, Silver scope, and Silver collection kind. These are presentation/observability changes only; coverage thresholds, Green-gap scheduling, Silver classifier v5, and normalized catalog relationships are unchanged.

## v4.1.5 Silver authority, period identity, and coverage semantics

Silver is a **promotion layer**, not a synonym for any league-level-looking video. `SOURCE_MEDIA` remains permissive; `history_collection_media` is fail-closed. Promotion requires both (1) strong daily/weekly league-wide roundup language and (2) source authority from a verified league publisher or trusted major broadcaster. Verified official league channel IDs receive the highest collection rank. Team/club publishers and unknown/self-described official channels cannot establish league-wide authority. `SEASON_LEAGUE` remains source taxonomy and is not Silver.

Collection periods are content-owned. `DAY_LEAGUE` resolves from explicit title date first and publication chronology second; crawler/backfill encounter dates cannot smear the same asset across adjacent days. `WEEK_LEAGUE` uses `league + explicit season ID + season week`, e.g. `NBA:2025-26:W24` or `NFL:2025:W18`, never `2026:W24` as an ISO/calendar interpretation. Collection-classifier upgrades rebuild only collection relationships and preserve source assets plus all GAME/discovery state.

GAME completeness has two independent axes:

- **Coverage:** Gold / Green / Purple (`extended`) = complete; Blue / None = incomplete.
- **Editorial quality:** Gold is complete; Green/Purple may remain optional upgrade candidates according to existing quality/search policy.

This distinction is observable in the History Audit as `Catalog Coverage Status` versus `Quality Gap Status`. It does not change media-tier thresholds or Green-gap worker eligibility; it only prevents a legitimate Purple game package from being counted as an unresolved coverage failure.

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
- `architecture/site-soundtrack.js` — exactly-one-Audio clip-scoped soundtrack, one new song per highlight media key, long-clip song continuation, pause/resume coupling, controls, singleton protection, single-tab ownership, and private Cloud Storage audio resolution
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

### v4.1.21 normalized historical catalog baseline

v4 treats a discovered media asset and a sporting-event relationship as different entities. The fundamental flow is:

`provider harvest → SOURCE_MEDIA → scope/intent classifier → EVENT_MEDIA or COLLECTION_MEDIA or REVIEW → validation/runtime truth → derived playback coverage`

The normalized tables are:

`history_catalog_event(canonical_event_key = LEAGUE:EventID, event_date, final_at, discovery state...)`

`history_source_media(asset_key, provider identity, URL/title/duration/published_at, scope, intent, classification evidence, validation/runtime...)`

`history_event_media(canonical_event_key, asset_key, association state/confidence/method/evidence/matcher version)`

`history_collection(scope, league, period_key, collection_kind)`

`history_collection_media(collection_key, asset_key, classification confidence/evidence/rank)`

`history_media_segment(asset_key, optional event/collection target, start/end/confidence/evidence)`

`history_media_verification(asset_key, verification type/state/reason/version/time)`

`history_discovery_attempt(canonical_event_key, source/query/results/accepted/before-after/quota/failure)`

`history_assignment_review(asset_key, proposed event, QUARANTINED|UNASSIGNED reason/evidence)`

`history_day` remains only a score/day hydration and compatibility cache. It is never event-media playback authority in v4.

#### Source identity and association

A YouTube video is stored once as `yt:<videoId>`. Other providers use explicit media ids or stable direct-URL fingerprints; generic ids are provider-namespaced and title-fingerprinted so a game id cannot collapse several clips. An asset can affect an event only through an `ASSIGNED` `history_event_media` relationship with confidence ≥ 0.90. Provider conflicts fail closed. Matchup-title association requires both opponents. Daily/nightly/top-plays packages are collections, not games.

An integrity audit treats these as release-blocking failures:

- Silver/collection media linked as GAME;
- GAME media linked into Silver;
- assigned event relationships below the confidence threshold;
- a GAME source asset assigned to more than one canonical event;
- low-confidence collection links; or
- reconstructed source assets with no event, collection, or review accounting.

#### Scope and intent

Scope answers **what the asset covers** (`GAME`, `DAY_LEAGUE`, `WEEK_LEAGUE`, `PLAYER`, `SEASON_LEAGUE`, `OTHER`). Intent answers **what kind of program it is** (`RECAP`, `CONDENSED_GAME`, `EXTENDED_HIGHLIGHTS`, `HIGHLIGHT`, `TOP_PLAYS`, `PLAYER_HIGHLIGHTS`, `INTERVIEW`, `ANALYSIS`, `PRESS_CONFERENCE`, `FULL_GAME`, `OTHER`). Both decisions retain confidence, reason, and classifier version.

Gold/Green/Purple/Blue remain GAME-only quality tiers. Silver is the UI representation of collection media. Consequently an NBA Nightly Recap can be an excellent Silver daily asset while Lakers/Bulls remains Purple because its best game-specific package is a 16-minute full-game highlight.

#### Derived coverage and search scheduling

Coverage is derived from assigned, validated, runtime-healthy GAME media rather than stored as fundamental asset truth:

`playable = at least one positively validated GAME asset`

`catalogComplete = applicable source lanes have completed for the current discovery pass`

`qualityComplete = preferred Gold package is present`

`coverageComplete = usable game-specific media exists even when a better tier could still appear`

Playback preference remains **Gold → Green → Purple/Extended → Blue**. Candidate GAME assets are validated before any new discovery. `LEAGUE:EventID` is the queue identity, so local/UTC date aliases cannot generate duplicate work. Retry cooldown/backoff and the `history_discovery_attempt` ledger prevent the same no-improvement search from consuming quota repeatedly. Search quota is partitioned among recent, empty, Blue-upgrade, and archive purposes.

`HISTORY_DISCOVERY_VERSION = 15` is fresh discovery bookkeeping on top of the reconstructed v4 catalog.

### v4.1.21 targeted Rule Game Catch-up v3

NFL, MLS, and EPL are reopened by source/objective version instead of by destructive reindex. During Rule Game Catch-up v3, the three Green workers use migration affinity: worker 1 prefers NFL, worker 2 MLS, and worker 3 EPL. Ordering remains newest-first inside each league; an affinity worker may consume other league work after its preferred queue is exhausted. This prevents a low-yield collector from monopolizing the entire pool while preserving the shared durable event lease.

MLS Quick and Extended use `mls-match-snapshot@v2` and `mls-match-highlights@v2`. The Snapshot collector walks MLSsoccer.com's paginated Match Highlights inventory and pairs an undated same-match Snapshot with the nearest explicit same-pair highlight date. EPL uses `premierleague-official@v4` for Quick and `nbc-epl-extended@v3` for Extended. NFL uses four public/team objective ledgers as described above.

The MLS/EPL Silver replay remains a dedicated post-seed worker, but v4.1.21 makes its accounting idempotent: candidates examined, qualifying, new unique assets, reused assets, new links, duplicate links, and rejects are tracked separately. A persisted Rule Collection Catch-up v2 completion marker means reboot does not restart finished migration work.

#### Offline v3 → v4 reconstruction

The application server never performs a destructive v3 relationship migration at startup. `tools/ensure_history_v4.py` and `sbb/history_rebuild.py` reconstruct a second database while the backend is stopped:

`v3 history.sqlite3 (immutable evidence) → pre-v4 backup → history-v4-rebuild.sqlite3 → reconciliation audit → atomic install`

The rebuild preserves canonical scores/events, deduplicates source assets, preserves safe verification/runtime truth, reruns scope/intent classification, distrusts generic legacy event stamps, re-proves GAME associations, routes daily/weekly content into Silver, quarantines ambiguity, and resets stale discovery completion/retry bookkeeping. Every source asset must be accounted for before installation.

Cloud deployment records the pre-v4 backup path before starting the new release. A release-health failure restores that database together with the prior `/opt/sports-big-board/current` symlink. Local/Android/Windows launch scripts use the same preflight.

#### Audit surfaces

- `/api/history/audit` — event coverage/tier/status projection.
- `/api/history/catalog/integrity` — schema/integrity counters.
- `/api/history/catalog/review` — quarantined/unassigned association review queue.
- `/api/history/catalog/attempts` — durable discovery attempt/quota/failure ledger.
- `/api/history/catalog/collections` — paged Silver collection membership/evidence audit with scope/kind/period/search/integrity filters.
- `/api/history/catalog/collections.csv` + `.xlsx` — filtered Silver Roundups audit export.
- `/api/history/roundups` — playable Silver daily/weekly programming.

The operator status vocabulary is **UNINDEXED**, **SEARCHED EMPTY**, **COVERAGE COMPLETE**, **UPGRADE PENDING**, **QUALITY COMPLETE**, **PROVIDER DEGRADED**, and **CANDIDATE ONLY**. Provider failure and successful empty search are deliberately distinct.

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

The IFrame API remains final runtime authority. Error 101/150 demotes only the exact YouTube asset and triggers same-game fallback/recovery; 153 is treated as client-identification/referrer failure rather than content unavailability. Sports Big Board serves `strict-origin-when-cross-origin` and supplies `origin`/`widget_referrer` to the player. Runtime failures are persisted into `history_source_media`, preventing stale green rails after reload.

`HISTORY_DISCOVERY_VERSION = 7` ensures older v3.0.1 and v2.8.x discovery records are reconsidered under the playable-vs-catalog-complete model without deleting the historical SQLite database.


## v3.0.9 success condition

Adding a league no longer requires teaching PlaybackController how that league works. The integration path is: register the competition, add/enable score inventory, contribute media assets through provider adapters, configure sport media policy, and use the shared Game Center contract. Existing providers may fail independently without collapsing the event inventory or forcing a league-specific playback branch.

A user can select and play a game, fail over among same-game sources, scroll normalized Game Center data while optionally keeping the video visible, switch games rapidly, restart the server and reuse prepared final Game Centers, and configure APIs once per machine — all while PlaybackController remains the sole media activation authority.

## v3.0.9 catalog-to-ribbon reconciliation

A verified asset is only useful when the browser actually hydrates it. v3.0.9 removed the remaining legacy `history_day.media_saved_at` dependency from browser hydration. `history_source_media` is authoritative and is always projected into `ScoreDateStore` for the selected historical date. This guarantees that server inventory, ribbon availability, event playback plans, and PlaybackController all consume the same asset truth.

Historical click flow is now cache-first: `GET /api/history/event/media` -> play if verified -> otherwise `POST /api/history/event/discover` -> rehydrate date -> play. `apiJson()` preserves RequestInit so POST semantics cannot silently degrade to GET.


## v3.0.9 Cloud Stage 1 deployment boundary

The browser and backend are now independently deployable. `config.js` selects the API origin at runtime and `api-runtime.js` rewrites `/api/*` requests to the configured HTTPS backend. Local mode leaves `apiBase` empty and remains same-origin. GitHub Pages builds inject `SBB_API_BASE_URL` and publish static assets only.

Cloud state is release-independent. `SBB_STATE_DIR` points the server at `/var/lib/sports-big-board`, mounted from a Google persistent disk. Historical SQLite, Game Center SQLite, provider caches, runtime playback truth, and daily backups therefore survive application upgrades and VM service restarts.

The VM remains the single discovery owner. GitHub Pages contains no API keys and no database. Caddy terminates HTTPS and proxies to the Python service on `127.0.0.1:8080`. Cloud mode disables browser mutation of API credentials.

The Stage 1 invariant is: **frontend deployments are disposable; historical state is persistent.**


## v3.0.9 audit-state projection

`history_catalog_event.discovery_state` remains a raw durable pipeline marker. The audit API no longer displays raw `UNKNOWN` as if it means no data. It combines current discovery-version metadata with the normalized verified media catalog to derive `effectiveStatus`, `discoveryPending`, `catalogComplete`, `qualityComplete`, and inferred `upgradeEligible`. This projection is read-only and therefore cannot accidentally mark stale events current or suppress the version-driven reindex scheduler.

### v4.1.21 fail-closed event association

Event Matcher v5 makes association evidence stricter than provider discovery. Broad source results are never stamped with the target Event ID or target away/home teams before matching. Matchup-title conflicts, explicit MLB date mismatches, stale season/year content, and one-asset/multiple-game conflicts fail closed into quarantine. A one-time matcher-version repair re-evaluates existing v4 EVENT_MEDIA links without deleting SOURCE_MEDIA.

The queue now prioritizes first-pass NONE/BLUE events ahead of archive Purple optimization, uses the remembered sports-day timezone for the recent window, persists YouTube Search exhaustion through restart until the provider reset window, and uses Pacific-day accounting with a hard internal search ceiling.


### v4.1.21 structural preflight boundary

Deployment health is intentionally split into **structural integrity** and **repairable relationship integrity**. Structural integrity covers the normalized table set, SQLite quick-check, foreign-key consistency, and normalization completeness. Only a structural failure can select the offline reconstruction path. Event/collection relationship issues such as matcher-version drift, cross-event links, scope leaks, and low-confidence associations never select reconstruction. They cause an optional pre-repair rollback snapshot, then `HistoryRepository.repair_relationships()` runs against the existing catalog. The backend performs a hard post-repair relationship audit before workers start.

This boundary means a future Event Matcher or Media Classifier version may re-evaluate `history_event_media` / `history_collection_media`, but cannot reset `history_catalog_event.discovery_*`, `history_discovery_attempt`, `history_media_verification`, or `history_day.discovery_json`.


## v4.1.21 bounded discovery concurrency

Historical discovery is concurrent at the event level, not at the quota level. Three Green-gap threads may own different canonical Event IDs in SEARCH mode, with `history_catalog_event` lease fields (`claim_owner`, `claim_started_at`, `claim_expires_at`) acting as the durable concurrency boundary. Date-backfill participates in the same lease protocol. Provider semaphores and same-day single-flight locks cap external pressure independently of worker count. YouTube Search and Highlightly remain single-concurrency lanes. The worker-console API exposes pool state, leases, provider active/waiting counts, and throughput. Daily/weekly Silver collection totals are also exposed without mixing collection media into GAME quality. The Historical Database Audit has a dedicated **Silver Roundups** tab that reads this collection model directly, surfaces collection/asset integrity flags, and exports Silver separately from GAME media.


## v4.1.21 tier-aware provider staging

The concurrent pool does not imply that every claimed game runs every provider. Each event pass has a **pass target** independent from the long-term Gold quality target. Green-gap and one-game chronological backfill passes target Green; full foreground discovery targets Gold. Candidate validation remains first. Authoritative/native lanes run one stage at a time, persist accepted GAME media, and recalculate the event tier after each stage. If the pass target is reached, remaining primary lanes and all fallback lanes are skipped.

The fallback stage is ordered `public page → public index → YouTube search rescue`. It also recalculates after every lane, so a free fallback hit can prevent the next web request or scarce `search.list` call. If the target remains unmet and Search rescue is unavailable or incomplete, the event remains partial rather than being falsely closed as searched-empty. The worker-console API publishes process-lifetime efficiency counters (`primaryPasses`, `primaryTargetHits`, `shortCircuits`, `fallbackAttempts`, `fallbackHits`, `fallbackSeconds`, `estimatedSecondsSaved`) for soak-test validation.

### Fixed historical seed boundary (v4.1.21)

Chronological date backfill is a one-time bootstrap, not a permanent rolling workload. The production seed floor is `2025-08-01` inclusive. The date worker owns broad score/media inventory only; Green-gap workers own subsequent per-event quality improvement. Seed completion is persisted in `history_catalog_meta` with the exact floor and completion timestamp. Once complete, the date worker remains heartbeat-only (`complete:historical-seed`) and does not scan older dates on later restarts. A future explicit floor change invalidates the marker and reopens only the newly requested seed range.

## v4.1.21 official content acquisition adapters

The discovery graph now includes explicit structured adapters for the content libraries that best fit the Sports Big Board product contract. Each adapter is an independent provider lane with shared single-flight/cache behavior and runs before generic fallback:

- NHL.com game-recaps topic → `official-nhl-game-recap`
- NHL.com condensed-games topic → `official-nhl-condensed-game`
- PremierLeague.com official video → `official-premierleague-match-highlights`
- NBC Sports Premier League extended highlights → `trusted-nbc-epl-extended`
- MLSsoccer.com match-highlights topic → `official-mls-match-highlights`

Exact GAME promotion still requires source-derived matchup/date evidence and Event Matcher v5 assignment. Direct MP4/HLS URLs must pass the native range/content-type probe. If a page is authoritative but does not expose usable in-app media, it remains an external source rather than being falsely counted playable.

Silver now models league rounds separately from dates and season weeks. `ROUND_LEAGUE` is canonical for Premier League Matchweeks and MLS Matchdays, while `SCORING_ROUNDUP` represents league-wide all-scoring packages. NHL weekly Top Goals / Top Saves remain `WEEK_LEAGUE:TOP_PLAYS`. The strict Silver classifier remains the promotion boundary, so collecting an official source page does not automatically make every item Silver.
