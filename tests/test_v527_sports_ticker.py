from pathlib import Path
import importlib.util, os, sys, tempfile, types

ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/'sbb'/'current_news_v523.py'
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
TEXT=BACKEND.read_text(encoding='utf-8')
DEV=(ROOT/'architecture'/'dev-mode.js').read_text(encoding='utf-8')
TICKER=(ROOT/'architecture'/'key-info-current-v520.js').read_text(encoding='utf-8')

def check(cond,msg):
    if not cond: raise AssertionError(msg)
    print('PASS',msg)

check('Sports Big Board — v5.2.7' in INDEX,'frontend title is v5.2.7')
check('architecture/dev-mode.js?v=5.2.7' in INDEX,'v5.2.7 global Dev authority is cache-busted')
check('architecture/key-info-current-v520.js?v=5.2.7' in INDEX,'v5.2.7 Sports Ticker is cache-busted')
check('Sports Ticker Dev Utility' in INDEX,'dedicated Sports Ticker Dev Utility is present')
check('id="devModeToggleBtn"' not in INDEX,'no second Dev Mode switch exists inside Settings')
for control in ['sportsTickerHeight','sportsTickerFontSize','sportsTickerLines','sportsTickerSpeed','sportsTickerGap','sportsTickerPauseBtn','sportsTickerCopyTuningBtn','sportsTickerAiRefreshBtn']:
    check(f'id="{control}"' in INDEX,f'{control} exists')
check("const CLICK_TARGET=5" in DEV and "brand-five-click" in DEV,'five-click logo gesture controls global Dev Mode')
check('for(const node of [root,body])' in DEV and "node.dataset.sbbDev='1'" in DEV,'Dev state is unified on html and body')
check("engine:'RAF_CONTINUOUS'" in TICKER,'continuous ticker engine is active')
check('conveyorGroup.animate(' not in TICKER,'per-story animation restart engine is retired')
check('speed:30' in TICKER,'default ticker speed is reduced to 30 px/s')
check('COPY TUNING VALUES' in INDEX,'operator can copy chosen tuning values')

# Backend OpenAI operator refresh remains intact from v5.2.6.
check('def _collect_live_source_rows()' in TEXT,'manual refresh still collects current league news before editorializing')
check('require_openai=True' in TEXT,'manual refresh still explicitly requires OpenAI')
check('parsed.path=="/api/sports-ticker/refresh"' in TEXT,'backend still exposes POST /api/sports-ticker/refresh')

# Execute the core backend refresh logic with an isolated fake source/server. No network is used.
with tempfile.TemporaryDirectory() as td:
    os.environ['SBB_STATE_DIR']=td
    pkg=types.ModuleType('sbb');pkg.__path__=[];sys.modules['sbb']=pkg
    src=types.ModuleType('sbb.current_news_v522')
    src._desk_rows=lambda server: []
    src._rows=lambda server: ([], 'EMPTY')
    src._FEEDS={}
    sys.modules['sbb.current_news_v522']=src
    spec=importlib.util.spec_from_file_location('sbb.current_news_v523',BACKEND)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    class Server:
        EDITORIAL_SNAPSHOT={}
        EDITORIAL_SNAPSHOT_LOCK=None
        @staticmethod
        def read_openai_key(): return 'configured-key'
        @staticmethod
        def openai_editorialize_events(rows): return [{**r,'eventType':'BREAKING'} for r in rows]
    fresh=[{'title':'Fresh current item','publishedAt':'2026-09-02T18:00:00Z','league':'MLB','source':'ESPN'}]
    ok=mod._refresh(Server,force=True,seed_rows=fresh,replace=True,require_openai=True,fresh_only=True,manual=True)
    check(ok,'manual OpenAI refresh still produces an authoritative edition')
