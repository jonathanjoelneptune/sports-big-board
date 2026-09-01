import importlib.util,json,sqlite3,tempfile,unittest,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class V5110(unittest.TestCase):
 def test_tombstones_and_init(self):
  init=(ROOT/'sbb/__init__.py').read_text();self.assertIn('ncaaf_ranked',init);self.assertNotIn('_install_cfb_trusted_youtube',init);self.assertNotIn('_install_game_center_runtime_v508',init)
  for name in ('cfb_ranked.py','cfb_trusted_youtube.py','game_center_runtime_v4721.py','game_center_runtime_v508.py'):
   self.assertIn('RETIRED=True',(ROOT/'sbb'/name).read_text())
 def test_ncaaf_provider_is_fresh_namespace(self):
  src=(ROOT/'sbb/ncaaf_ranked.py').read_text();self.assertIn("COMPETITION_ID='NCAAF'",src);self.assertIn("SEASON_ID='NCAAF2026'",src);self.assertIn("ncaaf-ranked-{SEASON}.json",src);self.assertNotIn("COMPETITION_ID='CFB'",src);self.assertIn("'/api/ncaaf/rankings'",src)
 def test_purge_sqlite(self):
  src=ROOT/'sbb/ncaaf_namespace_reset.py';spec=importlib.util.spec_from_file_location('reset',src);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'history.db';c=sqlite3.connect(p);c.execute('create table history_catalog_event(league text,event_id text)');c.executemany('insert into history_catalog_event values(?,?)',[('CFB','x'),('NCAAF','y'),('MLB','z')]);c.execute('create table history_event_media(canonical_event_key text,asset_key text)');c.executemany('insert into history_event_media values(?,?)',[('CFB:2026:x','a'),('NCAAF:2026:y','b')]);c.commit();c.close();r=m._purge_sqlite(p);self.assertGreaterEqual(r['rows'],2);c=sqlite3.connect(p);self.assertEqual(c.execute("select count(*) from history_catalog_event where league='CFB'").fetchone()[0],0);self.assertEqual(c.execute("select count(*) from history_catalog_event where league='NCAAF'").fetchone()[0],1);self.assertEqual(c.execute("select count(*) from history_event_media where canonical_event_key like 'CFB:%'").fetchone()[0],0);c.close()
if __name__=='__main__':unittest.main()
