from __future__ import annotations

import base64
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import pytest
from drawio_cli import xmlsafe
from drawio_cli.cli import main
from drawio_cli.document import DrawioDocument, sha256_file

FIXTURES = Path(__file__).parent / "fixtures"


def _copy_minimal(tmp_path: Path) -> Path:
    src = tmp_path / "diagram.drawio"
    src.write_bytes((FIXTURES / "minimal.drawio").read_bytes())
    return src


def _changed_model(doc: DrawioDocument) -> ET.Element:
    model = doc.page_model(page_index=0)
    node = model.find("root/mxCell[@id='a']")
    assert node is not None
    node.set("value", "Changed")
    return model


def test_page_get_refuses_to_overwrite_source(tmp_path: Path) -> None:
    src = _copy_minimal(tmp_path)
    alias = tmp_path / "alias.drawio"
    alias.hardlink_to(src)
    before = src.read_bytes()

    assert main(["get-page", str(src), "--output", str(alias)]) == 1
    assert src.read_bytes() == alias.read_bytes() == before


def test_page_replace_uses_sha_guard(tmp_path: Path) -> None:
    src = _copy_minimal(tmp_path)
    doc = DrawioDocument.from_file(src)
    model = _changed_model(doc)

    with pytest.raises(ValueError, match="sha256 conflict"):
        DrawioDocument.replace_page_atomic(
            src,
            model,
            page_index=0,
            expect_sha256="0" * 64,
        )
    assert sha256_file(src) == doc.sha256

    new_hash = DrawioDocument.replace_page_atomic(
        src,
        model,
        page_index=0,
        expect_sha256=doc.sha256,
    )
    assert new_hash == sha256_file(src)
    assert "Changed" in src.read_text()


def test_page_replace_preserves_other_pages(tmp_path: Path) -> None:
    src = tmp_path / "multi.drawio"
    src.write_text(
        """
<mxfile host="offline">
  <diagram id="first" name="First"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="a" value="Keep" vertex="1" parent="1"><mxGeometry x="0" y="0" width="80" height="40" as="geometry"/></mxCell></root></mxGraphModel></diagram>
  <diagram id="second" name="Second"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="b" value="Replace" vertex="1" parent="1"><mxGeometry x="0" y="0" width="80" height="40" as="geometry"/></mxCell></root></mxGraphModel></diagram>
</mxfile>
""".strip()
        + "\n",
        encoding="utf-8",
    )
    doc = DrawioDocument.from_file(src)
    replacement = xmlsafe.fromstring(
        '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="c" value="New" vertex="1" parent="1"><mxGeometry x="0" y="0" width="80" height="40" as="geometry"/></mxCell></root></mxGraphModel>'
    )

    DrawioDocument.replace_page_atomic(
        src,
        replacement,
        page_id="second",
        expect_sha256=doc.sha256,
    )

    updated = DrawioDocument.from_file(src)
    assert updated.page_model(page_id="first").find("root/mxCell[@id='a']") is not None
    assert updated.page_model(page_id="second").find("root/mxCell[@id='c']") is not None


def test_compressed_page_decodes(tmp_path: Path) -> None:
    model = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="z" value="Compressed" vertex="1" parent="1"><mxGeometry x="0" y="0" width="80" height="40" as="geometry"/></mxCell></root></mxGraphModel>'
    compressor = zlib.compressobj(wbits=-15)
    encoded = base64.b64encode(
        compressor.compress(urllib.parse.quote(model).encode()) + compressor.flush()
    ).decode()
    src = tmp_path / "compressed.drawio"
    src.write_text(
        f'<mxfile host="offline"><diagram id="p" name="Packed">{encoded}</diagram></mxfile>\n',
        encoding="utf-8",
    )

    doc = DrawioDocument.from_file(src)

    assert doc.pages()[0]["compressed"] is True
    assert doc.page_model(page_id="p").find("root/mxCell[@id='z']") is not None
