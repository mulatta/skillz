"""Offline tests for browser helper logic."""

from __future__ import annotations

import pytest

from paperfetch_cli.browser import _check_expect, _is_challenge
from paperfetch_cli.errors import CLIError


def test_is_challenge_detects_title_and_body_markers() -> None:
    assert _is_challenge("Just a moment...", "<html></html>")
    assert _is_challenge(
        "Article title", "<script src='/cdn-cgi/challenge-platform/x'></script>"
    )
    assert not _is_challenge("Article title", "<main>paper</main>")


def test_check_expect_rejects_wrong_content_type() -> None:
    _check_expect("application/pdf", "application/pdf; charset=binary", 200)
    with pytest.raises(CLIError, match="expected application/pdf"):
        _check_expect("application/pdf", "text/html", 200)
