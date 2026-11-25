import unittest

from monitor import config
from monitor.matcher import classify, decode_part_numbers, normalize
from monitor.models import Listing

CFG = config.load()
P = CFG["products_by_id"]


def L(title, price, desc="", aspects=None, **kw):
    base = dict(source="ebay", source_id=title[:40], title=title, price=price, url="https://x/1",
                description=desc, condition=kw.pop("condition", "Used"), postal_code=kw.pop("postal_code", "300**"),
                local_pickup=kw.pop("local_pickup", True), aspects=aspects or {},
                buying_options=kw.pop("buying_options", ["FIXED_PRICE"]))
    base.update(kw)
    return Listing(**base)


def run(listing):
    return classify(listing, P, CFG["filters"], CFG["location"])


# (title, price, desc, aspects, expected product id or None)
CASES = [
    # ------------------------------------------------------------ CPUs: valid
    ("AMD Ryzen 5 9600X 6-Core 12-Thread AM5 Desktop Processor", 139, "", {}, "ryzen5_9600x"),
    ("Ryzen 5 9600x cpu - lightly used", 120, "", {}, "ryzen5_9600x"),
    ("AMD RYZEN 5 9600 X Processor", 130, "", {}, "ryzen5_9600x"),
    ("AMD Ryzen 7 9700X 8-Core AM5 DDR5 PCIe 5.0 Processor", 189.99, "", {}, "ryzen7_9700x"),
    ("R7 9700X tray, no cooler", 175, "", {}, "ryzen7_9700x"),
    ("AMD Ryzen™ 7 9700X — Desktop CPU", 199.99, "", {}, "ryzen7_9700x"),
    # ------------------------------------------------------------ CPUs: invalid
    ("AMD Ryzen 5 9600X", 150, "", {}, None),                     # not strictly below
    ("AMD Ryzen 5 9600X", 151, "", {}, None),
    ("AMD Ryzen 7 9700X", 200, "", {}, None),
    ("AMD Ryzen 5 9600 6-Core Processor", 120, "", {}, None),     # non-X
    ("AMD Ryzen 7 9700 Processor", 150, "", {}, None),            # non-X
    ("AMD Ryzen 7 9800X3D", 150, "", {}, None),
    ("AMD Ryzen 7 7700X", 150, "", {}, None),
    ("Ryzen 7 9700X + ASRock B650I Lightning WiFi combo", 300, "", {}, None),
    ("Ryzen 7 9700X with 32GB DDR5 RAM bundle", 199, "", {}, None),
    ("Ryzen 5 9600X and RTX 5060 Ti", 140, "", {}, None),
    ("Gaming PC Ryzen 7 9700X RTX 5070 Ti 32GB", 199, "", {}, None),
    ("WTB Ryzen 7 9700X", 180, "", {}, None),
    ("Looking for Ryzen 5 9600X", 120, "", {}, None),
    ("AMD Ryzen 7 9700X empty box", 15, "", {}, None),
    ("AMD Ryzen 7 9700X box only", 80, "", {}, None),
    ("CPU cooler for Ryzen 7 9700X", 40, "", {}, None),
    ("Contact frame for AMD Ryzen 9700X AM5", 20, "", {}, None),
    ("AMD Ryzen 7 9700X - bent pins, for parts", 90, "", {}, None),
    ("AMD Ryzen 7 9700X", 150, "Doesn't post, bent pins on socket side", {}, None),
    ("AMD Ryzen 7 9700X SOLD", 180, "", {}, None),
    ("AMD Ryzen 7 9700X", 19, "", {}, None),                      # bait price
    ("AMD Ryzen 7 9700X", 150, "Payment by gift card only", {}, None),
    ("Ryzen 7 9700X vs 9600X lot", 180, "", {}, None),
    ("AMD Ryzen 7 9700X engineering sample", 120, "", {}, None),
    # ------------------------------------------------------------ GPUs: valid
    ("MSI GeForce RTX 5060 Ti 16GB Ventus 2X OC", 360, "", {}, "rtx5060ti_16gb"),
    ("ASUS Dual RTX5060Ti 16G OC Edition", 380, "", {}, "rtx5060ti_16gb"),
    ("Gigabyte RTX 5060 Ti Gaming OC", 370, "", {"memory size": "16 GB", "chipset/gpu model": "NVIDIA GeForce RTX 5060 Ti"}, "rtx5060ti_16gb"),
    ("Zotac RTX 5060-Ti twin edge", 350, "This is the 16GB version, works perfectly.", {}, "rtx5060ti_16gb"),
    ("ASUS TUF Gaming GeForce RTX 5070 Ti 16GB GDDR7 OC", 580, "", {}, "rtx5070ti_16gb"),
    ("RTX 5070ti 16gb Founders style - PNY", 550, "", {}, "rtx5070ti_16gb"),
    ("Gigabyte RTX 5070 Ti Windforce 16GB with box and cables", 599.99, "", {}, "rtx5070ti_16gb"),
    # ------------------------------------------------------------ GPUs: invalid
    ("MSI GeForce RTX 5060 8GB Ventus", 250, "", {}, None),       # non-Ti
    ("MSI GeForce RTX 5060 Ti 8GB Ventus", 300, "", {}, None),    # 8GB
    ("RTX 5060 Ti", 330, "", {}, None),                           # VRAM unverifiable
    ("RTX 5060 Ti", 330, "Great card. Upgraded from my old 8GB card.", {}, None),  # ambiguous
    ("Gigabyte RTX 5060 Ti Gaming OC", 370, "", {"memory size": "8 GB"}, None),
    ("RTX 5060 Ti 16GB laptop GPU", 300, "", {}, None),
    ("Lenovo Legion laptop RTX 5070 Ti 12GB", 550, "", {}, None),
    ("RTX 5070 Ti Mobile 12GB", 400, "", {}, None),
    ("RTX 5070 12GB Founders Edition", 450, "", {}, None),         # non-Ti
    ("RTX 5070 Ti Super 24GB", 590, "", {}, None),
    ("RTX 5070 Ti 16GB", 600, "", {}, None),                      # equal price
    ("RTX 5060 Ti 16GB", 400, "", {}, None),
    ("EKWB water block for RTX 5070 Ti", 120, "", {}, None),
    ("Backplate for RTX 5070 Ti 16GB", 40, "", {}, None),
    ("RTX 5070 Ti 16GB - artifacting, for repair", 300, "", {}, None),
    ("RTX 5070 Ti 16GB", 500, "card is dead, no display", {}, None),
    ("RTX 5070 Ti 16GB + Ryzen 7 9700X", 590, "", {}, None),
    ("[W] RTX 5070 Ti 16GB", 500, "", {}, None),
    ("RTX 5070 Ti 16GB empty box", 30, "", {}, None),
    ("RTX 5070 Ti 16GB", 500, "", {}, None) if False else ("RTX 4070 Ti / RTX 5070 Ti 16GB", 500, "", {}, None),
    ("RTX 5070 Ti 16GB", 500, "", {"chipset/gpu model": "NVIDIA GeForce RTX 5070"}, None),
    # ------------------------------------------------------------ Motherboard: valid
    ("ASRock B650I Lightning WiFi AMD AM5 Mini-ITX Motherboard", 140, "", {}, "asrock_b650i_lightning"),
    ("ASRock B650I Lightning Wi-Fi mITX DDR5 for Ryzen 7000/9000", 150, "", {}, "asrock_b650i_lightning"),
    ("asrock b650i lightning wifi", 120, "", {"model": "B650I Lightning WiFi"}, "asrock_b650i_lightning"),
    # ------------------------------------------------------------ Motherboard: invalid
    ("ASRock B650I Lightning WiFi", 160, "", {}, None),
    ("ASRock B650E PG-ITX WiFi", 150, "", {}, None),
    ("ASRock B650M PG Lightning WiFi", 120, "", {}, None),
    ("ASUS ROG Strix B650E-I Gaming WiFi", 150, "", {}, None),
    ("ASRock B850I Lightning WiFi", 150, "", {}, None),
    ("ASRock B650I Lightning WiFi + Ryzen 5 9600X", 159, "", {}, None),
    ("ASRock B650I Lightning WiFi with 32GB DDR5", 159, "", {}, None),
    ("ASRock B650I Lightning WiFi - bent pins", 70, "", {}, None),
    ("I/O shield for ASRock B650I Lightning", 10, "", {}, None),
    ("ASRock B650I Lightning", 120, "", {"model": "B650E PG-ITX WiFi"}, None),
    # ------------------------------------------------------------ RAM: valid
    ("G.Skill Flare X5 32GB (2x16GB) DDR5 6000 CL30 AMD EXPO", 110, "", {}, "ddr5_32gb_2x16"),
    ("Corsair Vengeance 32GB 2 x 16GB DDR5-6000 C36", 95, "", {}, "ddr5_32gb_2x16"),
    ("Kingston FURY Beast 32GB DDR5 5600MT/s CL36 kit (16GB x 2)", 90, "", {}, "ddr5_32gb_2x16"),
    ("Corsair Vengeance DDR5 32GB CMK32GX5M2B6000C30", 100, "", {}, "ddr5_32gb_2x16"),
    ("G.SKILL Ripjaws S5 F5-6000J3038F16GX2-RS5K DDR5", 105, "", {}, "ddr5_32gb_2x16"),
    ("Kingston FURY Beast DDR5 RAM KF560C30BBEK2-32", 100, "", {}, "ddr5_32gb_2x16"),
    ("TeamGroup T-Force Delta DDR5 FF3D532G6000HC30DC01", 99, "", {}, "ddr5_32gb_2x16"),
    ("32GB DDR5 desktop memory kit", 90, "2x16GB, 6000MHz CL32, EXPO, used for 6 months",
     {}, "ddr5_32gb_2x16"),
    ("Corsair 32GB DDR5 RAM", 90, "",
     {"number of modules": "2", "capacity per module": "16 GB", "bus speed": "PC5-48000 (DDR5-6000)",
      "cas latency": "30"}, "ddr5_32gb_2x16"),
    ("Corsair Vengeance 32GB 2x16GB DDR5 6000 CL30", 174.99, "", {}, "ddr5_32gb_2x16"),
    # ------------------------------------------------------------ RAM: invalid
    ("Corsair Vengeance 32GB 2x16GB DDR5 6000 CL30", 175, "", {}, None),
    ("Corsair Vengeance LPX 32GB (2x16GB) DDR4 3200 CL16", 60, "", {}, None),
    ("Crucial 32GB (2x16GB) DDR5 5600 SODIMM laptop memory", 70, "", {}, None),
    ("Kingston 32GB DDR5 5600 SO-DIMM CL40", 70, "", {}, None),
    ("G.Skill 16GB DDR5 6000 CL30 single stick", 50, "", {}, None),
    ("Corsair 16GB DDR5 6000 CL36", 50, "", {}, None),
    ("G.Skill 64GB (2x32GB) DDR5 6000 CL30", 170, "", {}, None),
    ("Crucial 32GB (1x32GB) DDR5 5600", 80, "", {}, None),
    ("Kingston 32GB (4x8GB) DDR5 5600 CL36", 80, "", {}, None),
    ("G.Skill Trident Z5 32GB (2x16GB) DDR5 6400 CL32", 120, "", {}, None),   # > 6000
    ("Crucial 32GB (2x16GB) DDR5 4800 CL40", 70, "", {}, None),
    ("Crucial Pro 32GB (2x16GB) DDR5 5600 CL46", 75, "", {}, None),           # CL > 36
    ("Crucial 32GB Kit CP2K16G56C46U5 DDR5", 75, "", {}, None),
    ("Corsair 32GB (2x16GB) DDR5 6000", 90, "", {}, None),                    # CL unknown
    ("Corsair DDR5 32GB 6000 CL30", 90, "", {}, None),                        # kit config unknown
    ("Samsung 32GB (2x16GB) DDR5 4800 ECC RDIMM server memory", 80, "", {}, None),
    ("WTB 32GB 2x16GB DDR5 6000 CL30", 100, "", {}, None),
    ("Corsair Vengeance CMK64GX5M2B6000C30 DDR5", 120, "", {}, None),
    ("32GB (2x16GB) DDR5 6000 CL30 - one stick dead", 50, "", {}, None),
    ("Gaming PC Ryzen 7 9700X 32GB DDR5 6000 CL30", 170, "", {}, None),
    # ------------------------------------------------------------ unrelated / ambiguous
    ("Samsung 990 Pro 2TB NVMe SSD", 120, "", {}, None),
    ("Lightning cable for iPhone", 10, "", {}, None),
    ("AMD Ryzen 5 9600X", None, "", {}, None),
]


class TestCases(unittest.TestCase):
    def test_table(self):
        failures = []
        for title, price, desc, aspects, expected in CASES:
            v = run(L(title, price, desc, aspects))
            if v.product_id != expected:
                failures.append(f"{title!r} ${price}: expected {expected}, got {v.product_id} ({v.reason})")
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_case_count(self):
        self.assertGreaterEqual(len(CASES), 100)


class TestFilters(unittest.TestCase):
    def test_shipping_only_rejected(self):
        v = run(L("AMD Ryzen 7 9700X", 150, local_pickup=False, shipping_only=True))
        self.assertIsNone(v.product_id)
        self.assertIn("shipping", v.reason)

    def test_out_of_radius_zip_rejected(self):
        v = run(L("AMD Ryzen 7 9700X", 150, postal_code="314**"))   # Savannah
        self.assertIsNone(v.product_id)

    def test_in_radius_zip_ok(self):
        self.assertTrue(run(L("AMD Ryzen 7 9700X", 150, postal_code="30097")).ok)

    def test_auction_rejected(self):
        v = run(L("AMD Ryzen 7 9700X", 50, buying_options=["AUCTION"]))
        self.assertIn("auction", v.reason)

    def test_parts_condition_rejected(self):
        self.assertFalse(run(L("AMD Ryzen 7 9700X", 150, condition="For parts or not working")).ok)

    def test_bad_seller_rejected(self):
        v = run(L("AMD Ryzen 7 9700X", 150, seller_feedback_score=50, seller_feedback_pct=80.0))
        self.assertFalse(v.ok)

    def test_reddit_location_requires_town(self):
        lst = L("RTX 5070 Ti 16GB", 550, source="reddit", postal_code="", location="Savannah, GA")
        self.assertFalse(run(lst).ok)
        lst.location = "Lawrenceville, GA"
        self.assertTrue(run(lst).ok)

    def test_ram_notes_preferred(self):
        v = run(L("G.Skill Flare X5 32GB (2x16GB) DDR5 6000 CL30 AMD EXPO low profile", 110))
        self.assertIn("★ preferred spec", v.notes)


class TestNormalize(unittest.TestCase):
    def test_variants(self):
        self.assertIn("5070 ti", normalize("RTX5070Ti"))
        self.assertIn("5060 ti", normalize("rtx 5060-ti"))
        self.assertIn("2x16gb", normalize("2 x 16 GB"))
        self.assertIn("16gbx2", normalize("16GB x 2"))
        self.assertIn("cl30", normalize("C30"))
        self.assertIn("6000mts", normalize("6000 MT/s"))
        self.assertIn("wifi", normalize("Wi-Fi"))
        self.assertIn("9700x", normalize("9700 X"))

    def test_part_numbers(self):
        s = decode_part_numbers("CMK32GX5M2B6000C30")[0]
        self.assertEqual((s.total_gb, s.modules, s.per_gb, s.speed, s.cl), (32, 2, 16, 6000, 30))
        s = decode_part_numbers("F5-6000J3038F16GX2-TZ5NR")[0]
        self.assertEqual((s.total_gb, s.modules, s.speed, s.cl), (32, 2, 6000, 30))
        s = decode_part_numbers("KF556C36BBEK2-32")[0]
        self.assertEqual((s.total_gb, s.modules, s.speed, s.cl), (32, 2, 5600, 36))


if __name__ == "__main__":
    unittest.main()
