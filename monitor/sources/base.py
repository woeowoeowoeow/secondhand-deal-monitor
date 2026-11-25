from __future__ import annotations

import os

from ..models import Listing


class SourceNotConfigured(Exception):
    pass


class Source:
    name = "base"
    display = "Base"
    required_env: tuple[str, ...] = ()

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.scfg = cfg.get("sources", {}).get(self.name, {})

    def enabled(self) -> bool:
        return bool(self.scfg.get("enabled", False))

    def missing_env(self) -> list[str]:
        return [e for e in self.required_env if not os.environ.get(e)]

    def fetch(self) -> list[Listing]:
        """Return current candidate listings. Raise on failure (health tracking)."""
        raise NotImplementedError

    def enrich(self, listing: Listing) -> Listing:
        """Optionally fetch full details (description, specs) for a candidate."""
        return listing
