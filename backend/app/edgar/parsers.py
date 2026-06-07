"""Light parsing helpers for EDGAR filings.

We do not try to perfectly extract every field. The LLM stage handles the messy
narrative work; this module's job is to turn a filing's HTML into clean text
that can be passed to Claude with a stable structure.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")


def html_to_text(html: str, max_chars: int = 200_000) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # EDGAR filings often have a giant front matter (XBRL hidden divs etc). Drop
    # anything that looks like an inline XBRL hidden block.
    for tag in soup.find_all(attrs={"style": re.compile(r"display:\s*none", re.I)}):
        tag.decompose()

    text = soup.get_text("\n")
    text = _WS.sub(" ", text)
    text = re.sub(r"(?: ?\n ?)+", "\n", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text


def first_n_paragraphs(text: str, n: int = 8) -> str:
    parts = [p for p in text.split("\n") if len(p.strip()) > 40]
    return "\n\n".join(parts[:n])
