from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skillcheck.reports.builder import ReportDocument


def render_json(document: ReportDocument) -> str:
    return json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
