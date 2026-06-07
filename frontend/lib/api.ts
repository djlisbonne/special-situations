// Two base URLs:
// - PUBLIC: what the browser uses. Must be reachable from the user's machine.
//   In Docker dev, the backend is published to localhost:8000.
// - INTERNAL: what Server Components and Route Handlers use. They run inside
//   the frontend container, where `localhost` is the container itself —
//   the backend is reachable at http://backend:8000 on the compose network.
const PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const INTERNAL_API_BASE =
  process.env.API_BASE_INTERNAL || PUBLIC_API_BASE;

function apiBase(): string {
  return typeof window === "undefined" ? INTERNAL_API_BASE : PUBLIC_API_BASE;
}

/** Browser-safe base — use this for things like EventSource URLs. */
export function publicApiBase(): string {
  return PUBLIC_API_BASE;
}

/** Kept for any consumer that imports it directly; browser-safe. */
export const API_BASE = PUBLIC_API_BASE;

export type EventSummary = {
  id: number;
  event_type: string;
  status: string;
  parent_name: string | null;
  parent_ticker: string | null;
  spinco_name: string | null;
  spinco_ticker: string | null;
  distribution_ratio: string | null;
  record_date: string | null;
  distribution_date: string | null;
  headline: string | null;
  composite_score: number | null;
  filed_at: string;
  accession_number: string;
};

export type AxisScore = {
  score: number | null;
  rationale: string | null;
  citations: string[];
  positive_evidence: string[];
  negative_evidence: string[];
  confidence: number | null;
};

export type FilingOut = {
  id: number;
  accession_number: string;
  cik: string;
  company_name: string;
  form_type: string;
  filed_at: string;
  primary_doc_url: string;
  index_url: string;
};

export type EventDetail = {
  id: number;
  event_type: string;
  status: string;
  parent_cik: string | null;
  parent_name: string | null;
  parent_ticker: string | null;
  spinco_name: string | null;
  spinco_ticker: string | null;
  distribution_ratio: string | null;
  record_date: string | null;
  distribution_date: string | null;
  headline: string | null;
  thesis: string | null;
  rationale_stated: string | null;
  composite_score: number | null;
  scores: Record<string, AxisScore>;
  flags: Record<string, unknown>;
  filing: FilingOut;
  parent_snapshot: Record<string, unknown> | null;
  spinco_snapshot: Record<string, unknown> | null;
};

export type ChatMessageOut = {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations: { id: string; quote: string }[];
  answered_from_filing: boolean | null;
  limitations: string[];
  created_at: string;
};

export async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${apiBase()}${path}`;
  let r: Response;
  try {
    r = await fetch(url, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch (e) {
    // fetch() throws TypeError on network failures (DNS, refused, etc.)
    // Re-throw with the URL so the cause is obvious in logs.
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`fetch ${url} failed: ${msg}`);
  }
  if (!r.ok) throw new Error(`${r.status} ${url} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const listEvents = (params: { event_type?: string; min_score?: number } = {}) => {
  const q = new URLSearchParams();
  if (params.event_type) q.set("event_type", params.event_type);
  if (params.min_score !== undefined) q.set("min_score", String(params.min_score));
  const qs = q.toString() ? `?${q.toString()}` : "";
  return fetchJSON<EventSummary[]>(`/events${qs}`);
};

export const getEvent = (id: number) => fetchJSON<EventDetail>(`/events/${id}`);

export type ScanStart = {
  scan_run_id: number;
  lookback_days: number;
  status: string;
};

export type ScanStatus = {
  scan_run_id: number;
  started_at: string;
  finished_at: string | null;
  finished: boolean;
  ok: boolean;
  error: string | null;
  filings_seen: number;
  events_created: number;
};

export const triggerScan = (lookback_days?: number) =>
  fetchJSON<ScanStart>(
    `/scan${lookback_days ? `?lookback_days=${lookback_days}` : ""}`,
    { method: "POST" }
  );

export const getScan = (id: number) => fetchJSON<ScanStatus>(`/scan/${id}`);

export type ActivityEventOut = {
  ts: string;
  level: "info" | "success" | "warn" | "error";
  stage: string;
  message: string;
  details: Record<string, unknown>;
  scan_run_id: number | null;
};

export const recentActivity = (limit = 100) =>
  fetchJSON<ActivityEventOut[]>(`/activity/recent?limit=${limit}`);

export type FilingDocument = {
  name: string;
  size: number;
  kind: "primary" | "information_statement" | "separation_agreement" | "exhibit";
};

export const listEventDocuments = (id: number) =>
  fetchJSON<{ documents: FilingDocument[] }>(`/events/${id}/documents`);

export const listChat = (id: number) =>
  fetchJSON<ChatMessageOut[]>(`/events/${id}/chat`);

export const sendChat = (id: number, question: string) =>
  fetchJSON<{ user_message: ChatMessageOut; assistant_message: ChatMessageOut }>(
    `/events/${id}/chat`,
    { method: "POST", body: JSON.stringify({ question }) }
  );
