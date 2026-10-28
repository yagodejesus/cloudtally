"""Reading cost exports: FinOps FOCUS (AWS, Azure, Google Cloud, Oracle…) and legacy AWS CUR."""

from __future__ import annotations

import csv
import gzip
import io
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

__all__ = ["Charge", "read_rows", "PRESETS", "CostDataError"]


class CostDataError(ValueError):
    """The file is missing the columns needed for cost analysis."""


@dataclass(slots=True)
class Charge:
    day: date
    cost: Decimal
    service: str = ""
    category: str = ""
    provider: str = ""
    region: str = ""
    account: str = ""
    resource: str = ""
    charge_category: str = ""
    currency: str = ""
    tags: dict[str, str] = field(default_factory=dict)

    def get(self, dim: str) -> str:
        if dim.startswith("tag:"):
            return self.tags.get(dim[4:], "")
        return getattr(self, dim)


# column → field, first match wins
PRESETS: dict[str, dict[str, list[str]]] = {
    "focus": {
        "day": ["ChargePeriodStart"],
        "cost": ["EffectiveCost", "BilledCost"],
        "service": ["ServiceName"],
        "category": ["ServiceCategory"],
        "provider": ["ProviderName", "ServiceProviderName"],
        "region": ["RegionName", "RegionId"],
        "account": ["SubAccountName", "SubAccountId", "BillingAccountName"],
        "resource": ["ResourceName", "ResourceId"],
        "charge_category": ["ChargeCategory"],
        "currency": ["BillingCurrency"],
        "tags": ["Tags"],
    },
    "aws-cur": {
        "day": ["lineItem/UsageStartDate"],
        "cost": ["lineItem/UnblendedCost"],
        "service": ["product/ProductName", "lineItem/ProductCode"],
        "category": ["product/productFamily"],
        "provider": [],
        "region": ["product/region"],
        "account": ["lineItem/UsageAccountId"],
        "resource": ["lineItem/ResourceId"],
        "charge_category": ["lineItem/LineItemType"],
        "currency": ["lineItem/CurrencyCode"],
        "tags": [],
    },
}


def _open_text(source: str | Path | bytes) -> io.TextIOBase:
    if isinstance(source, bytes):
        raw = gzip.decompress(source) if source[:2] == b"\x1f\x8b" else source
        return io.StringIO(raw.decode("utf-8-sig"))
    p = Path(source)
    if p.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(p), encoding="utf-8-sig", newline="")
    return open(p, encoding="utf-8-sig", newline="")


def _tags(raw: str) -> dict[str, str]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return {str(k): str(x) for k, x in v.items()} if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                k, x = part.split("=", 1)
                out[k.strip()] = x.strip()
        return out


def read_rows(source: str | Path | bytes, preset: str = "auto", tag_prefix: str = "resourceTags/user:") -> list[Charge]:
    """Read a cost export (CSV or CSV.gz). ``preset``: ``"focus"``, ``"aws-cur"`` or ``"auto"``."""
    with _open_text(source) as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        if preset == "auto":
            preset = "aws-cur" if "lineItem/UnblendedCost" in cols else "focus"
        if preset not in PRESETS:
            raise CostDataError(f"unknown preset {preset!r} (use {', '.join(PRESETS)})")
        mapping = {f_: next((c for c in names if c in cols), None) for f_, names in PRESETS[preset].items()}
        if not mapping["day"] or not mapping["cost"]:
            raise CostDataError(f"missing date/cost columns for preset '{preset}'. Found: {cols[:12]}")
        tag_cols = [c for c in cols if c.startswith(tag_prefix)]
        out: list[Charge] = []
        for row in reader:
            raw_day = (row.get(mapping["day"]) or "").strip()
            raw_cost = (row.get(mapping["cost"]) or "").strip()
            if not raw_day or not raw_cost:
                continue
            try:
                cost = Decimal(raw_cost)
                day = date.fromisoformat(raw_day[:10])
            except (InvalidOperation, ValueError) as exc:
                raise CostDataError(f"bad row (date={raw_day!r}, cost={raw_cost!r})") from exc
            tags = _tags(row.get(mapping["tags"], "")) if mapping["tags"] else {}
            for c in tag_cols:
                if row.get(c):
                    tags[c[len(tag_prefix) :]] = row[c]
            out.append(
                Charge(
                    day=day,
                    cost=cost,
                    service=(row.get(mapping["service"]) or "") if mapping["service"] else "",
                    category=(row.get(mapping["category"]) or "") if mapping["category"] else "",
                    provider=(row.get(mapping["provider"]) or ("AWS" if preset == "aws-cur" else ""))
                    if mapping["provider"]
                    else ("AWS" if preset == "aws-cur" else ""),
                    region=(row.get(mapping["region"]) or "") if mapping["region"] else "",
                    account=(row.get(mapping["account"]) or "") if mapping["account"] else "",
                    resource=(row.get(mapping["resource"]) or "") if mapping["resource"] else "",
                    charge_category=(row.get(mapping["charge_category"]) or "") if mapping["charge_category"] else "",
                    currency=(row.get(mapping["currency"]) or "") if mapping["currency"] else "",
                    tags=tags,
                )
            )
        return out
