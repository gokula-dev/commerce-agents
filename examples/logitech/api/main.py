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

from commerce_common.memory import InMemoryMemoryStore
from demo_common import CartAddRequest, MemorySeeder, build_storefront_host, load_demo_env
from shopping_agent_runtime import ShoppingAgent

from .agent_config import build_shopping_config
from .backend import DATA_DIR, LogitechBackend

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


@app.post("/api/cart/add")
async def cart_add(request: CartAddRequest, record: host.CurrentSession) -> dict:
    return await host.direct_add(
        record,
        request,
        note="Customer tapped the add-to-cart button on {title} ({product_id}), quantity {quantity}.",
    )
