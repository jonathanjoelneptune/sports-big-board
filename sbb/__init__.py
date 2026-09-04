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
from .ribbon_authority_v521 import install as _install_ribbon_authority_v521
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
_install_tennis_ribbon_projection()
_install_ribbon_authority_v521()
_install_day_state()
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

from .media_runtime_repair_v5116 import install as _install_media_runtime_repair_v5116
from .media_authority_v5117 import install as _install_media_authority_v5117
from .tennis_game_center import install as _install_tennis_game_center
_install_media_runtime_repair_v5116()
_install_media_authority_v5117()
_install_tennis_game_center()

from .game_center_identity_v5122 import install as _install_game_center_identity_v5122
_install_game_center_identity_v5122()

from .current_news_v522 import install as _install_current_news_v522
_install_current_news_v522()

from .release_identity_v523 import install as _install_release_identity_v523
from .integrity_lane_v523 import install as _install_integrity_lane_v523
from .backend_snapshot_v523 import install as _install_backend_snapshot_v523
from .current_news_v523 import install as _install_current_news_v523
_install_release_identity_v523()
_install_integrity_lane_v523()
_install_backend_snapshot_v523()
_install_current_news_v523()

# v5.4.1: persistent participant metadata + cached Team Focus enrichment.
# This installs after the normalized catalog and ticker read models so it remains
# a cache/read-only browser service and never becomes a score/playback authority.
from .team_focus_v537 import install as _install_team_focus_v537
_install_team_focus_v537()

# v5.4.1: cached standings/playoff/event context for the LEAGUE VIEW drawer.
from .league_view_v538 import install as _install_league_view_v538
_install_league_view_v538()
