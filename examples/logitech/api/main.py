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

from commerce_common.memory import InMemoryMemoryStore
from demo_common import (
    REPO_ROOT,
    CartAddRequest,
    MemorySeeder,
    build_storefront_host,
    load_demo_env,
)
from shopping_agent_runtime import ShoppingAgent

from .agent_config import build_shopping_config
from .backend import DATA_DIR, LogitechBackend

load_demo_env(DATA_DIR.parent)

backend = LogitechBackend()
agent = ShoppingAgent(
    backend=backend,
    skills_dir=REPO_ROOT / "shopping-agent" / "skills",
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


@app.post("/api/cart/add")
async def cart_add(request: CartAddRequest, record: host.CurrentSession) -> dict:
    return await host.direct_add(
        record,
        request,
        note="Customer tapped the add-to-cart button on {title} ({product_id}), quantity {quantity}.",
    )
