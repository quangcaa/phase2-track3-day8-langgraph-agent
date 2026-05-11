"""Report generation helper."""

from __future__ import annotations

from pathlib import Path

from .metrics import MetricsReport


def render_report_stub(metrics: MetricsReport) -> str:
    """Return a metrics summary report.

    The full lab report is maintained manually in reports/lab_report.md.
    This stub is auto-generated alongside metrics.json for quick reference.
    """
    lines = [
        "# Day 08 Lab Report",
        "",
        "## Metrics summary",
        "",
        f"- Total scenarios: {metrics.total_scenarios}",
        f"- Success rate: {metrics.success_rate:.2%}",
        f"- Average nodes visited: {metrics.avg_nodes_visited:.2f}",
        f"- Total retries: {metrics.total_retries}",
        f"- Total interrupts: {metrics.total_interrupts}",
        "",
        "## Scenario details",
        "",
        "| Scenario | Expected | Actual | Success | Retries | Errors |",
        "|---|---|---|---:|---:|---:|",
    ]
    for m in metrics.scenario_metrics:
        status = "✓" if m.success else "✗"
        lines.append(
            f"| {m.scenario_id} | {m.expected_route} | {m.actual_route} "
            f"| {status} | {m.retry_count} | {len(m.errors)} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(metrics: MetricsReport, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report_stub(metrics), encoding="utf-8")
