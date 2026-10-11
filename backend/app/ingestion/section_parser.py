"""Section-aware parser for 10-K filings.

Strategy:
  1. HTML -> plain text with BeautifulSoup (iXBRL and plain HTML both OK).
  2. Primary: regex-scan for "Item 1A."-style inline headings and keep the
     occurrence with the longest body per Item code (dedup against TOC).
  3. Fallback (when fewer than MIN_SECTIONS Items produce real bodies —
     common with filings that use a back-of-document cross-reference index
     and Title Case section titles only, e.g. Intel): emit the entire body
     as a single pseudo-section with item_code="FULL". Retrieval still works;
     per-Item citation labels are lost until a smarter parser lands.

The output preserves plain-text char offsets so downstream chunking can
record char_start / char_end back into the section's raw_text.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# iXBRL filings trigger this warning; the fallback is correct text extraction.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

MIN_SECTION_BODY_CHARS = 100
MIN_ITEM_SECTIONS = 5  # fallback to full-body if fewer real sections survive

# Canonical 10-K Item codes and the human-readable titles we attach.
# (Not exhaustive — covers everything RAG users typically ask about.)
ITEM_TITLES: dict[str, str] = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "Reserved",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Disclosure Regarding Foreign Jurisdictions",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}

ITEM_ORDER = list(ITEM_TITLES.keys())
ITEM_ORDER_INDEX = {code: i for i, code in enumerate(ITEM_ORDER)}

# Pseudo-section used by the fallback path when per-Item parsing fails.
FULL_BODY_CODE = "FULL"
FULL_BODY_TITLE = "Full 10-K Body"

# Matches "Item 1A", "ITEM  1A.", "Item 1A — Risk Factors", etc. at the start
# of a line (we normalize to one-item-per-line text before scanning).
_HEADING_RE = re.compile(
    r"^\s*ITEM\s+(?P<code>\d{1,2}[A-C]?)\s*[\.\-–—:]?\s*(?P<title>[^\n]*)$",
    re.IGNORECASE | re.MULTILINE,
)

# Blocks that always add noise.
_NOISE_TAGS = {"script", "style", "ix:header", "noscript"}


@dataclass(frozen=True)
class ParsedSection:
    item_code: str
    title: str
    order_index: int
    raw_text: str
    char_count: int


def html_to_text(html_bytes: bytes | str) -> str:
    """Convert 10-K HTML to normalized plain text."""
    soup = BeautifulSoup(html_bytes, "lxml")
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()
    # Keep paragraph structure.
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4"]):
        block.append("\n")
    text = soup.get_text()
    # Collapse horizontal whitespace within lines; drop empty lines run.
    lines = [re.sub(r"[\t\xa0 ]+", " ", ln).strip() for ln in text.splitlines()]
    cleaned = "\n".join(ln for ln in lines if ln)
    return cleaned


def _normalize_code(code: str) -> str:
    return code.upper()


def parse_sections(html_bytes: bytes | str) -> list[ParsedSection]:
    text = html_to_text(html_bytes)
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return []

    # Build candidate (code, start, end) spans.
    candidates: list[tuple[str, int, int, str]] = []
    for i, m in enumerate(matches):
        code = _normalize_code(m.group("code"))
        if code not in ITEM_TITLES:
            continue
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        candidates.append((code, body_start, body_end, body))

    # Dedup: for each item code, keep the occurrence with the longest body
    # (this filters out the table-of-contents heading, which has ~zero body).
    best: dict[str, tuple[str, int, int, str]] = {}
    for cand in candidates:
        code, _, _, body = cand
        prev = best.get(code)
        if prev is None or len(body) > len(prev[3]):
            best[code] = cand

    sections: list[ParsedSection] = []
    for code, (_, _, _, body) in best.items():
        if len(body) < MIN_SECTION_BODY_CHARS:
            # Guard against TOC-only matches when a filing lacks a real body.
            continue
        sections.append(
            ParsedSection(
                item_code=code,
                title=ITEM_TITLES[code],
                order_index=ITEM_ORDER_INDEX[code],
                raw_text=body,
                char_count=len(body),
            )
        )

    if len(sections) < MIN_ITEM_SECTIONS:
        # Fallback: filings like Intel's that use a back-of-document
        # cross-reference index won't yield enough real Items.
        # Keep the whole body as one pseudo-section so retrieval still works.
        if text.strip():
            return [
                ParsedSection(
                    item_code=FULL_BODY_CODE,
                    title=FULL_BODY_TITLE,
                    order_index=0,
                    raw_text=text,
                    char_count=len(text),
                )
            ]
        return []

    sections.sort(key=lambda s: s.order_index)
    return sections
