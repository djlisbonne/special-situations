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

// --- Outcome tracking -------------------------------------------------------

export type PerfPoint = { date: string; close: number };

export type PerfWindow = {
  label: string;
  from: string;
  to: string;
  return: number | null;
  market_return: number | null;
  sector_return: number | null;
  market_alpha: number | null;
  sector_alpha: number | null;
};

export type PerfLeg = {
  ticker: string;
  name: string | null;
  trading: boolean;
  first_close: number | null;
  first_date: string | null;
  last_close: number | null;
  last_date: string | null;
  series: PerfPoint[];
  windows: Record<string, PerfWindow>;
};

export type PerfHeadline = {
  subject: string;
  subject_role: "parent" | "spinco" | null;
  window: string;
  return: number | null;
  market_alpha: number | null;
  sector_alpha: number | null;
};

export type Washout = {
  applicable: boolean;
  first_close: number;
  first_date: string;
  trough_close: number;
  trough_date: string;
  trough_return: number;
  latest_close: number;
  recovery_from_trough: number | null;
  window_days: number;
  still_below_first: boolean;
};

export type PerfReport = {
  event_id: number;
  as_of: string;
  phase: "pre_distribution" | "seasoning" | "seasoned" | "no_data";
  phase_label: string;
  days_since_distribution: number | null;
  anchors: { filed: string | null; record: string | null; distribution: string | null };
  benchmarks: {
    market: { ticker: string; label: string };
    sector: { ticker: string; label: string };
  };
  benchmark_series: Record<string, PerfPoint[]>;
  legs: { parent: PerfLeg | null; spinco: PerfLeg | null };
  washout: Washout | null;
  headline: PerfHeadline | null;
  notes: string[];
  has_data: boolean;
};

export type AxisOutcome = {
  status: "confirmed" | "contradicted" | "not_yet_testable";
  note: string;
};

export type Corroboration = {
  verdict: "validated" | "partially_validated" | "invalidated" | "too_early";
  confidence: number;
  summary: string;
  drivers: string[];
  axis_assessment: Record<string, AxisOutcome>;
  what_to_watch: string[];
};

export type PerformanceResponse = {
  event_id: number;
  computed_at: string | null;
  report: PerfReport | null;
  corroboration: Corroboration | null;
};

export const getPerformance = (id: number, refresh = false) =>
  fetchJSON<PerformanceResponse>(
    `/events/${id}/performance${refresh ? "?refresh=true" : ""}`
  );

export const refreshPerformance = (id: number) =>
  fetchJSON<PerformanceResponse>(`/events/${id}/performance/refresh`, {
    method: "POST",
  });

export type TrackRecordRow = {
  event_id: number;
  parent_name: string | null;
  parent_ticker: string | null;
  spinco_name: string | null;
  spinco_ticker: string | null;
  composite_score: number | null;
  phase: string | null;
  phase_label: string | null;
  as_of: string | null;
  headline: PerfHeadline | null;
  verdict: string | null;
  computed_at: string | null;
};

export type Calibration = {
  n: number;
  avg_market_alpha?: number;
  positive_alpha_rate?: number;
  bottom_half_avg_alpha?: number;
  top_half_avg_alpha?: number;
  spread?: number;
};

export type TrackRecord = {
  items: TrackRecordRow[];
  calibration: Calibration;
  count: number;
};

export const getTrackRecord = () => fetchJSON<TrackRecord>(`/performance/track-record`);

export const refreshAllPerformance = (runLlm = true) =>
  fetchJSON<{ events_processed: number; events_with_price_data: number }>(
    `/performance/refresh-all?run_llm=${runLlm}`,
    { method: "POST" }
  );
