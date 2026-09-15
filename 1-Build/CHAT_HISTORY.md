# Chat History — Nestasia Beacon Diagnostic Build

Reference transcript of the session that produced `nestasia_beacon.py` and
`nestasia_beacon_report.html` in this folder. Condensed for readability;
tool-call plumbing and system reminders are omitted, technical content and
decisions are preserved verbatim where practical.

---

## 1. Initial request

The user asked for a working intelligence tool analyzing Nestasia
(nestasia.in), an Indian home decor Shopify Plus brand, for Swym's "Beacon"
merchant-intelligence product. The brief specified:

- Data sources: the `.oembed?page=N` collection endpoint, rendered collection
  HTML (filter/facet sidebars), and product pages.
- A known finding to validate against: in Nestasia's "What's Trending"
  collection, 1,064 of 1,254 products (84.8%) were manually confirmed to be
  out of stock with no recovery mechanism.
- Signals to compute: `variant_sellout_rate`, price, image-version timestamp,
  gift-occasion link density, inventory count, discount depth, review
  count/rating, trending-collection OOS ratio, occasion tag weights.
- A weighted composite `intent_risk_score`.
- Collections to scrape: `whats-trending`, `bestsellers-on-discount`,
  `new-in`, `gifts`, `flat-50-percent-off-offer`.
- Deliverable: a Python script (`nestasia_beacon.py`) using stdlib +
  `requests` + `beautifulsoup4`, producing a single-file HTML report with an
  executive summary, top-25 table, category chart, friction-point analysis,
  and a "Beacon pitch" paragraph — runnable end-to-end in under 5 minutes.

## 2. Environment reality check

Before writing any scraping code, the assistant verified the actual
environment and the actual site behavior rather than trusting the brief's
assumptions:

- The session's working directory is a local macOS machine, not the sandboxed
  `/mnt`-based environment the original prompt assumed — output paths were
  adjusted to a local project folder.
- `curl` against the oembed endpoint, a collection page, and a product page
  all returned **HTTP 403 "Just a moment..."** — Cloudflare's bot-management
  JS challenge — with a normal browser User-Agent. Plain `requests` would not
  retrieve real data at all.

This was flagged to the user directly before proceeding, rather than building
a script against the original (incorrect) assumption.

## 3. Playwright investigation

The assistant installed Playwright + Chromium and ran a series of live probes
to find a working fetch strategy:

- A full headless-browser page load of a collection page cleared the
  Cloudflare challenge after ~6–8 seconds — confirmed by checking for the
  absence of "Just a moment" in the settled DOM and inspecting real page
  content length/title.
- Fetching the `.oembed` endpoint via direct navigation triggered a
  **"Download is starting"** Playwright error — Chromium treats the JSON
  response as a file download in headless mode rather than rendering it. The
  fix: catch that navigation exception and read the payload back via
  `page.expect_download()` / `download.path()`.
- Pagination testing: `page=1`, `page=2`, `page=100`, and no `page` param at
  all were fetched and diffed (product IDs, titles, byte length) — all
  returned the **identical first 50 products**. This proved the oembed
  endpoint's pagination parameter is a no-op on this store, contradicting the
  original brief's assumption of full-catalog pagination.
- Product-page navigation was flaky-looking at first (a stale "Just a moment"
  substring appeared deep in a large, otherwise-real page — traced to an
  unrelated cached JS string, not an active challenge). A longer settle wait
  (~8–9s) confirmed real product HTML loads reliably, including price
  (`.price-item--regular` / `.price-item--sale`) and a Judge.me review
  histogram (`data-rating` / `data-frequency` attributes).
- The oembed JSON schema was confirmed to differ from the brief: variants live
  under the key `offers` (not `variants`), each with `price`, `in_stock`,
  `sku`; and `product_id` is actually the product's URL handle (verified by
  round-tripping `https://nestasia.in/products/{product_id}`).
- Collection-page facet sidebars were confirmed parseable via BeautifulSoup:
  `details.facets__disclosure-vertical` blocks contain an
  `.facets__summary-label` (facet group name, e.g. "Availability",
  "Occasions") and `li.facets__item` rows with a
  `.facet-checkbox__text-label` and a `(<count>)` suffix.

## 4. Script build

Given the above, the assistant built `nestasia_beacon.py` on
**Playwright (headless Chromium) + BeautifulSoup** instead of the originally
specified stdlib+requests stack, with the deviation and its cause documented
directly in the script's module docstring rather than silently substituted.

Pipeline:

1. Fetch oembed JSON (page=1 only, per the confirmed pagination limitation)
   for each of the 5 target collections; dedupe products by `product_id`
   across collections, tracking collection membership.
2. Compute `variant_sellout_rate`, max variant price, image-version
   timestamp (from the thumbnail URL's `?v=` param), and gift-occasion link
   count (occurrences of known gift-collection handles inside each product's
   description HTML).
3. Fetch the rendered `whats-trending` collection page once and parse its
   Availability and Occasions facets for store-wide (not sample-limited)
   counts.
4. Deep-dive the top-N products by raw sellout rate with an individual
   product-page fetch each, extracting low-stock banner text, regular/sale
   price (→ discount depth), and review count/rating from the Judge.me
   histogram.
5. Compute the composite `intent_risk_score` per the brief's stated weights,
   with `None`/missing signals normalized to neutral (0) rather than assumed.
6. Render a single-file HTML report (dark theme, Chart.js via CDN for the
   category-breakdown bar chart) with an executive summary, top-25 table,
   category chart, friction-point analysis, occasion-tag weights, and an
   explicit methodology section labeling which fields are direct measurements
   vs. proxies vs. known coverage limits.

## 5. First run

The script ran end-to-end in ~240 seconds against the live site:

- 239 unique products deduplicated across the 5 collections (50 raw per
  collection, per the oembed cap).
- Live Availability facet on `whats-trending`: **190 in stock / 1,064 out of
  stock** — an exact match to the user's independently, manually confirmed
  84.8% figure from prior research, cross-validating the pipeline against
  known ground truth.
- Top 20 sellout-rate products received a full product-page deep dive.
- Report written and spot-checked (row-level HTML inspected directly) to
  confirm real data — not placeholder — was flowing through every field.

## 6. Iteration: full top-25 deep dive

The user asked to see inventory/discount/review data populated for all 25
table rows, not just the top 20. `TOP_N_DEEPDIVE` was bumped from 20 to 25 and
the script re-run (~287 seconds). Verified: all 25 rows now reflect a real
product-page fetch; blank cells for inventory/discount on some rows reflect
genuinely absent low-stock banners / active discounts on those specific
products, not missing pipeline coverage.

The user opened the resulting `nestasia_beacon_report.html` directly in a
browser.

## 7. Final packaging (this folder)

The user asked to package the whole deliverable for git check-in, framed
explicitly as a **technical pitch to Swym and Nestasia** — engineering effort
and a concrete backend/data-access ask, not a marketing pitch — with all
scripts, the HTML report, and this chat transcript collected into one folder.
Changes made for this pass:

- Removed the "Swym take-home assignment" framing from the script's
  docstring.
- Replaced the report's "Beacon Pitch" marketing section with two technical
  sections: **Engineering Approach & Effort** (documenting the Cloudflare
  bypass and the oembed pagination bug as real engineering work, not
  incidental setup) and **Backend & Data Access Needed From Nestasia** (a
  concrete list: Admin API access, real-time inventory webhooks, order/
  conversion history, wishlist interaction events, customer identity/email
  linkage, and an allowlisted integration path around Cloudflare).
- Collected `nestasia_beacon.py`, `nestasia_beacon_report.html`, and this
  transcript into a single folder for check-in.
