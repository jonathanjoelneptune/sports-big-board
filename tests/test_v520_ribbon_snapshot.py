from pathlib import Path
import importlib.util, sys, tempfile, types, time
ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/'sbb'/'ribbon_snapshot_v520.py'
pkg=types.ModuleType('sbb');pkg.__path__=[str(ROOT/'sbb')];sys.modules['sbb']=pkg
ds=types.ModuleType('sbb.day_state');ds.engine=lambda:None;sys.modules['sbb.day_state']=ds
spec=importlib.util.spec_from_file_location('sbb.ribbon_snapshot_v520',MOD)
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)

def snap(day,eid):
    return mod._project({'ok':True,'version':'5.2.2','engineVersion':'x','date':day,'generatedAt':time.time(),'sourceRevision':eid,'registryRevision':5,'scoreRowsByLeague':{'MLB':[{'eventId':eid,'competitionId':'MLB'}]},'eventPlans':{f'MLB:{eid}':{'playable':[{'youtubeId':'x','verifiedPlayable':True}]}},'scoreGameCount':1,'scoreInventoryComplete':True,'summary':{'games':1,'playable':1,'live':0,'final':1,'scheduled':0}})

with tempfile.TemporaryDirectory() as td:
    store=mod.RibbonSnapshotStore(Path(td)/'ribbon.sqlite3')
    a=snap('2026-09-01','a');b=snap('2026-08-31','b')
    assert store.put(a) is True and store.put(b) is True
    assert store.get('2026-09-01')['ribbonRevision']==a['ribbonRevision']
    many=store.get_many(['2026-08-31','2026-09-01','2026-08-30'])
    assert set(many)=={'2026-08-31','2026-09-01'}
    assert store.put(a) is False
source=MOD.read_text()
assert 'engine.get(day, allow_build=False)' in source
assert 'allow_build=True' not in source
assert '/api/ribbon-snapshot/bundle' in source
assert 'threading.Thread(target=_startup_prime_recent' in source
print('PASS v5.2.2 prepared recent RibbonSnapshot bank')
