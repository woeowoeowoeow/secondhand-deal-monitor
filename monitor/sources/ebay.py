"""eBay via the official Browse API (OAuth client-credentials, free developer keyset).

Uses eBay's own local-pickup radius search, so shipping-only items are never returned.
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime

from .. import http
from ..models import Listing
from .base import Source

log = logging.getLogger(__name__)

API = "https://api.ebay.com"
SCOPE = "https://api.ebay.com/oauth/api_scope"


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class EbaySource(Source):
    name = "ebay"
    display = "eBay"
    required_env = ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._token: str | None = None

    def token(self) -> str:
        if self._token:
            return self._token
        cred = f"{os.environ['EBAY_CLIENT_ID']}:{os.environ['EBAY_CLIENT_SECRET']}"
        r = http.request("POST", f"{API}/identity/v1/oauth2/token", headers={
            "Authorization": "Basic " + base64.b64encode(cred.encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        }, data={"grant_type": "client_credentials", "scope": SCOPE})
        self._token = json.loads(r)["access_token"]
        return self._token

    def _headers(self) -> dict:
        zip_ = self.cfg["location"]["postal_code"]
        return {
            "Authorization": f"Bearer {self.token()}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "X-EBAY-C-ENDUSERCTX": "contextualLocation=" + urllib.parse.quote(f"country=US,zip={zip_}"),
            "Accept": "application/json",
        }

    def search_params(self, product: dict) -> dict:
        loc = self.cfg["location"]
        filters = [
            "deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}",
            "pickupCountry:US",
            f"pickupPostalCode:{loc['postal_code']}",
            f"pickupRadius:{loc['radius_miles']}",
            "pickupRadiusUnit:mi",
            f"price:[..{product['max_price']}]",
            "priceCurrency:USD",
        ]
        p = {"q": product["ebay_query"], "filter": ",".join(filters), "sort": "newlyListed",
             "limit": "200", "fieldgroups": "EXTENDED"}
        if product.get("ebay_category"):
            p["category_ids"] = product["ebay_category"]
        return p

    def fetch(self) -> list[Listing]:
        out: dict[str, Listing] = {}
        for product in self.cfg["products_by_id"].values():
            if not product.get("ebay_query"):
                continue
            data = http.get_json(f"{API}/buy/browse/v1/item_summary/search",
                                 headers=self._headers(), params=self.search_params(product))
            items = data.get("itemSummaries", [])
            log.info("ebay '%s': %d results (total %s)", product["ebay_query"], len(items), data.get("total"))
            for it in items:
                lst = self.from_summary(it)
                out[lst.key] = lst
        return list(out.values())

    @staticmethod
    def from_summary(it: dict) -> Listing:
        loc = it.get("itemLocation", {}) or {}
        seller = it.get("seller", {}) or {}
        price = it.get("price") or {}
        pct = seller.get("feedbackPercentage")
        return Listing(
            source="ebay",
            source_id=it["itemId"],
            title=it.get("title", ""),
            price=float(price["value"]) if price.get("currency") == "USD" and price.get("value") else None,
            url=it.get("itemWebUrl", ""),
            description=it.get("shortDescription", ""),
            condition=it.get("condition", ""),
            location=", ".join(x for x in [loc.get("city"), loc.get("stateOrProvince"), loc.get("postalCode")] if x),
            postal_code=loc.get("postalCode", ""),
            posted_at=parse_time(it.get("itemCreationDate") or it.get("itemOriginDate")),
            local_pickup=True,  # guaranteed by the pickup filter in the search
            buying_options=it.get("buyingOptions", []),
            category_ids=[c.get("categoryId") for c in it.get("categories", [])],
            seller_feedback_score=seller.get("feedbackScore"),
            seller_feedback_pct=float(pct) if pct not in (None, "") else None,
            marketplace="eBay",
        )

    def enrich(self, listing: Listing) -> Listing:
        it = http.get_json(f"{API}/buy/browse/v1/item/{urllib.parse.quote(listing.source_id, safe='')}",
                           headers=self._headers())
        loc = it.get("itemLocation", {}) or {}
        listing.description = " ".join(filter(None, [it.get("shortDescription"), strip_html(it.get("description", ""))]))[:8000]
        listing.aspects = {a["name"].lower(): a.get("value", "") for a in it.get("localizedAspects", []) if a.get("name")}
        listing.condition = it.get("condition") or listing.condition
        if it.get("conditionDescription"):
            listing.description += " " + it["conditionDescription"]
        if loc:
            listing.postal_code = loc.get("postalCode", listing.postal_code)
            listing.location = ", ".join(x for x in [loc.get("city"), loc.get("stateOrProvince"), loc.get("postalCode")] if x) or listing.location
        avail = it.get("estimatedAvailabilities") or []
        if avail and all(a.get("estimatedAvailabilityStatus") == "OUT_OF_STOCK" for a in avail):
            listing.sold = True
        pickup = it.get("pickupOptions") or []
        if pickup or listing.local_pickup:
            listing.local_pickup = True
        return listing
