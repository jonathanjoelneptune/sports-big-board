#!/usr/bin/env python3
"""
Sports Big Board R18 targeted media-repair source patch.

Purpose
-------
Apply the R18 repair-transport fix to the current repository checkout:
  1. ESPN generic video discovery must use ESPN's existing nested direct-media
     resolver instead of accepting image/article hrefs as video candidates.
  2. ESPN search candidate identities become deterministic across process restarts.
  3. Repair/audit URL selection prefers actual video transport fields ahead of
     external/article URLs.
  4. R17-exhausted repair jobs get one immediate R18 retry through the corrected
     discovery ladder, then normal cooldown behavior resumes.
  5. History canonical URL normalization recognizes videoUrl before externalUrl.

The patch is deliberately exact and fail-closed. If the expected R17 source text
has drifted, it aborts instead of applying a partial/ambiguous edit.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def patch_server(text: str) -> str:
    old = """        urls=[]
        for k,v in obj.items():
            if isinstance(v,str) and v.startswith('http'):
                if re.search(r'\\.(?:mp4|m3u8)(?:\\?|$)',v,re.I): urls.append(v)
        media=urls[0] if urls else ''
"""
    new = """        # R18: ESPN search payloads commonly keep the playable rendition under
        # links.source rather than as a top-level .mp4/.m3u8 field. Reuse the
        # event-video resolver so repair discovery only emits a candidate when
        # ESPN exposes an actual direct video transport.
        if not _espn_video_allowed_us(obj): continue
        media=_espn_video_media_url(obj)
        if not media: continue
"""
    text = replace_once(text, old, new, "server ESPN nested transport")

    text = replace_once(
        text,
        "        sig=(title,media or href)\n",
        "        sig=(title,media,href)\n"
        "        stable_id=hashlib.sha1(('\\\\n'.join(str(x or '') for x in sig)).encode('utf-8')).hexdigest()[:16]\n",
        "server ESPN stable identity",
    )

    text = replace_once(
        text,
        "        if not media and not href: continue\n"
        "        out.append({'id':f'espn-video-{abs(hash(sig))%10**12}','eventId':f'espn-video-{abs(hash(sig))%10**12}',",
        "        out.append({'id':f'espn-video-{stable_id}','eventId':f'espn-video-{stable_id}',",
        "server ESPN playable-only candidate",
    )
    return text


def patch_media_audit(text: str) -> str:
    text = replace_once(
        text,
        'AUDIT_GENERATION = "R17-MULTI-SOURCE-REPAIR-DISCOVERY"',
        'AUDIT_GENERATION = "R18-MEDIA-REPAIR-TRANSPORT"',
        "audit generation",
    )

    text = replace_once(
        text,
        '    for key in ("mediaUrl", "externalUrl", "url", "videoUrl", "href"):\n',
        '    for key in ("mediaUrl", "videoUrl", "videoURL", "streamUrl", "playbackUrl", "url", "href", "externalUrl"):\n',
        "repair playback URL priority",
    )

    text = replace_once(
        text,
        """            # R17 is a materially new discovery strategy. Give R16-exhausted jobs one
            # immediate pass through the new ladder, then normal cooldown preservation
            # prevents them from looping again.
            cur=conn.execute(
                "UPDATE history_media_repair_queue SET state='PENDING',next_retry_at=0,updated_at=?,last_error='', reason='R17 multi-source discovery strategy upgrade: immediate one-time retry' WHERE health IN ('DEGRADED','UNPLAYABLE','NO_MEDIA') AND state='WAITING_RETRY' AND COALESCE(details_json,'') NOT LIKE '%R17_MULTI_SOURCE_LADDER%'",
                (now,),
            ); strategy_requeued=int(cur.rowcount or 0)
""",
        """            # R18 changes the provider transport that reaches certification. Give
            # every R17-exhausted actionable job one immediate pass through the
            # corrected ladder. Once processed, details_json carries the R18 marker,
            # so normal cooldown preservation prevents service-restart loops.
            cur=conn.execute(
                "UPDATE history_media_repair_queue SET state='PENDING',next_retry_at=0,updated_at=?,last_error='', reason='R18 playable-transport strategy upgrade: immediate one-time retry' WHERE health IN ('DEGRADED','UNPLAYABLE','NO_MEDIA') AND state='WAITING_RETRY' AND COALESCE(details_json,'') NOT LIKE '%R18_MEDIA_REPAIR_TRANSPORT%'",
                (now,),
            ); strategy_requeued=int(cur.rowcount or 0)
""",
        "R18 one-time repair requeue",
    )

    text = replace_once(
        text,
        'details={"strategy":"R17_MULTI_SOURCE_LADDER","knownAssets":len(before),"target":target}',
        'details={"strategy":"R18_MEDIA_REPAIR_TRANSPORT","knownAssets":len(before),"target":target}',
        "R18 repair strategy marker",
    )

    # Keep operator telemetry honest about which ladder produced the result.
    text = text.replace("R17 deep local catalog recovery", "R18 deep local catalog recovery")
    text = text.replace("R17 registered provider discovery", "R18 registered provider discovery")
    text = text.replace("R17 official/trusted YouTube playlist index", "R18 official/trusted YouTube playlist index")
    text = text.replace("R17 generic YouTube last-resort search", "R18 generic YouTube last-resort search")
    text = text.replace(
        "R17 multi-source repair ladder exhausted without a newly certified candidate",
        "R18 media-repair transport ladder exhausted without a newly certified candidate",
    )
    return text


def patch_history_repository(text: str) -> str:
    return replace_once(
        text,
        '        return str(item.get("mediaUrl") or item.get("externalUrl") or "")\n',
        '        return str(item.get("mediaUrl") or item.get("videoUrl") or item.get("videoURL") or item.get("streamUrl") or item.get("playbackUrl") or item.get("externalUrl") or "")\n',
        "history canonical direct-video URL priority",
    )


def apply(path: Path, patch_fn, dry_run: bool) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = patch_fn(original)
    if updated == original:
        raise RuntimeError(f"{path}: patch produced no changes")
    if not dry_run:
        path.write_text(updated, encoding="utf-8")
    print(f"{'CHECK' if dry_run else 'PATCH'} OK  {path}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", default=".", help="Sports Big Board repository root")
    ap.add_argument("--dry-run", action="store_true", help="Validate exact patch points without writing")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    targets = [
        (root / "server.py", patch_server),
        (root / "media_audit_service.py", patch_media_audit),
        (root / "sbb" / "history_repository.py", patch_history_repository),
    ]
    missing = [str(p) for p, _ in targets if not p.is_file()]
    if missing:
        print("R18 patch aborted; missing files:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 2

    try:
        for path, fn in targets:
            apply(path, fn, args.dry_run)
    except Exception as exc:
        print(f"R18 patch aborted: {exc}", file=sys.stderr)
        return 3

    print("\nR18 media-repair transport patch validated." if args.dry_run
          else "\nR18 media-repair transport patch applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
