from pathlib import Path
p=Path('sbb/current_news_v523.py').read_text()
assert '5.2.4-sports-ticker-1' in p
assert '_REFRESH_SECONDS = 20 * 60' in p
assert '"/api/sports-ticker"' in p
assert '_MAX_ROWS = 150' in p
assert 'stale is always better than blank' in p
assert 'OPENAI_SPORTS_TICKER' in p
print('PASS v5.2.4 persisted Sports Ticker backend invariants')
