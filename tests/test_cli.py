import json
from pathlib import Path

from cloudtally.cli import main

SAMPLE = str(Path(__file__).parent.parent / "examples" / "focus_sample.csv")


def test_cli(tmp_path, capsys):
    html = tmp_path / "r.html"
    assert main([SAMPLE, "--tag", "team", "--html", str(html)]) == 0
    assert "Cloud spend" in capsys.readouterr().out and html.exists()
    assert main([SAMPLE, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["anomalies"][0]["key"] == "BigQuery" and data["currency"] == "USD"
    assert main([SAMPLE, "--fail-on", "anomaly"]) == 1
    assert main([SAMPLE, "--budget", "tag:team=data=1000", "--fail-on", "budget", "--markdown"]) == 1
    assert main([str(tmp_path / "missing.csv")]) == 2
