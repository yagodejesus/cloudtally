"""Analyses on cost data: breakdowns, tag coverage, anomalies, movers, forecasts and budgets."""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

from .reader import Charge, read_rows

__all__ = ["Costs", "Anomaly", "Mover", "Forecast", "BudgetStatus", "read"]

DIMENSIONS = ("service", "category", "provider", "region", "account", "resource", "charge_category")
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "BRL": "R$", "JPY": "¥", "INR": "₹"}
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Anomaly:
    day: date
    key: str
    cost: Decimal
    expected: Decimal
    impact: Decimal
    score: float


@dataclass(frozen=True)
class Mover:
    key: str
    before: Decimal
    after: Decimal
    delta: Decimal
    pct: float | None


@dataclass(frozen=True)
class Forecast:
    month: str
    month_to_date: Decimal
    daily_run_rate: Decimal
    projected: Decimal
    days_left: int


@dataclass(frozen=True)
class BudgetStatus:
    name: str
    limit: Decimal
    spent: Decimal
    projected: Decimal

    @property
    def pct_projected(self) -> float:
        return float(self.projected / self.limit * 100) if self.limit else 0.0

    @property
    def over(self) -> bool:
        return self.projected > self.limit


class Costs:
    """Cost line items with FinOps analyses. Create with :func:`read` or from :class:`Charge` objects."""

    def __init__(self, charges: Iterable[Charge]) -> None:
        self.charges = list(charges)
        currencies = {c.currency for c in self.charges if c.currency}
        self.currency = currencies.pop() if len(currencies) == 1 else ("mixed" if currencies else "")

    def __len__(self) -> int:
        return len(self.charges)

    def __repr__(self) -> str:
        span = f"{self.start} → {self.end}" if self.charges else "empty"
        return f"<Costs {len(self)} line items, {span}, total {self.money(self.total())}>"

    # -------------------------------------------------------------- basics
    @property
    def start(self) -> date:
        return min(c.day for c in self.charges)

    @property
    def end(self) -> date:
        return max(c.day for c in self.charges)

    def money(self, v: Decimal) -> str:
        sym = SYMBOLS.get(self.currency, f"{self.currency} " if self.currency else "")
        return f"{'-' if v < 0 else ''}{sym}{abs(v).quantize(CENT):,}"

    def total(self) -> Decimal:
        return sum((c.cost for c in self.charges), Decimal(0))

    def filter(self, since: date | None = None, until: date | None = None, **equals: str) -> Costs:
        """``costs.filter(since=date(2026, 9, 1), provider="AWS", tag_team="data")``."""

        def ok(c: Charge) -> bool:
            if since and c.day < since or until and c.day > until:
                return False
            for k, v in equals.items():
                dim = f"tag:{k[4:]}" if k.startswith("tag_") else k
                if c.get(dim) != v:
                    return False
            return True

        return Costs(c for c in self.charges if ok(c))

    def by(self, dim: str = "service", top: int | None = None) -> list[tuple[str, Decimal]]:
        """Totals per dimension (``service``, ``account``, ``region``, ``resource``, ``tag:team``…), largest first."""
        self._check_dim(dim)
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for c in self.charges:
            totals[c.get(dim) or "(none)"] += c.cost
        out = sorted(totals.items(), key=lambda kv: -kv[1])
        return out[:top] if top else out

    def daily(self, dim: str | None = None) -> dict:
        """``{day: cost}`` or, with ``dim``, ``{key: {day: cost}}`` — every day in range present (zeros filled)."""
        days = [self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)] if self.charges else []
        if dim is None:
            out = dict.fromkeys(days, Decimal(0))
            for c in self.charges:
                out[c.day] += c.cost
            return out
        self._check_dim(dim)
        series: dict[str, dict[date, Decimal]] = defaultdict(lambda: dict.fromkeys(days, Decimal(0)))
        for c in self.charges:
            series[c.get(dim) or "(none)"][c.day] += c.cost
        return dict(series)

    @staticmethod
    def _check_dim(dim: str) -> None:
        if dim not in DIMENSIONS and not dim.startswith("tag:"):
            raise ValueError(f"unknown dimension {dim!r}; use one of {DIMENSIONS} or 'tag:<key>'")

    # -------------------------------------------------------------- FinOps
    def tag_coverage(self, keys: Iterable[str]) -> dict[str, tuple[Decimal, Decimal, float]]:
        """For each tag key: (tagged cost, untagged cost, % of spend tagged). Credits and taxes are ignored."""
        usage = [c for c in self.charges if c.cost > 0 and c.charge_category.lower() not in ("tax", "credit")]
        total = sum((c.cost for c in usage), Decimal(0))
        out = {}
        for k in keys:
            tagged = sum((c.cost for c in usage if c.tags.get(k)), Decimal(0))
            out[k] = (tagged, total - tagged, float(tagged / total * 100) if total else 100.0)
        return out

    def untagged(self, key: str, dim: str = "resource", top: int = 10) -> list[tuple[str, Decimal]]:
        """Where the spend without tag ``key`` is — the to-do list for your tagging policy."""
        return Costs(c for c in self.charges if not c.tags.get(key) and c.cost > 0).by(dim, top)

    def anomalies(self, dim: str = "service", window: int = 14, threshold: float = 3.5, min_impact: float = 10.0) -> list[Anomaly]:
        """Daily spikes per ``dim`` using a robust z-score (median and MAD of the previous ``window`` days)."""
        found = []
        usage = Costs(c for c in self.charges if c.charge_category.lower() in ("", "usage"))  # purchases/credits/taxes are expected spikes
        if not len(usage):
            return []
        for key, series in usage.daily(dim).items():
            days = sorted(series)
            values = [series[d] for d in days]
            for i in range(window, len(values)):
                hist = [float(v) for v in values[i - window : i]]
                med = median(hist)
                mad = median(abs(x - med) for x in hist)
                scale = max(1.4826 * mad, abs(med) * 0.05, 0.01)
                x = float(values[i])
                z = (x - med) / scale
                impact = Decimal(str(x - med)).quantize(CENT)
                if z >= threshold and impact >= Decimal(str(min_impact)):
                    found.append(Anomaly(days[i], key, values[i].quantize(CENT), Decimal(str(med)).quantize(CENT), impact, round(z, 1)))
        return sorted(found, key=lambda a: -a.impact)

    def movers(self, days: int = 7, dim: str = "service", top: int = 10) -> list[Mover]:
        """Biggest changes between the last ``days`` days and the ``days`` before them."""
        end = self.end
        cut = end - timedelta(days=days)
        prev_cut = cut - timedelta(days=days)
        before: dict[str, Decimal] = defaultdict(Decimal)
        after: dict[str, Decimal] = defaultdict(Decimal)
        for c in self.charges:
            k = c.get(dim) or "(none)"
            if cut < c.day <= end:
                after[k] += c.cost
            elif prev_cut < c.day <= cut:
                before[k] += c.cost
        out = []
        for k in set(before) | set(after):
            b, a = before[k], after[k]
            out.append(Mover(k, b.quantize(CENT), a.quantize(CENT), (a - b).quantize(CENT), float((a - b) / b * 100) if b else None))
        return sorted(out, key=lambda m: -abs(m.delta))[:top]

    def forecast(self, run_rate_days: int = 7) -> Forecast:
        """Month-end projection for the latest month in the data: month-to-date + recent daily run rate."""
        end = self.end
        month = (end.year, end.month)
        mtd = sum((c.cost for c in self.charges if (c.day.year, c.day.month) == month), Decimal(0))
        daily = self.daily()
        recent = [v for d, v in daily.items() if end - timedelta(days=run_rate_days) < d <= end]
        rate = sum(recent, Decimal(0)) / len(recent) if recent else Decimal(0)
        days_left = calendar.monthrange(*month)[1] - end.day
        return Forecast(
            f"{month[0]}-{month[1]:02d}", mtd.quantize(CENT), rate.quantize(CENT), (mtd + rate * days_left).quantize(CENT), days_left
        )

    def budgets(self, limits: Mapping[str, float | Decimal]) -> list[BudgetStatus]:
        """Monthly budgets: ``{"total": 50000, "tag:team=data": 8000, "service=BigQuery": 3000}``."""
        out = []
        end = self.end
        for name, limit in limits.items():
            if name == "total":
                subset = self
            else:
                dim, _, value = name.partition("=")
                subset = Costs(c for c in self.charges if c.get(dim) == value)
            month_items = [c for c in subset.charges if (c.day.year, c.day.month) == (end.year, end.month)]
            if not month_items:
                out.append(BudgetStatus(name, Decimal(str(limit)), Decimal(0), Decimal(0)))
                continue
            sub = Costs(month_items + [Charge(end, Decimal(0))])  # anchor the forecast on the dataset's last day
            f = sub.forecast()
            out.append(BudgetStatus(name, Decimal(str(limit)), f.month_to_date, f.projected))
        return out


def read(source: str | Path | bytes, preset: str = "auto") -> Costs:
    """Load a FOCUS (default) or AWS CUR export, CSV or CSV.gz."""
    return Costs(read_rows(source, preset))
