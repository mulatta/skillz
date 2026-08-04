# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""HTML-to-Markdown rendering for Miniflux entries."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str | None] = []
        self.in_pre = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in {"p", "div", "section", "article", "blockquote"}:
            self._blank_line()
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._blank_line()
            level = int(tag[1])
            self.parts.append(f"{'#' * level} ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in {"ul", "ol"}:
            self._blank_line()
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("_")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")
        elif tag == "pre":
            self._blank_line()
            self.parts.append("```\n")
            self.in_pre = True
        elif tag == "a":
            self.links.append(attrs_dict.get("href"))
        elif tag == "img":
            alt = attrs_dict.get("alt") or "image"
            src = attrs_dict.get("src") or ""
            self.parts.append(f"![{alt}]({src})")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "section", "article", "blockquote"} or tag in {
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self._blank_line()
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("_")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")
        elif tag == "pre":
            if not self._last_endswith("\n"):
                self.parts.append("\n")
            self.parts.append("```")
            self._blank_line()
            self.in_pre = False
        elif tag == "a":
            href = self.links.pop() if self.links else None
            if href:
                self.parts.append(f" ({href})")
        elif tag in {"ul", "ol"}:
            self._blank_line()

    def handle_data(self, data: str) -> None:
        if self.in_pre:
            self.parts.append(data)
        else:
            self.parts.append(re.sub(r"\s+", " ", data))

    def _last_endswith(self, suffix: str) -> bool:
        return bool(self.parts and self.parts[-1].endswith(suffix))

    def _blank_line(self) -> None:
        text = "".join(self.parts)
        if not text:
            return
        if text.endswith("\n\n"):
            return
        if text.endswith("\n"):
            self.parts.append("\n")
        else:
            self.parts.append("\n\n")

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = unescape(text)
        lines = [line.rstrip() for line in text.splitlines()]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" +\n", "\n", text)
        return text.strip() + "\n"


def html_to_markdown(html: str) -> str:
    parser = _MarkdownParser()
    parser.feed(html)
    parser.close()
    return parser.markdown()


def entry_to_markdown(entry: dict[str, Any]) -> str:
    title = _string(entry.get("title"))
    content = _string(entry.get("content"))
    feed = _dict(entry.get("feed"))
    category = _dict(feed.get("category"))
    enclosures = (
        entry.get("enclosures") if isinstance(entry.get("enclosures"), list) else []
    )
    header = [
        "---",
        f"id: {entry.get('id', '')}",
        f"title: {_yaml_string(title)}",
        f"url: {_string(entry.get('url'))}",
        f"feed: {_yaml_string(_string(feed.get('title')))}",
        f"category: {_yaml_string(_string(category.get('title')))}",
        f"published_at: {_string(entry.get('published_at'))}",
        f"changed_at: {_string(entry.get('changed_at'))}",
        "attachments:",
    ]
    if enclosures:
        for idx, enclosure in enumerate(enclosures):
            if isinstance(enclosure, dict):
                header.append(
                    "  - "
                    f"idx: {idx}, url: {_yaml_string(_string(enclosure.get('url')))}, "
                    f"mime: {_yaml_string(_string(enclosure.get('mime_type')))}"
                )
    else:
        header.append("  []")
    header.extend(["---", ""])
    return "\n".join(header) + html_to_markdown(content)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _yaml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
