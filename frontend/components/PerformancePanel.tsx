"use client";

import { useEffect, useState } from "react";
import {
  Corroboration,
  PerfReport,
  PerformanceResponse,
  getPerformance,
  refreshPerformance,
} from "@/lib/api";
import { PerfChart, ChartSeries } from "./PerfChart";

function pct(n: number | null | undefined, digits = 1) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

function pp(n: number | null | undefined) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}pp`;
}

const GAIN = "#2e7d32";
const LOSS = "#b3261e";
const signColor = (n: number | null | undefined) =>
  typeof n === "number" ? (n >= 0 ? GAIN : LOSS) : "#5a5750";

const VERDICT_STYLE: Record<string, { label: string; bg: string; fg: string }> = {
  validated: { label: "Thesis validated", bg: "#e3efe3", fg: "#2e7d32" },
  partially_validated: { label: "Partially validated", bg: "#f3eede", fg: "#8a6d1f" },
  invalidated: { label: "Thesis invalidated", bg: "#f6e2df", fg: "#b3261e" },
  too_early: { label: "Too early to judge", bg: "#eceae3", fg: "#5a5750" },
};

const AXIS_STATUS: Record<string, { mark: string; color: string }> = {
  confirmed: { mark: "✓", color: "#2e7d32" },
  contradicted: { mark: "✗", color: "#b3261e" },
  not_yet_testable: { mark: "·", color: "#5a5750" },
};

function prettyAxis(k: string) {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function PerformancePanel({ eventId }: { eventId: number }) {
  const [data, setData] = useState<PerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getPerformance(eventId)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [eventId]);

  async function onRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      setData(await refreshPerformance(eventId));
    } catch (e) {
      setError(String(e));
    } finally {
      setRefreshing(false);
    }
  }

  if (loading) {
    return (
      <Shell>
        <div className="text-muted text-sm animate-pulse">Loading price history & outcome…</div>
      </Shell>
    );
  }
  if (error) {
    return (
      <Shell>
        <div className="text-sm" style={{ color: LOSS }}>
          Couldn’t load performance: {error}
        </div>
      </Shell>
    );
  }

  const report = data?.report;
  if (!report || !report.has_data) {
    return (
      <Shell onRefresh={onRefresh} refreshing={refreshing}>
        <p className="text-sm text-muted">
          No price history available yet
          {report?.notes?.length ? ` — ${report.notes[0]}` : "."}
        </p>
      </Shell>
    );
  }

  return (
    <Shell
      onRefresh={onRefresh}
      refreshing={refreshing}
      right={
        <span className="sans text-xs uppercase tracking-wide px-2 py-0.5 rounded-sm bg-rule/40 text-muted">
          {report.phase_label}
        </span>
      }
    >
      <Headline report={report} />
      <Chart report={report} />
      {report.washout?.applicable && <Washout report={report} />}
      {data?.corroboration && <CorroborationCard c={data.corroboration} />}
      {report.notes?.length > 0 && (
        <ul className="mt-3 text-xs text-muted list-disc pl-4 space-y-0.5">
          {report.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      {data?.computed_at && (
        <div className="mt-2 sans text-[11px] text-muted">
          As of {report.as_of} · computed {new Date(data.computed_at).toLocaleString()}
        </div>
      )}
    </Shell>
  );
}

function Shell({
  children,
  onRefresh,
  refreshing,
  right,
}: {
  children: React.ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
  right?: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-center gap-3 mb-3">
        <h2 className="text-lg">Outcome vs. thesis</h2>
        {right}
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="ml-auto sans text-xs underline text-muted hover:text-ink disabled:opacity-50"
          >
            {refreshing ? "Refreshing…" : "↻ Refresh"}
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

function Headline({ report }: { report: PerfReport }) {
  const h = report.headline;
  if (!h) return null;
  const subjectName =
    h.subject_role === "spinco" ? report.legs.spinco?.name : report.legs.parent?.name;
  return (
    <div className="border border-rule rounded-sm p-4 mb-4">
      <div className="sans text-xs uppercase tracking-wide text-muted mb-1">
        {h.subject} {subjectName ? `· ${subjectName}` : ""} — {h.window.toLowerCase()}
      </div>
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <div>
          <span className="text-3xl mono" style={{ color: signColor(h.return) }}>
            {pct(h.return)}
          </span>
          <span className="sans text-xs text-muted ml-1">total return</span>
        </div>
        <Stat label="vs S&P 500" value={pp(h.market_alpha)} color={signColor(h.market_alpha)} />
        <Stat
          label={`vs ${report.benchmarks.sector.ticker}`}
          value={pp(h.sector_alpha)}
          color={signColor(h.sector_alpha)}
        />
      </div>
      <div className="sans text-[11px] text-muted mt-2">
        Sector benchmark: {report.benchmarks.sector.label}. Positive alpha = the
        spin-specific edge beat the benchmark.
      </div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <span className="text-xl mono" style={{ color }}>
        {value}
      </span>
      <span className="sans text-xs text-muted ml-1">{label}</span>
    </div>
  );
}

function Chart({ report }: { report: PerfReport }) {
  const series: ChartSeries[] = [];
  const { parent, spinco } = report.legs;
  const mkt = report.benchmarks.market.ticker;
  const sec = report.benchmarks.sector.ticker;

  if (parent?.series?.length) {
    series.push({ name: `${parent.ticker} (parent)`, color: "#a0522d", points: parent.series });
  }
  if (spinco?.series?.length) {
    series.push({ name: `${spinco.ticker} (spinco)`, color: "#0e0f12", points: spinco.series });
  }
  if (report.benchmark_series[mkt]?.length) {
    series.push({ name: mkt, color: "#9a958a", dash: "4 3", points: report.benchmark_series[mkt] });
  }
  if (sec !== mkt && report.benchmark_series[sec]?.length) {
    series.push({ name: sec, color: "#b6a98c", dash: "1 3", points: report.benchmark_series[sec] });
  }

  const markers = [
    report.anchors.filed && { date: report.anchors.filed, label: "Filed" },
    report.anchors.distribution && { date: report.anchors.distribution, label: "Distribution" },
  ].filter(Boolean) as { date: string; label: string }[];

  return <PerfChart series={series} markers={markers} />;
}

function Washout({ report }: { report: PerfReport }) {
  const w = report.washout!;
  return (
    <div className="border border-rule rounded-sm p-3 mb-4 text-sm">
      <div className="sans text-xs uppercase tracking-wide text-muted mb-1">
        Forced-selling washout · first {w.window_days} days
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>
          Trough{" "}
          <span className="mono" style={{ color: signColor(w.trough_return) }}>
            {pct(w.trough_return)}
          </span>{" "}
          <span className="text-muted">({w.trough_date})</span>
        </span>
        <span>
          Recovery from trough{" "}
          <span className="mono" style={{ color: signColor(w.recovery_from_trough) }}>
            {pct(w.recovery_from_trough)}
          </span>
        </span>
        <span className="text-muted">
          {w.still_below_first ? "Still below first close" : "Recovered above first close"}
        </span>
      </div>
    </div>
  );
}

function CorroborationCard({ c }: { c: Corroboration }) {
  const v = VERDICT_STYLE[c.verdict] ?? VERDICT_STYLE.too_early;
  return (
    <div className="border border-rule rounded-sm p-4 mt-2">
      <div className="flex items-center gap-2 mb-2">
        <span
          className="sans text-xs font-medium px-2 py-0.5 rounded-sm"
          style={{ background: v.bg, color: v.fg }}
        >
          {v.label}
        </span>
        <span className="sans text-xs text-muted">
          {Math.round((c.confidence ?? 0) * 100)}% confidence
        </span>
        <span className="sans text-[11px] text-muted ml-auto">LLM post-mortem</span>
      </div>
      <p className="text-sm leading-relaxed">{c.summary}</p>

      {c.drivers?.length > 0 && (
        <div className="mt-3">
          <div className="sans text-xs uppercase tracking-wide text-muted mb-1">
            What actually moved it
          </div>
          <ul className="text-sm list-disc pl-4 space-y-0.5">
            {c.drivers.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      )}

      {c.axis_assessment && Object.keys(c.axis_assessment).length > 0 && (
        <div className="mt-3">
          <div className="sans text-xs uppercase tracking-wide text-muted mb-1">
            Did each axis hold up?
          </div>
          <ul className="text-sm space-y-1">
            {Object.entries(c.axis_assessment).map(([k, a]) => {
              const s = AXIS_STATUS[a.status] ?? AXIS_STATUS.not_yet_testable;
              return (
                <li key={k} className="flex gap-2">
                  <span className="mono" style={{ color: s.color }}>
                    {s.mark}
                  </span>
                  <span>
                    <strong className="font-medium">{prettyAxis(k)}:</strong>{" "}
                    <span className="text-muted">{a.note}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {c.what_to_watch?.length > 0 && (
        <div className="mt-3">
          <div className="sans text-xs uppercase tracking-wide text-muted mb-1">
            What to watch next
          </div>
          <ul className="text-sm list-disc pl-4 space-y-0.5 text-muted">
            {c.what_to_watch.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
