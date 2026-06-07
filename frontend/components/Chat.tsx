"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { listChat, sendChat, ChatMessageOut } from "@/lib/api";

const SUGGESTED = [
  "What is the stated rationale for the spin-off?",
  "What is the post-spin capital structure of SpinCo?",
  "Does management have equity incentives tied to SpinCo?",
  "What are the biggest disclosed risks?",
  "What is the expected record date and distribution date?",
];

export function Chat({ eventId }: { eventId: number }) {
  const { data, mutate, isLoading } = useSWR<ChatMessageOut[]>(
    `/events/${eventId}/chat`,
    () => listChat(eventId),
  );
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [data?.length]);

  async function ask(q: string) {
    if (!q.trim() || pending) return;
    setPending(true);
    setInput("");
    try {
      await sendChat(eventId, q);
      await mutate();
    } finally {
      setPending(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    ask(input);
  }

  return (
    <div className="border border-rule rounded-sm flex flex-col h-[600px]">
      <div className="px-4 py-3 border-b border-rule sans text-sm">
        <span className="font-medium">Ask the filing</span>
        <span className="text-muted ml-2">— answers cite the document verbatim.</span>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {isLoading && <div className="text-muted text-sm">Loading…</div>}
        {!isLoading && !data?.length && (
          <div className="space-y-2">
            <div className="sans text-xs text-muted uppercase tracking-wide">Suggested</div>
            <ul className="space-y-1">
              {SUGGESTED.map((s) => (
                <li key={s}>
                  <button
                    className="text-left text-sm underline decoration-rule hover:decoration-ink"
                    onClick={() => ask(s)}
                  >
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {data?.map((m) => (
          <MessageBubble key={m.id} m={m} />
        ))}
        {pending && (
          <div className="text-muted sans text-sm italic">Reading the filing…</div>
        )}
      </div>
      <form onSubmit={onSubmit} className="border-t border-rule p-3 flex gap-2">
        <input
          className="flex-1 sans text-sm bg-transparent border border-rule rounded-sm px-3 py-2 focus:outline-none focus:border-ink"
          placeholder="Ask a question about this filing…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={pending}
        />
        <button
          type="submit"
          className="sans text-sm px-4 py-2 border border-ink bg-ink text-paper rounded-sm disabled:opacity-50"
          disabled={pending || !input.trim()}
        >
          Ask
        </button>
      </form>
    </div>
  );
}

function MessageBubble({ m }: { m: ChatMessageOut }) {
  if (m.role === "user") {
    return (
      <div className="ml-12 border border-rule rounded-sm p-3 bg-rule/20">
        <div className="sans text-xs text-muted uppercase tracking-wide mb-1">You</div>
        <div className="text-sm whitespace-pre-wrap">{m.content}</div>
      </div>
    );
  }
  return (
    <div className="mr-12">
      <div className="sans text-xs text-muted uppercase tracking-wide mb-1">Assistant</div>
      <div className="text-sm whitespace-pre-wrap leading-relaxed">{m.content}</div>
      {m.citations?.length > 0 && (
        <div className="mt-3 space-y-1">
          {m.citations.map((c) => (
            <div key={c.id} className="sans text-xs text-muted border-l-2 border-rule pl-2 italic">
              [{c.id}] “{c.quote}”
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
