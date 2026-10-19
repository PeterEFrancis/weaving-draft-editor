#!/usr/bin/env python3
"""Build reviewed source overlays for Davison's two full-width overshot drafts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).parent

PAGES = {
    177: {
        "sourceBaseId": "davison-ch18-n002",
        "expected": 332,
        "staff": [486, 511, 536, 560, 583],
        "columns": [116, 141, 166, 190, 214, 239, 263],
        "rows": [
            (470, 620, 520, 2600, 0.014, 24.25, 497.0, 144),
            (650, 805, 520, 2650, 0.012, 24.25, 685.5, 138),
            (850, 990, 1800, 2650, 0.004, 24.25, 882.0, 50),
        ],
    },
    178: {
        "sourceBaseId": "davison-ch18-n003",
        "expected": 340,
        "staff": [493, 519, 545, 571, 595],
        "columns": [2596, 2620, 2645, 2669, 2693, 2718, 2742],
        "rows": [
            (450, 590, 270, 2340, 0.005, 24.5, 485.5, 136),
            (635, 775, 270, 2340, 0.004, 24.5, 670.0, 136),
            (830, 970, 1330, 2340, 0.002, 24.0, 866.5, 68),
        ],
    },
}


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def decode_row(gray: np.ndarray, config: tuple) -> list[int]:
    y0, y1, x0, x1, slope, pitch, offset, expected = config
    region = gray[y0:y1]
    ink = (region < 175).astype(np.uint8) * 255
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 8)),
    )
    count, _labels, stats, centers = cv2.connectedComponentsWithStats(vertical)
    marks = []
    for index in range(1, count):
        _x, _y, width, height, area = stats[index]
        center_x, center_y = centers[index]
        center_y += y0
        row = round((center_y - offset - slope * center_x) / pitch)
        residual = abs(center_y - offset - slope * center_x - row * pitch)
        if (x0 <= center_x <= x1 and width <= 18 and 16 <= height <= 38
                and area >= height * 0.45 and 0 <= row < 4 and residual < 4):
            marks.append((float(center_x), 4 - int(row)))
    marks.sort(reverse=True)
    if len(marks) != expected:
        raise RuntimeError(f"reviewed threading row drifted: {len(marks)} != {expected}")
    return [shaft for _x, shaft in marks]


def extract_page(gray: np.ndarray, page: int, single, builder, annotations: dict) -> dict:
    config = PAGES[page]
    threading_rows = [decode_row(gray, row) for row in config["rows"]]
    threading = [shaft for row in threading_rows for shaft in row]
    if len(threading) != config["expected"]:
        raise RuntimeError(f"page {page}: {len(threading)} ends != {config['expected']}")

    staff, columns = config["staff"], config["columns"]
    lowered, visual = single.decode_tieup(gray, staff, columns)
    all_shafts = set(range(1, 5))
    lifted = [sorted(all_shafts - set(column)) for column in lowered]
    columns_at_y = single.track_columns(gray, columns, staff[-1])
    separators = builder.grid_separators(gray, columns_at_y, staff[-1])
    treadling, marks = single.decode_treadlings(
        gray, columns_at_y, staff[-1], separators,
    )
    if len(treadling) != 2 or len(treadling[0]) != 2:
        raise RuntimeError(f"page {page}: source treadling review drifted")
    bounds = [staff[-1], *separators, gray.shape[0]]
    treadling_marks = []
    for start, end in zip(bounds, bounds[1:]):
        segment = [
            {"y": int(y), "treadle": int(treadle)}
            for y, treadle, _area in marks if start < y < end
        ]
        if segment:
            treadling_marks.append(segment)

    height, width = gray.shape
    cues = annotations.get(page, {}).get("cues", [])
    draft_id = f"davison-p{page:03d}-d01"
    record = {
        "id": draft_id,
        "chartGroup": f"davison-p{page:03d}-g01",
        "bbox": [0, 0, width, height],
        "pagePixelSize": [width, height],
        "anchor": {
            "staffY": staff,
            "tieupColumnsX": columns,
            "threadingSpanX": [min(row[2] for row in config["rows"]),
                               max(row[3] for row in config["rows"])],
            "score": 999,
            "continuation": False,
            "continuationOf": None,
        },
        "annotations": cues,
        "review": {
            "method": "source-checked multi-row projection",
            "threadingRowLengths": [len(row) for row in threading_rows],
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
            "tieupVisualTopToBottom": visual,
            "treadling": treadling,
            "possibleTabbyControl": True,
            "diagnostics": {
                "staffY": staff,
                "tieupColumnsX": columns,
                "separatorY": separators,
                "markCount": len(marks),
                "treadlingMarks": treadling_marks,
                "coordinatesRelativeToBbox": True,
                "reviewedThreadingRows": [len(row) for row in threading_rows],
            },
        },
    }
    return {
        "pdfPage": page,
        "drafts": [record],
        "chartGroups": [{
            "id": f"davison-p{page:03d}-g01",
            "sourceBaseId": config["sourceBaseId"],
            "draftIds": [draft_id],
            "assignmentConfidence": "reviewed-source",
        }],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--dpi", type=int, default=360)
    parser.add_argument("--annotations", type=Path,
                        default=ROOT / "davison-annotations.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    single = load("davison_single_large_overshot", "extract-davison-drafts.py")
    builder = load("davison_builder_large_overshot", "build-davison-catalog.py")
    source_annotations = json.loads(args.annotations.read_text())
    annotations = {int(item["pdfPage"]): item for item in source_annotations["pages"]}
    pages = [
        extract_page(single.render(args.source, page, args.dpi), page,
                     single, builder, annotations)
        for page in sorted(PAGES)
    ]
    payload = {
        "source": str(args.source),
        "dpi": args.dpi,
        "sourceThreadingOrder": "right-to-left",
        "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts",
        "pages": pages,
        "diagnostics": {
            "detected": len(pages),
            "decoded": len(pages),
            "failed": 0,
            "manifestEntries": len(pages),
            "reviewedThreadingEnds": {
                str(page): PAGES[page]["expected"] for page in sorted(PAGES)
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["diagnostics"]))


if __name__ == "__main__":
    main()
