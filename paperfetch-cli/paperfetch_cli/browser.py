# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Headful Chromium engine (patchright) for institutional / Cloudflare fetches.

Validated approach (see README.md): a headful browser under Xvfb with stock
Chromium clears Cloudflare where a headless browser gets a 403. A PDF is pulled
with an in-page ``fetch()`` run from a same-origin sibling page inside a fresh
iframe (the iframe's fetch is pristine, bypassing publisher window.fetch
bot-detection); an out-of-band HTTP client gets a CF 403, and navigating to the
PDF directly only opens Chrome's viewer.

ScienceDirect uses a best-effort second path that clicks the page's real
"View PDF" link and watches its popup for PDF bytes. Article authentication does
not guarantee that this interactive path will return a PDF to automation.
"""

from __future__ import annotations

import base64
import contextlib
import os
import re
import sys
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import urlsplit

from patchright.sync_api import Error as PlaywrightError
from patchright.sync_api import sync_playwright
from pyvirtualdisplay import Display

from paperfetch_cli.errors import EXIT_FETCH, CLIError
from paperfetch_cli.sanitize import redact_url

if TYPE_CHECKING:
    from types import TracebackType

    from paperfetch_cli.config import BrowserConfig

_CHALLENGE = re.compile(
    r"just a moment|attention required|checking your browser|enable javascript",
    re.IGNORECASE,
)
# Some sites (ScienceDirect) keep the real <title> while serving a Cloudflare
# interstitial in the body, so a title-only check misses it. The challenge page
# loads the cdn-cgi challenge script and tells the user to enable JS + cookies.
_CHALLENGE_BODY = re.compile(
    r"cdn-cgi/challenge-platform|enable javascript and cookies|are you a robot",
    re.IGNORECASE,
)


def _is_challenge(title: str, html: str) -> bool:
    return bool(_CHALLENGE.search(title) or _CHALLENGE_BODY.search(html))


def _pdf_link_count(links: list[str]) -> int:
    return sum(1 for link in links if "pdf" in link.lower())


_LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
]
_DEFAULT_SETTLE_MS = 3000
_CHALLENGE_WAIT_MS = 8000
_CHALLENGE_TRIES = 3
_NAV_TRIES = 4
_PDF_TRIES = 3
# The publisher's "View PDF" control - clicked with a real user gesture so the
# download endpoint is reached the way a human reaches it (ScienceDirect).
_PDF_LINK_SEL = 'a[aria-label^="View PDF" i], a#pdfLink, #ViewPDF'

# Pull bytes from inside the same-origin page: the request carries the browser
# fingerprint + session (cf_clearance, institutional cookies) where an
# out-of-band request gets a CF 403. fetch() runs in a fresh same-origin iframe
# so a publisher that monkeypatches window.fetch with bot-detection (Cell Press)
# is bypassed - the iframe's fetch is pristine. (An add_init_script capture
# would work too but breaks Chromium's DNS resolver against systemd-resolved.)
# Must start with the arrow so Playwright detects a function and passes the URL.
_PAGE_FETCH_JS = """async (u) => {
  const frame = document.createElement('iframe');
  frame.style.display = 'none';
  document.body.appendChild(frame);
  try {
    const f = frame.contentWindow.fetch.bind(frame.contentWindow);
    const r = await f(u, { credentials: 'include' });
    const blob = await r.blob();
    const b64 = await new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onerror = () => rej(new Error('read failed'));
      fr.onloadend = () => res(String(fr.result).split(',')[1] || '');
      fr.readAsDataURL(blob);
    });
    return { status: r.status, type: r.headers.get('content-type') || '', b64 };
  } finally {
    frame.remove();
  }
}"""


@dataclass
class PageResult:
    url: str
    status: int
    title: str
    html: str
    links: list[str]
    challenged: bool
    pdf_link_count: int = 0


@dataclass
class FetchResult:
    status: int
    content_type: str
    data: bytes


@dataclass
class BrowserPage:
    page: Any
    result: PageResult

    def close(self) -> None:
        with contextlib.suppress(PlaywrightError):
            self.page.close()


class Browser:
    """A patchright browser session usable as a context manager."""

    def __init__(self, cfg: BrowserConfig) -> None:
        self._cfg = cfg
        self._display: Any = None
        self._pw: Any = None
        self._browser: Any = None
        self._ctx: Any = None

    def __enter__(self) -> Self:
        self._start_display()
        self._pw = sync_playwright().start()
        try:
            self._launch()
        except PlaywrightError as exc:
            self._teardown()
            msg = (
                "could not launch Chromium - pass --executable PATH or run "
                f"'paperfetch-cli setup --chromium PATH' ({exc})"
            )
            raise CLIError(msg, EXIT_FETCH) from exc
        if self._cfg.headers:
            self._ctx.set_extra_http_headers(dict(self._cfg.headers))
        if self._cfg.cookies:
            self._load_cookies(self._cfg.cookies)
        return self

    def _launch(self) -> None:
        chromium = self._pw.chromium
        headless = not self._cfg.headful
        if self._cfg.profile:
            self._ctx = chromium.launch_persistent_context(
                self._cfg.profile,
                headless=headless,
                executable_path=self._cfg.executable,
                args=_LAUNCH_ARGS,
                accept_downloads=True,
            )
        else:
            self._browser = chromium.launch(
                headless=headless,
                executable_path=self._cfg.executable,
                args=_LAUNCH_ARGS,
            )
            self._ctx = self._browser.new_context(accept_downloads=True)

    def _teardown(self) -> None:
        for closer in (self._ctx, self._browser):
            if closer is not None:
                with contextlib.suppress(Exception):
                    closer.close()
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()
        if self._display is not None:
            with contextlib.suppress(Exception):
                self._display.stop()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._teardown()

    def _start_display(self) -> None:
        # Only Linux needs a virtual display; macOS/Windows run Chromium headful
        # natively, and an existing DISPLAY is reused as-is.
        if (
            not self._cfg.headful
            or sys.platform != "linux"
            or os.environ.get("DISPLAY")
        ):
            return
        self._display = Display(visible=False, size=(1440, 900))
        self._display.start()

    def _load_cookies(self, path: str) -> None:
        jar = MozillaCookieJar()
        jar.load(path, ignore_discard=True, ignore_expires=True)
        cookies = [
            {
                "name": c.name,
                "value": c.value or "",
                "domain": c.domain,
                "path": c.path,
                "secure": bool(c.secure),
                "expires": float(c.expires) if c.expires else -1,
            }
            for c in jar
        ]
        if cookies:
            self._ctx.add_cookies(cookies)

    def render(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        wait_ms: int | None = None,
    ) -> PageResult:
        rendered = self.render_page(url, wait_for=wait_for, wait_ms=wait_ms)
        try:
            return rendered.result
        finally:
            rendered.close()

    def render_page(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        wait_ms: int | None = None,
    ) -> BrowserPage:
        last: CLIError | PlaywrightError | None = None
        for _ in range(_NAV_TRIES):
            try:
                page = self._ctx.new_page()
            except PlaywrightError as exc:
                last = exc
                break
            try:
                resp = page.goto(
                    url,
                    timeout=self._cfg.timeout * 1000,
                    wait_until="domcontentloaded",
                )
                if wait_for:
                    with contextlib.suppress(PlaywrightError):
                        page.wait_for_selector(
                            wait_for, timeout=self._cfg.timeout * 1000
                        )
                page.wait_for_timeout(
                    _DEFAULT_SETTLE_MS if wait_ms is None else wait_ms
                )
                title, html, links = self._page_snapshot(page)
                challenged = _is_challenge(title, html)
                attempts = 0
                while challenged and attempts < _CHALLENGE_TRIES:
                    # Wait for the JS challenge to set cf_clearance, then reload to
                    # load the real page with it.
                    page.wait_for_timeout(_CHALLENGE_WAIT_MS)
                    with contextlib.suppress(PlaywrightError):
                        page.reload(
                            timeout=self._cfg.timeout * 1000,
                            wait_until="domcontentloaded",
                        )
                    title, html, links = self._page_snapshot(page)
                    challenged = _is_challenge(title, html)
                    attempts += 1
                status = int(resp.status) if resp is not None else 0
                link_list = [str(link) for link in links]
                result = PageResult(
                    url=str(page.url),
                    status=status,
                    title=title,
                    html=html,
                    links=link_list,
                    challenged=challenged,
                    pdf_link_count=_pdf_link_count(link_list),
                )
                return BrowserPage(page=page, result=result)
            except CLIError as exc:
                last = exc
            except PlaywrightError as exc:
                last = exc
                with contextlib.suppress(PlaywrightError):
                    page.wait_for_timeout(1500)
            with contextlib.suppress(PlaywrightError):
                page.close()
        msg = f"could not render page: {last}"
        raise CLIError(msg, EXIT_FETCH)

    def _page_snapshot(self, page: Any) -> tuple[str, str, list[str]]:  # noqa: ANN401
        # Cloudflare and publisher pages can continue redirecting after
        # domcontentloaded. Retrying avoids surfacing Playwright's transient
        # "execution context was destroyed" as a failed fetch.
        last: PlaywrightError | None = None
        for _ in range(3):
            try:
                title = str(page.title())
                html = str(page.content())
                links = page.eval_on_selector_all(
                    "a[href]", "els => els.map(e => e.href)"
                )
                return title, html, [str(link) for link in links]
            except PlaywrightError as exc:
                last = exc
                with contextlib.suppress(PlaywrightError):
                    page.wait_for_timeout(1500)
        msg = f"could not read rendered page: {last}"
        raise CLIError(msg, EXIT_FETCH)

    def fetch_bytes(
        self,
        url: str,
        *,
        expect: str | None = None,
        context_url: str | None = None,
    ) -> FetchResult:
        # Land on a normal HTML page on the same origin (the article page if
        # given, else the site root), then pull the file with an in-page fetch.
        # Navigating to the PDF itself opens Chrome's PDF viewer, whose document
        # exposes no usable JS context; from a sibling page the fetch is
        # same-origin and carries the browser's session (cf_clearance + cookies).
        landing = context_url or _origin(url)
        page = self._ctx.new_page()
        try:
            if not self._goto(page, landing):
                msg = f"could not load {redact_url(landing)} (DNS or navigation failed)"
                raise CLIError(msg, EXIT_FETCH)
            if _is_challenge(str(page.title()), str(page.content())):
                page.wait_for_timeout(_CHALLENGE_WAIT_MS)
            return self._fetch_bytes_from_page(page, url, expect=expect)
        finally:
            page.close()

    def _fetch_bytes_from_page(
        self,
        page: Any,  # noqa: ANN401
        url: str,
        *,
        expect: str | None = None,
    ) -> FetchResult:
        result = self._evaluate_fetch(page, url)
        status = int(result["status"])
        ctype = str(result["type"])
        payload = result.get("b64") or ""
        data = base64.b64decode(payload) if payload else b""
        _check_expect(expect, ctype, status)
        return FetchResult(status=status, content_type=ctype, data=data)

    def fetch_pdf_from_page(self, url: str, rendered: BrowserPage) -> FetchResult:
        result = self._fetch_bytes_from_page(rendered.page, url)
        if "pdf" in result.content_type and result.data[:4] == b"%PDF":
            return result
        return self._capture_download(url, rendered.result.url)

    def _capture_download(self, url: str, context_url: str | None) -> FetchResult:
        # ScienceDirect gates /pdfft behind a second, *interactive* Cloudflare
        # challenge that a scripted page.goto() can never clear: a scripted nav
        # omits the Sec-Fetch-User user-activation signal, so CF escalates it. A
        # real click on the publisher's "View PDF" link carries user activation
        # and same-origin referer, which is the only automation path that has
        # worked intermittently. Signed asset URLs and viewer resources often
        # re-request as HTML bot pages, so this path is best-effort and never logs
        # the signed URL or response body.
        landing = context_url or _origin(url)
        page = self._ctx.new_page()
        downloads: list[Any] = []
        pdfs: list[bytes] = []

        def _record(dl: Any) -> None:  # noqa: ANN401
            downloads.append(dl)

        def _watch_response(resp: Any) -> None:  # noqa: ANN401
            # Read immediately because Chrome's PDF viewer can consume response
            # bodies before polling code sees them.
            if pdfs:
                return
            with contextlib.suppress(PlaywrightError):
                if "pdf" not in str(resp.headers.get("content-type", "")).lower():
                    return
                body = resp.body()
                if isinstance(body, bytes) and body[:5] == b"%PDF-":
                    pdfs.append(body)

        def _watch_popup(popup: Any) -> None:  # noqa: ANN401
            popup.on("download", _record)
            popup.on("response", _watch_response)

        try:
            self._goto(page, landing)
            page.on("download", _record)
            page.on("response", _watch_response)
            page.on("popup", _watch_popup)
            # The post-click challenge auto-solves only probabilistically, so
            # retry the click a few times (reloading the article between tries to
            # refresh cf_clearance) before giving up.
            per_try = max(1, self._cfg.timeout // _PDF_TRIES)
            for attempt in range(_PDF_TRIES):
                if attempt > 0:
                    with contextlib.suppress(PlaywrightError):
                        self._goto(page, landing)
                link = page.query_selector(_PDF_LINK_SEL)
                with contextlib.suppress(PlaywrightError):
                    if link is not None:
                        link.click()
                    elif attempt == 0:
                        page.goto(url, timeout=self._cfg.timeout * 1000)
                for _ in range(per_try):
                    if pdfs:
                        return FetchResult(
                            status=200, content_type="application/pdf", data=pdfs[0]
                        )
                    if downloads:
                        return FetchResult(
                            status=200,
                            content_type="application/pdf",
                            data=Path(downloads[0].path()).read_bytes(),
                        )
                    page.wait_for_timeout(1000)
            msg = f"no PDF reached for {redact_url(url)}"
            raise CLIError(msg, EXIT_FETCH)
        finally:
            page.close()

    def _goto(self, page: Any, url: str) -> bool:  # noqa: ANN401
        # Chromium's resolver is flaky against the systemd-resolved stub (it
        # tries the resolv.conf search domains first); retry the navigation a
        # few times before giving up so a transient ERR_NAME_NOT_RESOLVED does
        # not look like an empty page.
        for _ in range(_NAV_TRIES):
            try:
                page.goto(
                    url, timeout=self._cfg.timeout * 1000, wait_until="domcontentloaded"
                )
            except PlaywrightError:
                page.wait_for_timeout(1500)
                continue
            page.wait_for_timeout(_DEFAULT_SETTLE_MS)
            return True
        return False

    def _evaluate_fetch(self, page: Any, url: str) -> Any:  # noqa: ANN401
        # The page may still be settling (idp / redirect); retry the in-page
        # fetch if its execution context is torn down by a navigation.
        last: PlaywrightError | None = None
        for _ in range(3):
            try:
                return page.evaluate(_PAGE_FETCH_JS, url)
            except PlaywrightError as exc:
                last = exc
                page.wait_for_timeout(2500)
        msg = f"in-page fetch failed: {last}"
        raise CLIError(msg, EXIT_FETCH)


def _check_expect(expect: str | None, ctype: str, status: int) -> None:
    if expect and expect not in ctype:
        got = ctype or "unknown"
        msg = f"expected {expect}, got {got} (status {status})"
        raise CLIError(msg, EXIT_FETCH)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"
