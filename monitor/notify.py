"""ntfy push notifications."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from . import http
from .models import Listing

log = logging.getLogger(__name__)


def _age(posted: datetime | None) -> str:
    if not posted:
        return "unknown"
    secs = (datetime.now(timezone.utc) - posted).total_seconds()
    if secs < 3600:
        return f"{max(1, int(secs // 60))} min ago"
    if secs < 86400:
        return f"{secs / 3600:.1f} h ago"
    return f"{secs / 86400:.1f} days ago"


def format_deal(listing: Listing, product: dict, notes: list[str], prev_price: float | None) -> dict:
    price = f"${listing.price:,.2f}"
    if prev_price:
        price += f" (was ${prev_price:,.2f})"
    lines = [
        f"Product: {product['name']}",
        f"Price: {price}  (limit < ${product['max_price']})",
        f"Condition: {listing.condition or 'not stated'}",
        f"Location: {listing.location or 'not stated'} (local pickup)",
        f"Marketplace: {listing.marketplace}",
        f"Listed: {_age(listing.posted_at)}",
    ]
    if notes:
        lines.append("Notes: " + ", ".join(notes))
    lines += ["", listing.title, listing.url]
    prefix = "Price drop" if prev_price else "Deal"
    return {
        "title": f"{prefix}: {product['name']} {price.split(' ')[0]}",
        "message": "\n".join(lines),
        "click": listing.url,
        "tags": ["moneybag"],
        "priority": 4,
        "actions": [{"action": "view", "label": "Open listing", "url": listing.url}],
    }


def send(payload: dict, cfg: dict) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        log.warning("NTFY_TOPIC not set; would have sent: %s", payload["title"])
        return
    body = {"topic": topic, **payload}
    headers = {}
    if os.environ.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['NTFY_TOKEN']}"
    http.post_json(cfg["notify"]["server"].rstrip("/"), body, headers=headers, retries=4)


def health_alert(title: str, message: str, cfg: dict, ok: bool = False) -> None:
    send({"title": title, "message": message, "tags": ["white_check_mark" if ok else "warning"],
          "priority": 3}, cfg)
