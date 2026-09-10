// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import { AgentApi } from "web-shared";
import type { CartPayload, Product, ProductDetails } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8004";

export const api = new AgentApi(API_URL, "/api");

export const UNREACHABLE =
  "Couldn't reach the Logitech demo API on port 8004. Start it with " +
  "`uvicorn logitech.api.main:app --app-dir examples --port 8004` and try again.";

export async function fetchProducts(): Promise<Product[] | null> {
  const data = await api.get<{ products: Product[] }>("/products", { limit: "100" });
  return data?.products ?? null;
}

export function fetchProduct(productId: string): Promise<ProductDetails | null> {
  return api.get<ProductDetails>(`/products/${encodeURIComponent(productId)}`);
}

export async function addToCart(productId: string, quantity = 1): Promise<CartPayload | null> {
  const data = await api.post<{ cart: CartPayload }>("/cart/add", { product_id: productId, quantity });
  return data?.cart ?? null;
}

export interface SearchBackendState {
  backend: string;
  options?: string[];
}

/** A global, process-wide toggle (every visitor shares it) — for comparing the
 * Typesense and GCP Retail Search ranking backends live, not a per-session setting. */
export function fetchSearchBackend(): Promise<SearchBackendState | null> {
  return api.get<SearchBackendState>("/search-backend");
}

export async function setSearchBackend(backend: string): Promise<string | null> {
  const data = await api.post<{ backend: string }>("/search-backend", { backend });
  return data?.backend ?? null;
}
