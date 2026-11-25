"""Entry point: python -m monitor [--dry-run] [--state PATH] [--test-notify]"""
from __future__ import annotations

import argparse
import collections
import logging
import os
import sys
import time

from . import config as config_mod
from . import notify
from .matcher import classify, identify, normalize
from .sources import ALL
from .state import State, fingerprint

log = logging.getLogger("monitor")


def _health(state: State, cfg: dict, source: str, ok: bool, error: str = "", dry: bool = False) -> None:
    h = state.health.setdefault(source, {"fails": 0, "alerted": False, "last_alert": 0, "last_ok": 0})
    now = time.time()
    hc = cfg["health"]
    if ok:
        if h["alerted"] and not dry:
            notify.health_alert(f"Monitor recovered: {source}", f"{source} is working again.", cfg, ok=True)
        if h["fails"] or h["alerted"]:
            state.dirty = True     # only commit state when health actually changes
        h.update(fails=0, alerted=False, last_ok=now, last_error="")
        return
    else:
        h["fails"] += 1
        h["last_error"] = error[:300]
        due = not h["alerted"] or now - h["last_alert"] > hc["repeat_hours"] * 3600
        if h["fails"] >= hc["fail_threshold"] and due and not dry:
            notify.health_alert(f"Monitor problem: {source}",
                                f"{source} failed {h['fails']} runs in a row.\nLast error: {error[:300]}", cfg)
            h.update(alerted=True, last_alert=now)
        state.dirty = True


def run(cfg: dict, state: State, dry: bool = False) -> dict:
    products = cfg["products_by_id"]
    stats = collections.Counter()
    reasons = collections.Counter()
    statuses = {}
    active = 0

    for cls in ALL:
        src = cls(cfg)
        if not src.enabled():
            statuses[src.name] = "disabled in config"
            continue
        missing = src.missing_env()
        if missing:
            statuses[src.name] = f"inactive: missing secrets {', '.join(missing)}"
            continue
        active += 1
        try:
            listings = src.fetch()
        except Exception as e:  # noqa: BLE001 - any failure counts against source health
            log.exception("source %s failed", src.name)
            statuses[src.name] = f"ERROR: {e}"
            _health(state, cfg, src.name, False, str(e), dry)
            continue
        _health(state, cfg, src.name, True, dry=dry)
        statuses[src.name] = f"ok ({len(listings)} listings)"
        stats["listings"] += len(listings)

        for lst in listings:
            found = identify(normalize(lst.title))
            if len(found) != 1 or lst.price is None:
                reasons["prefilter: not exactly one watchlist product"] += 1
                continue
            pid = next(iter(found))
            if pid not in products or lst.price >= products[pid]["max_price"]:
                reasons["prefilter: not under price limit"] += 1
                continue
            fp = fingerprint(pid, lst.title, lst.price)
            fc = cfg["filters"]
            notify_ok, why, prev = state.should_notify(lst.key, fp, lst.price,
                                                       fc["renotify_min_drop_usd"], fc["renotify_min_drop_pct"])
            if not notify_ok:
                reasons[f"dedup: {why}"] += 1
                continue
            if state.recently_rejected(lst.key, lst.price):
                reasons["cached rejection (unchanged)"] += 1
                continue
            try:
                lst = src.enrich(lst)
            except Exception as e:  # noqa: BLE001
                log.warning("enrich failed for %s: %s", lst.key, e)
                stats["enrich_errors"] += 1
            v = classify(lst, products, cfg["filters"], cfg["location"])
            log.info("%s %-60.60s $%s -> %s", "ACCEPT" if v.ok else "reject", lst.title, lst.price, v.reason)
            if not v.ok:
                reasons[v.reason] += 1
                if not dry:
                    state.record_reject(lst.key, lst.price)
                continue
            stats["deals"] += 1
            payload = notify.format_deal(lst, products[v.product_id], v.notes, prev)
            if dry:
                print("\n[DRY RUN] would notify:\n" + payload["title"] + "\n" + payload["message"])
                continue
            notify.send(payload, cfg)
            state.record(lst.key, fp, lst.price)
            stats["notified"] += 1

    if active == 0:
        h = state.meta.setdefault("no_sources", {"last_alert": 0})
        if time.time() - h["last_alert"] > 24 * 3600 and not dry:
            notify.health_alert("Monitor has no active sources",
                                "No marketplace source is configured, so nothing is being checked.\n" +
                                "\n".join(f"{k}: {v}" for k, v in statuses.items()), cfg)
            h["last_alert"] = time.time()
            state.dirty = True

    state.prune()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if state.meta.get("heartbeat") != today:   # daily commit keeps the repo "active" for cron
        state.meta["heartbeat"] = today
        state.dirty = True
    state.meta["last_run"] = int(time.time())
    return {"statuses": statuses, "stats": dict(stats), "reasons": dict(reasons)}


def write_summary(result: dict) -> None:
    lines = ["## Deal monitor run", "", "| source | status |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in result["statuses"].items()]
    lines += ["", f"stats: `{result['stats']}`", "", "| rejection reason | count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(result["reasons"].items(), key=lambda x: -x[1])]
    text = "\n".join(lines)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=os.environ.get("STATE_FILE", "state/state.json"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--dry-run", action="store_true", help="no notifications, no state writes")
    ap.add_argument("--test-notify", action="store_true", help="send one test notification and exit")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_mod.load(args.config)

    if args.test_notify:
        notify.send({"title": "Deal monitor test", "message": "ntfy delivery works. You'll only hear from "
                     "this topic when a qualifying deal appears or monitoring breaks.",
                     "tags": ["white_check_mark"], "priority": 3}, cfg)
        print("test notification sent")
        return 0

    state = State(args.state)
    try:
        result = run(cfg, state, dry=args.dry_run)
    except Exception as e:  # noqa: BLE001 - unexpected crash: track like a failing source
        log.exception("monitor crashed")
        _health(state, cfg, "monitor-core", False, f"{type(e).__name__}: {e}", args.dry_run)
        if not args.dry_run:
            state.save()
        return 1
    _health(state, cfg, "monitor-core", True, dry=args.dry_run)
    write_summary(result)
    if not args.dry_run and state.dirty:
        state.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
