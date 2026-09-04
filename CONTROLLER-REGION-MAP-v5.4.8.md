# Sports Big Board v5.4.8 Controller Navigation Map

v5.4.8 refines the v5.4.7 controller foundation around four user-facing contracts: reliable X / Square play-pause, Y / Triangle Game Center ↔ League View switching, L3 drawer visibility, and dense logo-first Team / Player Browse. It also makes controller video fullscreen reversible without leaving the fullscreen view.

## Input transport priority

1. Browser Gamepad API
2. Sports Big Board Windows Native Controller Bridge (`127.0.0.1:5410`)
3. WebHID fallback

Mouse/keyboard input still takes ownership immediately. Controller focus memory is preserved when controller mode is hidden.

## Core controller bindings

- D-pad / Left Stick — semantic navigation
- A / Cross — Select / activate
- B / Circle — Back
- **X / Square — Play / Pause**
- **Y / Triangle — toggle Game Center ↔ League View**
- **L3 / Left Stick Click — open / close the information drawer**
- R3 / Right Stick Click — Pointer fallback
- LB / RB — Previous / Next highlight
- Right Stick — contextual scroll / radial selection
- RT — League radial
- LT — Date / scope radial
- **LT + RT — Special Commands radial**
- Menu / Start — controller help

X / Square invokes the canonical `playBtn` transport directly and does not require that the button be visually exposed. This keeps pause/resume working while player controls are hidden or the stage is fullscreen.

## Game Center / League View controls

Y / Triangle is now a view switch, not a drawer visibility button:

- Game Center visible → **League View**
- League View visible → **Game Center**
- Settings/other drawer tab → **Game Center**

L3 independently owns drawer visibility. When the drawer is open, L3 collapses/closes it. When it is hidden or collapsed, L3 restores the previously active Game Center/League View tab.

## Hierarchical RT league radial

RT opens the league wheel. Selecting MLB, NFL, NBA, NHL, EPL, MLS, or NCAAF opens the league-scope radial with:

- **TODAY**
- **ALL**
- **TEAM BROWSE**

Player competitions use **PLAYER BROWSE** automatically.

Selecting **SPECIAL EVENTS** opens the same live Special Events inventory used by the page. Selecting an event opens **ALL** plus **TEAM BROWSE / PLAYER BROWSE**.

## Dense logo-first Team / Player Browse

Team/Player Browse remains controller-native but is much denser than v5.4.7:

- Up to **16 teams/players per radial page** instead of six.
- Team logos are used when participant metadata provides them.
- A compact abbreviation/initial mark is used when no logo is available.
- The full team/player name appears in the radial center when selected.
- PREV / NEXT / BACK remain available when pagination is required.

The selected participant is passed to the same Browse entity-selection authority used by the top league Team/Player Browse menu. The controller explicitly locks the selected league or Special Event context before invoking that authority, so a Padres selection under MLB cannot accidentally query the previous league and report `No games found`.

## Video fullscreen exit

Controller VIDEO FULLSCREEN now targets the complete `.stage-card`, rather than fullscreening the raw YouTube iframe or native `<video>` element. This keeps Sports Big Board controller overlays inside the fullscreen subtree.

While video fullscreen is active:

- LT + RT still displays the Special Commands radial.
- **VIDEO FULLSCREEN** changes to **EXIT VIDEO FULLSCREEN**.
- **EXIT FULLSCREEN** also remains available.
- Selecting either exit path returns to the normal board.

The controller radial is dynamically mounted inside the fullscreen stage while video fullscreen is active and moved back to the document body on exit.

## Special Commands radial

Hold LT + RT, point with the right stick, then release both triggers:

- APP FULLSCREEN / EXIT APP FULLSCREEN
- VIDEO FULLSCREEN / EXIT VIDEO FULLSCREEN
- EXIT FULLSCREEN
- PLAY / PAUSE
- MUTE / UNMUTE
- GAME CENTER
- LEAGUE VIEW
- SETTINGS

Controller-originated fullscreen still uses the local Windows bridge when transient browser user activation is required. The bridge whitelist remains limited to `app-fullscreen` and `video-fullscreen`.

## D-pad region traversal

Movement remains semantic-region first:

1. Find a directional target inside the current region.
2. At the region edge, follow the explicit region graph.
3. Skip intermediate regions that currently have no focusable controls.
4. Use whole-page geometry only as a safety fallback.

D-pad Up from the Score Ribbon jumps directly to League Navigation. Left/Right then walks the visible league/scope controls in deterministic DOM order.

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

## Retained controller diagnostics
- Header live-input indicator remains the immediate controller/bridge ownership diagnostic.
- R3 / Right Stick Click — Pointer fallback remains available independently of the new L3 drawer control.

### Compatibility control labels
- X — Play / Pause

## Fullscreen reliability
The controller fullscreen ownership contract remains certified.

## Controller-native Team / Player Browse
Dense logo-first participant selection remains entirely controller-native.

## SendInput
The v5.4.7 R1 Windows helper remains compatible with v5.4.8 and retains SendInput fullscreen delivery plus command-result acknowledgement.
