"""LangSmith tracing bootstrap.

Reads LangSmith settings from env and exports them to the environment variables
that LangChain / LangGraph consult at import time. Safe to call multiple times.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("core.tracing")


def configure_tracing() -> bool:
    settings = get_settings()
    key = settings.langsmith_api_key.get_secret_value()
    if not (settings.langchain_tracing_v2 and key):
        return False
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint
    os.environ["LANGCHAIN_API_KEY"] = key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    return True


class TraceCapture:
    """Context manager that captures the LangSmith trace URL for a block.

    Usage:
        with TraceCapture() as cap:
            run_agent(...)
        if cap.trace_url:
            persist(cap.trace_url)
    """

    def __init__(self) -> None:
        self.trace_url: str | None = None
        self._cm = None
        self._cb = None

    def __enter__(self) -> "TraceCapture":
        if not get_settings().langchain_tracing_v2:
            return self
        try:
            from langchain_core.tracers.context import collect_runs
        except Exception:
            return self
        self._cm = collect_runs()
        self._cb = self._cm.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._cm is None:
            return
        try:
            self._cm.__exit__(exc_type, exc, tb)
        except Exception:
            pass
        try:
            runs = list(self._cb.traced_runs or []) if self._cb is not None else []
            if not runs:
                return
            from langsmith import Client

            client = Client()
            self.trace_url = client.get_run_url(
                run=runs[0], project_name=get_settings().langsmith_project
            )
        except Exception as exc:
            log.warning("trace_url_fail", error=str(exc))


@contextmanager
def capture_trace() -> Iterator[TraceCapture]:
    """Convenience generator wrapper."""
    cap = TraceCapture()
    cap.__enter__()
    try:
        yield cap
    finally:
        cap.__exit__(None, None, None)
