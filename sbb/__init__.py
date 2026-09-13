"""Sports Big Board architecture services.

Backend services retain their existing install behavior, but startup ownership is
now centralized in ``sbb.startup`` so registration order and startup results are
explicit and inspectable.
"""
from .startup import STARTUP_REGISTRATIONS, bootstrap, startup_snapshot

bootstrap()

__all__ = ["STARTUP_REGISTRATIONS", "bootstrap", "startup_snapshot"]
