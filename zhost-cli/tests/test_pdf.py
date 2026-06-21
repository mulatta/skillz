"""Tests for the PDF highlight-geometry locator (the one non-trivial algorithm).

Uses pymupdf (a hard dependency) to synthesize tiny PDFs, including a hyphenated
line break, which is the case the word-stream fallback exists for."""

from __future__ import annotations

import fitz  # type: ignore[import-untyped]
import pytest

from zhost_cli import pdf
from zhost_cli.errors import InputError


def _make(tmp_path: object, text: str) -> str:
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((50, 60), text, fontsize=11)
    path = f"{tmp_path}/t.pdf"
    doc.save(path)
    doc.close()
    return path


def test_locate_exact(tmp_path: object) -> None:
    located = pdf.locate(_make(tmp_path, "hello world here"), "hello world")
    assert located.page_index == 0
    assert len(located.rects) == 1
    assert len(located.rects[0]) == 4  # [x0, y0, x1, y1], bottom-left


def test_locate_hyphenated_fallback(tmp_path: object) -> None:
    # search_for cannot match "structures" across "struc-\ntures"; the word-stream
    # fallback normalizes the hyphenated break away and finds it across two lines.
    path = _make(tmp_path, "tertiary struc-\ntures here")
    located = pdf.locate(path, "tertiary structures")
    assert located.page_index == 0
    assert len(located.rects) == 2  # one rect per line fragment


def test_locate_not_found(tmp_path: object) -> None:
    with pytest.raises(InputError):
        pdf.locate(_make(tmp_path, "nothing relevant"), "absent phrase")
