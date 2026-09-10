# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""GCP Retail Search as an alternate ranking backend, toggleable against the default
Typesense hybrid search (see ``typesense_client.py``) via ``SEARCH_BACKEND`` in
``backend.py`` — the same A/B pattern Cortex itself settled on in dtx-platform PR #7813
(CTX-697): **GCP ranks candidate product ids; content is still hydrated from Typesense**,
so a toggle changes only the ranking engine, never where product content comes from.

GCP Retail Search is keyword + Google's own ML ranking over structured catalog
attributes — no embedding-vector semantic search of its own, unlike Typesense's hybrid
approach here. This calls the REST API directly (not the ``google-cloud-retail`` gRPC
SDK) to stay consistent with this backend's lightweight httpx style and avoid a much
heavier dependency (grpcio) in a Vercel Python function.

Needs GCP_PROJECT_ID and GCP_SERVICE_ACCOUNT_JSON (raw or base64 service account key)
in the environment; GCP_RETAIL_CATALOG/SERVING_CONFIG/LOCATION/BRANCH all have the same
defaults dtx-platform's ``@logi/retail-search`` uses.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
# Filter syntax (bare `price`, not `priceInfo.price`, which GCP rejects; `attributes.X`
# for custom catalog attributes; ANY() for set membership) mirrors what dtx-platform's
# PR #7813 (CTX-697) confirmed working against the live catalog, not re-derived here.
# That PR also ships a `series` ranking boost (+0.3, tuned via an LLM-judge harness) —
# not ported here since this backend's SearchFilters has no series concept to boost on.


class GcpRetailError(RuntimeError):
    """A GCP Retail Search call failed; the caller decides how to degrade."""


def _decode_service_account_json(raw: str) -> dict[str, Any]:
    trimmed = raw.strip()
    try:
        if trimmed.startswith("{"):
            return json.loads(trimmed)
        return json.loads(base64.b64decode(trimmed).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise GcpRetailError(
            "GCP_SERVICE_ACCOUNT_JSON is set but could not be parsed (expected raw JSON "
            "starting with '{' or base64-encoded JSON)."
        ) from exc


_credentials: service_account.Credentials | None = None


def _get_access_token() -> str:
    """A cached, auto-refreshing OAuth2 bearer token — minted once per process, renewed
    only once actually expired (google-auth's own ``valid`` check), not per call."""
    global _credentials
    if _credentials is None:
        raw = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
        if not raw:
            raise GcpRetailError("GCP_SERVICE_ACCOUNT_JSON not set in the environment")
        info = _decode_service_account_json(raw)
        _credentials = service_account.Credentials.from_service_account_info(
            info, scopes=_SCOPES
        )
    if not _credentials.valid:
        _credentials.refresh(Request())
    return _credentials.token


def _serving_config_path() -> str:
    project = os.environ.get("GCP_PROJECT_ID")
    if not project:
        raise GcpRetailError("GCP_PROJECT_ID not set in the environment")
    location = os.environ.get("GCP_RETAIL_LOCATION", "global")
    catalog = os.environ.get("GCP_RETAIL_CATALOG", "default_catalog")
    config = os.environ.get("GCP_RETAIL_SERVING_CONFIG", "default_serving_config")
    return f"projects/{project}/locations/{location}/catalogs/{catalog}/servingConfigs/{config}"


def _branch_path() -> str:
    project = os.environ.get("GCP_PROJECT_ID")
    location = os.environ.get("GCP_RETAIL_LOCATION", "global")
    catalog = os.environ.get("GCP_RETAIL_CATALOG", "default_catalog")
    branch = os.environ.get("GCP_RETAIL_BRANCH", "0")
    return f"projects/{project}/locations/{location}/catalogs/{catalog}/branches/{branch}"


def _base_filter_clauses(now_ms: int) -> list[str]:
    return [
        'attributes.physicalProduct: ANY("True")',
        f"attributes.embargoDate <= {now_ms}",
        f"attributes.expiryDate >= {now_ms}",
    ]


def _price_clause(min_price: float | None, max_price: float | None) -> str | None:
    clauses = []
    if min_price is not None:
        clauses.append(f"price >= {min_price}")
    if max_price is not None:
        clauses.append(f"price <= {max_price}")
    return " AND ".join(clauses) if clauses else None


def _build_filter(category: str | None, min_price: float | None, max_price: float | None) -> str:
    clauses = [f"({c})" for c in _base_filter_clauses(int(time.time() * 1000))]
    clauses.append('(NOT attributes.isSparepart: ANY("True"))')
    if category:
        clauses.append(f'(categories: ANY("{category}"))')
    if price_clause := _price_clause(min_price, max_price):
        clauses.append(f"({price_clause})")
    return " AND ".join(clauses)


async def search_candidate_ids(
    query: str,
    *,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    visitor_id: str,
    limit: int = 8,
) -> list[str]:
    """Ranked candidate product ids only — GCP does the ranking, the caller hydrates
    full content from Typesense (this module never returns product content)."""
    token = _get_access_token()
    placement = _serving_config_path()
    request_body = {
        "placement": placement,
        "branch": _branch_path(),
        "query": query,
        "visitorId": visitor_id,
        "pageSize": limit,
        "filter": _build_filter(category, min_price, max_price),
        "queryExpansionSpec": {"condition": "AUTO", "pinUnexpandedResults": True},
        "spellCorrectionSpec": {"mode": "AUTO"},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        try:
            response = await client.post(
                f"https://retail.googleapis.com/v2/{placement}:search",
                json=request_body,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            detail = getattr(exc, "response", None)
            body = detail.text[:300] if detail is not None else str(exc)
            raise GcpRetailError(f"GCP Retail Search failed: {body}") from exc

    results = response.json().get("results", [])
    candidate_ids: list[str] = []
    for result in results:
        product = result.get("product", {})
        # GCP frequently returns `id` as "" with the slug living in `name` instead
        # (confirmed in dtx-platform's own GcpProduct adapter comments) — same
        # fallback Cortex's gcp-retail-search.tool.ts uses.
        product_id = product.get("id") or (product.get("name", "").rstrip("/").split("/")[-1])
        if product_id:
            candidate_ids.append(product_id)
    return candidate_ids
