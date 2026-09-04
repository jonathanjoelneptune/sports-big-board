# Sports Big Board v5.4.7 Windows Controller Bridge R1

R1 fixes bridge self-update on Windows. The original launcher could attempt to compile directly over the cached `SportsBigBoardControllerBridge.exe` while the previous bridge process was still running, which produced compiler error CS0016 (file in use).

## Install / update

1. Extract this ZIP to its own folder. Do not run the launcher from an older v5.4.4/v5.4.6 bridge folder.
2. Double-click `START-CONTROLLER-BRIDGE.cmd`.
3. If an older Sports Big Board Controller Bridge is running, R1 automatically stops it before rebuilding.
4. The bridge is compiled to a temporary EXE first, then safely replaces the cached EXE and starts it.
5. Return to Sports Big Board. The controller indicator should progress to `BR READY` / `BR LIVE` when the local bridge owns input.

The bridge remains loopback-only and the keyboard-command whitelist remains limited to app fullscreen (F11) and video fullscreen (F).

## If Windows still reports the EXE is locked

Open Task Manager and end `SportsBigBoardControllerBridge.exe`, then run `START-CONTROLLER-BRIDGE.cmd` again. You can also run this from Command Prompt:

`taskkill /F /IM SportsBigBoardControllerBridge.exe`

## Optional startup integration
- `INSTALL-STARTUP.cmd` installs the controller bridge launcher for user login startup.
- `REMOVE-STARTUP.cmd` removes that startup integration.
- Local bridge endpoint: `ws://127.0.0.1:5410/sbb-controller`.
