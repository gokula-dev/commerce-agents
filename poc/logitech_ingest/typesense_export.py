# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Read-only export of Cortex's ``products_en_us`` Typesense collection, filtered to what
Cortex V4's own product-lookup adapter would ever surface (``hideInSearch:false &&
physicalProduct:true``). Never uses the admin key — only ``TYPESENSE_SEARCH_API_KEY``.

    python poc/logitech_ingest/typesense_export.py [--limit N]

Needs TYPESENSE_HOST, TYPESENSE_PORT, TYPESENSE_PROTOCOL, TYPESENSE_SEARCH_API_KEY in the
environment (source dtx-platform's .env, or copy just those four names into your own).
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

COLLECTION = "products_en_us"
ELIGIBILITY_FILTER = "hideInSearch:false && physicalProduct:true"
RAW_DIR = Path(__file__).resolve().parent / "raw"
RAW_FILE = RAW_DIR / "products_en_us.jsonl"

# Some CMS-authored text fields (commerceDescription) carry raw, unescaped newline
# characters — invalid strict JSON, and it breaks a naive per-line split of the export's
# JSONL body. ``strict=False`` tolerates literal control characters inside strings;
# scanning object-by-object (not splitting on "\n") is what survives a document whose own
# string values contain real newlines.
_DECODER = json.JSONDecoder(strict=False)


def iter_json_objects(text: str) -> Iterator[dict[str, Any]]:
    idx, length = 0, len(text)
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            return
        obj, end = _DECODER.raw_decode(text, idx)
        yield obj
        idx = end


def _base_url_and_key() -> tuple[str, str]:
    host = os.environ.get("TYPESENSE_HOST")
    key = os.environ.get("TYPESENSE_SEARCH_API_KEY")
    if not host or not key:
        raise SystemExit(
            "TYPESENSE_HOST and TYPESENSE_SEARCH_API_KEY must be set in the environment — "
            "source dtx-platform's .env, or copy just those names (plus TYPESENSE_PORT / "
            "TYPESENSE_PROTOCOL) into commerce-agents' own .env. Never use TYPESENSE_API_KEY "
            "(the admin key) here — this is a read-only export."
        )
    port = os.environ.get("TYPESENSE_PORT", "443")
    protocol = os.environ.get("TYPESENSE_PROTOCOL", "https")
    return f"{protocol}://{host}:{port}", key


def export(limit: int | None = None) -> Path:
    """Fetch every eligible document and write it back out as JSONL to ``RAW_FILE``, one
    compact ``json.dumps`` per line (re-serialized, so the on-disk file is always
    naive-splittable even though the live export response is not)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    base_url, key = _base_url_and_key()
    with httpx.Client(
        base_url=base_url, headers={"X-TYPESENSE-API-KEY": key}, timeout=60.0
    ) as client:
        response = client.get(
            f"/collections/{COLLECTION}/documents/export",
            params={"filter_by": ELIGIBILITY_FILTER},
        )
        response.raise_for_status()
    documents = list(iter_json_objects(response.text))
    if limit is not None:
        documents = documents[:limit]
    with RAW_FILE.open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(json.dumps(document, ensure_ascii=False))
            handle.write("\n")
    print(f"exported {len(documents)} eligible documents from {COLLECTION} -> {RAW_FILE}")
    return RAW_FILE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="keep only the first N documents (dry run)"
    )
    args = parser.parse_args()
    export(limit=args.limit)


if __name__ == "__main__":
    main()
