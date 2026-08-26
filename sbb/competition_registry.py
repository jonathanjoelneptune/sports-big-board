"""Canonical competition/provider registry shared by server services (v4.2.1).

Competition definitions describe capabilities, not playback implementations. Media
providers are ordered discovery adapters; the EventMediaResolver remains free to
choose a different provider per requested package.
"""
from copy import deepcopy

COMPETITIONS = {
    "MLB":{"id":"MLB","sportId":"baseball","name":"Major League Baseball","enabled":True,"scoreProvider":"highlightly","mediaProviders":["mlb-stats","espn","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"mlb-stats"},
    "NFL":{"id":"NFL","sportId":"american-football","name":"National Football League","enabled":True,"scoreProvider":"espn","mediaProviders":["nfl-youtube-playlist","nfl-public-video","nfl-team-video","espn","nfl-feed","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "NBA":{"id":"NBA","sportId":"basketball","name":"National Basketball Association","enabled":True,"scoreProvider":"espn","mediaProviders":["espn","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "NHL":{"id":"NHL","sportId":"ice-hockey","name":"National Hockey League","enabled":True,"scoreProvider":"espn","mediaProviders":["nhl-official","espn","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "EPL":{"id":"EPL","sportId":"football","name":"Premier League","enabled":True,"scoreProvider":"espn","mediaProviders":["epl-youtube-pl","epl-youtube-nbc-extended","premierleague-official","nbc-epl-extended","espn","club-sites","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "MLS":{"id":"MLS","sportId":"football","name":"Major League Soccer","enabled":True,"scoreProvider":"espn","mediaProviders":["mls-official-web","mls","espn","club-sites","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "UCL":{"id":"UCL","sportId":"football","name":"UEFA Champions League","enabled":False},
    "ATP":{"id":"ATP","sportId":"tennis","name":"ATP Tour","enabled":False},
    "WTA":{"id":"WTA","sportId":"tennis","name":"WTA Tour","enabled":False},
    "F1":{"id":"F1","sportId":"motorsport","name":"Formula 1","enabled":False},
    "XGAMES":{"id":"XGAMES","sportId":"action-sports","name":"X Games","enabled":False},
    "TRACK":{"id":"TRACK","sportId":"athletics","name":"Track & Field","enabled":False},
}

def catalog():
    return [deepcopy(v) for v in COMPETITIONS.values()]

def enabled_ids():
    return [k for k,v in COMPETITIONS.items() if v.get("enabled")]
