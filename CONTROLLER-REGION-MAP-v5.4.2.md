# Sports Big Board v5.4.2 Controller Region + Binding Map

v5.4.2 keeps the v5.4.0 semantic interaction graph as the single controller navigation authority, preserves v5.4.1 automatic last-input-wins behavior, and adds live browser input diagnostics, radial navigation, and an analog pointer fallback.

## Coverage rule

Every actionable element is registered by `architecture/controller-readiness-v540.js` and receives a stable focus identity plus a named semantic region. Newly rendered controls are registered from child-list mutations only. `global-utility` remains a fail-loud safety net: anything that lands there is still reachable, but `SBB_CONTROLLER_READINESS.audit()` reports WARN until it is assigned to a specific region.

## Regions

| Region | Big Board surfaces |
|---|---|
| `launch` | Launch screen and startup controls |
| `global-header` | Fullscreen, Backend, controller-live indicator context, header utilities |
| `league-nav` | ALL, league chips, Special Events, TODAY/ALL/TEAM BROWSE |
| `date-nav` | Select Date, Return Today, day arrows, date indicator/picker |
| `sports-ticker` | Sports Ticker ribbon |
| `score-ribbon` | Daily scores and curated game/event cards |
| `system-status` | Feed/media diagnostics |
| `left-nav` | Primary application navigation |
| `now-watching` | Current program metadata |
| `player-alternates` | Quick/Extended/Commentary recap choices |
| `player-transport` | Previous / Play-Pause / Next |
| `soundtrack` | Soundtrack controls |
| `player-stage` | Video stage and native controls |
| `transition-overlay` | Bumpers, loading/fallback actions |
| `playback-terminal` | Playback diagnostics/endurance controls |
| `player-utilities` | Drawer launch, fullscreen and player utility controls |
| `drawer-tabs` | Game Center / League View / Settings |
| `game-center` | Game Center header, tabs, retries and stat controls |
| `sport-match-center` | Tennis/special-sport Match Center |
| `league-view` | Standings, brackets and league context |
| `settings` | Viewing, API, controller and certification settings |
| `coming-up` | Pinned Coming Up cards and queue |
| `team-browse` | Team/Player Browse, focus ribbon, Play All/Exit |
| `special-events` | Special Event selector |
| `date-picker` | Calendar/date popover |
| `milestone-console` | Certification/stress-test modal |
| `history-audit` | Historical database audit |
| `developer-tools` | Dev/debug controls |
| `modal` | Otherwise-unmapped dialogs/popovers |
| `global-utility` | Emergency accessibility fallback |

## Core controller bindings

Controller Mode is automatic. Mouse/keyboard input takes ownership immediately; the next meaningful controller input takes it back after a neutral latch.

| Controller input | Action |
|---|---|
| D-pad / left stick | Geometry-aware semantic focus navigation |
| A | Activate focused control |
| B | Canonical Back hierarchy |
| X | Play All when available |
| Y | Cycle Game Center → League View → Settings |
| LB / RB | Previous / Next highlight |
| Right stick | Scroll the focused scrollable region |
| Menu / Start | Toggle controller help |
| **RT — League radial** | Hold to open the League wheel; move right stick; release to select |
| **LT — Date / scope radial** | Hold to open Today/Yesterday/Prev/Next/Select Date/All/Team Browse/Return Today wheel |
| **R3 — Pointer fallback** | Toggle analog pointer mode; left stick moves cursor, A clicks, right stick scrolls, B returns to focus mode |

## Header live-input indicator

A compact controller indicator appears immediately next to **BACKEND**:

- `🎮 WAIT` — Browser Gamepad API is available but no controller is currently exposed to the page.
- `🎮 READY` — The browser can see the controller, but Sports Big Board has not received a meaningful controller input yet / pointer or keyboard currently owns input.
- `🎮 LIVE` — Controller input is reaching Sports Big Board and controller ownership is active.
- `🎮 POINTER` — Controller ownership is active in R3 pointer fallback mode.
- `🎮 NO API` — The browser context does not expose `navigator.getGamepads()`.

The tooltip shows the controller ID, browser mapping (`standard` or non-standard), input owner, and last controller-input time. This is intended to distinguish “Windows sees my controller” from “the browser is actually receiving Gamepad API input.”

## Robust browser/controller handling

v5.4.2 retains low-frequency disconnected discovery and rAF polling only while a browser-visible controller exists. It also adds:

- browser refocus and post-pointer discovery retries for browsers that gate controller enumeration until the page is focused;
- Turtle Beach / Xbox-family identification;
- non-standard trigger-axis normalization;
- fallback D-pad axes 6/7 handling;
- a neutral latch that ignores arbitrary non-standard axes resting at `-1`, preventing a controller from becoming permanently locked out after mouse takeover;
- raw meaningful-input detection so even an otherwise unmapped controller input can prove that the browser is receiving the device.

No `setInterval()` controller loop and no controller `MutationObserver` are introduced.

## Radial behavior

### RT League wheel

`ALL`, `MLB`, `NFL`, `NBA`, `NHL`, `EPL`, `MLS`, `NCAAF`, `SPECIAL EVENTS`.

The right stick is primary radial selection. The left stick can select as a fallback when the right stick is neutral. Releasing RT commits the highlighted wedge. Releasing without selecting does nothing.

### LT Date / scope wheel

`TODAY`, `YESTERDAY`, `PREV DAY`, `NEXT DAY`, `SELECT DATE`, `ALL`, `TEAM BROWSE`, `RETURN TODAY`.

The wheel uses the existing date and league-scope controls rather than creating a second date/navigation authority.

## Pointer fallback

R3 switches between semantic Focus Mode and Pointer Mode. Pointer Mode does not replace the normal controller UX; it is an escape hatch for unusual controls:

- left stick: cursor movement;
- A: click the item under the cursor;
- right stick: contextual scrolling beneath the cursor;
- B or R3: return to semantic Focus Mode.

RT/LT radials remain available while Pointer Mode is active.

## Back hierarchy

The canonical B-button order remains:

1. Certification console
2. Historical database audit
3. Team/Player Browse
4. Special Events menu
5. Date picker/calendar
6. Team/Player Focus
7. Active Special Event or league context
8. Information drawer
9. Active normal league → ALL
10. No-op at board root

## Runtime audits

```js
SBB_CONTROLLER_READINESS.audit()
SBB_CONTROLLER_MODE.snapshot()
```

A clean readiness result has `uncovered: 0`, `fallback: 0`, no duplicate focus IDs, and `ok: true`. The controller snapshot reports API visibility, controller ID/mapping, last raw input, current owner, radial/pointer state, and live-indicator state.
