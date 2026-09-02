from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
arch=(ROOT/'architecture'/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text(encoding='utf-8')
assert version=='5.2.8',version
assert arch==version,(arch,version)
assert '5.2.7' not in index
for token in [
    f'Sports Big Board — v{version}',
    f'app.js?v={version}',
    f'architecture/dev-mode.js?v={version}',
    f'architecture/milestone-console.js?v={version}',
    f'architecture/key-info-current-v520.js?v={version}',
]:
    assert token in index,token
for control in ['sportsTickerHeight','sportsTickerFontSize','sportsTickerLines','sportsTickerSpeed','sportsTickerGap','sportsTickerAiRefreshBtn']:
    assert f'id="{control}"' in index,control
assert 'id="devModeToggleBtn"' not in index
print('PASS v5.2.8 release/frontend handshake and Sports Ticker utility tokens are aligned')
