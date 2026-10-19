#!/usr/bin/env python3
"""Emit source-reviewed Davison overlays for page 40 and page 204."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).parent

THREADING_40 = [1, 2, 1, 2, 3, 4, 3, 2, 1, 2, 3, 4, 3]

# Tie-up columns are in treadle order. The plate has six columns; blank,
# unused columns on I-IV are retained rather than silently collapsed.
TIEUPS_40 = {
    "I": [[2], [3], [2, 4], [1, 3], [], []],
    "II": [[4], [3], [2], [1, 4], [], []],
    "III": [[1, 3, 4], [2, 4], [2, 3], [4], [], []],
    "IV": [[2, 3, 4], [3, 4], [1, 4], [2], [], []],
    "V": [[3, 4], [2, 3], [1, 2], [1, 4], [2, 4], [1, 3]],
    "VII": [[3, 4], [2, 3], [1, 2], [1, 4], [2, 4], [1, 3]],
    "IX": [[4], [3, 4], [2, 3, 4], [1, 2, 3], [1, 2], [1]],
    "XI": [[1], [2], [1, 3], [2, 4], [1, 3, 4], [2, 3, 4]],
}

RAILS_40 = [
    ("I", [3, 2, 1, 4, 2, 1]),
    ("II", [1, 2, 3, 4, 3, 2]),
    ("III", [1, 2, 3, 4, 3, 2]),
    ("IV", [1, 2, 3, 4, 3, 2]),
    ("V", [1, 2, 3, 4]),
    ("V", [4, 1, 2, 3, 4, 1, 4, 3, 2, 1]),  # VI shares V
    ("VII", [1, 2, 1, 4, 3, 4]),
    ("VII", [1, 5, 1, 6, 3, 5, 3, 6]),       # VIII shares VII
    ("IX", [1, 2, 3, 4, 5, 6]),
    ("IX", [1, 2, 3, 6, 5, 4]),               # X shares IX
    ("XI", [1, 2, 3, 4, 5, 6, 5, 4, 3, 2]),
]

THREADING_204 = [
    1, 4, 3, 2, 1, 4, 3, 2, 1, 4, 3, 4, 3, 4, 3, 4, 3, 2, 1, 4,
    3, 4, 3, 4, 3, 4, 3, 2, 1, 4, 3, 4, 3, 4, 3, 4, 3, 2, 1, 4,
    3, 4, 3, 4, 3, 4, 3, 2, 1, 3,
]
TIEUP_204 = [[3, 4], [2, 3], [1, 2], [1, 4], [2, 4], [1, 3]]
RAIL_204 = [
    1, 3, 3, 3, 1, 3, 1, 3, 1, 3, 3, 1, 3, 1,
    2, 3, 4, 3, 4, 3, 2, 1, 2, 3, 4, 3, 4, 3, 2, 1,
]


def visual(lowered: list[list[int]]) -> list[list[int]]:
    return [[int(4 - row in column) for column in reversed(lowered)]
            for row in range(4)]


def reviewed_draft(page: int, number: int, threading: list[int],
                   lowered: list[list[int]], rail: list[int], method: str,
                   control: list[int] | None = None) -> dict:
    draft_id = f"davison-p{page:03d}-reviewed-d{number:02d}"
    lifted = [sorted(set(range(1, 5)) - set(column)) for column in lowered]
    return {
        "id": draft_id,
        "chartGroup": f"davison-p{page:03d}-reviewed-g01",
        "bbox": [0, 0, 2869, 3799],
        "pagePixelSize": [2869, 3799],
        "anchor": {
            "staffY": [500, 525, 550, 575, 600],
            "tieupColumnsX": [2600 + 25 * index for index in range(7)],
            "threadingSpanX": [200, 2700],
            "score": 999,
            "continuation": False,
            "continuationOf": None,
        },
        "annotations": ([{
            "type": "tabby", "mode": "required", "scope": "all-treadlings",
            "confidence": 1.0, "raw": "USE TABBY",
        }] if control else []),
        "review": {
            "method": method,
            "sourceVisibleTreadling": True,
            "sourceTreadlingInstructions": [{"treadle": value, "count": 1}
                                             for value in rail],
            **({"sourceControlTreadling": control} if control else {}),
        },
        "draft": {
            "shafts": 4,
            "treadles": 6,
            "sourceThreadingOrder": "right-to-left",
            "sourceTreadleOrder": "right-to-left",
            "sourceTieupMarks": "lowered shafts",
            "threading": threading,
            "threadingShown": threading,
            "tieupLowered": lowered,
            "tieupLifted": lifted,
            "tieupVisualTopToBottom": visual(lowered),
            "treadling": [rail],
            "possibleTabbyControl": False,
            "diagnostics": {
                "reviewedSourceRail": True,
                "markCount": len(rail),
                "treadlingMarks": [[{"y": 700 + 25 * index, "treadle": value}
                                     for index, value in enumerate(rail)]],
                "coordinatesRelativeToBbox": True,
            },
        },
    }


def build(source: Path) -> dict:
    page40 = [
        reviewed_draft(
            40, index, THREADING_40, TIEUPS_40[tieup], rail,
            f"glyph-reviewed tie-up {tieup} and printed treadling {index}",
        )
        for index, (tieup, rail) in enumerate(RAILS_40, 1)
    ]
    page204 = [reviewed_draft(
        204, 1, THREADING_204, TIEUP_204, RAIL_204,
        "glyph-reviewed Sea Star main rail; false edge chart and post-rail marks excluded",
        control=[5, 6],
    )]
    assert [len(rail) for _tieup, rail in RAILS_40] == [6, 6, 6, 6, 4, 10, 6, 8, 6, 6, 10]
    assert len(page40) == 11 and len(RAIL_204) == 30
    assert all(rail and all(1 <= value <= 6 for value in rail)
               for _tieup, rail in RAILS_40)
    pages = []
    for page, base_id, drafts in [
        (40, "davison-ch02-n004", page40),
        (204, "davison-ch19-n006", page204),
    ]:
        pages.append({
            "pdfPage": page,
            "drafts": drafts,
            "chartGroups": [{
                "id": f"davison-p{page:03d}-reviewed-g01",
                "sourceBaseId": base_id,
                "draftIds": [draft["id"] for draft in drafts],
                "assignmentConfidence": "reviewed-source",
            }],
        })
    return {
        "source": str(source),
        "dpi": 360,
        "sourceThreadingOrder": "right-to-left",
        "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts",
        "pages": pages,
        "diagnostics": {
            "detected": 12,
            "decoded": 12,
            "failed": 0,
            "manifestEntries": 2,
            "variantCounts": {"40": 11, "204": 1},
            "pickCounts": {"40": [len(rail) for _tieup, rail in RAILS_40],
                           "204": [len(RAIL_204)]},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "davison-reviewed-birds-eye-sea-star.json")
    args = parser.parse_args()
    payload = build(args.source)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["diagnostics"]))


if __name__ == "__main__":
    main()
