#!/usr/bin/env python3
"""Retry Davison pages whose connected grid lines hide the five-row staff."""

from __future__ import annotations

import argparse
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np


def load_builder():
    path = Path(__file__).with_name("build-davison-catalog.py")
    spec = importlib.util.spec_from_file_location("davison_batch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def row_peaks(horizontal: np.ndarray) -> list[int]:
    height, width = horizontal.shape
    strength = (horizontal > 0).sum(axis=1)
    candidates = [
        y for y in range(4, height - 4)
        if strength[y] >= strength[y - 4:y + 5].max()
        and strength[y] >= width * 0.025
    ]
    kept: list[int] = []
    for y in sorted(candidates, key=lambda value: strength[value], reverse=True):
        if all(abs(y - other) > 4 for other in kept):
            kept.append(y)
    return sorted(kept)


def staff_candidates(rows: list[int], height: int) -> list[list[int]]:
    minimum, maximum = height * 0.0045, height * 0.0095

    def nearest(target: float) -> int:
        index = bisect_left(rows, target)
        options = rows[max(0, index - 1):min(len(rows), index + 1)]
        return min(options, key=lambda row: abs(row - target))

    scored: dict[tuple[int, ...], float] = {}
    steps = int((maximum - minimum) * 2) + 1
    for start in rows:
        choices: dict[tuple[int, ...], float] = {}
        for step in range(steps):
            pitch = minimum + step * 0.5
            chosen = tuple(nearest(start + i * pitch) for i in range(5))
            error = sum(abs(row - start - i * pitch) for i, row in enumerate(chosen))
            if len(set(chosen)) < 5 or error > max(4, pitch * 0.45):
                continue
            choices[chosen] = min(choices.get(chosen, math.inf), error)
        for chosen, error in sorted(choices.items(), key=lambda item: item[1])[:4]:
            scored[chosen] = min(scored.get(chosen, math.inf), error)
    return [list(key) for key, _error in sorted(scored.items(), key=lambda item: item[1])]


def projection_anchors(gray: np.ndarray, builder, single) -> list:
    height, width = gray.shape
    ink = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, width // 45), 1)),
    )
    anchors = []
    for staff in staff_candidates(row_peaks(horizontal), height):
        pitch = float(np.median(np.diff(staff)))
        bands = [
            np.max(horizontal[max(0, y - 4):min(height, y + 5)] > 0, axis=0)
            for y in staff
        ]
        common = np.all(bands, axis=0).astype(np.uint8)
        common = cv2.morphologyEx(
            common.reshape(1, -1),
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, int(pitch * 2)), 1)),
        ).ravel()
        spans = builder.runs(common, max(int(width * 0.02), int(pitch * 3.5)))
        for span in spans:
            for raw_columns in builder.regular_columns(builder.vertical_peaks(gray, staff, span), pitch):
                at_left = abs(raw_columns[0] - span[0]) <= pitch * 3
                at_right = abs(raw_columns[-1] - span[1]) <= pitch * 3
                if not (at_left or at_right):
                    continue
                valid = builder.valid_column_run(gray, staff, raw_columns, single)
                if valid is None:
                    continue
                columns, quality = valid
                support = builder.rail_support(gray, staff, columns)
                if support >= 0.18:
                    anchors.append(builder.Anchor(
                        staff, columns, span, quality + support * 80,
                    ))
    anchors.sort(key=lambda anchor: anchor.score, reverse=True)
    kept = []
    for anchor in anchors:
        box = (anchor.columns[0], anchor.staff[0], anchor.columns[-1], anchor.staff[-1])
        duplicate = False
        for existing in kept:
            other = (existing.columns[0], existing.staff[0], existing.columns[-1], existing.staff[-1])
            overlap_x = max(0, min(box[2], other[2]) - max(box[0], other[0]))
            overlap_y = max(0, min(box[3], other[3]) - max(box[1], other[1]))
            smaller = min(
                max(1, (box[2] - box[0]) * (box[3] - box[1])),
                max(1, (other[2] - other[0]) * (other[3] - other[1])),
            )
            if overlap_x * overlap_y > 0.45 * smaller:
                duplicate = True
                break
        if not duplicate:
            kept.append(anchor)
    return kept


def combined_detector(original, builder, single):
    def detect(gray, _single=None):
        anchors = original(gray, single)
        for candidate in projection_anchors(gray, builder, single):
            if all(
                abs(candidate.staff[0] - anchor.staff[0]) > candidate.pitch
                or abs(candidate.columns[0] - anchor.columns[0]) > candidate.pitch
                for anchor in anchors
            ):
                anchors.append(candidate)
        return sorted(anchors, key=lambda anchor: (anchor.staff[0], anchor.span[0]))
    return detect


def guarded_track_columns(gray: np.ndarray, columns: list[int], top: int) -> np.ndarray:
    """Track edge rails without taking a maximum over an empty clipped slice."""
    height, width = gray.shape
    base = np.asarray(columns, dtype=float)
    band_radius = max(15, height // 180)
    centers = np.arange(top, height, max(40, height // 50))
    search = range(-max(20, int(width * 0.025)), max(10, int(width * 0.01)) + 1)
    accepted, shifts = [], []
    for y in centers:
        band = gray[max(top, y - band_radius):min(height, y + band_radius + 1)]
        projection = (band < 185).sum(axis=0)
        scored = []
        for shift in search:
            score = 0
            for expected in base:
                x = int(round(expected + shift))
                left, right = max(0, x - 2), min(width, x + 3)
                if left < right:
                    score += int(np.max(projection[left:right]))
            scored.append(score)
        best = int(np.argmax(scored))
        if scored[best] >= band.shape[0] * len(base) * 0.28:
            accepted.append(int(y))
            shifts.append(float(list(search)[best]))
    if len(shifts) < 2:
        raise ValueError("Could not track the treadling grid")
    coefficient = np.polyfit(accepted, shifts, 1)
    return base[None, :] + np.polyval(coefficient, np.arange(height))[:, None]


def reviewed_page_39(gray: np.ndarray, builder, single, annotations: dict | None) -> dict:
    """Decode the five source-verified rails on the skewed Bird's Eye plate."""
    anchors = [
        builder.Anchor([323, 346, 371, 395, 417], [120, 144, 168, 193, 216, 240, 264], (118, 1900), 999),
        builder.Anchor([328, 350, 374, 398, 421], [575, 599, 624, 648, 672, 696, 720], (118, 1900), 999),
        builder.Anchor([1683, 1711, 1735, 1760, 1782], [92, 118, 142, 166, 188, 214, 238], (118, 1900), 999, True, (323, 120)),
        builder.Anchor([2610, 2632, 2653, 2674, 2694], [529, 553, 577, 601, 625, 649, 673], (118, 1900), 999, True, (328, 575)),
        builder.Anchor([3134, 3158, 3182, 3206, 3230], [512, 537, 561, 585, 609, 633, 657], (118, 1900), 999, True, (328, 575)),
    ]
    detect, continuations = builder.detect_anchors, builder.continuation_anchors
    try:
        builder.detect_anchors = lambda _gray, _single=None: anchors
        builder.continuation_anchors = lambda _gray, found, _single: found
        page = builder.extract_page(gray, 39, single, annotations)
    finally:
        builder.detect_anchors, builder.continuation_anchors = detect, continuations

    first, second = page["drafts"][:2]
    left = first["draft"]["treadling"]
    right = second["draft"]["treadling"]
    if len(left) != 5 or len(right) != 8:
        raise RuntimeError(f"page 39 rail review drifted: {len(left)} left, {len(right)} right")
    first["draft"]["treadling"] = left[:3] + [left[3] + left[4]]
    second["draft"]["treadling"] = [right[0] + right[1]] + right[2:]
    for record in page["drafts"]:
        draft = record["draft"]
        draft["threading"] = [4, 3, 2, 1, 2, 3]
        draft["threadingShown"] = [4, 3, 2, 1, 2, 3]
        draft["possibleTabbyControl"] = False
    page["chartGroups"] = [{
        "id": "davison-p039-g01",
        "sourceBaseId": "davison-ch02-n003",
        "draftIds": [record["id"] for record in page["drafts"]],
        "assignmentConfidence": "reviewed",
    }]
    return page


def reviewed_page_with_extra_anchor(
    gray: np.ndarray, page_number: int, builder, single, annotations: dict | None,
) -> dict:
    specs = {
        94: builder.Anchor([1976, 2000, 2024, 2048, 2073],
                           [2647, 2671, 2695, 2719, 2744],
                           (1400, 2749), 999),
        96: builder.Anchor([1865, 1889, 1914, 1938, 1963],
                           [2648, 2673, 2697, 2721, 2745],
                           (1500, 2750), 999),
        121: builder.Anchor([2188, 2212, 2236, 2260, 2284],
                            [2461, 2484, 2508, 2532, 2557],
                            (1369, 2564), 999),
        140: builder.Anchor([2098, 2123, 2147, 2172, 2196],
                            [2643, 2668, 2692, 2716, 2740, 2764, 2789],
                            (1400, 2794), 999),
    }
    detect = builder.detect_anchors
    anchors = detect(gray, single)
    anchors.append(specs[page_number])
    try:
        builder.detect_anchors = lambda _gray, _single=None: anchors
        return builder.extract_page(gray, page_number, single, annotations)
    finally:
        builder.detect_anchors = detect


def decode_reviewed_rail(
    gray: np.ndarray, columns: list[int], start: int, cap: int, builder, single,
) -> tuple[list[list[int]], list[list[dict]], list[int], tuple[int, int, int, int]]:
    pitch = float(np.median(np.diff(columns)))
    x0 = max(0, int(columns[0] - pitch * 7))
    x1 = min(gray.shape[1], int(columns[-1] + pitch * 7))
    y0 = max(0, int(start - pitch * 3))
    crop = gray[y0:cap, x0:x1]
    local_columns = [value - x0 for value in columns]
    local_top = start - y0
    columns_at_y = single.track_columns(crop, local_columns, local_top)
    separators = builder.grid_separators(crop, columns_at_y, local_top)
    treadling, marks = single.decode_treadlings(
        crop, columns_at_y, local_top, separators,
    )
    global_separators = [value + y0 for value in separators]
    bounds = [start, *global_separators, cap]
    treadling_marks = []
    for lower, upper in zip(bounds, bounds[1:]):
        segment = [
            {"y": y + y0, "treadle": treadle, "area": area}
            for y, treadle, area in marks if lower < y + y0 < upper
        ]
        if segment:
            treadling_marks.append(segment)
    return treadling, treadling_marks, global_separators, (x0, y0, x1, cap)


def reviewed_detached_page(
    gray: np.ndarray, page_number: int, builder, single, annotations: dict | None,
) -> dict:
    specs = {
        63: {
            "keepAfter": 1800,
            "threadStaff": [495, 521, 545, 570, 594],
            "threadSpan": (105, 1524),
            "tieupStaff": [660, 687, 712, 737, 762],
            "tieupColumns": [105, 130, 154, 178, 202, 227, 251],
            "rails": [
                ([105, 130, 154, 178, 202, 227, 251], 762, 2000),
                ([461, 486, 510, 534, 558, 583, 608], 762, 2000),
            ],
        },
        87: {
            "keepAfter": 2400,
            "threadStaff": [545, 569, 594, 618, 642],
            "threadSpan": (52, 2420),
            "tieupStaff": [702, 727, 750, 777, 800],
            "tieupColumns": [52, 76, 101, 125, 149, 174, 198],
            "rails": [
                ([52, 76, 101, 125, 149, 174, 198], 800, 2145),
                ([474, 498, 522, 547, 571, 596, 620], 800, 1840),
            ],
        },
        88: {
            "keepAfter": 2000,
            "threadStaff": [494, 514, 539, 563, 587],
            "threadSpan": (220, 2640),
            "tieupStaff": [494, 514, 539, 563, 587],
            "tieupColumns": [2640, 2664, 2688, 2712, 2736, 2760, 2786],
            "rails": [
                ([2238, 2262, 2286, 2310, 2334, 2358, 2384], 703, 2090),
                ([2640, 2664, 2688, 2712, 2736, 2760, 2786], 587, 2090),
            ],
        },
        90: {
            "keepAfter": 1800,
            "threadStaff": [524, 548, 572, 596, 620],
            "threadSpan": (252, 2642),
            "tieupStaff": [674, 697, 721, 744, 770],
            "tieupColumns": [2642, 2666, 2690, 2714, 2738, 2762],
            "rails": [
                ([2642, 2666, 2690, 2714, 2738, 2762], 770, 1980),
            ],
        },
    }
    spec = specs[page_number]
    detected = [anchor for anchor in builder.detect_anchors(gray, single)
                if anchor.staff[0] >= spec["keepAfter"]
                or (page_number == 63 and anchor.columns[0] > 2000)]
    manual = [builder.Anchor(
        spec["tieupStaff"], columns, spec["threadSpan"], 999,
    ) for columns, _start, _cap in spec["rails"]]
    if page_number == 90:
        detected = []
        bottom_staff = [2110, 2128, 2152, 2176, 2200]
        bottom_span = (250, 2619)
        bottom_left = [2236, 2260, 2284, 2308, 2332, 2356, 2380]
        bottom_right = [2619, 2642, 2666, 2690, 2714, 2738, 2762]
        manual.extend([
            builder.Anchor(bottom_staff, bottom_left, bottom_span, 999),
            builder.Anchor(bottom_staff, bottom_right, bottom_span, 999),
        ])
    anchors = sorted(detected + manual,
                     key=lambda anchor: (anchor.staff[0], anchor.span[0], anchor.columns[0]))
    detect, continuations = builder.detect_anchors, builder.continuation_anchors
    try:
        builder.detect_anchors = lambda _gray, _single=None: anchors
        builder.continuation_anchors = lambda _gray, found, _single: found
        result = builder.extract_page(gray, page_number, single, annotations)
    finally:
        builder.detect_anchors, builder.continuation_anchors = detect, continuations

    threading = builder.decode_threading_region(
        gray, spec["threadStaff"], *spec["threadSpan"],
    )
    lowered, visual = single.decode_tieup(
        gray, spec["tieupStaff"], spec["tieupColumns"],
    )
    all_shafts = set(range(1, 5))
    lifted = [sorted(all_shafts - set(column)) for column in lowered]
    for columns, start, cap in spec["rails"]:
        record = next(draft for draft in result["drafts"]
                      if draft["anchor"]["staffY"] == spec["tieupStaff"]
                      and draft["anchor"]["tieupColumnsX"] == columns)
        record["draft"] = {
            "shafts": 4,
            "treadles": len(spec["tieupColumns"]) - 1,
            "sourceThreadingOrder": "right-to-left",
            "sourceTreadleOrder": "right-to-left",
            "sourceTieupMarks": "lowered shafts",
            "tieupLowered": lowered,
            "tieupLifted": lifted,
            "tieupVisualTopToBottom": visual,
        }
        record.pop("error", None)
        treadling, marks, separators, box = decode_reviewed_rail(
            gray, columns, start, cap, builder, single,
        )
        record["bbox"] = list(box)
        if annotations:
            height, width = gray.shape
            record["annotations"] = [cue for cue in annotations.get("cues", [])
                                     if box[0] <= cue.get("xRatio", -1) * width <= box[2]
                                     and box[1] <= cue.get("yRatio", -1) * height <= box[3]]
        draft = record["draft"]
        draft["threading"] = builder.tolerant_period(threading)
        draft["threadingShown"] = threading
        draft["treadling"] = treadling
        draft["possibleTabbyControl"] = bool(
            len(treadling) > 1
            and set(treadling[0]).issubset({len(columns) - 2, len(columns) - 1})
        )
        draft["diagnostics"] = {
            "staffY": spec["tieupStaff"],
            "tieupColumnsX": columns,
            "separatorY": separators,
            "markCount": sum(map(len, marks)),
            "treadlingMarks": [[
                {**mark, "y": mark["y"] - box[1]} for mark in segment
            ] for segment in marks],
            "coordinatesRelativeToBbox": True,
            "reviewedDetachedLayout": True,
        }

    def absolute_marks(record: dict, sequence_index: int) -> list[dict]:
        local_top = record["bbox"][1]
        groups = record["draft"]["diagnostics"]["treadlingMarks"]
        return [{**mark, "y": mark["y"] + local_top}
                for mark in groups[sequence_index]]

    def empty_record(record: dict) -> None:
        record["draft"]["treadling"] = []
        diagnostics = record["draft"]["diagnostics"]
        diagnostics["treadlingMarks"] = []
        diagnostics["markCount"] = 0

    if page_number == 63:
        left = next(draft for draft in result["drafts"]
                    if draft["anchor"]["tieupColumnsX"][0] == 105)
        right = next(draft for draft in result["drafts"]
                     if draft["anchor"]["tieupColumnsX"][0] == 461)
        left_marks = absolute_marks(left, 1)
        right_marks = absolute_marks(right, 0)
        right["bbox"][0] = min(left["bbox"][0], right["bbox"][0])
        local_top = right["bbox"][1]
        right["draft"]["treadling"] = [[
            *left["draft"]["treadling"][1], *right["draft"]["treadling"][0],
        ]]
        right["draft"]["diagnostics"]["treadlingMarks"] = [[
            *[{**mark, "y": mark["y"] - local_top} for mark in left_marks],
            *[{**mark, "y": mark["y"] - local_top} for mark in right_marks],
        ]]
        right["draft"]["diagnostics"]["markCount"] = len(left_marks) + len(right_marks)
        empty_record(left)
    elif page_number == 88:
        left = next(draft for draft in result["drafts"]
                    if draft["anchor"]["tieupColumnsX"][0] == 2238)
        right = next(draft for draft in result["drafts"]
                     if draft["anchor"]["tieupColumnsX"][0] == 2640)
        right_marks = absolute_marks(right, 1)
        left_marks = absolute_marks(left, 0)
        right["bbox"][0] = min(left["bbox"][0], right["bbox"][0])
        local_top = right["bbox"][1]
        right["draft"]["treadling"][1] = [
            *right["draft"]["treadling"][1], *left["draft"]["treadling"][0],
        ]
        right["draft"]["diagnostics"]["treadlingMarks"][1] = [
            *[{**mark, "y": mark["y"] - local_top} for mark in right_marks],
            *[{**mark, "y": mark["y"] - local_top} for mark in left_marks],
        ]
        right["draft"]["diagnostics"]["markCount"] += len(left_marks)
        right["annotations"] = [*right.get("annotations", []), *left.get("annotations", [])]
        empty_record(left)
    elif page_number == 90:
        threading = builder.decode_threading_region(gray, bottom_staff, *bottom_span)
        lowered, visual = single.decode_tieup(gray, bottom_staff, bottom_right)
        lifted = [sorted(set(range(1, 5)) - set(column)) for column in lowered]
        left = next(draft for draft in result["drafts"]
                    if draft["anchor"]["tieupColumnsX"] == bottom_left)
        right = next(draft for draft in result["drafts"]
                     if draft["anchor"]["tieupColumnsX"] == bottom_right)
        left_treadling, left_marks, _, left_box = decode_reviewed_rail(
            gray, bottom_left, 2300, 3730, builder, single,
        )
        right_treadling, right_marks, separators, right_box = decode_reviewed_rail(
            gray, bottom_right, 2200, 3730, builder, single,
        )
        common = {
            "shafts": 4, "treadles": 6,
            "sourceThreadingOrder": "right-to-left",
            "sourceTreadleOrder": "right-to-left",
            "sourceTieupMarks": "lowered shafts",
            "threading": builder.tolerant_period(threading),
            "threadingShown": threading,
            "tieupLowered": lowered, "tieupLifted": lifted,
            "tieupVisualTopToBottom": visual,
            "possibleTabbyControl": True,
        }
        left["bbox"] = list(left_box)
        left["draft"] = {**common, "treadling": [], "diagnostics": {
            "staffY": bottom_staff, "tieupColumnsX": bottom_left,
            "separatorY": [], "markCount": 0, "treadlingMarks": [],
            "coordinatesRelativeToBbox": True, "reviewedDetachedLayout": True,
        }}
        left.pop("error", None)
        right["bbox"] = [left_box[0], right_box[1], right_box[2], right_box[3]]
        local_top = right["bbox"][1]
        combined_marks = [*right_marks[1], *left_marks[0]]
        right["draft"] = {**common, "treadling": [
            right_treadling[0], [*right_treadling[1], *left_treadling[0]],
        ], "diagnostics": {
            "staffY": bottom_staff, "tieupColumnsX": bottom_right,
            "separatorY": separators, "markCount": len(right_marks[0]) + len(combined_marks),
            "treadlingMarks": [
                [{**mark, "y": mark["y"] - local_top} for mark in right_marks[0]],
                [{**mark, "y": mark["y"] - local_top} for mark in combined_marks],
            ],
            "coordinatesRelativeToBbox": True, "reviewedDetachedLayout": True,
        }}
        right.pop("error", None)
    return result


def reviewed_page_80(
    gray: np.ndarray, builder, single, annotations: dict | None,
) -> dict:
    groups = [
        {
            "sourceBaseId": "davison-ch05-n023",
            "threadStaff": [506, 530, 553, 578, 602],
            "threadSpan": (224, 2585),
            "tieupStaff": [693, 715, 737, 760, 782],
            "tieupColumns": [2585, 2610, 2634, 2658, 2682, 2706, 2731],
            "rails": [
                ([1768, 1792, 1817, 1841, 1865, 1889, 1914], 782, 1910),
                ([2174, 2198, 2222, 2246, 2270, 2296, 2322], 782, 1910),
                ([2585, 2610, 2634, 2658, 2682, 2706, 2731], 782, 1910),
            ],
        },
        {
            "sourceBaseId": "davison-ch05-n024",
            "threadStaff": [2178, 2202, 2226, 2250, 2274],
            "threadSpan": (224, 2729),
            "tieupStaff": [2178, 2202, 2226, 2250, 2274],
            "tieupColumns": [2582, 2607, 2632, 2656, 2680, 2704, 2729],
            "rails": [
                ([2582, 2607, 2632, 2656, 2680, 2704, 2729], 2274, 3720),
            ],
        },
    ]
    anchors = sorted([
        builder.Anchor(group["tieupStaff"], columns, group["threadSpan"], 999)
        for group in groups for columns, _start, _cap in group["rails"]
    ], key=lambda anchor: (anchor.staff[0], anchor.span[0], anchor.columns[0]))
    detect, continuations = builder.detect_anchors, builder.continuation_anchors
    try:
        builder.detect_anchors = lambda _gray, _single=None: anchors
        builder.continuation_anchors = lambda _gray, found, _single: found
        result = builder.extract_page(gray, 80, single, annotations)
    finally:
        builder.detect_anchors, builder.continuation_anchors = detect, continuations

    chart_groups = []
    for group_number, group in enumerate(groups, 1):
        threading = builder.decode_threading_region(
            gray, group["threadStaff"], *group["threadSpan"],
        )
        lowered, visual = single.decode_tieup(
            gray, group["tieupStaff"], group["tieupColumns"],
        )
        lifted = [sorted(set(range(1, 5)) - set(column)) for column in lowered]
        draft_ids = []
        for columns, start, cap in group["rails"]:
            record = next(draft for draft in result["drafts"]
                          if draft["anchor"]["staffY"] == group["tieupStaff"]
                          and draft["anchor"]["tieupColumnsX"] == columns)
            treadling, marks, separators, box = decode_reviewed_rail(
                gray, columns, start, cap, builder, single,
            )
            record["bbox"] = list(box)
            record.pop("error", None)
            if annotations:
                height, width = gray.shape
                record["annotations"] = [cue for cue in annotations.get("cues", [])
                                         if box[0] <= cue.get("xRatio", -1) * width <= box[2]
                                         and box[1] <= cue.get("yRatio", -1) * height <= box[3]]
            record["draft"] = {
                "shafts": 4,
                "treadles": len(group["tieupColumns"]) - 1,
                "sourceThreadingOrder": "right-to-left",
                "sourceTreadleOrder": "right-to-left",
                "sourceTieupMarks": "lowered shafts",
                "threading": builder.tolerant_period(threading),
                "threadingShown": threading,
                "tieupLowered": lowered,
                "tieupLifted": lifted,
                "tieupVisualTopToBottom": visual,
                "treadling": treadling,
                "possibleTabbyControl": False,
                "diagnostics": {
                    "staffY": group["tieupStaff"],
                    "tieupColumnsX": columns,
                    "separatorY": separators,
                    "markCount": sum(map(len, marks)),
                    "treadlingMarks": [[
                        {**mark, "y": mark["y"] - box[1]} for mark in segment
                    ] for segment in marks],
                    "coordinatesRelativeToBbox": True,
                    "reviewedDetachedLayout": True,
                },
            }
            draft_ids.append(record["id"])
        chart_groups.append({
            "id": f"davison-p080-reviewed-g{group_number:02d}",
            "sourceBaseId": group["sourceBaseId"],
            "draftIds": draft_ids,
            "assignmentConfidence": "reviewed-source",
        })
        if group["sourceBaseId"] == "davison-ch05-n023":
            left, middle, right = [next(
                draft for draft in result["drafts"] if draft["id"] == draft_id
            ) for draft_id in draft_ids]
            right_pattern = right["draft"]["treadling"][-1]
            right_marks = right["draft"]["diagnostics"]["treadlingMarks"][-1]
            right["draft"]["treadling"] = [[
                *right_pattern,
                *middle["draft"]["treadling"][0],
                *left["draft"]["treadling"][0],
            ]]
            right["draft"]["diagnostics"]["treadlingMarks"] = [[
                *right_marks,
                *middle["draft"]["diagnostics"]["treadlingMarks"][0],
                *left["draft"]["diagnostics"]["treadlingMarks"][0],
            ]]
            right["draft"]["diagnostics"]["markCount"] = len(
                right["draft"]["diagnostics"]["treadlingMarks"][0]
            )
            for continuation in (left, middle):
                continuation["draft"]["treadling"] = []
                continuation["draft"]["diagnostics"]["treadlingMarks"] = []
                continuation["draft"]["diagnostics"]["markCount"] = 0
    result["chartGroups"] = chart_groups
    return result


def decode_sloped_threading(
    gray: np.ndarray, left_staff: list[int], right_staff: list[int],
    x0: int, x1: int, builder,
) -> list[int]:
    slope = float(np.median(np.asarray(right_staff) - np.asarray(left_staff))) / (x1 - x0)
    matrix = np.asarray([[1, 0, 0], [-slope, 1, slope * x0]], dtype=np.float32)
    aligned = cv2.warpAffine(
        gray, matrix, (gray.shape[1], gray.shape[0]),
        flags=cv2.INTER_LINEAR, borderValue=255,
    )
    return builder.decode_threading_region(aligned, left_staff, x0, x1)


def reviewed_page_72(
    gray: np.ndarray, builder, single, annotations: dict | None,
) -> dict:
    top_thread = decode_sloped_threading(
        gray, [539, 563, 588, 612, 637], [524, 548, 576, 598, 622],
        775, 2600, builder,
    )
    bottom_thread = decode_sloped_threading(
        gray, [2595, 2619, 2644, 2668, 2692], [2566, 2590, 2614, 2639, 2663],
        1200, 2603, builder,
    )
    primary_staff = [524, 548, 576, 598, 622]
    primary_columns = [2600, 2624, 2649, 2673, 2697, 2722, 2746]
    middle_columns = [2229, 2254, 2278, 2302, 2326, 2350, 2375]
    left_columns = [1856, 1880, 1904, 1928, 1952, 1977, 2001]
    bottom_staff = [2566, 2590, 2614, 2639, 2663]
    bottom_right = [2603, 2627, 2651, 2675, 2699, 2723, 2750]
    bottom_left = [2237, 2261, 2285, 2309, 2333, 2357, 2382]
    anchors = sorted([
        builder.Anchor(primary_staff, middle_columns, (775, 2746), 999),
        builder.Anchor(primary_staff, primary_columns, (775, 2746), 999),
        builder.Anchor([710, 734, 759, 785, 810], left_columns, (775, 2746), 999),
        builder.Anchor([1017, 1036, 1058, 1082, 1106], left_columns, (775, 2746), 999),
        builder.Anchor([1239, 1260, 1282, 1304, 1326], left_columns, (775, 2746), 999),
        builder.Anchor([1990, 2014, 2037, 2062, 2088], middle_columns, (775, 2746), 999),
        builder.Anchor(bottom_staff, bottom_left, (1200, 2750), 999),
        builder.Anchor(bottom_staff, bottom_right, (1200, 2750), 999),
    ], key=lambda anchor: (anchor.staff[0], anchor.span[0], anchor.columns[0]))
    detect, continuations = builder.detect_anchors, builder.continuation_anchors
    try:
        builder.detect_anchors = lambda _gray, _single=None: anchors
        builder.continuation_anchors = lambda _gray, found, _single: found
        result = builder.extract_page(gray, 72, single, annotations)
    finally:
        builder.detect_anchors, builder.continuation_anchors = detect, continuations

    rail_specs = [
        (middle_columns, 622, 1989), (primary_columns, 622, 2300),
        (left_columns, 810, 1017), (left_columns, 1106, 1239),
        (left_columns, 1326, 2300), (middle_columns, 2088, 2290),
        (bottom_left, 2663, 3730), (bottom_right, 2663, 3730),
    ]
    decoded = {}
    for columns, start, cap in rail_specs:
        treadling, marks, separators, box = decode_reviewed_rail(
            gray, columns, start, cap, builder, single,
        )
        decoded[(tuple(columns), start)] = (
            [mark for segment in marks for mark in segment], box,
        )

    def split(marks: list[dict], bounds: list[int]) -> tuple[list[list[int]], list[list[dict]]]:
        groups = [[mark for mark in marks if lower < mark["y"] < upper]
                  for lower, upper in zip(bounds, bounds[1:])]
        return [[mark["treadle"] for mark in group] for group in groups], groups

    middle_marks, middle_box = decoded[(tuple(middle_columns), 622)]
    right_marks, right_box = decoded[(tuple(primary_columns), 622)]
    middle_sequences, middle_groups = split(middle_marks, [622, 1394, 1546, 1818, 1989])
    right_sequences, right_groups = split(right_marks, [622, 748, 2300])
    top_records = [
        (primary_staff, middle_columns, primary_staff, primary_columns,
         middle_sequences[1:], middle_groups[1:], middle_box),
        (primary_staff, primary_columns, primary_staff, primary_columns,
         [right_sequences[1] + middle_sequences[0]],
         [right_groups[1] + middle_groups[0]], right_box),
        ([710, 734, 759, 785, 810], left_columns,
         [710, 734, 759, 785, 810], left_columns, None, None, None),
        ([1017, 1036, 1058, 1082, 1106], left_columns,
         [1017, 1036, 1058, 1082, 1106], left_columns, None, None, None),
        ([1239, 1260, 1282, 1304, 1326], left_columns,
         [1239, 1260, 1282, 1304, 1326], left_columns, None, None, None),
        ([1990, 2014, 2037, 2062, 2088], middle_columns,
         [1990, 2014, 2037, 2062, 2088], middle_columns, None, None, None),
    ]

    def set_record(record, threading, tie_staff, tie_columns,
                   sequences, mark_groups, box) -> None:
        lowered, visual = single.decode_tieup(gray, tie_staff, tie_columns)
        lifted = [sorted(set(range(1, 5)) - set(column)) for column in lowered]
        if sequences is None:
            key = (tuple(record["anchor"]["tieupColumnsX"]), tie_staff[-1])
            marks, box = decoded[key]
            sequences = [[mark["treadle"] for mark in marks]]
            mark_groups = [marks]
        record["bbox"] = list(box)
        record.pop("error", None)
        if annotations:
            height, width = gray.shape
            record["annotations"] = [cue for cue in annotations.get("cues", [])
                                     if box[0] <= cue.get("xRatio", -1) * width <= box[2]
                                     and box[1] <= cue.get("yRatio", -1) * height <= box[3]]
        record["draft"] = {
            "shafts": 4, "treadles": len(tie_columns) - 1,
            "sourceThreadingOrder": "right-to-left",
            "sourceTreadleOrder": "right-to-left",
            "sourceTieupMarks": "lowered shafts",
            "threading": builder.tolerant_period(threading),
            "threadingShown": threading,
            "tieupLowered": lowered, "tieupLifted": lifted,
            "tieupVisualTopToBottom": visual, "treadling": sequences,
            "possibleTabbyControl": False,
            "diagnostics": {
                "staffY": tie_staff, "tieupColumnsX": record["anchor"]["tieupColumnsX"],
                "separatorY": [], "markCount": sum(map(len, mark_groups)),
                "treadlingMarks": [[{**mark, "y": mark["y"] - box[1]}
                                      for mark in group] for group in mark_groups],
                "coordinatesRelativeToBbox": True,
                "reviewedDetachedLayout": True,
            },
        }

    top_ids = []
    for anchor_staff, anchor_columns, tie_staff, tie_columns, sequences, marks, box in top_records:
        record = next(draft for draft in result["drafts"]
                      if draft["anchor"]["staffY"] == anchor_staff
                      and draft["anchor"]["tieupColumnsX"] == anchor_columns)
        set_record(record, top_thread, tie_staff, tie_columns, sequences, marks, box)
        top_ids.append(record["id"])

    bottom_left_marks, bottom_left_box = decoded[(tuple(bottom_left), 2663)]
    bottom_right_marks, bottom_right_box = decoded[(tuple(bottom_right), 2663)]
    bottom_right_sequences, bottom_right_groups = split(bottom_right_marks, [2663, 2749, 3730])
    left_record = next(draft for draft in result["drafts"]
                       if draft["anchor"]["tieupColumnsX"] == bottom_left)
    right_record = next(draft for draft in result["drafts"]
                        if draft["anchor"]["tieupColumnsX"] == bottom_right)
    set_record(left_record, bottom_thread, bottom_staff, bottom_right,
               [], [], bottom_left_box)
    set_record(right_record, bottom_thread, bottom_staff, bottom_right,
               [bottom_right_sequences[1] + [mark["treadle"] for mark in bottom_left_marks]],
               [bottom_right_groups[1] + bottom_left_marks], bottom_right_box)
    result["chartGroups"] = [
        {"id": "davison-p072-reviewed-g01", "sourceBaseId": "davison-ch04-n029",
         "draftIds": top_ids, "assignmentConfidence": "reviewed-source"},
        {"id": "davison-p072-reviewed-g02", "sourceBaseId": "davison-ch04-n030",
         "draftIds": [left_record["id"], right_record["id"]],
         "assignmentConfidence": "reviewed-source"},
    ]
    return result


def apply_reviewed_bindings(page: dict) -> dict:
    reviewed = {
        63: [
            ("davison-ch04-n007", ["davison-p063-d02", "davison-p063-d03"]),
            ("davison-ch04-n008", ["davison-p063-d01"]),
            ("davison-ch04-n009", ["davison-p063-d05"]),
            ("davison-ch04-n010", ["davison-p063-d04"]),
        ],
        87: [
            ("davison-ch06-n013", ["davison-p087-d01", "davison-p087-d02"]),
            ("davison-ch06-n014", ["davison-p087-d03"]),
        ],
        88: [
            ("davison-ch06-n015", ["davison-p088-d01", "davison-p088-d02"]),
            ("davison-ch06-n016", ["davison-p088-d03"]),
        ],
        90: [
            ("davison-ch06-n020", ["davison-p090-d01"]),
            ("davison-ch06-n021", ["davison-p090-d02", "davison-p090-d03"]),
        ],
        85: [
            ("davison-ch06-n008", ["davison-p085-d01"]),
            ("davison-ch06-n009", ["davison-p085-d03"]),
            ("davison-ch06-n010", ["davison-p085-d02"]),
        ],
        133: [
            ("davison-ch12-n013", ["davison-p133-d01"]),
            ("davison-ch12-n014", ["davison-p133-d03", "davison-p133-d04"]),
        ],
        94: [
            ("davison-ch07-n004", ["davison-p094-d02"]),
            ("davison-ch07-n005", ["davison-p094-d01"]),
            ("davison-ch07-n006", ["davison-p094-d03"]),
            ("davison-ch07-n007", ["davison-p094-d04"]),
        ],
        96: [
            ("davison-ch07-n012", ["davison-p096-d01"]),
            ("davison-ch07-n013", ["davison-p096-d02"]),
            ("davison-ch07-n014", ["davison-p096-d03"]),
        ],
        121: [
            ("davison-ch11-n004", ["davison-p121-d01"]),
            ("davison-ch11-n005", ["davison-p121-d02"]),
            ("davison-ch11-n006", ["davison-p121-d03"]),
        ],
        140: [
            ("davison-ch13-n009", ["davison-p140-d01"]),
            ("davison-ch13-n010", ["davison-p140-d03"]),
            ("davison-ch13-n011", ["davison-p140-d02"]),
        ],
    }.get(page["pdfPage"])
    if reviewed:
        page["chartGroups"] = [{
            "id": f"davison-p{page['pdfPage']:03d}-reviewed-g{index:02d}",
            "sourceBaseId": source_id,
            "draftIds": draft_ids,
            "assignmentConfidence": "reviewed-visual",
        } for index, (source_id, draft_ids) in enumerate(reviewed, 1)]
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--dpi", type=int, default=360)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--rotation", type=float, default=0.0,
                        help="Image rotation in degrees for skewed source pages")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("davison-manifest.json"))
    parser.add_argument("--annotations", type=Path, default=Path(__file__).with_name("davison-annotations.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    builder = load_builder()
    single = builder.load_single_extractor()
    single.track_columns = guarded_track_columns
    original = builder.detect_anchors
    builder.detect_anchors = combined_detector(original, builder, single)
    page_manifest = builder.manifest_by_page(args.manifest)
    page_annotations = builder.annotations_by_page(args.annotations)

    def work(page: int) -> dict:
        gray = single.render(args.source, page, args.dpi)
        if args.rotation:
            height, width = gray.shape
            matrix = cv2.getRotationMatrix2D(
                (width / 2, height / 2), args.rotation, 1,
            )
            gray = cv2.warpAffine(
                gray, matrix, (width, height),
                flags=cv2.INTER_LINEAR, borderValue=255,
            )
        if page == 39:
            result = reviewed_page_39(gray, builder, single, page_annotations.get(page))
        elif page == 72:
            result = reviewed_page_72(
                gray, builder, single, page_annotations.get(page),
            )
        elif page == 80:
            result = reviewed_page_80(
                gray, builder, single, page_annotations.get(page),
            )
        elif page in {63, 87, 88, 90}:
            result = reviewed_detached_page(
                gray, page, builder, single, page_annotations.get(page),
            )
        elif page in {94, 96, 121, 140}:
            result = reviewed_page_with_extra_anchor(
                gray, page, builder, single, page_annotations.get(page),
            )
        else:
            result = builder.extract_page(gray, page, single, page_annotations.get(page))
        result = apply_reviewed_bindings(result)
        result["rotationDegrees"] = args.rotation
        result["manifestEntries"] = page_manifest.get(page, [])
        result["countDelta"] = len(result["drafts"]) - len(result["manifestEntries"])
        return result

    pages = builder.parse_pages(args.pages)
    reviewed_pages = {39, 63, 72, 80, 87, 88, 90, 94, 96, 121, 140}
    workers = 1 if reviewed_pages.intersection(pages) else max(1, args.jobs)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = sorted(executor.map(work, pages), key=lambda result: result["pdfPage"])
    payload = {
        "source": str(args.source),
        "dpi": args.dpi,
        "sourceThreadingOrder": "right-to-left",
        "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts",
        "pages": results,
        "diagnostics": {
            "detected": sum(len(page["drafts"]) for page in results),
            "decoded": sum("draft" in draft for page in results for draft in page["drafts"]),
            "failed": sum("error" in draft for page in results for draft in page["drafts"]),
            "manifestEntries": sum(len(page["manifestEntries"]) for page in results),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["diagnostics"]))


if __name__ == "__main__":
    main()
