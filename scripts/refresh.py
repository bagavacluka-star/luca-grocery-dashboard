#!/usr/bin/env python3
"""Refresh the hosted grocery dashboard from retailer-owned public sources.

One tracked SKU per store and staple makes changes over time interpretable.
Missing or unavailable data remains visible; yesterday's price is never reused
as today's. Run from any directory: python3 scripts/refresh.py.
"""

import json
import re
import sys
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
import truststore

truststore.inject_into_ssl()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "data.json"
JS_OUT = ROOT / "dist" / "data.js"
SEED = ROOT / "data" / "seed-2026-11-16.json"
NOW = datetime.now(ZoneInfo("Europe/Belgrade"))
DAY = NOW.date().isoformat()
STAMP = NOW.isoformat(timespec="seconds")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; CeneNamirnica/1.0; public grocery price check)"})

ITEMS = [
    {"id": "oil", "name": "Rafinisano suncokretovo ulje", "target": "1 l", "basis": "RSD/l"},
    {"id": "flour", "name": "Pšenično brašno T-500", "target": "1 kg", "basis": "RSD/kg"},
    {"id": "sugar", "name": "Šećer kristal", "target": "1 kg", "basis": "RSD/kg"},
    {"id": "eggs", "name": "Jaja, klasa M", "target": "10 kom", "basis": "RSD/10 kom"},
    {"id": "milk", "name": "Mleko, 2,8% m. m.", "target": "1 l", "basis": "RSD/l"},
]
STORES = [
    {"id": "lidl", "name": "Lidl", "scope": "Javni sajt, bez izbora radnje"},
    {"id": "metro", "name": "Metro Zemun", "scope": "Metro radnja 00020"},
    {"id": "maxi", "name": "Maxi Online", "scope": "Online katalog, bez adrese dostave"},
]

# The exact product and exception status were manually checked on 16-17 Nov 2026.
# Fixed SKUs deliberately keep the price history tied to the same product.
PRODUCTS = {
    "oil": {
        "lidl": {"url": "https://www.lidl.rs/p/vita-d-or-suncokretovo-ulje/p11494977", "sku": "11494977", "pack": "1 l", "kind": "exact", "basis_qty": "1", "reason": "Etiketa potvrđuje rafinisano ulje."},
        "metro": {"article": "BTY-X389810", "variant": "0032", "bundle": "0021", "pack": "1 l", "kind": "exact", "basis_qty": "1"},
        "maxi": {"code": "7344808", "pack": "1 l", "kind": "exact", "basis_qty": "1", "reason": "Etiketa potvrđuje rafinisano ulje."},
    },
    "flour": {
        "lidl": {"url": "https://www.lidl.rs/p/belbake-psenicno-belo-brasno/p11494980", "sku": "11494980", "pack": "2 kg", "kind": "pack_alternative", "basis_qty": "2", "reason": "Isto brašno T-500, pakovanje od 2 kg umesto traženog 1 kg."},
        "metro": {"article": "BTY-X352515", "variant": "0032", "bundle": "0021", "pack": "1 kg", "kind": "exact", "basis_qty": "1"},
        "maxi": {"code": "7486026", "pack": "1 kg", "kind": "exact", "basis_qty": "1"},
    },
    "sugar": {
        "lidl": {"url": "https://www.lidl.rs/p/sunoko-secer/p11495820", "sku": "11495820", "pack": "1 kg", "kind": "exact", "basis_qty": "1", "reason": "Fotografija pakovanja označava kristal šećer."},
        "metro": {"article": "BTY-X294920", "variant": "0032", "bundle": "0021", "pack": "1 kg", "kind": "exact", "basis_qty": "1"},
        "maxi": {"code": "7349784", "pack": "1 kg", "kind": "exact", "basis_qty": "1"},
    },
    "eggs": {
        "lidl": {"url": "https://www.lidl.rs/p/sveza-jaja-jaja-iz-podnog-uzgoja-xxl/p11494422", "sku": "11494422", "pack": "24 kom", "kind": "pack_alternative", "basis_qty": "24", "reason": "Jaja klase M, ali pakovanje od 24 umesto traženih 10 komada."},
        "metro": {"article": "BTY-X392190", "variant": "0032", "bundle": "0021", "pack": "10 kom", "kind": "exact", "basis_qty": "10"},
        "maxi": {"code": "7747892", "pack": "10 kom", "kind": "exact", "basis_qty": "10"},
    },
    "milk": {
        "lidl": {"url": "https://www.lidl.rs/p/pilos-dugotrajno-mleko/p11495005", "sku": "11495005", "pack": "1 l, 3,2%", "kind": "spec_alternative", "basis_qty": "1", "reason": "Pakovanje je 1 l, ali ima 3,2% mlečne masti umesto traženih 2,8%."},
        "metro": {"article": "BTY-X54079", "variant": "0032", "bundle": "0021", "pack": "1 l, 2,8%", "kind": "exact", "basis_qty": "1"},
        "maxi": {"code": "7655976", "pack": "1 l, 2,8%", "kind": "exact", "basis_qty": "1"},
    },
}


def money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalized(price, item_id, spec):
    if spec["kind"] == "spec_alternative":
        return None
    basis = Decimal("10") if item_id == "eggs" else Decimal("1")
    return money(Decimal(str(price)) / Decimal(spec["basis_qty"]) * basis)


def source_url(store_id, spec):
    if store_id == "lidl":
        return spec["url"]
    if store_id == "metro":
        return f"https://proizvodi.metro.rs/shop/pv/{spec['article']}/{spec['variant']}/{spec['bundle']}"
    return f"https://www.maxi.rs/p/{spec['code']}"


def lidl(spec):
    response = SESSION.get(spec["url"], timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    product = next((json.loads(tag.string) for tag in soup.find_all("script", type="application/ld+json") if (tag.string or "").strip().startswith("{") and json.loads(tag.string).get("@type") == "Product"), None)
    if not product or str(product.get("sku")) != spec["sku"]:
        raise ValueError("Lidl product identity changed")
    offer = product["offers"][0]
    panel = soup.find("article", class_="detail-one")
    panel_text = panel.get_text(" ", strip=True) if panel else ""
    pack_head = spec["pack"].split(",")[0]
    if pack_head not in panel_text:
        raise ValueError("Lidl pack no longer matches the tracked product")
    return {"product": f"{product.get('brand',{}).get('name','')} {product['name']}".strip(),
            "price": money(offer["price"]), "source": spec["url"],
            "image": (product.get("image") or [None])[0],
            "availability": "Dostupnost u konkretnoj Lidl radnji nije potvrđena",
            "evidence": "Lidl Product.offers.price; " + (spec.get("reason") or "pakovanje provereno na stranici")}


def metro(spec):
    params = {"ids": spec["article"], "country": "RS", "locale": "sr-RS", "storeIds": "00020", "details": "true"}
    response = SESSION.get("https://proizvodi.metro.rs/evaluate.article.v1/betty-articles", params=params, timeout=25)
    response.raise_for_status()
    bundle = response.json()["result"][spec["article"]]["variants"][spec["variant"]]["bundles"][spec["bundle"]]
    if str(bundle.get("bundleSize")) != "1":
        raise ValueError("Metro bundle changed")
    store = bundle["stores"]["00020"]
    price = store["sellingPriceInfo"].get("grossPrice")
    if price is None:
        raise ValueError("Metro gross price unavailable")
    return {"product": bundle["description"], "price": money(price),
            "source": f"https://proizvodi.metro.rs/shop/pv/{spec['article']}/{spec['variant']}/{spec['bundle']}",
            "image": bundle.get("imageUrlL") or bundle.get("imageUrl"),
            "availability": f"Metro katalog: {bundle.get('availability','nepoznato')}",
            "evidence": "Metro stores.00020.sellingPriceInfo.grossPrice (sa PDV-om)"}


MAXI_QUERY = "query GetProductDetails($productCode:String!,$lang:String!){productDetails(productCode:$productCode,lang:$lang){name price{value formattedValue} stock{inStock} url}}"


def maxi(spec):
    response = SESSION.post("https://www.maxi.rs/api/v1/", json={"query": MAXI_QUERY, "variables": {"productCode": spec["code"], "lang": "sr"}},
                            headers={"Origin": "https://www.maxi.rs", "Referer": "https://www.maxi.rs/"}, timeout=25)
    response.raise_for_status()
    product = response.json()["data"]["productDetails"]
    if not product or f"/p/{spec['code']}" not in product["url"]:
        raise ValueError("Maxi product identity changed")
    if product["price"].get("value") is None:
        raise ValueError("Maxi online price unavailable")
    product_url = urljoin("https://www.maxi.rs", product["url"])
    image = None
    try:
        page = SESSION.get(product_url, timeout=25)
        page.raise_for_status()
        next_data = BeautifulSoup(page.text, "html.parser").find("script", id="__NEXT_DATA__")
        page_data = json.loads(next_data.string)["props"]["pageProps"]["pageData"] if next_data else {}
        images = page_data.get("galleryImages") or []
        selected = next((entry for entry in images if entry.get("format") == "product"), images[0] if images else None)
        if selected and selected.get("url"):
            image = urljoin("https://static.maxi.rs", selected["url"])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass  # A missing image must not erase a verified price.
    return {"product": product["name"], "price": money(product["price"]["value"]),
            "source": product_url, "image": image,
            "availability": "Maxi Online: na stanju" if product.get("stock",{}).get("inStock") else "Maxi Online: nije na stanju",
            "evidence": "Maxi productDetails.price.value; " + (spec.get("reason") or "naziv i pakovanje na stranici")}


def load_existing():
    path = OUT if OUT.exists() else SEED
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"observations": []}


data = load_existing()
prior = [r for r in data.get("observations", []) if r.get("date") != DAY]
today = []
for item in ITEMS:
    for store in STORES:
        item_id, store_id = item["id"], store["id"]
        spec = PRODUCTS[item_id][store_id]
        try:
            result = {"lidl": lidl, "metro": metro, "maxi": maxi}[store_id](spec)
            row = {"date": DAY, "checked_at": STAMP, "item": item_id, "store": store_id,
                   "kind": spec["kind"], "pack": spec["pack"], "price": result["price"],
                   "equivalent_price": normalized(result["price"], item_id, spec),
                   "product": result["product"], "source": result["source"],
                   "image": result.get("image"),
                   "availability": result["availability"], "reason": spec.get("reason", ""),
                   "evidence": result["evidence"]}
        except Exception as exc:
            row = {"date": DAY, "checked_at": STAMP, "item": item_id, "store": store_id,
                   "kind": "source_error", "pack": spec["pack"], "price": None,
                   "equivalent_price": None, "product": "", "source": source_url(store_id, spec),
                   "image": None,
                   "availability": "Neprovereno", "reason": f"{type(exc).__name__}: {exc}", "evidence": ""}
        today.append(row)
        print(f"{item_id:6} {store_id:5} {row['kind']:16} {str(row['price']):>7} {row['product'][:45]}")

data = {"generated_at": STAMP, "timezone": "Europe/Belgrade", "currency": "RSD",
        "items": ITEMS, "stores": STORES,
        "method": "Jedan fiksni artikal po trgovcu i namirnici. Različita pakovanja imaju posebno označenu jediničnu cenu. Različit sastav se ne poredi.",
        "observations": sorted(prior + today, key=lambda r: (r["date"], r["item"], r["store"]))}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
JS_OUT.write_text("window.GROCERY_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";\n", encoding="utf-8")
print(f"Saved {len(today)} observations for {DAY}; {len(data['observations'])} total")
