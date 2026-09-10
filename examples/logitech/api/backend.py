# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Logitech example API: a StorefrontBackend over **live** queries against Cortex's own
Typesense collection (``products_en_us``) — real hybrid text+vector search per request,
not a one-time export loaded into memory. See ``typesense_client.py`` for the query and
``normalize.py`` for the raw-document -> Product/ProductDetails mapping.

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
    load_orders,
    load_policies,
    load_users,
    orders_for,
    preferences_of,
    search_help,
    summary_of,
    unavailable_detail,
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

from .normalize import normalize_document
from .typesense_client import TypesenseError, get_document_by_product_id, search_documents

DATA_DIR = example_data_dir(__file__)


class LogitechBackend(StorefrontBackend):
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.store_name = "Logitech"
        self._users = load_users(data_dir)
        self._orders = load_orders(data_dir)
        self._policies = load_policies(data_dir)
        self._carts = SessionCarts()
        # A live-fetch cache, not a preloaded catalog: populated as search/lookup calls
        # resolve real documents, so `product()` (the sync path demo_common's routes and
        # the cart gates use — it can't await a network call) only ever resolves what's
        # already been seen this process, mirroring the gates' own "seen this session"
        # provenance model rather than fighting it.
        self.products: dict[str, ProductDetails] = {}
        self.variants: dict[str, ProductDetails] = {}

    def _cache_document(self, doc: dict[str, Any]) -> ProductDetails | None:
        normalized = normalize_document(doc)
        if normalized is None:
            return None
        record = ProductDetails.model_validate(normalized)
        self.products[record.product_id] = record
        for variant in record.variants:
            self.variants[variant.product_id] = variant
        return record

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

    async def search_products(
        self,
        session: ShoppingSessionContext,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 8,
    ) -> list[Product]:
        del session
        try:
            docs = await search_documents(
                query,
                category=filters.category if filters else None,
                min_price=filters.min_price if filters else None,
                max_price=filters.max_price if filters else None,
                limit=limit,
            )
        except TypesenseError:
            # One search failing shouldn't crash the turn — the agent reads an empty
            # result as "nothing found" and says so, per its own prompt rules.
            return []
        results = []
        for doc in docs:
            if record := self._cache_document(doc):
                results.append(summary_of(record))
        return results

    async def get_product_details(
        self, session: ShoppingSessionContext, product_id: str
    ) -> ProductDetails | None:
        del session
        if cached := self.product(product_id):
            return cached
        try:
            doc = await get_document_by_product_id(product_id)
        except TypesenseError:
            return None
        return self._cache_document(doc) if doc else None

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
        del session, product_ids
        return []

    def price_intelligence(self, product_id: str) -> dict[str, Any] | None:
        del product_id
        return None
