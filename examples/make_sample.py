"""Builds examples/focus_sample.csv: 60 days of synthetic FOCUS 1.0 cost data (not real billing data)."""

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
START, DAYS = date(2026, 8, 1), 60
RESOURCES = [
    # provider, service, category, account, region, resource, base $/day, tags
    ("AWS", "Amazon Elastic Compute Cloud", "Compute", "prod", "us-east-1", "i-0a91f3c2web", 410, {"team": "web", "env": "prod"}),
    ("AWS", "Amazon Elastic Compute Cloud", "Compute", "prod", "us-east-1", "i-07c1e9a4api", 280, {"team": "api", "env": "prod"}),
    ("AWS", "Amazon Elastic Compute Cloud", "Compute", "staging", "us-east-1", "i-0bb2d11ci", 95, {}),
    ("AWS", "Amazon Relational Database Service", "Databases", "prod", "us-east-1", "orders-db", 230, {"team": "api", "env": "prod"}),
    ("AWS", "Amazon Simple Storage Service", "Storage", "prod", "us-east-1", "media-bucket", 120, {"team": "web", "env": "prod"}),
    ("AWS", "Amazon Simple Storage Service", "Storage", "prod", "us-east-1", "logs-archive", 60, {}),
    ("Microsoft", "Azure Kubernetes Service", "Compute", "analytics", "brazilsouth", "aks-ml", 190, {"team": "data", "env": "prod"}),
    ("Google Cloud", "BigQuery", "Analytics", "analytics", "us", "warehouse", 140, {"team": "data", "env": "prod"}),
    ("Google Cloud", "Cloud Storage", "Storage", "analytics", "us", "datalake", 45, {"team": "data"}),
]
rows = []
for i in range(DAYS):
    day = START + timedelta(days=i)
    weekend = day.weekday() >= 5
    for prov, svc, cat, acct, region, res, base, tags in RESOURCES:
        cost = base * random.uniform(0.92, 1.08) * (0.8 if weekend and cat == "Compute" else 1)
        if res == "orders-db" and day >= date(2026, 9, 15):
            cost *= 1.45  # someone scaled the database up
        if res == "warehouse" and day == date(2026, 9, 20):
            cost *= 7  # runaway query
        rows.append(
            {
                "ChargePeriodStart": f"{day}T00:00:00Z",
                "ChargePeriodEnd": f"{day + timedelta(days=1)}T00:00:00Z",
                "BilledCost": f"{cost:.4f}",
                "EffectiveCost": f"{cost:.4f}",
                "BillingCurrency": "USD",
                "ProviderName": prov,
                "ServiceName": svc,
                "ServiceCategory": cat,
                "SubAccountName": acct,
                "RegionName": region,
                "ResourceId": res,
                "ResourceName": res,
                "ChargeCategory": "Usage",
                "Tags": json.dumps(tags),
            }
        )
    if day.day == 1:
        rows.append(
            {
                **rows[-1],
                "ServiceName": "Support",
                "ResourceId": "",
                "ResourceName": "",
                "ChargeCategory": "Purchase",
                "BilledCost": "300.0000",
                "EffectiveCost": "300.0000",
                "Tags": "{}",
                "ServiceCategory": "Other",
                "ProviderName": "AWS",
            }
        )
        rows.append(
            {
                **rows[-1],
                "ServiceName": "Amazon Elastic Compute Cloud",
                "ChargeCategory": "Credit",
                "BilledCost": "-150.0000",
                "EffectiveCost": "-150.0000",
                "ServiceCategory": "Compute",
            }
        )
out = Path(__file__).with_name("focus_sample.csv")
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} rows → {out.name}")
