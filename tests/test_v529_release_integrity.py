#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.2.9', VERSION
assert (ROOT/'architecture'/'VERSION').read_text().strip()==VERSION

index=(ROOT/'index.html').read_text()
assert f'<title>Sports Big Board — v{VERSION}</title>' in index
assert f'<meta name="sbb-release-version" content="{VERSION}"' in index
assert 'window.SBB_RELEASE_VERSION=version' in index
assert 'window.SBB_RELEASE=Object.freeze' in index
assert 'sbbLegacyCoreReleaseProjection' in index
assert 'class="settings-card sports-ticker-dev-card"' in index
assert 'sports-ticker-dev-card sbb-dev-global-card' not in index
assert 'sports-ticker-dev-card" data-sbb-dev-only' not in index
assert 'id="settingsFrontendVersion"' in index
assert 'id="settingsBackendVersion"' in index
assert 'id="settingsReleaseMatch"' in index
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==VERSION,(asset,found,VERSION)

settings=(ROOT/'ui'/'settings-view.js').read_text()
assert 'window.SBB_RELEASE_VERSION=' not in settings
assert 'window.SBB_CORE=Object.freeze' not in settings
assert 'window.SBB_RELEASE?.version||window.SBB_RELEASE_VERSION' in settings
assert '/api/release-identity?frontendVersion=' in settings
assert 'settingsReleaseMatch' in settings

backend=(ROOT/'sbb'/'release_identity_v523.py').read_text()
assert 'VERSION = (ROOT / "VERSION").read_text' in backend
assert not re.search(r'^VERSION\s*=\s*["\']\d+\.\d+\.\d+["\']',backend,re.M)

ticker=(ROOT/'architecture'/'key-info-current-v520.js').read_text()
assert "const VERSION='5.2.9'" in ticker
assert '.sports-ticker-dev-card{display:block!important}' in ticker
assert "card.className='settings-card sports-ticker-dev-card'" in ticker
assert 'RUN SPORTS TICKER AI' in ticker

verify=(ROOT/'VERIFY.sh').read_text()
assert 'tools/check_release_version.py' in verify
assert 'tests/test_v529_release_integrity.py' in verify
assert not re.search(r'^exit\s+0\s*$',verify,re.M)

print('PASS v5.2.9 atomic release identity + always-visible ticker utility')
