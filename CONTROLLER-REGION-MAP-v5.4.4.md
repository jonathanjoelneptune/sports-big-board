# Sports Big Board v5.4.4 Controller Region + Transport Map

v5.4.4 preserves the complete semantic focus architecture introduced in v5.4.0 and the controller UX added in v5.4.1-v5.4.3. The change in this release is the controller **transport stack**: controllers that Windows can read but Chrome will not expose can now feed the exact same semantic navigation engine through a loopback-only Windows helper.

## Controller input priority

1. **Browser Gamepad API** — preferred zero-install path whenever Chrome exposes the controller normally.
2. **Sports Big Board Windows Controller Bridge** — local `127.0.0.1:5410` WebSocket transport. The helper reads XInput first and falls back to Windows `joyGetPosEx`.
3. **WebHID** — retained as a browser diagnostic/fallback for compatible HID controllers.

Only one transport is presented to the controller engine at a time, preventing duplicate events when a physical controller is visible through more than one path.

## Windows bridge indicator states

- `🎮 NO BRIDGE` — no browser controller is visible and the local helper is not connected.
- `🎮 BRIDGE` — helper is connected to the page but no Windows controller is currently available.
- `🎮 BR READY` — helper and Windows controller are detected; waiting for meaningful input.
- `🎮 BR LIVE` — controller input from the helper currently owns Sports Big Board.
- `🎮 READY` / `🎮 LIVE` — direct browser Gamepad path.
- `🎮 HID READY` / `🎮 HID LIVE` — WebHID fallback path.
- `🎮 POINTER` — R3 pointer fallback is active regardless of underlying controller transport.

## Windows helper boundary

The helper is under `windows-controller-bridge/` and is deliberately local/read-only:

- binds only `IPAddress.Loopback` / `127.0.0.1`;
- accepts the production Sports Big Board GitHub Pages origin plus localhost development origins;
- reads XInput slots 0-3 first;
- falls back to WinMM joystick input for Windows-recognized controllers not exposed by XInput;
- emits only normalized buttons, triggers, D-pad and stick axes;
- sends no controller output, rumble, firmware, USB, HID, authentication or vendor commands;
- makes no outbound internet requests.

## Controller mappings retained

- D-pad / Left Stick: semantic focus navigation
- A: select / activate
- B: semantic back
- X: Play All when available
- Y: Game Center → League View → Settings
- LB / RB: previous / next highlight
- RT: league radial
- LT: date / scope radial
- Right Stick: contextual scroll and radial selection
- R3: pointer fallback
- Menu / Start: controller help overlay

## Semantic region inventory

Every current actionable component remains registered in one of these regions:

- `launch`
- `global-header`
- `league-nav`
- `date-nav`
- `sports-ticker`
- `score-ribbon`
- `system-status`
- `left-nav`
- `now-watching`
- `player-alternates`
- `player-transport`
- `soundtrack`
- `player-stage`
- `transition-overlay`
- `playback-terminal`
- `player-utilities`
- `drawer-tabs`
- `game-center`
- `sport-match-center`
- `league-view`
- `settings`
- `coming-up`
- `team-browse`
- `special-events`
- `date-picker`
- `milestone-console`
- `history-audit`
- `developer-tools`
- `modal`
- `global-utility`

The v5.4.0 completeness audit remains authoritative: new interactive controls that fall into `global-utility` keep basic access but cause the readiness audit to warn until they receive an explicit semantic region.

## Compatibility labels retained

- RT — League radial
- LT — Date / scope radial
- R3 — Pointer fallback
- Header live-input indicator
