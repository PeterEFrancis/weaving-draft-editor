#!/usr/bin/env python3
"""Build reviewed Chapter I data extracted from Davison's draft plates."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools/davison-manifest.json"
OUTPUT = ROOT / "tools/davison-chapter-one.json"

THREADING = [4, 3, 2, 1]
STANDARD = [[3, 4], [2, 3], [1, 2], [1, 4], [2, 4], [1, 3]]

PAGE_6 = [[4], [3], [2], [1], [2, 4], [1, 3]]
PAGE_7 = [
    [[3, 4], [1, 2]],
    [[2, 4], [3], [2], [1, 3]],
    [[3, 4], [2, 3], [1, 2], [4]],
    [[1, 2, 3], [1, 2, 4], [1, 3, 4], [2, 3, 4], [2, 4], [1, 3]],
    [[2, 3, 4], [1]],
]
PAGE_8 = [
    [[2, 3, 4], [1], [1, 3, 4], [2], [1, 2, 4], [3], [1, 2, 3], [4]],
    [[2, 3, 4], [4], [3], [1, 2, 3], [2], [1]],
    [[3, 4], [3], [2, 3], [2], [1, 2], [1], [1, 4], [4]],
]
PAGE_9 = [
    [[4], [3], [2], [1], [2, 3, 4], [1, 3, 4], [1, 2, 4], [1, 2, 3]],
    [[1, 2, 4], [2, 3, 4], [1, 3]],
    [[1, 2, 4], [1, 3, 4], [2, 3, 4], [1, 2, 3], [1, 3], [2, 4]],
    [[1, 2], [1, 2, 4], [2, 4], [2, 3], [2, 3, 4], [3, 4]],
    [[1], [1, 2], [1, 2, 3], [4], [3, 4], [2, 3, 4]],
    [[2, 4], [1, 3], [2, 3, 4]],
    STANDARD,
    STANDARD,
]
PAGE_10 = [
    [[2, 3, 4], [1, 2, 3], [1, 2, 4], [1, 3, 4], [2, 4], [1, 3]],
    STANDARD,
    [[4], [2, 3, 4], [2], [1, 2, 4]],
    [[4], [2, 3, 4], [2], [1, 2, 4]],
]

TIEUPS = (
    [STANDARD] * 12
    + [PAGE_6] * 8
    + PAGE_7
    + PAGE_8
    + PAGE_9
    + PAGE_10
)

TREADLINGS = [
    [5, 6, 5, 6],
    [1, 2, 3, 4, 1, 2, 3, 4],
    [1, 2, 3, 4, 3, 2],
    [1, 4, 3, 2, 4, 1, 2, 3],
    [1, 2, 3, 4, 3, 2, 1, 4, 3, 2, 1],
    [4, 6, 4, 5],
    [4, 5, 3, 6],
    [6, 5, 3, 1],
    [3, 1, 4, 2],
    [3, 2, 3, 1],
    [3, 1, 5, 6],
    [3, 2, 4, 1],
    [1, 2, 3, 4],
    [1, 2, 3, 4, 3, 2],
    [1, 2, 1, 2, 3, 4, 1, 2, 3, 4, 3, 4, 1, 2, 3, 4],
    [1, 2, 5, 6, 3, 4, 5, 6, 1, 3, 4, 2, 3, 1, 2, 4],
    [1, 3, 2, 4],
    [1, 2, 3],
    [4, 1, 2, 4, 3, 2, 1, 4, 3],
    [6, 5, 4, 1, 2, 3],
    [1, 2, 1, 2],
    [1, 2, 3, 4, 2, 3],
    [1, 2, 3, 4],
    [1, 2, 3, 4],
    [1, 2, 1, 2],
    [1, 2, 3, 4, 5, 6, 7, 8],
    [1, 2, 3, 4, 5, 6],
    [1, 2, 3, 4, 5, 6, 7, 8],
    [1, 2, 3, 4, 5, 6, 7, 8],
    [3, 2, 1],
    [1, 2, 3, 4, 5, 6],
    [1, 2, 3, 4, 5, 6],
    [1, 2, 3, 4, 5, 6],
    [1, 2, 1, 2, 3],
    [1, 4, 2, 3, 5, 6, 3, 2, 4, 1, 5, 6],
    [4, 6, 1, 5, 3, 6, 2, 5],
    [5, 6, 1, 2, 3, 4],
    [3, 5, 6],
    [4, 2, 3, 1],
    [4, 3, 2, 1],
]


def lifted(lowered: list[list[int]]) -> list[list[int]]:
    shafts = {1, 2, 3, 4}
    return [sorted(shafts - set(treadle)) for treadle in lowered]


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    source_entries = manifest["chapters"][0]["entries"]
    if len(source_entries) != len(TIEUPS) or len(TIEUPS) != len(TREADLINGS):
        raise ValueError("Chapter I source/extraction counts differ")

    entries = {}
    for source, tieup, treadling in zip(source_entries, TIEUPS, TREADLINGS):
        printed_page = source["printedPages"][0]
        entries[source["id"]] = {
            "id": source["id"],
            "title": source["title"],
            "printedPage": printed_page,
            "pdfPage": printed_page + 26,
            "shafts": 4,
            "treadles": len(tieup),
            "threading": THREADING,
            "tieupLowered": tieup,
            "tieupLifted": lifted(tieup),
            "treadling": treadling,
        }

    output = {
        "schemaVersion": 1,
        "chapterId": "davison-ch01",
        "sourceThreadingOrder": "right-to-left",
        "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts",
        "entryOrder": list(entries),
        "entries": entries,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
