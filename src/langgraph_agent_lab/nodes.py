"""Node functions for the LangGraph workflow.

Each function should be small, testable, and return a partial state update. Avoid mutating the
input state in place.
"""

from __future__ import annotations

import re

from .state import AgentState, ApprovalDecision, Route, make_event

# ---------------------------------------------------------------------------
# Keyword sets for classify_node — checked against clean_words (word boundary)
# Priority order: risky > tool > missing_info > error > simple
# ---------------------------------------------------------------------------
_RISKY_KEYWORDS = {"refund", "delete", "send", "cancel", "remove", "revoke"}
_TOOL_KEYWORDS = {"status", "order", "lookup", "check", "track", "find", "search"}
_ERROR_KEYWORDS = {"timeout", "fail", "failure", "error", "crash", "unavailable"}


def intake_node(state: AgentState) -> dict:
    """Normalize raw query into state fields.

    Strips whitespace and lowercases for downstream matching.
    """
    query = state.get("query", "").strip()
    return {
        "query": query,
        "messages": [f"intake:{query[:80]}"],
        "events": [make_event("intake", "completed", "query normalized")],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using keyword-based heuristics.

    Priority: risky > tool > missing_info > error > simple (default).
    Uses word-boundary matching on cleaned words to avoid substring false positives.
    """
    query = state.get("query", "").lower()
    # Strip punctuation from each word for clean matching
    clean_words = set(re.findall(r"[a-z]+", query))

    route = Route.SIMPLE
    risk_level = "low"

    if clean_words & _RISKY_KEYWORDS:
        route = Route.RISKY
        risk_level = "high"
    elif clean_words & _TOOL_KEYWORDS:
        route = Route.TOOL
    elif len(query.split()) < 5 and "it" in clean_words:
        route = Route.MISSING_INFO
    elif clean_words & _ERROR_KEYWORDS:
        route = Route.ERROR

    return {
        "route": route.value,
        "risk_level": risk_level,
        "events": [make_event("classify", "completed", f"route={route.value}")],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating.

    Generates a context-aware clarification question from the original query.
    """
    original_query = state.get("query", "").strip()
    question = (
        f"Your request '{original_query}' is too vague. "
        "Could you please provide more details such as an order ID, "
        "account number, or a clearer description of the issue?"
    )
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [make_event("clarify", "completed", "missing information requested")],
    }


def tool_node(state: AgentState) -> dict:
    """Call a mock tool with idempotent execution.

    Simulates transient failures for error-route scenarios to demonstrate retry loops.
    Returns structured tool results.
    """
    attempt = int(state.get("attempt", 0))
    scenario_id = state.get("scenario_id", "unknown")

    if state.get("route") == Route.ERROR.value and attempt < 2:
        result = f"ERROR: transient failure attempt={attempt} scenario={scenario_id}"
    else:
        result = f"mock-tool-result for scenario={scenario_id}"

    return {
        "tool_results": [result],
        "events": [make_event("tool", "completed", f"tool executed attempt={attempt}")],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for approval with evidence and risk justification."""
    query = state.get("query", "")
    risk_level = state.get("risk_level", "unknown")
    proposed = (
        f"Proposed action for query: '{query}'. "
        f"Risk level: {risk_level}. "
        "This action may have irreversible side-effects. Approval required before execution."
    )
    return {
        "proposed_action": proposed,
        "events": [make_event("risky_action", "pending_approval", "approval required")],
    }


def approval_node(state: AgentState) -> dict:
    """Human approval step with optional LangGraph interrupt().

    Set LANGGRAPH_INTERRUPT=true to use real interrupt() for HITL demos.
    Default uses mock decision so tests and CI run offline.
    Supports reject decisions — rejected requests are routed to clarify.
    """
    import os

    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        value = interrupt({
            "proposed_action": state.get("proposed_action"),
            "risk_level": state.get("risk_level"),
        })
        if isinstance(value, dict):
            decision = ApprovalDecision(**value)
        else:
            decision = ApprovalDecision(approved=bool(value))
    else:
        decision = ApprovalDecision(approved=True, comment="mock approval for lab")

    return {
        "approval": decision.model_dump(),
        "events": [make_event("approval", "completed", f"approved={decision.approved}")],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt with bounded counter and backoff metadata."""
    attempt = int(state.get("attempt", 0)) + 1
    max_attempts = int(state.get("max_attempts", 3))
    backoff_ms = min(1000 * (2 ** (attempt - 1)), 30000)  # exponential backoff cap 30s

    errors = [f"transient failure attempt={attempt}"]
    return {
        "attempt": attempt,
        "errors": errors,
        "events": [make_event(
            "retry", "completed", "retry attempt recorded",
            attempt=attempt, max_attempts=max_attempts, backoff_ms=backoff_ms,
        )],
    }


def answer_node(state: AgentState) -> dict:
    """Produce a final response grounded in tool_results and approval context."""
    tool_results = state.get("tool_results") or []
    approval = state.get("approval")

    if tool_results:
        latest_result = tool_results[-1]
        if approval and approval.get("approved"):
            answer = f"[Approved] Action completed. Result: {latest_result}"
        else:
            answer = f"I found: {latest_result}"
    elif state.get("route") == Route.SIMPLE.value:
        answer = (
            "Thank you for your question. "
            "Here is the information you requested based on our knowledge base."
        )
    else:
        answer = "Your request has been processed."

    return {
        "final_answer": answer,
        "events": [make_event("answer", "completed", "answer generated")],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the 'done?' check that enables retry loops.

    Checks the latest tool result for error indicators.
    Returns evaluation_result: 'needs_retry' or 'success'.
    """
    tool_results = state.get("tool_results", [])
    latest = tool_results[-1] if tool_results else ""

    if "ERROR" in latest:
        return {
            "evaluation_result": "needs_retry",
            "events": [make_event(
                "evaluate", "completed",
                "tool result indicates failure, retry needed",
            )],
        }
    return {
        "evaluation_result": "success",
        "events": [make_event("evaluate", "completed", "tool result satisfactory")],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Log unresolvable failures for manual review.

    Third layer of error strategy: retry -> fallback -> dead letter.
    Persists failure details for downstream alerting and ticket creation.
    """
    attempt = state.get("attempt", 0)
    scenario_id = state.get("scenario_id", "unknown")
    dead_msg = (
        "Request could not be completed after maximum retry attempts. "
        "Logged for manual review."
    )
    return {
        "final_answer": dead_msg,
        "errors": [
            f"dead_letter: scenario={scenario_id} "
            f"exhausted after {attempt} attempts",
        ],
        "events": [make_event(
            "dead_letter", "completed",
            f"max retries exceeded, attempt={attempt}",
        )],
    }


def finalize_node(state: AgentState) -> dict:
    """Finalize the run and emit a final audit event."""
    return {"events": [make_event("finalize", "completed", "workflow finished")]}
