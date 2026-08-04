# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import importlib
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType
from typing import cast

_DEFUSED_ET: ModuleType = importlib.import_module("defusedxml.ElementTree")


def fromstring(text: str | bytes) -> ET.Element:
    return cast("ET.Element", _DEFUSED_ET.fromstring(text))


def parse(path: str | Path) -> ET.ElementTree:
    return cast("ET.ElementTree", _DEFUSED_ET.parse(path))
