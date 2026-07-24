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


class RecordingChromium:
    def __init__(self) -> None:
        self.launch_kwargs: dict[str, object] = {}
        self.context_kwargs: dict[str, object] = {}

    def launch(self, **kwargs: object) -> RecordingChromium:
        self.launch_kwargs = kwargs
        return self

    def new_context(self, **kwargs: object) -> object:
        self.context_kwargs = kwargs
        return object()


class FetchPage:
    def __init__(self) -> None:
        self.closed = False
        self.url = "https://example.org/article"

    def goto(self, *_args: object, **_kwargs: object) -> object:
        return type("Response", (), {"status": 200})()

    def wait_for_timeout(self, _timeout: int) -> None:
        return None

    def title(self) -> str:
        return "Article"

    def content(self) -> str:
        return "<main>Article</main>"

    def eval_on_selector_all(self, *_args: object) -> list[str]:
        return ["https://example.org/paper.pdf"]

    def evaluate(self, _script: str, _url: str) -> dict[str, object]:
        return {"status": 200, "type": "application/pdf", "b64": "JVBERi0="}

    def close(self) -> None:
        self.closed = True


class FetchContext:
    def __init__(self) -> None:
        self.pages: list[FetchPage] = []

    def new_page(self) -> FetchPage:
        page = FetchPage()
        self.pages.append(page)
        return page


def test_fetch_pdf_from_rendered_page_reuses_article_tab() -> None:
    browser = Browser(BrowserConfig())
    context = FetchContext()
    browser.__dict__["_ctx"] = context

    rendered = browser.render_page("https://example.org/article", wait_ms=0)
    result = browser.fetch_pdf_from_page("https://example.org/paper.pdf", rendered)
    rendered.close()

    assert result.data == b"%PDF-"
    assert len(context.pages) == 1
    assert context.pages[0].closed


def test_launch_keeps_sandbox_and_tls_verification_enabled() -> None:
    chromium = RecordingChromium()
    browser = Browser(BrowserConfig())
    browser.__dict__["_pw"] = type("PW", (), {"chromium": chromium})()

    Browser.__dict__["_launch"](browser)

    args = chromium.launch_kwargs["args"]
    assert isinstance(args, list)
    assert "--no-sandbox" not in args
    assert "--disable-setuid-sandbox" not in args
    assert "--ignore-certificate-errors" not in args
    assert chromium.context_kwargs == {"accept_downloads": True}
