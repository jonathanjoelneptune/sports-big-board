#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
init = (root / "sbb" / "__init__.py").read_text(encoding="utf-8")
startup_path = root / "sbb" / "startup.py"
startup = startup_path.read_text(encoding="utf-8") if startup_path.is_file() else ""
module = (root / "sbb" / "canonical_schedule_watchdogs_v6116.py").read_text(encoding="utf-8")
hotfix = (root / "sbb" / "canonical_reconciliation_hotfix_v6116.py").read_text(encoding="utf-8")
followup = (root / "sbb" / "canonical_reconciliation_followup_v6116.py").read_text(encoding="utf-8")
epl_followup_path = root / "sbb" / "canonical_epl_fpl_state_followup_v6116.py"
epl_followup = epl_followup_path.read_text(encoding="utf-8")
epl_followup_test = root / "tests" / "test_v6116_epl_fpl_state_followup.py"
verify = (root / "VERIFY.sh").read_text(encoding="utf-8")

expected = ".".join(("6", "1", "16"))
assert version == expected, version

if "from .startup import" in init and "bootstrap()" in init:
    assert 'StartupRegistration("canonical-reconcile-v6116", "canonical_reconciliation_hotfix_v6116")' in startup
    assert 'StartupPhase("canonical-reconcile-v6116"' in startup
    assert 'StartupRegistration("canonical-reconcile-followup-v6116", "canonical_reconciliation_followup_v6116")' in startup
    assert 'StartupPhase("canonical-reconcile-followup-v6116"' in startup
    assert 'StartupRegistration("canonical-epl-fpl-state-v6116", "canonical_epl_fpl_state_followup_v6116")' in startup
    assert 'StartupPhase("canonical-epl-fpl-state-v6116"' in startup
    assert startup.index('StartupPhase("canonical-reconcile-followup-v6116"') < startup.index('StartupPhase("canonical-epl-fpl-state-v6116"')
else:
    assert "from .canonical_schedule_watchdogs_v6116 import install" in init
    assert "_install_canonical_schedule_watchdogs_v6116()" in init
    assert "from .canonical_reconciliation_hotfix_v6116 import install" in init
    assert "_install_canonical_reconciliation_hotfix_v6116()" in init
    assert "from .canonical_reconciliation_followup_v6116 import install" in init
    assert "_install_canonical_reconciliation_followup_v6116()" in init
    assert "from .canonical_epl_fpl_state_followup_v6116 import install" in init
    assert "_install_canonical_epl_fpl_state_followup_v6116()" in init

for token in (
    "OFFICIAL_SCHEDULE_PAGES",
    "https://www.premierleague.com/en/matches/premier-league/2026-27/matchweek-4",
    "https://www.nfl.com/schedules",
    "https://www.mlb.com/schedule",
    "https://www.nba.com/schedule",
    "https://www.mlssoccer.com/schedule/scores",
    "https://www.nhl.com/schedule",
    "https://fbschedules.com/college-football-schedule/",
    "PREMIER_LEAGUE_OFFICIAL_SCHEDULE",
    "nflCurrentByWeekScheduleRoute",
    "trustedExplicitSlateDateRehome",
    "ncaafFbschedulesSecondaryOnly",
):
    assert token in module, token

for token in (
    "nflExactWeekCoverageProof",
    "nflCompletedFinalRowParser",
    "ncaafGuardedAliasDriftReconciliation",
    "NCAA_SD_DATA",
):
    assert token in hotfix, token

for token in (
    "nflPregameLiveFinalContinuity",
    "ncaafPostCollectionAliasRepair",
    "mlbStrongProviderIdentityGuard",
    "mlbAdjacentDayCollapseRepair",
):
    assert token in followup, token

for token in (
    "FPL_FIXTURES_URL",
    "FPL_BOOTSTRAP_URL",
    "PREMIER_LEAGUE_OFFICIAL_SCHEDULE",
    "eplOfficialFplApiAuthoritative",
    "staleKnownConflictStateNormalization",
):
    assert token in epl_followup, token

compile(epl_followup, str(epl_followup_path), "exec")
assert epl_followup_test.is_file(), epl_followup_test
subprocess.run([sys.executable, str(epl_followup_test)], cwd=root, check=True)

assert "python3 -m py_compile sbb/canonical_schedule_watchdogs_v6116.py" in verify
assert "python3 tests/test_v6116_official_schedule_watchdogs.py" in verify
assert "python3 tests/test_v6116_official_schedule_release.py" in verify
assert "python3 -m py_compile sbb/canonical_reconciliation_hotfix_v6116.py" in verify
assert "python3 tests/test_v6116_canonical_reconcile_hotfix.py" in verify
assert "python3 -m py_compile sbb/canonical_reconciliation_followup_v6116.py" in verify
assert "python3 tests/test_v6116_canonical_reconcile_followup.py" in verify

print("PASS v6.1.16 official schedule resiliency + canonical reconciliation + EPL FPL/state follow-up release contract")
