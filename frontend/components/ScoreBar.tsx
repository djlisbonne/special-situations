import clsx from "clsx";

export function ScoreBar({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-muted sans text-xs">n/a</span>;
  }
  const pct = Math.max(0, Math.min(10, value)) * 10;
  const color =
    value >= 7 ? "bg-emerald-700" : value >= 5 ? "bg-amber-700" : "bg-rose-700";
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-2 bg-rule rounded-sm overflow-hidden">
        <div className={clsx("h-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="mono text-xs tabular-nums">{value.toFixed(1)}</span>
    </div>
  );
}

export function ScoreBadge({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-muted sans text-xs">—</span>;
  }
  const tone =
    value >= 7 ? "border-emerald-700 text-emerald-900 bg-emerald-50" :
    value >= 5 ? "border-amber-700 text-amber-900 bg-amber-50" :
                 "border-rose-700 text-rose-900 bg-rose-50";
  return (
    <span className={clsx("mono text-xs tabular-nums px-2 py-0.5 border rounded-sm", tone)}>
      {value.toFixed(1)}
    </span>
  );
}
