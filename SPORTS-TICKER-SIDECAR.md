# Sports Ticker Sidecar — Phase A

Phase A is intentionally independent of the current Sports Big Board
application and controller development.

## Isolation boundary

This package adds only new files:

- `.github/workflows/sports-ticker-refresh.yml`
- `tools/refresh_sports_ticker.py`
- `data/sports-ticker.json`
- `data/sports-ticker.txt`
- `SPORTS-TICKER-SIDECAR.md`

It does **not** modify:

- `VERSION`
- `architecture/VERSION`
- `VERIFY.sh`
- `index.html`
- `app.js`
- `sbb/`
- `ui/`
- `architecture/`
- controller files
- backend files
- current Sports Ticker rendering

The website will be wired to `data/sports-ticker.json` later as a separate
Phase B release.

## Schedule

GitHub Actions refreshes at:

- `:07`
- `:27`
- `:47`

of every hour.

That is exactly every 20 minutes and avoids the busiest top-of-hour scheduling
window.

The workflow also supports manual **Run workflow** execution.

## Required secret

Create this repository secret:

`OPENAI_API_KEY`

GitHub path:

`Settings > Secrets and variables > Actions > New repository secret`

## Optional model variable

You may optionally create the repository variable:

`SPORTS_TICKER_MODEL`

If it is not set, the workflow uses:

`gpt-5.6-luna`

## Output

The generator writes:

- `data/sports-ticker.json` — machine-readable authoritative dataset
- `data/sports-ticker.txt` — human-readable view generated from the same data

The base league set is:

- MLB
- NFL
- NBA
- NHL
- EPL
- MLS
- NCAAF

The generator may also create Special Event groups when a major event is
currently active.

## Editorial behavior

The generator targets up to 10 high-value items per league and prioritizes:

- breaking news
- results and upsets
- trades and signings
- injuries and returns
- records and record chases
- milestones
- streaks and slumps
- rankings
- playoff and standings movement
- awards
- stat leaders
- contracts
- suspensions
- coaching changes
- major schedule developments
- important upcoming events

It is explicitly instructed not to merely summarize the ten newest articles.

## Commit behavior

Every scheduled run performs fresh research.

If the semantic ticker content is unchanged, neither data file is rewritten and
no commit is created.

If meaningful content changes:

1. both data files are regenerated;
2. the workflow stages only those two paths;
3. it commits the data-only change;
4. it fetches/rebases onto the newest `main`;
5. it pushes without force.

This is designed to coexist with controller work happening in parallel.

## Failure behavior

If web research/API access fails, JSON is malformed, required league coverage
is missing, source URLs are invalid, or validation fails, the existing cache is
left untouched.

During Phase A, the website does not read the cache, so a sidecar failure cannot
break current Sports Big Board behavior.
