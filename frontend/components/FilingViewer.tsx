"use client";

import { ReactNode, useState } from "react";
import { publicApiBase } from "@/lib/api";

type Props = {
  eventId: number;
  primaryDocUrl: string;
  children: ReactNode;
};

// Splits the event detail page into a content column and a collapsible filing
// pane on the right. The pane iframes a same-origin proxy (`/events/:id/document`)
// so EDGAR's missing CORS headers don't block embedding, and so we can repair
// stale primary-doc URLs server-side before serving.
export function FilingViewer({ eventId, primaryDocUrl, children }: Props) {
  const [open, setOpen] = useState(false);
  const src = `${publicApiBase()}/events/${eventId}/document`;

  return (
    <div className="flex gap-6 items-start">
      <div className={open ? "min-w-0 flex-1 lg:basis-1/2" : "min-w-0 flex-1"}>
        <div className="mb-4 flex justify-end">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="sans text-xs uppercase tracking-wide border border-rule px-3 py-1.5 hover:bg-rule/30"
            aria-expanded={open}
          >
            {open ? "Hide filing" : "Read filing →"}
          </button>
        </div>
        {children}
      </div>
      {open && (
        <aside className="hidden lg:flex flex-col w-1/2 shrink-0 border border-rule rounded-sm sticky top-6 self-start h-[calc(100vh-3rem)] bg-paper">
          <div className="flex items-center justify-between border-b border-rule px-3 py-2 sans text-xs">
            <span className="uppercase tracking-wide text-muted">
              Filing document
            </span>
            <div className="flex items-center gap-3">
              <a
                href={primaryDocUrl}
                target="_blank"
                rel="noreferrer"
                className="underline text-ink"
              >
                Open in new tab ↗
              </a>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-muted hover:text-ink"
                aria-label="Close filing viewer"
              >
                ✕
              </button>
            </div>
          </div>
          <iframe
            src={src}
            title="Filing document"
            sandbox="allow-same-origin allow-popups"
            className="flex-1 w-full bg-white"
          />
        </aside>
      )}
    </div>
  );
}
