# Sports Big Board v3.0.3

## v3.0.3 quality-aware historical catalog

This release fixes the remaining reason old dates could settle permanently on Blue reels. Historical media now has **three separate truths** instead of one overloaded completion flag:

- `playable`: at least one verified in-app asset exists.
- `catalogComplete`: all applicable provider/source lanes have been inventoried.
- `qualityComplete`: the preferred historical package quality has been reached.

The preferred playback order remains **Gold commentary → Green quick recap → Purple extended → Blue reel**. A Blue, Purple, or Green result stays immediately playable and is never discarded, but it no longer closes the event. Only Gold marks the quality target satisfied. Lower tiers are persisted as `VERIFIED_UPGRADE_PENDING` once source discovery is exhausted, with gentle cloud retry windows so the always-on server can keep improving the archive without hammering providers.

`HISTORY_DISCOVERY_VERSION = 8` is also an automatic **soft reindex** of the existing cloud database. v3.0.1/v3.0.2 scores, media assets, Game Center data, and runtime playback truth are preserved. Old discovery completion/retry state is treated as stale and each historical event is reconsidered under the new quality rules. No manual SQLite deletion/reset is required.

The cloud backfill now revisits a source-complete date when a lower-tier quality retry becomes due. Initial day bootstrapping no longer writes authoritative event-completion state; only the canonical per-event discovery pipeline can do that. This prevents a cheap Blue find from accidentally closing a game before the richer lanes are assessed.

Historical diagnostics now expose both **CATALOG** and **QUALITY** counts so it is visible when a day is fully indexed but still has Gold/Green/Purple upgrades pending. Desktop ribbon wheel/drag navigation and the larger full-surface date arrows from v3.0.2 are retained.

## Cloud Stage 1

The production path remains the GitHub Pages frontend backed by the always-on Google Compute Engine server and persistent historical SQLite catalog. The cloud backend owns score/media discovery, Game Center hydration, runtime playback truth, and the 400-day historical backfill. Local Termux/Windows mode remains supported for development and fallback.

### Normal release workflow

After the one-time `cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh` setup, a release is just a push to `main`: upload the complete unzipped repository contents at the GitHub repository root. The GitHub Action verifies the build, deploys the Compute Engine backend with automatic rollback/health checking, then publishes the matching GitHub Pages frontend. No Cloud Shell command is required for normal releases.

## v3.0.1 historical playback foundation

v3.0.1 established the server-owned historical event/media catalog used by v3.0.3:

`selected date → canonical score events → event catalog → validated media assets → playback plan → PlaybackController → runtime feedback`

The normalized `history_event` and `history_media_asset` tables remain the persistent source of truth. Runtime playback success/failure survives browser reloads, score-ribbon hydration uses the same catalog as playback, and historical Game Center remains independent of media selection.

### Historical discovery lanes

1. Official/native event media such as ESPN event packages and MLB official media.
2. Official YouTube channel activity indexing with exact-ID validation.
3. One shared official-channel `search.list` rescue per league/date during foreground historical browsing.
4. Public YouTube/search-engine discovery as candidate metadata only until positively validated.
5. League/team-specific free lanes where available, including the NFL feed.

The idle cloud builder intentionally does not spend the scarce YouTube `search.list` bucket. It exhausts the no-search lanes and leaves the event instantly playable with a lower tier while still marking richer catalog discovery as eligible for later foreground upgrade.

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
- **The old two-face Today/Yesterday toggle has been superseded in v3.0.3 by explicit calendar-day navigation.** The underlying viewer-day date authority and ESPN fallback behavior remain in place.
- **Playback waits longer for the exact YouTube player and retries the exact media once** before falling back to a user tap. This preserves the single PlaybackController ownership model while making normal iframe/network startup hiccups less visible.
- **Friendly loading states.** Game Center now says **Loading Game Center…** with a spinner. Video startup/buffering shows **Loading video…** or **Buffering video…** with the same lightweight animation instead of developer-oriented status text.

Sports Big Board is a local, personalized sports television system: live scores and game state feed a direct-tune ribbon, official highlights and recaps feed the player, Game Center adds the live/final statistical context, and Around the League provides unattended programming.

v3.0.3 builds on the stabilized score inventory and Game Center work by adding arbitrary historical date context without coupling ribbon browsing to playback.

## Launch experience

A fresh page load now opens on a full-screen **Sports Big Board** splash instead of immediately starting the channel. Scores, news and media discovery may warm in the background, but active playback is launch-gated until the viewer presses **START SPORTS BIG BOARD**. The pre-launch page stays clean. After Play is pressed, the current program is selected into Game Center and the local resolver runs several short follow-up passes while score inventory finishes warming, so the first game's statistics populate automatically instead of requiring a second score-card click.

## Legacy Today / Yesterday score authority

NFL, NBA and NHL score inventory retains its ESPN fallback whenever Highlightly is empty. In v3.0.3 the league filter no longer changes the date automatically: the viewer-selected calendar date remains authoritative. ESPN historical lookups keep trying alternate transports when a non-empty endpoint response contains only the wrong calendar day, preventing a weekly/current board from masking the requested date.

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

Detailed adapters in v3.0.3:

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

The browser uses request generations and AbortController so obsolete selections cannot update the current panel. v3.0.3 also makes repository misses asynchronous: localhost returns PREPARING immediately, promotes the selected game to touch-intent priority on a dedicated Game Center worker pool, and the browser polls localhost until the prepared snapshot is available. A slow MLB/ESPN socket therefore no longer blocks the browser request.

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
cd ~/storage/downloads/sports-big-board-v3.0.3/sports-big-board-v3.0.3
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

The v3.0.3 regression suite covers, among other things:

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

## League-level editorial packages

The canonical programming model continues to reserve league-level Top Plays packages separately from individual games:

- MLB — **Top Plays of the Day** (`daily`)
- NBA — **Top Plays of the Night** (`nightly`)
- NFL — **Top Plays of the Week** (`weekly`)

They belong to Around-the-League programming and never mutate `SelectedEvent` or a game's Gold/Green/Purple/Blue package.

## v3.0.3 historical playback reconciliation

v3.0.3 fixes the first integration issues revealed by the canonical v2.9 history catalog:

- Browser JSON requests now preserve HTTP method/body, so exact-event historical discovery reaches the POST endpoint instead of falling through to a GET 404.
- Normalized `history_media_asset` catalog rows hydrate the score-date store even when the legacy league-day `media_saved_at` field is empty. Server `playable` counts and score-card rails therefore derive from the same catalog.
- A historical game click checks the existing event playback plan before launching discovery, making revisited dates instant when verified assets already exist.
- Historical diagnostics separately expose verified catalog assets and ribbon-ready games.
- Current-day YouTube search work yields while a historical date is foregrounded, and exhausted `search.list` cooldowns no longer produce one error per game.
- ESPN/network postgame analysis and press-room coverage classify as Gold commentary instead of Blue highlight reels when appropriate.
