# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Logitech example API: the shopping agent over a real catalog synced from Cortex's own
Typesense collection, for comparing commerce-agents against Cortex V4 on the same data.

    uvicorn logitech.api.main:app --app-dir examples --reload --port 8004

No merchant router — Cortex has no merchant-agent equivalent to compare against. Memory
is in-memory only (not file-backed like retail's): this is a point-in-time comparison run,
not a persistent deployment.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from commerce_common.memory import InMemoryMemoryStore
from demo_common import (
    CartAddRequest,
    MemorySeeder,
    StorefrontHost,
    build_storefront_host,
    load_demo_env,
)
from shopping_agent_runtime import ShoppingAgent

from .agent_config import build_shopping_config
from .backend import DATA_DIR, GCP_RETAIL_SEARCH, TYPESENSE, LogitechBackend

_VALID_BACKENDS = {TYPESENSE, GCP_RETAIL_SEARCH}

load_demo_env(DATA_DIR.parent)

# A local copy of shopping-agent/skills, not a reference to the repo root: Vercel's
# Python function bundle only ships the backend service's own root (examples/) plus
# pip-installed packages (vendored separately) — a sibling directory of examples/ with
# no .py files in it, like the real shopping-agent/skills/, never makes it into the
# deployed bundle at all, whatever path is used to reach it.
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

backend = LogitechBackend()
agent = ShoppingAgent(
    backend=backend,
    skills_dir=SKILLS_DIR,
    config=build_shopping_config(),
    memory_store=InMemoryMemoryStore(),
)

host = build_storefront_host(
    title="Logitech shopping agent demo API",
    example_root=DATA_DIR.parent,
    backend=backend,
    agent=agent,
    # No data/memory-seed.json — MemorySeeder tolerates a missing file (seeds nothing).
    memory_seeder=MemorySeeder(DATA_DIR / "memory-seed.json"),
)
app = host.app


def _build_compare_stack(*, search_backend: str) -> StorefrontHost:
    """A second, independent backend+agent+host pinned to one ranking engine — for the
    side-by-side A/B compare page, which needs two live sessions running the same turn
    in parallel rather than one shared instance toggled between requests."""
    compare_backend = LogitechBackend(search_backend=search_backend)
    compare_agent = ShoppingAgent(
        backend=compare_backend,
        skills_dir=SKILLS_DIR,
        config=build_shopping_config(),
        memory_store=InMemoryMemoryStore(),
    )
    return build_storefront_host(
        title=f"Logitech shopping agent demo API ({search_backend})",
        example_root=DATA_DIR.parent,
        backend=compare_backend,
        agent=compare_agent,
        memory_seeder=MemorySeeder(DATA_DIR / "memory-seed.json"),
    )


# Mounted, not routed: each is a fully separate app (own SessionStore, own agent, own
# pinned backend), so two visitors — or one compare page driving both at once — never
# share cart/session state across engines. Reachable at /api/compare/ts/api/* and
# /api/compare/gcp/api/*; the doubled "/api" is the mount prefix plus each sub-app's own
# route prefix, harmless and kept so both mounts still live inside Vercel's existing
# `/api/(.*)` -> backend rewrite without any routing changes.
app.mount("/api/compare/ts", _build_compare_stack(search_backend=TYPESENSE).app)
app.mount("/api/compare/gcp", _build_compare_stack(search_backend=GCP_RETAIL_SEARCH).app)


@app.post("/api/cart/add")
async def cart_add(request: CartAddRequest, record: host.CurrentSession) -> dict:
    return await host.direct_add(
        record,
        request,
        note="Customer tapped the add-to-cart button on {title} ({product_id}), quantity {quantity}.",
    )


class SearchBackendRequest(BaseModel):
    backend: str


@app.get("/api/search-backend")
async def get_search_backend() -> dict:
    """Which candidate-ranking engine is active — for demo visibility, not consumed by
    the agent itself."""
    return {"backend": backend.search_backend, "options": sorted(_VALID_BACKENDS)}


@app.post("/api/search-backend")
async def set_search_backend(request: SearchBackendRequest) -> dict:
    """Switch the ranking engine live, no restart — a global, process-wide toggle (every
    visitor shares it) for demo purposes, not a per-session preference."""
    if request.backend not in _VALID_BACKENDS:
        raise HTTPException(
            status_code=400, detail=f"backend must be one of {sorted(_VALID_BACKENDS)}"
        )
    backend.search_backend = request.backend
    return {"backend": backend.search_backend}
