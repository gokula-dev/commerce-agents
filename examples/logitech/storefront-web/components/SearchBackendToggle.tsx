// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { useEffect, useState } from "react";
import { fetchSearchBackend, setSearchBackend } from "@/lib/api";

const LABELS: Record<string, string> = {
  typesense: "Typesense",
  "gcp-retail-search": "GCP Retail Search",
};

/**
 * A global, process-wide toggle — every visitor shares one active backend — for
 * demoing the Typesense vs. GCP Retail Search ranking comparison live, no restart.
 * Not a per-session preference; there is exactly one LogitechBackend instance.
 */
export default function SearchBackendToggle() {
  const [backend, setBackend] = useState<string | null>(null);
  const [options, setOptions] = useState<string[]>(["typesense", "gcp-retail-search"]);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchSearchBackend().then((state) => {
      if (cancelled || !state) return;
      setBackend(state.backend);
      if (state.options?.length) setOptions(state.options);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function choose(next: string) {
    if (next === backend || pending) return;
    setPending(true);
    const confirmed = await setSearchBackend(next);
    if (confirmed) setBackend(confirmed);
    setPending(false);
  }

  if (!backend) return null;

  return (
    <div
      className="flex items-center gap-0.5 rounded-full border border-(--line) bg-(--well)/60 p-0.5 text-[11.5px]"
      title="Which engine ranks search results — a demo-only, shared toggle"
    >
      {options.map((option) => {
        const active = option === backend;
        return (
          <button
            key={option}
            type="button"
            disabled={pending}
            onClick={() => choose(option)}
            aria-pressed={active}
            className={`rounded-full px-2.5 py-1 font-medium transition-colors disabled:opacity-60 ${
              active
                ? "bg-(--ink) text-(--surface)"
                : "text-(--ink-soft) hover:bg-(--well)"
            }`}
          >
            {LABELS[option] ?? option}
          </button>
        );
      })}
    </div>
  );
}
