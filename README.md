# Greenblatt

A personal "Perplexity Finance for special situations" — discovers and evaluates
corporate events in the tradition of Joel Greenblatt's *You Can Be a Stock
Market Genius*.

V1 focuses on **spin-offs** (Form 10-12B / 10-12B-A). The pipeline:

1. **Discover.** Daily EDGAR scan pulls every new Form 10-12B / 10-12B-A.
2. **Extract.** OpenAI reads the information statement and pulls structured
   fields (parent, spinco, distribution ratio, record/distribution dates,
   stated rationale, capital structure, insider ownership, key risks).
3. **Score.** OpenAI scores the situation across five Greenblatt axes
   (insider alignment, forced selling, hidden value, leverage profile,
   information asymmetry) with verbatim citations from the filing.
4. **Browse.** Next.js dashboard ranks events by composite score; the detail
   page renders the thesis, scoring, citations, and live fundamentals.
5. **Interrogate.** A per-event chat lets you ask follow-ups grounded only in
   the filing text, with inline citation markers.
6. **Corroborate.** Once a spin announces or distributes, pull real daily price
   history and close the loop: how did it actually perform vs. the thesis, and
   why? See **Outcome tracking** below.

## Outcome tracking & thesis corroboration

A score is a *prediction*. This layer measures what the market actually did and
asks the LLM whether the thesis explains it — turning the dashboard from a
screener into a back-tested, self-grading tool.

- **Phase-aware.** A spin-off is a sequence (filed → record → distribution →
  seasoning), and value shows up in different legs at different times. Before
  distribution we track the **parent's** anticipation re-rating; after, the
  **spin-co's** survival of the forced-selling washout. The `phase` drives which
  leg is the headline.
- **Alpha, not vanity.** Every return is measured against both the S&P 500 and
  the relevant **sector ETF** (e.g. aerospace → XAR), so you see whether the
  *edge* was real or just beta. Positive alpha = the spin-specific edge showed up.
- **Forced-selling washout.** For trading spin-cos we quantify the first-90-day
  trough and recovery — Greenblatt's classic entry signal.
- **LLM post-mortem.** Realized price stats (computed in Python, never invented
  by the model) are fed back with the original thesis for a structured verdict
  (`validated` / `partially_validated` / `invalidated` / `too_early`), a
  per-axis "did it hold up?" read, and a what-to-watch-next list.
- **Track record.** `/track-record` lines every scored event up against its
  realized alpha and asks the question that matters to an LP: does a higher
  composite score actually predict higher alpha? (Honest calibration, including
  the small-sample / pre-distribution caveat.)
- **Coverage.** Most filings name the parent but not its ticker; a strict,
  exact-match name→ticker resolver (SEC `company_tickers.json`) backfills them so
  the loop can run. It never guesses — a wrong ticker is worse than none.

Endpoints: `GET /events/{id}/performance`, `POST /events/{id}/performance/refresh`,
`GET /performance/track-record`, `POST /performance/refresh-all`,
`POST /performance/resolve-tickers`. The factual report and the LLM verdict are
cached per event in `outcome_snapshots` (12h TTL).

---

## Quick start

```bash
cp .env.example .env
# edit .env: set OPENAI_API_KEY, SEC_EDGAR_USER_AGENT (with your real email),
# and POLYGON_API_KEY (Massive / Polygon.io) for fundamentals snapshots.

docker compose up --build
```

- Backend: http://localhost:8000  (`/docs` for OpenAPI)
- Frontend: http://localhost:3000
- Postgres: localhost:5433 (user `greenblatt`, db `greenblatt`)

### Live reload during development

The compose file deliberately does **not** bind-mount source code into the
containers. On Docker Desktop for Mac (Apple Silicon, VirtioFS) host bind
mounts deadlock on high-fan-out reads — Python's `importlib` walking the
package tree and `npm` reading `package.json` both surface as
`OSError: [Errno 35] Resource deadlock avoided`. Running off the image's
copy avoids the issue entirely.

For hot-reload, run `docker compose watch` in a second terminal (or
`docker compose up --watch` on Compose 2.22+):

```bash
docker compose watch
```

This rsyncs source changes into the running containers; `uvicorn --reload`
and `next dev` pick them up. Changes to `pyproject.toml` or `package.json`
trigger an image rebuild automatically.

Trigger a first scan from http://localhost:3000/scan, or:

```bash
curl -XPOST 'http://localhost:8000/scan?lookback_days=60'
```

The scheduler then re-runs nightly at 21:15 UTC (~5:15pm ET).

---

## Architecture

```
backend/                  FastAPI + SQLAlchemy + APScheduler
  app/
    config.py             Pydantic settings (env-driven)
    db/models.py          Filings, Events, ChatMessages, ScanRuns
    edgar/
      client.py           EDGAR HTTP client (User-Agent, rate-limited)
      parsers.py          HTML → clean text
    events/
      detector.py         Form-type + LLM classifier
      spinoff.py          Two-pass extraction + Greenblatt scoring
      pipeline.py         End-to-end: fetch → persist → analyze
    fundamentals/massive.py  Wraps the `massive` Python SDK (RESTClient) —
                             ticker_details + snapshot_ticker + list_stock_financials,
                             then computes EV/EBITDA, earnings yield, net debt / EBITDA,
                             FCF yield, ROIC from the typed dataclasses
    fundamentals/prices.py   Cached daily price bars via list_aggs + pure return /
                             alpha / drawdown helpers (the back-test raw material)
    fundamentals/tickers.py  Strict name→ticker resolver (SEC company_tickers.json)
    performance/
      benchmarks.py       Company name/SIC → sector ETF (else SPY)
      tracker.py          Event + prices → phase-aware outcome report + washout
      corroborate.py      LLM post-mortem: thesis vs. realized price action
    llm/
      client.py           OpenAI SDK wrapper (Structured Outputs helper)
      schemas.py          Strict JSON schemas for LLM responses
      prompts.py          Greenblatt-grounded prompts
    api/
      events.py           GET /events, GET /events/{id}
      scan.py             POST /scan
      chat.py             POST /events/{id}/chat
      performance.py      Outcome tracking + track-record + ticker backfill
    scheduler/jobs.py     APScheduler daily job

frontend/                 Next.js 14 (app router) + Tailwind
  app/
    page.tsx              Dashboard (ranked event list)
    events/[id]/page.tsx  Event detail + Outcome panel + Chat panel
    track-record/page.tsx Calibration: score vs. realized alpha across events
    scan/page.tsx         Manual scan trigger
  components/
    EventTable.tsx        Ranked rows
    PerformancePanel.tsx  Outcome-vs-thesis: headline alpha, chart, washout, verdict
    PerfChart.tsx         Rebased growth-of-100 multi-line SVG chart
    AxisCard.tsx          Per-axis score with citations
    Chat.tsx              Per-filing Q&A
    ScoreBar.tsx          Score widgets
  lib/api.ts              Typed client
```

## The Greenblatt scoring axes

Each filing is scored 0–10 on five axes, with the LLM required to attach
verbatim quotes from the filing as evidence:

| Axis                  | High score means                                                      |
|-----------------------|-----------------------------------------------------------------------|
| insider_alignment     | Post-spin management has equity skin-in-the-game                      |
| forced_selling        | Index/institutional holders will dump for non-economic reasons        |
| hidden_value          | Rationale is "unlocking hidden value," not defensive                  |
| leverage_profile      | Capital structure produces asymmetric upside or sensible stub equity  |
| information_asymmetry | Under-covered enough for a diligent retail investor to have edge      |

Composite weights: 0.25 / 0.25 / 0.20 / 0.15 / 0.15.

## Planned (post-V1)

- Form 4 insider-buying cluster detector
- 13D/G activist-stake tracker
- Post-bankruptcy equity tracker (Plan-of-Reorganization parsing)
- Rights offering parser (S-1 / 424B)
- Stub stock / partial spin detection
- Watchlists + email/push alerts when a setup matches criteria
- Backtest harness: how do high-score events perform vs. SPY?

## Notes

- EDGAR requires a real, identifying User-Agent. Set `SEC_EDGAR_USER_AGENT` in
  your `.env` to something like `"Jane Doe jane@example.com"` — non-compliant
  requests get rate-limited or blocked.
- The LLM stage uses OpenAI. By default `gpt-4o` for the heavy passes
  (extraction, scoring, chat) and `gpt-4o-mini` for cheap classification
  fallbacks. Override with `OPENAI_MODEL_PRIMARY` / `OPENAI_MODEL_FAST` in
  your `.env`. All structured calls use OpenAI Structured Outputs with strict
  JSON schemas, so responses are constrained to the expected application shape.
- Fundamentals come from **Massive (formerly Polygon.io)** via the official
  [`massive` Python SDK](https://github.com/massive-com/client-python). The
  client computes derived ratios (EV/EBITDA, ROIC, net debt / EBITDA, FCF
  yield, earnings yield) from `list_stock_financials` plus `ticker_details`
  and `snapshot_ticker`. Without a key the detail page omits these panels
  gracefully.
- This is a personal research tool. No authentication. Don't expose it
  publicly without adding auth.
