# Logitech (real-data comparison example)

Not a fictional vertical like the other four — this example runs the shopping agent over
**live queries against Cortex's own Typesense collection** (`products_en_us`), the same
one Logitech's Cortex V4 assistant queries in production. It exists to compare this
reference architecture against Cortex V4 on identical underlying data, for an internal
Logitech/dtx-platform evaluation. It intentionally breaks the repo-wide "only ACME,
nothing real" convention (see `CLAUDE.md`) for that reason, and is not meant to be
upstreamed.

No merchant side (Cortex has no merchant-agent equivalent), no orders/policies/fulfillment
tools (the source data has none of that content — see "What's real vs. simplified" below).
Cart and checkout-staging are on, as a capability this architecture adds beyond Cortex.

## Architecture: live search, not a snapshot

`LogitechBackend.search_products`/`get_product_details` call Typesense **on every
request** (`api/typesense_client.py`) — a hybrid text + vector query (`query_by` includes
`embedding`, auto-embedded by Typesense from each document's `embeddingText`), hard-filtered
to `hideInSearch:false && physicalProduct:true` plus a per-variant embargo/expiry
sellability window, the same eligibility Cortex V4's own product-lookup adapter applies.
Results are normalized (`api/normalize.py` — Plain vs. Family/variant modeling, per
`docs/backends.md` Step 4) and cached in-process as they're seen, so cart/gate logic (which
needs a synchronous, already-resolved lookup) can resolve anything the agent has already
searched or fetched this session.

**This means TYPESENSE_HOST/PORT/PROTOCOL/TYPESENSE_SEARCH_API_KEY must be reachable at
*runtime*, not just from your own machine.** `search-dev.logitech.com` (the host in
dtx-platform's default `.env`) is a dev-environment host that returns 403 from Vercel's
infrastructure — confirmed when we tried syncing at Vercel *build* time earlier; the same
block applies to a live *runtime* call. **Before deploying this version anywhere,
confirm a Typesense endpoint that's actually reachable from that environment** — check
what host the `cortex` Vercel project uses in its **Production** environment variables
(likely different from dtx-platform's local dev default), or get your platform team to
extend that same network path to wherever this runs. Locally, this all works today
because the local machine already has whatever network access (VPN/corporate network)
`search-dev.logitech.com` requires.

`poc/logitech_ingest/` (the one-time export/normalize/build-catalog scripts from an
earlier version of this example) is kept only as a **historical reference** for the
raw-document mapping — it's not part of the running app anymore.

## Setup

```bash
pip install -r requirements.txt                             # once, from the repo root (venv)
(cd examples && npm ci)                                      # once, workspace-wide
```

No ingestion step anymore — there's no catalog data to generate. `data/users.json` is a
small hand-authored guest profile (not derived from Typesense); `orders.json`/
`policies.json` are empty-shaped placeholders the fixture loader expects to exist.

## Run

```bash
# TYPESENSE_HOST / TYPESENSE_PORT / TYPESENSE_PROTOCOL / TYPESENSE_SEARCH_API_KEY —
# source dtx-platform's .env, or copy just those four names into your own. Never use
# TYPESENSE_API_KEY (the admin key) — this backend only ever reads.
uvicorn logitech.api.main:app --app-dir examples --reload --port 8004
(cd examples/logitech/storefront-web && npm run dev)          # :3004
```

Chat needs Anthropic credentials in the environment (`ANTHROPIC_API_KEY`, or
`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` for an internal gateway like LogiQ) *and* the
four `TYPESENSE_*` vars above — both catalog browsing and chat now depend on live
Typesense access.

## Try

1. My wrist hurts from clicking all day, need something that won't make it worse, budget around $60.
2. Compare the top two for me.
3. Add the one you'd recommend to my cart.

Query 1 is deliberately indirect (no "ergonomic"/"trackball" literal match) — it's a real
test of the hybrid text+vector retrieval, not keyword luck. For the Cortex-comparison
writeup, run the same prompts against Cortex V4 and compare: tool-call shape, product
accuracy, latency, and how each handles a query the catalog can't satisfy.

## What's real vs. simplified

- **Real**: every product's title, price, brand, category, images, and specs, queried
  live from `products_en_us` on every request, filtered to the same eligibility Cortex
  V4's own product-lookup adapter applies — this never surfaces something Cortex itself
  would hide. Color/size variant families are modeled properly (a family record with real
  `variantsData`-derived options), not flattened. Search is genuinely semantic (hybrid
  text + vector), not keyword overlap — verified against queries with zero literal
  keyword match to the right products.
- **Simplified — `in_stock` is a sellability window, not live inventory.** Derived from
  each variant's `embargoDate`/`expiryDate` (the same signal Cortex V4 trusts for
  sellability), not a warehouse stock count. A variant outside that window is dropped
  from search results entirely rather than shown as "out of stock" — the source data has
  no separate live-inventory signal to show it with.
- **Absent, not fabricated**: no order history, no store policies (returns/shipping), no
  review ratings — none of this exists in the source collection, so `enable_orders`,
  `enable_policies`, and `enable_fulfillment` are off rather than inventing stand-in
  content for a real brand (`docs/backends.md` Step 6). `search_policies` always returns
  nothing; `get_orders` always returns empty.
- **`GET /api/products` (bulk catalog browse) only shows what's been searched/looked-up
  this process** — there's no "list everything" equivalent against a search API the way
  there was against a preloaded dict. Low impact: the storefront-web homepage's "Popular
  right now" section already never renders (relies on a `labels` field this data doesn't
  set), and cart/comparison rendering only ever needs products the agent has already
  resolved.
- A handful of raw `productId`/`productName` mismatches inherited from the source data
  itself (not our normalization) aren't worth chasing for this comparison's purposes.

## What is specific to this example

- `api/typesense_client.py`: the live hybrid search/lookup calls, read-only, using
  `TYPESENSE_SEARCH_API_KEY` only.
- `api/normalize.py`: raw Typesense document → `Product`/`ProductDetails` mapping
  (Plain-vs-Family modeling) — a copy of, not an import from, the historical
  `poc/logitech_ingest/normalize.py`, for the same Vercel-bundling reason as `skills/`
  below.
- `api/backend.py`: `LogitechBackend` — live search/lookup with an in-process cache
  backing the synchronous provenance-gate/cart code paths that can't await a network call.
- `api/agent_config.py`: `ShoppingAgentConfig` scoped to match Cortex's own capability
  surface (cart on; orders, policies, fulfillment, disclosures, web search off).
- `api/main.py`: no merchant router, in-memory (not file-backed) memory store — this is a
  point-in-time comparison run, not a persistent deployment.
- `skills/`: a **copy** of `../../shopping-agent/skills/`, not a reference to it —
  Vercel's Python function bundle only ships the backend service's own root (`examples/`)
  plus pip-installed packages; a sibling directory with no `.py` files in it never makes
  it into the deployed bundle. Keep in sync by hand if the source skills change.
- `storefront-web/`: copied from `../retail/storefront-web/` and adapted — peripherals
  glyphs in `lib/format.ts`, port 3004, no fabricated shipping/returns copy in the cart
  and checkout components (removed rather than left showing retail's placeholder terms
  against a real product).
