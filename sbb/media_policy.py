"""Sport-aware media request policy shared by server tests/diagnostics (v4.0.0)."""
from copy import deepcopy

REQUESTS=("QUICK","EXTENDED","COMMENTARY","MOMENTS","ANY")
BASE={
    "quick":{"ideal":(150,300),"accept":(45,390),"target":210},
    "extended":{"ideal":(600,1200),"accept":(420,1800),"target":900},
    "commentary":{"ideal":(120,360),"accept":(90,420),"target":210},
}
POLICIES={
    "baseball":{**BASE,"quick":{"ideal":(150,300),"accept":(60,390),"target":210}},
    "american-football":{**BASE,"quick":{"ideal":(150,300),"accept":(45,390),"target":210},"extended":{"ideal":(720,1080),"accept":(540,1800),"target":900}},
    "basketball":{**BASE,"quick":{"ideal":(120,300),"accept":(45,420),"target":210}},
    "ice-hockey":{**BASE,"quick":{"ideal":(120,300),"accept":(45,420),"target":210}},
    "football":{**BASE,"quick":{"ideal":(120,300),"accept":(45,420),"target":180},"extended":{"ideal":(480,900),"accept":(360,1500),"target":720}},
    "multi-sport":BASE,
}

def policy_for(sport_id):
    return deepcopy(POLICIES.get(str(sport_id or ""),BASE))

def duration_score(seconds,rule):
    try:d=float(seconds or 0)
    except Exception:return 0
    if not d:return 0
    lo,hi=rule["accept"]
    if not lo<=d<=hi:return -70
    ilo,ihi=rule["ideal"]
    target=float(rule["target"])
    if ilo<=d<=ihi:
        spread=max(1,(ihi-ilo)/2)
        return 35-min(15,abs(d-target)/spread*10)
    return 10-min(25,abs(d-target)/max(1,target)*25)
