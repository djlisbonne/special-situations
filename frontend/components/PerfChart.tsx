"use client";

import { useMemo, useState } from "react";
import { PerfPoint } from "@/lib/api";

export type ChartSeries = {
  name: string;
  color: string;
  dash?: string; // SVG stroke-dasharray
  points: PerfPoint[];
};

type Marker = { date: string; label: string };

// Growth-of-100 chart. Every series is rebased to 100 at its own first point,
// so the lines answer "if I'd put $100 in each on day one, where would I be?" —
// the only honest way to overlay a $230 stock against a $720 index.
export function PerfChart({
  series,
  markers = [],
  height = 240,
}: {
  series: ChartSeries[];
  markers?: Marker[];
  height?: number;
}) {
  const live = series.filter((s) => s.points.length >= 2);
  const [hover, setHover] = useState<number | null>(null);

  const model = useMemo(() => {
    if (!live.length) return null;
    // Shared, sorted date axis across every series.
    const dateSet = new Set<string>();
    live.forEach((s) => s.points.forEach((p) => dateSet.add(p.date)));
    const dates = Array.from(dateSet).sort();
    const xOf = new Map(dates.map((d, i) => [d, i]));

    const rebased = live.map((s) => {
      const base = s.points[0].close || 1;
      return {
        ...s,
        vals: s.points.map((p) => ({
          x: xOf.get(p.date) ?? 0,
          v: (p.close / base) * 100,
          date: p.date,
          close: p.close,
        })),
      };
    });

    let min = Infinity;
    let max = -Infinity;
    rebased.forEach((s) => s.vals.forEach((d) => {
      min = Math.min(min, d.v);
      max = Math.max(max, d.v);
    }));
    // Pad the band a touch.
    const pad = (max - min) * 0.08 || 5;
    min -= pad;
    max += pad;
    return { dates, rebased, min, max, n: dates.length };
  }, [live]);

  if (!model) {
    return (
      <div className="border border-rule rounded-sm p-6 text-center text-muted text-sm">
        Not enough price history to chart yet.
      </div>
    );
  }

  const W = 720;
  const H = height;
  const padL = 8;
  const padR = 8;
  const padT = 10;
  const padB = 22;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const { min, max, n } = model;

  const px = (x: number) => padL + (n <= 1 ? 0 : (x / (n - 1)) * plotW);
  const py = (v: number) => padT + (1 - (v - min) / (max - min || 1)) * plotH;

  const path = (vals: { x: number; v: number }[]) =>
    vals.map((d, i) => `${i === 0 ? "M" : "L"}${px(d.x).toFixed(1)},${py(d.v).toFixed(1)}`).join(" ");

  const baseY = py(100);
  const hoverIdx = hover;

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ overflow: "visible" }}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const rel = ((e.clientX - rect.left) / rect.width) * W;
          const i = Math.round(((rel - padL) / plotW) * (n - 1));
          setHover(Math.max(0, Math.min(n - 1, i)));
        }}
      >
        {/* baseline at 100 */}
        <line x1={padL} x2={W - padR} y1={baseY} y2={baseY} stroke="#dcd7c7" strokeWidth={1} />
        <text x={padL} y={baseY - 3} fontSize={9} fill="#5a5750" className="sans">
          100 (start)
        </text>

        {/* event-date markers */}
        {markers.map((m) => {
          const idx = model.dates.indexOf(m.date);
          if (idx < 0) return null;
          const x = px(idx);
          return (
            <g key={m.label}>
              <line x1={x} x2={x} y1={padT} y2={padT + plotH} stroke="#a0522d" strokeWidth={1} strokeDasharray="2 3" opacity={0.6} />
              <text x={x + 3} y={padT + 9} fontSize={9} fill="#a0522d" className="sans">
                {m.label}
              </text>
            </g>
          );
        })}

        {/* series */}
        {model.rebased.map((s) => (
          <path
            key={s.name}
            d={path(s.vals)}
            fill="none"
            stroke={s.color}
            strokeWidth={s.name.includes("(") ? 1.4 : 2.2}
            strokeDasharray={s.dash}
            strokeLinejoin="round"
          />
        ))}

        {/* hover crosshair + dots */}
        {hoverIdx != null && (
          <line
            x1={px(hoverIdx)}
            x2={px(hoverIdx)}
            y1={padT}
            y2={padT + plotH}
            stroke="#0e0f12"
            strokeWidth={0.5}
            opacity={0.3}
          />
        )}
        {hoverIdx != null &&
          model.rebased.map((s) => {
            const d = s.vals.find((p) => p.x === hoverIdx);
            if (!d) return null;
            return <circle key={s.name} cx={px(d.x)} cy={py(d.v)} r={2.5} fill={s.color} />;
          })}
      </svg>

      {/* legend + hover readout */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 sans text-xs">
        {model.rebased.map((s) => {
          const last = s.vals[s.vals.length - 1];
          const hov = hoverIdx != null ? s.vals.find((p) => p.x === hoverIdx) : undefined;
          const shown = hov ?? last;
          const ret = shown.v - 100;
          return (
            <span key={s.name} className="inline-flex items-center gap-1.5">
              <svg width={16} height={6}>
                <line x1={0} y1={3} x2={16} y2={3} stroke={s.color} strokeWidth={2} strokeDasharray={s.dash} />
              </svg>
              <span className="text-muted">{s.name}</span>
              <span className="mono" style={{ color: ret >= 0 ? "#2e7d32" : "#b3261e" }}>
                {ret >= 0 ? "+" : ""}
                {ret.toFixed(1)}%
              </span>
            </span>
          );
        })}
        {hoverIdx != null && (
          <span className="ml-auto mono text-muted">{model.dates[hoverIdx]}</span>
        )}
      </div>
    </div>
  );
}
