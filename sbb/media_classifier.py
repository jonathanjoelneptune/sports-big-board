"""Single authoritative server-side Gold/Green/Purple/Blue media classifier."""
import re

COMMENTARY="gold"
QUICK="green"
EXTENDED="extended"
HIGHLIGHT_REEL="blue"

_NON_GAME_PROGRAM_RE=re.compile(r"\b(?:post[- ]?game show|post[- ]?game live|instant reaction|reaction(?:s)?(?: to)?|reacts? to|analysis show|film room|podcast|press conference|presser|interview)\b",re.I)

def _text(item):
    return " ".join(str(item.get(k) or "") for k in ("title","subtitle","description")).lower()

def _source(item):
    return " ".join(str(item.get(k) or "") for k in ("sourceLabel","source","provider")).lower()

def duration_seconds(item):
    try: return float(item.get("durationSeconds", item.get("duration",0)) or 0)
    except Exception: return 0.0

def is_non_game_program(item):
    if not item: return False
    t=_text(item)
    if re.search(r"\b(?:full game highlights|game highlights|full match highlights|match highlights|condensed game|extended highlights)\b",t,re.I): return False
    return bool(_NON_GAME_PROGRAM_RE.search(t))

def is_recap_candidate(item):
    if not item or is_non_game_program(item): return False
    return bool(item.get("overview") or item.get("programType")=="recap" or re.search(r"full game highlights|game recap|game summary|game highlights|match recap|match highlights|condensed game|extended highlights|postgame recap",_text(item)))

def is_commentary(item):
    if not item or is_non_game_program(item): return False
    if item.get("recapTier")==COMMENTARY or item.get("commentaryLikely") is True or float(item.get("commentaryConfidence") or 0)>=0.85: return True
    d=duration_seconds(item)
    if d and (d<45 or d>900): return False
    t=_text(item)
    if re.search(r"condensed game|extended highlights|full game highlights|full match highlights",t): return False
    network=bool(re.search(r"espn|sportscenter|fox sports|fs1|nbc sports|cbs sports|sportsnet|mlb network|nfl network|nba tv|nhl network|spectrum|sny|nesn|masn|yes network|marquee|fanduel sports|bally",_source(item)))
    produced=bool(re.search(r"game recap|postgame recap|postgame report|game story|what happened|highlights (?:and|&) analysis",t))
    return network and produced

def is_extended(item):
    if not is_recap_candidate(item) or is_commentary(item): return False
    objective=str(item.get("mediaObjective") or "").upper()
    if objective=="EXTENDED": return True
    if objective=="QUICK": return False
    d=duration_seconds(item); t=_text(item)
    return item.get("recapTier")==EXTENDED or (420<=d<=1500) or (not d and bool(re.search(r"\bextended highlights?\b|\bcondensed game\b|\bextended recap\b",t)))

def tier(item):
    if is_commentary(item): return COMMENTARY
    if not is_recap_candidate(item): return HIGHLIGHT_REEL
    objective=str(item.get("mediaObjective") or "").upper()
    if objective=="QUICK": return QUICK
    if objective=="EXTENDED": return EXTENDED
    if is_extended(item): return EXTENDED
    return QUICK

def annotate(item):
    out=dict(item or {})
    out["recapTier"]=tier(out)
    return out
