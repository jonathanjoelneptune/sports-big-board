from pathlib import Path
import importlib.util, os, sys, tempfile, types

ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/'sbb'/'current_news_v523.py'
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
TEXT=BACKEND.read_text(encoding='utf-8')

def check(cond,msg):
    if not cond: raise AssertionError(msg)
    print('PASS',msg)

check('VERSION = "5.2.6-sports-ticker-3"' in TEXT,'backend Sports Ticker is v5.2.6')
check('def _collect_live_source_rows()' in TEXT,'manual refresh collects current league news before editorializing')
check('require_openai=True' in TEXT,'manual refresh explicitly requires OpenAI')
check('replace=True' in TEXT and 'fresh_only=True' in TEXT,'manual refresh creates an authoritative fresh edition')
check('parsed.path=="/api/sports-ticker/refresh"' in TEXT,'backend exposes POST /api/sports-ticker/refresh')
check('manualRunning' in TEXT and 'manualCompletedAt' in TEXT,'manual refresh exposes pollable status')
check('id="sportsTickerAiRefreshBtn"' in INDEX,'Dev panel contains RUN SPORTS TICKER AI button')
check('RUN SPORTS TICKER AI' in INDEX,'Dev panel control has operator-facing label')

# Execute the core refresh logic with an isolated fake source/server. No network is used.
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

    old={'title':'Old stale item','eventType':'RESULT','publishedAt':'2026-08-20T00:00:00Z','tickerKey':'old'}
    mod._CACHE={'savedAt':1.0,'source':'OLD','data':[old],'sourceSignature':'old'}
    class Server:
        EDITORIAL_SNAPSHOT={}
        EDITORIAL_SNAPSHOT_LOCK=None
        @staticmethod
        def read_openai_key(): return 'configured-key'
        @staticmethod
        def openai_editorialize_events(rows):
            return [{**r,'eventType':'BREAKING'} for r in rows]
    fresh=[{'title':'Fresh current item','publishedAt':'2026-09-02T18:00:00Z','league':'MLB','source':'ESPN'}]
    ok=mod._refresh(Server,force=True,seed_rows=fresh,replace=True,require_openai=True,fresh_only=True,manual=True)
    check(ok,'manual OpenAI refresh produces an edition')
    check(len(mod._CACHE['data'])==1 and mod._CACHE['data'][0]['title']=='Fresh current item','authoritative manual edition removes stale prior item')
    check(mod._CACHE['source']=='OPENAI_SPORTS_TICKER','manual edition records OpenAI as its source')

    class NoKey(Server):
        @staticmethod
        def read_openai_key(): return ''
    try:
        mod._refresh(NoKey,force=True,seed_rows=fresh,replace=True,require_openai=True,fresh_only=True,manual=True)
    except RuntimeError:
        print('PASS manual AI refresh fails clearly when OpenAI is not configured')
    else:
        raise AssertionError('manual AI refresh must not silently fall back without OpenAI')
