"""Precision-first product classification.

classify() decides whether a listing is exactly one watchlist product, in a
qualifying variant, at a qualifying price, with local pickup near the target
location. Anything ambiguous is rejected (precision over recall).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Listing, Verdict

# --------------------------------------------------------------------------- text


def normalize(text: str) -> str:
    t = (text or "").lower()
    t = t.translate(str.maketrans({"–": "-", "—": "-", "×": "x", "™": "", "®": "", " ": " ",
                                   "’": "'", "​": ""}))
    t = re.sub(r"wi[- ]?fi", "wifi", t)
    t = re.sub(r"\brtx\s*-?\s*(\d{4})", r"rtx \1", t)
    t = re.sub(r"\b(\d{4})\s*-?\s*ti\b", r"\1 ti", t)                # 5070ti -> 5070 ti
    t = re.sub(r"\b(\d{4})\s+x\b(?!\s*\d)", r"\1x", t)                # 9700 x -> 9700x
    t = re.sub(r"\b(\d{1,3})\s*-?\s*gb\b", r"\1gb", t)                # 16 gb -> 16gb
    t = re.sub(r"\b(8|12|16|24|32|48|64)\s?g\b", r"\1gb", t)         # 16g -> 16gb
    t = re.sub(r"\b(\d{1,2})\s*(?:x|\*)\s*(\d{1,2})\s*gb\b", r"\1x\2gb", t)   # 2 x 16gb -> 2x16gb
    t = re.sub(r"\b(\d{1,2})gb\s*(?:x|\*)\s*(\d)\b", r"\1gbx\2", t)  # 16gb x 2 -> 16gbx2
    t = re.sub(r"\b(\d{4})\s*(?:mt/s|mts|mhz|mt)\b", r"\1mts", t)
    t = re.sub(r"\bcl\s*-?\s*(\d{2})\b", r"cl\1", t)
    t = re.sub(r"\bc(\d{2})\b", r"cl\1", t)                          # c30 -> cl30
    t = re.sub(r"\bmini[- ]itx\b", "mini-itx", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _any(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


# ---------------------------------------------------------------- shared patterns

WANTED = r"^\W*\[w\]|^\W*(\[[^\]]*\]\s*)*(wtb|want(ed)?|iso|looking for|buying|need|seeking)\b|\b(wtb|in search of|looking to buy)\b"
SOLD = r"\b(sold|pending|ppu|closed|no longer available)\b"
COMPLETE_PC = (r"\b(gaming pc|gaming computer|gaming desktop|gaming rig|desktop pc|desktop computer|prebuilt|"
               r"pre-built|pre built|full build|complete build|complete pc|full pc|pc build|custom pc|"
               r"computer tower|tower pc|workstation|all-in-one|whole pc|entire pc|full system)\b")
COMBO = (r"\b(combo|bundle|lot of|kit with|w/ ?(cpu|gpu|motherboard|mobo|ram|board)|with (cpu|gpu|motherboard|mobo|ram|board))\b|"
         r"\+\s*(cpu|gpu|mobo|motherboard|ram|ddr5|ryzen|rtx|b650i?|asrock|\d+gb)\b")
# accessory words only count when they come BEFORE the product name
# ("Waterblock for RTX 5070 Ti" vs "RTX 5070 Ti with box and cables")
ACCESSORY = (r"\b(backplate|back plate|water ?block|bracket|riser|cables?|shroud|thermal pads?|io shield|i/o shield|"
             r"stickers?|replacement fans?|fan replacement|anti-?sag|delid|contact frame|keychain|display stand|"
             r"skin|decal|dust cover|mounting kit|cooler|aio|heatsink|adapter)\b")
BOX_ONLY = r"\b(empty box|box only|just the box|retail box only|packaging only|manual only|original box only)\b"
FOR_PHRASE = (r"\b(for|fits|compatible with|works with)\s+(the\s+|your\s+|an?\s+)?"
              r"(amd\s+|nvidia\s+|asrock\s+|geforce\s+)?(ryzen|rtx|am5|b650i?|5060|5070|9600x|9700x)")
BROKEN_TITLE = (r"\b(for parts|parts only|not working|non[- ]working|doesn'?t work|does not work|broken|"
                r"defective|dead|faulty|as[- ]is|untested|bent pins?|missing pins?|cracked|artifact(s|ing)?|"
                r"no display|no post|won'?t post|for repair|needs repair|damaged|burnt|burned|melted|"
                r"engineering sample|read description)\b")
BROKEN_DESC = (r"\b(for parts|parts only|not working|non[- ]working|doesn'?t work|does not work|is broken|"
               r"defective|faulty|bent pins?|missing pins?|cracked|artifacting|no display|won'?t post|"
               r"doesn'?t post|burnt|melted|needs repair|for repair)\b")
SCAM_DESC = (r"\b(gift ?cards?|western union|wire transfer|whatsapp|telegram|bitcoin|crypto|usdt|"
             r"moneygram|cashier'?s check|shipping agent|text me at|email me at)\b")

GPU_MODEL = r"\b(?:rtx |gtx )?([2345]0[5-9]0)( ti)?\b"
ANY_GPU = r"\b(rtx|gtx|radeon|geforce|rx ?[5-9]\d{3}|arc [ab]\d{3})\b|" + GPU_MODEL
ANY_CPU_MODEL = r"\b[3579]\d{3}x3?d?\b|\bcore (i[3579]|ultra)\b|\bi[3579]-?\d{4,5}k?f?\b|\bthreadripper\b"
ANY_MOBO = r"\b(motherboard|mobo|mainboard|[abxz][3-8][0-9]0[a-z]?(-[a-z])?)\b"

# ----------------------------------------------------------------- identification

IDENTIFIERS = {
    "ryzen5_9600x": r"\b9600x\b",
    "ryzen7_9700x": r"\b9700x\b",
    "rtx5060ti_16gb": r"\b5060 ti\b",
    "rtx5070ti_16gb": r"\b5070 ti\b",
    "asrock_b650i_lightning": r"\bb650i\b.*\blightning\b|\blightning\b.*\bb650i\b",
}
RAM_CUES = r"\b(ddr5|ram|memory|dimm|udimm)\b"


def product_position(title_n: str) -> int:
    """Index of the first product mention in the title (len(title) if none)."""
    starts = [m.start() for pat in IDENTIFIERS.values() for m in [re.search(pat, title_n)] if m]
    m = re.search(r"\b(ddr5|32gb|2x16gb|16gbx2)\b", title_n)
    if m:
        starts.append(m.start())
    return min(starts, default=len(title_n))


def _before_product(pattern: str, title_n: str) -> bool:
    m = re.search(pattern, title_n)
    return m is not None and m.start() < product_position(title_n)


def identify(title_n: str) -> set[str]:
    found = {pid for pid, pat in IDENTIFIERS.items() if _any(pat, title_n)}
    if not found and _any(RAM_CUES, title_n) and _any(r"\bddr5\b|\b32gb\b|\b2x16gb\b|\b16gbx2\b", title_n):
        found.add("ddr5_32gb_2x16")
    return found


# ------------------------------------------------------------------- RAM decoding


@dataclass
class RamSpec:
    total_gb: int | None = None
    modules: int | None = None
    per_gb: int | None = None
    speed: int | None = None
    cl: int | None = None


def decode_part_numbers(raw: str) -> list[RamSpec]:
    t = (raw or "").lower()
    specs = []
    for m in re.finditer(r"\bcm[a-z]{1,4}(\d{2})gx5m(\d)[a-z](\d{4})c(\d{2})", t):        # Corsair
        total, mods = int(m[1]), int(m[2])
        specs.append(RamSpec(total, mods, total // mods, int(m[3]), int(m[4])))
    for m in re.finditer(r"\bf5-(\d{4})[a-z](\d{2})\d{2}[a-z](\d{2})g[a-z]?x(\d)", t):     # G.Skill
        per, mods = int(m[3]), int(m[4])
        specs.append(RamSpec(per * mods, mods, per, int(m[1]), int(m[2])))
    for m in re.finditer(r"\bkf5(\d{2})c(\d{2})[a-z0-9]*?k(\d)-(\d{2,3})", t):            # Kingston FURY
        mods, total = int(m[3]), int(m[4])
        specs.append(RamSpec(total, mods, total // mods, int(m[1]) * 100, int(m[2])))
    for m in re.finditer(r"\b[a-z0-9]{2,6}d5(\d{2})g(\d{4})hc(\d{2})dc01\b", t):           # TeamGroup
        total = int(m[1])
        specs.append(RamSpec(total, 2, total // 2, int(m[2]), int(m[3])))
    for m in re.finditer(r"\bc[a-z]{1,2}2k(\d{2})g(\d{2})c(\d{2})", t):                    # Crucial
        per = int(m[1])
        specs.append(RamSpec(per * 2, 2, per, int(m[2]) * 100, int(m[3])))
    return specs


SPEED = r"\b(?:ddr5[- ]?)?(4400|4800|5200|5600|6000|6200|6400|6600|6800|7000|7200|7600|8000|8200|8400)(?:mts)?\b"


def _speeds(text_n: str) -> list[int]:
    out = [int(s) for s in re.findall(SPEED, text_n)]
    out += [int(s) // 8 for s in re.findall(r"\bpc5-(\d{5})\b", text_n)]
    return out


def _cls(text_n: str) -> list[int]:
    return [int(c) for c in re.findall(r"\bcl(\d{2})\b", text_n) if 14 <= int(c) <= 60]


KIT_OK = (r"\b2x16gb\b|\b16gbx2\b|\b2x16\b|\b(2|two) ?(pcs?|sticks?|modules?|dimms?) ?(x |of )?16gb\b|"
          r"\b16gb ?\(?x ?2\)?|\b(2|two) ?x? ?16gb sticks?\b|\bkit of (2|two)\b.*\b16gb\b|\b32gb \(2x16gb\)")
KIT_BAD = (r"\b(1|3|4)x(8|16|32|48)gb\b|\b2x(8|24|32|48|64)gb\b|\b(8|24|32|48)gbx\d\b|\b16gbx[134]\b|"
           r"\bsingle (stick|module|dimm)\b|\b(1|one) (stick|module)\b|\b(16|48|64|96|128)gb (kit|ddr5)\b|"
           r"\bddr5 (16|48|64|96)gb\b")


def _aspect(listing: Listing, *names: str) -> str:
    for n in names:
        v = listing.aspects.get(n)
        if v:
            return normalize(v)
    return ""


# ---------------------------------------------------------------- product checks


def _check_cpu(pid: str, title: str, desc: str, listing: Listing) -> Verdict:
    model = "9600x" if pid == "ryzen5_9600x" else "9700x"
    others = {m for m in re.findall(r"\b([3579]\d{3}x3?d?)\b", title) if m != model}
    if others:
        return Verdict(None, f"mentions other CPU models {sorted(others)}")
    if _any(ANY_GPU, title) or _any(ANY_MOBO, title) or _any(r"\b\d{1,3}gb\b|\bram\b|\bdimm\b", title):
        return Verdict(None, "CPU listed with other components (bundle)")
    if _any(r"\bx3d\b", title):
        return Verdict(None, "X3D variant")
    return Verdict(pid, "cpu ok")


def _check_gpu(pid: str, title: str, desc: str, listing: Listing) -> Verdict:
    target = "5060" if pid == "rtx5060ti_16gb" else "5070"
    if _any(r"\b(laptop|notebook|mobile|max-?q|max q)\b", title):
        return Verdict(None, "laptop GPU")
    if _any(r"\bnon-?ti\b|\bnot (a )?ti\b", title):
        return Verdict(None, "non-Ti variant")
    if _any(r"\bsuper\b", title):
        return Verdict(None, "Super variant")
    for num, ti in re.findall(GPU_MODEL, title):
        if num != target or not ti:
            return Verdict(None, f"mentions other GPU model {num}{ti}")
    if _any(ANY_CPU_MODEL + r"|\bryzen\b", title) or _any(ANY_MOBO, title) or _any(r"\bddr[45]\b|\bdimm\b|\bram\b", title):
        return Verdict(None, "GPU listed with other components (bundle)")
    chip = _aspect(listing, "chipset/gpu model", "gpu model", "chipset")
    if chip and not _any(rf"\b{target} ti\b", chip):
        return Verdict(None, f"item specifics say GPU model is '{chip}'")
    if _any(r"\b(8|12)gb\b", title):
        return Verdict(None, "non-16GB VRAM variant")
    mem = _aspect(listing, "memory size", "memory capacity")
    if mem and not _any(r"\b16\s?gb\b", mem):
        return Verdict(None, f"item specifics say VRAM is '{mem}'")
    if _any(r"\b16gb\b", title) or mem:
        return Verdict(pid, "gpu ok, 16GB verified")
    if _any(r"\b16gb\b", desc) and not _any(r"\b(8|12)gb\b", desc):
        return Verdict(pid, "gpu ok, 16GB verified in description")
    return Verdict(None, "VRAM cannot be verified as 16GB")


def _check_mobo(pid: str, title: str, desc: str, listing: Listing) -> Verdict:
    if _any(r"\b(asus|msi|gigabyte|aorus|biostar|nzxt|rog|tuf)\b", title):
        return Verdict(None, "different motherboard brand")
    if _any(r"\b(b650e|b650m|b650 pro|x670e?|x870e?|b850i?|a620i?|b840)\b", title):
        return Verdict(None, "different chipset/variant")
    if _any(r"\b[3579]\d{3}x3?d?\b|\bcore i[3579]\b", title) or _any(ANY_GPU, title) or \
            _any(r"\b\d{1,3}gb\b|\bram\b|\bmemory kit\b|\bdimm\b", title):
        return Verdict(None, "motherboard listed with other components (bundle)")
    model = _aspect(listing, "model")
    if model and "lightning" not in model:
        return Verdict(None, f"item specifics say model is '{model}'")
    return Verdict(pid, "motherboard ok")


def _check_ram(pid: str, title: str, desc: str, listing: Listing) -> Verdict:
    raw_all = " ".join([listing.title, listing.description, " ".join(listing.aspects.values())])
    parts = decode_part_numbers(raw_all)
    aspects_n = normalize(" ".join(f"{k}: {v}" for k, v in listing.aspects.items()))
    full = f"{title} {desc} {aspects_n}"

    if _any(ANY_CPU_MODEL + r"|\bryzen\b", title) or _any(ANY_GPU, title) or _any(ANY_MOBO, title):
        return Verdict(None, "RAM listed with other components (bundle)")
    if _any(r"\bddr4\b", title) or (not _any(r"\bddr5\b", full) and not parts):
        return Verdict(None, "not DDR5")
    if _any(r"\bso-?dimm\b|\bsodimm\b|\blaptop\b|\bnotebook\b|\b262[- ]?pin\b|\bcamm2?\b", title) or \
            _any(r"so-?dimm|laptop", _aspect(listing, "form factor")):
        return Verdict(None, "SO-DIMM / laptop memory")
    if _any(r"(?<!non-)(?<!non )\b(ecc|rdimm|registered|server)\b", title):
        return Verdict(None, "server/ECC memory")
    if _any(KIT_BAD, title):
        return Verdict(None, "wrong kit configuration")

    # kit configuration
    kit_ok = _any(KIT_OK, title) or any(p.modules == 2 and p.per_gb == 16 for p in parts)
    if not kit_ok:
        mods = _aspect(listing, "number of modules")
        per = _aspect(listing, "capacity per module")
        if mods.startswith("2") and per.startswith("16"):
            kit_ok = True
        elif _any(r"\b32gb\b", title) and (_any(KIT_OK, desc) and not _any(KIT_BAD, desc)):
            kit_ok = True
    if any(p.total_gb is not None and (p.modules != 2 or p.per_gb != 16) for p in parts):
        return Verdict(None, "part number decodes to a different kit configuration")
    if not kit_ok:
        return Verdict(None, "2x16GB configuration cannot be verified")

    # speed: rated speed is the highest one mentioned (JEDEC fallback is lower)
    speeds = _speeds(title) or [p.speed for p in parts if p.speed] or _speeds(f"{desc} {aspects_n}")
    if not speeds:
        return Verdict(None, "speed unknown")
    speed = max(speeds)
    if not 5600 <= speed <= 6000:
        return Verdict(None, f"speed {speed} outside 5600-6000")
    cls = _cls(title) or [p.cl for p in parts if p.cl] or _cls(f"{desc} {aspects_n}")
    if not cls:
        cl_aspect = re.findall(r"\d{2}", _aspect(listing, "cas latency"))
        cls = [int(c) for c in cl_aspect]
    if not cls:
        return Verdict(None, "CAS latency unknown")
    cl = min(cls)
    if cl > 36:
        return Verdict(None, f"CL{cl} above CL36")

    notes = [f"DDR5-{speed} CL{cl} 2x16GB"]
    expo = _any(r"\bexpo\b|\bflare x5\b", full)
    low_profile = _any(r"low[- ]?profile|\bflare x5\b|\bripjaws (s5|m5)\b|\bvengeance (?!rgb)", full)
    if expo:
        notes.append("AMD EXPO")
    if low_profile:
        notes.append("low-profile")
    if speed == 6000 and cl in (30, 32) and expo and low_profile:
        notes.append("★ preferred spec")
    return Verdict(pid, "ram ok", notes)


CHECKS = {
    "ryzen5_9600x": _check_cpu,
    "ryzen7_9700x": _check_cpu,
    "rtx5060ti_16gb": _check_gpu,
    "rtx5070ti_16gb": _check_gpu,
    "asrock_b650i_lightning": _check_mobo,
    "ddr5_32gb_2x16": _check_ram,
}

# -------------------------------------------------------------------- location

# sources whose own search already applies the 50-mile radius around the configured ZIP
RADIUS_TRUSTED = ("ebay", "craigslist")
ZIP_RE = re.compile(r"\b(\d{3})(\d{2}\b|\*\*)")


def location_ok(listing: Listing, loc_cfg: dict) -> tuple[bool, str]:
    if listing.shipping_only or not listing.local_pickup:
        return False, "no local pickup (shipping only)"
    pc = (listing.postal_code or "").strip()
    if pc:
        m = ZIP_RE.search(pc)
        if m and m[1] not in loc_cfg["allowed_zip3"]:
            return False, f"postal code {pc} outside radius"
        if m:
            return True, "postal code in radius"
    loc = (listing.location or "").lower()
    if loc:
        m = ZIP_RE.search(loc)
        if m:
            return (m[1] in loc_cfg["allowed_zip3"]), f"zip {m[0]} in location"
        if any(re.search(rf"\b{re.escape(t)}\b", loc) for t in loc_cfg["allowed_towns"]):
            return True, "town in radius"
        if listing.source not in RADIUS_TRUSTED:
            return False, f"location '{listing.location}' not verifiably within radius"
    # eBay's pickup-radius search / the Craigslist saved search's radius already constrained this.
    return listing.source in RADIUS_TRUSTED, "radius enforced by marketplace search"


# ----------------------------------------------------------------------- main


def classify(listing: Listing, products: dict[str, dict], filters: dict, loc_cfg: dict) -> Verdict:
    title = normalize(listing.title)
    desc = normalize(listing.description)
    cond = normalize(listing.condition)

    if listing.sold or _any(SOLD, title):
        return Verdict(None, "sold/pending")
    if _any(WANTED, title):
        return Verdict(None, "wanted post")
    if _any(COMPLETE_PC, title):
        return Verdict(None, "complete PC")
    if _any(BROKEN_TITLE, title) or _any(r"parts|not working", cond) or _any(BROKEN_DESC, desc):
        return Verdict(None, "broken / for parts")
    if _any(BOX_ONLY, title) or _before_product(ACCESSORY, title) or _before_product(FOR_PHRASE, title):
        return Verdict(None, "accessory / box / compatible-with listing")
    if _any(SCAM_DESC, desc) or _any(SCAM_DESC, title):
        return Verdict(None, "scam indicators")

    found = identify(title)
    if not found:
        return Verdict(None, "no watchlist product in title")
    if len(found) > 1:
        return Verdict(None, f"multiple watchlist products {sorted(found)} (bundle)")
    pid = found.pop()
    if pid not in products:
        return Verdict(None, f"{pid} not enabled")
    if _any(COMBO, title):
        return Verdict(None, "combo/bundle listing")

    verdict = CHECKS[pid](pid, title, desc, listing)
    if not verdict.ok:
        return verdict

    prod = products[pid]
    if listing.price is None:
        return Verdict(None, "price unknown")
    if "AUCTION" in listing.buying_options and "FIXED_PRICE" not in listing.buying_options \
            and not filters.get("allow_auctions", False):
        return Verdict(None, "auction (current bid is not a real price)")
    if listing.price >= prod["max_price"]:
        return Verdict(None, f"price ${listing.price:.2f} not below ${prod['max_price']}")
    if listing.price < prod["max_price"] * filters["min_price_ratio"]:
        return Verdict(None, f"price ${listing.price:.2f} suspiciously low (bait/scam/misleading)")
    if listing.seller_feedback_pct is not None and listing.seller_feedback_score is not None:
        if listing.seller_feedback_score >= 10 and listing.seller_feedback_pct < 95:
            return Verdict(None, "seller feedback below 95%")
        if listing.seller_feedback_score == 0 and listing.price < prod["max_price"] * 0.6:
            return Verdict(None, "zero-feedback seller with very low price")

    ok, why = location_ok(listing, loc_cfg)
    if not ok:
        return Verdict(None, why)
    return verdict
