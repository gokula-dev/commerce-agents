# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""A thin, read-only async Typesense client for live catalog queries against
``products_en_us`` — the replacement for the one-time export + static-snapshot
approach in ``poc/logitech_ingest/`` (kept there only as a historical reference for
the normalization mapping, not part of the running app anymore).

Every query includes the same eligibility filter Cortex V4's own product-lookup
adapter applies (``hideInSearch:false && physicalProduct:true``, plus a per-variant
embargo/expiry sellability window), so this never surfaces something Cortex itself
would hide. Search is hybrid: the ``embedding`` field (auto-embedded by Typesense from
each document's ``embeddingText`` at index time) is queried alongside text fields, so a
query like "won't wake up my partner" can match "quiet"/"silent" without either word
appearing literally — real semantic retrieval, not keyword overlap.

Needs TYPESENSE_HOST/PORT/PROTOCOL/TYPESENSE_SEARCH_API_KEY in the environment. Never
uses the admin key — this backend only ever reads.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

COLLECTION = "products_en_us"
BASE_ELIGIBILITY = (
    "hideInSearch:false && physicalProduct:true "
    "&& variantsData.embargoDate:>0"
)
# Text fields weighted like V4's own adapter (title highest, then taxonomy); the
# embedding field adds semantic/hybrid ranking on top of plain text relevance.
QUERY_BY = "productName,categories,brand,embedding"
QUERY_BY_WEIGHTS = "4,2,1,3"


class TypesenseError(RuntimeError):
    """A Typesense call failed; the caller decides how to degrade (see backend.py)."""


# One pooled, keep-alive client for the process lifetime, not one per call — measured
# ~1s per call to search-dev.logitech.com even for a bare /health check (pure network
# round-trip, not query cost), so paying a fresh TCP+TLS handshake on every single
# search/lookup on top of that is pure waste. Doesn't fix the underlying per-request
# round-trip time, but removes the handshake overhead stacked on top of it.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        host = os.environ.get("TYPESENSE_HOST")
        key = os.environ.get("TYPESENSE_SEARCH_API_KEY")
        if not host or not key:
            raise TypesenseError(
                "TYPESENSE_HOST / TYPESENSE_SEARCH_API_KEY not set in the environment"
            )
        port = os.environ.get("TYPESENSE_PORT", "443")
        protocol = os.environ.get("TYPESENSE_PROTOCOL", "https")
        _client = httpx.AsyncClient(
            base_url=f"{protocol}://{host}:{port}",
            headers={"X-TYPESENSE-API-KEY": key},
            timeout=httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _client


async def aclose() -> None:
    """Call from a FastAPI shutdown hook if one gets added; harmless to skip for a
    short-lived dev process."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _price_filter(min_price: float | None, max_price: float | None) -> str | None:
    if min_price is None and max_price is None:
        return None
    lo = min_price if min_price is not None else 0
    hi = max_price if max_price is not None else 100000
    return f"price:[{lo}..{hi}]"


async def search_documents(
    query: str,
    *,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Hybrid text+vector search, hard-filtered to what's eligible and in range."""
    filters = [BASE_ELIGIBILITY]
    if category:
        filters.append(f"categories:=`{category}`")
    if price_filter := _price_filter(min_price, max_price):
        filters.append(price_filter)

    params = {
        "q": query,
        "query_by": QUERY_BY,
        "query_by_weights": QUERY_BY_WEIGHTS,
        "filter_by": " && ".join(filters),
        "sort_by": "_text_match:desc,categoryRanking:asc",
        "per_page": limit,
        "exclude_fields": "embedding",
        "prioritize_exact_match": "true",
    }
    try:
        response = await _get_client().get(
            f"/collections/{COLLECTION}/documents/search", params=params
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TypesenseError(f"search failed: {exc}") from exc
    return [hit["document"] for hit in response.json().get("hits", [])]


async def get_document_by_product_id(product_id: str) -> dict[str, Any] | None:
    """One product by its family id (``productId``) *or* a variant's own sku (a
    customer naming a specific color they were shown resolves by sku, not family id)."""
    params = {
        "q": "*",
        "query_by": "productName",
        "filter_by": (
            f"{BASE_ELIGIBILITY} && "
            f"(productId:=`{product_id}` || variantsData.sku:=`{product_id}`)"
        ),
        "per_page": 1,
        "exclude_fields": "embedding",
    }
    try:
        response = await _get_client().get(
            f"/collections/{COLLECTION}/documents/search", params=params
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TypesenseError(f"lookup failed: {exc}") from exc
    hits = response.json().get("hits", [])
    return hits[0]["document"] if hits else None
