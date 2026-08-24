"""League-level editorial programming definitions for v4.1.8."""
EDITORIAL_SERIES = {
    "MLB_TOP_PLAYS_DAILY": {
        "id":"MLB_TOP_PLAYS_DAILY","competitionId":"MLB","scope":"league",
        "editorialType":"top_plays","cadence":"daily","label":"Top Plays of the Day","preferredSource":"MLB"
    },
    "NBA_TOP_PLAYS_NIGHTLY": {
        "id":"NBA_TOP_PLAYS_NIGHTLY","competitionId":"NBA","scope":"league",
        "editorialType":"top_plays","cadence":"nightly","label":"Top Plays of the Night","preferredSource":"NBA"
    },
    "NFL_TOP_PLAYS_WEEKLY": {
        "id":"NFL_TOP_PLAYS_WEEKLY","competitionId":"NFL","scope":"league",
        "editorialType":"top_plays","cadence":"weekly","label":"Top Plays of the Week","preferredSource":"NFL"
    },
}

def catalog():
    return [dict(v) for v in EDITORIAL_SERIES.values()]
