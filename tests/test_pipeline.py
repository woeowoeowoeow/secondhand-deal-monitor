import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from monitor import config, main, notify
from monitor.models import Listing
from monitor.sources.ebay import EbaySource
from monitor.sources.reddit import post_to_listings
from monitor.state import State, fingerprint

CFG = config.load()

EBAY_SUMMARY = {
    "itemId": "v1|123456789|0",
    "title": "MSI GeForce RTX 5070 Ti 16GB Gaming Trio OC",
    "price": {"value": "549.99", "currency": "USD"},
    "condition": "Used",
    "itemLocation": {"postalCode": "300**", "country": "US", "city": "Duluth", "stateOrProvince": "Georgia"},
    "itemWebUrl": "https://www.ebay.com/itm/123456789",
    "itemCreationDate": "2026-11-24T10:00:00.000Z",
    "buyingOptions": ["FIXED_PRICE", "BEST_OFFER"],
    "categories": [{"categoryId": "27386"}],
    "seller": {"feedbackScore": 250, "feedbackPercentage": "100.0", "username": "x"},
}
EBAY_ITEM = {
    "description": "<p>Works great, never mined. <b>16GB GDDR7</b></p>",
    "localizedAspects": [{"name": "Memory Size", "value": "16 GB"},
                         {"name": "Chipset/GPU Model", "value": "NVIDIA GeForce RTX 5070 Ti"}],
    "condition": "Used",
    "itemLocation": {"postalCode": "30097", "city": "Duluth", "stateOrProvince": "GA", "country": "US"},
    "pickupOptions": [{"pickupLocationType": "LOCAL_PICKUP"}],
}


class FakeEbay(EbaySource):
    def __init__(self, cfg, summaries=None, fail=False):
        super().__init__(cfg)
        self._summaries = summaries if summaries is not None else [EBAY_SUMMARY]
        self._fail = fail

    def enabled(self):
        return True

    def missing_env(self):
        return []

    def fetch(self):
        if self._fail:
            raise RuntimeError("HTTP 503")
        return [self.from_summary(s) for s in self._summaries]

    def enrich(self, listing):
        with mock.patch("monitor.http.get_json", return_value=EBAY_ITEM):
            with mock.patch.object(EbaySource, "token", return_value="t"):
                return EbaySource.enrich(self, listing)


class TestEbayMapping(unittest.TestCase):
    def test_summary(self):
        lst = EbaySource.from_summary(EBAY_SUMMARY)
        self.assertEqual(lst.price, 549.99)
        self.assertEqual(lst.postal_code, "300**")
        self.assertTrue(lst.local_pickup)
        self.assertEqual(lst.posted_at.year, 2026)

    def test_search_params_enforce_pickup_radius(self):
        p = EbaySource(CFG).search_params(CFG["products_by_id"]["rtx5070ti_16gb"])
        f = p["filter"]
        for part in ["deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}", "pickupPostalCode:30097",
                     "pickupRadius:50", "pickupRadiusUnit:mi", "pickupCountry:US", "price:[..600]"]:
            self.assertIn(part, f)
        self.assertEqual(p["category_ids"], "27386")

    def test_enrich(self):
        src = FakeEbay(CFG)
        lst = src.enrich(EbaySource.from_summary(EBAY_SUMMARY))
        self.assertEqual(lst.aspects["memory size"], "16 GB")
        self.assertIn("16GB GDDR7", lst.description)
        self.assertEqual(lst.postal_code, "30097")


class TestState(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "s.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_dedup_and_price_drop(self):
        s = State(self.path)
        fp = fingerprint("x", "t", 100)
        self.assertTrue(s.should_notify("ebay:1", fp, 100, 10, 0.05)[0])
        s.record("ebay:1", fp, 100)
        s.save()
        s = State(self.path)                               # persisted across runs
        self.assertFalse(s.should_notify("ebay:1", fp, 100, 10, 0.05)[0])
        self.assertFalse(s.should_notify("ebay:1", fp, 95, 10, 0.05)[0])   # small drop
        ok, why, prev = s.should_notify("ebay:1", fp, 85, 10, 0.05)
        self.assertTrue(ok)
        self.assertEqual((why, prev), ("price drop", 100))
        self.assertFalse(s.should_notify("ebay:1", fp, 120, 10, 0.05)[0])  # price increase

    def test_cross_platform_duplicate(self):
        s = State(self.path)
        fp = fingerprint("rtx5070ti_16gb", "RTX 5070 Ti 16GB MSI", 550)
        s.record("ebay:1", fp, 550)
        ok, why, _ = s.should_notify("reddit:abc:0", fingerprint("rtx5070ti_16gb", "MSI RTX 5070 Ti 16GB", 550), 550, 10, .05)
        self.assertFalse(ok)
        self.assertIn("another platform", why)

    def test_keys_are_hashed(self):
        s = State(self.path)
        s.record("ebay:v1|123456789|0", "fp", 1)
        s.save()
        self.assertNotIn("123456789", self.path.read_text())

    def test_prune(self):
        s = State(self.path)
        s.seen["old"] = {"p": 1, "t": time.time() - 90 * 86400}
        s.prune()
        self.assertNotIn("old", s.seen)


class TestReddit(unittest.TestCase):
    def post(self, **kw):
        p = {"id": "abc", "subreddit": "hardwareswap", "permalink": "/r/hardwareswap/comments/abc/x/",
             "created_utc": time.time() - 600, "link_flair_text": "SELLING"}
        p.update(kw)
        return p

    def test_hardwareswap_local_ga(self):
        out = post_to_listings(self.post(
            title="[USA-GA] [H] MSI RTX 5070 Ti 16GB, Ryzen 7 9700X [W] PayPal, Local Cash",
            selftext="Local to Duluth 30097, can ship too.\n\n* MSI RTX 5070 Ti 16GB - $560\n* ~~Ryzen 7 9700X - $190~~ SOLD\n"),
            CFG)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].price, 560)
        self.assertTrue(out[0].local_pickup)
        self.assertEqual(out[0].location, "Duluth, GA")

    def test_hardwareswap_other_state_ignored(self):
        self.assertEqual(post_to_listings(self.post(title="[USA-CA] [H] RTX 5070 Ti [W] PayPal",
                                                    selftext="$500 local only LA"), CFG), [])

    def test_hardwareswap_buying_post_ignored(self):
        self.assertEqual(post_to_listings(self.post(title="[USA-GA] [H] PayPal, Local Cash [W] RTX 5070 Ti",
                                                    selftext="Paying $550 local Atlanta"), CFG), [])

    def test_hardwareswap_shipping_only(self):
        out = post_to_listings(self.post(title="[USA-GA] [H] RTX 5070 Ti 16GB [W] PayPal",
                                         selftext="RTX 5070 Ti 16GB $550 shipped. Shipping only, Savannah"), CFG)
        self.assertTrue(all(not o.local_pickup for o in out))

    def test_atllist(self):
        out = post_to_listings(self.post(subreddit="ATLlist", link_flair_text="For Sale",
                                         title="[FS] ASRock B650I Lightning WiFi - $130 - Marietta",
                                         selftext="Barely used, cash local pickup."), CFG)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].price, 130)
        self.assertTrue(out[0].local_pickup)

    def test_full_reddit_listing_classifies(self):
        from monitor.matcher import classify
        out = post_to_listings(self.post(
            title="[USA-GA] [H] Gigabyte RTX 5060 Ti 16GB [W] Local Cash",
            selftext="Meet in Lawrenceville. Gigabyte RTX 5060 Ti 16GB Windforce $350 local"), CFG)
        v = classify(out[0], CFG["products_by_id"], CFG["filters"], CFG["location"])
        self.assertTrue(v.ok, v.reason)


class TestRun(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = State(Path(self.dir.name) / "s.json")

    def tearDown(self):
        self.dir.cleanup()

    def _run(self, src):
        sent = []
        with mock.patch.object(main, "ALL", [lambda cfg: src]), \
             mock.patch.object(notify, "send", side_effect=lambda p, c: sent.append(p)):
            res = main.run(CFG, self.state)
        return res, sent

    def test_end_to_end_alert_then_dedup(self):
        res, sent = self._run(FakeEbay(CFG))
        self.assertEqual(len(sent), 1, res)
        msg = sent[0]
        self.assertIn("RTX 5070 Ti", msg["title"])
        for needle in ["$549.99", "Condition: Used", "Duluth", "Marketplace: eBay", "Listed:", "https://www.ebay.com/itm/123456789"]:
            self.assertIn(needle, msg["message"])
        self.assertEqual(msg["click"], "https://www.ebay.com/itm/123456789")
        res, sent = self._run(FakeEbay(CFG))        # second run: deduplicated
        self.assertEqual(sent, [])
        cheaper = dict(EBAY_SUMMARY, price={"value": "499.00", "currency": "USD"})
        res, sent = self._run(FakeEbay(CFG, [cheaper]))   # meaningful drop: renotify
        self.assertEqual(len(sent), 1)
        self.assertIn("was $549.99", sent[0]["message"])

    def test_no_deals_no_notifications(self):
        expensive = dict(EBAY_SUMMARY, price={"value": "650", "currency": "USD"})
        _, sent = self._run(FakeEbay(CFG, [expensive]))
        self.assertEqual(sent, [])

    def test_health_alert_after_threshold_and_recovery(self):
        alerts = []
        for _ in range(CFG["health"]["fail_threshold"] + 2):
            _, sent = self._run(FakeEbay(CFG, fail=True))
            alerts += sent
        self.assertEqual(len(alerts), 1)               # once, not every run
        self.assertIn("problem", alerts[0]["title"])
        _, sent = self._run(FakeEbay(CFG, []))
        self.assertEqual(len(sent), 1)
        self.assertIn("recovered", sent[0]["title"])

    def test_notify_payload_is_json_serialisable(self):
        lst = Listing("ebay", "1", "t", 1.0, "https://u")
        json.dumps(notify.format_deal(lst, {"name": "n", "max_price": 2}, [], None))


if __name__ == "__main__":
    unittest.main()
