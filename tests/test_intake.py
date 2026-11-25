import unittest
from datetime import datetime, timezone
from unittest import mock

from monitor import config
from monitor.matcher import classify
from monitor.sources.email_intake import EmailIntakeSource, block_to_listing, blocks
from monitor.state import State

CFG = config.load()
NOW = datetime.now(timezone.utc)

CRAIGSLIST_ALERT = """new results for your saved search "5070 ti"

RTX 5070 Ti 16GB Gigabyte Windforce - $520 (johns creek)
https://atlanta.craigslist.org/nat/sop/d/johns-creek-rtx-5070-ti-16gb/7801234567.html

RTX 5070 Ti laptop - $900 (alpharetta)
https://atlanta.craigslist.org/nat/sys/d/alpharetta-rtx-5070-ti-laptop/7801234568.html

Gaming PC RTX 5070 Ti - $1400 (duluth)
https://atlanta.craigslist.org/gwn/sys/d/duluth-gaming-pc/7801234569.html

manage your saved searches: https://accounts.craigslist.org/savesearch
"""

F5BOT_ALERT = """Reddit Posts (2):

Keyword: 5070 ti
r/hardwareswap: [USA-GA] [H] MSI RTX 5070 Ti 16GB Ventus, $560 local cash Johns Creek [W] Local Cash, PayPal
https://www.reddit.com/r/hardwareswap/comments/1abcdef/usaga_h_msi_rtx_5070_ti/

r/hardwareswap: [USA-TX] [H] RTX 5070 Ti 16GB $550 [W] PayPal
https://www.reddit.com/r/hardwareswap/comments/1zzzzzz/usatx_h_rtx_5070_ti/

Unsubscribe: https://f5bot.com/unsubscribe/xyz
"""


def accepted(text):
    out = []
    for ctx, url in blocks(text):
        lst = block_to_listing(ctx, url, NOW, CFG)
        if lst:
            v = classify(lst, CFG["products_by_id"], CFG["filters"], CFG["location"])
            out.append((lst, v))
    return out


class TestIntake(unittest.TestCase):
    def test_craigslist_alert(self):
        res = accepted(CRAIGSLIST_ALERT)
        self.assertEqual(len(res), 3)                       # boilerplate link ignored
        ok = [(l, v) for l, v in res if v.ok]
        self.assertEqual(len(ok), 1, [(l.title, v.reason) for l, v in res])
        lst = ok[0][0]
        self.assertEqual((lst.price, lst.location, lst.source_id), (520, "johns creek", "7801234567"))
        self.assertIn("7801234567.html", lst.url)
        self.assertEqual(lst.title, "RTX 5070 Ti 16GB Gigabyte Windforce")

    def test_f5bot_reddit_alert(self):
        res = accepted(F5BOT_ALERT)
        self.assertEqual(len(res), 1)                       # only the [USA-GA] post
        lst, v = res[0]
        self.assertTrue(v.ok, v.reason)
        self.assertEqual(lst.price, 560)
        self.assertEqual(lst.location, "Johns Creek, GA")

    def test_poll_cursor_persisted(self):
        st = State("/nonexistent/s.json")
        src = EmailIntakeSource(CFG)
        src.state = st
        msgs = [{"id": "m1", "time": NOW.timestamp(), "event": "message", "title": "x", "message": CRAIGSLIST_ALERT}]
        with mock.patch.object(EmailIntakeSource, "poll", return_value=msgs) as p:
            out = src.fetch()
            self.assertEqual(p.call_args[0][0], "12h")
        self.assertEqual(len(out), 3)
        self.assertEqual(st.meta["intake_since"], "m1")
        with mock.patch.object(EmailIntakeSource, "poll", return_value=[]) as p:
            src.fetch()
            self.assertEqual(p.call_args[0][0], "m1")


if __name__ == "__main__":
    unittest.main()
