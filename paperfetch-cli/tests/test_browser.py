"""Offline tests for browser helper logic."""

from __future__ import annotations

import pytest
from patchright.sync_api import Error as PlaywrightError

from paperfetch_cli.browser import Browser, _check_expect, _is_challenge
from paperfetch_cli.config import BrowserConfig
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


class ClosingPage:
    def __init__(self) -> None:
        self.waits = 0

    def goto(self, *_args: object, **_kwargs: object) -> None:
        return None

    def title(self) -> str:
        msg = "execution context was destroyed"
        raise PlaywrightError(msg)

    def wait_for_timeout(self, _timeout: int) -> None:
        self.waits += 1
        if self.waits > 1:
            msg = "Target page, context or browser has been closed"
            raise PlaywrightError(msg)

    def close(self) -> None:
        return None


class ClosingContext:
    def new_page(self) -> ClosingPage:
        return ClosingPage()


def test_render_reports_page_snapshot_closure_as_cli_error() -> None:
    browser = Browser(BrowserConfig())
    browser.__dict__["_ctx"] = ClosingContext()
    with pytest.raises(CLIError, match="could not read rendered page"):
        browser.render("https://example.org/article")
