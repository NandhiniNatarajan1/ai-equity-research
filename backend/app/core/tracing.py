"""LangSmith tracing bootstrap.

Reads LangSmith settings from env and exports them to the environment variables
that LangChain / LangGraph consult at import time. Safe to call multiple times.
"""

from __future__ import annotations

import os

from app.core.config import get_settings


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
