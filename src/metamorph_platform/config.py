"""Settings come from the environment, so secrets never live in files or the repository."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str  # METAMORPH_DATABASE_URL, e.g. postgresql://metamorph:…@localhost:5432/metamorph

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] = os.environ) -> Settings:
        missing = [name for name in ("METAMORPH_DATABASE_URL",) if not environment.get(name)]
        if missing:
            raise ConfigurationError(f"set {', '.join(missing)} (see docker/.env.example)")
        return cls(database_url=environment["METAMORPH_DATABASE_URL"])
