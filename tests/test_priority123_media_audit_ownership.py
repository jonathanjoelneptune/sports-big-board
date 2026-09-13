from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_p1_backend_startup_is_explicit_and_ordered():
    init = text("sbb/__init__.py")
    startup = text("sbb/startup.py")

    assert "from .startup import STARTUP_REGISTRATIONS, bootstrap, startup_snapshot" in init
    assert "bootstrap()" in init
    assert "_install_" not in init

    registrations = re.findall(r'StartupRegistration\("([^"]+)",\s*"([^"]+)"', startup)
    assert len(registrations) >= 36
    modules = [module for _key, module in registrations]
    assert modules[:4] == [
        "nfl_weekly_playlists",
        "competition_builder",
        "competition_builder_v467",
        "historical_media_v4610",
    ]
    assert "backend_inspector_routes" in modules
    assert modules.index("database_authority") < modules.index("backend_inspector_routes") < modules.index("ncaaf_ranked")
    assert modules[-4:] == [
        "canonical_shadow_v600",
        "canonical_certification_v610",
        "nfl_club_sources",
        "nfl_audit_migration",
    ]
    for token in ["startup_snapshot", "durationMs", "bootstrapped", "services"]:
        assert token in startup


def test_p1_shared_route_table_has_compatibility_fallback_and_live_migration():
    registry = text("sbb/route_registry.py")
    inspector_routes = text("sbb/backend_inspector_routes.py")
    startup = text("sbb/startup.py")

    for token in [
        "class RouteRegistration",
        "def register_get",
        "def dispatch",
        "__sbbSharedRouteRegistry",
        "return legacy_get(self)",
        "Duplicate Sports Big Board route",
    ]:
        assert token in registry

    assert 'register_get(' in inspector_routes
    assert '"/api/backend-inspector/date"' in inspector_routes
    assert "backend_inspector_routes" in startup
    # The legacy inspector implementation remains available as compatibility code,
    # but startup no longer calls its direct Handler.do_GET installer.
    assert 'StartupRegistration("backend-inspector-api", "backend_inspector_api")' not in startup


def test_p1_playback_adapter_owns_pause_resume_and_recovery_extensions():
    orchestrator = text("architecture/playback-orchestrator-v5.js")
    recovery = text("architecture/playback-early-pause-recovery-v538.js")

    for token in [
        "OWNERSHIP_REVISION='P1-2026-09'",
        "function extendAdapter(extension)",
        "function requestPauseAll",
        "function requestResumeActive",
        "function requestRecovery",
        "adapterExtendedAt",
        "capabilities:",
    ]:
        assert token in orchestrator

    for token in [
        "installAdapterOwnership",
        "orchestrator.extendAdapter",
        "orchestrator.requestPauseAll",
        "orchestrator.requestResumeActive",
        "orchestrator.requestRecovery",
        "adapterOwned",
    ]:
        assert token in recovery

    # Recovery policy may inspect provider state, but the recovery decisions route
    # through the orchestrator instead of directly retuning via the old global.
    assert "tuneProgramIndexV5(currentIndex" not in recovery


def test_p2_media_audit_remains_cheap_to_observe_and_interrupt_safe():
    service = text("media_audit_service.py")
    js = text("ui/media-audit-v550.js")

    for token in [
        "class AuditStatusCache",
        "statusCacheAgeSeconds",
        "LIMIT ? OFFSET ?",
        "DEFERRED_INFRA",
        "def defer_queue_item",
        "PROBE_COMPLETE_WAITING_DB",
        "CANONICAL_PACKAGE_WAITING_DB",
        "SerializedAuditDbWriter",
    ]:
        assert token in service

    assert "document.hidden" in js
    assert "Inventory refresh delayed" in js
    assert "STATUS DELAYED" in js
    assert "refreshInventory();" in js


def test_p3_valid_fallback_is_separate_from_preferred_package():
    service = text("media_audit_service.py")

    for token in [
        "MEDIA_AUDIT_FALLBACK_AVAILABLE",
        "MEDIA_AUDIT_ALTERNATE_AVAILABLE",
        "recover_healthy_audit_alternatives",
        "preferenceSeparatedFromValidity",
        'state = ASSIGNED',
        'hard_failed = meta["runtime"] == "FAILED" and _hard_media_failure_reason',
    ]:
        assert token in service

    canonicalize = service[service.index("def canonicalize"):service.index("def inventory")]
    assert "MEDIA_AUDIT_FALLBACK_AVAILABLE" in canonicalize
    assert "MEDIA_AUDIT_ALTERNATE_AVAILABLE" in canonicalize
    assert "hard_failed" in canonicalize
