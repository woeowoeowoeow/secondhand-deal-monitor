"""Reddit (r/hardwareswap, r/ATLlist, ...) via the official OAuth Data API.

Reddit blocks unauthenticated access, and since Nov 2025 new API credentials
require Reddit's approval (Responsible Builder Policy). This source therefore
stays inactive until REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET secrets exist.

Each post is split into per-item listings: every line (or the [H] part of the
title) that names a watchlist product *and* carries a price becomes a Listing.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone

from .. import http
from ..matcher import identify, normalize
from ..models import Listing
from .base import Source

log = logging.getLogger(__name__)

PRICE = re.compile(r"\$\s?(\d{2,4}(?:,\d{3})?(?:\.\d{2})?)|\b(\d{2,4})\s?(?:\$|usd|obo|firm|local|shipped|cash)\b", re.I)
LOCAL = re.compile(r"\blocal\b|\bpick ?up\b|\bmeet ?up\b|\bin person\b|\bcash\b", re.I)
SHIP_ONLY = re.compile(r"\b(no local|shipping only|ship only|will not meet|no meetups?)\b", re.I)
SOLD_FLAIR = {"sold", "closed", "trade completed", "purchased", "completed"}


def prices_in(text: str) -> list[float]:
    vals = []
    for a, b in PRICE.findall(text):
        v = float((a or b).replace(",", ""))
        if 10 <= v <= 5000:
            vals.append(v)
    return vals


def find_town(text: str, towns: list[str]) -> str | None:
    low = text.lower()
    for t in sorted(towns, key=len, reverse=True):
        if re.search(rf"\b{re.escape(t)}\b", low):
            return t
    m = re.search(r"\b(30[0-3]|30[56])\d{2}\b", low)
    return m[0] if m else None


def split_hardwareswap_title(title: str) -> tuple[str, str]:
    """'[USA-GA] [H] RTX 5070 Ti [W] PayPal, Local Cash' -> (have, want)."""
    m = re.search(r"\[h\](.*?)(\[w\](.*))?$", title, re.I | re.S)
    if not m:
        return title, ""
    return m[1].strip(), (m[3] or "").strip()


def post_to_listings(post: dict, cfg: dict) -> list[Listing]:
    sub = post.get("subreddit", "").lower()
    title = post.get("title", "")
    body = post.get("selftext", "") or ""
    flair = (post.get("link_flair_text") or "").strip().lower()
    url = "https://www.reddit.com" + post.get("permalink", "")
    created = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)
    towns = cfg["location"]["allowed_towns"]

    if sub == "hardwareswap":
        if not re.search(r"\[usa-ga\]", title, re.I):
            return []
        if flair and flair not in ("selling", "buying") and flair in SOLD_FLAIR:
            return []
        have, _want = split_hardwareswap_title(title)
        if re.search(r"^\s*(paypal|cash|local cash|money)\b", have, re.I):  # a buying post
            return []
    else:
        have = title
        if flair in SOLD_FLAIR:
            return []

    full = f"{title}\n{body}"
    local = bool(LOCAL.search(full)) and not SHIP_ONLY.search(full)
    town = find_town(full, towns)
    if not town and sub == "atllist":
        town = "Atlanta area (r/ATLlist)"
    location = f"{town.title()}, GA" if town and not town.startswith("Atlanta area") else (town or "")

    candidates: list[tuple[int, str, float]] = []
    lines = [have] + [ln.strip() for ln in body.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if "~~" in line:          # struck-through = sold
            continue
        if not identify(normalize(line)):
            continue
        ps = prices_in(line)
        if ps:
            candidates.append((i, line, min(ps)))
    if not candidates and identify(normalize(have)):
        ps = sorted(set(prices_in(full)))
        if len(ps) == 1:
            candidates.append((0, have, ps[0]))

    out = []
    for i, line, price in candidates:
        out.append(Listing(
            source="reddit",
            source_id=f"{post['id']}:{i}",
            title=re.sub(r"[*_#>|]", " ", line),
            price=price,
            url=url,
            description=body[:6000],
            condition="used (per post)",
            location=location if town else "",
            posted_at=created,
            local_pickup=local and bool(town),
            shipping_only=not local,
            marketplace=f"Reddit r/{post.get('subreddit', sub)}",
        ))
    return out


class RedditSource(Source):
    name = "reddit"
    display = "Reddit"
    required_env = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")

    def _token(self) -> str:
        cred = f"{os.environ['REDDIT_CLIENT_ID']}:{os.environ['REDDIT_CLIENT_SECRET']}"
        r = http.request("POST", "https://www.reddit.com/api/v1/access_token", headers={
            "Authorization": "Basic " + base64.b64encode(cred.encode()).decode(),
            "User-Agent": self.scfg["user_agent"],
        }, data={"grant_type": "client_credentials"})
        return json.loads(r)["access_token"]

    def fetch(self) -> list[Listing]:
        headers = {"Authorization": f"bearer {self._token()}", "User-Agent": self.scfg["user_agent"]}
        out = []
        for sub in self.scfg.get("subreddits", []):
            data = http.get_json(f"https://oauth.reddit.com/r/{sub}/new", headers=headers,
                                 params={"limit": 100, "raw_json": 1})
            posts = [c["data"] for c in data.get("data", {}).get("children", [])]
            log.info("reddit r/%s: %d posts", sub, len(posts))
            for p in posts:
                out.extend(post_to_listings(p, self.cfg))
        return out
