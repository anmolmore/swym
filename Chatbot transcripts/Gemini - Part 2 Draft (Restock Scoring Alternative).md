# Swym Beacon: Product Architecture & Defensibility Strategy

## 1. From Question to Answer: NL Query Execution Architecture

### Data Processing Pipeline
To process merchant queries like *"Which products should I restock first?"*, the system bypasses non-deterministic LLM calculations and routes requests through a four-stage execution pipeline:


```

[NL Merchant Query] ──► [Semantic Intent Router] ──► [Deterministic Intent Engine] ──► [LLM Narrative & Action Layer]

```

1. **Semantic Parsing & Schema Mapping:** The NLU layer maps the query to the `INVENTORY_RESTOCK_PRIORITIZATION` intent class, binding parameters to four core metrics: Back-in-Stock (BIS) subscriptions, wishlist velocity (7-day change), variant sellout rates, and occasion tag proximity weights.
2. **Deterministic Calculation (Non-LLM Engine):** The engine executes a mathematical model over the merchant's first-party graph to generate a **Restock Priority Score (RPS)** and estimate at-risk revenue:

$$\text{RPS} = \left( 0.35 \cdot \frac{\text{Unmet BIS}}{\text{Avg BIS}} + 0.30 \cdot \Delta\text{Wishlist}_{7\text{d}} + 0.20 \cdot \text{Sellout}_{\text{ratio}} + 0.15 \cdot \text{Margin} \right) \times \text{OccasionWeight}$$

$$\text{At-Risk Revenue} = \sum (\text{Unmet BIS Requests} + \text{Saved Carts}) \times \text{Unit Price} \quad \text{}$$

3. **Governed JSON Output:** The engine produces a verified JSON payload containing exact SKU ranks, calculated risk values, and actionable recommendations.
4. **Narrative Synthesis & Workflow Triggers:** The LLM formats the payload into a merchant-facing summary equipped with operational triggers (e.g., *"Draft Purchase Order"* or *"Sync to Klaviyo Restock Flow"*).

### Failure Modes & Safeguards for 50,000 Stores

* **Stale Data Race Conditions:** Recommending restocks for items replenished minutes prior.
  * *Safeguard:* Enforce a real-time verification ping against Shopify's `inventory_levels/update` webhook before rendering responses, capping inventory cache TTL at 60 seconds.
* **Hallucination of Metrics or SKUs:** LLMs generating fabricated metrics.
  * *Safeguard:* Restrict the LLM strictly to formatting raw JSON responses. Run automated output validation checks that verify numbers against the underlying dataset before display.
* **Temporal Demand Distortion:** Recommending restocks for out-of-season products due to stale historical wishlist data.
  * *Safeguard:* Apply exponential decay ($e^{-\lambda t}$) to intent events older than 60 days, discounting non-recurring intent unless aligned with upcoming calendar facets (e.g., Diwali, Christmas).
* **Multi-Tenant Data Leakage:** Cross-tenant context contamination.
  * *Safeguard:* Implement Row-Level Security (RLS) at the database tier and enforce isolated, containerized prompt sandboxes per merchant ID.

---

## 2. Product Defensibility Evaluation

### Platform Absorption Risk (Shopify Sidekick / Native AI)
Basic post-purchase analytics (e.g., querying order history, native inventory levels, or generating product summaries) are standard platform features. Platform owners like Shopify natively control the `orders` and `products` schema, rendering third-party apps that only analyze completed transactions highly vulnerable to platform absorption.

### Durable Moats for Standalone AI Intelligence

| Defensive Moat | Operational Mechanism | Strategic Value |
| :--- | :--- | :--- |
| **1. Pre-Purchase Intent Graph** | Captures pre-purchase intent (wishlists, OOS hits) before an order exists. | Platform analytics only track completed orders; Swym captures uncaptured shopper demand across 45,000+ stores. |
| **2. Multi-Platform Coverage** | Operates across Shopify, BigCommerce, Adobe Commerce, and offline POS stacks. | Platform-native tools (like Sidekick) remain walled gardens inside single platforms. |
| **3. Operational Ecosystem Sync** | Direct API triggers to ERPs (NetSuite) & ESPs (Klaviyo). | Automates restock workflows directly in external execution systems. |

