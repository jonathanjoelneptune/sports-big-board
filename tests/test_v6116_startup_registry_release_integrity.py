#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATERIALIZER = ROOT / "tools" / "apply_v6116_release.py"

spec = importlib.util.spec_from_file_location("sbb_apply_v6116_release", MATERIALIZER)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

CHECKER_FIXTURE = '''from pathlib import Path
root=Path(__file__).resolve().parents[1]
errors=[]
sbb_init=text(Path('sbb')/'__init__.py')
team_focus=text(Path('sbb')/'team_focus_v537.py')
if 'from .team_focus_v537 import install as _install_team_focus_v537' not in sbb_init or '_install_team_focus_v537()' not in sbb_init:
    errors.append('sbb package does not install v5.5.0 Team Focus backend')
league_backend=text(Path('sbb')/'league_view_v538.py')
if 'from .league_view_v538 import install as _install_league_view_v538' not in sbb_init or '_install_league_view_v538()' not in sbb_init:
    errors.append('sbb package does not install v5.5.0 League View backend')
'''


def verify_checker_patch():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = root / "tools" / "check_release_version.py"
        path.parent.mkdir(parents=True)
        path.write_text(CHECKER_FIXTURE, encoding="utf-8")

        assert module.patch_release_integrity_startup_registry(root) is True
        rendered = path.read_text(encoding="utf-8")
        assert "def backend_install_present(" in rendered
        assert "startup_registry_path=root/'sbb'/'startup.py'" in rendered
        assert 'StartupRegistration("{key}", "{module}")' in rendered
        assert 'StartupPhase("{phase_name}", ("{key}",), ("{key}",))' in rendered
        assert "'team_focus_v537','team-focus-v537','team-focus'" in rendered
        assert "'league_view_v538','league-view-v538','league-view'" in rendered
        assert "legacy or registered" in rendered

        # The transformation is deliberately idempotent because release
        # materializers can be replayed in CI/recovery workflows.
        before = rendered
        assert module.patch_release_integrity_startup_registry(root) is False
        assert path.read_text(encoding="utf-8") == before


def verify_patch_precedes_delegation():
    source = MATERIALIZER.read_text(encoding="utf-8")
    main = source.split("def main(argv=None):", 1)[1]
    patch_pos = main.index("patch_release_integrity_startup_registry(root)")
    base_pos = main.index("run_base(root, preserved)")
    assert patch_pos < base_pos, "release checker must be patched before historical materializer delegation"


def verify_live_registry_contract():
    startup = (ROOT / "sbb" / "startup.py").read_text(encoding="utf-8")
    assert 'StartupRegistration("team-focus-v537", "team_focus_v537")' in startup
    assert 'StartupPhase("team-focus", ("team-focus-v537",), ("team-focus-v537",))' in startup
    assert 'StartupRegistration("league-view-v538", "league_view_v538")' in startup
    assert 'StartupPhase("league-view", ("league-view-v538",), ("league-view-v538",))' in startup


def main():
    verify_checker_patch()
    verify_patch_precedes_delegation()
    verify_live_registry_contract()
    print("PASS: v6.1.16 release integrity accepts exact startup-registry ownership without weakening backend install checks")


if __name__ == "__main__":
    main()
