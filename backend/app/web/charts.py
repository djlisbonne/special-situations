"""Server-side SVG chart generators for the templated UI.

These are deliberately dependency-free string builders — the same hand-rolled
SVG the old React components produced, now emitted in Python so the page is
fully server-rendered (no chart library, no client build step). Each returns a
self-contained `<svg>` string to drop into a template with `| safe`.
"""

from __future__ import annotations

from html import escape

GAIN = "#2e7d32"
LOSS = "#b3261e"
ACCENT = "#a0522d"
INK = "#0e0f12"
MUTED = "#5a5750"
RULE = "#dcd7c7"


def _fmt_pct(x: float, digits: int = 1) -> str:
    return f"{'+' if x >= 0 else ''}{x * 100:.{digits}f}%"


def growth_of_100(
    series: list[dict],
    markers: list[dict] | None = None,
    height: int = 240,
) -> str:
    """Multi-line growth-of-100 chart.

    `series`: list of {name, color, dash(optional), points:[{date, close}]}.
    `markers`: list of {date, label} drawn as vertical event lines.
    Each series is rebased to 100 at its own first point.
    """
    markers = markers or []
    live = [s for s in series if len(s.get("points") or []) >= 2]
    if not live:
        return (
            '<div class="empty">Not enough price history to chart yet.</div>'
        )

    dates = sorted({p["date"] for s in live for p in s["points"]})
    x_of = {d: i for i, d in enumerate(dates)}
    n = len(dates)

    rebased = []
    vmin, vmax = float("inf"), float("-inf")
    for s in live:
        base = s["points"][0]["close"] or 1
        vals = [
            {"x": x_of[p["date"]], "v": (p["close"] / base) * 100, "date": p["date"]}
            for p in s["points"]
        ]
        for d in vals:
            vmin = min(vmin, d["v"])
            vmax = max(vmax, d["v"])
        rebased.append({**s, "vals": vals})

    pad = (vmax - vmin) * 0.08 or 5
    vmin -= pad
    vmax += pad

    W, H = 720, height
    padL, padR, padT, padB = 8, 8, 12, 22
    plotW, plotH = W - padL - padR, H - padT - padB

    def px(x: float) -> float:
        return padL + (0 if n <= 1 else (x / (n - 1)) * plotW)

    def py(v: float) -> float:
        return padT + (1 - (v - vmin) / ((vmax - vmin) or 1)) * plotH

    parts: list[str] = [
        f'<svg viewBox="0 0 {W} {H}" class="chart" preserveAspectRatio="xMidYMid meet">'
    ]
    base_y = py(100)
    parts.append(
        f'<line x1="{padL}" x2="{W - padR}" y1="{base_y:.1f}" y2="{base_y:.1f}" '
        f'stroke="{RULE}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{padL}" y="{base_y - 3:.1f}" font-size="9" fill="{MUTED}" '
        f'class="sans">100 (start)</text>'
    )

    for m in markers:
        if m["date"] not in x_of:
            continue
        x = px(x_of[m["date"]])
        parts.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{padT}" y2="{padT + plotH}" '
            f'stroke="{ACCENT}" stroke-width="1" stroke-dasharray="2 3" opacity="0.6"/>'
        )
        parts.append(
            f'<text x="{x + 3:.1f}" y="{padT + 9}" font-size="9" fill="{ACCENT}" '
            f'class="sans">{escape(m["label"])}</text>'
        )

    for s in rebased:
        d = " ".join(
            f'{"M" if i == 0 else "L"}{px(p["x"]):.1f},{py(p["v"]):.1f}'
            for i, p in enumerate(s["vals"])
        )
        dash = f' stroke-dasharray="{s["dash"]}"' if s.get("dash") else ""
        width = 1.4 if "(" in s["name"] else 2.2
        parts.append(
            f'<path d="{d}" fill="none" stroke="{s["color"]}" '
            f'stroke-width="{width}"{dash} stroke-linejoin="round"/>'
        )
    parts.append("</svg>")

    # Legend with end-of-series return.
    legend = ['<div class="legend">']
    for s in rebased:
        last = s["vals"][-1]["v"] - 100
        color = GAIN if last >= 0 else LOSS
        dash = f' stroke-dasharray="{s["dash"]}"' if s.get("dash") else ""
        legend.append(
            '<span class="legend-item">'
            f'<svg width="16" height="6"><line x1="0" y1="3" x2="16" y2="3" '
            f'stroke="{s["color"]}" stroke-width="2"{dash}/></svg>'
            f'<span class="muted">{escape(s["name"])}</span>'
            f'<span class="mono" style="color:{color}">{_fmt_pct(last / 100)}</span>'
            "</span>"
        )
    legend.append("</div>")
    return "".join(parts) + "".join(legend)


def score_alpha_scatter(points: list[dict]) -> str:
    """Composite score (x) vs realized market alpha (y).

    `points`: list of {x: score, y: alpha, label: ticker}.
    """
    pts = [p for p in points if isinstance(p.get("x"), (int, float))
           and isinstance(p.get("y"), (int, float))]
    if len(pts) < 2:
        return ""

    W, H = 720, 260
    padL, padR, padT, padB = 44, 12, 12, 30
    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    x_min, x_max = min(0, *xs), max(10, *xs)
    y_min = min(0, *ys) * 1.1
    y_max = (max(0, *ys) * 1.1) or 0.1

    def px(x: float) -> float:
        return padL + ((x - x_min) / ((x_max - x_min) or 1)) * (W - padL - padR)

    def py(y: float) -> float:
        return padT + (1 - (y - y_min) / ((y_max - y_min) or 1)) * (H - padT - padB)

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" preserveAspectRatio="xMidYMid meet">']
    zero_y = py(0)
    parts.append(
        f'<line x1="{padL}" x2="{W - padR}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" stroke="{RULE}"/>'
    )
    parts.append(
        f'<text x="{W - padR}" y="{zero_y - 3:.1f}" font-size="9" fill="{MUTED}" '
        f'text-anchor="end" class="sans">0 alpha</text>'
    )
    for t in (y_min, (y_min + y_max) / 2, y_max):
        parts.append(
            f'<text x="{padL - 6}" y="{py(t) + 3:.1f}" font-size="9" fill="{MUTED}" '
            f'text-anchor="end" class="mono">{_fmt_pct(t, 0)}</text>'
        )
    for s in (0, 2, 4, 6, 8, 10):
        parts.append(
            f'<text x="{px(s):.1f}" y="{H - padB + 14}" font-size="9" fill="{MUTED}" '
            f'text-anchor="middle" class="mono">{s}</text>'
        )
    parts.append(
        f'<text x="{W / 2:.0f}" y="{H - 2}" font-size="9" fill="{MUTED}" '
        f'text-anchor="middle" class="sans">composite score →</text>'
    )
    for p in pts:
        color = GAIN if p["y"] >= 0 else LOSS
        parts.append(
            f'<circle cx="{px(p["x"]):.1f}" cy="{py(p["y"]):.1f}" r="4" '
            f'fill="{color}" opacity="0.75"/>'
        )
        if p.get("label"):
            parts.append(
                f'<text x="{px(p["x"]) + 6:.1f}" y="{py(p["y"]) + 3:.1f}" font-size="8" '
                f'fill="{MUTED}" class="mono">{escape(str(p["label"]))}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)
