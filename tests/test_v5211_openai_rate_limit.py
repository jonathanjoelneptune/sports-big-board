#!/usr/bin/env python3
"""Static release invariants for the v5.2.11 Sports Ticker OpenAI limiter."""
from pathlib import Path

root=Path(__file__).resolve().parents[1]
backend=(root/'sbb/current_news_v523.py').read_text(encoding='utf-8')
frontend=(root/'architecture/key-info-current-v520.js').read_text(encoding='utf-8')

checks={
    'ticker backend version': '5.2.11-sports-ticker-4' in backend,
    '20-record paced batches': '_OPENAI_BATCH_SIZE = 20' in backend and '_OPENAI_BATCH_PACE_SECONDS = 2.5' in backend,
    'manual run <= 2 batches': '_OPENAI_MAX_CANDIDATES_MANUAL = 40' in backend,
    'automatic run <= 1 batch': '_OPENAI_MAX_CANDIDATES_AUTO = 20' in backend,
    'bounded retry count': '_OPENAI_MAX_ATTEMPTS = 3' in backend,
    'retry-after honored': 'Retry-After' in backend and '_retry_after_seconds' in backend,
    'exponential backoff jitter': '2**(attempt-1)' in backend and 'random.uniform' in backend,
    'quota errors are nonretryable': 'credit_balance_exhausted' in backend and 'insufficient_quota' in backend,
    'last-good ticker protected': backend.count('Last-good Sports Ticker retained') >= 2,
    'cooldown blocks hammering': 'openaiCooldownUntil' in backend and 'Try again in' in backend,
    'legacy request storm removed': 'editor(raw[:160])' not in backend,
    'OpenAI calls serialized': 'EDITORIAL_REFRESH_LOCK' in backend,
    'operator sees retry countdown': 'OpenAI rate limited • retrying in' in frontend,
    'operator timeout allows bounded backoff': 'attempt<240' in frontend,
}
failed=[name for name,ok in checks.items() if not ok]
if failed:
    print('FAIL v5.2.11 OpenAI Sports Ticker rate-limit invariants')
    for name in failed: print(' -',name)
    raise SystemExit(1)
print('PASS v5.2.11 OpenAI Sports Ticker rate-limit invariants')
