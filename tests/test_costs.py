import gzip
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import cloudtally
from cloudtally import CostDataError

SAMPLE = Path(__file__).parent.parent / "examples" / "focus_sample.csv"


@pytest.fixture(scope="module")
def costs():
    return cloudtally.read(SAMPLE)


def test_read_focus(costs):
    assert len(costs) == 9 * 60 + 4 and costs.currency == "USD"
    assert (costs.start, costs.end) == (date(2026, 8, 1), date(2026, 9, 29))
    assert costs.total() == sum(c.cost for c in costs.charges)
    assert costs.money(Decimal("1234.5")) == "$1,234.50"


def test_breakdowns(costs):
    services = dict(costs.by("service"))
    assert next(iter(services)) == "Amazon Elastic Compute Cloud"
    assert sum(services.values()) == costs.total()
    teams = dict(costs.by("tag:team"))
    assert {"web", "api", "data", "(none)"} <= set(teams)
    with pytest.raises(ValueError):
        costs.by("colour")


def test_tag_coverage_and_untagged(costs):
    tagged, untagged, pct = costs.tag_coverage(["team"])["team"]
    assert 80 < pct < 95 and untagged > 0
    assert [k for k, _ in costs.untagged("team", top=2)] == ["i-0bb2d11ci", "logs-archive"]


def test_anomaly_detection_finds_the_runaway_query(costs):
    top = costs.anomalies()[0]
    assert (top.day, top.key) == (date(2026, 9, 20), "BigQuery")
    assert top.cost > 5 * top.expected and top.score > 10
    assert all(a.key != "Amazon Simple Storage Service" for a in costs.anomalies())


def test_movers_find_the_database_scale_up(costs):
    movers = {m.key: m for m in costs.movers(days=7)}
    rds = movers["Amazon Relational Database Service"]
    assert rds.delta > 0 and rds.pct is None or rds.pct > 0
    weekly = {m.key: m for m in costs.filter(since=date(2026, 9, 1)).movers(days=14)}
    assert weekly["Amazon Relational Database Service"].pct > 25


def test_forecast_and_budgets(costs):
    f = costs.forecast()
    assert f.month == "2026-09" and f.days_left == 1
    assert f.projected == f.month_to_date + f.daily_run_rate
    statuses = {b.name: b for b in costs.budgets({"total": 40000, "tag:team=data": 5000, "service=BigQuery": 10})}
    assert statuses["total"].over and statuses["service=BigQuery"].over
    assert statuses["tag:team=data"].spent > 0


def test_filters(costs):
    gcp = costs.filter(provider="Google Cloud")
    assert {c.provider for c in gcp.charges} == {"Google Cloud"}
    data = costs.filter(tag_team="data", since=date(2026, 9, 1))
    assert data.start >= date(2026, 9, 1) and all(c.tags.get("team") == "data" for c in data.charges)


def test_aws_cur_preset_and_gzip(tmp_path):
    csv_text = (
        "lineItem/UsageStartDate,lineItem/UnblendedCost,lineItem/ProductCode,product/region,lineItem/UsageAccountId,"
        "lineItem/ResourceId,lineItem/CurrencyCode,resourceTags/user:team\n"
        "2026-09-01T00:00:00Z,10.5,AmazonEC2,us-east-1,111111111111,i-1,USD,web\n"
        "2026-09-02T00:00:00Z,4.5,AmazonS3,us-east-1,111111111111,bucket,USD,\n"
    )
    f = tmp_path / "cur.csv.gz"
    f.write_bytes(gzip.compress(csv_text.encode()))
    c = cloudtally.read(f)
    assert c.total() == Decimal("15.0") and c.charges[0].provider == "AWS"
    assert c.charges[0].tags == {"team": "web"} and c.tag_coverage(["team"])["team"][2] == 70.0


def test_bad_files(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n")
    with pytest.raises(CostDataError):
        cloudtally.read(f)
    with pytest.raises(CostDataError):
        cloudtally.read(SAMPLE, preset="nope")


def test_reports(costs):
    t = cloudtally.text_report(costs, ["team"], {"total": 40000})
    assert "By service" in t and "Anomalies" in t and "Budget total" in t
    md = cloudtally.markdown_report(costs, ["team"])
    assert md.startswith("### Cloud spend") and "| BigQuery |" in md
    html = cloudtally.html_report(costs, ["team"], {"total": 40000})
    assert html.startswith("<!doctype html>") and "Daily spend" in html and "<svg" in html and "Budgets" in html
