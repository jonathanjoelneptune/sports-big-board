from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text(encoding='utf-8')
assert version=='5.2.7',version
for token in [f'app.js?v={version}',f'architecture/dev-mode.js?v={version}',f'architecture/milestone-console.js?v={version}',f'architecture/key-info-current-v520.js?v={version}',f'Sports Big Board — v{version}']:
    assert token in index,token
assert 'sportsTickerAiRefreshBtn' in index
assert 'sportsTickerSpeed' in index
assert 'sportsTickerCopyTuningBtn' in index
assert 'devModeToggleBtn' not in index
print('PASS v5.2.7 release/frontend handshake tokens are aligned')
