# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
import hashlib
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import xmlsafe
from .atomic import atomic_write_bytes


class DrawioError(ValueError):
    """Raised for invalid draw.io document operations."""


class Sha256Conflict(DrawioError):
    """Raised when guarded source bytes changed before replacement."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_xml(text: str) -> ET.Element:
    try:
        return xmlsafe.fromstring(text)
    except ET.ParseError as exc:
        raise DrawioError(f"cannot parse XML: {exc}") from exc


def decode_diagram_text(text: str) -> ET.Element:
    stripped = text.strip()
    if stripped.startswith("<"):
        root = _parse_xml(stripped)
        if root.tag != "mxGraphModel":
            raise DrawioError(f"expected mxGraphModel, got {root.tag}")
        return root

    try:
        raw = base64.b64decode(stripped, validate=False)
        inflated = zlib.decompress(raw, -15).decode("utf-8")
        xml_text = urllib.parse.unquote(inflated)
    except (ValueError, zlib.error, UnicodeDecodeError) as exc:
        raise DrawioError(f"cannot decode compressed diagram: {exc}") from exc

    root = _parse_xml(xml_text)
    if root.tag != "mxGraphModel":
        raise DrawioError(f"expected mxGraphModel, got {root.tag}")
    return root


def element_to_bytes(element: ET.Element) -> bytes:
    return cast(
        bytes, ET.tostring(element, encoding="utf-8", short_empty_elements=True)
    )


def element_to_text(element: ET.Element) -> str:
    return element_to_bytes(element).decode("utf-8")


@dataclass(frozen=True)
class Page:
    index: int
    element: ET.Element

    @property
    def page_id(self) -> str:
        return self.element.get("id", "")

    @property
    def name(self) -> str:
        return self.element.get("name", "")

    @property
    def compressed(self) -> bool:
        return (
            not (self.element.text or "").lstrip().startswith("<")
            and self.element.find("mxGraphModel") is None
        )

    def model(self) -> ET.Element:
        child = self.element.find("mxGraphModel")
        if child is not None:
            return child
        return decode_diagram_text(self.element.text or "")


@dataclass
class DrawioDocument:
    root: ET.Element
    sha256: str

    @classmethod
    def from_file(cls, path: Path) -> DrawioDocument:
        raw = path.read_bytes()
        try:
            root = xmlsafe.fromstring(raw)
        except ET.ParseError as exc:
            raise DrawioError(f"cannot parse {path}: {exc}") from exc
        if root.tag == "mxGraphModel":
            mxfile = ET.Element("mxfile", {"host": "offline"})
            diagram = ET.SubElement(
                mxfile, "diagram", {"id": "page-1", "name": "Page-1"}
            )
            diagram.append(root)
            root = mxfile
        if root.tag != "mxfile":
            raise DrawioError(f"expected mxfile or mxGraphModel, got {root.tag}")
        return cls(root=root, sha256=hashlib.sha256(raw).hexdigest())

    def page_objects(self) -> list[Page]:
        diagrams = self.root.findall("diagram")
        if not diagrams:
            raise DrawioError("mxfile has no diagram pages")
        return [
            Page(index=index, element=diagram) for index, diagram in enumerate(diagrams)
        ]

    def pages(self) -> list[dict[str, Any]]:
        return [
            {
                "index": page.index,
                "id": page.page_id,
                "name": page.name,
                "compressed": page.compressed,
            }
            for page in self.page_objects()
        ]

    def select_page(
        self,
        *,
        page_id: str | None = None,
        page_name: str | None = None,
        page_index: int | None = None,
    ) -> Page:
        selectors = [page_id is not None, page_name is not None, page_index is not None]
        if sum(selectors) == 0:
            pages = self.page_objects()
            if len(pages) != 1:
                raise DrawioError("page selector required for multi-page document")
            return pages[0]
        if sum(selectors) > 1:
            raise DrawioError("provide only one page selector")

        matches: list[Page]
        pages = self.page_objects()
        if page_id is not None:
            matches = [page for page in pages if page.page_id == page_id]
        elif page_name is not None:
            matches = [page for page in pages if page.name == page_name]
        else:
            matches = [page for page in pages if page.index == page_index]

        if not matches:
            raise DrawioError("no matching page")
        if len(matches) > 1:
            raise DrawioError("page selector matched multiple pages")
        return matches[0]

    def page_model(
        self,
        *,
        page_id: str | None = None,
        page_name: str | None = None,
        page_index: int | None = None,
    ) -> ET.Element:
        return self.select_page(
            page_id=page_id,
            page_name=page_name,
            page_index=page_index,
        ).model()

    def replace_page(
        self,
        model: ET.Element,
        *,
        page_id: str | None = None,
        page_name: str | None = None,
        page_index: int | None = None,
    ) -> None:
        if model.tag != "mxGraphModel":
            raise DrawioError(f"expected mxGraphModel, got {model.tag}")
        page = self.select_page(
            page_id=page_id, page_name=page_name, page_index=page_index
        )
        for child in list(page.element):
            page.element.remove(child)
        page.element.text = None
        page.element.append(model)

    def to_bytes(self) -> bytes:
        return element_to_bytes(self.root) + b"\n"

    @staticmethod
    def replace_page_atomic(
        path: Path,
        model: ET.Element,
        *,
        expect_sha256: str,
        page_id: str | None = None,
        page_name: str | None = None,
        page_index: int | None = None,
    ) -> str:
        current = sha256_file(path)
        if current != expect_sha256:
            raise Sha256Conflict(
                f"sha256 conflict: expected {expect_sha256}, got {current}"
            )
        doc = DrawioDocument.from_file(path)
        doc.replace_page(
            model, page_id=page_id, page_name=page_name, page_index=page_index
        )
        data = doc.to_bytes()
        if sha256_file(path) != expect_sha256:
            raise Sha256Conflict("sha256 conflict: file changed during replace")
        stat = path.stat()
        atomic_write_bytes(path, data, stat.st_mode & 0o777)
        return sha256_file(path)
