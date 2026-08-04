# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

import pytest

from drawio_cli.document import DrawioDocument
from drawio_cli.validate import validate_document

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("old", "new", "result_field", "message"),
    [
        ('target="b"', 'target="missing"', "errors", "target 'missing' does not exist"),
        ('x="220" y="40"', 'x="80" y="50"', "warnings", "overlap"),
        ('width="120"', 'width="inf"', "errors", "invalid geometry"),
    ],
)
def test_validation_reports_structural_problems(
    tmp_path: Path, old: str, new: str, result_field: str, message: str
) -> None:
    src = tmp_path / "invalid.drawio"
    src.write_text((FIXTURES / "minimal.drawio").read_text().replace(old, new))

    result = validate_document(DrawioDocument.from_file(src))

    assert any(message in item for item in getattr(result, result_field))


def test_validation_does_not_mutate_user_object_ids(tmp_path: Path) -> None:
    src = tmp_path / "userobject.drawio"
    src.write_text(
        """
<mxfile host="offline"><diagram id="p" name="P"><mxGraphModel><root>
  <mxCell id="0"/>
  <mxCell id="1" parent="0"/>
  <UserObject id="outer" label="Wrapped"><mxCell id="inner" value="Wrapped" vertex="1" parent="1"><mxGeometry x="10" y="10" width="80" height="40" as="geometry"/></mxCell></UserObject>
</root></mxGraphModel></diagram></mxfile>
""".strip()
        + "\n",
        encoding="utf-8",
    )
    doc = DrawioDocument.from_file(src)
    before = doc.to_bytes()

    validate_document(doc)

    assert doc.to_bytes() == before
