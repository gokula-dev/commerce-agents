# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Maps one raw ``products_en_us`` Typesense document (from a live search or lookup —
see ``typesense_client.py``) to the ``Product``/``ProductDetails``-shaped dict
``shopping_agent.types`` expects: a family record with a compact ``variants`` list when
more than one color/size/style is eligible, or a Plain record under the single eligible
variant's own id when there is exactly one (``docs/backends.md`` Step 4).

A copy of ``poc/logitech_ingest/normalize.py``'s mapping logic, not an import from it —
that module lives outside this backend service's root (a sibling of ``examples/``) and,
having no ``.py`` consumers of its own, wouldn't be bundled into the deployed Vercel
function regardless of import path (the same reason ``shopping-agent/skills`` needed its
own copy under ``examples/logitech/``). ``poc/logitech_ingest/`` is kept only as the
historical reference for this mapping, not part of the running app anymore now that
catalog reads are live.

Eligibility, per variant, mirrors Cortex V4's own product-lookup adapter filter:
``not hideInSearch and embargoDate > 0 and embargoDate <= now and (expiryDate == 0 or
expiryDate > now)``. A variant that fails this is dropped rather than shown as "out of
stock" — the raw data has no separate live-inventory signal, only this sellability
window, so ``in_stock`` here means "currently in its sellable window", not "in stock at
a warehouse right now".
"""

from __future__ import annotations

import time
from typing import Any

_IMAGE_BASE = "https://resource.logitech.com"
_OPTION_FIELDS = ("color", "size", "style", "platform", "length")
_MAX_SPECS = 12


def _now_ms() -> int:
    return int(time.time() * 1000)


def _truthy(value: Any) -> bool:
    """Typesense's AEM-sourced booleans arrive stringified (``"true"``/``"false"``), not
    as JSON booleans — a bare Python truthiness check on the string ``"false"`` is wrong."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def variant_eligible(variant: dict[str, Any], *, now_ms: int | None = None) -> bool:
    now_ms = _now_ms() if now_ms is None else now_ms
    if _truthy(variant.get("hideInSearch")):
        return False
    embargo = _as_int(variant.get("embargoDate"))
    if not embargo or embargo > now_ms:
        return False
    expiry = _as_int(variant.get("expiryDate"))
    return expiry == 0 or expiry > now_ms


def _image_url(variant: dict[str, Any]) -> str | None:
    candidate = variant.get("image") or variant.get("angled")
    if not candidate:
        gallery = variant.get("gallery") or []
        candidate = gallery[0].get("path") if gallery and isinstance(gallery[0], dict) else None
    if not candidate:
        return None
    return candidate if candidate.startswith("http") else f"{_IMAGE_BASE}{candidate}"


def _flatten_specs(node: Any, out: dict[str, str], limit: int = _MAX_SPECS) -> None:
    """Best-effort walk of the AEM-authored ``specifications`` tree (nested ``spec``/
    ``specs``/``facet`` objects with no fixed depth) into a flat label -> value dict."""
    if len(out) >= limit:
        return
    if isinstance(node, dict):
        if "facet" in node:
            label = str(node["facet"]).strip()
            value = None
            if node.get("value"):
                value = str(node["value"])
            elif node.get("numeric"):
                value = f"{node['numeric']} {node.get('unit', '')}".strip()
            if value and label and label not in out:
                out[label] = value
            if "specs" in node:
                _flatten_specs(node["specs"], out, limit)
        else:
            for value in node.values():
                if len(out) >= limit:
                    return
                _flatten_specs(value, out, limit)
    elif isinstance(node, list):
        for item in node:
            if len(out) >= limit:
                return
            _flatten_specs(item, out, limit)


def _feature_bullets(product_features: Any) -> list[str]:
    rows = ((product_features or {}).get("features") or {}).get("row") or []
    return [
        row["description"].strip()
        for row in rows
        if isinstance(row, dict) and row.get("description")
    ]


def _package_items(package_contents: Any) -> list[str]:
    rows = ((package_contents or {}).get("package") or {}).get("row") or []
    items = [row.get("item") for row in rows if isinstance(row, dict) and row.get("item")]
    return [str(item) for item in items]


def _specs_of(doc: dict[str, Any]) -> dict[str, str]:
    specs: dict[str, str] = {}
    _flatten_specs(doc.get("specifications"), specs)
    if package_items := _package_items(doc.get("packageContents")):
        specs.setdefault("In the box", ", ".join(package_items))
    if warranty := doc.get("warranty"):
        specs.setdefault("Warranty", str(warranty))
    return specs


def _option_field(variants: list[dict[str, Any]]) -> str | None:
    """Whichever declared variant facet actually varies across the eligible variants."""
    for field in _OPTION_FIELDS:
        values = {v.get(field) for v in variants if v.get(field)}
        if len(values) > 1:
            return field
    return None


def _variant_record(
    variant: dict[str, Any],
    *,
    family_id: str,
    family_title: str,
    brand: str,
    category: str | None,
    option_field: str,
    index: int,
) -> dict[str, Any]:
    # Fully self-contained (title/brand/category included), not a compact "differs from
    # family" row — unlike catalog.json's on-disk format, there's no separate fixture
    # loader here to fill these in from the family record at read time.
    record: dict[str, Any] = {
        "product_id": variant.get("sku") or f"{family_id}-{variant.get('color', 'default')}",
        "title": family_title,
        "brand": brand,
        "category": category,
        "currency": "USD",
        "price": variant.get("price"),
        "in_stock": True,  # only eligible variants reach here
        "variant_of": family_id,
    }
    if option_field in _OPTION_FIELDS and variant.get(option_field):
        record["option_values"] = {option_field: variant[option_field]}
    else:
        record["option_values"] = {"variant": f"option-{index + 1}"}
    if image_url := _image_url(variant):
        record["image_url"] = image_url
    description = variant.get("shortDescription") or variant.get("commerceDescription")
    if description:
        record["short_description"] = description[:280]
    if long_description := variant.get("commerceDescription"):
        record["long_description"] = long_description
    return record


def normalize_document(doc: dict[str, Any], *, now_ms: int | None = None) -> dict[str, Any] | None:
    """One ``Product``/``ProductDetails``-shaped dict (Plain or Family), or ``None`` when
    nothing in the document is currently eligible."""
    variants = [v for v in doc.get("variantsData", []) if variant_eligible(v, now_ms=now_ms)]
    if not variants:
        return None

    family_id = doc["productId"]
    category = None
    if categories := doc.get("categories"):
        category = categories[0]
    elif category_id := doc.get("categoryId"):
        category = category_id

    specs = _specs_of(doc)
    features = _feature_bullets(doc.get("productFeatures"))
    if features:
        specs.setdefault("Highlights", "; ".join(features[:3])[:400])

    if len(variants) == 1:
        variant = variants[0]
        plain: dict[str, Any] = {
            "product_id": variant.get("sku") or family_id,
            "title": doc.get("productName", family_id),
            "brand": doc.get("brand", "Logitech"),
            "price": variant.get("price"),
            "currency": "USD",
            "category": category,
            "in_stock": True,
            "attributes": {},
            "specs": specs,
        }
        if series := doc.get("series"):
            plain["attributes"]["series"] = series
        if image_url := _image_url(variant):
            plain["image_url"] = image_url
        if description := (variant.get("shortDescription") or variant.get("commerceDescription")):
            plain["short_description"] = description[:280]
        if long_description := variant.get("commerceDescription"):
            plain["long_description"] = long_description
        return plain

    option_field = _option_field(variants) or "variant"
    family_title = doc.get("productName", family_id)
    brand = doc.get("brand", "Logitech")
    family: dict[str, Any] = {
        "product_id": family_id,
        "title": family_title,
        "brand": brand,
        "price": min(v["price"] for v in variants if v.get("price") is not None),
        "currency": "USD",
        "category": category,
        "attributes": {},
        "specs": specs,
        "variants": [
            _variant_record(
                v,
                family_id=family_id,
                family_title=family_title,
                brand=brand,
                category=category,
                option_field=option_field,
                index=i,
            )
            for i, v in enumerate(variants)
        ],
    }
    if series := doc.get("series"):
        family["attributes"]["series"] = series
    return family
