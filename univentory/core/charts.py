"""Server-rendered SVG charts (owner: Jesher, S5 Visual Foundation).

No JavaScript and no third-party script, so the Content Security Policy
stays strict and charts render the same for every viewer. Colours come from
the theme's validated categorical slots (``--chart-1`` .. ``--chart-4``) via
CSS classes, so dark and light themes are each selected, not flipped.

Mark specs follow the dataviz method: bars at most 24px thick with a 4px
rounded data end and a square baseline, 2px surface gaps between touching
marks, 2px lines, an area wash at ~10% opacity, >= 8px end markers with a
2px surface ring, hairline recessive grid. Every mark carries a <title>
tooltip, and every chart is paired with a table view by the template tag.
All text is escaped with ``format_html``.
"""
from __future__ import annotations

import math
from decimal import Decimal

from django.utils.html import conditional_escape, format_html, format_html_join
from django.utils.safestring import mark_safe


def _h(template: str, *args):
    """Like format_html, but numbers keep their type so format codes work.

    Text arguments are escaped; numbers are formatted by the template.
    """
    safe = [a if isinstance(a, (int, float)) and not isinstance(a, bool) else conditional_escape(a) for a in args]
    return mark_safe(template.format(*safe))


def _num(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def fmt(value) -> str:
    """Compact, clean number for labels: 1,284 / 12.9K / 4.2M."""
    v = _num(value)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".0M", "M")
    if abs(v) >= 10_000:
        return f"{v / 1000:.1f}K".replace(".0K", "K")
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.1f}"


def _nice_max(value: float) -> float:
    if value <= 0:
        return 4.0
    exp = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        top = step * exp
        if top >= value:
            return top
    return 10 * exp


def _round_top_bar(x, y, w, h, r=4.0):
    """Path for a column with rounded data end and square baseline."""
    if h <= 0:
        return ""
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h:.1f} Z")


def bar_chart(categories, series, *, height=240, width=640, label_max=True, unit=""):
    """Vertical columns. ``series`` is ``[(name, [values per category]), ...]`` (max 4)."""
    pad_l, pad_r, pad_t, pad_b = 40, 8, 18, 28
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    values = [_num(v) for _, vals in series for v in vals]
    top = _nice_max(max(values, default=0))
    n_cat = max(len(categories), 1)
    band = plot_w / n_cat
    n_ser = max(len(series), 1)
    bar_w = min(24.0, (band * 0.62 - 2 * (n_ser - 1)) / n_ser)
    group_w = bar_w * n_ser + 2 * (n_ser - 1)
    parts = []
    for i in range(5):  # hairline grid with clean ticks
        val = top * i / 4
        y = pad_t + plot_h - plot_h * i / 4
        parts.append(_h('<line class="c-grid" x1="{}" x2="{}" y1="{:.1f}" y2="{:.1f}"/>'
                                 '<text class="c-tick" x="{}" y="{:.1f}" text-anchor="end">{}</text>',
                                 pad_l, width - pad_r, y, y, pad_l - 8, y + 4, fmt(val)))
    best = max(values, default=0)
    labelled = False
    for ci, cat in enumerate(categories):
        gx = pad_l + band * ci + (band - group_w) / 2
        for si, (name, vals) in enumerate(series):
            v = _num(vals[ci]) if ci < len(vals) else 0
            h = plot_h * v / top if top else 0
            x = gx + si * (bar_w + 2)
            y = pad_t + plot_h - h
            d = _round_top_bar(x, y, bar_w, h)
            if d:
                parts.append(_h('<path class="c-bar s{}" d="{}"><title>{}: {} {}{}</title></path>',
                                         si + 1, d, cat, name, fmt(v), f" {unit}" if unit else ""))
            if label_max and not labelled and v == best and v > 0:
                parts.append(_h('<text class="c-val" x="{:.1f}" y="{:.1f}" text-anchor="middle">{}</text>',
                                         x + bar_w / 2, y - 6, fmt(v)))
                labelled = True
        parts.append(_h('<text class="c-tick" x="{:.1f}" y="{}" text-anchor="middle">{}</text>',
                                 pad_l + band * ci + band / 2, height - 8, cat))
    parts.append(_h('<line class="c-axis" x1="{}" x2="{}" y1="{}" y2="{}"/>',
                             pad_l, width - pad_r, pad_t + plot_h, pad_t + plot_h))
    return _h('<svg class="chart" viewBox="0 0 {} {}" role="img" preserveAspectRatio="xMidYMid meet">{}</svg>',
                       width, height, mark_safe("".join(parts)))


def area_chart(categories, values, *, height=220, width=640, unit=""):
    """One series over time: 2px line, ~10% wash, ringed end dot, value at the end."""
    pad_l, pad_r, pad_t, pad_b = 40, 40, 18, 28
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    vals = [_num(v) for v in values]
    top = _nice_max(max(vals, default=0))
    n = max(len(vals) - 1, 1)
    pts = [(pad_l + plot_w * i / n, pad_t + plot_h - (plot_h * v / top if top else 0)) for i, v in enumerate(vals)]
    parts = []
    for i in range(5):
        y = pad_t + plot_h - plot_h * i / 4
        parts.append(_h('<line class="c-grid" x1="{}" x2="{}" y1="{:.1f}" y2="{:.1f}"/>'
                                 '<text class="c-tick" x="{}" y="{:.1f}" text-anchor="end">{}</text>',
                                 pad_l, width - pad_r, y, y, pad_l - 8, y + 4, fmt(top * i / 4)))
    if pts:
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area = f"{pts[0][0]:.1f},{pad_t + plot_h:.1f} " + line + f" {pts[-1][0]:.1f},{pad_t + plot_h:.1f}"
        parts.append(_h('<polygon class="c-area s1" points="{}"/>', area))
        parts.append(_h('<polyline class="c-line s1" points="{}"/>', line))
        for (x, y), cat, v in zip(pts, categories, vals):
            parts.append(_h('<circle class="c-hit" cx="{:.1f}" cy="{:.1f}" r="12"><title>{}: {}{}</title></circle>',
                                     x, y, cat, fmt(v), f" {unit}" if unit else ""))
        x, y = pts[-1]
        parts.append(_h('<circle class="c-dot s1" cx="{:.1f}" cy="{:.1f}" r="4.5"/>'
                                 '<text class="c-val" x="{:.1f}" y="{:.1f}">{}</text>', x, y, x + 9, y + 4, fmt(vals[-1])))
    for i, cat in enumerate(categories):
        parts.append(_h('<text class="c-tick" x="{:.1f}" y="{}" text-anchor="middle">{}</text>',
                                 pad_l + plot_w * i / n, height - 8, cat))
    return _h('<svg class="chart" viewBox="0 0 {} {}" role="img">{}</svg>', width, height,
                       mark_safe("".join(parts)))


def sparkline(values, *, width=120, height=36):
    """Stat-tile trend: muted line, current point in the accent."""
    vals = [_num(v) for v in values] or [0]
    top = max(vals) or 1
    n = max(len(vals) - 1, 1)
    pts = [(2 + (width - 8) * i / n, height - 4 - (height - 10) * v / top) for i, v in enumerate(vals)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"2,{height - 2} {line} {pts[-1][0]:.1f},{height - 2}"
    x, y = pts[-1]
    return _h('<svg class="spark" viewBox="0 0 {} {}" aria-hidden="true"><polygon class="c-area s1" points="{}"/>'
                       '<polyline class="c-line c-muted" points="{}"/><circle class="c-dot s1" cx="{:.1f}" cy="{:.1f}" r="3.5"/></svg>',
                       width, height, area, line, x, y)


def donut(segments, *, size=180, thickness=22, center_value="", center_label=""):
    """Parts of one whole. ``segments`` is ``[(name, value), ...]`` (max 4, fixed order)."""
    total = sum(_num(v) for _, v in segments)
    r = (size - thickness) / 2
    c = size / 2
    circ = 2 * math.pi * r
    parts = [_h('<circle class="c-track" cx="{}" cy="{}" r="{:.1f}" stroke-width="{}"/>', c, c, r, thickness)]
    offset = 0.0
    if total > 0:
        for i, (name, v) in enumerate(segments):
            share = _num(v) / total
            if share <= 0:
                continue
            length = max(circ * share - 2, 0.5)  # 2px surface gap between segments
            parts.append(_h(
                '<circle class="c-seg s{}" cx="{}" cy="{}" r="{:.1f}" stroke-width="{}" stroke-dasharray="{:.2f} {:.2f}" '
                'stroke-dashoffset="{:.2f}" transform="rotate(-90 {} {})"><title>{}: {} ({:.0f}%)</title></circle>',
                i + 1, c, c, r, thickness, length, circ - length, -offset, c, c, name, fmt(v), share * 100))
            offset += circ * share
    parts.append(_h('<text class="c-center" x="{}" y="{}" text-anchor="middle">{}</text>'
                             '<text class="c-center-label" x="{}" y="{}" text-anchor="middle">{}</text>',
                             c, c + 4, center_value, c, c + 22, center_label))
    return _h('<svg class="donut" viewBox="0 0 {} {}" role="img">{}</svg>', size, size, mark_safe("".join(parts)))


def legend(names, values=None, unit=""):
    """Legend with a coloured key beside text (text never wears the data colour)."""
    values = values or [None] * len(names)
    return _h('<ul class="c-legend">{}</ul>', format_html_join(
        "", '<li><i class="key s{}"></i><span>{}</span>{}</li>',
        ((i + 1, n, _h('<strong>{}{}</strong>', fmt(v), f" {unit}" if unit else "") if v is not None else "")
         for i, (n, v) in enumerate(zip(names, values)))))


def table(headers, rows):
    """Table view for any chart (accessibility and the light-mode contrast relief)."""
    head = format_html_join("", "<th>{}</th>", ((h,) for h in headers))
    body = format_html_join("", "<tr>{}</tr>", ((format_html_join("", "<td>{}</td>", ((c if isinstance(c, str) else fmt(c),) for c in row)),) for row in rows))
    return _h('<details class="chart-table"><summary>View as table</summary><table class="data"><thead><tr>{}</tr></thead>'
                       '<tbody>{}</tbody></table></details>', head, body)


def monthly_buckets(months=6, today=None):
    """Last N calendar months as (year, month, label), oldest first."""
    from django.utils import timezone

    today = today or timezone.localdate()
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    out.reverse()
    import calendar

    return [(y, m, calendar.month_abbr[m]) for y, m in out]


def count_by_month(queryset, date_field, months=6, sum_field=None):
    """Counts (or sums) per calendar month for the last N months."""
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth

    buckets = monthly_buckets(months)
    start = buckets[0]
    from datetime import date

    qs = queryset.filter(**{f"{date_field}__date__gte": date(start[0], start[1], 1)})
    agg = Sum(sum_field) if sum_field else Count("pk")
    rows = qs.annotate(_m=TruncMonth(date_field)).values("_m").annotate(v=agg).values_list("_m", "v")
    found = {(d.year, d.month): (v or Decimal(0)) for d, v in rows}
    return [label for _, _, label in buckets], [found.get((y, m), 0) for y, m, _ in buckets]
