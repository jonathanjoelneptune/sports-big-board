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
from .cfb_trusted_youtube import install as _install_cfb_trusted_youtube
from .game_center_multisport import install as _install_game_center_multisport
from .history_readiness_repair import install as _install_history_readiness_repair
from .runtime_path_repair_v4720 import install as _install_runtime_path_repair_v4720
from .database_authority import install as _install_database_authority
from .game_center_runtime_v4721 import install as _install_game_center_runtime_v4721
from .game_center_runtime_v482 import install as _install_game_center_runtime_v482

_install_nfl_weekly_playlists()
_install_competition_builder()
_install_competition_builder_v467()
_install_historical_media_v4610()
_install_competition_builder_v4612()
_install_competition_builder_v4613()
_install_competition_builder_v4614()
_install_competition_builder_v4615()
_install_special_event_media_v4616()
_install_day_state()
_install_cfb_trusted_youtube()
_install_game_center_multisport()
_install_history_readiness_repair()
# Preserve v4.7.20's bounded owner-specific LLWS/CFB recovery underneath the final
# database-authority policy. The final policy prevents generic startup repair from
# reinterpreting durable event/collection relationships again.
_install_runtime_path_repair_v4720()
_install_database_authority()
_install_game_center_runtime_v4721()
_install_game_center_runtime_v482()
