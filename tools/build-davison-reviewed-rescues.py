#!/usr/bin/env python3
"""Build source-reviewed overlays for five detached/high-page Davison drafts."""

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
    168: {
        "sourceBaseId": "davison-ch17-n001", "title": "China Leaves",
        "bbox": [0, 440, 1500, 3740], "expected": 77,
        "segments": [20, 7, 16, 15, 19],
        "rows": [(470, 650, 200, 1450, 0.0005, 24.6, 533.5, 77, 5.0)],
        "staff": [658, 682, 708, 734, 760],
        "columns": [247, 272, 296, 320, 343, 367, 391],
        "tabbyControl": [5, 6],
    },
    173: {
        "sourceBaseId": "davison-ch17-n017", "title": "Note from John Landes Book",
        "bbox": [0, 440, 1400, 1700], "expected": 82,
        "segments": [11, 10, 12, 21, 14, 14],
        "rows": [(500, 650, 100, 1320, 0.002, 24.3, 548.0, 82, 5.0)],
        "staff": [669, 692, 715, 737, 760],
        "columns": [97, 121, 146, 170, 194, 218, 243],
        "tabbyControl": [5, 6],
        "manualCues": [{"type": "tabby", "mode": "required", "scope": "local",
                        "confidence": 1.0, "raw": "USE TABBY"}],
    },
    180: {
        "sourceBaseId": "davison-ch18-n005", "title": "Isaac’s Favorite",
        "bbox": [150, 430, 2810, 1870], "expected": 142,
        "segments": [14, 51, 14, 15, 15, 18, 15],
        "rows": [(480, 650, 200, 2820, -0.005, 24.3, 535.0, 142, 5.0)],
        "staff": [649, 672, 693, 715, 735],
        "columns": [2604, 2629, 2654, 2678, 2702, 2726, 2751],
        "tabbyControl": [5, 6],
    },
    226: {
        "sourceBaseId": "davison-ch21-n014", "title": "Anne Mueller’s Crackle Weave",
        "bbox": [0, 390, 2800, 2010], "expected": 90,
        "segments": [10, 12, 12, 10, 16, 30],
        "rows": [(480, 620, 850, 2652, -0.006, 24.5, 527.0, 90, 6.0)],
        "staff": [510, 535, 560, 584, 609],
        "columns": [258, 283, 307, 332, 356, 380, 404],
        "tabbyControl": [5, 6],
        "manualCues": [{"type": "tabby", "mode": "required", "scope": "local",
                        "confidence": 1.0, "raw": "USE TABBY"}],
    },
    228: {
        "sourceBaseId": "davison-ch21-n021", "title": "Small Rose Crackle Weave",
        "bbox": [1360, 680, 2823, 3740], "expected": 82,
        "segments": [11, 10, 12, 9, 5, 10, 4, 10, 11],
        "rows": [
            (900, 1020, 1485, 2788, -0.0035, 24.4, 930.0, 61, 5.0),
            (1090, 1220, 2025, 2560, -0.005, 24.4, 1132.0, 21, 5.0),
        ],
        "staff": [1105, 1130, 1154, 1179, 1203],
        "columns": [2662, 2686, 2711, 2735, 2759, 2784, 2810],
        "tabbyControl": [5, 6],
        "manualCues": [{"type": "tabby", "mode": "required",
                        "scope": "all-treadlings", "confidence": 1.0,
                        "raw": "USE TABBY ON ALL TREADLINGS"}],
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
    y0, y1, x0, x1, slope, pitch, offset, expected, tolerance = config
    ink = (gray[y0:y1] < 175).astype(np.uint8) * 255
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
        if (x0 <= center_x <= x1 and width <= 18 and 14 <= height <= 40
                and area >= height * 0.4 and 0 <= row < 4
                and residual < tolerance):
            marks.append((float(center_x), 4 - int(row)))
    marks.sort(reverse=True)
    if len(marks) != expected:
        raise RuntimeError(f"reviewed threading row drifted: {len(marks)} != {expected}")
    return [shaft for _x, shaft in marks]


def page_cues(gray: np.ndarray, config: dict, annotations: dict) -> list[dict]:
    x0, y0, x1, y1 = config["bbox"]
    height, width = gray.shape
    cues = [cue for cue in annotations.get("cues", [])
            if x0 <= cue.get("xRatio", -1) * width <= x1
            and y0 <= cue.get("yRatio", -1) * height <= y1]
    cues.extend(config.get("manualCues", []))
    return cues


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

    x0, y0, x1, y1 = config["bbox"]
    crop = gray[y0:y1, x0:x1]
    local_staff = [value - y0 for value in staff]
    local_columns = [value - x0 for value in columns]
    padded = cv2.copyMakeBorder(crop, 0, 0, 100, 100, cv2.BORDER_CONSTANT, value=255)
    padded_columns = [value + 100 for value in local_columns]
    columns_at_y = single.track_columns(padded, padded_columns, local_staff[-1])
    separators = builder.grid_separators(padded, columns_at_y, local_staff[-1])
    treadling, marks = single.decode_treadlings(padded, columns_at_y,
                                                local_staff[-1], separators)
    tabby_control = config["tabbyControl"]
    if treadling and set(treadling[0]).issubset(set(tabby_control)):
        treadling[0] = tabby_control
    else:
        treadling.insert(0, tabby_control)
    bounds = [local_staff[-1], *separators, crop.shape[0]]
    treadling_marks = []
    for start, end in zip(bounds, bounds[1:]):
        segment = [{"y": int(y), "treadle": int(treadle)}
                   for y, treadle, _area in marks if start < y < end]
        if segment:
            treadling_marks.append(segment)

    draft_id = f"davison-p{page:03d}-reviewed-d01"
    record = {
        "id": draft_id,
        "chartGroup": f"davison-p{page:03d}-reviewed-g01",
        "bbox": config["bbox"],
        "pagePixelSize": [gray.shape[1], gray.shape[0]],
        "anchor": {
            "staffY": staff, "tieupColumnsX": columns,
            "threadingSpanX": [min(row[2] for row in config["rows"]),
                               max(row[3] for row in config["rows"])],
            "score": 999, "continuation": len(threading_rows) > 1,
            "continuationOf": None,
        },
        "annotations": page_cues(gray, config, annotations),
        "review": {
            "method": "source-checked projection and source label totals",
            "title": config["title"],
            "threadingRowLengths": [len(row) for row in threading_rows],
            "sourceSegmentTotals": config["segments"],
            "sourceTabbyControl": tabby_control,
        },
        "draft": {
            "shafts": 4, "treadles": 6,
            "sourceThreadingOrder": "right-to-left",
            "sourceTreadleOrder": "right-to-left",
            "sourceTieupMarks": "lowered shafts",
            "threading": threading, "threadingShown": threading,
            "tieupLowered": lowered, "tieupLifted": lifted,
            "tieupVisualTopToBottom": visual, "treadling": treadling,
            "possibleTabbyControl": True,
            "diagnostics": {
                "staffY": local_staff, "tieupColumnsX": local_columns,
                "separatorY": separators, "markCount": len(marks),
                "treadlingMarks": treadling_marks,
                "coordinatesRelativeToBbox": True,
                "reviewedThreadingRows": [len(row) for row in threading_rows],
            },
        },
    }
    return {
        "pdfPage": page, "drafts": [record],
        "chartGroups": [{
            "id": f"davison-p{page:03d}-reviewed-g01",
            "sourceBaseId": config["sourceBaseId"], "draftIds": [draft_id],
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
    single = load("davison_single_reviewed_rescues", "extract-davison-drafts.py")
    builder = load("davison_builder_reviewed_rescues", "build-davison-catalog.py")
    source_annotations = json.loads(args.annotations.read_text())
    annotations = {int(item["pdfPage"]): item for item in source_annotations["pages"]}
    pages = [extract_page(single.render(args.source, page, args.dpi), page,
                          single, builder, annotations.get(page, {}))
             for page in sorted(PAGES)]
    payload = {
        "source": str(args.source), "dpi": args.dpi,
        "sourceThreadingOrder": "right-to-left",
        "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts", "pages": pages,
        "diagnostics": {
            "detected": len(pages), "decoded": len(pages), "failed": 0,
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
