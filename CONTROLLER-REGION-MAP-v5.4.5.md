# Sports Big Board v5.4.5 Controller Navigation Map

v5.4.5 retains the v5.4.0 semantic region architecture and the v5.4.4 Windows Native Controller Bridge, then tightens D-pad region transitions, adds fullscreen ownership, adds an LT+RT Special Commands radial, and makes the ALL/score ribbon follow the currently playing game.

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
- Y — Game Center → League View → Settings
- LB / RB — Previous / Next highlight
- Right Stick — contextual scroll
- RT — League radial
- LT — Date / scope radial
- **LT + RT — Special Commands radial**
- R3 — Pointer fallback
- Menu / Start — controller help

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
