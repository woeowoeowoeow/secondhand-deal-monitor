"""Facebook Marketplace placeholder (intentionally excluded for now).

Meta offers no public Marketplace search API. To add it later, implement
fetch() to return Listing objects (source="facebook", local_pickup=True for
pickup listings, location/postal_code filled), set
[sources.facebook] enabled = true in config.toml, and add any required
secrets to required_env + the workflow env block. The shared matcher,
dedup, location and notification pipeline need no changes.
"""
from __future__ import annotations

from ..models import Listing
from .base import Source


class FacebookSource(Source):
    name = "facebook"
    display = "Facebook Marketplace"

    def fetch(self) -> list[Listing]:
        raise NotImplementedError("Facebook Marketplace source not implemented (excluded by request)")
