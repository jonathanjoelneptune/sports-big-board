# Sports Big Board v5.4.3 Controller Region + Transport Map

v5.4.3 preserves every semantic focus region from v5.4.0-v5.4.2. The transport layer now has two browser inputs feeding the same controller navigation engine:

1. **Gamepad API (primary, automatic)** — no permission prompt when the browser exposes the controller normally.
2. **WebHID bridge (fallback)** — intended for devices such as the Turtle Beach Stealth Ultra wireless receiver when Windows/vendor software sees the device but `navigator.getGamepads()` does not.

## Header indicator

- `🎮 WAIT` — browser controller APIs available, no usable controller currently exposed.
- `🎮 HID PAIR` — Gamepad API did not expose a controller; click once to grant WebHID access.
- `🎮 HID READY` — authorized HID device is open and waiting for input.
- `🎮 HID LIVE` — HID input reports are being translated into the normal Big Board controller engine.
- `🎮 READY` / `🎮 LIVE` — normal Gamepad API path.
- `🎮 POINTER` — analog pointer fallback active.
- `🎮 NO API` — neither Gamepad nor WebHID is available in the browser context.

The HID bridge is deliberately read-only. It never sends vendor, GIP, USB, feature, output, initialization, authentication, LED, or rumble packets.

## Turtle Beach IDs used for discovery

- Vendor: `0x10f5`
- Stealth Ultra wireless receiver: `0x7070`
- Stealth Ultra wired controller: `0x7073`

The bridge can parse standard HID gamepad descriptors and already-delivered Microsoft GIP gamepad input payloads. If a receiver exposes only proprietary/unmapped reports, the diagnostic snapshot retains report ID/bytes so hardware behavior can be mapped without guessing.

## Existing semantic regions

All v5.4.0 regions remain controller reachable: launch, global header, league/date navigation, Sports Ticker, score ribbon, player/transport, drawer tabs, Game Center, Match Center, League View, Settings, Coming Up, Team/Player Browse, Special Events, date picker, history/audit, developer tools, modals and global fallback.

## Existing mappings retained

- D-pad / Left Stick: semantic focus navigation
- A: select
- B: back
- X: Play All
- Y: cycle Game Center / League View / Settings
- LB / RB: previous / next
- RT: league radial
- LT: date/scope radial
- Right Stick: contextual scroll / radial selection
- R3: pointer fallback
- Menu/Start: controller help

## Compatibility labels

- RT — League radial
- LT — Date / scope radial
- R3 — Pointer fallback
- Header live-input indicator

## Semantic region inventory

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
