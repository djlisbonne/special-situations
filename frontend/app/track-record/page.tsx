"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Calibration,
  TrackRecord,
  TrackRecordRow,
  getTrackRecord,
  refreshAllPerformance,
} from "@/lib/api";

function pct(n: number | null | undefined, d = 1) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(d)}%`;
}
const GAIN = "#2e7d32";
const LOSS = "#b3261e";
const sign = (n: number | null | undefined) =>
  typeof n === "number" ? (n >= 0 ? GAIN : LOSS) : "#5a5750";

const VERDICT: Record<string, { label: string; color: string }> = {
  validated: { label: "Validated", color: "#2e7d32" },
  partially_validated: { label: "Partial", color: "#8a6d1f" },
  invalidated: { label: "Invalidated", color: "#b3261e" },
  too_early: { label: "Too early", color: "#5a5750" },
};

export default function TrackRecordPage() {
  const [data, setData] = useState<TrackRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setData(await getTrackRecord());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function refreshAll() {
    setBusy(true);
    setError(null);
    try {
      await refreshAllPerformance(true);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl">Track record</h1>
          <p className="sans text-muted mt-2 max-w-2xl">
            Every spin-off the tool scored, lined up against what the market
            actually did. The question that matters for a fund: does a higher
            composite score actually predict higher market-relative alpha?
          </p>
        </div>
        <button
          onClick={refreshAll}
          disabled={busy}
          className="sans text-sm border border-rule rounded-sm px-3 py-1.5 hover:bg-rule/30 disabled:opacity-50 whitespace-nowrap"
        >
          {busy ? "Recomputing…" : "↻ Recompute all"}
        </button>
      </div>

      {error && (
        <div className="text-sm mb-4" style={{ color: LOSS }}>
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-muted animate-pulse">Loading…</div>
      ) : !data || data.count === 0 ? (
        <div className="border border-rule rounded-sm p-8 text-center text-muted">
          No outcomes computed yet. Click <strong>Recompute all</strong> to pull
          price history for every scored event and build the track record.
        </div>
      ) : (
        <>
          <CalibrationCard c={data.calibration} />
          <Scatter rows={data.items} />
          <RecordTable rows={data.items} />
        </>
      )}
    </div>
  );
}

function CalibrationCard({ c }: { c: Calibration }) {
  if (!c || !c.n) return null;
  const hasSplit = typeof c.spread === "number";
  return (
    <div className="border border-rule rounded-sm p-4 mb-6">
      <div className="sans text-xs uppercase tracking-wide text-muted mb-3">
        Calibration · {c.n} priced events
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Metric label="Avg market alpha" value={pct(c.avg_market_alpha)} color={sign(c.avg_market_alpha)} />
        <Metric
          label="Positive-alpha rate"
          value={typeof c.positive_alpha_rate === "number" ? `${Math.round(c.positive_alpha_rate * 100)}%` : "—"}
        />
        {hasSplit && (
          <>
            <Metric label="Top-half avg alpha" value={pct(c.top_half_avg_alpha)} color={sign(c.top_half_avg_alpha)} />
            <Metric label="Bottom-half avg alpha" value={pct(c.bottom_half_avg_alpha)} color={sign(c.bottom_half_avg_alpha)} />
          </>
        )}
      </div>
      {hasSplit && (
        <p className="sans text-xs text-muted mt-3">
          Score edge:{" "}
          <span className="mono" style={{ color: sign(c.spread) }}>
            {pct(c.spread)}
          </span>{" "}
          spread between high-score and low-score halves.{" "}
          {c.spread! > 0
            ? "Higher scores are tracking with higher alpha — the model is adding signal."
            : "Higher scores are NOT yet beating lower ones — treat the score with caution."}
        </p>
      )}
      <p className="sans text-[11px] text-muted mt-2">
        Many events are still pre-distribution, so this is an early read, not a
        seasoned out-of-sample result. Alpha is measured over each event’s
        headline window (since distribution once trading, else since filing).
      </p>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div className="text-2xl mono" style={{ color: color ?? "#0e0f12" }}>
        {value}
      </div>
      <div className="sans text-xs text-muted">{label}</div>
    </div>
  );
}

// Composite score (x) vs realized market alpha (y). The visual a fund manager
// wants: do the dots slope up-and-to-the-right?
function Scatter({ rows }: { rows: TrackRecordRow[] }) {
  const pts = rows
    .filter(
      (r) =>
        typeof r.composite_score === "number" &&
        r.headline &&
        typeof r.headline.market_alpha === "number"
    )
    .map((r) => ({
      x: r.composite_score as number,
      y: r.headline!.market_alpha as number,
      label: r.spinco_ticker || r.parent_ticker || "",
    }));
  if (pts.length < 2) return null;

  const W = 720;
  const H = 260;
  const padL = 44;
  const padR = 12;
  const padT = 12;
  const padB = 30;
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const xMin = Math.min(0, ...xs);
  const xMax = Math.max(10, ...xs);
  const yMin = Math.min(0, ...ys) * 1.1;
  const yMax = Math.max(0, ...ys) * 1.1 || 0.1;
  const px = (x: number) => padL + ((x - xMin) / (xMax - xMin || 1)) * (W - padL - padR);
  const py = (y: number) => padT + (1 - (y - yMin) / (yMax - yMin || 1)) * (H - padT - padB);

  return (
    <div className="border border-rule rounded-sm p-4 mb-6">
      <div className="sans text-xs uppercase tracking-wide text-muted mb-2">
        Composite score vs. realized market alpha
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {/* zero-alpha line */}
        <line x1={padL} x2={W - padR} y1={py(0)} y2={py(0)} stroke="#dcd7c7" />
        <text x={W - padR} y={py(0) - 3} fontSize={9} fill="#5a5750" textAnchor="end" className="sans">
          0 alpha
        </text>
        {/* y ticks */}
        {[yMin, (yMin + yMax) / 2, yMax].map((t, i) => (
          <text key={i} x={padL - 6} y={py(t) + 3} fontSize={9} fill="#5a5750" textAnchor="end" className="mono">
            {pct(t, 0)}
          </text>
        ))}
        {/* x axis label */}
        {[0, 2, 4, 6, 8, 10].map((s) => (
          <text key={s} x={px(s)} y={H - padB + 14} fontSize={9} fill="#5a5750" textAnchor="middle" className="mono">
            {s}
          </text>
        ))}
        <text x={(W) / 2} y={H - 2} fontSize={9} fill="#5a5750" textAnchor="middle" className="sans">
          composite score →
        </text>
        {pts.map((p, i) => (
          <g key={i}>
            <circle cx={px(p.x)} cy={py(p.y)} r={4} fill={p.y >= 0 ? GAIN : LOSS} opacity={0.75} />
            <text x={px(p.x) + 6} y={py(p.y) + 3} fontSize={8} fill="#5a5750" className="mono">
              {p.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function RecordTable({ rows }: { rows: TrackRecordRow[] }) {
  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="border-b border-rule sans text-xs uppercase tracking-wide text-muted">
          <th className="text-left py-2 pr-3">Score</th>
          <th className="text-left py-2 pr-3">Parent → SpinCo</th>
          <th className="text-left py-2 pr-3">Phase</th>
          <th className="text-right py-2 pr-3">Return</th>
          <th className="text-right py-2 pr-3">vs S&P</th>
          <th className="text-right py-2 pr-3">vs sector</th>
          <th className="text-left py-2 pl-3">Verdict</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const h = r.headline;
          const v = r.verdict ? VERDICT[r.verdict] : null;
          return (
            <tr key={r.event_id} className="border-b border-rule/50 hover:bg-rule/20">
              <td className="py-3 pr-3 mono">{r.composite_score?.toFixed(1) ?? "—"}</td>
              <td className="py-3 pr-3">
                <Link href={`/events/${r.event_id}`} className="underline decoration-rule hover:decoration-ink">
                  <span className="text-sm">
                    {r.parent_ticker || r.parent_name}
                    {" → "}
                    {r.spinco_ticker || r.spinco_name || "—"}
                  </span>
                </Link>
              </td>
              <td className="py-3 pr-3 sans text-xs text-muted">{r.phase_label}</td>
              <td className="py-3 pr-3 text-right mono" style={{ color: sign(h?.return) }}>
                {pct(h?.return)}
              </td>
              <td className="py-3 pr-3 text-right mono" style={{ color: sign(h?.market_alpha) }}>
                {pct(h?.market_alpha)}
              </td>
              <td className="py-3 pr-3 text-right mono" style={{ color: sign(h?.sector_alpha) }}>
                {pct(h?.sector_alpha)}
              </td>
              <td className="py-3 pl-3 sans text-xs" style={{ color: v?.color ?? "#5a5750" }}>
                {v?.label ?? "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
