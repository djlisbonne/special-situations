"""SEC EDGAR HTTP client.

EDGAR rules:
- Custom User-Agent identifying the operator is mandatory.
- Max 10 requests/second.
- Prefer the JSON endpoints (data.sec.gov) over scraping HTML.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

EDGAR_BASE = "https://www.sec.gov"
EDGAR_DATA = "https://data.sec.gov"

# Forms most relevant to Greenblatt-style events.
SPINOFF_FORMS = ("10-12B", "10-12B/A", "10-12G", "10-12G/A")
COMPLETION_FORMS = ("8-K",)

# Exhibit-99.1 (the information statement) under every naming convention we've
# seen: "ex99-1", "ex991", "exhibit991", "d123dex991", "tm..._ex99-1". The
# `(?:hibit)?` lets "ex" or "exhibit" precede the number, and the trailing
# negative lookahead keeps "ex99-10"/"ex9911" from masquerading as 99.1.
_INFO_STATEMENT_RE = re.compile(r"ex(?:hibit)?[-_]?99[-_.]?1(?!\d)", re.IGNORECASE)
# Any numbered exhibit: capture the leading exhibit number so we can tell a
# distribution/tax-matters agreement (ex2.x / ex10.x) from a certification.
_EXHIBIT_RE = re.compile(r"ex(?:hibit)?[-_]?(\d{1,2})", re.IGNORECASE)


def _classify_doc(lname: str, size: int) -> str:
    """Classify one filing document by filename + size. See list_filing_documents."""
    if _INFO_STATEMENT_RE.search(lname):
        return "information_statement"
    m = _EXHIBIT_RE.search(lname)
    if m:
        num = m.group(1)
        # The separation/distribution and tax-matters agreements are the large
        # ex2.x / ex10.x exhibits; small numbered exhibits stay generic.
        if num in ("2", "10") and size > 100_000:
            return "separation_agreement"
        return "exhibit"
    return "primary"


@dataclass
class FilingRef:
    accession_number: str
    cik: str
    company_name: str
    form_type: str
    filed_at: datetime
    primary_doc: str  # filename of primary document
    index_url: str
    primary_doc_url: str


class EdgarClient:
    def __init__(self, user_agent: str | None = None):
        settings = get_settings()
        self.user_agent = user_agent or settings.sec_edgar_user_agent
        self._sem = asyncio.Semaphore(8)
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _get(self, url: str, **kw) -> httpx.Response:
        async with self._sem:
            r = await self._client.get(url, **kw)
            await asyncio.sleep(0.12)  # ~8 req/sec ceiling
            r.raise_for_status()
            return r

    async def recent_filings_by_form(
        self, forms: tuple[str, ...], lookback_days: int = 30
    ) -> list[FilingRef]:
        """Use the full-text-search-free 'browse' endpoint to enumerate recent filings by form.

        EDGAR exposes a JSON feed for each form type at /cgi-bin/browse-edgar?... but the
        cleaner path is the daily index. We use the form-search JSON at efts.sec.gov which
        returns recent filings by form type across all companies.
        """
        results: list[FilingRef] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        for form in forms:
            page = 0
            while True:
                params = {
                    "q": "",
                    "dateRange": "custom",
                    "startdt": cutoff.strftime("%Y-%m-%d"),
                    "enddt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "forms": form,
                    "from": page * 100,
                }
                r = await self._get(
                    "https://efts.sec.gov/LATEST/search-index", params=params
                )
                data = r.json()
                hits = data.get("hits", {}).get("hits", [])
                if not hits:
                    break
                for h in hits:
                    src = h.get("_source", {})
                    accession = h.get("_id", "").split(":")[0]
                    if not accession:
                        continue
                    ciks = src.get("ciks") or []
                    if not ciks:
                        continue
                    cik = str(ciks[0]).lstrip("0") or "0"
                    company = (src.get("display_names") or ["Unknown"])[0]
                    filed = src.get("file_date") or src.get("filed")
                    try:
                        filed_dt = datetime.strptime(filed, "%Y-%m-%d").replace(
                            tzinfo=timezone.utc
                        )
                    except Exception:
                        continue
                    primary_doc = src.get("primary_doc") or ""
                    accession_no_dashes = accession.replace("-", "")
                    if not primary_doc:
                        primary_doc = (
                            await self.resolve_primary_doc(cik, accession_no_dashes)
                            or ""
                        )
                    index_url = (
                        f"{EDGAR_BASE}/cgi-bin/browse-edgar?action=getcompany"
                        f"&CIK={cik}&type={form}&dateb=&owner=include&count=40"
                    )
                    primary_doc_url = (
                        f"{EDGAR_BASE}/Archives/edgar/data/{cik}/"
                        f"{accession_no_dashes}/{primary_doc}"
                    )
                    results.append(
                        FilingRef(
                            accession_number=accession,
                            cik=cik,
                            company_name=company,
                            form_type=src.get("form", form),
                            filed_at=filed_dt,
                            primary_doc=primary_doc,
                            index_url=index_url,
                            primary_doc_url=primary_doc_url,
                        )
                    )
                total = data.get("hits", {}).get("total", {}).get("value", 0)
                page += 1
                if page * 100 >= total or page > 50:
                    break
        return results

    async def fetch_document(self, url: str) -> str:
        r = await self._get(url)
        return r.text

    async def filing_index(self, cik: str, accession_no_dashes: str) -> dict:
        """Return the filing's directory listing (index.json) from Archives."""
        url = (
            f"{EDGAR_BASE}/Archives/edgar/data/"
            f"{cik.lstrip('0')}/{accession_no_dashes}/index.json"
        )
        r = await self._get(url)
        return r.json()

    async def list_filing_documents(
        self, cik: str, accession_no_dashes: str
    ) -> list[dict]:
        """Classify the filing's HTML documents.

        Returns a list of `{name, size, kind}` for each .htm/.html file, where
        `kind` is one of:
          - "primary"               cover form (10-12B, 10-12B/A, etc.)
          - "information_statement" prospectus-grade narrative (ex99-1*)
          - "separation_agreement"  large ex2/ex10 typically holding the
                                    distribution and tax matters agreements
          - "exhibit"               other numbered exhibits
        Sorted with the most-substantive docs first so callers can take the
        head of the list when building LLM context.
        """
        try:
            data = await self.filing_index(cik, accession_no_dashes)
        except Exception:
            return []
        items = (data.get("directory") or {}).get("item") or []
        out: list[dict] = []
        for it in items:
            name = it.get("name") or ""
            lname = name.lower()
            if not (lname.endswith(".htm") or lname.endswith(".html")):
                continue
            if "-index" in lname or lname.endswith("-headers.html"):
                continue
            try:
                size = int(it.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            kind = _classify_doc(lname, size)
            out.append({"name": name, "size": size, "kind": kind})

        # Fallback: if no exhibit-99.1 was matched by name but one document
        # dwarfs the rest, it is almost certainly the information statement.
        # Filers name it inconsistently (exhibit991.htm, ex99-1.htm,
        # d123dex991.htm, or occasionally no recognizable token at all), and a
        # cover Form 10 is rarely above ~150 KB — so a 300 KB+ HTML doc is the
        # prospectus-grade narrative we actually need.
        if out and not any(d["kind"] == "information_statement" for d in out):
            biggest = max(out, key=lambda d: d["size"])
            if biggest["size"] > 300_000:
                biggest["kind"] = "information_statement"
        # Order: primary first, then info statement, then separation
        # agreement, then other exhibits. Within each kind, biggest first
        # (size is a decent proxy for "more substance").
        priority = {
            "primary": 0,
            "information_statement": 1,
            "separation_agreement": 2,
            "exhibit": 3,
        }
        out.sort(key=lambda d: (priority.get(d["kind"], 9), -d["size"]))
        return out

    async def resolve_primary_doc(
        self, cik: str, accession_no_dashes: str
    ) -> str | None:
        """Pick the primary cover-form filename for a filing."""
        docs = await self.list_filing_documents(cik, accession_no_dashes)
        for d in docs:
            if d["kind"] == "primary":
                return d["name"]
        # Fall back to the largest non-exhibit document if classification was
        # ambiguous (e.g. unusual filing layouts).
        non_exhibits = [d for d in docs if d["kind"] != "exhibit"]
        if non_exhibits:
            return max(non_exhibits, key=lambda d: d["size"])["name"]
        return None

    async def company_submissions(self, cik: str) -> dict:
        cik_padded = cik.lstrip("0").zfill(10)
        url = f"{EDGAR_DATA}/submissions/CIK{cik_padded}.json"
        r = await self._get(url)
        return r.json()
