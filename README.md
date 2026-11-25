# Secondhand PC hardware deal monitor

Checks local-pickup listings within 50 miles of Duluth, GA (30097) on a schedule.
When a watchlist part is listed **strictly below** your price limit, it pushes an
alert to a private [ntfy](https://ntfy.sh) topic. Runs on GitHub Actions at $0. Python stdlib only, no paid APIs.

## How it works

```
GitHub Actions cron (*/5) ─► python -m monitor
   sources/ (eBay Browse API, Reddit OAuth, …) ─► Listing objects
   matcher.py  precision filter: exact model/variant, price, pickup radius, scams, bundles…
   state.py    dedup across runs + platforms, price-drop re-alerts, source health
   notify.py   ntfy push (product, price, condition, location, marketplace, age, link)
state/state.json ─► committed to the `state` branch (keys are salted SHA-256 hashes)
```

## Sources

| Source | Status | Notes |
|---|---|---|
| eBay | Implemented. **Needs free API keys** (`EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`) | Official Browse API, `deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}` + 50 mi radius from 30097. ~1.8k of the 5k/day default calls. |
| Reddit r/hardwareswap, r/ATLlist | Implemented, **inactive** | Reddit blocks unauthenticated access, and since Nov 2025 new API credentials require Reddit's manual approval. Add `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` if you're approved. Only `[USA-GA]` posts offering local pickup in a listed metro town count. |
| Craigslist | Unsupported | No API. Craigslist blocks automated clients (HTTP 403), and its terms forbid scraping. |
| OfferUp, Nextdoor | Unsupported | No public API. Login or app only. |
| Mercari, Jawa, Swappa, Poshmark | Excluded | Shipping-only platforms, which the local-pickup requirement rules out. |
| Facebook Marketplace | Excluded (stub ready) | See below. |

A source runs only when it's enabled in `config.toml` **and** its secrets exist.
A source with missing secrets is reported as inactive in every run summary and is never shown as working.

## Configuration (`config.toml`)

* `[[products]]`: name, `max_price` (alerts only strictly below it), eBay query and category, `enabled`.
  Variant rules (e.g. reject 5060 Ti 8GB, SO-DIMMs, CL>36) live in `monitor/matcher.py`, one function per product.
* `[location]`: ZIP, radius, allowed ZIP3 prefixes, and town names used for free-text sources.
* `[filters]`: bait-price floor, re-alert thresholds for price drops, auctions on/off.
* `[health]`: consecutive failures before a "Monitor problem" alert, and the repeat interval.

Secrets (GitHub → Settings → Secrets → Actions): `NTFY_TOPIC`, `STATE_SALT`,
`EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, optional `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `NTFY_TOKEN`.

## Getting eBay keys (free, about 5 min)

1. Sign in at <https://developer.ebay.com/my/keys> and accept the API License Agreement.
2. Create a **Production** keyset and copy the *App ID (Client ID)* and *Cert ID (Client Secret)*.
3. Store them by running `EBAY_CLIENT_ID=... EBAY_CLIENT_SECRET=... scripts/deploy.sh`, or with
   `gh secret set EBAY_CLIENT_ID` and `gh secret set EBAY_CLIENT_SECRET`.

## Notifications

* Deals: one push per qualifying listing. Tapping it opens the listing.
* Price drops: a re-alert only when the price falls ≥ $10 **and** ≥ 5% below the last alerted price.
* Health: "Monitor problem: <source>" after 3 consecutive failed runs, repeated at most every 12 h, plus a "recovered" message. If no source is active, one reminder per day.
* Nothing else is sent: no heartbeats or "no deals" messages.

## Adding Facebook Marketplace later

Implement `fetch()` in `monitor/sources/facebook.py` to return `Listing` objects, then set
`[sources.facebook] enabled = true`. Add any secrets to `required_env` and the workflow `env:` block.
Matching, dedup, location checks and alerts work unchanged.

## Local commands

```bash
python3 -m unittest discover -s tests -t . -v           # tests (100+ listing cases)
EBAY_CLIENT_ID=… EBAY_CLIENT_SECRET=… python3 -m monitor --dry-run   # live check, no alerts/state
NTFY_TOPIC=… python3 -m monitor --test-notify            # test push
gh workflow run deal-monitor -f test_notify=true         # test push from the cloud
```

## Cost and schedule

The repo is public, so GitHub-hosted Actions minutes are free and unlimited, and storage is a small JSON file on the `state` branch.
The cron asks for runs every 5 minutes, GitHub's minimum. GitHub starts scheduled runs on a best-effort basis, so actual gaps are often 5–15+ minutes under load.
A daily state commit keeps the repo active, so GitHub doesn't disable the schedule after 60 days of inactivity.
