"""PDF geometry for highlight annotations.

Zotero stores a highlight's `annotationPosition` as a JSON string with rects in
PDF coordinates (origin bottom-left). pymupdf reports geometry in top-left
origin, so every rect is flipped: [x0, H - y1, x1, H - y0]. A sentence that
wraps across lines yields one rect per line, matching how the desktop client
renders a multi-line highlight.

Two locators, tried in order:
1. `search_for` — exact, fast, gives clean per-line rects when the text appears
   verbatim in the layout.
2. word-stream fallback — academic PDFs hyphenate across line breaks
   ("struc-\\ntures"), so the verbatim string is absent even though the sentence
   is there. Normalize words to alnum-lowercase, concatenate into a stream,
   find the normalized target as a substring, then union the covering words'
   boxes per line. Robust to hyphenation, line breaks, case, and spacing.

No LLM tokens are spent: locating text and computing geometry is deterministic.
The caller supplies the exact text to find.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from zhost_cli.errors import InputError


@dataclass(frozen=True)
class Located:
    page_index: int
    rects: list[list[float]]

    def position_json(self) -> str:
        """The `annotationPosition` string the API expects."""
        return json.dumps({"pageIndex": self.page_index, "rects": self.rects})


def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _flip(boxes: list[tuple[float, float, float, float]], height: float) -> list[list[float]]:
    return [
        [round(x0, 2), round(height - y1, 2), round(x1, 2), round(height - y0, 2)]
        for (x0, y0, x1, y1) in boxes
    ]


def _word_rects(page: object, target: str) -> list[list[float]]:
    """Locate `target` via the normalized word stream; [] if not found."""
    words = page.get_text("words")  # type: ignore[attr-defined]  # (x0,y0,x1,y1,word,block,line,n)
    stream: list[str] = []
    owner: list[int] = []
    for idx, word in enumerate(words):
        for ch in word[4].lower():
            if ch.isalnum():
                stream.append(ch)
                owner.append(idx)
    pos = "".join(stream).find(_norm(target))
    if pos < 0:
        return []
    covered = sorted({owner[i] for i in range(pos, pos + len(_norm(target)))})
    # Union the covering words' boxes per text line, preserving top-to-bottom order.
    lines: dict[tuple[int, int], tuple[float, float, float, float]] = {}
    for idx in covered:
        w = words[idx]
        key = (w[5], w[6])
        box = (w[0], w[1], w[2], w[3])
        if key in lines:
            a = lines[key]
            lines[key] = (
                min(a[0], box[0]),
                min(a[1], box[1]),
                max(a[2], box[2]),
                max(a[3], box[3]),
            )
        else:
            lines[key] = box
    ordered = sorted(lines.values(), key=lambda b: (b[1], b[0]))
    return _flip(ordered, page.rect.height)  # type: ignore[attr-defined]


def locate(pdf_path: str, text: str) -> Located:
    """Find `text` in the PDF and return its page index + bottom-left rects.

    Raises InputError if the text is not found on any page.
    """
    import fitz  # type: ignore[import-untyped]  # lazy: keeps the rest import-light

    doc = fitz.open(pdf_path)
    try:
        for index in range(doc.page_count):
            page = doc[index]
            hits = page.search_for(text)
            if hits:
                return Located(
                    index, _flip([(r.x0, r.y0, r.x1, r.y1) for r in hits], page.rect.height)
                )
            rects = _word_rects(page, text)
            if rects:
                return Located(index, rects)
    finally:
        doc.close()
    raise InputError(f"text not found in {pdf_path}: {text!r}")
