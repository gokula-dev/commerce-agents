# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""The Logitech example's shopping agent config — no environment knobs, unlike retail's
merchant config, since this example has no merchant side."""

from __future__ import annotations

from shopping_agent import ShoppingAgentConfig

_DOMAIN_SEARCH_NOTES = (
    "This catalog spans mice, keyboards, webcams, headsets, speakers, and video-"
    "conferencing gear. Match the customer's own vocabulary (mouse/mice, wireless/"
    "cordless, ergonomic) rather than the catalog's category labels, and put a stated "
    "connectivity, color, or use case (gaming, office, travel) in the query wording."
)


def build_shopping_config() -> ShoppingAgentConfig:
    return ShoppingAgentConfig(
        brand_name="Logitech",
        assistant_name="the Logitech shopping assistant",
        brand_voice="direct, plain about trade-offs, technical when it helps",
        domain_search_notes=_DOMAIN_SEARCH_NOTES,
        enable_cart=True,
        enable_orders=False,
        enable_policies=False,
        enable_fulfillment=False,
        enable_disclosures=False,
        enable_web_search=False,
    )
