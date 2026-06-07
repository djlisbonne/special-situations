import Link from "next/link";
import { EventSummary } from "@/lib/api";
import { ScoreBadge } from "./ScoreBar";

function fmtDate(s: string | null) {
  if (!s) return "—";
  return new Date(s).toISOString().slice(0, 10);
}

export function EventTable({ events }: { events: EventSummary[] }) {
  if (!events.length) {
    return (
      <div className="border border-rule rounded-sm p-8 text-center text-muted">
        No events yet. Trigger a scan from the <Link className="underline" href="/scan">Scan</Link> page
        or wait for the nightly job.
      </div>
    );
  }
  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="border-b border-rule sans text-xs uppercase tracking-wide text-muted">
          <th className="text-left py-2 pr-3">Score</th>
          <th className="text-left py-2 pr-3">Type</th>
          <th className="text-left py-2 pr-3">Parent → SpinCo</th>
          <th className="text-left py-2 pr-3">Headline</th>
          <th className="text-left py-2 pr-3">Distribution</th>
          <th className="text-left py-2 pr-3">Filed</th>
        </tr>
      </thead>
      <tbody>
        {events.map((e) => (
          <tr key={e.id} className="border-b border-rule/50 hover:bg-rule/20">
            <td className="py-3 pr-3 align-top">
              <ScoreBadge value={e.composite_score} />
            </td>
            <td className="py-3 pr-3 align-top sans text-xs uppercase tracking-wide text-muted">
              {e.event_type}
            </td>
            <td className="py-3 pr-3 align-top">
              <div className="text-sm">
                {e.parent_name ?? "—"}
                {e.parent_ticker ? <span className="mono text-muted"> ({e.parent_ticker})</span> : null}
              </div>
              <div className="text-sm text-muted">
                → {e.spinco_name ?? "—"}
                {e.spinco_ticker ? <span className="mono"> ({e.spinco_ticker})</span> : null}
              </div>
            </td>
            <td className="py-3 pr-3 align-top max-w-sm">
              <Link href={`/events/${e.id}`} className="underline decoration-rule hover:decoration-ink">
                {e.headline ?? "(awaiting analysis)"}
              </Link>
            </td>
            <td className="py-3 pr-3 align-top mono text-xs text-muted">
              {fmtDate(e.distribution_date)}
            </td>
            <td className="py-3 pr-3 align-top mono text-xs text-muted">
              {fmtDate(e.filed_at)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
