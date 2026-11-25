"""Load config.toml."""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: str | Path | None = None) -> dict:
    with open(path or ROOT / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    cfg["products_by_id"] = {p["id"]: p for p in cfg["products"] if p.get("enabled", True)}
    return cfg
