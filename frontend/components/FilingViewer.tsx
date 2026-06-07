"use client";

import { ReactNode, useEffect, useState } from "react";
import {
  FilingDocument,
  listEventDocuments,
  publicApiBase,
} from "@/lib/api";

type Props = {
  eventId: number;
  primaryDocUrl: string;
  children: ReactNode;
};

const KIND_LABEL: Record<FilingDocument["kind"], string> = {
  primary: "Cover form",
  information_statement: "Information statement",
  separation_agreement: "Separation agreement",
  exhibit: "Exhibit",
};

function docLabel(d: FilingDocument): string {
  return `${KIND_LABEL[d.kind]} — ${d.name}`;
}

// Splits the event detail page into a content column and a collapsible filing
// pane on the right. The pane iframes a same-origin proxy
// (`/events/:id/document`) so EDGAR's missing CORS headers don't block
// embedding, and so we can repair stale primary-doc URLs server-side. A picker
// in the header switches between the cover form, the information statement,
// and the separation agreement.
export function FilingViewer({ eventId, primaryDocUrl, children }: Props) {
  const [open, setOpen] = useState(false);
  const [docs, setDocs] = useState<FilingDocument[] | null>(null);
  const [selected, setSelected] = useState<string>(""); // "" = server default

  useEffect(() => {
    if (!open || docs !== null) return;
    let alive = true;
    listEventDocuments(eventId)
      .then((r) => {
        if (!alive) return;
        setDocs(r.documents);
        // Prefer information statement once we know it exists; cover form is
        // usually thin boilerplate.
        const info = r.documents.find(
          (d) => d.kind === "information_statement",
        );
        if (info) setSelected(info.name);
      })
      .catch(() => {
        if (alive) setDocs([]);
      });
    return () => {
      alive = false;
    };
  }, [open, docs, eventId]);

  const base = publicApiBase();
  const src =
    `${base}/events/${eventId}/document` +
    (selected ? `?file=${encodeURIComponent(selected)}` : "");
  const openInTab = selected
    ? `${base}/events/${eventId}/document?file=${encodeURIComponent(selected)}`
    : primaryDocUrl;

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
          <div className="flex items-center justify-between border-b border-rule px-3 py-2 sans text-xs gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <span className="uppercase tracking-wide text-muted shrink-0">
                Filing
              </span>
              {docs && docs.length > 0 ? (
                <select
                  value={selected}
                  onChange={(e) => setSelected(e.target.value)}
                  className="bg-paper border border-rule rounded-sm px-1.5 py-0.5 max-w-[28ch] truncate"
                  aria-label="Select document"
                >
                  {docs.map((d) => (
                    <option key={d.name} value={d.name}>
                      {docLabel(d)}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="text-muted">
                  {docs === null ? "loading…" : "primary document"}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <a
                href={openInTab}
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
