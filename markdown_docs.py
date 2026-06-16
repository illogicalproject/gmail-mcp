"""Markdown -> Google Docs rendering for the multi-account MCP server.

The Docs API has no markdown import. This module converts a useful subset of
Markdown into Docs `batchUpdate` requests so headings, bold/italic/code, links,
bullet & numbered lists, blockquotes, and tables render as real Docs formatting
instead of flat text.

Design
------
Text content (everything except tables) is inserted in a SINGLE `insertText`
call, then styled with requests that do not change document length
(`updateParagraphStyle`, `updateTextStyle`, `createParagraphBullets`). Because
those styling requests never shift indices, all offsets can be precomputed
against the inserted string -- this is what makes the index math reliable.

Tables are structural and cannot be created with `insertText`, so a document is
rendered as a sequence of segments (text run, table, text run, ...). Each
segment is applied with its own `batchUpdate`, re-reading the document's end
index between segments so we never compute across a structural change.

Public entry points are the three functions used by gdocs.py:
    render_markdown(service, document_id, markdown, start_index=None)
    document_end_index(service, document_id)
    clear_body(service, document_id)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Monospace family used for `inline code` and ``` fenced ``` blocks.
_MONO_FONT = "Roboto Mono"

_HEADING_STYLES = {
    1: "HEADING_1",
    2: "HEADING_2",
    3: "HEADING_3",
    4: "HEADING_4",
    5: "HEADING_5",
    6: "HEADING_6",
}


# ---------------------------------------------------------------------------
# Block model
# ---------------------------------------------------------------------------


class Block:
    """A single rendered paragraph (heading, normal, list item, quote, code)."""

    __slots__ = ("text", "style", "heading", "list_kind", "nesting", "mono")

    def __init__(
        self,
        text: str,
        style: str = "NORMAL_TEXT",
        heading: int = 0,
        list_kind: Optional[str] = None,  # "bullet" | "ordered" | None
        nesting: int = 0,
        mono: bool = False,
    ):
        self.text = text
        self.style = style
        self.heading = heading
        self.list_kind = list_kind
        self.nesting = nesting
        self.mono = mono


# ---------------------------------------------------------------------------
# Inline parsing: **bold**, *italic* / _italic_, `code`, [text](url)
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def parse_inline(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Return (plain_text, spans). Each span is a dict with char offsets
    relative to plain_text and style flags: bold, italic, code, link."""
    spans: List[Dict[str, Any]] = []
    out: List[str] = []
    i = 0
    n = len(text)
    bold = italic = False

    def cur() -> int:
        return sum(len(s) for s in out)

    open_bold = 0
    open_italic = 0

    while i < n:
        # Links: [text](url)
        m = _LINK_RE.match(text, i)
        if m:
            label, url = m.group(1), m.group(2)
            start = cur()
            # Inline styles inside link labels are uncommon; keep label literal.
            out.append(label)
            spans.append(
                {
                    "start": start,
                    "end": start + len(label),
                    "bold": bold,
                    "italic": italic,
                    "code": False,
                    "link": url,
                }
            )
            i = m.end()
            continue

        ch = text[i]

        # Inline code `...`
        if ch == "`":
            j = text.find("`", i + 1)
            if j != -1:
                code_text = text[i + 1 : j]
                start = cur()
                out.append(code_text)
                spans.append(
                    {
                        "start": start,
                        "end": start + len(code_text),
                        "bold": bold,
                        "italic": italic,
                        "code": True,
                        "link": None,
                    }
                )
                i = j + 1
                continue

        # Bold ** or __
        if text.startswith("**", i) or text.startswith("__", i):
            if bold:
                _emit_style(spans, open_bold, cur(), "bold", bold, italic)
                bold = False
            else:
                bold = True
                open_bold = cur()
            i += 2
            continue

        # Italic * or _
        if ch in "*_":
            if italic:
                _emit_style(spans, open_italic, cur(), "italic", bold, italic)
                italic = False
            else:
                italic = True
                open_italic = cur()
            i += 1
            continue

        out.append(ch)
        i += 1

    # Close any dangling emphasis at end of string.
    if bold:
        _emit_style(spans, open_bold, cur(), "bold", True, italic)
    if italic:
        _emit_style(spans, open_italic, cur(), "italic", bold, True)

    return "".join(out), _merge_spans(spans)


def _emit_style(spans, start, end, kind, bold, italic):
    if end > start:
        spans.append(
            {
                "start": start,
                "end": end,
                "bold": kind == "bold",
                "italic": kind == "italic",
                "code": False,
                "link": None,
            }
        )


def _merge_spans(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only spans that actually carry style, sorted by start."""
    keep = [
        s
        for s in spans
        if s["bold"] or s["italic"] or s["code"] or s["link"]
    ]
    keep.sort(key=lambda s: (s["start"], s["end"]))
    return keep


# ---------------------------------------------------------------------------
# Block parsing
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_HR_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$")


def _nesting_from_indent(indent: str) -> int:
    # Treat a tab or every two/four spaces as one nesting level.
    spaces = indent.replace("\t", "    ")
    return min(len(spaces) // 2, 8)


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") or ("|" in s and not _HR_RE.match(line))


# ---------------------------------------------------------------------------
# Segmentation: split markdown into ("text", lines) and ("table", lines)
# ---------------------------------------------------------------------------


def segment_markdown(markdown: str) -> List[Tuple[str, List[str]]]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: List[Tuple[str, List[str]]] = []
    buf: List[str] = []
    i = 0
    n = len(lines)

    def flush_text():
        if buf:
            segments.append(("text", buf.copy()))
            buf.clear()

    in_fence = False
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            in_fence = not in_fence
            buf.append(line)
            i += 1
            continue

        # A table needs a header row followed by a separator row.
        if (
            not in_fence
            and i + 1 < n
            and _is_table_row(line)
            and _TABLE_SEP_RE.match(lines[i + 1])
        ):
            flush_text()
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < n and _is_table_row(lines[i]) and lines[i].strip():
                table_lines.append(lines[i])
                i += 1
            segments.append(("table", table_lines))
            continue

        buf.append(line)
        i += 1

    flush_text()
    return segments


# ---------------------------------------------------------------------------
# Text segment -> blocks
# ---------------------------------------------------------------------------


def parse_text_blocks(lines: List[str]) -> List[Block]:
    blocks: List[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            i += 1
            code_lines: List[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            for cl in code_lines:
                blocks.append(Block(cl, style="NORMAL_TEXT", mono=True))
            continue

        if not stripped:
            i += 1
            continue

        if _HR_RE.match(line):
            blocks.append(Block("", style="NORMAL_TEXT"))
            i += 1
            continue

        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            blocks.append(Block(m.group(2).strip(), heading=level))
            i += 1
            continue

        m = _BULLET_RE.match(line)
        if m:
            blocks.append(
                Block(
                    m.group(2).strip(),
                    list_kind="bullet",
                    nesting=_nesting_from_indent(m.group(1)),
                )
            )
            i += 1
            continue

        m = _ORDERED_RE.match(line)
        if m:
            blocks.append(
                Block(
                    m.group(2).strip(),
                    list_kind="ordered",
                    nesting=_nesting_from_indent(m.group(1)),
                )
            )
            i += 1
            continue

        m = _QUOTE_RE.match(line)
        if m:
            blocks.append(Block(m.group(1).strip(), style="QUOTE"))
            i += 1
            continue

        blocks.append(Block(stripped))
        i += 1

    return blocks


# ---------------------------------------------------------------------------
# Blocks -> (insert_text, requests) at a base index
# ---------------------------------------------------------------------------


def build_text_requests(
    blocks: List[Block], base_index: int
) -> Tuple[str, List[Dict[str, Any]], int]:
    """Return (text_to_insert, styling_requests, new_end_index).

    For each block we prepend nesting tabs (used by createParagraphBullets to
    derive list level), append the paragraph text, then a newline. Styling
    requests reference absolute indices computed against the inserted string.
    """
    pieces: List[str] = []
    style_requests: List[Dict[str, Any]] = []
    bullet_runs: List[Dict[str, Any]] = []  # {start, end, kind}

    cursor = base_index
    run_start: Optional[int] = None
    run_kind: Optional[str] = None

    def close_run(end_idx: int):
        nonlocal run_start, run_kind
        if run_start is not None and run_kind is not None:
            bullet_runs.append({"start": run_start, "end": end_idx, "kind": run_kind})
        run_start = None
        run_kind = None

    for blk in blocks:
        tabs = "\t" * blk.nesting if blk.list_kind else ""
        # Mono (code) blocks are inserted verbatim; everything else is parsed
        # for inline styles so the literal markers (**, *, `, []()) don't show.
        if blk.mono:
            display, spans = blk.text, []
        else:
            display, spans = parse_inline(blk.text)

        para_text = tabs + display
        para_start = cursor
        text_start = cursor + len(tabs)

        pieces.append(para_text + "\n")
        cursor += len(para_text) + 1  # +1 for newline
        para_end = cursor  # index just past the newline

        # Paragraph-level style (headings, quote)
        if blk.heading:
            style_requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": para_start, "endIndex": para_end},
                        "paragraphStyle": {
                            "namedStyleType": _HEADING_STYLES[blk.heading]
                        },
                        "fields": "namedStyleType",
                    }
                }
            )
        elif blk.style == "QUOTE":
            style_requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": para_start, "endIndex": para_end},
                        "paragraphStyle": {
                            "indentStart": {"magnitude": 36, "unit": "PT"},
                            "indentFirstLine": {"magnitude": 36, "unit": "PT"},
                        },
                        "fields": "indentStart,indentFirstLine",
                    }
                }
            )

        # Inline text styling
        if blk.mono:
            if display:
                style_requests.append(_mono_request(text_start, text_start + len(display)))
        else:
            for sp in spans:
                style_requests.append(
                    _text_style_request(
                        text_start + sp["start"],
                        text_start + sp["end"],
                        sp,
                    )
                )
        # Quote text is italicised for visual distinction.
        if blk.style == "QUOTE" and display:
            style_requests.append(
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": text_start,
                            "endIndex": text_start + len(display),
                        },
                        "textStyle": {"italic": True},
                        "fields": "italic",
                    }
                }
            )

        # Track contiguous list runs for createParagraphBullets
        if blk.list_kind:
            if run_kind == blk.list_kind:
                pass  # extend current run
            else:
                close_run(para_start)
                run_start = para_start
                run_kind = blk.list_kind
        else:
            close_run(para_start)

    close_run(cursor)

    # Bullets must be applied after text styling; they do not change length.
    for run in bullet_runs:
        preset = (
            "NUMBERED_DECIMAL_ALPHA_ROMAN"
            if run["kind"] == "ordered"
            else "BULLET_DISC_CIRCLE_SQUARE"
        )
        style_requests.append(
            {
                "createParagraphBullets": {
                    "range": {"startIndex": run["start"], "endIndex": run["end"]},
                    "bulletPreset": preset,
                }
            }
        )

    return "".join(pieces), style_requests, cursor


def _text_style_request(start: int, end: int, sp: Dict[str, Any]) -> Dict[str, Any]:
    text_style: Dict[str, Any] = {}
    fields: List[str] = []
    if sp.get("bold"):
        text_style["bold"] = True
        fields.append("bold")
    if sp.get("italic"):
        text_style["italic"] = True
        fields.append("italic")
    if sp.get("code"):
        text_style["weightedFontFamily"] = {"fontFamily": _MONO_FONT}
        fields.append("weightedFontFamily")
    if sp.get("link"):
        text_style["link"] = {"url": sp["link"]}
        fields.append("link")
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": text_style,
            "fields": ",".join(fields),
        }
    }


def _mono_request(start: int, end: int) -> Dict[str, Any]:
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": {"weightedFontFamily": {"fontFamily": _MONO_FONT}},
            "fields": "weightedFontFamily",
        }
    }


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def parse_table(lines: List[str]) -> List[List[str]]:
    """Parse markdown table lines into a 2D list of cell strings (incl header).
    The separator row (---|---) is dropped."""
    rows: List[List[str]] = []
    for idx, line in enumerate(lines):
        if idx == 1 and _TABLE_SEP_RE.match(line):
            continue
        cells = line.strip()
        if cells.startswith("|"):
            cells = cells[1:]
        if cells.endswith("|"):
            cells = cells[:-1]
        rows.append([c.strip() for c in cells.split("|")])
    # Normalise column count.
    width = max((len(r) for r in rows), default=0)
    for r in rows:
        while len(r) < width:
            r.append("")
    return rows


# ---------------------------------------------------------------------------
# Document-level rendering (handles segments + tables, re-reading indices)
# ---------------------------------------------------------------------------


def document_end_index(service, document_id: str) -> int:
    doc = service.documents().get(documentId=document_id).execute()
    content = doc.get("body", {}).get("content", [])
    if not content:
        return 1
    return content[-1].get("endIndex", 1)


def clear_body(service, document_id: str) -> None:
    end = document_end_index(service, document_id)
    if end > 2:
        service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "deleteContentRange": {
                            "range": {"startIndex": 1, "endIndex": end - 1}
                        }
                    }
                ]
            },
        ).execute()


def _insert_index(service, document_id: str) -> int:
    """Index at which new content should be inserted (before the final
    newline of the body)."""
    return max(1, document_end_index(service, document_id) - 1)


def render_markdown(
    service,
    document_id: str,
    markdown: str,
    start_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Render markdown into an existing document, appending at the end.

    Returns a summary dict with counts of segments / tables processed.
    """
    segments = segment_markdown(markdown)
    tables_done = 0
    text_blocks_done = 0

    for kind, lines in segments:
        if kind == "text":
            blocks = parse_text_blocks(lines)
            if not blocks:
                continue
            base = _insert_index(service, document_id)
            text, style_requests, _ = build_text_requests(blocks, base)
            if not text.strip("\n"):
                # Only blank lines; skip to avoid empty inserts.
                continue
            requests = [
                {"insertText": {"location": {"index": base}, "text": text}}
            ] + style_requests
            service.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()
            text_blocks_done += len(blocks)
        else:  # table
            rows = parse_table(lines)
            if not rows:
                continue
            _insert_table(service, document_id, rows)
            tables_done += 1

    return {
        "documentId": document_id,
        "status": "rendered",
        "segments": len(segments),
        "tables": tables_done,
        "paragraphs": text_blocks_done,
        "url": f"https://docs.google.com/document/d/{document_id}/edit",
    }


def _insert_table(service, document_id: str, rows: List[List[str]]) -> None:
    n_rows = len(rows)
    n_cols = len(rows[0]) if rows else 0
    if n_rows == 0 or n_cols == 0:
        return

    insert_at = _insert_index(service, document_id)
    service.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [
                {
                    "insertTable": {
                        "location": {"index": insert_at},
                        "rows": n_rows,
                        "columns": n_cols,
                    }
                }
            ]
        },
    ).execute()

    # Re-read to find the table and each cell's text insertion index.
    doc = service.documents().get(documentId=document_id).execute()
    table_el = _find_table_at_or_after(doc, insert_at)
    if not table_el:
        return

    # Gather (index, text, spans) for every cell, then insert highest-first so
    # earlier insertions don't shift the indices of later ones.
    cell_inserts: List[Tuple[int, str, List[Dict[str, Any]]]] = []
    table_rows = table_el["table"]["tableRows"]
    for r, row in enumerate(table_rows):
        for c, cell in enumerate(row["tableCells"]):
            cell_content = cell.get("content", [])
            # The empty cell has a paragraph; its start index is where text goes.
            start = cell_content[0].get("startIndex") if cell_content else None
            if start is None:
                continue
            raw = rows[r][c] if r < len(rows) and c < len(rows[r]) else ""
            plain, spans = parse_inline(raw)
            cell_inserts.append((start, plain, spans))

    cell_inserts.sort(key=lambda t: t[0], reverse=True)

    requests: List[Dict[str, Any]] = []
    for start, plain, spans in cell_inserts:
        if not plain:
            continue
        requests.append({"insertText": {"location": {"index": start}, "text": plain}})
        for sp in spans:
            requests.append(
                _text_style_request(start + sp["start"], start + sp["end"], sp)
            )
        # Bold the header row cells (row 0). Header cells map to the last inserts
        # but we already know r via ordering? Simpler: bold handled below.

    if requests:
        service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()

    # Bold the header row (first row) for readability.
    _bold_header_row(service, document_id, insert_at, n_cols)


def _bold_header_row(service, document_id: str, insert_at: int, n_cols: int) -> None:
    doc = service.documents().get(documentId=document_id).execute()
    table_el = _find_table_at_or_after(doc, insert_at)
    if not table_el:
        return
    first_row = table_el["table"]["tableRows"][0]
    requests: List[Dict[str, Any]] = []
    for cell in first_row["tableCells"]:
        for el in cell.get("content", []):
            para = el.get("paragraph")
            if not para:
                continue
            for run in para.get("elements", []):
                tr = run.get("textRun")
                if tr and run.get("endIndex", 0) > run.get("startIndex", 0):
                    s, e = run["startIndex"], run["endIndex"]
                    # Don't bold the trailing newline only.
                    if e - s >= 1:
                        requests.append(
                            {
                                "updateTextStyle": {
                                    "range": {"startIndex": s, "endIndex": e},
                                    "textStyle": {"bold": True},
                                    "fields": "bold",
                                }
                            }
                        )
    if requests:
        service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()


def _find_table_at_or_after(doc: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    content = doc.get("body", {}).get("content", [])
    candidate = None
    for el in content:
        if "table" in el and el.get("startIndex", -1) >= index - 1:
            return el
        if "table" in el:
            candidate = el  # fall back to last table before index
    return candidate
