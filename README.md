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
    llm/
      client.py           OpenAI SDK wrapper (json_chat helper, JSON-mode)
      prompts.py          Greenblatt-grounded prompts
    api/
      events.py           GET /events, GET /events/{id}
      scan.py             POST /scan
      chat.py             POST /events/{id}/chat
    scheduler/jobs.py     APScheduler daily job

frontend/                 Next.js 14 (app router) + Tailwind
  app/
    page.tsx              Dashboard (ranked event list)
    events/[id]/page.tsx  Event detail + Chat panel
    scan/page.tsx         Manual scan trigger
  components/
    EventTable.tsx        Ranked rows
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
  your `.env`. All structured calls use OpenAI JSON mode
  (`response_format={"type": "json_object"}`) so the model output is
  guaranteed to parse.
- Fundamentals come from **Massive (formerly Polygon.io)** via the official
  [`massive` Python SDK](https://github.com/massive-com/client-python). The
  client computes derived ratios (EV/EBITDA, ROIC, net debt / EBITDA, FCF
  yield, earnings yield) from `list_stock_financials` plus `ticker_details`
  and `snapshot_ticker`. Without a key the detail page omits these panels
  gracefully.
- This is a personal research tool. No authentication. Don't expose it
  publicly without adding auth.
