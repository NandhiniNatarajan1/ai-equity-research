"""Research report endpoints.

  GET /research/report/{ticker}         -> JSON (structured report)
  GET /research/report/{ticker}.html    -> print-friendly HTML page

The HTML page is deliberately styled to look clean when printed to PDF via
the browser (`Ctrl+P -> Save as PDF`). This avoids pulling in a server-side
PDF renderer (weasyprint/cairo), which bloats the Docker image.
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.agents.report_agent import ReportResult
from app.agents.report_cache import get_or_generate, invalidate
from app.core.logging import get_logger

router = APIRouter(prefix="/research", tags=["report"])
log = get_logger("api.report")


def _report_to_dict(r: ReportResult, cache_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    def _specialist(name: str, state: Any) -> dict[str, Any]:
        if state is None:
            return {"available": False}
        if hasattr(state, "answer") and state.answer is not None:
            ans = state.answer
            return {
                "available": True,
                "answer_markdown": ans.answer_markdown,
                "citations": [
                    {
                        "marker": c.marker,
                        "chunk_id": c.chunk_id,
                        "quoted_text": c.quoted_text,
                    }
                    for c in ans.citations
                ],
            }
        # Financial agent has no .answer wrapper.
        return {
            "available": True,
            "answer_markdown": getattr(state, "answer_markdown", ""),
            "metrics": getattr(state, "metrics", []),
            "metric_markers": getattr(state, "metric_markers", []),
            "error": getattr(state, "error", None),
        }

    out: dict[str, Any] = {
        "ticker": r.ticker,
        "generated_at": (cache_meta or {}).get("generated_at")
        or datetime.now(tz=timezone.utc).isoformat(),
        "report_markdown": r.report_markdown,
        "specialists": {
            "business": _specialist("business", r.specialists.business),
            "financial": _specialist("financial", r.specialists.financial),
            "risk": _specialist("risk", r.specialists.risk),
            "competitor": _specialist("competitor", r.specialists.competitor),
        },
        "specialist_errors": r.specialists.errors,
        "all_citations": [
            {"marker": c.marker, "chunk_id": c.chunk_id, "quoted_text": c.quoted_text}
            for c in r.all_citations
        ],
        "financial_metrics": r.financial_metrics,
    }
    if cache_meta is not None:
        out["cache"] = cache_meta
    return out


# ---------------------------------------------------------------------------
# Print-friendly HTML (user hits Ctrl+P -> Save as PDF).
# NOTE: this route must be registered BEFORE the plain {ticker} JSON route,
# otherwise the JSON route greedily matches "AMD.html" as the ticker.
# ---------------------------------------------------------------------------

HTML_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{ticker} Research Report</title>
<style>
  @page {{ margin: 0.75in; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: white; color: #111; font-family: Georgia, serif; }}
  body {{ max-width: 7.5in; margin: 0 auto; padding: 24px; line-height: 1.5; }}
  h1 {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0 0 4px; }}
  h2 {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  .meta {{ color: #666; font-size: 12px; font-family: -apple-system, Segoe UI, Roboto, sans-serif; }}
  .report p {{ margin: 10px 0; }}
  .report ul {{ margin: 10px 0 10px 20px; padding: 0; }}
  .report li {{ margin: 4px 0; }}
  .cite {{ display: inline-block; padding: 0 4px; margin: 0 2px; border-radius: 3px; border: 1px solid #c7d2fe; background: #eef2ff; color: #3730a3; font-size: 11px; font-family: -apple-system, Segoe UI, Roboto, sans-serif; }}
  .metric {{ display: inline-block; padding: 0 4px; margin: 0 2px; border-radius: 3px; border: 1px solid #a7f3d0; background: #ecfdf5; color: #065f46; font-size: 11px; font-family: ui-monospace, Menlo, monospace; }}
  details.sources {{ margin-top: 24px; font-size: 12px; }}
  details.sources summary {{ cursor: pointer; font-weight: bold; font-family: -apple-system, Segoe UI, Roboto, sans-serif; }}
  details.sources table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 11px; font-family: ui-monospace, Menlo, monospace; }}
  details.sources th, details.sources td {{ border: 1px solid #e5e7eb; padding: 4px 6px; text-align: left; vertical-align: top; }}
  details.sources th {{ background: #f9fafb; }}
  blockquote {{ margin: 4px 0 8px; padding-left: 10px; border-left: 2px solid #ccc; color: #333; font-size: 12px; }}
  .print-hint {{ margin: 0 0 20px; padding: 10px 12px; border: 1px dashed #94a3b8; background: #f8fafc; color: #475569; font-size: 12px; font-family: -apple-system, Segoe UI, Roboto, sans-serif; }}
  @media print {{ .print-hint {{ display: none; }} }}
</style>
</head>
<body>
<p class="print-hint">Press <strong>Ctrl+P</strong> (or Cmd+P) and choose <strong>Save as PDF</strong> to download this report.</p>
<h1>{ticker} Research Report</h1>
<p class="meta">Generated {generated_at}</p>
<div class="report">{body_html}</div>
<details class="sources" open>
  <summary>Sources</summary>
  <h3>Filing citations</h3>
  <table>
    <thead><tr><th>Marker</th><th>Quote</th><th>Chunk ID</th></tr></thead>
    <tbody>{citations_rows}</tbody>
  </table>
  <h3>Deterministic metrics</h3>
  <table>
    <thead><tr><th>Metric</th><th>Value</th><th>Period</th><th>XBRL inputs</th></tr></thead>
    <tbody>{metrics_rows}</tbody>
  </table>
</details>
</body>
</html>
"""


def _markdown_to_html(md: str) -> str:
    """Lightweight markdown -> HTML (headings, lists, paragraphs, bold, citations)."""
    import re

    out: list[str] = []
    in_list = False
    in_para_lines: list[str] = []

    def _flush_para() -> None:
        nonlocal in_para_lines
        if not in_para_lines:
            return
        line = " ".join(in_para_lines).strip()
        if line:
            out.append(f"<p>{_inline(line)}</p>")
        in_para_lines = []

    def _inline(s: str) -> str:
        # bold **text**
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        # textual citation [1], [12], NVDA [1]
        s = re.sub(
            r"(?:([A-Z]{1,5})\s+)?\[(\d+)\]",
            lambda m: f'<span class="cite">{(m.group(1) + " ") if m.group(1) else ""}[{m.group(2)}]</span>',
            s,
        )
        # metric marker [metric: name]
        s = re.sub(
            r"\[metric:\s*([a-z0-9_]+)\]",
            r'<span class="metric">[\1]</span>',
            s,
        )
        return s

    for raw_line in md.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()
        if not stripped:
            _flush_para()
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("## "):
            _flush_para()
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{html_lib.escape(stripped[3:])}</h2>")
            continue
        if stripped.startswith("# "):
            _flush_para()
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{html_lib.escape(stripped[2:])}</h1>")
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            _flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        in_para_lines.append(stripped)

    _flush_para()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _citations_table(result: dict[str, Any]) -> str:
    rows = []
    for c in result.get("all_citations", []):
        rows.append(
            "<tr>"
            f"<td>{html_lib.escape(c['marker'])}</td>"
            f"<td><blockquote>{html_lib.escape(c['quoted_text'])}</blockquote></td>"
            f"<td>{html_lib.escape(c['chunk_id'])}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="3">(none)</td></tr>'


def _metrics_table(result: dict[str, Any]) -> str:
    rows = []
    for m in result.get("financial_metrics", []):
        inputs = "<br>".join(
            f"{html_lib.escape(i['concept'])}: {i['value']:,.0f} ({i['form']} {i['accession']}, filed {i['filed']})"
            for i in m.get("inputs", [])
        )
        rows.append(
            "<tr>"
            f"<td>{html_lib.escape(m['name'])}</td>"
            f"<td>{m['value']} {html_lib.escape(m['unit'])}</td>"
            f"<td>{html_lib.escape(m['period_label'])}</td>"
            f"<td>{inputs}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="4">(none)</td></tr>'


@router.get("/report/{ticker}.html", response_class=HTMLResponse)
def report_html(
    ticker: str,
    refresh: bool = Query(default=False, description="Bypass the report cache"),
) -> HTMLResponse:
    try:
        res, meta = get_or_generate(ticker, force_refresh=refresh)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = _report_to_dict(res, cache_meta=meta)
    body = _markdown_to_html(result.get("report_markdown", ""))
    html = HTML_SHELL.format(
        ticker=html_lib.escape(result["ticker"]),
        generated_at=html_lib.escape(result["generated_at"]),
        body_html=body,
        citations_rows=_citations_table(result),
        metrics_rows=_metrics_table(result),
    )
    return HTMLResponse(content=html)


@router.get("/report/{ticker}")
def report_json(
    ticker: str,
    refresh: bool = Query(default=False, description="Bypass the report cache"),
) -> dict[str, Any]:
    try:
        res, meta = get_or_generate(ticker, force_refresh=refresh)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _report_to_dict(res, cache_meta=meta)


@router.delete("/report/{ticker}")
def report_invalidate(ticker: str) -> dict[str, Any]:
    """Drop any cached reports for `ticker`. Next GET regenerates."""
    removed = invalidate(ticker)
    return {"ticker": ticker.upper(), "removed": removed}
