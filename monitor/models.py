"""Shared data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Listing:
    source: str                 # e.g. "ebay", "reddit"
    source_id: str              # id unique within the source
    title: str
    price: float | None         # USD; None if unknown
    url: str
    description: str = ""       # free text used for verification
    condition: str = ""
    location: str = ""          # human readable, e.g. "Duluth, GA 30096"
    postal_code: str = ""       # may be partially masked ("300**")
    posted_at: datetime | None = None
    local_pickup: bool = False  # buyer can pick up in person
    shipping_only: bool = False
    aspects: dict[str, str] = field(default_factory=dict)   # structured specs (lower-cased keys)
    buying_options: list[str] = field(default_factory=list)  # e.g. FIXED_PRICE, AUCTION
    category_ids: list[str] = field(default_factory=list)
    seller_feedback_score: int | None = None
    seller_feedback_pct: float | None = None
    sold: bool = False
    marketplace: str = ""       # display name, e.g. "eBay"

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass
class Verdict:
    product_id: str | None      # matched product id, None when rejected
    reason: str                 # why accepted/rejected (for logs & tests)
    notes: list[str] = field(default_factory=list)  # extra info shown in the alert

    @property
    def ok(self) -> bool:
        return self.product_id is not None
