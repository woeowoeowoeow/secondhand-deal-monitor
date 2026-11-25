"""Persistent dedup + source health state (a JSON file kept on the `state` branch).

Listing keys are stored as salted SHA-256 digests so the (public) state branch
does not reveal what is being watched or which listings were alerted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

RETENTION_DAYS = 60
CROSS_SOURCE_DAYS = 7
REJECT_DAYS = 3


def _h(s: str) -> str:
    salt = os.environ.get("STATE_SALT", "")
    return hashlib.sha256(f"{salt}|{s}".encode()).hexdigest()[:24]


def fingerprint(product_id: str, title: str, price: float) -> str:
    """Cross-platform identity: same product, price and title words → same item reposted."""
    words = sorted(set(re.findall(r"[a-z0-9]+", title.lower())))
    return f"{product_id}|{round(price)}|{' '.join(words)[:120]}"


class State:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        data = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                data = {}
        self.seen: dict[str, dict] = data.get("seen", {})
        self.fps: dict[str, float] = data.get("fps", {})
        self.rejects: dict[str, dict] = data.get("rejects", {})
        self.health: dict[str, dict] = data.get("health", {})
        self.meta: dict = data.get("meta", {})
        self.dirty = False

    # ------------------------------------------------------------ dedup
    def should_notify(self, key: str, fp: str, price: float, min_drop_usd: float, min_drop_pct: float
                      ) -> tuple[bool, str, float | None]:
        """Returns (notify?, reason, previous_price)."""
        rec = self.seen.get(_h(key))
        if rec is None:
            fpt = self.fps.get(_h(fp))
            if fpt and time.time() - fpt < CROSS_SOURCE_DAYS * 86400:
                return False, "duplicate of a listing already alerted on another platform", None
            return True, "new", None
        prev = rec["p"]
        drop = prev - price
        if drop >= min_drop_usd and drop >= prev * min_drop_pct:
            return True, "price drop", prev
        return False, "already alerted", prev

    def record(self, key: str, fp: str, price: float) -> None:
        now = time.time()
        k = _h(key)
        rec = self.seen.get(k)
        # keep the lowest alerted price so tiny oscillations don't re-alert
        self.seen[k] = {"p": min(price, rec["p"]) if rec else price, "t": now}
        self.fps[_h(fp)] = now
        self.dirty = True

    # ------------------------------------------------------------ reject cache
    def recently_rejected(self, key: str, price: float) -> bool:
        """Same listing at the same (or higher) price was rejected within REJECT_DAYS."""
        rec = self.rejects.get(_h(key))
        return bool(rec) and price >= rec["p"] and time.time() - rec["t"] < REJECT_DAYS * 86400

    def record_reject(self, key: str, price: float) -> None:
        self.rejects[_h(key)] = {"p": price, "t": time.time()}
        self.dirty = True

    def prune(self) -> None:
        cutoff = time.time() - RETENTION_DAYS * 86400
        reject_cutoff = time.time() - REJECT_DAYS * 86400
        for d, getter, cut in ((self.seen, lambda v: v["t"], cutoff), (self.fps, lambda v: v, cutoff),
                               (self.rejects, lambda v: v["t"], reject_cutoff)):
            for k in [k for k, v in d.items() if getter(v) < cut]:
                del d[k]
                self.dirty = True

    # ------------------------------------------------------------ save
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"seen": self.seen, "fps": self.fps, "rejects": self.rejects, "health": self.health, "meta": self.meta}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
        tmp.replace(self.path)
