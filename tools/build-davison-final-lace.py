#!/usr/bin/env python3
"""Build reviewed records for the final Swedish Lace and Quaker Ladies plates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PAGE_SIZE = [2869, 3799]


def lifted(lowered: list[list[int]]) -> list[list[int]]:
    return [sorted(set(range(1, 5)) - set(column)) for column in lowered]


def visual(lowered: list[list[int]]) -> list[list[int]]:
    source = list(reversed(lowered))
    return [[int(4 - row in column) for column in source] for row in range(4)]


def record(*, page: int, suffix: str, group: str, threading: list[int],
           lowered: list[list[int]], treadling: list[list[int]],
           staff: list[int], columns: list[int], span: list[int], bbox: list[int],
           tabby: bool = False, control: bool = False, review: dict | None = None) -> dict:
    return {
        "id": f"davison-p{page:03d}-finalreview-{suffix}",
        "chartGroup": group,
        "bbox": bbox,
        "pagePixelSize": PAGE_SIZE,
        "anchor": {
            "staffY": staff,
            "tieupColumnsX": columns,
            "threadingSpanX": span,
            "score": 1000,
            "continuation": False,
            "continuationOf": None,
        },
        "annotations": ([{"type": "tabby", "mode": "required", "scope": "local",
                           "confidence": 1.0, "raw": "USE TABBY"}] if tabby else []),
        "review": {
            "method": "manual source transcription from 360 dpi scan",
            **(review or {}),
        },
        "draft": {
            "shafts": 4,
            "treadles": len(lowered),
            "sourceThreadingOrder": "right-to-left",
            "sourceTreadleOrder": "right-to-left",
            "sourceTieupMarks": "lowered shafts",
            "threading": threading,
            "threadingShown": threading,
            "tieupLowered": lowered,
            "tieupLifted": lifted(lowered),
            "tieupVisualTopToBottom": visual(lowered),
            "treadling": treadling,
            "possibleTabbyControl": control,
            "diagnostics": {
                "reviewedSource": True,
                "threadingEnds": len(threading),
                "expandedRailLengths": [len(sequence) for sequence in treadling],
            },
        },
    }


TRADITIONAL_THREADING = [
    1, 2, 1, 2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1, 2, 1,
    4, 3, 4, 3, 4, 1, 4, 3, 4, 3, 4, 1, 4, 3, 4, 3, 4,
]
SARA_THREADING = [
    1, 2, 1, 2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1, 2, 1,
    4, 3, 4, 3, 4, 1, 4, 3, 4, 3, 4, 1, 4, 3, 4, 3, 4,
    1, 4, 3, 4, 3, 4, 1, 4, 3, 4, 3, 4, 1, 4, 3, 4, 3, 4,
    1, 4, 3, 4, 3, 4,
]
QUAKER_THREADING = [
    4, 3, 2, 1, 4, 3, 4, 3, 2, 3, 4, 3, 4,
    1, 2, 3, 4, 1, 2, 1, 2, 3, 2, 1, 2, 1,
]

TRADITIONAL_LOWERED = [[2, 4], [1], [4], [1, 3]]
SARA_LOWERED = [[2, 4], [1], [4], [1]]
QUAKER_LOWERED = [[3, 4], [2, 3], [1, 2], [1, 4], [2, 4], [1, 3]]
QUAKER_IX_LOWERED = [[4], [3], [2], [1], [2, 4], [1, 3]]


def repeat(sequence: list[int], count: int) -> list[int]:
    return sequence * count


def build_pages() -> list[dict]:
    traditional_i = (
        repeat([1, 2, 1, 2, 1, 4], 2)
        + [1, 2, 1, 2, 1, 4]
        + repeat([3, 4, 3, 4], 2)
        + [4, 3, 4, 3, 4]
    )
    traditional_ii = (
        repeat([1, 2, 1, 2, 1, 4], 2)
        + [1, 2, 1, 2, 1, 4, 1, 4, 1, 4, 1, 4, 1, 4, 1, 4, 1, 4, 1, 4]
    )
    traditional_iii = [1, 2, 1, 2, 1, 4]
    sara_i = (
        repeat([4, 3, 4, 3, 4, 1], 2)
        + [4, 3, 4, 3, 4]
        + repeat([1, 2, 1, 2, 1, 4], 8)
        + [1, 2, 1, 2, 1]
    )
    sara_ii = (
        repeat([1, 2, 1, 2, 1, 4], 2)
        + [1, 2, 1, 2, 1]
        + repeat([4, 3, 4, 3, 4, 1], 8)
        + [4, 3, 4, 3, 4]
    )

    p120_records = [
        record(
            page=120, suffix="traditional", group="davison-p120-finalreview-g01",
            threading=TRADITIONAL_THREADING, lowered=TRADITIONAL_LOWERED,
            treadling=[[1, 4], traditional_i, traditional_ii, traditional_iii],
            staff=[528, 554, 578, 602, 627], columns=[294, 318, 342, 367, 393],
            span=[590, 1400], bbox=[150, 450, 1500, 2900], tabby=True, control=True,
            review={"sourceRailLabels": ["PLAIN WEAVE", "I", "II", "III"],
                    "sourceThreadingSections": [17, 17],
                    "expandedRailLengths": [2, len(traditional_i), len(traditional_ii), 6]},
        ),
        record(
            page=120, suffix="sara", group="davison-p120-finalreview-g02",
            threading=SARA_THREADING, lowered=SARA_LOWERED,
            treadling=[[1, 4], sara_i, sara_ii],
            staff=[1876, 1900, 1924, 1949, 1973],
            columns=[2666, 2689, 2713, 2737, 2762], span=[1500, 2620],
            bbox=[1500, 1800, 2869, 3799], tabby=True, control=True,
            review={"sourceRailLabels": ["PLAIN WEAVE", "I", "II"],
                    "sourceThreadingSections": [41, 17],
                    "expandedRailLengths": [2, len(sara_i), len(sara_ii)]},
        ),
    ]

    quaker_sequences = [
        repeat([1], 3) + [2] + repeat([1], 3)
        + [4, 3, 2, 1, 4] + repeat([3], 3) + [2]
        + repeat([3], 3) + [4, 1, 2, 3, 4],
        repeat([3], 3) + [4] + repeat([3], 3) + [2]
        + repeat([1], 3) + [4, 3, 2] + repeat([1], 3)
        + [4, 2, 3, 4, 1, 2],
        [1, 2, 3, 4, 3, 2, 1, 4, 3, 2, 1, 4, 1, 2, 3, 4],
        repeat([1], 10) + [4, 3, 2, 1, 2, 3, 4],
        repeat([2], 10) + [1, 4, 3, 2, 3, 4, 1, 2],
        repeat([4], 9) + [1, 2, 1, 4],
        [4, 1, 2, 1, 4, 3, 2, 3],
        [2, 3, 4, 3, 2, 1, 4, 1],
        repeat([1, 2, 1, 2, 1, 2, 5, 6], 2)
        + repeat([3, 4, 3, 4, 3, 4, 5, 6], 2),
    ]
    quaker_records = []
    for index, sequence in enumerate(quaker_sequences, 1):
        alternate = index == 9
        left_side = index >= 5
        quaker_records.append(record(
            page=138, suffix=f"quaker-{index:02d}", group="davison-p138-finalreview-g01",
            threading=QUAKER_THREADING,
            lowered=QUAKER_IX_LOWERED if alternate else QUAKER_LOWERED,
            treadling=[sequence],
            staff=([2980, 3004, 3028, 3052, 3070] if alternate
                   else ([2035, 2060, 2085, 2109, 2133] if left_side
                         else [2041, 2066, 2091, 2115, 2139])),
            columns=([2220, 2244, 2268, 2292, 2316, 2340, 2364] if alternate
                     else ([2230, 2254, 2277, 2301, 2324, 2351, 2375] if left_side
                           else [2612, 2637, 2661, 2685, 2708, 2732, 2757])),
            span=[350, 2200], bbox=[800, 1950, 2869, 3730],
            tabby=index in {1, 2, 4, 5, 6, 7, 8},
            review={"sourceRailLabel": ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"][index - 1],
                    "sourceThreadingSections": [13, 13],
                    "alternateTieup": alternate,
                    "expandedRailLength": len(sequence)},
        ))

    return [
        {
            "pdfPage": 120,
            "drafts": p120_records,
            "chartGroups": [
                {"id": "davison-p120-finalreview-g01", "sourceBaseId": "davison-ch11-n001",
                 "draftIds": [p120_records[0]["id"]], "assignmentConfidence": "reviewed-source"},
                {"id": "davison-p120-finalreview-g02", "sourceBaseId": "davison-ch11-n003",
                 "draftIds": [p120_records[1]["id"]], "assignmentConfidence": "reviewed-source"},
            ],
        },
        {
            "pdfPage": 138,
            "drafts": quaker_records,
            "chartGroups": [
                {"id": "davison-p138-finalreview-g01", "sourceBaseId": "davison-ch13-n005",
                 "draftIds": [item["id"] for item in quaker_records],
                 "assignmentConfidence": "reviewed-source"},
            ],
        },
    ]


def validate(pages: list[dict]) -> dict:
    records = [item for page in pages for item in page["drafts"]]
    if len(records) != 11:
        raise RuntimeError("reviewed record count drift")
    expected = {120: {34, 58}, 138: {26}}
    for page in pages:
        lengths = {len(item["draft"]["threading"]) for item in page["drafts"]}
        if lengths != expected[page["pdfPage"]]:
            raise RuntimeError(f"threading length drift on p{page['pdfPage']}: {lengths}")
    for item in records:
        draft = item["draft"]
        if any(not 1 <= treadle <= draft["treadles"]
               for rail in draft["treadling"] for treadle in rail):
            raise RuntimeError(f"out-of-range treadle in {item['id']}")
    return {"decoded": len(records), "failed": 0,
            "threadingEnds": {"traditional": 34, "sara": 58, "quaker": 26},
            "variantCounts": {"traditional": 3, "sara": 2, "quaker": 9}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"source PDF not found: {args.source}")
    pages = build_pages()
    payload = {
        "source": str(args.source),
        "dpi": 360,
        "mergeMode": "additive",
        "sourceThreadingOrder": "per-record",
        "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts",
        "pages": pages,
        "diagnostics": validate(pages),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["diagnostics"], sort_keys=True))


if __name__ == "__main__":
    main()
