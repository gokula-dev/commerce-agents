// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import Link from "next/link";
import { useCallback } from "react";
import { AgentApi, type AgentTurn, Chat as ChatShell, Composer, useAgentTurn, useSession } from "web-shared";
import { Pending } from "@/components/Chat";
import GenerativeBlock from "@/components/generative";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8004";
const WIDE = new Set(["comparison", "plan"]);

// Two fully separate sessions against the two pinned compare stacks main.py mounts
// (/api/compare/ts, /api/compare/gcp) — not the single toggleable backend the main page
// uses. Each keeps its own cart/session state; this page only ever reads chat.
const apiTs = new AgentApi(API_URL, "/api/compare/ts/api");
const apiGcp = new AgentApi(API_URL, "/api/compare/gcp/api");

const UNREACHABLE_TS = "Couldn't reach the Typesense compare session on port 8004.";
const UNREACHABLE_GCP = "Couldn't reach the GCP Retail Search compare session on port 8004.";

function ColumnHome({ label }: { label: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1.5 px-6 text-center">
      <p className="text-[15px] font-semibold text-(--ink)">{label}</p>
      <p className="max-w-[34ch] text-[13.5px] text-(--ink-soft)">Ask a question below — it runs on both engines at once, same message, same moment.</p>
    </div>
  );
}

function Column({ label, chat }: { label: string; chat: AgentTurn }) {
  return (
    <div className="flex h-full min-w-0 flex-1 flex-col border-b border-(--line) sm:border-r sm:border-b-0 last:border-r-0">
      <div className="flex shrink-0 items-center justify-between border-b border-(--line) bg-(--well)/40 px-4 py-2">
        <span className="text-[12.5px] font-semibold tracking-wide text-(--ink)">{label}</span>
        {chat.busy ? <span className="text-[11.5px] text-(--ink-soft)">thinking…</span> : null}
      </div>
      <div className="min-h-0 flex-1">
        <ChatShell
          chat={chat}
          home={<ColumnHome label={label} />}
          wide={WIDE}
          renderPending={(item) => <Pending item={item} />}
          renderBlock={(segment) => <GenerativeBlock block={segment.block} status={segment.status} />}
        />
      </div>
    </div>
  );
}

export default function ComparePage() {
  const sessionTs = useSession(apiTs);
  const sessionGcp = useSession(apiGcp);

  const chatTs = useAgentTurn(apiTs, { sessionId: sessionTs.sessionId, unreachable: UNREACHABLE_TS });
  const chatGcp = useAgentTurn(apiGcp, { sessionId: sessionGcp.sessionId, unreachable: UNREACHABLE_GCP });

  const ready = chatTs.ready && chatGcp.ready;
  const busy = chatTs.busy || chatGcp.busy;

  // One composer, one message — fired at both sessions in the same tick so the two
  // columns answer the identical prompt in parallel, not staggered.
  const send = useCallback(
    (text: string) => {
      void chatTs.send(text);
      void chatGcp.send(text);
    },
    [chatTs, chatGcp],
  );

  return (
    <div className="flex h-dvh flex-col bg-(--surface)">
      <header className="flex shrink-0 items-center justify-between border-b border-(--line) px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span aria-hidden className="grid h-[26px] w-[26px] place-items-center rounded-lg bg-(--ink) text-[13px] font-bold text-(--surface)">
            L
          </span>
          <span className="text-[14.5px] font-semibold text-(--ink)">Search backend A/B compare</span>
        </div>
        <Link href="/" className="text-[13px] font-medium text-(--ink-soft) transition-colors hover:text-(--ink)">
          ← Back to assistant
        </Link>
      </header>
      <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
        <Column label="Typesense" chat={chatTs} />
        <Column label="GCP Retail Search" chat={chatGcp} />
      </div>
      <div className="shrink-0 border-t border-(--line) bg-(--card) p-3">
        <Composer send={send} ready={ready} busy={busy} label="Ask both engines" placeholder="Ask about a product — sent to both engines at once…" />
      </div>
    </div>
  );
}
