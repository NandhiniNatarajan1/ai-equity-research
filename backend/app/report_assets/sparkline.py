"""Minimal inline SVG sparkline + bar generators (no external deps).

Designed for embedding in the research report HTML. The output is a
self-contained <svg> element that renders in any browser or PDF printer.
"""

from __future__ import annotations


def _scale(values: list[float], out_min: float, out_max: float) -> list[float]:
    if not values:
        return []
    v_min, v_max = min(values), max(values)
    if v_min == v_max:
        mid = (out_min + out_max) / 2
        return [mid for _ in values]
    span = v_max - v_min
    out_span = out_max - out_min
    return [out_max - (v - v_min) / span * out_span for v in values]


def line_sparkline(
    values: list[float],
    *,
    width: int = 200,
    height: int = 40,
    stroke: str = "#2563eb",
    fill: str = "#dbeafe",
    pad: int = 2,
) -> str:
    """Return an inline <svg> rendering the sequence as a filled line sparkline."""
    if not values:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><text x="4" y="20" font-size="10" fill="#999">no data</text></svg>'
        )

    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    ys = _scale(values, pad, pad + inner_h)
    xs = (
        [pad + (i / (len(values) - 1)) * inner_w for i in range(len(values))]
        if len(values) > 1
        else [width / 2]
    )
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    # Closed fill path (back to the baseline).
    baseline_y = pad + inner_h
    fill_path = f"M{xs[0]:.1f},{baseline_y:.1f} L" + points + f" L{xs[-1]:.1f},{baseline_y:.1f} Z"
    last_x, last_y = xs[-1], ys[-1]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<path d="{fill_path}" fill="{fill}" opacity="0.5"/>'
        f'<polyline points="{points}" fill="none" stroke="{stroke}" stroke-width="1.5"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.2" fill="{stroke}"/>'
        f"</svg>"
    )


def bar_chart(
    values: list[float],
    labels: list[str],
    *,
    width: int = 240,
    height: int = 60,
    color: str = "#10b981",
    neg_color: str = "#ef4444",
    pad: int = 4,
    label_h: int = 12,
) -> str:
    """Vertical bars with text labels under each — compact enough for an inline chart."""
    if not values:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" />'

    assert len(values) == len(labels), "values/labels must align"
    n = len(values)
    plot_h = height - 2 * pad - label_h
    inner_w = width - 2 * pad
    bar_w = max(2.0, inner_w / n * 0.7)
    gap = (inner_w - bar_w * n) / max(n - 1, 1) if n > 1 else 0

    v_min = min(min(values), 0.0)
    v_max = max(max(values), 0.0)
    span = v_max - v_min if v_max > v_min else 1.0
    zero_y = pad + plot_h * (v_max / span) if span else pad + plot_h

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{width - pad}" y2="{zero_y:.1f}" '
        f'stroke="#d1d5db" stroke-width="0.5"/>',
    ]
    for i, (v, label) in enumerate(zip(values, labels)):
        x = pad + i * (bar_w + gap)
        value_fraction = abs(v) / span if span else 0.0
        bar_h = value_fraction * plot_h
        if v >= 0:
            y = zero_y - bar_h
            color_ = color
        else:
            y = zero_y
            color_ = neg_color
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color_}"/>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - pad / 2:.1f}" '
            f'font-size="9" text-anchor="middle" fill="#6b7280">{label}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
