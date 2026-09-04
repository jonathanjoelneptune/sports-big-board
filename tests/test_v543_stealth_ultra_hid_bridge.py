#!/usr/bin/env python3
"""v5.4.5 controller fallback: WebHID bridge + Turtle Beach wireless diagnostics."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
parts=tuple(int(x) for x in VERSION.split('.'))
assert parts >= (5,4,3), VERSION
index=(ROOT/'index.html').read_text()
core=(ROOT/'architecture'/'controller-mode-v542.js').read_text()
hid=(ROOT/'architecture'/'controller-hid-bridge-v543.js').read_text()
css=(ROOT/'ui'/'controller-hid-bridge-v543.css').read_text()

assert f'ui/controller-hid-bridge-v543.css?v={VERSION}' in index
assert f'architecture/controller-hid-bridge-v543.js?v={VERSION}' in index
assert index.index(f'architecture/controller-hid-bridge-v543.js?v={VERSION}') < index.index(f'architecture/controller-mode-v542.js?v={VERSION}')
assert 'id="controllerLiveIndicator"' in index and '<button id="controllerLiveIndicator"' in index
assert 'id="controllerHidPairBtn"' in index and 'PAIR WIRELESS CONTROLLER' in index
assert 'id="controllerHidStatus"' in index

# WebHID security/permission model: requestDevice only from explicit UI action;
# prior grants are recovered with getDevices for future zero-prompt reconnect.
assert 'navigator.hid.requestDevice' in hid
assert 'navigator.hid.getDevices' in hid
assert 'controllerHidPairBtn' in hid
assert 'TURTLE_BEACH_VENDOR_ID=0x10f5' in hid
assert 'STEALTH_ULTRA_WIRELESS_PID=0x7070' in hid
assert 'STEALTH_ULTRA_WIRED_PID=0x7073' in hid
assert "addEventListener?.('inputreport',onInputReport)" in hid
assert 'parseGip' in hid and 'bytes[0]===0x20' in hid
assert 'parseGenericHid' in hid
assert 'lastParser' in hid and 'lastBytes' in hid and 'reportCount' in hid
# Read-only diagnostic/input bridge: never send protocol/output packets from a browser.
for forbidden in ('sendReport(', 'sendFeatureReport(', 'receiveFeatureReport(', 'navigator.usb.requestDevice'):
    assert forbidden not in hid, forbidden

# Existing controller engine consumes the synthetic HID gamepad without duplicating
# D-pad/radial/pointer behavior in the HID layer.
assert 'SBB_CONTROLLER_HID_BRIDGE' in core
assert 'const hid=hidGamepad();return hid?[hid]:[];' in core
assert "state:'hid-ready'" in core and "'hid-live'" in core
assert "document.addEventListener('sbb:controller-hid-change'" in core
assert 'controllerHidPairBtn' in index
assert 'hidApiAvailable' in core
assert '[data-state="hid-pair"]' in css and '[data-state="hid-live"]' in css
print(f'PASS v{VERSION} Turtle Beach/WebHID fallback + diagnostic controller bridge')
