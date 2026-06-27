"""Regression tests for filing-document classification.

The original `ex99[-_]?1` regex matched Middleby's `dex991.htm` but silently
failed on Honeywell's `exhibit991-...htm` (after "ex" comes "hibit", not "99"),
so a 3.7 MB information statement was mislabeled `primary` and truncated to the
60k primary cap — which is why the financials read as "not disclosed". These
pin the broadened matcher and the largest-document fallback.
"""

from __future__ import annotations

from app.edgar.client import _classify_doc


def test_honeywell_exhibit991_is_information_statement():
    assert _classify_doc("exhibit991-10x12ba2.htm", 3_723_934) == "information_statement"


def test_middleby_dex991_is_information_statement():
    assert _classify_doc("d14360dex991.htm", 2_003_984) == "information_statement"


def test_sp_ex99_dash_1_is_information_statement():
    assert _classify_doc("tm2528763d9_ex99-1.htm", 4_267_241) == "information_statement"


def test_ex99_2_is_not_information_statement():
    # Consent / minor exhibit, not the info statement.
    assert _classify_doc("tm2528763d10_ex99-2.htm", 6_253) == "exhibit"


def test_ex99_10_does_not_masquerade_as_99_1():
    assert _classify_doc("something_ex99-10.htm", 500_000) != "information_statement"


def test_cover_form_is_primary():
    assert _classify_doc("honeywellaerospace-10x12ba2.htm", 80_058) == "primary"
    assert _classify_doc("d14360d1012ba.htm", 35_057) == "primary"


def test_large_ex2_and_ex10_are_separation_agreements():
    assert _classify_doc("tm2528763d10_ex2-1.htm", 369_501) == "separation_agreement"
    assert _classify_doc("tm2528763d10_ex10-14.htm", 407_396) == "separation_agreement"


def test_small_ex2_stays_exhibit():
    assert _classify_doc("foo_ex2-1.htm", 5_000) == "exhibit"


def test_certifications_are_exhibits_not_primary():
    # exhibit31/32 are SOX certs; must not be mistaken for the cover form.
    assert _classify_doc("exhibit32-10x12ba2.htm", 196_672) == "exhibit"
    assert _classify_doc("exhibit31-10x12ba2.htm", 41_701) == "exhibit"


def test_subsidiaries_ex21_is_exhibit():
    assert _classify_doc("tm2528763d10_ex21-1.htm", 11_456) == "exhibit"
