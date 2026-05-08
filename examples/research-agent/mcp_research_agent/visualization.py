"""Pure-Python SVG chart generation for research visualizations.

No external dependencies — SVG is generated as XML and returned base64-encoded
so it can be embedded directly in an MCP ImageContent block.
"""

import base64
import html
import re


def extract_metrics(text: str) -> dict[str, float]:
    """Extract labelled numeric metrics from research text.

    Recognises patterns like "Market size: $4.5B", "Growth rate: 12%",
    "Users: 1.2M" and returns a dict suitable for charting.
    """
    metrics: dict[str, float] = {}
    # Match "Label: [$]number[unit]" — label starts with a capital letter
    pattern = (
        r"([A-Z][a-zA-Z\s\-]{2,25}?):\s*"
        r"\$?([\d,]+(?:\.\d+)?)\s*"
        r"(%|B|M|K|billion|million|thousand)?\b"
    )
    for match in re.finditer(pattern, text):
        label = match.group(1).strip()
        value_str = match.group(2).replace(",", "")
        unit = (match.group(3) or "").lower()

        try:
            value = float(value_str)
        except ValueError:
            continue

        if unit in ("b", "billion"):
            metrics[f"{label[:18]} ($B)"] = value
        elif unit in ("m", "million"):
            metrics[f"{label[:18]} ($M)"] = value
        elif unit == "%":
            metrics[f"{label[:18]} (%)"] = value
        elif unit in ("k", "thousand"):
            metrics[f"{label[:18]} (K)"] = value
        else:
            metrics[label[:24]] = value

        if len(metrics) >= 6:
            break

    return metrics


def generate_bar_chart(
    data: dict[str, float],
    title: str = "Research Findings",
    width: int = 640,
    height: int = 400,
) -> str:
    """Generate a bar chart and return it as a base64-encoded SVG string.

    Args:
        data: Mapping of label → numeric value.
        title: Chart title displayed at the top.
        width: SVG canvas width in pixels.
        height: SVG canvas height in pixels.

    Returns:
        Base64-encoded UTF-8 SVG string (mimeType ``image/svg+xml``).
    """
    if not data:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<rect width="{width}" height="{height}" fill="#f8f9fa"/>'
            f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
            f'font-family="Arial" font-size="14" fill="#666">No data to visualize</text>'
            "</svg>"
        )
        return base64.b64encode(svg.encode()).decode()

    pad = 60
    title_h = 40
    chart_w = width - 2 * pad
    chart_h = height - 2 * pad - title_h

    max_val = max(data.values()) or 1.0
    n = len(data)
    slot_w = chart_w / n
    bar_w = slot_w * 0.65
    colors = ["#4285f4", "#34a853", "#fbbc04", "#ea4335", "#9c27b0", "#00bcd4"]

    rects: list[str] = []
    value_labels: list[str] = []
    x_labels: list[str] = []

    for i, (key, val) in enumerate(data.items()):
        bar_h = (val / max_val) * chart_h
        x = pad + i * slot_w + (slot_w - bar_w) / 2
        y = pad + title_h + chart_h - bar_h
        color = colors[i % len(colors)]

        rects.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}" rx="3"/>')
        value_labels.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle" '
            f'font-family="Arial" font-size="10" fill="#333">{val:.1f}</text>'
        )
        short = html.escape(key[:14]) + ("…" if len(key) > 14 else "")
        x_labels.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - pad + 16:.1f}" '
            f'text-anchor="middle" font-family="Arial" font-size="10" fill="#555">'
            f"{short}</text>"
        )

    baseline_y = pad + title_h + chart_h
    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<rect width="{width}" height="{height}" fill="#fff" stroke="#e0e0e0" stroke-width="1"/>',
        f'<text x="{width // 2}" y="{pad + 24}" text-anchor="middle" font-family="Arial" '
        f'font-size="15" font-weight="bold" fill="#333">{html.escape(title[:60])}</text>',
        f'<line x1="{pad}" y1="{pad + title_h}" x2="{pad}" y2="{baseline_y}" stroke="#ccc" stroke-width="1"/>',
        f'<line x1="{pad}" y1="{baseline_y}" x2="{width - pad}" y2="{baseline_y}" stroke="#ccc" stroke-width="1"/>',
        *rects,
        *value_labels,
        *x_labels,
        "</svg>",
    ]
    return base64.b64encode("\n".join(svg_lines).encode()).decode()
