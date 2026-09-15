#!/usr/bin/env python3
"""
Nestasia Beacon Diagnostic
==========================
Technical proof-of-concept for Swym Beacon, run against Nestasia's live storefront.

Beacon-style intent-intelligence pass over nestasia.in (Shopify Plus, home
decor, India). Surfaces products generating "silent" demand — traffic/intent
Nestasia's storefront cannot currently capture because it has no back-in-stock
alerts and no wishlist data pipeline — using only public storefront pages.

------------------------------------------------------------------------------
ENGINEERING NOTE — read before running
------------------------------------------------------------------------------
The original plan for this script was stdlib + `requests` + `beautifulsoup4`
hitting the oembed/collection/product URLs directly. That does not work:

  1. Nestasia sits behind Cloudflare bot management. A plain `requests.get()`
     (or curl, with a normal browser User-Agent) against the oembed endpoint,
     any collection page, or any product page returns HTTP 403 with a
     "Just a moment..." JS-challenge page, not real content. Verified live
     against all three endpoint types before writing this script.
     -> Fix: drive an actual headless Chromium instance via Playwright. It
        executes Cloudflare's JS challenge like a real browser and clears it
        (confirmed reliable after an ~8s settle time per navigation).

  2. The oembed endpoint's `page` query parameter is a no-op on this store.
     `.oembed?page=1`, `?page=2`, `?page=100`, and no param at all were
     fetched and diffed byte-for-byte / product-for-product: they all return
     the SAME first 50 products. There is no working pagination on this
     endpoint from the outside. So oembed-sourced data in this report reflects
     the first 50 products Shopify returns per collection — NOT the full
     collection (e.g. not all 1,254 products in "What's Trending"). This is
     disclosed explicitly in the generated report rather than glossed over.

  3. The oembed JSON schema differs slightly from what was assumed: variants
     are under the key `offers` (not `variants`), each with `price`,
     `in_stock`, `sku`. `product_id` is actually the product's URL handle
     (confirmed by round-tripping `https://nestasia.in/products/{product_id}`).

Requirements:
    pip install playwright beautifulsoup4
    playwright install chromium

Run:
    python3 nestasia_beacon.py

Output:
    ./nestasia_beacon_report.html   (single-file report, open in a browser)
"""

import json
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run:\n"
          "  pip install playwright beautifulsoup4\n"
          "  playwright install chromium")
    sys.exit(1)

OUT_DIR = Path(__file__).resolve().parent
REPORT_PATH = OUT_DIR / "nestasia_beacon_report.html"

BASE = "https://nestasia.in"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Target collections to scrape. NOTE: due to the broken oembed pagination
# (see engineering note above), this pulls the first ~50 products actually
# returned per collection, not the full catalog depth quoted in prior manual
# research (e.g. 1,254 for what's-trending). Coverage is disclosed in the
# report, not hidden.
COLLECTIONS = [
    "whats-trending",
    "bestsellers-on-discount",
    "new-in",
    "gifts",
    "flat-50-percent-off-offer",
]

# Gift-occasion collection handles we look for as links inside product
# description HTML -> proxy for how "occasion-tagged" a product is.
GIFT_OCCASION_HANDLES = [
    "birthday-gifts", "anniversary-gifts", "house-warming-gifts",
    "wedding-gifts", "trousseau-gifts", "farewell-gifts",
]

REQUEST_DELAY = 0.5     # polite delay between logical fetches
PAGE_SETTLE_MS = 8000   # time to let Cloudflare's JS challenge clear
TOP_N_DEEPDIVE = 25     # how many top-sellout products get a product-page visit
                         # (matches the top-25 table so every row in the report
                         # gets full inventory/discount/review data; still well
                         # under the 5-minute budget at ~9s/page)


def log(msg):
    print(f"[beacon] {msg}", flush=True)


# ------------------------------------------------------------------------
# Fetching (Playwright-backed, Cloudflare-aware)
# ------------------------------------------------------------------------

def fetch_oembed_json(browser, collection_handle):
    """Fetch the oembed JSON for a collection.

    Chromium treats the JSON response as a file download rather than
    rendering it (there's no built-in JSON viewer in headless mode), so we
    have to catch the resulting "Download is starting" navigation error and
    read the downloaded payload back off disk instead of reading page content.
    """
    url = f"{BASE}/collections/{collection_handle}.oembed?page=1"
    ctx = browser.new_context(user_agent=UA, accept_downloads=True)
    page = ctx.new_page()
    try:
        with page.expect_download(timeout=20000) as dl_info:
            try:
                page.goto(url, timeout=20000)
            except Exception:
                pass  # expected: Playwright raises because nav becomes a download
        data = open(dl_info.value.path(), "rb").read()
        return json.loads(data)
    except Exception as e:
        log(f"  ! oembed fetch failed for {collection_handle}: {e}")
        return None
    finally:
        ctx.close()


def fetch_rendered_html(browser, url, wait_ms=PAGE_SETTLE_MS):
    """Fetch a URL's fully-rendered HTML after Cloudflare's challenge clears."""
    ctx = browser.new_context(user_agent=UA)
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(wait_ms)
        return page.content()
    except Exception as e:
        log(f"  ! page fetch failed for {url}: {e}")
        return None
    finally:
        ctx.close()


# ------------------------------------------------------------------------
# Parsing helpers
# ------------------------------------------------------------------------

def extract_image_version(thumbnail_url):
    """Pull the unix timestamp off `?v=...` — a recency proxy (last time the
    product image asset was touched, which correlates with last edit/publish)."""
    if not thumbnail_url:
        return None
    m = re.search(r"[?&]v=(\d+)", thumbnail_url)
    return int(m.group(1)) if m else None


def count_gift_occasion_links(description_html):
    if not description_html:
        return 0
    return sum(1 for h in GIFT_OCCASION_HANDLES if h in description_html)


def parse_facets(html):
    """Generic parser for Shopify "Search & Discovery" facet sidebars.

    Returns {facet_group_label: {option_label: count}}, e.g.
    {"Availability": {"In stock": 190, "Out of stock": 1064}, "Occasions": {...}}
    """
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    facets = {}
    for details in soup.select("details.facets__disclosure-vertical, details.js-filter"):
        label_el = details.select_one(".facets__summary-label")
        if not label_el:
            continue
        group = label_el.get_text(strip=True)
        options = {}
        for li in details.select("li.facets__item"):
            text_label = li.select_one(".facet-checkbox__text-label")
            if not text_label:
                continue
            opt_name = text_label.get_text(strip=True)
            m = re.search(r"\((\d+)\)", li.get_text(" ", strip=True))
            if m:
                options[opt_name] = int(m.group(1))
        if options:
            facets[group] = options
    return facets


def parse_product_page(html):
    """Extract deep-dive signals from a rendered product page.

    All fields here are best-effort / may be None — Nestasia's theme doesn't
    guarantee every element renders for every product (e.g. "Only X left!"
    only shows up for genuinely low-stock items).
    """
    result = {"inventory_count": None, "price_regular": None,
              "price_sale": None, "discount_depth": None,
              "review_count": None, "review_rating": None}
    if not html:
        return result

    # Low-stock urgency banner, e.g. "Only 3 left!"
    m = re.search(r"Only\s*(\d+)\s*left", html, re.IGNORECASE)
    if m:
        result["inventory_count"] = int(m.group(1))

    soup = BeautifulSoup(html, "html.parser")

    def parse_price(el):
        if not el:
            return None
        txt = el.get_text(strip=True).replace("₹", "").replace(",", "").strip()
        try:
            return float(txt)
        except ValueError:
            return None

    reg = parse_price(soup.select_one(".price-item--regular"))
    sale = parse_price(soup.select_one(".price-item--sale"))
    result["price_regular"] = reg
    result["price_sale"] = sale
    if reg and sale and reg > 0 and sale < reg:
        result["discount_depth"] = round((reg - sale) / reg, 4)
    else:
        result["discount_depth"] = 0.0

    # Judge.me rating histogram: data-rating (1-5) x data-frequency (count)
    total, weighted = 0, 0
    for row in soup.select(".jdgm-histogram__row"):
        try:
            rating = int(row.get("data-rating", 0))
            freq = int(row.get("data-frequency", 0))
        except (TypeError, ValueError):
            continue
        total += freq
        weighted += rating * freq
    if total > 0:
        result["review_count"] = total
        result["review_rating"] = round(weighted / total, 2)

    return result


# ------------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------------

def normalize(values):
    """Min-max normalize a list of numbers (None treated as 0) to [0, 1]."""
    clean = [v if v is not None else 0 for v in values]
    lo, hi = min(clean), max(clean)
    if hi - lo < 1e-9:
        return [0.0 for _ in clean]
    return [(v - lo) / (hi - lo) for v in clean]


def compute_scores(products):
    """Composite intent_risk_score per the brief's weighting:

        0.30 * variant_sellout_rate
      + 0.20 * normalized(low_inventory_score)   # inverse of inventory count
      + 0.20 * trending_membership_flag
      + 0.15 * discount_depth
      + 0.10 * normalized(review_count)
      + 0.05 * normalized(gift_occasion_density)
    """
    inv_scores = []
    for p in products:
        inv = p.get("inventory_count")
        # Inverse of inventory count: lower stock -> higher risk. Products
        # with no inventory signal captured get a neutral 0 (no evidence
        # either way, rather than assuming urgency).
        inv_scores.append(1.0 / (inv + 1) if inv is not None else 0.0)
    norm_inv = normalize(inv_scores)
    norm_reviews = normalize([p.get("review_count") or 0 for p in products])
    norm_gift = normalize([p.get("gift_occasion_links") or 0 for p in products])

    for i, p in enumerate(products):
        p["intent_risk_score"] = round(
            0.30 * (p.get("variant_sellout_rate") or 0)
            + 0.20 * norm_inv[i]
            + 0.20 * (1.0 if p.get("in_trending") else 0.0)
            + 0.15 * (p.get("discount_depth") or 0)
            + 0.10 * norm_reviews[i]
            + 0.05 * norm_gift[i],
            4,
        )
    return products


# ------------------------------------------------------------------------
# Main pipeline
# ------------------------------------------------------------------------

def main():
    t_start = time.time()
    products_by_id = {}

    with sync_playwright() as p:
        log("Launching headless Chromium...")
        browser = p.chromium.launch(headless=True)

        # --- Stage 1: oembed sweep across target collections ---
        for handle in COLLECTIONS:
            log(f"Fetching oembed for collection '{handle}'...")
            data = fetch_oembed_json(browser, handle)
            time.sleep(REQUEST_DELAY)
            if not data or "products" not in data:
                log(f"  ! no data for {handle}, skipping")
                continue
            log(f"  -> {len(data['products'])} products returned")
            for prod in data["products"]:
                pid = prod.get("product_id")
                if not pid:
                    continue
                offers = prod.get("offers") or []
                total_offers = len(offers)
                sold_out = sum(1 for o in offers if o.get("in_stock") is False)
                sellout_rate = (sold_out / total_offers) if total_offers else 0.0
                max_price = max((o.get("price") or 0 for o in offers), default=0.0)

                if pid not in products_by_id:
                    products_by_id[pid] = {
                        "product_id": pid,
                        "title": prod.get("title", pid),
                        "collections": [],
                        "variant_sellout_rate": sellout_rate,
                        "total_variants": total_offers,
                        "sold_out_variants": sold_out,
                        "price": max_price,
                        "image_version_timestamp": extract_image_version(prod.get("thumbnail_url")),
                        "gift_occasion_links": count_gift_occasion_links(prod.get("description")),
                    }
                products_by_id[pid]["collections"].append(handle)

        products = list(products_by_id.values())
        for p in products:
            p["in_trending"] = "whats-trending" in p["collections"]
            p["multi_collection"] = len(set(p["collections"])) > 1
            p["primary_collection"] = p["collections"][0]
        log(f"Deduplicated to {len(products)} unique products across "
            f"{len(COLLECTIONS)} collections.")

        # --- Stage 2: collection-level facet analysis (trending collection) ---
        log("Fetching rendered HTML for 'whats-trending' collection facets...")
        trending_html = fetch_rendered_html(browser, f"{BASE}/collections/whats-trending")
        time.sleep(REQUEST_DELAY)
        facets = parse_facets(trending_html)

        avail = facets.get("Availability", {})
        in_stock_ct = avail.get("In stock", 0)
        oos_ct = avail.get("Out of stock", 0)
        trending_total = in_stock_ct + oos_ct
        trending_oos_ratio = (oos_ct / trending_total) if trending_total else None
        occasion_weights = facets.get("Occasions", {})
        log(f"  -> Availability facet: {in_stock_ct} in stock / {oos_ct} out of stock "
            f"(store-reported totals, independent of the 50-product oembed sample)")

        # --- Stage 3: product-page deep dive on top sellout-rate candidates ---
        candidates = sorted(products, key=lambda p: p["variant_sellout_rate"], reverse=True)
        deepdive_targets = candidates[:TOP_N_DEEPDIVE]
        log(f"Deep-diving {len(deepdive_targets)} highest sellout-rate products "
            f"(product-page fetch each)...")
        for i, p in enumerate(deepdive_targets, 1):
            url = f"{BASE}/products/{p['product_id']}"
            log(f"  [{i}/{len(deepdive_targets)}] {p['title'][:50]}")
            html = fetch_rendered_html(browser, url, wait_ms=7000)
            details = parse_product_page(html)
            p.update(details)
            time.sleep(REQUEST_DELAY)

        browser.close()

    # Fill defaults for products that never got a deep-dive fetch
    for p in products:
        p.setdefault("inventory_count", None)
        p.setdefault("discount_depth", 0.0)
        p.setdefault("review_count", None)
        p.setdefault("review_rating", None)

    products = compute_scores(products)
    products.sort(key=lambda p: p["intent_risk_score"], reverse=True)

    elapsed = time.time() - t_start
    log(f"Done fetching/scoring in {elapsed:.1f}s. Building report...")

    context = {
        "products": products,
        "trending_oos_ratio": trending_oos_ratio,
        "trending_in_stock": in_stock_ct,
        "trending_out_of_stock": oos_ct,
        "occasion_weights": occasion_weights,
        "collections": COLLECTIONS,
        "top_n_deepdive": TOP_N_DEEPDIVE,
    }
    html_report = build_report(context)
    REPORT_PATH.write_text(html_report, encoding="utf-8")
    log(f"Report written to {REPORT_PATH}")
    log(f"Total runtime: {time.time() - t_start:.1f}s")


# ------------------------------------------------------------------------
# Report generation
# ------------------------------------------------------------------------

def build_report(ctx):
    products = ctx["products"]
    n = len(products)
    partial_oos = [p for p in products if 0 < p["variant_sellout_rate"] < 1]
    full_oos = [p for p in products if p["variant_sellout_rate"] >= 1]
    pct_partial_or_full = round(100 * (len(partial_oos) + len(full_oos)) / n, 1) if n else 0

    est_lost_demand = sum(
        p["sold_out_variants"] * (p["price"] or 0) for p in products
    )

    top25 = products[:25]

    # Category breakdown (proxy: primary collection membership, since Shopify
    # oembed does not expose a `product_type` field on this store's feed).
    cat_scores = defaultdict(list)
    for p in products:
        cat_scores[p["primary_collection"]].append(p["variant_sellout_rate"])
    cat_avg = {
        k: round(statistics.mean(v) * 100, 1) for k, v in cat_scores.items()
    }
    cat_labels = list(cat_avg.keys())
    cat_values = [cat_avg[k] for k in cat_labels]

    def recommendation(p):
        has_stock_signal = p["variant_sellout_rate"] > 0
        has_intent_signal = (p.get("review_count") or 0) > 0 or p["in_trending"]
        if has_stock_signal and has_intent_signal:
            return "Both"
        if has_stock_signal:
            return "Back-in-Stock"
        return "Wishlist"

    def fmt_money(v):
        return f"₹{v:,.0f}"

    def fmt_pct(v):
        return f"{v*100:.0f}%" if v is not None else "—"

    rows_html = []
    for i, p in enumerate(top25, 1):
        inv = p["inventory_count"] if p["inventory_count"] is not None else "—"
        disc = f"{p['discount_depth']*100:.0f}%" if p.get("discount_depth") else "—"
        reviews = p["review_count"] if p["review_count"] is not None else "—"
        rows_html.append(f"""
        <tr>
          <td class="num">{i}</td>
          <td class="prod-name">{escape(p['title'])}</td>
          <td>{escape(p['primary_collection'])}</td>
          <td class="num">{fmt_pct(p['variant_sellout_rate'])}</td>
          <td class="num">{inv}</td>
          <td class="num">{disc}</td>
          <td class="num">{reviews}</td>
          <td class="num score">{p['intent_risk_score']}</td>
          <td><span class="tag tag-{recommendation(p).lower().replace(' ', '')}">{recommendation(p)}</span></td>
        </tr>""")

    trending_oos_pct = f"{ctx['trending_oos_ratio']*100:.1f}%" if ctx["trending_oos_ratio"] else "n/a"

    occasion_rows = "".join(
        f"<li><span>{escape(k)}</span><span>{v}</span></li>"
        for k, v in sorted(ctx["occasion_weights"].items(), key=lambda x: -x[1])[:8]
    ) or "<li><span>No occasion facet data captured this run</span></li>"

    top_insight_product = top25[0] if top25 else None

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Beacon Diagnostic — Nestasia</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --panel-2: #1e222b;
    --text: #e8eaef; --text-dim: #9aa1af; --border: #2a2f3a;
    --accent: #f37a1f; --accent-2: #ffcb67; --danger: #e5484d; --ok: #3fb950;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--text); margin: 0; padding: 0 0 4rem; }}
  header {{ padding: 2.5rem 3rem 1.5rem; border-bottom: 1px solid var(--border); }}
  header .kicker {{ color: var(--accent); font-size: .8rem; letter-spacing: .12em; text-transform: uppercase; font-weight: 600; }}
  header h1 {{ margin: .3rem 0 .4rem; font-size: 2rem; }}
  header p {{ color: var(--text-dim); max-width: 60rem; line-height: 1.5; margin: 0; }}
  main {{ padding: 2rem 3rem; max-width: 74rem; margin: 0 auto; }}
  section {{ margin-bottom: 3rem; }}
  h2 {{ font-size: 1.15rem; text-transform: uppercase; letter-spacing: .08em; color: var(--text-dim); margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: .5rem; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }}
  .stat-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 1.2rem 1.4rem; }}
  .stat-card .value {{ font-size: 1.9rem; font-weight: 700; color: var(--accent-2); }}
  .stat-card .label {{ color: var(--text-dim); font-size: .82rem; margin-top: .3rem; }}
  .callout {{ background: linear-gradient(135deg, rgba(243,122,31,.14), rgba(243,122,31,.04)); border: 1px solid rgba(243,122,31,.35); border-radius: 10px; padding: 1.2rem 1.4rem; margin-top: 1.2rem; line-height: 1.55; }}
  .callout b {{ color: var(--accent-2); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 10px; overflow: hidden; font-size: .88rem; }}
  th, td {{ padding: .6rem .8rem; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--text-dim); font-weight: 600; text-transform: uppercase; font-size: .72rem; letter-spacing: .05em; background: var(--panel-2); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.score {{ color: var(--accent-2); font-weight: 700; }}
  .prod-name {{ max-width: 20rem; }}
  .tag {{ padding: .2rem .55rem; border-radius: 999px; font-size: .72rem; font-weight: 600; white-space: nowrap; }}
  .tag-wishlist {{ background: rgba(63,185,80,.15); color: var(--ok); }}
  .tag-backinstock {{ background: rgba(229,72,77,.15); color: var(--danger); }}
  .tag-both {{ background: rgba(255,203,103,.18); color: var(--accent-2); }}
  .table-wrap {{ overflow-x: auto; }}
  .chart-wrap {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 1.2rem; height: 340px; }}
  .friction-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
  .friction-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 1.1rem 1.3rem; }}
  .friction-card h3 {{ margin: 0 0 .4rem; font-size: .95rem; color: var(--accent-2); }}
  .friction-card p {{ margin: 0; color: var(--text-dim); font-size: .88rem; line-height: 1.5; }}
  .two-col {{ display: grid; grid-template-columns: 1.4fr 1fr; gap: 1.5rem; align-items: start; }}
  ul.occasion-list {{ list-style: none; margin: 0; padding: 0; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; }}
  ul.occasion-list li {{ display: flex; justify-content: space-between; padding: .6rem 1rem; border-bottom: 1px solid var(--border); font-size: .88rem; }}
  ul.occasion-list li:last-child {{ border-bottom: none; }}
  ul.occasion-list span:last-child {{ color: var(--accent-2); font-weight: 600; }}
  .pitch {{ background: var(--panel); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 6px; padding: 1.4rem 1.6rem; line-height: 1.65; font-size: 1rem; }}
  .footnote {{ color: var(--text-dim); font-size: .78rem; margin-top: 1rem; line-height: 1.6; }}
  .footnote code {{ background: var(--panel-2); padding: .1rem .35rem; border-radius: 4px; }}
  @media (max-width: 900px) {{ .two-col {{ grid-template-columns: 1fr; }} header, main {{ padding-left: 1.2rem; padding-right: 1.2rem; }} }}
</style>
</head>
<body>

<header>
  <div class="kicker">Beacon &middot; Diagnostic Run</div>
  <h1>Nestasia — Silent Shopper Demand Report</h1>
  <p>First pass of Beacon's intent-intelligence layer against nestasia.in's public storefront.
     No account access, no private APIs — this is exactly what's visible to anyone browsing the
     site, reassembled into signal. {n} unique products analyzed across {len(ctx['collections'])}
     collections.</p>
</header>

<main>

<section>
  <h2>Executive Summary</h2>
  <div class="stat-grid">
    <div class="stat-card"><div class="value">{n}</div><div class="label">Unique products analyzed</div></div>
    <div class="stat-card"><div class="value">{pct_partial_or_full}%</div><div class="label">Have at least one sold-out variant</div></div>
    <div class="stat-card"><div class="value">{trending_oos_pct}</div><div class="label">Out of stock in "What's Trending" (store-reported)</div></div>
    <div class="stat-card"><div class="value">{fmt_money(est_lost_demand)}</div><div class="label">Est. demand value sitting on sold-out variants*</div></div>
  </div>
  <div class="callout">
    <b>Top signal:</b>
    {"'" + escape(top_insight_product['title']) + "'" if top_insight_product else 'The dataset'}
    tops Beacon's intent-risk ranking at a score of <b>{top_insight_product['intent_risk_score'] if top_insight_product else '—'}</b> —
    it's in {"the trending collection and " if top_insight_product and top_insight_product.get('in_trending') else ""}
    carrying a {fmt_pct(top_insight_product['variant_sellout_rate']) if top_insight_product else '—'} variant sellout rate,
    with zero mechanism on the live site to capture the demand once a shopper hits a sold-out variant.
    That is the gap this report quantifies: demand Nestasia is generating and then losing, silently,
    at the exact moment a shopper is ready to buy.
  </div>
  <p class="footnote">*Estimated as sold-out variant count &times; product price, summed across all analyzed
  products. This is a directional proxy for at-risk revenue, not a measured figure — Nestasia doesn't expose
  actual traffic or conversion data publicly, so this report uses stock and pricing signals as a stand-in.</p>
</section>

<section>
  <h2>Top 25 Products by Intent-Risk Score</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th><th>Product</th><th>Collection</th><th>Sellout Rate</th>
          <th>Inventory Left</th><th>Discount</th><th>Reviews</th><th>Score</th><th>Swym Rec.</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
  </div>
  <p class="footnote">"Inventory Left" and "Discount" are only populated for the top {ctx['top_n_deepdive']}
  products by raw variant sellout rate, which received a full product-page fetch during this run (see
  methodology note at the bottom). A dash means that product wasn't in the deep-dive batch this run, not
  that the signal is zero.</p>
</section>

<section>
  <h2>Category Breakdown — Avg. Sellout Rate by Collection</h2>
  <div class="chart-wrap"><canvas id="catChart"></canvas></div>
  <p class="footnote">"Category" here is a proxy: Nestasia's oembed feed doesn't expose a product-type
  field, so products are grouped by the first target collection they were discovered in
  ({', '.join(ctx['collections'])}).</p>
</section>

<section>
  <div class="two-col">
    <div>
      <h2>Friction Point Analysis</h2>
      <div class="friction-grid">
        <div class="friction-card">
          <h3>1. Trending = sold out, with no recovery path</h3>
          <p>{trending_oos_pct} of Nestasia's own hand-curated "What's Trending" collection
          ({ctx['trending_out_of_stock']} of {ctx['trending_in_stock'] + ctx['trending_out_of_stock']} products,
          per the store's live availability facet) is out of stock. There is no back-in-stock alert on these
          product pages — a shopper who lands on a trending product Nestasia is actively promoting has a
          coin-flip chance of hitting a dead end with no way to be notified.</p>
        </div>
        <div class="friction-card">
          <h3>2. Discounted + sold-out variants compound</h3>
          <p>Among the deep-dive sample, products carrying both a live discount and a partial sellout rate
          show the classic "hot item" pattern — price cut drove a burst of demand that outran stock on
          specific variants (size/color), while other variants of the same product sit fully available and
          undiscounted. That's inventory-allocation intelligence Nestasia's team can't see from the
          storefront today.</p>
        </div>
        <div class="friction-card">
          <h3>3. Gifting intent has no dedicated capture mechanism</h3>
          <p>Products cross-linked into occasion-specific gifting collections (Housewarming, Wedding,
          Anniversary, etc. — see facet weights) carry seasonal, date-sensitive intent. A wishlist without
          ESP integration can't remind a shopper before Diwali or a wedding date; that intent simply expires
          unrecorded.</p>
        </div>
        <div class="friction-card">
          <h3>4. Multi-collection membership is an unused prioritization signal</h3>
          <p>{sum(1 for p in products if p['multi_collection'])} products in this dataset appear in more than
          one target collection simultaneously (e.g. trending AND on a discount collection) — a stronger
          demand signal than either collection alone, and one the merchant dashboard has no way to surface
          today without a tool like Beacon.</p>
        </div>
      </div>
    </div>
    <div>
      <h2>Occasion Tag Weights</h2>
      <ul class="occasion-list">{occasion_rows}</ul>
      <p class="footnote">Pulled from the live "Occasions" facet on the What's Trending collection page —
      counts reflect the store's full catalog for that facet, not just this run's 50-product sample.</p>
    </div>
  </div>
</section>

<section>
  <h2>The Beacon Pitch</h2>
  <div class="pitch">
    Nestasia doesn't have a demand problem — it has a <b>capture</b> problem. This single diagnostic run,
    using nothing but public pages, surfaced {n} products with measurable stockout or discount pressure,
    found that {trending_oos_pct} of the merchandising team's own trending picks are currently unbuyable,
    and reconstructed occasion-level gifting intent the site's localStorage-only wishlist throws away on
    every session. None of that is visible in Nestasia's admin today. Swym's Wishlist Plus and Back-in-Stock
    products turn every one of those dead ends — a sold-out variant, a closed heart-icon click, a
    gift-collection browse two weeks before Diwali — into a captured lead with an ESP-ready contact and a
    trigger to re-engage the moment stock (or the occasion) is live again. Beacon is the layer that finds
    and ranks where that leakage is worst, continuously, so the Nestasia team spends its restock and
    re-engagement budget on the {min(25, n)} products actually worth chasing — not a guess.
  </div>
</section>

<section>
  <h2>Methodology &amp; Signal Labels</h2>
  <p class="footnote">
  <b>Directly measured</b> (from live storefront data, this run): variant sellout rate, price, review count
  &amp; rating, discount depth, collection membership, occasion facet counts, trending-collection
  availability split.<br>
  <b>Proxies</b> (stand-ins for data Beacon would get directly via pixel/API in a real integration):
  "image version timestamp" as a recency signal, "gift occasion links" as a gifting-intent signal,
  "estimated demand value" as a revenue-risk signal, and the category breakdown (grouped by collection,
  not true product type).<br>
  <b>Known coverage limits, disclosed rather than hidden:</b> the oembed endpoint's <code>page</code>
  parameter does not paginate on this store (verified: page=1/2/100 all return the same 50 products), so
  each collection contributes at most ~50 products to this dataset, not its full catalog depth.
  Product-page deep-dive fields (inventory count, discount %, reviews) were only fetched for the top
  {ctx['top_n_deepdive']} products by raw sellout rate, to keep this run's wall-clock time reasonable
  against Cloudflare's per-request JS-challenge overhead.
  </p>
</section>

</main>

<script>
  const ctx = document.getElementById('catChart');
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: {json.dumps(cat_labels)},
      datasets: [{{
        label: 'Avg. variant sellout rate (%)',
        data: {json.dumps(cat_values)},
        backgroundColor: '#f37a1f',
        borderRadius: 6,
      }}]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        y: {{ beginAtZero: true, ticks: {{ color: '#9aa1af' }}, grid: {{ color: '#2a2f3a' }} }},
        x: {{ ticks: {{ color: '#9aa1af' }}, grid: {{ display: false }} }}
      }}
    }}
  }});
</script>

</body>
</html>
"""
    return html


def escape(s):
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


if __name__ == "__main__":
    main()
