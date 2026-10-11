"""Section parser unit tests over a committed fixture."""

from __future__ import annotations

from app.ingestion.section_parser import ITEM_TITLES, html_to_text, parse_sections


def test_html_to_text_strips_markup(mini_10k_html: bytes) -> None:
    text = html_to_text(mini_10k_html)
    assert "<p>" not in text
    assert "<b>" not in text
    assert "Risk Factors" in text


def test_parse_sections_finds_items_1_1a_7(mini_10k_html: bytes) -> None:
    sections = parse_sections(mini_10k_html)
    codes = [s.item_code for s in sections]
    assert codes == sorted(codes, key=lambda c: list(ITEM_TITLES).index(c))
    assert "1" in codes
    assert "1A" in codes
    assert "7" in codes


def test_parse_sections_skips_table_of_contents(mini_10k_html: bytes) -> None:
    """The TOC entries have tiny bodies; dedup should keep the real sections."""
    sections = parse_sections(mini_10k_html)
    for s in sections:
        # Every retained section must contain real prose, not just a TOC line.
        assert s.char_count >= 100


def test_parse_sections_assigns_titles(mini_10k_html: bytes) -> None:
    sections_by_code = {s.item_code: s for s in parse_sections(mini_10k_html)}
    assert sections_by_code["1"].title == "Business"
    assert sections_by_code["1A"].title == "Risk Factors"
    assert "Management" in sections_by_code["7"].title


def test_parse_sections_content_boundaries(mini_10k_html: bytes) -> None:
    sections_by_code = {s.item_code: s for s in parse_sections(mini_10k_html)}
    risk = sections_by_code["1A"].raw_text
    assert "Export controls" in risk
    # Item 7 content must not leak into Item 1A.
    assert "Revenue for fiscal year" not in risk
