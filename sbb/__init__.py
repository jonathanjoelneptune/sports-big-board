"""Sports Big Board architecture services."""
from .nfl_weekly_playlists import install as _install_nfl_weekly_playlists
from .competition_builder import install as _install_competition_builder
from .competition_builder_v467 import install as _install_competition_builder_v467
from .historical_media_v4610 import install as _install_historical_media_v4610
from .competition_builder_v4612 import install as _install_competition_builder_v4612
from .competition_builder_v4613 import install as _install_competition_builder_v4613
from .competition_builder_v4614 import install as _install_competition_builder_v4614
from .competition_builder_v4615 import install as _install_competition_builder_v4615
from .special_event_media_v4616 import install as _install_special_event_media_v4616
from .day_state import install as _install_day_state
from .tennis_ribbon_projection import install as _install_tennis_ribbon_projection
from .game_center_multisport import install as _install_game_center_multisport
from .history_readiness_repair import install as _install_history_readiness_repair
from .runtime_path_repair_v5110 import install as _install_runtime_path_repair_v5110
from .database_authority import install as _install_database_authority
from .backend_inspector_api import install as _install_backend_inspector_api

_install_nfl_weekly_playlists()
_install_competition_builder()
_install_competition_builder_v467()
_install_historical_media_v4610()
_install_competition_builder_v4612()
_install_competition_builder_v4613()
_install_competition_builder_v4614()
_install_competition_builder_v4615()
_install_special_event_media_v4616()
# v5.1.22: install the backend tennis presentation projection before Day State
# starts its worker. The browser receives already-renderable names/flags/rounds.
_install_tennis_ribbon_projection()
_install_day_state()
# v5.2.0: persist already-built Day State into a request-cheap RibbonSnapshot.
# This never builds/provider-fetches on the ribbon request thread.
from .ribbon_snapshot_v520 import install as _install_ribbon_snapshot_v520
_install_ribbon_snapshot_v520()
_install_game_center_multisport()
from .ncaaf_game_center import install as _install_ncaaf_game_center
_install_ncaaf_game_center()
_install_history_readiness_repair()

from .ncaaf_namespace_reset import install as _install_ncaaf_namespace_reset
from .ncaaf_ranked import install as _install_ncaaf_ranked

_install_ncaaf_namespace_reset()
_install_runtime_path_repair_v5110()
_install_database_authority()
_install_backend_inspector_api()
_install_ncaaf_ranked()

# v5.1.19: durable media authority + one canonical tennis adapter. Keep NCAAF Game Center unchanged.
from .media_runtime_repair_v5116 import install as _install_media_runtime_repair_v5116
from .media_authority_v5117 import install as _install_media_authority_v5117
from .tennis_game_center import install as _install_tennis_game_center
_install_media_runtime_repair_v5116()
_install_media_authority_v5117()
_install_tennis_game_center()

# v5.1.22: durable event-fingerprint Game Center lookup + deterministic tennis routing.
# This installs after the canonical tennis adapter so generic /api/events/... requests
# cannot fall through to fixed-league provider validation.
from .game_center_identity_v5122 import install as _install_game_center_identity_v5122
_install_game_center_identity_v5122()

# DayStateEngine remains the sole date authority. Tennis ribbon presentation is a
# backend read-model projection, not a browser-side score authority.
