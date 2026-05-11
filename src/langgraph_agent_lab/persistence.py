"""Checkpointer adapter."""

from __future__ import annotations

from typing import Any


def build_checkpointer(
    kind: str = "memory",
    database_url: str | None = None,
) -> Any | None:  # noqa: ANN401
    """Return a LangGraph checkpointer.

    Supported kinds:
      - 'none'     → no persistence
      - 'memory'   → MemorySaver (in-process, for dev/test)
      - 'sqlite'   → SqliteSaver with WAL mode (for crash recovery demos)
      - 'postgres'  → PostgresSaver (production)
    """
    if kind == "none":
        return None
    if kind == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    if kind == "sqlite":
        try:
            import sqlite3

            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            msg = (
                "SQLite checkpointer requires: "
                "pip install langgraph-checkpoint-sqlite"
            )
            raise RuntimeError(msg) from exc
        conn = sqlite3.connect(database_url or "checkpoints.db", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        return SqliteSaver(conn)
    if kind == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            msg = (
                "Postgres checkpointer requires: "
                "pip install langgraph-checkpoint-postgres"
            )
            raise RuntimeError(msg) from exc
        return PostgresSaver.from_conn_string(database_url or "")
    raise ValueError(f"Unknown checkpointer kind: {kind}")
