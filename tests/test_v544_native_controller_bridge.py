#!/usr/bin/env python3
"""v5.4.7 native Windows controller bridge + transport priority regression."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.4.7', VERSION
index=(ROOT/'index.html').read_text()
core=(ROOT/'architecture'/'controller-mode-v542.js').read_text()
bridge=(ROOT/'architecture'/'controller-native-bridge-v544.js').read_text()
css=(ROOT/'ui'/'controller-native-bridge-v544.css').read_text()
cs=(ROOT/'windows-controller-bridge'/'SportsBigBoardControllerBridge.cs').read_text()
ps=(ROOT/'windows-controller-bridge'/'Start-SportsBigBoardControllerBridge.ps1').read_text()
cmd=(ROOT/'windows-controller-bridge'/'START-CONTROLLER-BRIDGE.cmd').read_text()
readme=(ROOT/'windows-controller-bridge'/'README.md').read_text()

# Browser integration and load order.
assert f'ui/controller-native-bridge-v544.css?v={VERSION}' in index
assert f'architecture/controller-native-bridge-v544.js?v={VERSION}' in index
assert index.index('architecture/controller-readiness-v540.js') < index.index('architecture/controller-native-bridge-v544.js') < index.index('architecture/controller-hid-bridge-v543.js') < index.index('architecture/controller-mode-v542.js')
assert 'controllerNativeReconnectBtn' in index and 'controllerNativeBridgeStatus' in index

# Local websocket transport is loopback-only from the browser side and pushes a
# standard synthetic gamepad into the existing semantic controller engine.
assert "ws://127.0.0.1:5410/sbb-controller" in bridge
assert 'SBB_CONTROLLER_NATIVE_BRIDGE' in bridge
assert 'index:-544' in bridge and "mapping:'standard'" in bridge
assert "sbb:controller-native-bridge-change" in bridge
assert 'new WebSocket(endpoint)' in bridge
assert "fetch('http://127.0.0.1:5410/health'" in bridge
assert "targetAddressSpace='loopback'" in bridge

# Strict transport priority: browser Gamepad -> native bridge -> WebHID.
assert 'if(browser.length)return browser;' in core
assert 'const bridged=nativeBridgeGamepad();if(bridged)return [bridged];' in core
assert 'const hid=hidGamepad();return hid?[hid]:[];' in core
assert 'activeIndex===-544' in core
assert "state:'bridge-live'" in core and "state:'bridge-ready'" in core and "state:'no-bridge'" in core
assert "document.addEventListener('sbb:controller-native-bridge-change'" in core

# Windows helper security and controller coverage.
assert 'new TcpListener(IPAddress.Loopback, Port)' in cs
assert 'IPAddress.Any' not in cs
assert 'jonathanjoelneptune.github.io' in cs
assert 'Access-Control-Allow-Private-Network: true' in cs
assert 'XInputGetState' in cs and 'joyGetPosEx' in cs
assert 'xinput1_4.dll' in cs and 'winmm.dll' in cs
assert 'ws://127.0.0.1:' in cs
assert 'SendText(stream' in cs
# Read-only input helper: no controller output/rumble or outbound web client.
for forbidden in ('XInputSetState', 'HttpClient', 'WebClient', 'UdpClient', 'IPAddress.Any'):
    assert forbidden not in cs, forbidden

# One-click local launcher compiles with the Windows .NET Framework compiler;
# no administrator-only install path is required.
assert 'csc.exe' in ps and '/target:winexe' in ps
assert 'LOCALAPPDATA' in ps
assert 'ExecutionPolicy Bypass' in cmd
assert 'INSTALL-STARTUP.cmd' in readme and 'REMOVE-STARTUP.cmd' in readme
assert '127.0.0.1:5410' in readme

assert '[data-state="bridge-live"]' in css and '[data-state="bridge-ready"]' in css and '[data-state="no-bridge"]' in css
print(f'PASS v{VERSION} native Windows controller bridge + Gamepad/bridge/HID transport priority')
