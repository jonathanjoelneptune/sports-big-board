from pathlib import Path
import importlib.util, json, sqlite3, sys, tempfile, types, time
ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/'sbb'/'ribbon_snapshot_v520.py'

# Stub package/day_state so the standalone module can be verified without loading
# the production server in the packaging environment.
pkg=types.ModuleType('sbb');pkg.__path__=[str(ROOT/'sbb')];sys.modules['sbb']=pkg
ds=types.ModuleType('sbb.day_state');ds.engine=lambda:None;sys.modules['sbb.day_state']=ds
spec=importlib.util.spec_from_file_location('sbb.ribbon_snapshot_v520',MOD)
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)

snapshot={
 'ok':True,'version':'5.2.0','engineVersion':'4.7.20','date':'2026-09-01','generatedAt':time.time(),
 'sourceRevision':'abc','registryRevision':5,
 'scoreRowsByLeague':{'MLB':[{'eventId':'1','competitionId':'MLB'}],'USOPEN-2026':[{'eventId':'2','sportId':'tennis'}]},
 'eventPlans':{'MLB:1':{'playable':[{'youtubeId':'x','verifiedPlayable':True}]}},
 'scoreGameCount':2,'scoreInventoryComplete':True,
 'summary':{'games':2,'playable':1,'live':0,'final':2,'scheduled':0},
}
projected=mod._project(snapshot)
assert projected['ribbonSnapshotVersion']==mod.VERSION
assert projected['scoreRowsByLeague']==snapshot['scoreRowsByLeague']
assert projected['eventPlans']==snapshot['eventPlans']
assert projected['ribbonRevision']

with tempfile.TemporaryDirectory() as td:
    store=mod.RibbonSnapshotStore(Path(td)/'ribbon.sqlite3')
    assert store.put(projected) is True
    assert store.get('2026-09-01')['ribbonRevision']==projected['ribbonRevision']
    assert store.put(projected) is False
    rows=store.status();assert rows and rows[0]['day']=='2026-09-01'

source=MOD.read_text()
assert 'engine.get(day, allow_build=False)' in source
assert 'allow_build=True' not in source, 'RibbonSnapshot request path must never build Day State'
assert '/api/ribbon-snapshot' in source
assert 'time.sleep' not in source[source.find('def _serve'):source.find('def _install_into_server')]
print('PASS v5.2.0 backend-prepared RibbonSnapshot invariants')
