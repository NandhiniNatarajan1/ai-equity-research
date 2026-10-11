"""Sparkline SVG generator tests (no deps, no network)."""

from __future__ import annotations

import re

from app.report_assets.sparkline import bar_chart, line_sparkline


def test_line_sparkline_with_data_produces_svg_polyline() -> None:
    svg = line_sparkline([1.0, 2.5, 2.0, 3.0, 5.0], width=120, height=24)
    assert svg.startswith("<svg")
    assert "polyline" in svg
    assert 'viewBox="0 0 120 24"' in svg
    # Count the points on the polyline — should equal input length.
    m = re.search(r'<polyline points="([^"]+)"', svg)
    assert m
    assert len(m.group(1).split()) == 5


def test_line_sparkline_empty_renders_placeholder() -> None:
    svg = line_sparkline([])
    assert "no data" in svg
    assert "<svg" in svg


def test_line_sparkline_constant_series_doesnt_crash() -> None:
    """Flat series would divide by zero if _scale wasn't guarded."""
    svg = line_sparkline([5.0, 5.0, 5.0])
    assert "polyline" in svg


def test_bar_chart_mixed_signs_colors_correctly() -> None:
    svg = bar_chart([10.0, -2.0, 5.0], ["FY23", "FY24", "FY25"])
    assert svg.count("<rect") == 3
    assert "FY23" in svg
    assert "#10b981" in svg  # positive color
    assert "#ef4444" in svg  # negative color (because of -2.0)


def test_bar_chart_all_positive_omits_negative_color() -> None:
    svg = bar_chart([1.0, 2.0, 3.0], ["a", "b", "c"])
    assert "#10b981" in svg
    assert "#ef4444" not in svg
