"""Marketplace alert emails, received through a private ntfy "intake" topic.

Platforms that block automated access still send their own alert emails
(Craigslist saved-search alerts, F5Bot Reddit keyword alerts, ...). Those
emails are addressed to  ntfy-<INTAKE_TOPIC>@ntfy.sh ; ntfy turns each one
into a message on the intake topic (cached 12 h). This source polls the topic,
splits every email into (text, URL) blocks, and turns blocks that point at a
known marketplace into Listing objects for the normal matcher.

Note: ntfy keeps only the plain-text part of an email (HTML links are lost),
so senders must include a text/plain part with the listing URLs.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

from .. import http
from ..models import Listing
from .base import Source
from .reddit import LOCAL, SHIP_ONLY, find_town, prices_in, split_hardwareswap_title

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
CL_LISTING = re.compile(r"https?://[a-z]+\.craigslist\.org/(?:[a-z]+/)*[a-z]{3}/d/[^\s]+?/(\d{8,12})\.html")
REDDIT_POST = re.compile(r"https?://(?:www\.|old\.)?reddit\.com/r/(\w+)/comments/(\w+)")
OFFERUP_ITEM = re.compile(r"https?://(?:www\.)?offerup\.com/item/detail/([\w-]+)")
NOISE = re.compile(r"(unsubscribe|manage (your )?(alerts|searches)|view all|see all|log ?in|"
                   r"privacy|terms|f5bot|keyword:|you are receiving|notification settings)", re.I)


def blocks(text: str) -> list[tuple[str, str]]:
    """Split an alert email into (context text, url) pairs: the text right before/around each URL."""
    out = []
    pos = 0
    for m in URL_RE.finditer(text):
        before = text[pos:m.start()]
        # context = the paragraph directly before the URL (alerts put one listing per paragraph/line)
        para = re.split(r"\n\s*\n", before.rstrip())[-1]
        lines = [ln.strip(" -–•*\t") for ln in para.splitlines() if ln.strip()]
        lines = [ln for ln in lines if not NOISE.search(ln)][-3:]
        out.append((" ".join(lines).strip(), m.group(0).rstrip(".,;")))
        pos = m.end()
    return out


def _price(ctx: str) -> float | None:
    ps = prices_in(ctx)
    return min(ps) if ps else None


def block_to_listing(ctx: str, url: str, received: datetime, cfg: dict) -> Listing | None:
    towns = cfg["location"]["allowed_towns"]
    if m := CL_LISTING.match(url):
        # Craigslist alert lines look like: "RTX 5070 Ti 16GB - $550 (johns creek)"
        loc = re.search(r"\(([^()]{2,40})\)\s*$", ctx)
        title = re.sub(r"\s*\([^()]*\)\s*$", "", ctx)
        title = re.sub(r"\s*[-–]?\s*\$\s?\d[\d,]*(\.\d\d)?\s*", " ", title).strip()
        location = loc[1] if loc else (find_town(ctx, towns) or "")
        return Listing(source="craigslist", source_id=m[1], title=title or ctx, price=_price(ctx), url=url,
                       description=ctx, condition="used (Craigslist)", location=location,
                       posted_at=received, local_pickup=True, marketplace="Craigslist (alert email)")
    if m := REDDIT_POST.match(url):
        sub = m[1].lower()
        have = ctx
        if sub == "hardwareswap":
            if not re.search(r"\[usa-ga\]", ctx, re.I):
                return None
            have, _ = split_hardwareswap_title(ctx)
        local = bool(LOCAL.search(ctx)) and not SHIP_ONLY.search(ctx)
        town = find_town(ctx, towns) or ("atlanta" if sub == "atllist" else None)
        return Listing(source="reddit", source_id=m[2], title=have, price=_price(ctx), url=url,
                       description=ctx, condition="used (per post)", location=f"{town.title()}, GA" if town else "",
                       posted_at=received, local_pickup=local and bool(town), shipping_only=not local,
                       marketplace=f"Reddit r/{m[1]} (F5Bot alert)")
    if m := OFFERUP_ITEM.match(url):
        town = find_town(ctx, towns)
        return Listing(source="offerup", source_id=m[1], title=ctx, price=_price(ctx), url=url,
                       description=ctx, condition="", location=f"{town.title()}, GA" if town else "",
                       posted_at=received, local_pickup=bool(town), marketplace="OfferUp (alert email)")
    return None


class EmailIntakeSource(Source):
    name = "email_intake"
    display = "Alert emails (Craigslist / Reddit via F5Bot / OfferUp)"
    required_env = ("INTAKE_TOPIC",)

    def poll(self, since: str) -> list[dict]:
        server = self.cfg["notify"]["server"].rstrip("/")
        raw = http.request("GET", f"{server}/{os.environ['INTAKE_TOPIC']}/json",
                           params={"poll": "1", "since": since})
        msgs = [json.loads(ln) for ln in raw.decode().splitlines() if ln.strip()]
        msgs = [m for m in msgs if m.get("event") == "message"]
        for m in msgs:   # long emails become attachments
            att = m.get("attachment") or {}
            if att.get("url") and (att.get("type", "").startswith("text") or att.get("name", "").endswith(".txt")):
                try:
                    m["message"] = http.request("GET", att["url"]).decode("utf-8", "replace")
                except Exception as e:  # noqa: BLE001
                    log.warning("could not fetch intake attachment: %s", e)
        return msgs

    def fetch(self) -> list[Listing]:
        meta = self.state.meta if self.state is not None else {}
        since = meta.get("intake_since") or "12h"
        msgs = self.poll(since)
        out = []
        for msg in msgs:
            received = datetime.fromtimestamp(msg.get("time", 0), tz=timezone.utc)
            text = f"{msg.get('title', '')}\n{msg.get('message', '')}"
            n = 0
            for ctx, url in blocks(text):
                lst = block_to_listing(ctx, url, received, self.cfg)
                if lst:
                    out.append(lst)
                    n += 1
            log.info("intake email %r: %d listing links", msg.get("title", "")[:60], n)
        if msgs and self.state is not None:
            meta["intake_since"] = msgs[-1]["id"]
            self.state.dirty = True
        return out
