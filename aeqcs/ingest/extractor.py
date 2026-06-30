"""Rule-based proposal extraction from uploaded documents."""

from __future__ import annotations

import re
from typing import Any


FACTOR_PATTERN = re.compile(r"factor:\s*(?P<factor_id>[A-Za-z0-9_]+)\s*=\s*(?P<definition>.+)")
CORRECTION_PATTERN = re.compile(r"correction:\s*(?P<target>[^=]+)=>\s*(?P<corrected>.+)")


def extract_proposals(text: str, source: str = "upload") -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for line in text.splitlines():
        factor = FACTOR_PATTERN.search(line)
        if factor:
            proposals.append(
                {
                    "kind": "factor",
                    "payload": {
                        "factor_id": factor.group("factor_id").strip(),
                        "definition": factor.group("definition").strip(),
                    },
                    "source": source,
                    "confidence": 0.7,
                }
            )
            continue
        correction = CORRECTION_PATTERN.search(line)
        if correction:
            proposals.append(
                {
                    "kind": "correction",
                    "payload": {
                        "target": correction.group("target").strip(),
                        "corrected": correction.group("corrected").strip(),
                    },
                    "source": source,
                    "confidence": 0.9,
                }
            )
    return proposals
