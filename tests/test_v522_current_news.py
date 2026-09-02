from pathlib import Path
import importlib.util, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('current_news_v522',ROOT/'sbb/current_news_v522.py')
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
article={'headline':'Test sports headline','description':'Update','published':'2026-09-02T12:00:00Z','links':{'web':{'href':'https://example.com'}}}
row=mod._normalize_article(article,'MLB')
assert row['title']=='Test sports headline' and row['league']=='MLB' and row['eventType']=='NEWS'
assert row['verifiedPlayable'] is False
src=(ROOT/'sbb/current_news_v522.py').read_text()
assert '/api/current-news' in src
assert 'threading.Thread(target=_refresh_fallback' in src
assert 'urlopen' not in src[src.find('def do_GET'):src.find('Handler.do_GET = do_GET')], 'interactive endpoint cannot fetch news network'
print('PASS v5.2.2 cache-only current-news backend')
