#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / 'apply_v6116_release.py'
text = path.read_text(encoding='utf-8')

preserve_anchor = '    "tests/test_media_audit_discovery_visibility_v6116.py",\n'
preserve_add = preserve_anchor + '    "tests/test_v6116_storage_retention_release.py",\n'
if preserve_add not in text:
    if preserve_anchor not in text:
        raise SystemExit('PRESERVE anchor missing')
    text = text.replace(preserve_anchor, preserve_add, 1)

# Install the compatibility block on a source tree that does not have it yet.
loop_tail = '''        if rendered != text:
            path.write_text(rendered, encoding="utf-8")


def patch_verify(root):
'''
compat = '''        if rendered != text:
            path.write_text(rendered, encoding="utf-8")

    # v5.3.4 encoded the original fixed 256 MiB deploy guard as a literal token.
    # v6.1.16 replaces that fixed threshold with bounded daily-backup retention
    # and rollback-sized dynamic headroom. Translate only the obsolete literal;
    # the dedicated v6.1.16 storage test verifies the stronger full contract.
    browse_safety = tests / "test_v534_complete_browse_deploy_safety.py"
    if browse_safety.is_file():
        source = browse_safety.read_text(encoding="utf-8")
        legacy_phrase = "less than 256 MiB free after safe cleanup"
        if legacy_phrase in source:
            browse_safety.write_text(
                source.replace(legacy_phrase, "REQUIRED_KB=1048576", 1),
                encoding="utf-8",
            )


def patch_verify(root):
'''
if 'browse_safety = tests / "test_v534_complete_browse_deploy_safety.py"' not in text:
    if loop_tail not in text:
        raise SystemExit('patch_legacy_contracts tail anchor missing')
    text = text.replace(loop_tail, compat, 1)
else:
    old = '''    # v5.3.4 encoded the original fixed 256 MiB deploy guard as a literal token.
    # v6.1.16 replaces that fixed threshold with bounded daily-backup retention
    # and rollback-sized dynamic headroom. Preserve the historical test's safety
    # intent by upgrading only that obsolete assertion in the materialized tree.
    browse_safety = tests / "test_v534_complete_browse_deploy_safety.py"
    if browse_safety.is_file():
        source = browse_safety.read_text(encoding="utf-8")
        legacy = "        'less than 256 MiB free after safe cleanup',\\n"
        upgraded = (
            "        'prune_daily_backups history 3',\\n"
            "        'prune_daily_backups game-centers 3',\\n"
            "        'REQUIRED_KB=1048576',\\n"
            "        'HISTORY_KB + 524288',\\n"
            "        'Live catalog was not touched',\\n"
        )
        if legacy in source:
            browse_safety.write_text(source.replace(legacy, upgraded, 1), encoding="utf-8")
        elif "'REQUIRED_KB=1048576'" not in source:
            raise SystemExit("ERROR: v5.3.4 deploy-safety compatibility anchor missing")
'''
    new = '''    # v5.3.4 encoded the original fixed 256 MiB deploy guard as a literal token.
    # v6.1.16 replaces that fixed threshold with bounded daily-backup retention
    # and rollback-sized dynamic headroom. Translate only the obsolete literal;
    # the dedicated v6.1.16 storage test verifies the stronger full contract.
    browse_safety = tests / "test_v534_complete_browse_deploy_safety.py"
    if browse_safety.is_file():
        source = browse_safety.read_text(encoding="utf-8")
        legacy_phrase = "less than 256 MiB free after safe cleanup"
        if legacy_phrase in source:
            browse_safety.write_text(
                source.replace(legacy_phrase, "REQUIRED_KB=1048576", 1),
                encoding="utf-8",
            )
'''
    if old in text:
        text = text.replace(old, new, 1)

verify_anchor = '        "node --check ui/media-audit-copy-v6116.js",\n'
verify_add = verify_anchor + '        "python3 tests/test_v6116_storage_retention_release.py",\n'
if verify_add not in text:
    if verify_anchor not in text:
        raise SystemExit('VERIFY additions anchor missing')
    text = text.replace(verify_anchor, verify_add, 1)

required_anchor = '        root / "tests" / "test_media_audit_discovery_visibility_v6116.py",\n'
required_add = required_anchor + '        root / "tests" / "test_v6116_storage_retention_release.py",\n'
if required_add not in text:
    if required_anchor not in text:
        raise SystemExit('required files anchor missing')
    text = text.replace(required_anchor, required_add, 1)

path.write_text(text, encoding='utf-8')
print('patched robust v6.1.16 storage-retention compatibility + verification wiring')
