#!/usr/bin/env python3
"""
Claude Usage Dashboard Generator
Fetches token usage from Anthropic Admin API and generates a static HTML dashboard.
"""

import os
import json
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta


ADMIN_API_KEY = os.environ.get("ANTHROPIC_ADMIN_KEY", "")
API_BASE = "https://api.anthropic.com/v1"
HEADERS = {
    "anthropic-version": "2023-06-01",
    "x-api-key": ADMIN_API_KEY,
    "Content-Type": "application/json",
}


def fetch_usage(days: int = 30) -> list[dict]:
    """Fetch daily token usage for the past N days, grouped by model."""
    ending_at = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    starting_at = ending_at - timedelta(days=days)

    params = {
        "starting_at": starting_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ending_at": ending_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bucket_width": "1d",
        "group_by[]": "model",
        "limit": 200,
    }

    url = f"{API_BASE}/organizations/usage_report/messages?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=HEADERS)

    results = []
    while url:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        results.extend(data.get("data", []))
        if data.get("has_more") and data.get("next_page"):
            params["page"] = data["next_page"]
            url = f"{API_BASE}/organizations/usage_report/messages?" + urllib.parse.urlencode(params, doseq=True)
        else:
            url = None

    return results


def aggregate(raw: list[dict]) -> tuple[dict, dict]:
    """Aggregate usage by date and by model."""
    by_date: dict[str, dict] = {}
    by_model: dict[str, dict] = {}

    for entry in raw:
        date = entry.get("start_time", "")[:10]
        model = entry.get("model") or "unknown"

        input_t = entry.get("uncached_input_tokens", 0) or 0
        cached_t = entry.get("cached_input_tokens", 0) or 0
        cache_write_t = entry.get("cache_creation_input_tokens", 0) or 0
        output_t = entry.get("output_tokens", 0) or 0

        for bucket, key in [(by_date, date), (by_model, model)]:
            if key not in bucket:
                bucket[key] = {"input": 0, "cached": 0, "cache_write": 0, "output": 0}
            bucket[key]["input"] += input_t
            bucket[key]["cached"] += cached_t
            bucket[key]["cache_write"] += cache_write_t
            bucket[key]["output"] += output_t

    return dict(sorted(by_date.items())), by_model


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def generate_html(by_date: dict, by_model: dict, days: int) -> str:
    dates = list(by_date.keys())
    input_series = [by_date[d]["input"] for d in dates]
    cached_series = [by_date[d]["cached"] for d in dates]
    cache_write_series = [by_date[d]["cache_write"] for d in dates]
    output_series = [by_date[d]["output"] for d in dates]

    total_input = sum(input_series) + sum(cached_series) + sum(cache_write_series)
    total_output = sum(output_series)
    total_all = total_input + total_output

    model_labels = list(by_model.keys())
    model_totals = [
        v["input"] + v["cached"] + v["cache_write"] + v["output"]
        for v in by_model.values()
    ]

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Table rows
    table_rows = ""
    for d in reversed(dates):
        v = by_date[d]
        total_day = v["input"] + v["cached"] + v["cache_write"] + v["output"]
        table_rows += f"""
        <tr>
          <td>{d}</td>
          <td>{fmt_tokens(v['input'])}</td>
          <td>{fmt_tokens(v['cached'])}</td>
          <td>{fmt_tokens(v['cache_write'])}</td>
          <td>{fmt_tokens(v['output'])}</td>
          <td><strong>{fmt_tokens(total_day)}</strong></td>
        </tr>"""

    model_rows = ""
    for m, v in sorted(by_model.items(), key=lambda x: -(sum(x[1].values()))):
        total_m = sum(v.values())
        model_rows += f"""
        <tr>
          <td>{m}</td>
          <td>{fmt_tokens(v['input'])}</td>
          <td>{fmt_tokens(v['output'])}</td>
          <td><strong>{fmt_tokens(total_m)}</strong></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Claude Usage Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0f0f13; color: #e2e2e7; min-height: 100vh; padding: 24px; }}
    h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
    .subtitle {{ color: #888; font-size: 0.85rem; margin-bottom: 28px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
              gap: 16px; margin-bottom: 32px; }}
    .card {{ background: #1a1a24; border: 1px solid #2a2a38; border-radius: 12px;
             padding: 20px; }}
    .card-label {{ font-size: 0.75rem; color: #888; text-transform: uppercase;
                   letter-spacing: 0.08em; margin-bottom: 8px; }}
    .card-value {{ font-size: 2rem; font-weight: 700; }}
    .card-value.blue {{ color: #60a5fa; }}
    .card-value.green {{ color: #34d399; }}
    .card-value.purple {{ color: #a78bfa; }}
    .card-value.orange {{ color: #fb923c; }}
    .charts {{ display: grid; grid-template-columns: 2fr 1fr; gap: 24px; margin-bottom: 32px; }}
    @media (max-width: 768px) {{ .charts {{ grid-template-columns: 1fr; }} }}
    .chart-box {{ background: #1a1a24; border: 1px solid #2a2a38; border-radius: 12px;
                  padding: 20px; }}
    .chart-title {{ font-size: 0.9rem; font-weight: 600; color: #ccc;
                    margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    th {{ text-align: left; padding: 10px 12px; color: #888; font-weight: 500;
          border-bottom: 1px solid #2a2a38; }}
    td {{ padding: 9px 12px; border-bottom: 1px solid #1e1e2a; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #1e1e2c; }}
    .section-title {{ font-size: 1rem; font-weight: 600; margin: 0 0 14px; color: #ccc; }}
    .table-box {{ background: #1a1a24; border: 1px solid #2a2a38; border-radius: 12px;
                  padding: 20px; margin-bottom: 24px; overflow-x: auto; }}
    .badge {{ display: inline-block; font-size: 0.7rem; background: #2a2a38;
              border-radius: 4px; padding: 2px 8px; color: #aaa; margin-left: 8px; }}
  </style>
</head>
<body>
  <h1>Claude Usage Dashboard <span class="badge">Last {days} days</span></h1>
  <div class="subtitle">Updated: {updated_at} &nbsp;·&nbsp; All workspaces &nbsp;·&nbsp; All models</div>

  <div class="cards">
    <div class="card">
      <div class="card-label">Total Input Tokens</div>
      <div class="card-value blue">{fmt_tokens(total_input)}</div>
    </div>
    <div class="card">
      <div class="card-label">Total Output Tokens</div>
      <div class="card-value green">{fmt_tokens(total_output)}</div>
    </div>
    <div class="card">
      <div class="card-label">Grand Total</div>
      <div class="card-value purple">{fmt_tokens(total_all)}</div>
    </div>
    <div class="card">
      <div class="card-label">Active Days</div>
      <div class="card-value orange">{sum(1 for d in by_date.values() if sum(d.values()) > 0)}</div>
    </div>
  </div>

  <div class="charts">
    <div class="chart-box">
      <div class="chart-title">Daily Token Usage</div>
      <canvas id="dailyChart" height="220"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-title">By Model</div>
      <canvas id="modelChart" height="220"></canvas>
    </div>
  </div>

  <div class="table-box">
    <div class="section-title">Daily Breakdown</div>
    <table>
      <thead>
        <tr>
          <th>Date</th><th>Input</th><th>Cache Hit</th>
          <th>Cache Write</th><th>Output</th><th>Total</th>
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>

  <div class="table-box">
    <div class="section-title">Model Breakdown</div>
    <table>
      <thead>
        <tr><th>Model</th><th>Input</th><th>Output</th><th>Total</th></tr>
      </thead>
      <tbody>{model_rows}</tbody>
    </table>
  </div>

  <script>
    const COLORS = ['#60a5fa','#34d399','#a78bfa','#fb923c','#f472b6','#facc15','#38bdf8'];

    new Chart(document.getElementById('dailyChart'), {{
      type: 'bar',
      data: {{
        labels: {json.dumps(dates)},
        datasets: [
          {{ label: 'Input', data: {json.dumps(input_series)}, backgroundColor: '#60a5fa88', borderColor: '#60a5fa', borderWidth: 1 }},
          {{ label: 'Cache Hit', data: {json.dumps(cached_series)}, backgroundColor: '#34d39988', borderColor: '#34d399', borderWidth: 1 }},
          {{ label: 'Cache Write', data: {json.dumps(cache_write_series)}, backgroundColor: '#a78bfa88', borderColor: '#a78bfa', borderWidth: 1 }},
          {{ label: 'Output', data: {json.dumps(output_series)}, backgroundColor: '#fb923c88', borderColor: '#fb923c', borderWidth: 1 }},
        ]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ labels: {{ color: '#aaa', boxWidth: 12 }} }} }},
        scales: {{
          x: {{ stacked: true, ticks: {{ color: '#888', maxRotation: 45 }}, grid: {{ color: '#2a2a38' }} }},
          y: {{ stacked: true, ticks: {{ color: '#888' }}, grid: {{ color: '#2a2a38' }} }}
        }}
      }}
    }});

    new Chart(document.getElementById('modelChart'), {{
      type: 'doughnut',
      data: {{
        labels: {json.dumps(model_labels)},
        datasets: [{{ data: {json.dumps(model_totals)},
                      backgroundColor: COLORS, borderColor: '#1a1a24', borderWidth: 2 }}]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#aaa', boxWidth: 12, font: {{ size: 11 }} }} }} }}
      }}
    }});
  </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Generate Claude usage dashboard")
    parser.add_argument("--days", type=int, default=30, help="Number of days to look back")
    parser.add_argument("--output", default="index.html", help="Output HTML file path")
    args = parser.parse_args()

    if not ADMIN_API_KEY:
        print("Error: Set ANTHROPIC_ADMIN_KEY environment variable")
        raise SystemExit(1)

    print(f"Fetching {args.days} days of usage data...")
    raw = fetch_usage(args.days)
    print(f"  Got {len(raw)} data points")

    by_date, by_model = aggregate(raw)
    html = generate_html(by_date, by_model, args.days)

    with open(args.output, "w") as f:
        f.write(html)
    print(f"Dashboard written to: {args.output}")


if __name__ == "__main__":
    main()
