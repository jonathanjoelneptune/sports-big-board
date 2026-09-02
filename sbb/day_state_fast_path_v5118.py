"""Retired Sports Big Board v5.1.18 score-only fast path.

v5.1.19 deliberately has one date authority: DayStateEngine. This module remains
import-safe only so stale deployments cannot fail during an incremental upload.
It does not patch the server or expose the retired fast Day State endpoint.
"""
VERSION="5.1.19-retired"

def install():
    return False

__all__=["VERSION","install"]
