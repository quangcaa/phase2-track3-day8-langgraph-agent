"""CLI for the lab."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from .graph import build_graph
from .metrics import MetricsReport, metric_from_state, summarize_metrics, write_metrics
from .persistence import build_checkpointer
from .report import write_report
from .scenarios import load_scenarios
from .state import initial_state

app = typer.Typer(no_args_is_help=True)


@app.command("run-scenarios")
def run_scenarios(
    config: Annotated[Path, typer.Option("--config")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Run all grading scenarios and write metrics JSON."""
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    scenarios = load_scenarios(cfg["scenarios_path"])
    checkpointer = build_checkpointer(cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)
    metrics = []
    for scenario in scenarios:
        state = initial_state(scenario)
        run_config = {"configurable": {"thread_id": state["thread_id"]}}
        final_state = graph.invoke(state, config=run_config)
        metrics.append(metric_from_state(
            final_state,
            scenario.expected_route.value,
            scenario.requires_approval,
        ))
    report = summarize_metrics(metrics)
    write_metrics(report, output)
    if cfg.get("report_path"):
        write_report(report, cfg["report_path"])
    typer.echo(f"Wrote metrics to {output}")

    # --- Persistence evidence: show state history for first scenario ---
    first_thread = f"thread-{scenarios[0].id}"
    try:
        history = list(graph.get_state_history({"configurable": {"thread_id": first_thread}}))
        typer.echo(f"\n=== State history for {first_thread} ({len(history)} checkpoints) ===")
        for i, snapshot in enumerate(history[:5]):  # show up to 5 most recent
            node = snapshot.metadata.get("source", "unknown") if snapshot.metadata else "unknown"
            step = snapshot.metadata.get("step", "?") if snapshot.metadata else "?"
            route = snapshot.values.get('route', '')
            typer.echo(
                f"  [{i}] step={step} source={node}"
                f" route={route}"
            )
    except Exception:
        typer.echo("(State history not available with current checkpointer)")


@app.command("validate-metrics")
def validate_metrics(metrics: Annotated[Path, typer.Option("--metrics")]) -> None:
    """Validate metrics JSON schema for grading."""
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    report = MetricsReport.model_validate(payload)
    if report.total_scenarios < 6:
        raise typer.BadParameter("Expected at least 6 scenarios")
    typer.echo(f"Metrics valid. success_rate={report.success_rate:.2%}")


@app.command("export-diagram")
def export_diagram(
    output: Annotated[Path, typer.Option("--output")] = Path("outputs/graph.mermaid"),
) -> None:
    """Export graph architecture as a Mermaid diagram (bonus extension)."""
    graph = build_graph(checkpointer=None)
    mermaid_str = graph.get_graph().draw_mermaid()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(mermaid_str, encoding="utf-8")
    typer.echo(f"Mermaid diagram written to {output}")
    typer.echo("\n--- Mermaid Diagram ---")
    typer.echo(mermaid_str)


@app.command("show-state-history")
def show_state_history(
    config: Annotated[Path, typer.Option("--config")],
    scenario_id: Annotated[str, typer.Option("--scenario-id")] = "S01_simple",
) -> None:
    """Run one scenario and display full state history (bonus: time travel evidence)."""
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    scenarios = load_scenarios(cfg["scenarios_path"])
    target = next((s for s in scenarios if s.id == scenario_id), scenarios[0])

    checkpointer = build_checkpointer(cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)
    state = initial_state(target)
    run_config = {"configurable": {"thread_id": state["thread_id"]}}
    graph.invoke(state, config=run_config)

    # Retrieve full state history
    history = list(graph.get_state_history(run_config))
    typer.echo(f"\n=== State history for thread-{target.id} ({len(history)} checkpoints) ===\n")
    for i, snapshot in enumerate(history):
        meta = snapshot.metadata or {}
        typer.echo(f"Checkpoint [{i}]:")
        typer.echo(f"  step    = {meta.get('step', '?')}")
        typer.echo(f"  source  = {meta.get('source', '?')}")
        typer.echo(f"  route   = {snapshot.values.get('route', '')}")
        typer.echo(f"  attempt = {snapshot.values.get('attempt', 0)}")
        answer = snapshot.values.get("final_answer")
        if answer:
            typer.echo(f"  answer  = {answer[:80]}")
        typer.echo()

    # Save evidence to file
    evidence_path = Path("outputs/state_history_evidence.txt")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"State history for thread-{target.id} ({len(history)} checkpoints)\n"]
    for i, snapshot in enumerate(history):
        meta = snapshot.metadata or {}
        route = snapshot.values.get('route', '')
        attempt = snapshot.values.get('attempt', 0)
        lines.append(
            f"[{i}] step={meta.get('step','?')}"
            f" source={meta.get('source','?')}"
            f" route={route} attempt={attempt}"
        )
    evidence_path.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Evidence saved to {evidence_path}")


if __name__ == "__main__":
    app()

