# Sports Big Board v5.1.19 — Canonical Read-Model Consolidation

v5.1.19 is a consolidation release. It removes the competing v5.1.18 score/date
and tennis runtime authorities instead of adding another wrapper around them.

## Runtime ownership

```text
Competition Registry
        |
providers / Competition Builder / History workers
        |
canonical repositories
        |
DayStateEngine  --------------------> durable Event Media relationships
        |                                      |
        +---- /api/day-state ------------------+
                         |
                    ScoreDateStore
                         |
                    score ribbon
                         |
                   Selected Event
                    /          \
             Media Plan      Game Center
```

### Date and score authority

- `DayStateEngine` is the only backend date read model.
- `ScoreDateStore` is the browser cache for canonical Day State rows. Its legacy
  public `version` remains `1.1` for retained test/consumer compatibility while
  `architectureVersion=1.3-v5119` identifies the consolidated implementation.
- A transport explicitly marked preview/thin/score-only cannot enter `ScoreDateStore`.
- A canonical compact Day State projection may enter the store, but it merges into
  the resident Event by stable provider aliases/fingerprint and cannot strip richer
  event metadata or the separate date/competition media cache.
- An empty response cannot erase populated canonical rows unless the producer
  explicitly marks the league/day confirmed empty.
- Repeated canonical rows merge by stable Event identity, so new scores/status do
  not strip richer resident event metadata.
- Browser localStorage is not an event authority.

### Media authority

- Media remains owned by the normalized canonical Event relationship in the
  History Repository / Day State event plan.
- A date refresh updates the Event score projection; it does not manufacture a
  second Event with an empty media plan.
- Existing verified/locked media is reused. v5.1.19 performs no blanket media
  rediscovery as part of date navigation.

### Tennis authority

- Competition Registry `sportId=tennis` owns server routing.
- Competition Builder, History Repository, and request identity hints are ordered
  sources for reconstructing the one selected Event.
- ESPN ATP/WTA scoreboards are provider adapters beneath that Event identity.
- Only the selected match may initiate provider work.
- Scoreboard calls are coalesced per tour/date. No whole-tournament Game Center
  prewarm runs at startup, on date navigation, or after a match is selected.
- Completed rich Game Centers may be persisted and reused without provider work.
- Valid v5.1.18 durable tennis Game Centers are migrated once into the stable
  `tennis-game-center.json` cache instead of being refetched.
- `/api/tennis/presentation` is compatibility-only and schedule-only; it performs
  zero provider calls and zero warming.

### Tennis presentation

`architecture/tennis-presentation.js` is the only tennis frontend layer. It is
pure presentation: no fetches, no `ScoreDateStore` writes, and no interval polling.
It owns compact tennis labels (`#rank F. Lastname` when rank is available), round
badges, tennis Game Center vocabulary, and layout-only styling.

Round normalization is explicit. Known rounds display `R1`, `R2`, `R3`, `R16`,
`QF`, `SF`, or `F`; an unresolved generic `Round` value displays no badge rather
than the literal word `ROUND`.

## Retired v5.1.18 runtime paths

The old filenames remain as inert tombstones for incremental/manual deployment
safety, but the v5.1.19 page does not load them:

- `architecture/score-date-stability-v5118.js`
- `architecture/day-state-browser-cache-v5118.js`
- `architecture/tennis-presentation-v5118.js`
- `architecture/tennis-presentation-v5117.js`
- `sbb/day_state_fast_path_v5118.py`

They cannot install a competing authority even if an older cached page requests
one of those files during rollout.

## Release invariants

1. One canonical backend date read model: Day State.
2. One canonical browser score cache: ScoreDateStore.
3. One tennis frontend presentation module.
4. Registry sport identity decides tennis Game Center routing.
5. Score refresh cannot detach an Event from its existing media plan.
6. Final verified media and final rich Game Centers survive refresh/restart.
7. Date navigation initiates no tennis tournament-wide provider work.
8. Generic/unresolved round labels never render as `ROUND`.
