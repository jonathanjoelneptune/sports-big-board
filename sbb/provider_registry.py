"""Provider routing registry for v4.1.30.

SCORE_API retains the existing Highlightly adapter metadata. MEDIA_ADAPTERS is the
new provider-independent capability registry consumed by architecture diagnostics
and future resolver/server orchestration.
"""
BASE_URL="https://sports.highlightly.net"
SPORT_API={
    "mlb":{"competitionId":"MLB","league":"MLB","base":BASE_URL,"prefix":"/baseball","matchParam":"league","highlightParam":"leagueName"},
    "nba":{"competitionId":"NBA","league":"NBA","base":"https://nba.highlightly.net","prefix":"","matchParam":"league","highlightParam":"leagueName"},
    "nfl":{"competitionId":"NFL","league":"NFL","base":"https://american-football.highlightly.net","prefix":"","matchParam":"league","highlightParam":"leagueName"},
    "nhl":{"competitionId":"NHL","league":"NHL","base":"https://nhl.highlightly.net","prefix":"","matchParam":"league","highlightParam":"leagueName"},
    "epl":{"competitionId":"EPL","league":"Premier League","base":"https://soccer.highlightly.net","prefix":"","matchParam":"leagueName","highlightParam":"leagueName","countryCode":"GB","rapidHost":"football-highlights-api.p.rapidapi.com"},
    "mls":{"competitionId":"MLS","league":"Major League Soccer","base":"https://soccer.highlightly.net","prefix":"","matchParam":"leagueName","highlightParam":"leagueName","countryCode":"US","rapidHost":"football-highlights-api.p.rapidapi.com"},
}

MEDIA_ADAPTERS={
    "mlb-stats":{"kind":"official-api","transport":["DIRECT_VIDEO"],"competitions":["MLB"],"reliability":100},
    "espn":{"kind":"broadcaster-api","transport":["DIRECT_VIDEO"],"competitions":["MLB","NFL","NBA","NHL","EPL","MLS"],"reliability":94},
    "nfl-youtube-playlist":{"kind":"official-youtube-playlist","transport":["YOUTUBE"],"competitions":["NFL"],"reliability":100},
    "nfl-youtube-playlist-quick":{"kind":"official-youtube-playlist","transport":["YOUTUBE"],"competitions":["NFL"],"reliability":100},
    "nfl-youtube-playlist-extended":{"kind":"official-youtube-playlist","transport":["YOUTUBE"],"competitions":["NFL"],"reliability":100},
    "nfl-public-video":{"kind":"official-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["NFL"],"reliability":100},
    "nfl-team-video":{"kind":"official-team-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["NFL"],"reliability":99},
    "nfl-public-video-quick":{"kind":"official-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["NFL"],"reliability":100},
    "nfl-public-video-extended":{"kind":"official-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["NFL"],"reliability":100},
    "nfl-team-video-quick":{"kind":"official-team-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["NFL"],"reliability":99},
    "nfl-team-video-extended":{"kind":"official-team-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["NFL"],"reliability":99},
    "nfl-club":{"kind":"official-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["NFL"],"reliability":96},
    "nfl-feed":{"kind":"official-feed","transport":["YOUTUBE_EMBED","EXTERNAL"],"competitions":["NFL"],"reliability":92},
    "nhl-official":{"kind":"official-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["NHL"],"reliability":100},
    "epl-youtube-pl":{"kind":"official-youtube-playlist","transport":["YOUTUBE"],"competitions":["EPL"],"reliability":100},
    "epl-youtube-pl-quick":{"kind":"official-youtube-playlist","transport":["YOUTUBE"],"competitions":["EPL"],"reliability":100},
    "epl-youtube-pl-extended":{"kind":"official-youtube-playlist","transport":["YOUTUBE"],"competitions":["EPL"],"reliability":100},
    "epl-youtube-nbc-extended":{"kind":"trusted-broadcaster-youtube-playlist","transport":["YOUTUBE"],"competitions":["EPL"],"reliability":99},
    "epl-youtube-every-goal":{"kind":"official-youtube-playlist","transport":["YOUTUBE"],"competitions":["EPL"],"reliability":100},
    "premierleague-official":{"kind":"official-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["EPL"],"reliability":100},
    "nbc-epl-extended":{"kind":"trusted-broadcaster-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["EPL"],"reliability":96},
    "mls-official-web":{"kind":"official-web","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["MLS"],"reliability":100},
    "mls":{"kind":"official-api","transport":["DIRECT_VIDEO","EXTERNAL"],"competitions":["MLS"],"reliability":95},
    "club-sites":{"kind":"official-web","transport":["DIRECT_VIDEO","YOUTUBE_EMBED","EXTERNAL"],"competitions":["EPL","MLS"],"reliability":90},
    "highlightly":{"kind":"aggregator-api","transport":["YOUTUBE_EMBED","EXTERNAL"],"competitions":["MLB","NFL","NBA","NHL","EPL","MLS"],"reliability":80},
    "youtube":{"kind":"discovery-api","transport":["YOUTUBE_EMBED","EXTERNAL"],"competitions":["MLB","NFL","NBA","NHL","EPL","MLS"],"reliability":78},
}

def media_adapters_for(competition):
    key=str(competition or "").upper()
    return [name for name,row in MEDIA_ADAPTERS.items() if key in row.get("competitions",[])]
