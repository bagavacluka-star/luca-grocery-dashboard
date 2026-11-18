#!/usr/bin/env python3
"""Validate the dashboard data before publishing a snapshot."""

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

path = Path(__file__).resolve().parents[1] / "dist" / "data.json"
data = json.loads(path.read_text(encoding="utf-8"))
js = (path.parent / "data.js").read_text(encoding="utf-8")
assert js.startswith("window.GROCERY_DATA = ") and js.rstrip().endswith(";"), "Bundled data.js missing"
assert json.loads(js[len("window.GROCERY_DATA = "):].strip().removesuffix(";")) == data, "Bundled data differs from JSON"
assert data["timezone"] == "Europe/Belgrade"
assert data["currency"] == "RSD"
assert len(data["items"]) == 5 and len(data["stores"]) == 3
today = data["generated_at"][:10]
rows = [r for r in data["observations"] if r["date"] == today]
assert len(rows) == 15, f"Expected 15 today's observations, got {len(rows)}"
keys = [(r["date"], r["item"], r["store"]) for r in data["observations"]]
assert len(keys) == len(set(keys)), "Duplicate date-item-store observation"
for r in rows:
    assert r["kind"] in {"exact", "pack_alternative", "spec_alternative", "source_error"}
    if r["kind"] == "source_error":
        assert r["price"] is None and r["equivalent_price"] is None
    else:
        assert isinstance(r["price"], (int, float)) and r["price"] > 0
        assert urlparse(r["source"]).scheme == "https"
        if r.get("image") is not None:
            image = urlparse(r["image"])
            assert image.scheme == "https" and image.hostname in {"www.lidl.rs", "cdn.metro-group.com", "static.maxi.rs"}
        assert r["equivalent_price"] is None if r["kind"] == "spec_alternative" else r["equivalent_price"] > 0
counts = Counter(r["kind"] for r in rows)
print(f"PASS {today}: {len(rows)} unique current observations; {dict(counts)}; {len(data['observations'])} all dates")
for row in rows:
    if row["kind"] == "source_error":
        print(f"WARNING source_error {row['store']}/{row['item']}: {row['reason']}")
