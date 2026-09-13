"""v6.1.16 R25 operator-supplied authoritative team video-source seeds.

Only rows with an explicit first-party URL are included. Missing/ambiguous rows
remain resolver-owned and are never guessed.
"""
from __future__ import annotations
from collections import Counter

_DATA = r"""\
NBA|Atlanta Hawks|Atlanta Hawks|https://www.nba.com/hawks/videos|VIDEO_INDEX
NBA|Boston Celtics|Boston Celtics|https://www.nba.com/celtics/videos|VIDEO_INDEX
NBA|Charlotte Hornets|Charlotte Hornets|https://www.nba.com/hornets/videos|VIDEO_INDEX
NBA|Chicago Bulls|Chicago Bulls|https://www.nba.com/bulls/videos|VIDEO_INDEX
NBA|Cleveland Cavaliers|Cleveland Cavaliers|https://www.nba.com/cavaliers/videos|VIDEO_INDEX
NBA|Denver Nuggets|Denver Nuggets|https://www.nba.com/nuggets/videos|VIDEO_INDEX
NBA|Detroit Pistons|Detroit Pistons|https://www.nba.com/pistons/videos|VIDEO_INDEX
NBA|Golden State Warriors|Golden State Warriors|https://www.nba.com/warriors/videos|VIDEO_INDEX
NBA|Houston Rockets|Houston Rockets|https://www.nba.com/rockets/videos|VIDEO_INDEX
NBA|Indiana Pacers|Indiana Pacers|https://www.nba.com/pacers/videos|VIDEO_INDEX
NBA|Los Angeles Clippers|Los Angeles Clippers|https://www.nba.com/clippers/videos|VIDEO_INDEX
NBA|Los Angeles Lakers|Los Angeles Lakers|https://www.nba.com/lakers/videos|VIDEO_INDEX
NBA|Memphis Grizzlies|Memphis Grizzlies|https://www.nba.com/grizzlies/videos|VIDEO_INDEX
NBA|Miami Heat|Miami Heat|https://www.nba.com/heat/videos|VIDEO_INDEX
NBA|Milwaukee Bucks|Milwaukee Bucks|https://www.nba.com/bucks/videos|VIDEO_INDEX
NBA|Minnesota Timberwolves|Minnesota Timberwolves|https://www.nba.com/timberwolves/videos|VIDEO_INDEX
NBA|New Orleans Pelicans|New Orleans Pelicans|https://www.nba.com/pelicans/videos|VIDEO_INDEX
NBA|New York Knicks|New York Knicks|https://www.nba.com/knicks/videos|VIDEO_INDEX
NBA|Orlando Magic|Orlando Magic|https://www.nba.com/magic/videos|VIDEO_INDEX
NBA|Philadelphia 76ers|Philadelphia 76ers|https://www.nba.com/sixers/videos|VIDEO_INDEX
NBA|Phoenix Suns|Phoenix Suns|https://www.nba.com/suns/videos|VIDEO_INDEX
NBA|Portland Trail Blazers|Portland Trail Blazers|https://www.nba.com/blazers/videos|VIDEO_INDEX
NBA|Sacramento Kings|Sacramento Kings|https://www.nba.com/kings/videos|VIDEO_INDEX
NBA|San Antonio Spurs|San Antonio Spurs|https://www.nba.com/spurs/videos|VIDEO_INDEX
NBA|Utah Jazz|Utah Jazz|https://www.nba.com/jazz/videos|VIDEO_INDEX
NBA|Washington Wizards|Washington Wizards|https://www.nba.com/wizards/videos|VIDEO_INDEX
NFL|Arizona Cardinals|Arizona Cardinals|https://www.azcardinals.com/video/|VIDEO_INDEX
NFL|Atlanta Falcons|Atlanta Falcons|https://www.atlantafalcons.com/video/|VIDEO_INDEX
NFL|Baltimore Ravens|Baltimore Ravens|https://www.baltimoreravens.com/video/|VIDEO_INDEX
NFL|Buffalo Bills|Buffalo Bills|https://www.buffalobills.com/video/|VIDEO_INDEX
NFL|Carolina Panthers|Carolina Panthers|https://www.panthers.com/video/|VIDEO_INDEX
NFL|Chicago Bears|Chicago Bears|https://www.chicagobears.com/video/|VIDEO_INDEX
NFL|Cincinnati Bengals|Cincinnati Bengals|https://www.bengals.com/video/|VIDEO_INDEX
NFL|Cleveland Browns|Cleveland Browns|https://www.clevelandbrowns.com/video/|VIDEO_INDEX
NFL|Dallas Cowboys|Dallas Cowboys|https://www.dallascowboys.com/video/|VIDEO_INDEX
NFL|Denver Broncos|Denver Broncos|https://www.denverbroncos.com/video/|VIDEO_INDEX
NFL|Detroit Lions|Detroit Lions|https://www.detroitlions.com/video/|VIDEO_INDEX
NFL|Green Bay Packers|Green Bay Packers|https://www.packers.com/video/|VIDEO_INDEX
NFL|Houston Texans|Houston Texans|https://www.houstontexans.com/video/|VIDEO_INDEX
NFL|Indianapolis Colts|Indianapolis Colts|https://www.colts.com/video/|VIDEO_INDEX
NFL|Jacksonville Jaguars|Jacksonville Jaguars|https://www.jaguars.com/video/|VIDEO_INDEX
NFL|Kansas City Chiefs|Kansas City Chiefs|https://www.chiefs.com/video/|VIDEO_INDEX
NFL|Las Vegas Raiders|Las Vegas Raiders|https://www.raiders.com/video/|VIDEO_INDEX
NFL|Los Angeles Chargers|Los Angeles Chargers|https://www.chargers.com/video/|VIDEO_INDEX
NFL|Los Angeles Rams|Los Angeles Rams|https://www.therams.com/video/|VIDEO_INDEX
NFL|Miami Dolphins|Miami Dolphins|https://www.miamidolphins.com/video/|VIDEO_INDEX
NFL|Minnesota Vikings|Minnesota Vikings|https://www.vikings.com/video/|VIDEO_INDEX
NFL|New England Patriots|New England Patriots|https://www.patriots.com/video/|VIDEO_INDEX
NFL|New Orleans Saints|New Orleans Saints|https://www.neworleanssaints.com/video/|VIDEO_INDEX
NFL|New York Giants|New York Giants|https://www.giants.com/video/|VIDEO_INDEX
NFL|New York Jets|New York Jets|https://www.newyorkjets.com/video/|VIDEO_INDEX
NFL|Philadelphia Eagles|Philadelphia Eagles|https://www.philadelphiaeagles.com/video/|VIDEO_INDEX
NFL|Pittsburgh Steelers|Pittsburgh Steelers|https://www.steelers.com/video/|VIDEO_INDEX
NFL|San Francisco 49ers|San Francisco 49ers|https://www.49ers.com/video/highlights/|VIDEO_INDEX
NFL|Seattle Seahawks|Seattle Seahawks|https://www.seahawks.com/video/|VIDEO_INDEX
NFL|Tampa Bay Buccaneers|Tampa Bay Buccaneers|https://www.buccaneers.com/video/|VIDEO_INDEX
NFL|Tennessee Titans|Tennessee Titans|https://www.tennesseetitans.com/video/|VIDEO_INDEX
NFL|Washington Commanders|Washington Commanders|https://www.commanders.com/video/game-highlights|VIDEO_INDEX
MLB|Arizona Diamondbacks|Arizona Diamondbacks|https://www.mlb.com/dbacks/video|VIDEO_INDEX
MLB|Athletics|Athletics|https://www.mlb.com/athletics/video|VIDEO_INDEX
MLB|Atlanta Braves|Atlanta Braves|https://www.mlb.com/braves/video|VIDEO_INDEX
MLB|Baltimore Orioles|Baltimore Orioles|https://www.mlb.com/orioles/video|VIDEO_INDEX
MLB|Boston Red Sox|Boston Red Sox|https://www.mlb.com/redsox/video|VIDEO_INDEX
MLB|Chicago Cubs|Chicago Cubs|https://www.mlb.com/cubs/video|VIDEO_INDEX
MLB|Chicago White Sox|Chicago White Sox|https://www.mlb.com/whitesox/video|VIDEO_INDEX
MLB|Cincinnati Reds|Cincinnati Reds|https://www.mlb.com/reds/video|VIDEO_INDEX
MLB|Cleveland Guardians|Cleveland Guardians|https://www.mlb.com/guardians/video|VIDEO_INDEX
MLB|Colorado Rockies|Colorado Rockies|https://www.mlb.com/rockies/video|VIDEO_INDEX
MLB|Detroit Tigers|Detroit Tigers|https://www.mlb.com/tigers/video|VIDEO_INDEX
MLB|Houston Astros|Houston Astros|https://www.mlb.com/astros/video|VIDEO_INDEX
MLB|Kansas City Royals|Kansas City Royals|https://www.mlb.com/royals/video|VIDEO_INDEX
MLB|Los Angeles Angels|Los Angeles Angels|https://www.mlb.com/angels/video|VIDEO_INDEX
MLB|Los Angeles Dodgers|Los Angeles Dodgers|https://www.mlb.com/dodgers/video|VIDEO_INDEX
MLB|Miami Marlins|Miami Marlins|https://www.mlb.com/marlins/video|VIDEO_INDEX
MLB|Milwaukee Brewers|Milwaukee Brewers|https://www.mlb.com/brewers/video|VIDEO_INDEX
MLB|Minnesota Twins|Minnesota Twins|https://www.mlb.com/twins/video|VIDEO_INDEX
MLB|New York Mets|New York Mets|https://www.mlb.com/mets/video|VIDEO_INDEX
MLB|New York Yankees|New York Yankees|https://www.mlb.com/yankees/video|VIDEO_INDEX
MLB|Philadelphia Phillies|Philadelphia Phillies|https://www.mlb.com/phillies/video|VIDEO_INDEX
MLB|Pittsburgh Pirates|Pittsburgh Pirates|https://www.mlb.com/pirates/video|VIDEO_INDEX
MLB|San Diego Padres|San Diego Padres|https://www.mlb.com/padres/video|VIDEO_INDEX
MLB|San Francisco Giants|San Francisco Giants|https://www.mlb.com/giants/video|VIDEO_INDEX
MLB|Seattle Mariners|Seattle Mariners|https://www.mlb.com/mariners/video|VIDEO_INDEX
MLB|St. Louis Cardinals|St. Louis Cardinals|https://www.mlb.com/cardinals/video|VIDEO_INDEX
MLB|Tampa Bay Rays|Tampa Bay Rays|https://www.mlb.com/rays/video|VIDEO_INDEX
MLB|Texas Rangers|Texas Rangers|https://www.mlb.com/rangers/video|VIDEO_INDEX
MLB|Toronto Blue Jays|Toronto Blue Jays|https://www.mlb.com/bluejays/video|VIDEO_INDEX
MLB|Washington Nationals|Washington Nationals|https://www.mlb.com/nationals/video|VIDEO_INDEX
MLS|Atlanta United FC|Atlanta United FC|https://www.atlutd.com/video/|VIDEO_INDEX
MLS|Austin FC|Austin FC|https://www.austinfc.com/video/|VIDEO_INDEX
MLS|Charlotte FC|Charlotte FC|https://www.charlottefootballclub.com/video/topics/match-highlights/|VIDEO_INDEX
MLS|Chicago Fire FC|Chicago Fire FC|https://www.chicagofirefc.com/video/|VIDEO_INDEX
MLS|FC Cincinnati|FC Cincinnati|https://www.fccincinnati.com/video/|VIDEO_INDEX
MLS|Colorado Rapids|Colorado Rapids|https://www.coloradorapids.com/video/|VIDEO_INDEX
MLS|Columbus Crew|Columbus Crew|https://www.columbuscrew.com/video/|VIDEO_INDEX
MLS|D.C. United|D.C. United|https://www.dcunited.com/video/|VIDEO_INDEX
MLS|FC Dallas|FC Dallas|https://www.fcdallas.com/video/|VIDEO_INDEX
MLS|Houston Dynamo FC|Houston Dynamo FC|https://www.houstondynamofc.com/video/|VIDEO_INDEX
MLS|Inter Miami CF|Inter Miami CF|https://www.intermiamicf.com/video/|VIDEO_INDEX
MLS|LA Galaxy|LA Galaxy|https://www.lagalaxy.com/video/|VIDEO_INDEX
MLS|Los Angeles FC|Los Angeles FC|https://www.lafc.com/video/|VIDEO_INDEX
MLS|Minnesota United FC|Minnesota United FC|https://www.mnufc.com/video/|VIDEO_INDEX
MLS|CF Montréal|CF Montréal|https://www.cfmontreal.com/video/|VIDEO_INDEX
MLS|New England Revolution|New England Revolution|https://www.revolutionsoccer.net/video/|VIDEO_INDEX
MLS|New York City FC|New York City FC|https://www.newyorkcityfc.com/video/|VIDEO_INDEX
MLS|New York Red Bulls|New York Red Bulls;Red Bull New York|https://www.newyorkredbulls.com/video/|VIDEO_INDEX
MLS|Orlando City SC|Orlando City SC|https://www.orlandocitysc.com/video/|VIDEO_INDEX
MLS|Philadelphia Union|Philadelphia Union|https://www.philadelphiaunion.com/video/|VIDEO_INDEX
MLS|Portland Timbers|Portland Timbers|https://www.timbers.com/video/|VIDEO_INDEX
MLS|Real Salt Lake|Real Salt Lake|https://www.rsl.com/video/|VIDEO_INDEX
MLS|San Diego FC|San Diego FC|https://www.sandiegofc.com/video/|VIDEO_INDEX
MLS|San Jose Earthquakes|San Jose Earthquakes|https://www.sjearthquakes.com/video/|VIDEO_INDEX
MLS|Seattle Sounders FC|Seattle Sounders FC|https://www.soundersfc.com/video/|VIDEO_INDEX
MLS|Sporting Kansas City|Sporting Kansas City|https://www.sportingkc.com/video/|VIDEO_INDEX
MLS|Toronto FC|Toronto FC|https://www.torontofc.ca/video/topics/match-highlights/|VIDEO_INDEX
MLS|Vancouver Whitecaps FC|Vancouver Whitecaps FC|https://www.whitecapsfc.com/video/|VIDEO_INDEX
EPL|AFC Bournemouth|AFC Bournemouth|https://www.afcb.co.uk/videos/|VIDEO_INDEX
EPL|Arsenal|Arsenal|https://www.arsenal.com/media/all/1|TEAM_PAGE_WITH_VIDEO
EPL|Aston Villa|Aston Villa|https://www.avfc.co.uk/videos/|VIDEO_INDEX
EPL|Brentford|Brentford|https://www.brentfordfc.com/en/news/category/video|VIDEO_INDEX
EPL|Brighton & Hove Albion|Brighton & Hove Albion|https://www.brightonandhovealbion.com/latest-videos|VIDEO_INDEX
EPL|Coventry City|Coventry City|https://www.ccfc.co.uk/videos/|VIDEO_INDEX
EPL|Crystal Palace|Crystal Palace|https://www.cpfc.co.uk/palace-tv/videos/highlights/|VIDEO_INDEX
EPL|Everton|Everton|https://www.evertonfc.com/videos/|VIDEO_INDEX
EPL|Fulham|Fulham|https://www.fulhamfc.com/videos/browse/|VIDEO_INDEX
EPL|Hull City|Hull City|https://www.wearehullcity.co.uk/videos/|VIDEO_INDEX
EPL|Ipswich Town|Ipswich Town|https://www.itfc.co.uk/videos/browse/|VIDEO_INDEX
EPL|Leeds United|Leeds United|https://www.leedsunited.com/en/news?page=0&type=video|VIDEO_INDEX
EPL|Liverpool|Liverpool|https://www.liverpoolfc.com/watch|VIDEO_INDEX
EPL|Manchester City|Manchester City|https://www.mancity.com/citytv/mens|VIDEO_INDEX
EPL|Manchester United|Manchester United|https://www.manutd.com/en/mutv/collections/short-highlights|VIDEO_INDEX
EPL|Newcastle United|Newcastle United|https://www.newcastleunited.com/en/news/category/watch|VIDEO_INDEX
EPL|Nottingham Forest|Nottingham Forest|https://www.nottinghamforest.co.uk/videos/|VIDEO_INDEX
EPL|Sunderland|Sunderland|https://www.safc.com/videos/browse|VIDEO_INDEX
NCAAF|Air Force|Air Force|https://goairforcefalcons.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Alabama|Alabama|https://rolltide.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Arizona|Arizona|https://arizonawildcats.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Arizona State|Arizona State|https://sundevils.com/sports/mens/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Arkansas|Arkansas|https://arkansasrazorbacks.com/sport/m-footbl/|TEAM_PAGE_WITH_VIDEO
NCAAF|Army|Army|https://goarmywestpoint.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Auburn|Auburn|https://auburntigers.com/sports/football/videos|VIDEO_INDEX
NCAAF|Baylor|Baylor|https://baylorbears.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Boise State|Boise State|https://broncosports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Boston College|Boston College|https://bceagles.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|BYU|BYU|https://byucougars.com/sports/football/videos|VIDEO_INDEX
NCAAF|Cincinnati|Cincinnati|https://gobearcats.com/sports/football/videos|VIDEO_INDEX
NCAAF|Clemson|Clemson|https://clemsontigers.com/sports/football/videos|VIDEO_INDEX
NCAAF|Coastal Carolina|Coastal Carolina|https://goccusports.com/sports/football/|TEAM_PAGE_WITH_VIDEO
NCAAF|Colorado|Colorado|https://cubuffs.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Duke|Duke|https://goduke.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Florida|Florida|https://floridagators.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Florida State|Florida State|https://seminoles.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Fresno State|Fresno State|https://gobulldogs.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Georgia|Georgia|https://georgiadogs.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Georgia Tech|Georgia Tech|https://ramblinwreck.com/sports/m-footbl/|TEAM_PAGE_WITH_VIDEO
NCAAF|Houston|Houston|https://uhcougars.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Illinois|Illinois|https://fightingillini.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Indiana|Indiana|https://iuhoosiers.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Iowa|Iowa|https://hawkeyesports.com/sports/football/|TEAM_PAGE_WITH_VIDEO
NCAAF|Iowa State|Iowa State|https://cyclones.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|James Madison|James Madison|https://jmusports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Kansas|Kansas|https://kuathletics.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Kansas State|Kansas State|https://www.kstatesports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Kentucky|Kentucky|https://ukathletics.com/sports/football/|TEAM_PAGE_WITH_VIDEO
NCAAF|Liberty|Liberty|https://libertyflames.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Louisiana|Louisiana|https://ragincajuns.com/sports/football/|TEAM_PAGE_WITH_VIDEO
NCAAF|Louisville|Louisville|https://gocards.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|LSU|LSU|https://lsusports.net/sports/fb/videos|VIDEO_INDEX
NCAAF|Memphis|Memphis|https://gotigersgo.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Miami (FL)|Miami (FL)|https://miamihurricanes.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Michigan|Michigan|https://mgoblue.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Michigan State|Michigan State|https://msuspartans.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Minnesota|Minnesota|https://gophersports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Mississippi State|Mississippi State|https://hailstate.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Missouri|Missouri|https://mutigers.com/sports/football/videos|VIDEO_INDEX
NCAAF|Navy|Navy|https://navysports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|NC State|NC State|https://gopack.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Nebraska|Nebraska|https://huskers.com/sports/football/videos|VIDEO_INDEX
NCAAF|North Carolina|North Carolina|https://goheels.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|North Texas|North Texas|https://meangreensports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Northern Illinois|Northern Illinois|https://niuhuskies.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Notre Dame|Notre Dame|https://fightingirish.com/sports/football/videos|VIDEO_INDEX
NCAAF|Ohio State|Ohio State|https://ohiostatebuckeyes.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Oklahoma|Oklahoma|https://soonersports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Oklahoma State|Oklahoma State|https://okstate.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Ole Miss|Ole Miss|https://olemisssports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Oregon|Oregon|https://goducks.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Oregon State|Oregon State|https://osubeavers.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Penn State|Penn State|https://gopsusports.com/sports/football/videos|VIDEO_INDEX
NCAAF|Pittsburgh|Pittsburgh|https://pittsburghpanthers.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Purdue|Purdue|https://purduesports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|San Diego State|San Diego State|https://goaztecs.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|SMU|SMU|https://smumustangs.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|South Carolina|South Carolina|https://gamecocksonline.com/sports/football/|TEAM_PAGE_WITH_VIDEO
NCAAF|South Florida|South Florida|https://gousfbulls.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Syracuse|Syracuse|https://cuse.com/sports/football/|TEAM_PAGE_WITH_VIDEO
NCAAF|TCU|TCU|https://gofrogs.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Tennessee|Tennessee|https://utsports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Texas|Texas|https://texassports.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Texas A&M|Texas A&M|https://12thman.com/sports/football/videos|VIDEO_INDEX
NCAAF|Texas Tech|Texas Tech|https://texastech.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Toledo|Toledo|https://utrockets.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Troy|Troy|https://troytrojans.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Tulane|Tulane|https://tulanegreenwave.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|UCF|UCF|https://ucfknights.com/sports/football/videos|VIDEO_INDEX
NCAAF|UCLA|UCLA|https://uclabruins.com/sports/football/videos|VIDEO_INDEX
NCAAF|UNLV|UNLV|https://unlvrebels.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|USC|USC|https://usctrojans.com/sports/football/|TEAM_PAGE_WITH_VIDEO
NCAAF|UTSA|UTSA|https://goutsa.com/sports/football/videos|VIDEO_INDEX
NCAAF|Utah|Utah|https://utahutes.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Utah State|Utah State|https://utahstateaggies.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Vanderbilt|Vanderbilt|https://vucommodores.com/sports/football/videos|VIDEO_INDEX
NCAAF|Virginia|Virginia|https://virginiasports.com/sports/football/videos|VIDEO_INDEX
NCAAF|Virginia Tech|Virginia Tech|https://hokiesports.com/sports/football/videos|VIDEO_INDEX
NCAAF|Wake Forest|Wake Forest|https://godeacs.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Washington|Washington|https://gohuskies.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Washington State|Washington State|https://wsucougars.com/sports/football|TEAM_PAGE_WITH_VIDEO
NCAAF|Wisconsin|Wisconsin|https://uwbadgers.com/sports/football/|TEAM_PAGE_WITH_VIDEO
"""

TEAM_VIDEO_SEEDS = []
for _line in _DATA.splitlines():
    if not _line.strip():
        continue
    _league, _team, _aliases, _url, _role = _line.split("|", 4)
    TEAM_VIDEO_SEEDS.append({
        "league": _league,
        "team": _team,
        "aliases": [x for x in _aliases.split(";") if x],
        "url": _url,
        "role": _role,
    })

SEED_COUNTS = dict(Counter(row["league"] for row in TEAM_VIDEO_SEEDS))
