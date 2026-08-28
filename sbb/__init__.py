"""Sports Big Board v4.5.0 architecture services."""
import os

# Media Intelligence installs itself asynchronously because the sbb package is
# imported before server.py has constructed HISTORY_REPOSITORY and worker policy.
# The installer waits for those globals and then starts exactly one low-bandwidth
# scanner. Tests/operators can disable the background thread explicitly.
if str(os.environ.get("SBB_DISABLE_MEDIA_INTELLIGENCE", "0")).lower() not in ("1", "true", "yes", "on"):
    try:
        from sbb.media_intelligence import schedule_media_intelligence_install
        schedule_media_intelligence_install()
    except Exception:
        pass
