# Sports Big Board v5.4.3 Controller Readiness Region Map

v5.4.3 is an interaction-architecture release. It does **not** bind the Gamepad API yet. It establishes the semantic focus graph that v5.4.3+ Controller Mode will consume.

## Coverage rule

Every actionable element is registered by `architecture/controller-readiness-v540.js` and receives:

- `data-sbb-focusable="1"`
- a stable `data-sbb-focus-id`
- a named `data-sbb-region`
- keyboard activation for non-native clickable controls when required

New controls rendered after startup are registered through one **child-list-only** MutationObserver. The observer never watches attributes, so the attributes added by registration cannot feed back into the observer.

`global-utility` is the emergency accessibility safety net. A control routed there remains reachable, but `SBB_CONTROLLER_READINESS.audit()` reports the release as WARN until that control receives a more specific semantic region. This gives future UI a fail-loud coverage path without making it unreachable.

## Regions

| Region | Current Big Board surfaces | Preferred entry |
|---|---|---|
| `launch` | Launch screen, local-file warning | Start Sports Big Board |
| `global-header` | Fullscreen, backend utility, top-level header actions | Fullscreen / date utility |
| `league-nav` | ALL, league chips, Special Events, TODAY/ALL/TEAM BROWSE subnav | Active league |
| `date-nav` | Select Date, Return to Today, day arrows, day indicator, date input | Current day indicator |
| `sports-ticker` | Sports Ticker ribbon | First actionable ticker item if present |
| `score-ribbon` | Daily score cards, curated event/game cards | First visible game card |
| `system-status` | Feed diagnostics and media coverage pipeline | First action if a control is added |
| `left-nav` | Around the League, My Teams, Live Games, Scores, Standings, Settings | Active nav item |
| `now-watching` | Current league/title/subtitle presentation | Playback control handoff |
| `player-alternates` | Quick / Extended / Commentary recap choices | First visible recap choice |
| `player-transport` | Previous, Play/Pause, Next | Play/Pause |
| `soundtrack` | Soundtrack toggle, next, volume | Soundtrack toggle |
| `player-stage` | Video stage and native controls | Playback control handoff |
| `transition-overlay` | Bumpers, unavailable/fallback actions, loading/search overlays | First fallback action |
| `playback-terminal` | Dev playback terminal and endurance controls | Start endurance test |
| `player-utilities` | Game Center, League View, Settings, bumper, fullscreen | Game Center |
| `drawer-tabs` | Game Center / League View / Settings tabs and close | Active drawer tab |
| `game-center` | Score header, Game Center section tabs, retries, player team tabs | Active Game Center tab |
| `sport-match-center` | Tennis/special-sport Match Center fallback | First Match Center action |
| `league-view` | Standings / bracket / tournament context | Refresh if present |
| `settings` | Viewing, APIs, ticker tuning, database/certification launch controls | First settings control |
| `coming-up` | Pinned Coming Up cards and legacy queue rows | First queued program |
| `team-browse` | Team/Player Browse dialog, favorites, search, focus ribbon, Play All/Exit | Search / first team or player |
| `special-events` | Special Events selector | First event |
| `date-picker` | Calendar/date popover | Today / selected date |
| `milestone-console` | Certification/stress-test modal | Close / Run |
| `history-audit` | Historical database audit, playlists, recovery, Silver audit | Close / Refresh |
| `developer-tools` | Player debug and Dev-only controls | First control |
| `modal` | Any otherwise-unmapped dialog/popover | First control |
| `global-utility` | Emergency safety-net region | First global action |

## Navigation foundation

`window.SBB_SEMANTIC_NAVIGATION` exposes the future controller primitives:

- `move('up'|'down'|'left'|'right')`: region-first, geometry-aware directional navigation
- `focus(...)` / `focusById(...)`: visible semantic focus and region memory
- `activate(...)`: common future Controller-A activation path
- `back()`: centralized hierarchical Back behavior
- `ensureVisible(...)`: keeps selected controls inside their scroll viewport

Directional navigation prefers another control in the current region. If none exists, it evaluates visible controls by screen geometry and then uses the explicit region graph as a final neighbor fallback.

## Back hierarchy

The future Controller-B action will use the already-defined `back()` order:

1. Certification console
2. Historical database audit
3. Team/Player Browse popover
4. Special Events menu
5. Date picker/calendar
6. Team/Player Focus
7. Active Special Event or normal league context (`Exit Event` / `Exit League`)
8. Information drawer
9. Active normal league -> ALL
10. No-op at board root

## Input ownership foundation

`window.SBB_INPUT_OWNERSHIP` supports three owners now:

- `pointer`
- `keyboard`
- `controller`

v5.4.3 only detects pointer and keyboard. It intentionally does **not** call `navigator.getGamepads`, listen for `gamepadconnected`, or poll a controller. v5.4.3 can claim `controller` ownership immediately when meaningful gamepad input is detected.

Pointer ownership requires a click, wheel action, or at least 10 pixels of meaningful movement, which prevents tiny sensor movement from stealing ownership. Keyboard ownership ignores modifier-only keys.

## Focus memory

The last focused semantic control is remembered independently for every region in session storage. This allows future controller navigation to return to the last league, score card, Game Center tab, team, Coming Up card, etc., rather than resetting to the first control every time.

## Runtime audit

In the browser console:

```js
SBB_CONTROLLER_READINESS.audit()
```

A clean result has:

- `uncovered: 0`
- `fallback: 0`
- `duplicateFocusIds: []`
- `ok: true`

The full region/control counts are included in the returned `regions` object.

## v5.4.3 Core Controller Bindings

Controller Mode is automatic. A connected standard-mapped controller does not change input ownership until the user makes a meaningful controller input. Mouse click/wheel/meaningful movement or a keyboard key immediately returns ownership to that device. Controller focus memory is preserved between ownership changes.

| Controller input | Core action |
| --- | --- |
| D-pad / left stick | Geometry-aware semantic focus navigation through the region graph |
| A / primary face button | Activate the focused control |
| B / secondary face button | Canonical Back hierarchy |
| X / west face button | Play All when the active context exposes Play All |
| Y / north face button | Cycle Game Center → League View → Settings |
| LB | Previous highlight |
| RB | Next highlight |
| Right stick | Scroll the focused scrollable region without moving semantic focus |
| Menu / Start | Toggle the compact controller help legend |
| LT / RT | Reserved for v5.4.3 radial menus; no action in v5.4.3 |
| Stick clicks | Reserved for later pointer/fallback UX |

Controller input uses a 0.22 analog deadzone, edge-triggered face/shoulder buttons, and bounded D-pad/left-stick repeat. A neutral-input latch prevents a held controller input or stick drift from immediately stealing ownership back after mouse/keyboard takeover.
