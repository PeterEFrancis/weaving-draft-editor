#!/usr/bin/env python3
"""Build additive source-reviewed bindings for Davison pages 98, 108, and 116."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PAGE_SIZE = [2869, 3799]


def lifted(lowered: list[list[int]], shafts: int = 4) -> list[list[int]]:
    all_shafts = set(range(1, shafts + 1))
    return [sorted(all_shafts - set(column)) for column in lowered]


def visual(lowered: list[list[int]], shafts: int = 4) -> list[list[int]]:
    return [
        [int(shaft in column) for column in reversed(lowered)]
        for shaft in range(shafts, 0, -1)
    ]


def expand(raw: list[int], multipliers: list[int]) -> list[int]:
    return [value for value, count in zip(raw, multipliers) for _ in range(count)]


EPHRATA_THREADING = [4, 3, 2, 1, 4, 3, 2, 1, 4, 3, 2, 1]

GERMAN_1_THREADING = [
    4, 3, 4, 3, 4, 3,
    4, 2, 4, 3, 1, 3,
    4, 2, 4, 3, 1, 3,
]

GERMAN_2_THREADING = [
    4, 3, 4, 3, 4, 3, 4, 3,
    4, 2, 4, 2, 4, 3, 1, 3, 1, 3,
    4, 3, 1, 3, 1, 3, 4, 2, 4, 2, 4, 3,
]

GERMAN_LOWERED = [[4], [2, 3], [3], [1, 4]]
GERMAN_RAILS = [
    [2, 4],
    [4, 3, 4, 3, 4, 2, 1, 2, 1, 2],
    [4, 3, 4, 2, 1, 2],
    [4, 3, 4, 3, 4, 2, 4, 3, 4, 3, 4, 2, 1, 2, 1, 2, 4, 2, 1, 2, 1, 2],
]

PENNYPACKER_TOP = [
    2, 1, 2, 1, 3, 1, 3, 1, 4, 1, 4, 1, 2, 1, 2, 1, 3, 1, 3, 1, 2, 1, 2, 1,
    3, 1, 3, 1, 2, 1, 2, 1, 4, 1, 4, 1, 3, 1, 3, 1, 2, 1, 2, 1, 3, 1, 3, 1,
    4, 1, 4, 1, 2, 1, 2, 1, 3, 1, 3, 1, 2, 1, 2, 1, 3, 1, 3, 1, 2, 1, 2, 1,
]
PENNYPACKER_BOTTOM = [
    1, 3, 1, 3, 1, 4, 1, 4, 1, 2, 1, 2, 1, 3, 1, 3, 1, 2, 1, 2, 1, 3, 1, 3,
    1, 2, 1, 2, 1, 4, 1, 4, 1, 2, 1, 4, 1, 4, 1, 2, 1, 4, 1, 4, 1, 2, 1, 4,
    1, 4, 1, 2, 1, 4, 1, 4, 1, 2, 1, 4, 1, 4,
]
PENNYPACKER_LOWERED = [[1, 2], [1, 3], [1, 4], [2, 3, 4], [1]]
PENNYPACKER_I = [1, 2, 1, 2, 1, 3, 2, 1, 2, 3, 1, 2, 1, 2, 1, 3, 2, 1, 2, 3, 1, 2, 1, 2, 1]
PENNYPACKER_II = [3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3]
PENNYPACKER_I_MULTIPLIERS = [2] * 25
PENNYPACKER_II_MULTIPLIERS = [2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2]


def record(*, page: int, suffix: str, source_id: str, title: str,
           bbox: list[int], threading: list[int], lowered: list[list[int]],
           treadling: list[list[int]], review: dict, possible_tabby: bool = False,
           source_order: str = "right-to-left", annotations: list[dict] | None = None) -> dict:
    draft_id = f"davison-p{page:03d}-midreview-{suffix}"
    group_id = f"davison-p{page:03d}-midreview-g{suffix[1:]}"
    shafts = 4
    return {
        "id": draft_id,
        "chartGroup": group_id,
        "bbox": bbox,
        "pagePixelSize": PAGE_SIZE,
        "anchor": {"score": 1000, "continuation": "continuation" in source_order,
                   "continuationOf": None},
        "annotations": annotations or [],
        "review": {"method": "manual source transcription from 360/720 dpi scan",
                   "title": title, **review},
        "draft": {
            "shafts": shafts, "treadles": len(lowered),
            "sourceThreadingOrder": source_order,
            "sourceTreadleOrder": "right-to-left",
            "sourceTieupMarks": "lowered shafts",
            "threading": threading, "threadingShown": threading,
            "tieupLowered": lowered, "tieupLifted": lifted(lowered, shafts),
            "tieupVisualTopToBottom": visual(lowered, shafts),
            "treadling": treadling,
            "possibleTabbyControl": possible_tabby,
            "diagnostics": {"reviewedSource": True, "threadingEnds": len(threading),
                            "visibleRailLengths": review.get("sourceVisibleRailLengths",
                                                            [len(rail) for rail in treadling])},
        },
        "_binding": {"sourceBaseId": source_id, "title": title},
    }


def build_pages() -> list[dict]:
    ephrata_lowered = [[2, 4], [1, 3]]
    ephrata = record(
        page=98, suffix="d01", source_id="davison-ch08-n003",
        title="Ephrata Curtain Material", bbox=[230, 2510, 1590, 3740],
        threading=EPHRATA_THREADING, lowered=ephrata_lowered,
        treadling=[[1, 2, 1, 2]],
        review={
            "sourceThreadingSections": [4, 4, 4],
            "sourceVisibleRailLengths": [4],
            "printedInstructions": [
                "THREAD 20 ENDS IN REED - LEAVE 10 DENTS EMPTY - REPEAT.",
                "WEAVE 20 PICKS - LEAVE EQUAL SIZED SPACE - REPEAT.",
                "KEEP WARP TAUT WHILE WEAVING.",
            ],
        },
        annotations=[{"type": "repeat", "scope": "local", "confidence": 1.0,
                      "raw": "REPEAT"}],
    )

    german_common_review = {
        "sourceVisibleRailLengths": [2, 10, 6, 22],
        "sourceRailLabels": ["PLAIN WEAVE", "I", "II", "III"],
        "sourceTabbyControl": [2, 4],
    }
    german_1 = record(
        page=108, suffix="d01", source_id="davison-ch09-n008",
        title="German Huck-A-Back - No. 1", bbox=[210, 250, 1130, 2050],
        threading=GERMAN_1_THREADING, lowered=GERMAN_LOWERED,
        treadling=GERMAN_RAILS,
        review={**german_common_review, "sourceThreadingSections": [6, 6, 6]},
        possible_tabby=True,
        annotations=[{"type": "tabby", "mode": "required", "scope": "local",
                      "confidence": 1.0, "raw": "PLAIN WEAVE"}],
    )
    german_2 = record(
        page=108, suffix="d02", source_id="davison-ch09-n009",
        title="German Huck-A-Back - No. 2", bbox=[1120, 250, 1930, 2050],
        threading=GERMAN_2_THREADING, lowered=GERMAN_LOWERED,
        treadling=GERMAN_RAILS,
        review={**german_common_review, "sourceThreadingSections": [8, 10, 12]},
        possible_tabby=True,
        annotations=[{"type": "tabby", "mode": "required", "scope": "local",
                      "confidence": 1.0, "raw": "PLAIN WEAVE"}],
    )

    pennypacker_raw = [[4], PENNYPACKER_I, PENNYPACKER_II]
    pennypacker_multipliers = [[1], PENNYPACKER_I_MULTIPLIERS,
                               PENNYPACKER_II_MULTIPLIERS]
    pennypacker = record(
        page=116, suffix="d01", source_id="davison-ch10-n022",
        title="Pennypacker Linen", bbox=[1500, 1800, 2810, 3700],
        threading=PENNYPACKER_TOP + PENNYPACKER_BOTTOM,
        lowered=PENNYPACKER_LOWERED,
        treadling=[[4], expand(PENNYPACKER_I, PENNYPACKER_I_MULTIPLIERS),
                   expand(PENNYPACKER_II, PENNYPACKER_II_MULTIPLIERS)],
        review={
            "threadingRowLengths": [72, 62],
            "sourceThreadingSectionLabels": [[20, 20, 20, 20], [34, 20]],
            "sourceUnlabelledContinuationEnds": 8,
            "sourceVisibleTreadling": pennypacker_raw,
            "sourceTreadlingMultipliers": pennypacker_multipliers,
            "sourceVisibleRailLengths": [1, 25, 11],
            "expandedRailLengths": [1, 50, 17],
            "sourceRailLabels": ["TABBY", "I", "II"],
            "sourceTabbyControl": [4],
        },
        possible_tabby=True,
        source_order="continuation path: top left-to-right, bottom right-to-left",
        annotations=[{"type": "tabby", "mode": "required", "scope": "local",
                      "confidence": 1.0, "raw": "USE TABBY"}],
    )

    records_by_page = {98: [ephrata], 108: [german_1, german_2], 116: [pennypacker]}
    pages = []
    for page, records in records_by_page.items():
        groups = []
        for item in records:
            binding = item.pop("_binding")
            groups.append({
                "id": item["chartGroup"], "sourceBaseId": binding["sourceBaseId"],
                "draftIds": [item["id"]], "assignmentConfidence": "reviewed-source",
            })
        pages.append({"pdfPage": page, "drafts": records, "chartGroups": groups})
    return pages


def validate(pages: list[dict]) -> dict:
    records = [record for page in pages for record in page["drafts"]]
    expected = {"davison-p098-midreview-d01": 12, "davison-p108-midreview-d01": 18,
                "davison-p108-midreview-d02": 30, "davison-p116-midreview-d01": 134}
    actual = {item["id"]: len(item["draft"]["threading"]) for item in records}
    if actual != expected:
        raise RuntimeError(f"reviewed threading length drift: {actual}")
    for item in records:
        draft = item["draft"]
        if len(draft["tieupLowered"]) != draft["treadles"]:
            raise RuntimeError(f"tie-up width drift: {item['id']}")
        if any(not 1 <= treadle <= draft["treadles"]
               for rail in draft["treadling"] for treadle in rail):
            raise RuntimeError(f"treadling out of range: {item['id']}")
    return {"decoded": len(records), "failed": 0, "threadingEnds": actual,
            "p116ExpandedRailLengths": [1, 50, 17]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"source PDF not found: {args.source}")
    pages = build_pages()
    payload = {
        "source": str(args.source), "dpi": 360, "mergeMode": "additive",
        "sourceThreadingOrder": "per-record", "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts", "pages": pages,
        "diagnostics": validate(pages),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["diagnostics"], sort_keys=True))


if __name__ == "__main__":
    main()
