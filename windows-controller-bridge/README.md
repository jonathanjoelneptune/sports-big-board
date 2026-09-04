# Sports Big Board Windows Controller Bridge — v5.4.6

This local helper is for Windows controllers that work in **joy.cpl** but are not exposed by Chrome's Gamepad API. The Turtle Beach Stealth Ultra in 2.4 GHz wireless mode is the initial target.

## Start it

1. Keep the controller connected normally in Windows.
2. Double-click `START-CONTROLLER-BRIDGE.cmd`.
3. Windows builds the tiny helper locally on first launch using the .NET Framework compiler already included with Windows. No administrator rights are required.
4. A Sports Big Board Controller Bridge icon appears in the Windows notification area.
5. Open Sports Big Board. If Chrome asks for **Local Network / loopback access**, choose **Allow**. This permission only lets the page talk to the helper on your own PC.
6. The controller indicator should progress from `NO BRIDGE` to `BR READY` and then `BR LIVE` when you press a controller input.

If the helper is running but the page still says `NO BRIDGE`, click the controller indicator or **RECONNECT BRIDGE** in Settings once. Big Board will run a loopback permission/health probe and reconnect.

The compiled helper is cached at:

`%LOCALAPPDATA%\SportsBigBoard\ControllerBridge\SportsBigBoardControllerBridge.exe`

Run `INSTALL-STARTUP.cmd` if you want the helper to launch automatically when you sign in to Windows. `REMOVE-STARTUP.cmd` removes that shortcut.

## Transport and privacy

The helper:

- listens only on `127.0.0.1:5410`;
- accepts the Sports Big Board GitHub Pages origin and localhost development origins;
- reads controller input only;
- never sends rumble, firmware, authentication, HID output, or other commands to the controller;
- sends only normalized buttons, triggers, D-pad and stick positions to the browser on the same PC;
- accepts only two local browser-to-bridge shortcut commands: `app-fullscreen` (F11) and `video-fullscreen` (F);
- does not make outbound internet connections.
- makes no outbound internet connections.

The site still prefers Chrome's standard Gamepad API whenever Chrome exposes a controller. The local bridge is the second transport; WebHID remains the diagnostic/fallback third transport.

## Windows input paths

The bridge tries **XInput first**. This is the expected path for Xbox-compatible controllers such as the Stealth Ultra. If XInput is unavailable for a device, it falls back to the classic Windows multimedia joystick API (`joyGetPosEx`), which is close to the input path demonstrated by `joy.cpl`.

## Troubleshooting

- `NO BRIDGE`: run `START-CONTROLLER-BRIDGE.cmd`.
- `BRIDGE`: helper is running but Windows controller input is not currently found.
- `BR READY`: helper and controller are both detected.
- `BR LIVE`: Sports Big Board is receiving active controller input.

Right-click the tray icon and choose **Copy bridge status** for diagnostics.

## v5.4.6 fullscreen command whitelist

The bridge remains loopback-only and origin-restricted. v5.4.6 adds exactly two browser-to-bridge commands so controller input can invoke browser/video fullscreen even though Chromium does not count Gamepad/WebSocket polling as trusted user activation:

- `app-fullscreen` — sends F11 to the active browser window.
- `video-fullscreen` — sends F, matching Sports Big Board's existing video-fullscreen keyboard shortcut.

No arbitrary key injection command is exposed. Unknown commands are ignored. The bridge still has no outbound internet connection and sends no output, rumble, firmware, or authentication data to the controller.


## v5.4.6 fullscreen shortcuts

Controller-originated browser fullscreen requests do not count as a trusted browser click. To make the LT+RT Special Commands wheel useful, the bridge accepts only two whitelisted local commands from Sports Big Board:

- `app-fullscreen` -> taps F11 in the active Windows browser
- `video-fullscreen` -> taps F, using Big Board's existing video-fullscreen shortcut

No arbitrary key command is accepted, and these commands never send data or commands to the controller itself.
