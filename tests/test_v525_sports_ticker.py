import importlib.util
import pathlib
import sys
import types
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
MODULE=ROOT/'sbb'/'current_news_v523.py'

# The release package intentionally contains changed files only. Stub the unchanged
# v5.2.2 source module so the v5.2.5 merge helpers can be exercised in isolation.
pkg=types.ModuleType('sbb');pkg.__path__=[]
src=types.ModuleType('sbb.current_news_v522')
src._desk_rows=lambda server: []
src._rows=lambda server: ([], 'EMPTY')
sys.modules.setdefault('sbb',pkg)
sys.modules.setdefault('sbb.current_news_v522',src)
spec=importlib.util.spec_from_file_location('sbb.current_news_v523',MODULE)
mod=importlib.util.module_from_spec(spec);sys.modules['sbb.current_news_v523']=mod;spec.loader.exec_module(mod)

class SportsTickerV525Tests(unittest.TestCase):
    def test_refresh_interval_and_capacity(self):
        self.assertEqual(mod._REFRESH_SECONDS,20*60)
        self.assertEqual(mod._MAX_ROWS,150)
        self.assertEqual(mod.VERSION,'5.2.5-sports-ticker-2')

    def test_new_items_prepend_without_reordering_existing(self):
        old=[
            {'title':'Older A','eventType':'NEWS','tickerKey':'a','firstSeenAt':1},
            {'title':'Older B','eventType':'NEWS','tickerKey':'b','firstSeenAt':2},
        ]
        fresh=[
            {'title':'Brand New','eventType':'NEWS','tickerKey':'n'},
            {'title':'Older B','eventType':'NEWS','tickerKey':'b','source':'updated'},
            {'title':'Older A','eventType':'NEWS','tickerKey':'a'},
        ]
        rows,count=mod._merge_new_first(fresh,old,now=100)
        self.assertEqual(count,1)
        self.assertEqual([r['tickerKey'] for r in rows],['n','a','b'])
        self.assertEqual(rows[0]['firstSeenAt'],100)
        self.assertEqual(rows[2]['source'],'updated')

    def test_normalize_orders_fresh_candidates_by_time_then_importance(self):
        rows=mod._normalize([
            {'title':'Team clinched playoff berth','publishedAt':'2026-09-02T10:00:00Z'},
            {'title':'Coach fired after loss','publishedAt':'2026-09-02T11:00:00Z'},
        ],'RULES')
        self.assertEqual(rows[0]['title'],'Coach fired after loss')
        self.assertTrue(all(r.get('tickerKey') for r in rows))

    def test_state_file_migrates_from_v524(self):
        text=MODULE.read_text()
        self.assertIn('sports-ticker.json',text)
        self.assertIn('sports-ticker-v524.json',text)
        self.assertIn('NEW_FIRST_STABLE',text)

if __name__=='__main__':unittest.main()
