import Link from "next/link";
import { getEvent } from "@/lib/api";
import { AxisCard } from "@/components/AxisCard";
import { ScoreBadge } from "@/components/ScoreBar";
import { Chat } from "@/components/Chat";

export const dynamic = "force-dynamic";

function fmtDate(s: string | null) {
  if (!s) return "—";
  return new Date(s).toISOString().slice(0, 10);
}

function fmtNum(n: unknown) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return n.toLocaleString();
}

function fmtRatio(n: unknown) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  return n.toFixed(2) + "×";
}

function fmtPct(n: unknown) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  return (n * 100).toFixed(1) + "%";
}

export default async function EventPage({ params }: { params: { id: string } }) {
  const event = await getEvent(Number(params.id));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
      <div className="lg:col-span-2 space-y-8">
        <div>
          <div className="flex items-center gap-2 sans text-xs uppercase tracking-wide text-muted mb-2">
            <span>{event.event_type}</span>
            <span>•</span>
            <span>{event.status}</span>
            <span className="ml-auto">
              <ScoreBadge value={event.composite_score} />
            </span>
          </div>
          <h1 className="text-3xl leading-tight">{event.headline ?? "Untitled event"}</h1>
          <div className="mt-2 sans text-sm text-muted">
            <strong className="text-ink">{event.parent_name ?? "—"}</strong>
            {event.parent_ticker ? ` (${event.parent_ticker})` : ""}
            {" → "}
            <strong className="text-ink">{event.spinco_name ?? "—"}</strong>
            {event.spinco_ticker ? ` (${event.spinco_ticker})` : ""}
          </div>
        </div>

        <section>
          <h2 className="text-lg mb-2">Thesis</h2>
          <p className="leading-relaxed">{event.thesis ?? "—"}</p>
        </section>

        {event.rationale_stated && (
          <section>
            <h2 className="text-lg mb-2">Stated rationale (from the filing)</h2>
            <p className="leading-relaxed text-muted italic">“{event.rationale_stated}”</p>
          </section>
        )}

        <section>
          <h2 className="text-lg mb-3">Greenblatt scoring</h2>
          <div className="grid sm:grid-cols-2 gap-3">
            {Object.entries(event.scores).map(([k, v]) => (
              <AxisCard key={k} name={k} axis={v} />
            ))}
          </div>
        </section>

        {(event.parent_snapshot || event.spinco_snapshot) && (
          <section>
            <h2 className="text-lg mb-3">Market snapshot</h2>
            <div className="grid sm:grid-cols-2 gap-3">
              {event.parent_snapshot && (
                <Snapshot label="Parent" data={event.parent_snapshot} />
              )}
              {event.spinco_snapshot && (
                <Snapshot label="SpinCo" data={event.spinco_snapshot} />
              )}
            </div>
          </section>
        )}

        <section className="text-sm sans text-muted">
          <h2 className="text-lg text-ink mb-2 font-serif">Filing</h2>
          <div>Form: {event.filing.form_type}</div>
          <div>Accession: <span className="mono">{event.filing.accession_number}</span></div>
          <div>Filed: {fmtDate(event.filing.filed_at)}</div>
          <div className="mt-2 flex gap-4">
            <a className="underline text-ink" href={event.filing.primary_doc_url} target="_blank" rel="noreferrer">
              Primary document ↗
            </a>
            <a className="underline text-ink" href={event.filing.index_url} target="_blank" rel="noreferrer">
              EDGAR index ↗
            </a>
          </div>
        </section>

        <section className="sans text-sm">
          <Link href="/" className="text-muted underline">← Back to dashboard</Link>
        </section>
      </div>

      <aside className="lg:col-span-1">
        <div className="lg:sticky lg:top-6 space-y-4">
          <KeyDates event={event} />
          <Chat eventId={event.id} />
        </div>
      </aside>
    </div>
  );
}

function KeyDates({ event }: { event: Awaited<ReturnType<typeof getEvent>> }) {
  return (
    <div className="border border-rule rounded-sm p-4">
      <div className="sans text-xs uppercase tracking-wide text-muted mb-2">Key dates</div>
      <dl className="text-sm grid grid-cols-2 gap-y-1">
        <dt className="text-muted">Record date</dt>
        <dd className="mono">{fmtDate(event.record_date)}</dd>
        <dt className="text-muted">Distribution</dt>
        <dd className="mono">{fmtDate(event.distribution_date)}</dd>
        <dt className="text-muted">Ratio</dt>
        <dd className="text-xs">{event.distribution_ratio ?? "—"}</dd>
      </dl>
    </div>
  );
}

function Snapshot({ label, data }: { label: string; data: Record<string, unknown> }) {
  return (
    <div className="border border-rule rounded-sm p-4">
      <div className="sans text-xs uppercase tracking-wide text-muted mb-2">
        {label}{" "}
        <span className="mono text-ink">
          {typeof data.ticker === "string" ? data.ticker : ""}
        </span>
      </div>
      <dl className="text-sm grid grid-cols-2 gap-y-1">
        <dt className="text-muted">Market cap</dt>
        <dd className="mono">{fmtNum(data.market_cap)}</dd>
        <dt className="text-muted">EV / EBITDA</dt>
        <dd className="mono">{fmtRatio(data.ev_to_ebitda)}</dd>
        <dt className="text-muted">Earnings yield</dt>
        <dd className="mono">{fmtPct(data.earnings_yield)}</dd>
        <dt className="text-muted">ROIC</dt>
        <dd className="mono">{fmtPct(data.roic)}</dd>
        <dt className="text-muted">Net debt / EBITDA</dt>
        <dd className="mono">{fmtRatio(data.net_debt_to_ebitda)}</dd>
        <dt className="text-muted">FCF yield</dt>
        <dd className="mono">{fmtPct(data.fcf_yield)}</dd>
      </dl>
    </div>
  );
}
