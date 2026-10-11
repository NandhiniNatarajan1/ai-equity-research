"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import filings, research
from app.core.logging import configure_logging, get_logger
from app.core.tracing import configure_tracing


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    traced = configure_tracing()
    log = get_logger("app.startup")
    log.info("startup", tracing_enabled=traced)
    yield


app = FastAPI(
    title="AI Equity Research API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(research.router)
app.include_router(filings.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
