"""Existing recorded app: no providers, retries or side effects."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
from typing import Any


def process(request: dict[str, Any], policy: str) -> dict[str, Any]:
    records = json.loads(Path(__file__).with_name("recorded.json").read_text())
    return deepcopy(records[policy][request["ticket_id"]])
