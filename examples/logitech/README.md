# Logitech (real-data comparison example)

Not a fictional vertical like the other four — this example runs the shopping agent over
a **real Logitech product catalog**, synced from the same Typesense collection
(`products_en_us`) that Logitech's own Cortex V4 assistant queries in production. It
exists to compare this reference architecture against Cortex V4 on identical underlying
data, for an internal Logitech/dtx-platform evaluation. It intentionally breaks the
repo-wide "only ACME, nothing real" convention (see `CLAUDE.md`) for that reason, and is
not meant to be upstreamed.

No merchant side (Cortex has no merchant-agent equivalent), no orders/policies/fulfillment
tools (the source data has none of that content — see "What's real vs. simplified" below).
Cart and checkout-staging are on, as a capability this architecture adds beyond Cortex.

## Setup

```bash
pip install -r requirements.txt                             # once, from the repo root (venv)
(cd examples && npm ci)                                      # once, workspace-wide

# TYPESENSE_HOST / TYPESENSE_PORT / TYPESENSE_PROTOCOL / TYPESENSE_SEARCH_API_KEY —
# source dtx-platform's .env, or copy just those four names into your own. Never use
# TYPESENSE_API_KEY (the admin key) for this — it's a read-only export.
python poc/logitech_ingest/build_catalog.py                  # writes examples/logitech/data/
```

`build_catalog.py` is rerunnable (catalog.json/policies.json/orders.json/manifest.json
are regenerated and gitignored every run — see the root `.gitignore`); `data/users.json`
is a small hand-authored guest profile, not derived from Typesense, and is tracked.

**On Vercel, this data ships as a static snapshot, not a build-time sync.** The
Typesense host used here (`search-dev.logitech.com`) isn't reachable from Vercel's build
infrastructure (403 Forbidden) — it's a dev-environment host, presumably locked to the
corporate network/VPN. `.vercelignore` deliberately does *not* exclude
`examples/logitech/data/*.json`, so whatever you last generated locally is what gets
deployed. To refresh the live demo: rerun `build_catalog.py` locally, then redeploy.

## Run

```bash
uvicorn logitech.api.main:app --app-dir examples --reload --port 8004
(cd examples/logitech/storefront-web && npm run dev)          # :3004
```

Chat needs Anthropic credentials in the environment (`ANTHROPIC_API_KEY`, or
`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` for an internal gateway like LogiQ); browsing
the catalog does not.

## Try

1. I need a quiet wireless mouse for the office, nothing too big — budget around $50.
2. Compare the top two for me.
3. Add the one you'd recommend to my cart.

For the Cortex-comparison writeup, run the same prompts against Cortex V4 and compare:
tool-call shape, product accuracy, latency, and how each handles a query the catalog
can't satisfy.

## What's real vs. simplified

- **Real**: every product's title, price, brand, category, images, and specs, synced
  live from `products_en_us`, filtered to `hideInSearch:false && physicalProduct:true` —
  the same eligibility filter Cortex V4's own product-lookup adapter applies, so this
  example never surfaces something Cortex itself would hide. Color/size variant families
  are modeled properly (a family record with real `variantsData`-derived options), not
  flattened.
- **Simplified — `in_stock` is a sellability window, not live inventory.** Derived from
  each variant's `embargoDate`/`expiryDate` (the same signal Cortex V4 trusts for
  sellability), not a warehouse stock count. A variant outside that window is dropped
  from the catalog entirely rather than shown as "out of stock" — the source data has no
  separate live-inventory signal to show it with.
- **Absent, not fabricated**: no order history, no store policies (returns/shipping), no
  review ratings — none of this exists in the source collection, so `enable_orders`,
  `enable_policies`, and `enable_fulfillment` are off rather than inventing stand-in
  content for a real brand (`docs/backends.md` Step 6). `search_policies` always returns
  nothing; `get_orders` always returns empty.
- One product id collision on ingestion (541 unique listings from 542 eligible raw
  documents — see `data/manifest.json` after a build) and a handful of raw
  `productId`/`productName` mismatches inherited from the source data itself; neither
  is worth chasing for this comparison's purposes.

## What is specific to this example

- `poc/logitech_ingest/` (repo root, not under `examples/`): `typesense_export.py` (the
  read-only Typesense export), `normalize.py` (raw document → `ProductDetails` mapping,
  including Plain-vs-Family modeling), `build_catalog.py` (orchestrator).
- `api/backend.py`: `LogitechBackend`, the `StorefrontBackend` over the synced catalog —
  reuses `demo_common.storefront_fixtures`' generic search/ranking helpers, same as the
  other verticals.
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
