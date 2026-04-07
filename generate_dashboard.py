#!/usr/bin/env python3
"""
Claude Code usage dashboard generator.
Reads local Claude Code session logs and generates a static HTML dashboard.
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def token_total(usage: dict) -> int:
    return sum(
        int(usage.get(key) or 0)
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
        )
    )


def fetch_usage(days: int = 30, claude_dir: Optional[str] = None) -> list[dict]:
    """Fetch usage from local Claude Code JSONL session logs."""
    base_dir = Path(claude_dir or os.path.expanduser("~/.claude"))
    projects_dir = base_dir / "projects"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if not projects_dir.exists():
        raise FileNotFoundError(f"Claude projects directory not found: {projects_dir}")

    latest_records: dict[tuple[str, str], tuple[datetime, dict]] = {}

    for path in projects_dir.rglob("*.jsonl"):
        try:
            with path.open() as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    message = entry.get("message") or {}
                    usage = message.get("usage") or {}
                    session_id = entry.get("sessionId")
                    message_id = message.get("id")
                    timestamp = parse_timestamp(entry.get("timestamp", ""))
                    model = message.get("model") or "unknown"

                    if not usage or not session_id or not message_id or not timestamp:
                        continue
                    if timestamp < cutoff or model == "<synthetic>":
                        continue
                    if token_total(usage) <= 0:
                        continue

                    dedupe_key = (session_id, message_id)
                    current = latest_records.get(dedupe_key)
                    if current is None or timestamp > current[0] or (
                        timestamp == current[0] and token_total(usage) > token_total(current[1]["usage"])
                    ):
                        latest_records[dedupe_key] = (
                            timestamp,
                            {
                                "timestamp": timestamp,
                                "model": model,
                                "usage": usage,
                            },
                        )
        except OSError:
            continue

    results = []
    for timestamp, record in latest_records.values():
        usage = record["usage"]
        results.append(
            {
                "start_time": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "model": record["model"],
                "uncached_input_tokens": int(usage.get("input_tokens") or 0),
                "cached_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
                "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
            }
        )

    results.sort(key=lambda item: item["start_time"])
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

        for bucket, key in ((by_date, date), (by_model, model)):
            if key not in bucket:
                bucket[key] = {"input": 0, "cached": 0, "cache_write": 0, "output": 0}
            bucket[key]["input"] += input_t
            bucket[key]["cached"] += cached_t
            bucket[key]["cache_write"] += cache_write_t
            bucket[key]["output"] += output_t

    return dict(sorted(by_date.items())), by_model


def fmt_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def generate_html(by_date: dict, by_model: dict, days: int, source_dir: str, data_points: int) -> str:
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
        values["input"] + values["cached"] + values["cache_write"] + values["output"]
        for values in by_model.values()
    ]

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    table_rows = ""
    for day in reversed(dates):
        values = by_date[day]
        total_day = values["input"] + values["cached"] + values["cache_write"] + values["output"]
        table_rows += f"""
        <tr>
          <td>{day}</td>
          <td>{fmt_tokens(values['input'])}</td>
          <td>{fmt_tokens(values['cached'])}</td>
          <td>{fmt_tokens(values['cache_write'])}</td>
          <td>{fmt_tokens(values['output'])}</td>
          <td><strong>{fmt_tokens(total_day)}</strong></td>
        </tr>"""

    model_rows = ""
    for model, values in sorted(by_model.items(), key=lambda item: -(sum(item[1].values()))):
        total_model = sum(values.values())
        model_rows += f"""
        <tr>
          <td>{model}</td>
          <td>{fmt_tokens(values['input'])}</td>
          <td>{fmt_tokens(values['output'])}</td>
          <td><strong>{fmt_tokens(total_model)}</strong></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Claude Code Usage Dashboard</title>
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
    .chart-wrap {{ position: relative; height: 320px; }}
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
  <h1>Claude Code Usage Dashboard <span class="badge">Last {days} days</span></h1>
  <div class="subtitle">Updated: {updated_at} &nbsp;·&nbsp; Source: local Claude Code logs &nbsp;·&nbsp; Messages: {data_points}</div>

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
      <div class="card-value orange">{sum(1 for day in by_date.values() if sum(day.values()) > 0)}</div>
    </div>
  </div>

  <div class="charts">
    <div class="chart-box">
      <div class="chart-title">Daily Token Usage</div>
      <div class="chart-wrap">
        <canvas id="dailyChart"></canvas>
      </div>
    </div>
    <div class="chart-box">
      <div class="chart-title">By Model</div>
      <div class="chart-wrap">
        <canvas id="modelChart"></canvas>
      </div>
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

  <div class="table-box">
    <div class="section-title">Data Source</div>
    <table>
      <tbody>
        <tr><td>Claude directory</td><td>{source_dir}</td></tr>
        <tr><td>Scope</td><td>Local Claude Code sessions found on this machine</td></tr>
        <tr><td>Limitation</td><td>Does not include usage from other devices or non-CLI surfaces</td></tr>
      </tbody>
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
          {{ label: 'Output', data: {json.dumps(output_series)}, backgroundColor: '#fb923c88', borderColor: '#fb923c', borderWidth: 1 }}
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
    parser = argparse.ArgumentParser(description="Generate Claude Code usage dashboard")
    parser.add_argument("--days", type=int, default=30, help="Number of days to look back")
    parser.add_argument("--output", default="index.html", help="Output HTML file path")
    parser.add_argument(
        "--claude-dir",
        default=os.path.expanduser("~/.claude"),
        help="Base directory for Claude Code local data",
    )
    args = parser.parse_args()

    print(f"Reading {args.days} days of local Claude Code usage...")
    raw = fetch_usage(args.days, args.claude_dir)
    print(f"  Got {len(raw)} message records")

    by_date, by_model = aggregate(raw)
    html = generate_html(by_date, by_model, args.days, args.claude_dir, len(raw))

    with open(args.output, "w") as handle:
        handle.write(html)
    print(f"Dashboard written to: {args.output}")


if __name__ == "__main__":
    main()
