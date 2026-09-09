# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Export products_en_us from Cortex's Typesense instance, normalize it into the shape
``examples/logitech``'s ``StorefrontBackend`` expects, and write ``examples/logitech/data/``.

    python poc/logitech_ingest/build_catalog.py [--limit N]

Rerunnable: catalog.json/policies.json/orders.json/manifest.json are regenerated every
run (and gitignored — see the repo .gitignore); users.json is written only if missing,
since it's hand-authored, not derived from Typesense.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from normalize import normalize_document
from typesense_export import export

DATA_DIR = Path(__file__).resolve().parents[2] / "examples" / "logitech" / "data"

_DEFAULT_USERS = {
    "users": [
        {
            "user_id": "demo-user",
            "display_name": "Jordan",
            "loyalty_tier": "Guest",
            "default_location": "Fremont",
            "preferences": {},
        }
    ]
}


def build(limit: int | None = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_file = export(limit=limit)
    # str.splitlines() also breaks on Unicode line-separator characters (U+2028 and
    # friends) that can legitimately sit inside a JSON string's text content; splitting
    # on a literal "\n" only (what the writer actually delimits on) avoids that.
    lines = [json.loads(line) for line in raw_file.read_text(encoding="utf-8").split("\n") if line]

    products: list[dict] = []
    families = 0
    plains = 0
    variants_total = 0
    dropped: list[str] = []
    for doc in lines:
        entry = normalize_document(doc)
        if entry is None:
            dropped.append(doc.get("productId", "<unknown>"))
            continue
        products.append(entry)
        if "variants" in entry:
            families += 1
            variants_total += len(entry["variants"])
        else:
            plains += 1

    catalog = {"store_name": "Logitech", "products": products}
    (DATA_DIR / "catalog.json").write_text(json.dumps(catalog, indent=1), encoding="utf-8")

    if not (DATA_DIR / "users.json").exists():
        (DATA_DIR / "users.json").write_text(json.dumps(_DEFAULT_USERS, indent=1), encoding="utf-8")

    (DATA_DIR / "orders.json").write_text(json.dumps({"orders": []}, indent=1), encoding="utf-8")
    (DATA_DIR / "policies.json").write_text(
        json.dumps({"policies": []}, indent=1), encoding="utf-8"
    )

    manifest = {
        "synced_at": datetime.now(UTC).isoformat(),
        "raw_documents": len(lines),
        "eligible_products": len(products),
        "plain_products": plains,
        "family_products": families,
        "variants_total": variants_total,
        "dropped_no_eligible_variant": dropped,
    }
    (DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    print(
        f"catalog: {len(products)} products ({plains} plain, {families} families, "
        f"{variants_total} variants); {len(dropped)} dropped (no eligible variant)"
    )
    print(f"wrote {DATA_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="cap raw documents fetched (dry run)"
    )
    args = parser.parse_args()
    build(limit=args.limit)


if __name__ == "__main__":
    main()
