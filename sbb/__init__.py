"""Sports Big Board architecture services."""
from .nfl_weekly_playlists import install as _install_nfl_weekly_playlists
from .competition_builder import install as _install_competition_builder
from .competition_builder_v467 import install as _install_competition_builder_v467

_install_nfl_weekly_playlists()
_install_competition_builder()
_install_competition_builder_v467()
