# Sports Big Board v5.4.7 Hierarchical Controller Navigation Map

v5.4.7 retains the v5.4.5 controller/navigation foundation, repairs fullscreen activation, makes Y / Triangle a guaranteed Game Center show/hide control, and adds hierarchical league, Special Event, and team/player-browse controller radials.

## Input transport priority

1. Browser Gamepad API
2. Sports Big Board Windows Native Controller Bridge (`127.0.0.1:5410`)
3. WebHID fallback

Mouse/keyboard input still takes ownership immediately. Controller focus memory is preserved when controller mode is hidden.

- Header live-input indicator remains beside BACKEND and reports bridge/controller state.

## Core controller bindings

- D-pad / Left Stick — semantic navigation
- A — Select / activate
- B — Back
- X — Play / Pause
- **Y / Triangle — Show / Hide Game Center drawer**
- LB / RB — Previous / Next highlight
- Right Stick — contextual scroll
- RT — League radial
- LT — Date / scope radial
- **LT + RT — Special Commands radial**
- R3 — Pointer fallback
- Menu / Start — controller help


## Hierarchical RT league radial

RT opens the league wheel. Selecting a core league such as MLB, NFL, NBA, NHL, EPL, MLS, or NCAAF immediately opens a second radial with:

- **TODAY** — league games for the current day
- **ALL** — the league's historical/all-games browse surface
- **TEAM BROWSE** — team-focused browse for team sports
- **PLAYER BROWSE** — used automatically for player-based competitions such as tennis

Selecting **SPECIAL EVENTS** opens a second radial populated from the same live Special Events registry used by the on-screen menu. Selecting an event then opens an event-scope radial with **ALL** and **TEAM BROWSE / PLAYER BROWSE** as appropriate. No duplicate special-event registry is introduced.

## Game Center recovery

Y / Triangle is reserved for Game Center visibility. If the desktop drawer is collapsed, Y expands it and switches to Game Center. If another drawer tab is active, Y switches to Game Center. If Game Center is already open and expanded, Y collapses it. On overlay/mobile layouts the same control uses the normal open/close drawer contract.

## Fullscreen reliability

The logo-adjacent fullscreen button requests standards-based fullscreen on `document.documentElement` during the trusted click event. Controller-originated APP FULLSCREEN and VIDEO FULLSCREEN commands continue through the local Windows bridge (`F11` and `F`) because gamepad/WebSocket input cannot create browser transient user activation.

## Special Commands radial

Hold LT + RT, point with the right stick, then release both triggers:

- APP FULLSCREEN
- VIDEO FULLSCREEN
- EXIT FULLSCREEN
- PLAY / PAUSE
- MUTE / UNMUTE
- GAME CENTER
- LEAGUE VIEW
- SETTINGS

The browser Fullscreen API is used for trusted mouse/keyboard activation. Controller-originated fullscreen may use the loopback Windows bridge's two-command whitelist (`app-fullscreen` = F11, `video-fullscreen` = F) because Chromium does not treat Gamepad/WebSocket polling as a transient user activation.

## D-pad region traversal

Movement is now **semantic-region first**:

1. Find a directional target inside the current region.
2. At the region edge, follow the explicit region graph.
3. Skip any intermediate region that currently has no focusable controls.
4. Only then use whole-page geometry as a safety fallback.

D-pad Up from the Score Ribbon now jumps directly to League Navigation. Once there, Left/Right walks the visible league/scope controls in deterministic DOM order, so animated TODAY / ALL / TEAM BROWSE controls cannot steal or strand focus. Sports Ticker remains reachable by moving Down from League Navigation.

## Primary regions

- Launch
- Global Header
- League Navigation
- Date Navigation
- Sports Ticker
- Score Ribbon
- System Status
- Left Navigation
- Now Watching
- Recap Alternatives
- Player Transport
- Soundtrack
- Player Stage
- Transition/Bumper Overlay
- Playback Terminal
- Player Utilities
- Drawer Tabs
- Game Center
- Sport Match Center
- League View
- Settings
- Coming Up
- Team / Player Browse
- Special Events
- Date Picker
- Milestone Console
- Historical Database Audit
- Developer Tools
- Generic Modals
- Global Utility fallback

## ALL / score-ribbon playback follow

When an ALL/score-ribbon program advances, the card corresponding to the active game receives a **NOW WATCHING** highlight. On each game change the horizontal ribbon scrolls so the active game is approximately the third visible card, giving the viewer two items of context behind the current program while still exposing upcoming games to the right.

This reconciliation is event-driven from title, SelectedEvent, playback-progress, score-click, curated-selection, and ribbon-render events. It does not add a continuous polling loop.

## Stable region IDs

- `launch`
- `special-events`
- `date-picker`
- `team-browse`
- `milestone-console`
- `history-audit`
- `sport-match-center`
- `league-view`
- `settings`
- `game-center`
- `coming-up`
- `drawer-tabs`
- `transition-overlay`
- `playback-terminal`
- `soundtrack`
- `player-alternates`
- `player-transport`
- `player-utilities`
- `player-stage`
- `now-watching`
- `left-nav`
- `date-nav`
- `league-nav`
- `global-header`
- `sports-ticker`
- `score-ribbon`
- `system-status`
- `developer-tools`
- `modal`
- `global-utility`


## v5.4.7 Controller-native Team / Player Browse

Selecting **TEAM BROWSE** or **PLAYER BROWSE** now stays entirely inside the controller radial system. The actual participant list is loaded from the existing persisted Browse participant catalog and shown six participants per radial page, with **PREV**, **NEXT**, and **BACK** wedges when needed. This applies uniformly to MLB, NFL, NBA, NHL, EPL, MLS, NCAAF, World Cup, US Open, LLWS, and other supported competitions. World Cup is no longer a special-case interaction.

The radial delegates the selected participant back to the existing Browse `browseEntity` authority, so this does not create a second history, queue, or playback system.

## v5.4.7 SendInput fullscreen delivery

Controller fullscreen keeps the same two-command loopback whitelist, but the Windows bridge now sends F11/F with Windows **SendInput** first. Legacy `keybd_event` remains only as a compatibility fallback. After handling either command, the bridge returns a `command-result` message to the browser so Sports Big Board can distinguish a command that was merely requested from one that Windows actually accepted for injection.
