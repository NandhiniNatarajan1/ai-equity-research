"""Research report endpoints.

  GET /research/report/{ticker}         -> JSON (structured report)
  GET /research/report/{ticker}.html    -> print-friendly HTML page

The HTML page is deliberately styled to look clean when printed to PDF via
the browser (`Ctrl+P -> Save as PDF`). This avoids pulling in a server-side
PDF renderer (weasyprint/cairo), which bloats the Docker image.
"""

from __future__ import annotations

import html as html_lib
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from app.agents.report_agent import ReportResult
from app.agents.report_cache import get_or_generate, invalidate
from app.core.logging import get_logger
from app.report_assets.sparkline import bar_chart, line_sparkline

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
        or datetime.now(tz=UTC).isoformat(),
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
        "price": None
        if r.specialists.price is None
        else {
            "ticker": r.specialists.price.ticker,
            "currency": r.specialists.price.currency,
            "last_price": r.specialists.price.last_price,
            "change_1d_pct": r.specialists.price.change_1d_pct,
            "change_1y_pct": r.specialists.price.change_1y_pct,
            "history_1y_closes": r.specialists.price.history_1y_closes,
        },
        "history": {
            k: {
                "name": v.name,
                "unit": v.unit,
                "points": [
                    {"fiscal_year": p.fiscal_year, "value": p.value, "end_date": p.end_date}
                    for p in v.points
                ],
            }
            for k, v in r.specialists.history.items()
        },
    }
    if cache_meta is not None:
        out["cache"] = cache_meta
    return out


# ---------------------------------------------------------------------------
# Dot-suffix routes (.html / .pdf) must be registered BEFORE the plain
# /{ticker} JSON route, otherwise the JSON route greedily matches
# "AMD.html" or "AMD.pdf" as the ticker.
# ---------------------------------------------------------------------------

try:
    from weasyprint import HTML as _WeasyHTML  # type: ignore

    _WEASY_OK = True
    _WEASY_ERR: str | None = None
except Exception as _weasy_exc:  # pragma: no cover - exercised only in degraded builds
    _WeasyHTML = None  # type: ignore
    _WEASY_OK = False
    _WEASY_ERR = str(_weasy_exc)
    log.warning("weasyprint_unavailable", error=_WEASY_ERR)


@router.get("/report/{ticker}/pdf")
def report_pdf(
    ticker: str,
    refresh: bool = Query(default=False, description="Bypass the report cache"),
    peers: str | None = Query(default=None),
) -> Response:
    if not _WEASY_OK:
        raise HTTPException(
            status_code=503,
            detail=(
                "PDF rendering unavailable in this build (WeasyPrint missing or "
                f"system deps absent). Use /research/report/{ticker}.html and "
                f"print to PDF from the browser instead. Underlying error: {_WEASY_ERR}"
            ),
        )
    try:
        res, meta = get_or_generate(ticker, force_refresh=refresh, peers=_parse_peers(peers))
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = _report_to_dict(res, cache_meta=meta)
    body = _markdown_to_html(result.get("report_markdown", ""))
    html = HTML_SHELL.format(
        ticker=html_lib.escape(result["ticker"]),
        generated_at=html_lib.escape(result["generated_at"]),
        fundamentals_html=_fundamentals_section(result),
        body_html=body,
        citations_rows=_citations_table(result),
        metrics_rows=_metrics_table(result),
    )
    try:
        pdf_bytes = _WeasyHTML(string=html).write_pdf()  # type: ignore[union-attr]
    except Exception as exc:  # pragma: no cover
        log.exception("pdf_render_failed", ticker=ticker, error=str(exc))
        raise HTTPException(status_code=500, detail=f"PDF render failed: {exc}") from exc

    filename = f"{result['ticker']}_research_report.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

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
  h3 {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 16px 0 6px; font-size: 14px; }}
  .meta {{ color: #666; font-size: 12px; font-family: -apple-system, Segoe UI, Roboto, sans-serif; }}
  .report p {{ margin: 10px 0; }}
  .report ul {{ margin: 10px 0 10px 20px; padding: 0; }}
  .report li {{ margin: 4px 0; }}
  .cite {{ display: inline-block; padding: 0 4px; margin: 0 2px; border-radius: 3px; border: 1px solid #c7d2fe; background: #eef2ff; color: #3730a3; font-size: 11px; font-family: -apple-system, Segoe UI, Roboto, sans-serif; }}
  .metric {{ display: inline-block; padding: 0 4px; margin: 0 2px; border-radius: 3px; border: 1px solid #a7f3d0; background: #ecfdf5; color: #065f46; font-size: 11px; font-family: ui-monospace, Menlo, monospace; }}
  .fundamentals {{ margin: 24px 0; padding: 14px 16px; border: 1px solid #e5e7eb; background: #fafafa; border-radius: 6px; font-family: -apple-system, Segoe UI, Roboto, sans-serif; font-size: 12px; }}
  .fundamentals h3 {{ margin-top: 0; }}
  .fund-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }}
  .fund-cell {{ background: white; border: 1px solid #eee; border-radius: 4px; padding: 8px 10px; }}
  .fund-cell .label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; margin-bottom: 2px; }}
  .fund-cell .value {{ font-family: ui-monospace, Menlo, monospace; font-size: 14px; font-weight: 600; color: #111; }}
  .fund-cell .sub {{ color: #6b7280; font-size: 11px; margin-top: 2px; }}
  .fund-cell svg {{ display: block; margin-top: 6px; }}
  .pos {{ color: #047857; }}
  .neg {{ color: #b91c1c; }}
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
{fundamentals_html}
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


def _fmt_usd(x: float) -> str:
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1e9:
        return f"{sign}${a / 1e9:,.2f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:,.2f}M"
    return f"{sign}${a:,.0f}"


def _fundamentals_section(result: dict[str, Any]) -> str:
    price = result.get("price")
    history = result.get("history") or {}
    if not price and not history:
        return ""

    cells: list[str] = []

    # Price snapshot cell
    if price:
        change = price.get("change_1y_pct")
        change_html = ""
        if change is not None:
            cls = "pos" if change >= 0 else "neg"
            change_html = f'<span class="{cls}">{change:+.2f}% 1Y</span>'
        spark = line_sparkline(price.get("history_1y_closes") or [], width=220, height=34)
        cells.append(
            f'<div class="fund-cell">'
            f'<div class="label">Last close ({html_lib.escape(price.get("currency", "USD"))})</div>'
            f'<div class="value">{price["last_price"]:,.2f}</div>'
            f'<div class="sub">{change_html}</div>'
            f"{spark}"
            f"</div>"
        )

    def _series_cell(key: str, label: str, is_pct: bool) -> str | None:
        series = history.get(key)
        if not series or not series.get("points"):
            return None
        pts = series["points"]
        values = [p["value"] for p in pts]
        labels_x = [f"FY{p['fiscal_year'] % 100:02d}" for p in pts]
        latest = pts[-1]
        if is_pct:
            latest_str = f"{latest['value']:.1f}%"
        else:
            latest_str = _fmt_usd(latest["value"])
        chart = bar_chart(values, labels_x, width=220, height=58)
        return (
            f'<div class="fund-cell">'
            f'<div class="label">{html_lib.escape(label)}</div>'
            f'<div class="value">{latest_str}</div>'
            f'<div class="sub">FY{latest["fiscal_year"]} • last {len(pts)} years</div>'
            f"{chart}"
            f"</div>"
        )

    for key, label, is_pct in [
        ("revenue", "Revenue", False),
        ("gross_margin", "Gross margin", True),
        ("operating_margin", "Operating margin", True),
        ("free_cash_flow", "Free cash flow", False),
    ]:
        cell = _series_cell(key, label, is_pct)
        if cell:
            cells.append(cell)

    if not cells:
        return ""

    return (
        '<div class="fundamentals">'
        '<h3>Fundamentals snapshot</h3>'
        f'<div class="fund-grid">{"".join(cells)}</div>'
        "</div>"
    )


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


def _parse_peers(peers: str | None) -> list[str] | None:
    if peers is None:
        return None
    tickers = [t.strip().upper() for t in peers.split(",") if t.strip()]
    return tickers or None


@router.get("/report/{ticker}.html", response_class=HTMLResponse)
def report_html(
    ticker: str,
    refresh: bool = Query(default=False, description="Bypass the report cache"),
    peers: str | None = Query(
        default=None,
        description=(
            "Optional comma-separated list of peer tickers for the Competitor "
            "section (e.g. 'NVDA,AMD'). Custom peer lists bypass the cache."
        ),
    ),
) -> HTMLResponse:
    try:
        res, meta = get_or_generate(ticker, force_refresh=refresh, peers=_parse_peers(peers))
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = _report_to_dict(res, cache_meta=meta)
    body = _markdown_to_html(result.get("report_markdown", ""))
    html = HTML_SHELL.format(
        ticker=html_lib.escape(result["ticker"]),
        generated_at=html_lib.escape(result["generated_at"]),
        fundamentals_html=_fundamentals_section(result),
        body_html=body,
        citations_rows=_citations_table(result),
        metrics_rows=_metrics_table(result),
    )
    return HTMLResponse(content=html)


@router.get("/report/{ticker}")
def report_json(
    ticker: str,
    refresh: bool = Query(default=False, description="Bypass the report cache"),
    peers: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        res, meta = get_or_generate(ticker, force_refresh=refresh, peers=_parse_peers(peers))
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _report_to_dict(res, cache_meta=meta)




@router.delete("/report/{ticker}")
def report_invalidate(ticker: str) -> dict[str, Any]:
    """Drop any cached reports for `ticker`. Next GET regenerates."""
    removed = invalidate(ticker)
    return {"ticker": ticker.upper(), "removed": removed}
