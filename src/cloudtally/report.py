"""Text, Markdown and HTML reports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from html import escape

from .costs import Costs

__all__ = ["text_report", "markdown_report", "html_report"]


def _pct(v: float | None) -> str:
    return "new" if v is None else f"{v:+.0f}%"


def text_report(c: Costs, tag_keys: list[str] | None = None, budgets: Mapping[str, float] | None = None) -> str:
    if not len(c):
        return "No cost data."
    f = c.forecast()
    lines = [
        f"Cloud spend {c.start} → {c.end}: {c.money(c.total())}",
        f"  {f.month} month-to-date {c.money(f.month_to_date)} · run rate {c.money(f.daily_run_rate)}/day · projected {c.money(f.projected)}",
        "",
        "By service",
    ]
    total = c.total() or Decimal(1)
    for k, v in c.by("service", 10):
        lines.append(f"  {k[:38]:<38} {c.money(v):>14}  {'█' * max(1, round(24 * v / total))}")
    for key in tag_keys or []:
        tagged, untagged, pct = c.tag_coverage([key])[key]
        lines += ["", f"Tag '{key}': {pct:.1f}% of spend tagged ({c.money(untagged)} untagged)"]
        for k, v in c.by(f"tag:{key}", 8):
            lines.append(f"  {k[:38]:<38} {c.money(v):>14}")
    an = c.anomalies()
    if an:
        lines += ["", "Anomalies"]
        lines += [
            f"  {a.day}  {a.key[:34]:<34} {c.money(a.cost):>12} (expected {c.money(a.expected)}, +{c.money(a.impact)})" for a in an[:10]
        ]
    mv = [m for m in c.movers() if m.delta]
    if mv:
        lines += ["", "Top movers (last 7 days vs previous 7)"]
        lines += [f"  {m.key[:38]:<38} {c.money(m.before):>12} → {c.money(m.after):>12}  {_pct(m.pct)}" for m in mv[:8]]
    for b in c.budgets(budgets or {}):
        mark = "⚠ over" if b.over else "ok"
        lines.append(
            f"\nBudget {b.name}: {c.money(b.spent)} spent, {c.money(b.projected)} projected of {c.money(b.limit)} ({b.pct_projected:.0f}%) {mark}"
        )
    return "\n".join(lines)


def markdown_report(c: Costs, tag_keys: list[str] | None = None, budgets: Mapping[str, float] | None = None) -> str:
    if not len(c):
        return "_No cost data._"
    f = c.forecast()
    out = [
        f"### Cloud spend {c.start} → {c.end}: **{c.money(c.total())}**",
        f"Projected for {f.month}: **{c.money(f.projected)}** (run rate {c.money(f.daily_run_rate)}/day)",
        "",
        "| Service | Cost |",
        "|---|---:|",
    ]
    out += [f"| {k} | {c.money(v)} |" for k, v in c.by("service", 10)]
    an = c.anomalies()
    if an:
        out += ["", "**Anomalies**", "", "| Day | Where | Cost | Expected |", "|---|---|---:|---:|"]
        out += [f"| {a.day} | {a.key} | {c.money(a.cost)} | {c.money(a.expected)} |" for a in an[:10]]
    for key in tag_keys or []:
        out.append(f"\nTag `{key}` coverage: **{c.tag_coverage([key])[key][2]:.1f}%**")
    for b in c.budgets(budgets or {}):
        out.append(f"\n{'⚠️' if b.over else '✅'} Budget `{b.name}`: {c.money(b.projected)} projected of {c.money(b.limit)}")
    return "\n".join(out)


_CSS = """
:root{--ink:#0c2a3e;--soft:#5b7385;--line:#d8e4ec;--paper:#fff;--bg:#eef4f8;--brand:#0284c7;--hot:#dc2626;--cool:#059669}
@media (prefers-color-scheme:dark){:root{--ink:#e2eef6;--soft:#93aebf;--line:#24384a;--paper:#112230;--bg:#0a1720;--brand:#38bdf8;--hot:#f87171;--cool:#34d399}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 20px 48px}h1{font-size:27px;margin:0;letter-spacing:-.02em}h2{font-size:16px;margin:0 0 12px}
.sub{color:var(--soft);font-size:14px}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:18px 0}
.kpi,.card{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:16px 18px}.kpi span{display:block;color:var(--soft);font-size:13px}
.kpi strong{font-size:24px;font-variant-numeric:tabular-nums}.card{margin-bottom:14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.bar{display:grid;grid-template-columns:minmax(110px,1fr) 2fr 104px;gap:10px;align-items:center;font-size:14px;margin:7px 0}
.bar span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.track{height:9px;background:var(--bg);border-radius:6px;overflow:hidden}
.track i{display:block;height:100%;background:var(--brand);border-radius:6px}.bar b{text-align:right;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:14px}th{color:var(--soft);font-weight:500;text-align:left;padding:6px;border-bottom:1px solid var(--line)}
td{padding:7px 6px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}tr:last-child td{border:0}.n{text-align:right}
.hot{color:var(--hot)}.cool{color:var(--cool)}svg{width:100%;height:auto;display:block}.scroll{overflow-x:auto}
"""


def _bars(c: Costs, rows: list[tuple[str, Decimal]]) -> str:
    top = max((v for _, v in rows), default=Decimal(1)) or Decimal(1)
    return "".join(
        f"<div class='bar'><span title='{escape(k)}'>{escape(k)}</span><div class='track'><i style='width:{max(0.0, float(v / top)) * 100:.1f}%'></i></div><b>{c.money(v)}</b></div>"
        for k, v in rows
    )


def _chart(c: Costs, anomaly_days: set[date]) -> str:
    daily = c.daily()
    days = sorted(daily)
    vals = [float(daily[d]) for d in days]
    if not vals:
        return ""
    w, h, pad = 960, 220, 8
    hi = max(vals) or 1
    xs = [pad + i * (w - 2 * pad) / max(1, len(vals) - 1) for i in range(len(vals))]
    ys = [h - pad - v / hi * (h - 2 * pad) for v in vals]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{h - pad} {line} {xs[-1]:.1f},{h - pad}"
    dots = "".join(
        f"<circle cx='{x:.1f}' cy='{y:.1f}' r='5' fill='var(--hot)'><title>{d}: {c.money(daily[d])}</title></circle>"
        for d, x, y in zip(days, xs, ys)
        if d in anomaly_days
    )
    return (
        f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='Daily spend'><polygon points='{area}' fill='var(--brand)' opacity='.15'/>"
        f"<polyline points='{line}' fill='none' stroke='var(--brand)' stroke-width='2.5'/>{dots}</svg>"
        f"<p class='sub'>{days[0]} → {days[-1]} · peak {c.money(Decimal(str(hi)))}/day"
        + (" · <span class='hot'>●</span> anomaly" if dots else "")
        + "</p>"
    )


def html_report(c: Costs, tag_keys: list[str] | None = None, budgets: Mapping[str, float] | None = None, title: str = "Cloud spend") -> str:
    if not len(c):
        return f"<!doctype html><meta charset='utf-8'><title>{title}</title><p>No cost data.</p>"
    f = c.forecast()
    an = c.anomalies()
    kpis = [
        ("Total in period", c.money(c.total())),
        (f"Projected {f.month}", c.money(f.projected)),
        ("Run rate", f"{c.money(f.daily_run_rate)}/day"),
    ]
    for key in tag_keys or []:
        kpis.append((f"Tagged with '{key}'", f"{c.tag_coverage([key])[key][2]:.1f}%"))
    sections = [f"<div class='card'><h2>Daily spend</h2>{_chart(c, {a.day for a in an})}</div>", "<div class='grid'>"]
    sections.append(f"<div class='card'><h2>By service</h2>{_bars(c, c.by('service', 10))}</div>")
    sections.append(f"<div class='card'><h2>By account</h2>{_bars(c, c.by('account', 10))}</div>")
    for key in tag_keys or []:
        sections.append(f"<div class='card'><h2>By {escape(key)}</h2>{_bars(c, c.by(f'tag:{key}', 10))}</div>")
        sections.append(f"<div class='card'><h2>Largest spend without '{escape(key)}'</h2>{_bars(c, c.untagged(key, 'resource', 8))}</div>")
    sections.append("</div>")
    if an:
        rows = "".join(
            f"<tr><td>{a.day}</td><td>{escape(a.key)}</td><td class='n hot'>{c.money(a.cost)}</td><td class='n'>{c.money(a.expected)}</td><td class='n'>+{c.money(a.impact)}</td></tr>"
            for a in an[:12]
        )
        sections.append(
            f"<div class='card'><h2>Anomalies</h2><div class='scroll'><table><tr><th>Day</th><th>Where</th><th class='n'>Cost</th><th class='n'>Expected</th><th class='n'>Impact</th></tr>{rows}</table></div></div>"
        )
    mv = [m for m in c.movers() if m.delta][:10]
    if mv:
        rows = "".join(
            f"<tr><td>{escape(m.key)}</td><td class='n'>{c.money(m.before)}</td><td class='n'>{c.money(m.after)}</td><td class='n {'hot' if m.delta > 0 else 'cool'}'>{_pct(m.pct)}</td></tr>"
            for m in mv
        )
        sections.append(
            f"<div class='card'><h2>Top movers — last 7 days vs previous 7</h2><div class='scroll'><table><tr><th>Service</th><th class='n'>Before</th><th class='n'>After</th><th class='n'>Change</th></tr>{rows}</table></div></div>"
        )
    bs = c.budgets(budgets or {})
    if bs:
        rows = "".join(
            f"<tr><td>{escape(b.name)}</td><td class='n'>{c.money(b.spent)}</td><td class='n'>{c.money(b.projected)}</td><td class='n'>{c.money(b.limit)}</td><td class='n {'hot' if b.over else 'cool'}'>{b.pct_projected:.0f}%</td></tr>"
            for b in bs
        )
        sections.append(
            f"<div class='card'><h2>Budgets ({f.month})</h2><table><tr><th>Budget</th><th class='n'>Spent</th><th class='n'>Projected</th><th class='n'>Limit</th><th class='n'>Projected use</th></tr>{rows}</table></div>"
        )
    kp = "".join(f"<div class='kpi'><span>{escape(a)}</span><strong>{escape(b)}</strong></div>" for a, b in kpis)
    from . import __version__

    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body><main><h1>{escape(title)}</h1>"
        f"<p class='sub'>{c.start} → {c.end} · {len(c):,} line items · currency {escape(c.currency or '?')}</p>"
        f"<div class='kpis'>{kp}</div>{''.join(sections)}<p class='sub'>Generated by cloudtally {__version__}.</p></main></body></html>"
    )
