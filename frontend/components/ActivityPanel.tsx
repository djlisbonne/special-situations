"use client";

import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { ActivityEventOut, publicApiBase, recentActivity } from "@/lib/api";

const MAX_KEEP = 200;

function levelColor(level: ActivityEventOut["level"]): string {
  switch (level) {
    case "success":
      return "bg-emerald-700";
    case "warn":
      return "bg-amber-700";
    case "error":
      return "bg-rose-700";
    default:
      return "bg-muted/60";
  }
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso.slice(11, 19);
  }
}

export function ActivityPanel() {
  const [events, setEvents] = useState<ActivityEventOut[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // Initial backfill
  useEffect(() => {
    let alive = true;
    recentActivity(100)
      .then((rows) => {
        if (alive) setEvents(rows.slice().reverse()); // newest first
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Live stream
  useEffect(() => {
    const url = `${publicApiBase()}/activity/stream`;
    const es = new EventSource(url);
    esRef.current = es;

    const onMsg = (e: MessageEvent) => {
      try {
        const ev = JSON.parse(e.data) as ActivityEventOut;
        setEvents((prev) => [ev, ...prev].slice(0, MAX_KEEP));
      } catch {
        /* ignore */
      }
    };
    es.addEventListener("message", onMsg);
    es.addEventListener("open", () => setConnected(true));
    es.onerror = () => setConnected(false);

    return () => {
      es.removeEventListener("message", onMsg);
      es.close();
    };
  }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-baseline justify-between mb-3">
        <div className="sans text-xs uppercase tracking-wide text-muted">
          Activity
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={clsx(
              "h-1.5 w-1.5 rounded-full",
              connected ? "bg-emerald-700" : "bg-muted/50",
            )}
            title={connected ? "Live" : "Disconnected"}
          />
          <span className="sans text-[10px] uppercase tracking-wide text-muted">
            {connected ? "live" : "offline"}
          </span>
        </div>
      </div>

      {events.length === 0 ? (
        <div className="sans text-xs text-muted leading-relaxed">
          No activity yet. Trigger a scan from the{" "}
          <a href="/scan" className="underline">
            Scan
          </a>{" "}
          page; pipeline steps will stream here in real time.
        </div>
      ) : (
        <ul className="flex-1 overflow-y-auto -mr-2 pr-2 space-y-3">
          {events.map((e, i) => (
            <li key={`${e.ts}-${i}`} className="flex gap-2.5">
              <span
                className={clsx(
                  "mt-1.5 h-1.5 w-1.5 rounded-full shrink-0",
                  levelColor(e.level),
                )}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="mono text-[10px] text-muted tabular-nums">
                    {fmtTime(e.ts)}
                  </span>
                  <span className="mono text-[10px] text-muted truncate">
                    {e.stage}
                  </span>
                </div>
                <div className="sans text-xs leading-snug text-ink/90 break-words">
                  {e.message}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
