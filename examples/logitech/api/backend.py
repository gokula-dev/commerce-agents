# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Logitech example API: a StorefrontBackend over a real catalog synced from Cortex's own
Typesense collection (``poc/logitech_ingest/build_catalog.py``), for comparing the
commerce-agents shopping agent against Cortex V4 on the same underlying product data.

Cortex itself exposes no cart, checkout, orders, or store-policy tools — it is a pure
search-and-recommend assistant — so this backend's cart is a genuine *added* capability
kept in-memory for the comparison, not something to read as like-for-like with Cortex.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from demo_common.storefront_fixtures import (
    SessionCarts,
    example_data_dir,
    find_product,
    keyword_score,
    load_catalog,
    load_orders,
    load_policies,
    load_users,
    option_text,
    orders_for,
    preferences_of,
    rank_products,
    search_help,
    summary_of,
    unavailable_detail,
    within_price_and_rating,
)
from shopping_agent import (
    Cart,
    FulfillmentOption,
    Order,
    Policy,
    Product,
    ProductDetails,
    SearchFilters,
    ShoppingSessionContext,
    StorefrontBackend,
    Unavailable,
    UserPreferences,
)

DATA_DIR = example_data_dir(__file__)

_SEARCH_WEIGHTS = {
    "title": 3.0,
    "brand": 2.0,
    "category": 2.0,
    "attributes": 1.5,
    "description": 1.0,
}
_SYNONYMS: dict[str, list[str]] = {
    "mouse": ["mice"],
    "mice": ["mouse"],
    "webcam": ["camera"],
    "camera": ["webcam"],
    "headset": ["headphones", "earbuds"],
    "headphones": ["headset"],
    "keyboard": ["keys"],
    "wireless": ["cordless", "bluetooth"],
    "cordless": ["wireless"],
}
# Not a real inventory signal (see poc/logitech_ingest/normalize.py's module docstring):
# in_stock here means "currently in Cortex's own sellability window", not live stock.
_SEARCHABLE_ATTRIBUTE_SKIP = {"synced_at"}


class LogitechBackend(StorefrontBackend):
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        catalog, self.products, self.variants = load_catalog(data_dir)
        self.store_name: str = catalog.get("store_name", "Logitech")
        self._users = load_users(data_dir)
        self._orders = load_orders(data_dir)
        self._policies = load_policies(data_dir)
        self._carts = SessionCarts()

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def product(self, product_id: str) -> ProductDetails | None:
        return find_product(self.products, self.variants, product_id)

    def listing_of(self, product_id: str) -> ProductDetails | None:
        record = self.product(product_id)
        if record is not None and record.variant_of:
            return self.products.get(record.variant_of)
        return record

    def _searchable_text(self, product: ProductDetails) -> dict[str, str]:
        return {
            "title": product.title,
            "brand": product.brand or "",
            "category": product.category or "",
            "attributes": (
                " ".join(
                    f"{k} {v}"
                    for k, v in product.attributes.items()
                    if k not in _SEARCHABLE_ATTRIBUTE_SKIP
                )
                + " "
                + option_text(product)
            ),
            "description": f"{product.short_description or ''} {product.long_description or ''}",
        }

    def _score(self, product: ProductDetails, query_tokens: list[str]) -> float:
        return keyword_score(
            self._searchable_text(product), _SEARCH_WEIGHTS, query_tokens, _SYNONYMS
        )

    @staticmethod
    def _soft_filter(product: ProductDetails, filters: SearchFilters) -> bool:
        if filters.category and filters.category.lower() not in (product.category or "").lower():
            return False
        if not filters.attributes:
            return True
        haystack = " ".join(
            f"{k}={v}".lower()
            for k, v in product.attributes.items()
            if k not in _SEARCHABLE_ATTRIBUTE_SKIP
        )
        haystack += f" {product.title.lower()} {option_text(product).lower()}"
        return all(str(value).lower() in haystack for value in filters.attributes.values())

    async def search_products(
        self,
        session: ShoppingSessionContext,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 8,
    ) -> list[Product]:
        del session
        ranked = rank_products(
            self.products.values(),
            query,
            filters,
            limit,
            score=self._score,
            hard_filter=within_price_and_rating,
            soft_filter=self._soft_filter,
        )
        return [summary_of(product) for product in ranked]

    async def get_product_details(
        self, session: ShoppingSessionContext, product_id: str
    ) -> ProductDetails | None:
        del session
        return self.product(product_id)

    # ------------------------------------------------------------------
    # Cart — a real capability this reference architecture adds beyond Cortex, which has
    # no cart/checkout tools at all.
    # ------------------------------------------------------------------

    async def get_cart(self, session: ShoppingSessionContext) -> Cart:
        return self._carts.cart(session.session_id)

    async def add_to_cart(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart:
        product = self.product(product_id)
        if product is None or product.has_options:
            raise KeyError(product_id)
        if not product.in_stock:
            raise Unavailable(unavailable_detail(product, self.listing_of(product_id)))
        existing = self._carts.lines(session.session_id).get(product_id)
        quantity += existing.quantity if existing else 0
        return self._carts.put(session.session_id, product, quantity)

    async def update_cart_item(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart:
        return self._carts.set_quantity(session.session_id, product_id, quantity)

    async def remove_from_cart(self, session: ShoppingSessionContext, product_id: str) -> Cart:
        return self._carts.remove(session.session_id, product_id)

    def reset_session(self, session_id: str) -> None:
        self._carts.reset(session_id)

    # ------------------------------------------------------------------
    # Customer, orders, policies, fulfillment — none of this exists in the source data
    # (Typesense has no order history or policy content), so these stay honestly empty
    # rather than fabricating stand-ins (docs/backends.md Step 6). The corresponding
    # tools are disabled in ShoppingAgentConfig; the methods still exist because
    # StorefrontBackend declares them as abstract regardless.
    # ------------------------------------------------------------------

    async def get_preferences(self, session: ShoppingSessionContext) -> UserPreferences:
        return preferences_of(self._users, session.user_id)

    async def get_orders(self, session: ShoppingSessionContext, limit: int = 5) -> list[Order]:
        return orders_for(self._orders, session.user_id, limit)

    async def get_order(self, session: ShoppingSessionContext, order_id: str) -> Order | None:
        del session, order_id
        return None

    def recent_orders(self, limit: int = 6) -> list[Order]:
        del limit
        return []

    async def search_policies(self, session: ShoppingSessionContext, query: str) -> list[Policy]:
        del session
        return search_help(self._policies, query)

    async def get_fulfillment_options(
        self, session: ShoppingSessionContext, product_ids: list[str]
    ) -> list[FulfillmentOption]:
        # enable_fulfillment=False means this tool is never offered to the model, but
        # StorefrontBackend still declares the method abstract.
        del session, product_ids
        return []

    def price_intelligence(self, product_id: str) -> dict[str, Any] | None:
        del product_id
        return None
