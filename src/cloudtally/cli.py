"""Command line: ``cloudtally focus.csv --tag team --html report.html``."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .costs import read
from .reader import CostDataError
from .report import html_report, markdown_report, text_report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cloudtally", description="FinOps reports from FOCUS / AWS CUR cost exports.")
    p.add_argument("file", help="cost export (.csv or .csv.gz)")
    p.add_argument("--preset", default="auto", choices=("auto", "focus", "aws-cur"))
    p.add_argument("--tag", action="append", default=[], help="tag key to report coverage for (repeatable)")
    p.add_argument("--budget", action="append", default=[], help="monthly budget: total=50000, tag:team=data=8000, service=BigQuery=3000")
    p.add_argument("--since", type=date.fromisoformat)
    p.add_argument("--html", help="write an HTML report")
    p.add_argument("--markdown", action="store_true", help="print Markdown (for PRs, Slack, GitHub summaries)")
    p.add_argument("--json", action="store_true", help="print anomalies, movers, forecast and budgets as JSON")
    p.add_argument("--fail-on", choices=("anomaly", "budget"), action="append", default=[], help="exit 1 when found")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = p.parse_args(argv)
    try:
        costs = read(a.file, a.preset)
    except (CostDataError, OSError) as e:
        print(f"cloudtally: {e}", file=sys.stderr)
        return 2
    if a.since:
        costs = costs.filter(since=a.since)
    budgets = {}
    for b in a.budget:
        name, _, value = b.rpartition("=")
        budgets[name] = float(value)
    if a.json:
        f = costs.forecast()
        print(
            json.dumps(
                {
                    "period": [str(costs.start), str(costs.end)],
                    "total": str(costs.total()),
                    "currency": costs.currency,
                    "forecast": {"month": f.month, "month_to_date": str(f.month_to_date), "projected": str(f.projected)},
                    "by_service": {k: str(v) for k, v in costs.by("service")},
                    "anomalies": [
                        {"day": str(x.day), "key": x.key, "cost": str(x.cost), "expected": str(x.expected)} for x in costs.anomalies()
                    ],
                    "tag_coverage": {k: round(v[2], 2) for k, v in costs.tag_coverage(a.tag).items()},
                    "budgets": [
                        {"name": b.name, "projected": str(b.projected), "limit": str(b.limit), "over": b.over}
                        for b in costs.budgets(budgets)
                    ],
                },
                indent=2,
            )
        )
    elif a.markdown:
        print(markdown_report(costs, a.tag, budgets))
    else:
        print(text_report(costs, a.tag, budgets))
    if a.html:
        Path(a.html).write_text(html_report(costs, a.tag, budgets), encoding="utf-8")
        print(f"\n✓ HTML report: {a.html}", file=sys.stderr)
    fail = ("anomaly" in a.fail_on and costs.anomalies()) or ("budget" in a.fail_on and any(b.over for b in costs.budgets(budgets)))
    return 1 if fail else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
