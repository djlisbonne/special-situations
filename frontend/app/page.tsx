import { listEvents } from "@/lib/api";
import { EventTable } from "@/components/EventTable";

export const dynamic = "force-dynamic";

export default async function Page({
  searchParams,
}: {
  searchParams: { min?: string; type?: string };
}) {
  const min = searchParams.min ? Number(searchParams.min) : undefined;
  const events = await listEvents({
    event_type: searchParams.type,
    min_score: Number.isFinite(min) ? min : undefined,
  });

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl">Special-situations dashboard</h1>
        <p className="sans text-muted mt-2 max-w-2xl">
          Corporate events with mispricing potential, ranked by a Greenblatt-style composite.
          Click any row to read the LLM analysis and ask follow-ups grounded in the filing.
        </p>
      </div>

      <div className="flex gap-3 mb-4 sans text-sm">
        <FilterLink href="/" label="All" active={!searchParams.type} />
        <FilterLink href="/?type=spinoff" label="Spin-offs" active={searchParams.type === "spinoff"} />
        <span className="text-muted">|</span>
        <FilterLink href="/?min=7" label="Score ≥ 7" active={searchParams.min === "7"} />
        <FilterLink href="/?min=5" label="Score ≥ 5" active={searchParams.min === "5"} />
      </div>

      <EventTable events={events} />
    </div>
  );
}

function FilterLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <a
      href={href}
      className={
        active
          ? "underline decoration-ink underline-offset-4"
          : "text-muted hover:text-ink"
      }
    >
      {label}
    </a>
  );
}
