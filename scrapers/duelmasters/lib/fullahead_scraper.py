"""Scraper for fullahead-dm.com (MakeShop single-card shop) listings.

One booster = one brand page, e.g. DM26-EX4 -> https://fullahead-dm.com/shopbrand/dm26-ex04
Pages are EUC-JP and plain `requests` works (no JS rendering / bot wall).

Listing title format:
    DM26-EX4/<no>/<rarity>/<name>【<variant>】
    DM26-EX4/秘2/VR/切札混成 インビンシブル・ドラゴン【シークレットレア】
    DM26-EX4/超1/KGM/アルカディアス・モモキング【デュエキングMAX】
<no> is a shop-side sub-set prefix + number (秘N, 超N, 超GN or a bare number),
NOT the takaratomy card number.
"""
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://fullahead-dm.com"
ENCODING = "euc-jp"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; geekstack-price-bot)"}
MAX_PAGES = 30

_CODE_RE = re.compile(r"^(?:dm)?-?(\d+)-?([a-z]+)-?0*(\d+)$")
_TITLE_RE = re.compile(
    r"^(?P<set>[^/]+)/(?P<no>[^/]+)/(?P<rarity>[^/]+)/(?P<name>.+?)\s*(?:【(?P<variant>[^【】]*)】)?\s*$"
)
_PRODUCT_RE = re.compile(r"/shopdetail/(\d+)/")
_PRICE_RE = re.compile(r"([\d,]+)\s*円")
_STOCK_RE = re.compile(r"残りあと\s*(\d+)\s*[個点]|在庫[:：]?\s*(\d+)")


def normalize_booster_code(code: str) -> str:
    """'DM26-EX4' / 'dm26ex4' / '26ex4' / 'dm26-ex04' -> 'dm26ex4' (DB form)."""
    m = _CODE_RE.match(code.strip().lower().replace("_", "-"))
    if not m:
        raise ValueError(f"unrecognised booster code: {code!r}")
    num, kind, n = m.groups()
    return f"dm{num}{kind}{int(n)}"


def booster_to_shop_slug(code: str) -> str:
    """'dm26ex4' -> 'dm26-ex04' (fullahead's brand slug, 2-digit padded)."""
    m = _CODE_RE.match(code.strip().lower())
    if not m:
        raise ValueError(f"unrecognised booster code: {code!r}")
    num, kind, n = m.groups()
    return f"dm{num}-{kind}{int(n):02d}"


def page_url(slug: str, page: int) -> str:
    if page <= 1:
        return f"{BASE}/shopbrand/{slug}"
    return f"{BASE}/shopbrand/{slug}/page{page}/recommend/"


def fetch_page(url: str, max_retries: int = 3, timeout: int = 30) -> str | None:
    """GET + EUC-JP decode, retrying on transient network errors.
    Returns None on 404 (brand page doesn't exist on the shop)."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.content.decode(ENCODING, errors="replace")
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            print(f"⚠️ fetch failed for {url} (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    raise last_exc


def parse_title(title: str) -> dict:
    """Split a listing title into its parts; unparseable titles keep only name_raw."""
    title = title.strip()
    m = _TITLE_RE.match(title)
    if not m:
        return {"title": title, "shop_set": None, "shop_no": None,
                "rarity": None, "name": title, "variant": None}
    return {
        "title": title,
        "shop_set": m.group("set"),
        "shop_no": m.group("no"),
        "rarity": m.group("rarity"),
        "name": m.group("name").strip(),
        "variant": m.group("variant"),
    }


def parse_listing(html: str) -> list[dict]:
    """Extract one dict per product block from a brand page."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for name_span in soup.select("span.itemName"):
        block = name_span.find_parent("div")
        link = name_span.find_parent("a")
        if block is None or link is None:
            continue
        href = link.get("href", "")
        pm = _PRODUCT_RE.search(href)
        if not pm:
            continue

        img = block.select_one("span.itemImg img")
        price_el = block.select_one("span.itemPrice")
        price_text = price_el.get_text(" ", strip=True) if price_el else ""
        price_m = _PRICE_RE.search(price_text)
        stock_m = _STOCK_RE.search(price_text)
        if stock_m:
            stock = int(stock_m.group(1) or stock_m.group(2))
        elif re.search(r"売り切れ|SOLD\s*OUT|品切れ|在庫なし", price_text, re.I):
            stock = 0
        else:
            stock = None  # shop shows no count (e.g. plenty in stock)

        item = parse_title(name_span.get_text(strip=True))
        item.update({
            "product_id": pm.group(1),
            "url": BASE + href.split("/page")[0] + "/" if href.startswith("/") else href,
            "image": img.get("src") if img else None,
            "price": int(price_m.group(1).replace(",", "")) if price_m else None,
            "stock": stock,
        })
        items.append(item)
    return items


def scrape_booster(code: str, delay: float = 1.0, slug: str | None = None) -> list[dict]:
    """Scrape every page of a booster's brand listing. `code` is any accepted form."""
    slug = slug or booster_to_shop_slug(normalize_booster_code(code))
    seen: dict[str, dict] = {}
    for page in range(1, MAX_PAGES + 1):
        url = page_url(slug, page)
        html = fetch_page(url)
        if html is None:
            print(f"  page {page}: 404 {url}")
            break
        items = parse_listing(html)
        new = [i for i in items if i["product_id"] not in seen]
        print(f"  page {page}: {len(items)} items ({len(new)} new)  {url}")
        if not new:
            break
        for i in new:
            seen[i["product_id"]] = i
        time.sleep(delay)
    return list(seen.values())
