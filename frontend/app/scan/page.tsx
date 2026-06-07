"use client";

import { useEffect, useState } from "react";
import { ScanStatus, getScan, triggerScan } from "@/lib/api";

export default function ScanPage() {
  const [starting, setStarting] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lookback, setLookback] = useState(30);

  // Poll for completion when a run is in progress.
  useEffect(() => {
    if (!runId) return;
    let alive = true;
    const tick = async () => {
      try {
        const s = await getScan(runId);
        if (!alive) return;
        setStatus(s);
        if (s.finished) return;
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
      if (alive) setTimeout(tick, 1500);
    };
    tick();
    return () => {
      alive = false;
    };
  }, [runId]);

  async function start() {
    setStarting(true);
    setError(null);
    setStatus(null);
    try {
      const r = await triggerScan(lookback);
      setRunId(r.scan_run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  const running = runId !== null && (!status || !status.finished);

  return (
    <div className="max-w-xl">
      <h1 className="text-3xl mb-2">Run a scan</h1>
      <p className="sans text-muted mb-6">
        Pull recent Form 10-12B / 10-12B-A filings from EDGAR, classify, and run the Greenblatt
        scoring pipeline. The nightly scheduler also runs this automatically.
      </p>

      <div className="space-y-4 border border-rule rounded-sm p-4">
        <label className="block">
          <div className="sans text-sm text-muted mb-1">Lookback (days)</div>
          <input
            type="number"
            value={lookback}
            min={1}
            max={180}
            onChange={(e) => setLookback(Number(e.target.value))}
            className="sans border border-rule rounded-sm px-3 py-2 w-32 bg-transparent"
            disabled={running}
          />
        </label>
        <button
          className="sans text-sm px-4 py-2 border border-ink bg-ink text-paper rounded-sm disabled:opacity-50"
          onClick={start}
          disabled={running || starting}
        >
          {starting ? "Starting…" : running ? "Scanning…" : "Run scan now"}
        </button>
        {running && (
          <p className="sans text-xs text-muted">
            Watch the Activity panel on the right to follow each pipeline step.
          </p>
        )}
      </div>

      {status?.finished && status.ok && (
        <div className="mt-6 p-4 border border-emerald-700 bg-emerald-50 rounded-sm">
          <div className="sans text-sm">
            Scan #{status.scan_run_id} complete: found{" "}
            <strong>{status.filings_seen}</strong> filing(s); created{" "}
            <strong>{status.events_created}</strong> new event(s).
          </div>
        </div>
      )}
      {status?.finished && !status.ok && (
        <div className="mt-6 p-4 border border-rose-700 bg-rose-50 rounded-sm text-sm">
          Scan #{status.scan_run_id} failed: {status.error}
        </div>
      )}
      {error && (
        <div className="mt-6 p-4 border border-rose-700 bg-rose-50 rounded-sm text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
