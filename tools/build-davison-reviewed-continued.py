#!/usr/bin/env python3
"""Emit reviewed transcriptions for Davison's continued, multi-row drafts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).parent


def digits(*parts: str) -> list[int]:
    return [int(value) for part in parts for value in part if value.isdigit()]


# Heddle marks are written here in image order (left to right).  Reversal into
# Davison's documented right-to-left reading order happens in the page builders.
P125_TOP = digits(
    "3131413131", "4141214141", "212131314141212131314141212131314141",
    "2121312121", "3131413131", "4141214141214141214141214141",
    "3131413131", "2121312121",
)
P125_BOTTOM = digits(
    "414131312121414131312121414131312121", "4141214141",
    "3131413131", "2121312121312121312121312121",
)

P188_TOP = digits(
    "43" * 7 + "41" * 5,  # eight omitted 4/3 ends restored to printed 24
    "212121212123232323232", "34343434341414141212121",
    "23232343434141412123234",
    "1414121214141212141412121414121214141212141412121414121214141",
)
P188_BOTTOM = digits(
    "43232121414143434323232", "12121214141414343434343",
    "232323232321212121212", "141414141434343432323232",
    "12121414143432321", "414141414141414", "12323434141412121",
)

P201_FIELD = digits("14143432321214141212323434")
P201_BORDER = digits(
    "1414343232121", "414343232121", "414343232121",
    "4141212323434", "14121232343414", "12123234341414",
)
P201_RIGHT_SELVAGE = digits("12341234")
P201_LEFT_SELVAGE = digits("12341234")
P201_END_FIELD = digits("3432321214141212323434")


# Glyph-by-glyph source-rail transcriptions.  Each tuple is
# (source treadle number, numeral/count); bare dashes have count one.
P125_INSTRUCTIONS = [[(value, 1) for value in digits(
    "34345434342424542424141454141454141454141454141424",
    "24542424343454343414142424343414142424343414142424",
    "34341414541414242454242434345434345434345434345434",
    "34242454242414145414143434242414143434242414143434",
    "24241414",
)]]

P188_INSTRUCTIONS = [[
    (4, 3), (3, 2), (4, 2), (3, 2), (4, 2), (3, 2), (4, 2), (3, 2),
    (4, 2), (3, 2), (4, 2), (3, 2), (4, 2), (3, 2), (4, 2), (3, 2),
    (4, 3), (1, 1), (2, 2), (3, 2), (4, 3),
    (1, 3), (2, 3), (3, 4), (4, 4),
    (1, 5), (2, 6), (3, 6), (4, 5),
    (1, 4), (2, 4), (3, 3), (4, 2),
    (1, 2), (2, 2), (4, 10), (3, 1), (2, 2), (1, 2),
    (4, 2), (3, 3), (2, 4), (1, 4),
    (4, 5), (3, 6), (2, 6), (1, 5),
    (4, 4), (3, 4), (2, 3), (1, 3),
    (4, 3), (3, 2), (2, 2), (1, 1),
]]

P201_I = digits(
    "4123412341234321432143214",  # borders
    "12343214",                   # field repeat
    "1234321",                    # end field
)
P201_II = digits(
    "4321432143214123412341234",  # borders
    "32141234",                   # field repeat
    "3214123",                    # end field
)
P201_INSTRUCTIONS = [[(value, 2) for value in sequence]
                     for sequence in (P201_I, P201_II)]

P125_LOWERED = [[1, 4], [1, 3], [1, 2], [2, 3, 4], [1]]
P125_LIFTED = [[2, 3], [2, 4], [3, 4], [1], [2, 3, 4]]
OVERSHOT_LOWERED = [[3, 4], [2, 3], [1, 2], [1, 4], [2, 4], [1, 3]]
OVERSHOT_LIFTED = [[1, 2], [1, 4], [3, 4], [2, 3], [1, 3], [2, 4]]


def record(page: int, base_id: str, threading: list[int],
           instructions: list[list[tuple[int, int]]], rows: list[int],
           method: str, tabby: bool, lowered: list[list[int]],
           lifted: list[list[int]], columns: list[int],
           control: list[int] | None = None) -> dict:
    draft_id = f"davison-p{page:03d}-d01"
    treadling = [[treadle for treadle, count in sequence for _ in range(count)]
                 for sequence in instructions]
    cues = ([{"type": "tabby", "mode": "alternate", "confidence": 1.0,
              "raw": "USE TABBY"}] if tabby else [])
    return {
        "pdfPage": page,
        "drafts": [{
            "id": draft_id,
            "chartGroup": f"davison-p{page:03d}-g01",
            "bbox": [0, 0, 3137 if page != 188 else 3188, 4212 if page != 188 else 4222],
            "pagePixelSize": [3137 if page != 188 else 3188, 4212 if page != 188 else 4222],
            "anchor": {
                "staffY": [554, 581, 608, 635, 662],
                "tieupColumnsX": columns,
                "threadingSpanX": [200, 2820],
                "score": 999,
                "continuation": True,
                "continuationOf": None,
            },
            "annotations": cues,
            "review": {
                "method": method,
                "threadingRowLengths": rows,
                "sourceVisibleTreadling": True,
                "sourceTreadlingInstructions": [[
                    {"treadle": treadle, "count": count}
                    for treadle, count in sequence
                ] for sequence in instructions],
                **({"sourceControlTreadling": control} if control else {}),
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
                "tieupLifted": lifted,
                "tieupVisualTopToBottom": [
                    [int(4 - row in column) for column in reversed(lowered)]
                    for row in range(4)
                ],
                "treadling": treadling,
                "possibleTabbyControl": False,
                "diagnostics": {
                    "reviewedThreadingRows": rows,
                    "markCount": sum(len(sequence) for sequence in instructions),
                    "treadlingMarks": [[
                        {"y": 900 + 20 * i, "treadle": treadle, "count": count}
                        for i, (treadle, count) in enumerate(sequence)
                    ] for sequence in instructions],
                    "coordinatesRelativeToBbox": True,
                },
            },
        }],
        "chartGroups": [{
            "id": f"davison-p{page:03d}-g01",
            "sourceBaseId": base_id,
            "draftIds": [draft_id],
            "assignmentConfidence": "reviewed-source",
        }],
    }


def build(source: Path) -> dict:
    # The plate labels 208 ends, but its continued chart has one additional
    # balancing/source-visible mark at the wrap; retain all 209 marks.
    p125 = list(reversed(P125_TOP)) + [4] + list(reversed(P125_BOTTOM))
    p188 = list(reversed(P188_TOP)) + list(reversed(P188_BOTTOM))
    visual_201 = (P201_LEFT_SELVAGE + list(reversed(P201_BORDER)) + P201_END_FIELD
                  + P201_FIELD * 11 + P201_BORDER + P201_RIGHT_SELVAGE)
    p201 = list(reversed(visual_201))
    assert (len(p125), len(p188), len(p201)) == (209, 292, 480)
    assert [len(sequence) for sequence in P125_INSTRUCTIONS] == [208]
    assert [len(sequence) for sequence in P188_INSTRUCTIONS] == [55]
    assert [len(sequence) for sequence in P201_INSTRUCTIONS] == [40, 40]
    assert [sum(count for _treadle, count in sequence)
            for sequence in P188_INSTRUCTIONS] == [169]
    assert [sum(count for _treadle, count in sequence)
            for sequence in P201_INSTRUCTIONS] == [80, 80]
    pages = [
        record(125, "davison-ch11-n014", p125, P125_INSTRUCTIONS, [124, 85],
               "reviewed two-row source transcription and continued 100+108-pick rail",
               False, P125_LOWERED, P125_LIFTED, [131, 159, 186, 214, 241, 269],
               control=[4, 5]),
        record(188, "davison-ch18-n014", p188, P188_INSTRUCTIONS, [152, 140],
               "reviewed two-row transcription; printed 24-end shorthand and rail numerals expanded",
               True, OVERSHOT_LOWERED, OVERSHOT_LIFTED,
               [2879, 2907, 2934, 2961, 2988, 3015, 3042]),
        record(201, "davison-ch19-n003", p201, P201_INSTRUCTIONS, [112, 30, 338],
               "reviewed 480-end sequence reconstruction and two complete 40-glyph rails",
               True, OVERSHOT_LOWERED, OVERSHOT_LIFTED,
               [73, 100, 128, 155, 182, 209, 237]),
    ]
    return {
        "source": str(source),
        "dpi": 400,
        "sourceThreadingOrder": "right-to-left",
        "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts",
        "pages": pages,
        "diagnostics": {
            "detected": 3,
            "decoded": 3,
            "failed": 0,
            "manifestEntries": 3,
            "reviewedThreadingEnds": {"125": 209, "188": 292, "201": 480},
            "variantCounts": {"125": 1, "188": 1, "201": 2},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "davison-reviewed-continued-drafts.json")
    args = parser.parse_args()
    payload = build(args.source)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["diagnostics"]))


if __name__ == "__main__":
    main()
