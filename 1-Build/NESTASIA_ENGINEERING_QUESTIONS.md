# Questions for Nestasia Engineering

Follow-up to the Beacon diagnostic in this folder (`nestasia_beacon_report.html`).
The report's "Backend & Data Access Needed From Nestasia" section lists what a
production integration would need; these are the specific questions to ask
Nestasia's engineering team to figure out how to actually get there.

## Platform & access

1. Is the storefront's Cloudflare configuration (bot management / WAF rules)
   something your team controls directly, or is it managed by an agency/
   partner? Who owns changes to it?
2. Would you be open to allowlisting a Swym IP range or service token so a
   Beacon integration doesn't have to render pages through a browser to get
   past the bot challenge?
3. Do you have a Shopify Plus plan tier that supports custom app installs, or
   would a Beacon integration need to go through the Shopify App Store review
   process?
4. Is there an existing internal API layer (BFF, middleware) in front of
   Shopify Admin API that we should integrate against instead of hitting
   Shopify directly?

## Inventory & catalog

5. What system is source-of-truth for inventory — native Shopify inventory,
   or an external OMS/ERP synced into Shopify? How often does that sync run?
6. Is `inventory_quantity` tracked per-variant reliably across your whole
   catalog, or are some products using continue-selling / untracked
   inventory policies that would make a stock signal unreliable?
7. Do you use Shopify's `inventory_levels/update` webhook today for anything?
   If not, is there an appetite to add a subscriber for back-in-stock
   triggers?
8. Is there a `product_type` or structured category taxonomy maintained
   consistently across the catalog? (Our diagnostic had to proxy "category"
   with collection membership because this wasn't available publicly.)

## Orders & conversion

9. Can you share (even directionally/aggregated) add-to-cart and checkout-
   start rates for a sample of the products flagged in the top-25 table, to
   sanity-check the sellout-rate-based scoring against real demand?
10. Is order data queryable per-SKU historically, e.g. to see whether a
    product's sellout coincided with a spike in orders vs. a supply-side
    stockout with no demand signal at all?

## Wishlist & customer identity

11. What does the current heart-icon wishlist actually write today — is it
    purely `localStorage`, or does anything touch a Shopify customer
    metafield or a third-party app's backend?
12. Is customer email captured at any point before checkout (newsletter
    signup, account creation) that could be linked to wishlist/browse
    behavior, or is email only ever collected at checkout?
13. Do you have an existing ESP (Klaviyo, etc.) already wired into Shopify
    events, or would back-in-stock / wishlist re-engagement need a new
    integration from scratch?

## Rollout & ownership

14. Who on your side would own an integration like this once live —
    is there a dedicated eng contact for Shopify app/webhook integrations?
15. Are there other apps currently installed that already touch inventory
    webhooks, checkout, or the wishlist UI that a new integration would need
    to coexist with (e.g. conflicting webhook subscriptions, theme app
    blocks)?
