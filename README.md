# Swym Beacon Product Builder — Submission

Response to the Beacon Product Builder assignment brief. This file maps each
numbered question in the assignment to where it's answered in this repo.

## Part 1: Build

> 1. **Objective:** Select any online store and ship a working tool or script
>    that delivers a clear, actionable insight using public data. Identify
>    key friction points across the shopper journey.
> 2. **Deliverable:** Provide functional, executable output (runnable code,
>    script output, or working video demo). Static decks or unexecuted
>    specifications are not accepted.
> 3. **AI Tooling:** Use any AI assistance desired, but include your prompts
>    and workflow transcript.

→ **[`Part 1 - Build/`](./Part%201%20-%20Build/)**

| File | What it is |
|---|---|
| `nestasia_beacon.py` | Runnable Python script — Playwright + BeautifulSoup pipeline that pulls live intent signals off nestasia.in's public storefront (oembed feeds, collection facets, product pages) and scores products by stockout/demand risk |
| `nestasia_beacon_report.html` | Output of that script — a single-file diagnostic report (executive summary, ranked product table, category chart, friction-point analysis, and the backend/API access this would need from Nestasia to go to production) |
| `NESTASIA_ENGINEERING_QUESTIONS.md` | Follow-up engineering questions for Nestasia, grounded in what the diagnostic could and couldn't determine from public data alone |

Question 3 (AI tooling/transcript) is answered jointly by this section and
`Chatbot transcripts/` below.

## Part 2: Thought Process & Architecture

> 4. **From Question to Answer:** Detail how you would answer a merchant's
>    natural language query (e.g., "Which products should I restock
>    first?") using intent data. Identify potential failure modes and
>    safeguards required before launching to 50,000 stores.
> 5. **Product Defensibility:** Evaluate whether AI merchant intelligence is
>    a defensible standalone product or a feature that platform owners
>    (e.g., Shopify) will inevitably absorb.

→ **[`Part 2 - Thought Process And Architecture.docx`](./Part%202%20-%20Thought%20Process%20And%20Architecture.docx)**

Covers the query-to-answer pipeline (query classification → deterministic
signal assembly and scoring → LLM-narrated answer → action bridge →
feedback loop), a severity-ranked failure-mode table (P0/P1/P2) for scaling
to 50,000 stores, and the defensibility argument (which parts of merchant
intelligence get absorbed by Shopify vs. which are structurally defensible).

An earlier alternative draft of this answer, produced independently via
Gemini, is kept for reference in `Chatbot transcripts/Gemini - Part 2 Draft
(Restock Scoring Alternative).md` — useful for comparing scoring-model
approaches, superseded by the `.docx` above as the actual submission.

## Part 3: Product Thinking & Process

> 6. **Product Discovery & Prioritization:** Briefly outline your framework
>    for identifying high-value merchant problems and deciding which
>    features to prioritize for Beacon.
> 7. **AI Transcript / Reflection:** Include a link to your AI interaction
>    transcript or a short reflection detailing how you leveraged AI tools
>    throughout your workflow.

→ **[`Part 3 - Product Thinking.docx`](./Part%203%20-%20Product%20Thinking.docx)** (Q6)
→ **[`Part 3 - AI Usage.docx`](./Part%203%20-%20AI%20Usage.docx)** (Q7)

Product Thinking covers a four-layer discovery framework (signal-first
problem discovery from Swym's own event data, merchant archetype
segmentation, a three-filter prioritization test, and activation-over-
feature-count sequencing), ending in a phased Beacon roadmap. AI Usage is
the required reflection/transcript pointer, with the full tool-by-tool
breakdown backed by `Chatbot transcripts/`.

## Chatbot transcripts

Raw AI workflow evidence referenced by Part 1 (Q3) and Part 3 (Q7):

| File | Tool | Covers |
|---|---|---|
| `Claude_Code_CHAT_TRANSCRIPT.md` | Claude Code | Full build transcript for the Part 1 diagnostic tool — the original prompt through Cloudflare/Playwright debugging to the final check-in |
| `beacon_claude_transcript.docx` | Claude (claude.ai) | Exported transcript of [this Claude chat](https://claude.ai/share/3c6fc88e-ef6f-46ad-8c4f-9bddf9895ab6) — a separate conversation from the Claude Code build session above |
| `Gemini - Nestasia E-commerce Pipeline Architecture.docx` | Gemini | Independent walkthrough of the Part 1 pipeline architecture and a first pass at Part 2 |
| `Gemini - Part 2 Draft (Restock Scoring Alternative).md` | Gemini | An alternative Part 2 draft with a different restock-scoring model, kept for comparison |
| `ChatGPT - Beacon_Competitor_Analysis_Technical.html` | ChatGPT | Competitive positioning analysis referenced while framing Part 2's defensibility argument |
| `Swym_Beacon_Chat_History_Evaluation.docx` | ChatGPT | Standalone reconstruction of [this ChatGPT chat](https://chatgpt.com/share/6aa94139-cb20-83ee-9432-6d0cc981c84c)'s history (competitor analysis → HTML presentation build) — a separate conversation from the competitor-analysis session above, prepared for evaluation since ChatGPT's native export only supports full-account export |

## Repo structure

```
.
├── README.md                               ← this file
├── Part 1 - Build/
├── Part 2 - Thought Process And Architecture.docx
├── Part 3 - Product Thinking.docx
├── Part 3 - AI Usage.docx
└── Chatbot transcripts/
```
