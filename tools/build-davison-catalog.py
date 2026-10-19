#!/usr/bin/env python3
"""Batch-locate and decode Davison's L-shaped four-shaft drafts.

This is deliberately geometry-first: titles/page groupings can be joined from a
separate TOC manifest.  Coordinates in the JSON make every automatic result
auditable against the source scan.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Anchor:
    staff: list[int]
    columns: list[int]
    span: tuple[int, int]
    score: float
    continuation: bool = False
    continuation_of: tuple[int, int] | None = None

    @property
    def pitch(self) -> float:
        return float(np.median(np.diff(self.staff)))


def load_single_extractor():
    path = Path(__file__).with_name("extract-davison-drafts.py")
    spec = importlib.util.spec_from_file_location("davison_single", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def groups(values: list[int], gap: int) -> list[int]:
    ordered = sorted(set(values))
    result: list[list[int]] = []
    for value in ordered:
        if not result or value - result[-1][-1] > gap:
            result.append([])
        result[-1].append(value)
    return [int(round(float(np.median(group)))) for group in result]


def runs(mask: np.ndarray, minimum: int) -> list[tuple[int, int]]:
    indexes = np.flatnonzero(mask)
    if not len(indexes):
        return []
    found: list[list[int]] = [[int(indexes[0])]]
    for index in indexes[1:]:
        if index - found[-1][-1] > 1:
            found.append([])
        found[-1].append(int(index))
    return [(run[0], run[-1]) for run in found if run[-1] - run[0] >= minimum]


def regular_five(rows: list[int], height: int) -> list[list[int]]:
    candidates: dict[tuple[int, ...], float] = {}
    for start_index, start in enumerate(rows):
        for end in rows[start_index + 4:]:
            pitch = (end - start) / 4
            if not height * 0.0045 <= pitch <= height * 0.0095:
                continue
            chosen = [min(rows, key=lambda row: abs(row - start - i * pitch)) for i in range(5)]
            error = sum(abs(row - start - i * pitch) for i, row in enumerate(chosen))
            if len(set(chosen)) == 5 and error <= max(4, pitch * 0.45):
                key = tuple(chosen)
                candidates[key] = min(candidates.get(key, math.inf), error)
    return [list(candidate) for candidate, _error in sorted(candidates.items(), key=lambda item: item[1])]


def horizontal_spans(gray: np.ndarray, staff: list[int]) -> list[tuple[int, int]]:
    height, width = gray.shape
    pitch = float(np.median(np.diff(staff)))
    radius = max(3, int(round(pitch * 0.25)))
    ink = (gray < 190).astype(np.uint8)
    masks = []
    for y in staff:
        line = ink[max(0, y - radius):min(height, y + radius + 1)].max(axis=0)
        line = cv2.morphologyEx(
            line.reshape(1, -1), cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(pitch * 0.7)), 1)),
        ).ravel()
        masks.append(line)
    common = (np.sum(masks, axis=0) == len(staff)).astype(np.uint8)
    common = cv2.morphologyEx(
        common.reshape(1, -1), cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, int(pitch * 2)), 1)),
    ).ravel()
    # A four-treadle tie-up is only about four pitches wide and can be
    # detached from the longer, slightly skewed threading staff.
    return runs(common, max(40, int(pitch * 3)))


def vertical_peaks(gray: np.ndarray, staff: list[int], span: tuple[int, int]) -> list[int]:
    y0, y1 = staff[0], staff[-1]
    band = gray[y0:y1 + 1]
    strength = (band < 175).sum(axis=0)
    indexes = [int(x) for x in np.flatnonzero(strength >= band.shape[0] * 0.52)
               if span[0] - 3 <= x <= span[1] + 3]
    return groups(indexes, 3)


def regular_columns(peaks: list[int], pitch: float) -> list[list[int]]:
    output: dict[tuple[int, ...], float] = {}
    for start in peaks:
        selected = [start]
        expected = start + pitch
        while True:
            options = [point for point in peaks if point > selected[-1] and abs(point - expected) <= pitch * 0.35]
            if not options:
                break
            point = min(options, key=lambda value: abs(value - expected))
            selected.append(point)
            expected = start + len(selected) * pitch
        if len(selected) >= 5:
            error = sum(abs(point - (start + index * pitch)) for index, point in enumerate(selected))
            output[tuple(selected)] = error
    # A maximal run is the grid; shorter suffixes of it are duplicate hypotheses.
    ordered = sorted(output.items(), key=lambda item: (-len(item[0]), item[1]))
    kept: list[list[int]] = []
    for candidate, _error in ordered:
        if any(set(candidate).issubset(existing) for existing in map(set, kept)):
            continue
        kept.append(list(candidate))
    return kept


def tieup_quality(gray: np.ndarray, staff: list[int], columns: list[int], single) -> float:
    region = gray[staff[0]:staff[-1] + 1, columns[0]:columns[-1] + 1]
    if region.size == 0 or float(np.mean(region < 190)) > 0.58:
        return -math.inf
    scores = np.asarray([
        [single.cell_score(gray, columns[col], staff[row], columns[col + 1], staff[row + 1])
         for col in range(len(columns) - 1)]
        for row in range(4)
    ], dtype=np.float32)
    if scores.size == 0 or not np.all(np.isfinite(scores)):
        return -math.inf
    if float(np.max(scores) - np.min(scores)) < 20:
        return -math.inf
    _compactness, labels, centers = cv2.kmeans(
        scores.reshape(-1, 1), 2, None,
        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 40, 0.01),
        5, cv2.KMEANS_PP_CENTERS,
    )
    marked = labels.reshape(scores.shape) == int(np.argmax(centers.ravel()))
    if not np.all(marked.sum(axis=0)) or not np.all(marked.sum(axis=1)):
        return -math.inf
    contrast = float(abs(centers[0, 0] - centers[1, 0]))
    # Four-shaft book tie-ups normally mark two cells per treadle.  Keep
    # legitimate 1/3 ties, but rank balanced 2/2 grids first.
    balance = float(np.mean(2 - np.abs(marked.sum(axis=0) - 2)))
    return contrast + balance * 12


def valid_column_run(
    gray: np.ndarray, staff: list[int], columns: list[int], single,
) -> tuple[list[int], float] | None:
    """Trim only blank edge cells when a detected grid includes neighboring rails."""
    quality = tieup_quality(gray, staff, columns, single)
    if math.isfinite(quality):
        return columns, quality
    for removed in range(1, len(columns) - 4):
        candidates = []
        for left_removed in range(removed + 1):
            right_removed = removed - left_removed
            candidate = columns[
                left_removed:len(columns) - right_removed if right_removed else None
            ]
            quality = tieup_quality(gray, staff, candidate, single)
            if math.isfinite(quality):
                candidates.append((candidate, quality))
        if candidates:
            return max(candidates, key=lambda item: item[1])
    return None


def rail_support(gray: np.ndarray, staff: list[int], columns: list[int]) -> float:
    height, _width = gray.shape
    pitch = float(np.median(np.diff(staff)))
    start = staff[-1] + 2
    end = min(height, int(start + pitch * 14))
    if end <= start:
        return 0
    scores = []
    for y in range(start, end):
        best = 0
        for shift in range(-max(3, int(pitch)), max(3, int(pitch)) + 1):
            present = 0
            for x in columns:
                left = max(0, x + shift - 2)
                right = min(gray.shape[1], x + shift + 3)
                if left < right and np.min(gray[y:y + 1, left:right]) < 185:
                    present += 1
            best = max(best, present)
        scores.append(best / len(columns))
    return float(np.mean(np.asarray(scores) >= 0.5))


def detect_anchors(gray: np.ndarray, single) -> list[Anchor]:
    height, width = gray.shape
    ink = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY_INV)[1]
    ink = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1)),
    )
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, width // 45), 1)),
    )
    count, _labels, stats, _centers = cv2.connectedComponentsWithStats(horizontal)
    segment_rows = []
    for x, y, component_width, component_height, _area in stats[1:]:
        if component_width >= width * 0.08 and component_height <= max(12, height // 180):
            segment_rows.append(int(round(y + (component_height - 1) / 2)))
    # Do not chain-merge slightly skewed side-by-side staffs (notably p144).
    rows = groups(segment_rows, 3)
    anchors: list[Anchor] = []
    for staff in regular_five(rows, height):
        pitch = float(np.median(np.diff(staff)))
        for span in horizontal_spans(gray, staff):
            peaks = vertical_peaks(gray, staff, span)
            column_runs = regular_columns(peaks, pitch)
            for detected_columns in column_runs:
                detected_at_left = abs(detected_columns[0] - span[0]) <= pitch * 1.5
                detected_at_right = abs(detected_columns[-1] - span[1]) <= pitch * 1.5
                valid = valid_column_run(gray, staff, detected_columns, single)
                if valid is None:
                    continue
                columns, quality = valid
                # Blank border cells may be trimmed from a real edge rail.  Its
                # original edge contact still identifies the chart geometry.
                at_left = detected_at_left or abs(columns[0] - span[0]) <= pitch * 1.5
                at_right = detected_at_right or abs(columns[-1] - span[1]) <= pitch * 1.5
                support = rail_support(gray, staff, columns)
                internal_rail = len(column_runs) > 1 and support >= 0.12
                if (not (at_left or at_right or internal_rail)
                        or support < (0.12 if internal_rail else 0.18)):
                    continue
                edge_bonus = 40 if at_left or at_right else 0
                anchors.append(Anchor(
                    staff, columns, span, quality + support * 80 + edge_bonus,
                ))
    anchors.sort(key=lambda anchor: anchor.score, reverse=True)
    kept: list[Anchor] = []
    for anchor in anchors:
        box = (anchor.columns[0], anchor.staff[0], anchor.columns[-1], anchor.staff[-1])
        duplicate = False
        for existing in kept:
            other = (existing.columns[0], existing.staff[0], existing.columns[-1], existing.staff[-1])
            overlap_x = max(0, min(box[2], other[2]) - max(box[0], other[0]))
            overlap_y = max(0, min(box[3], other[3]) - max(box[1], other[1]))
            if overlap_x * overlap_y > 0.45 * min(
                max(1, (box[2] - box[0]) * (box[3] - box[1])),
                max(1, (other[2] - other[0]) * (other[3] - other[1])),
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(anchor)
    return sorted(kept, key=lambda anchor: (anchor.staff[0], anchor.span[0]))


def connected_rails(gray: np.ndarray, first: Anchor, second: Anchor) -> bool:
    """True when two tie-ups are joined by the same continuous treadling rail."""
    if second.staff[0] <= first.staff[-1] or len(first.columns) != len(second.columns):
        return False
    pitch = max(first.pitch, second.pitch)
    if max(abs(a - b) for a, b in zip(first.columns, second.columns)) > pitch * 0.75:
        return False
    y0, y1 = first.staff[-1] + 2, second.staff[0] - 1
    if y1 <= y0:
        return False
    connected = 0
    for y in range(y0, y1, 2):
        best = 0
        for shift in range(-max(3, int(pitch)), max(3, int(pitch)) + 1):
            present = 0
            for x in first.columns:
                left = max(0, x + shift - 2)
                right = min(gray.shape[1], x + shift + 3)
                if left < right and np.min(gray[y:y + 1, left:right]) < 190:
                    present += 1
            best = max(best, present)
        connected += best >= max(2, math.ceil(len(first.columns) * 0.5))
    return connected / max(1, math.ceil((y1 - y0) / 2)) >= 0.55


def chart_groups(anchors: list[Anchor], gray: np.ndarray | None = None) -> list[list[int]]:
    """Group alternate rails that share one threading staff."""
    parents = list(range(len(anchors)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left, first in enumerate(anchors):
        for right in range(left + 1, len(anchors)):
            second = anchors[right]
            pitch = max(first.pitch, second.pitch)
            same_staff = max(abs(a - b) for a, b in zip(first.staff, second.staff)) <= pitch * 0.8
            overlap = max(0, min(first.span[1], second.span[1]) - max(first.span[0], second.span[0]))
            smaller = min(first.span[1] - first.span[0], second.span[1] - second.span[0])
            if same_staff and smaller > 0 and overlap / smaller >= 0.85:
                union(left, right)
            elif second.continuation_of == (first.staff[0], first.columns[0]):
                union(left, right)
            elif (gray is not None and second.continuation
                  and second.continuation_of is None and connected_rails(gray, first, second)):
                union(left, right)

    grouped: dict[int, list[int]] = {}
    for index in range(len(anchors)):
        grouped.setdefault(find(index), []).append(index)
    return sorted(grouped.values(), key=lambda group: (
        min(anchors[index].staff[0] for index in group),
        min(anchors[index].span[0] for index in group),
    ))


def continuation_anchors(
    gray: np.ndarray, anchors: list[Anchor], single,
) -> list[Anchor]:
    """Find later tie-up boxes embedded in an already detected vertical rail."""
    height, _width = gray.shape
    ink = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1)),
    )
    _count, _labels, stats, _centers = cv2.connectedComponentsWithStats(horizontal)
    found = list(anchors)
    for base in anchors:
        pitch = base.pitch
        required_width = (base.columns[-1] - base.columns[0]) * 0.7
        rows = groups([
            int(round(y + (component_height - 1) / 2))
            for x, y, component_width, component_height, _area in stats[1:]
            if component_width >= required_width
            and component_height <= max(12, height // 180)
            and x <= base.columns[0] + pitch
            and x + component_width >= base.columns[-1] - pitch
        ], 3)
        for staff in regular_five(rows, height):
            if staff[0] <= base.staff[-1] + pitch * 4:
                continue
            span = (int(base.columns[0] - pitch), int(base.columns[-1] + pitch))
            peaks = vertical_peaks(gray, staff, span)
            column_pitch = float(np.median(np.diff(base.columns)))
            for columns in regular_columns(peaks, column_pitch):
                valid = valid_column_run(gray, staff, columns, single)
                if valid is None:
                    continue
                columns, quality = valid
                if len(columns) != len(base.columns):
                    continue
                if max(abs(a - b) for a, b in zip(columns, base.columns)) > pitch * 0.75:
                    continue
                support = rail_support(gray, staff, columns)
                candidate = Anchor(
                    staff, columns, base.span, quality + support * 80,
                    True, (base.staff[0], base.columns[0]),
                )
                if any(
                    abs(candidate.staff[0] - existing.staff[0]) <= pitch
                    and abs(candidate.columns[0] - existing.columns[0]) <= pitch
                    for existing in found
                ):
                    continue
                found.append(candidate)
    return sorted(found, key=lambda anchor: (anchor.staff[0], anchor.span[0], anchor.columns[0]))


def trace_bottom(gray: np.ndarray, anchor: Anchor, cap: int) -> int:
    height, _width = gray.shape
    pitch = anchor.pitch
    start = anchor.staff[-1]
    cap = min(height, cap)
    good = []
    previous_shift = 0
    for y in range(start, cap):
        best_score, best_shift = 0, previous_shift
        limit = max(3, int(pitch * 2))
        for shift in range(max(-limit, previous_shift - 2), min(limit, previous_shift + 2) + 1):
            score = 0
            for x in anchor.columns:
                left = max(0, x + shift - 2)
                right = min(gray.shape[1], x + shift + 3)
                if left < right and np.min(gray[y:y + 1, left:right]) < 190:
                    score += 1
            if score > best_score:
                best_score, best_shift = score, shift
        previous_shift = best_shift
        good.append(best_score >= max(2, math.ceil(len(anchor.columns) * 0.35)))
    indexes = np.flatnonzero(good)
    if not len(indexes):
        return min(cap, int(start + pitch * 20))
    last = int(indexes[0])
    allowed_gap = int(pitch * 10)
    for index in indexes[1:]:
        if int(index) - last > allowed_gap:
            break
        last = int(index)
    return min(cap, start + last + int(pitch * 2))


def grid_separators(gray: np.ndarray, columns_at_y: np.ndarray, top: int) -> list[int]:
    """Find section rules physically joined to the vertical treadling staff."""
    height, width = gray.shape
    pitch = float(np.median(np.diff(columns_at_y[top])))
    grid_left = float(np.mean(columns_at_y[top])) < width / 2
    ink = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, int(pitch * 2)), 1)),
    )
    count, _labels, stats, _centers = cv2.connectedComponentsWithStats(horizontal)
    found = []
    for x, y, component_width, component_height, _area in stats[1:]:
        center_y = int(round(y + (component_height - 1) / 2))
        if (center_y <= top + pitch * 2 or component_height > max(12, pitch)
                or component_width < pitch * 6):
            continue
        local = columns_at_y[min(height - 1, center_y)]
        edge = float(local[-1] if grid_left else local[0])
        crosses = x - pitch * 3 <= edge <= x + component_width + pitch * 3
        extension = (x + component_width - edge) if grid_left else (edge - x)
        if crosses and extension >= pitch * 1.5:
            found.append(center_y)
    return groups(found, max(5, int(pitch * 0.7)))


def crop_box(gray: np.ndarray, anchor: Anchor, all_anchors: list[Anchor]) -> tuple[int, int, int, int]:
    height, width = gray.shape
    pitch = anchor.pitch
    x0 = max(0, int(anchor.span[0] - pitch * 6))
    x1 = min(width, int(anchor.span[1] + pitch * 6))
    y0 = max(0, int(anchor.staff[0] - pitch * 3))
    anchor_width = anchor.columns[-1] - anchor.columns[0]
    later = []
    for other in all_anchors:
        if other.staff[0] <= anchor.staff[-1] + pitch * 8:
            continue
        overlap = min(anchor.columns[-1], other.columns[-1]) - max(
            anchor.columns[0], other.columns[0],
        )
        other_width = other.columns[-1] - other.columns[0]
        if overlap >= min(anchor_width, other_width) * 0.5:
            later.append(other.staff[0])
    cap = min(later) - int(pitch * 2) if later else height
    return x0, y0, x1, min(height, cap)


def tolerant_period(values: list[int]) -> list[int]:
    """Reduce complete repeats even when one repeat-bar stroke survives CV."""
    for size in range(1, len(values) // 2 + 1):
        complete = len(values) // size
        used = complete * size
        if complete >= 2 and len(values) - used <= 1:
            if all(value == values[index % size] for index, value in enumerate(values[:used])):
                return values[:size]
    return values


def decode_threading_region(
    gray: np.ndarray,
    staff: list[int],
    x0: int,
    x1: int,
    excluded: list[tuple[int, int]] | None = None,
) -> list[int]:
    """Decode heddle strokes in an explicit staff span, always right-to-left."""
    height, width = gray.shape
    pitch = float(np.median(np.diff(staff)))
    x0, x1 = max(0, x0), min(width, x1)
    mask = (gray[:, x0:x1] < 125).astype(np.uint8) * 255
    for y in staff:
        mask[max(0, y - 4):min(height, y + 5)] = 0
    for left, right in excluded or []:
        mask[:, max(0, left - x0):min(mask.shape[1], right - x0)] = 0
    count, _labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    candidates: list[tuple[float, int]] = []
    for index in range(1, count):
        x, y, component_width, component_height, area = stats[index]
        if not (pitch * 0.12 <= component_width <= pitch * 0.65):
            continue
        if not (pitch * 0.45 <= component_height <= pitch * 1.3):
            continue
        if area < pitch * pitch * 0.08:
            continue
        center_x, center_y = centers[index]
        row = next((row for row in range(4) if staff[row] < center_y < staff[row + 1]), None)
        if row is not None:
            candidates.append((center_x + x0, 4 - row))
    candidates.sort()
    filtered = []
    for x, shaft in candidates:
        peers = [other for other, _shaft in candidates if abs(other - x) < pitch * 0.25]
        if len(peers) == 1:
            filtered.append((x, shaft))
    return [shaft for _x, shaft in reversed(filtered)]


def detached_threading(gray: np.ndarray, anchors: list[Anchor], group: list[int]) -> list[int]:
    """Recover a long threading staff that is detached from its tie-up rails."""
    height, width = gray.shape
    ink = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY_INV)[1]
    ink = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1)),
    )
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, width // 45), 1)),
    )
    _count, _labels, stats, _centers = cv2.connectedComponentsWithStats(horizontal)
    rows = groups([
        int(round(y + (component_height - 1) / 2))
        for x, y, component_width, component_height, _area in stats[1:]
        if component_width >= width * 0.08 and component_height <= max(12, height // 180)
    ], 3)
    center_y = float(np.mean([anchors[index].staff[0] for index in group]))
    pitch = float(np.mean([anchors[index].pitch for index in group]))
    excluded = [(anchors[index].columns[0] - int(pitch),
                 anchors[index].columns[-1] + int(pitch)) for index in group]
    options = []
    for staff in regular_five(rows, height):
        if abs(staff[0] - center_y) > pitch * 3:
            continue
        for span in horizontal_spans(gray, staff):
            if span[1] - span[0] < width * 0.25:
                continue
            shown = decode_threading_region(gray, staff, span[0], span[1], excluded)
            if 4 <= len(shown) <= 256:
                options.append(shown)
    return max(options, key=len, default=[])


def extract_page(gray: np.ndarray, page: int, single, annotations: dict | None = None) -> dict:
    anchors = continuation_anchors(gray, detect_anchors(gray, single), single)
    grouped = chart_groups(anchors, gray)
    group_for_index = {
        index: group_number
        for group_number, group in enumerate(grouped, 1)
        for index in group
    }
    drafts = []
    for index, anchor in enumerate(anchors, 1):
        box = crop_box(gray, anchor, anchors)
        x0, y0, x1, y1 = box
        crop = gray[y0:y1, x0:x1]
        record = {
            "id": f"davison-p{page:03d}-d{index:02d}",
            "chartGroup": f"davison-p{page:03d}-g{group_for_index[index - 1]:02d}",
            "bbox": list(box),
            "pagePixelSize": [gray.shape[1], gray.shape[0]],
            "anchor": {
                "staffY": anchor.staff,
                "tieupColumnsX": anchor.columns,
                "threadingSpanX": list(anchor.span),
                "score": round(anchor.score, 2),
                "continuation": anchor.continuation,
                "continuationOf": list(anchor.continuation_of) if anchor.continuation_of else None,
            },
        }
        if annotations:
            height, width = gray.shape
            record["annotations"] = [cue for cue in annotations.get("cues", [])
                                     if x0 <= cue.get("xRatio", -1) * width <= x1
                                     and y0 <= cue.get("yRatio", -1) * height <= y1]
        try:
            lowered, visual = single.decode_tieup(gray, anchor.staff, anchor.columns)
            all_shafts = set(range(1, 5))
            lifted = [sorted(all_shafts - set(column)) for column in lowered]
            page_height, page_width = gray.shape
            if np.mean(anchor.columns) > page_width / 2:
                threading_x0 = min(
                    anchor.span[0], anchor.columns[0] - int(page_width * 0.38),
                )
                threading_x1 = anchor.columns[0]
            else:
                threading_x0 = anchor.columns[-1]
                threading_x1 = max(
                    anchor.span[1], anchor.columns[-1] + int(page_width * 0.38),
                )
            threading_shown = decode_threading_region(
                gray, anchor.staff, threading_x0, threading_x1,
            )
            if not threading_shown:
                _threading, threading_shown = single.decode_threading(
                    gray, anchor.staff, anchor.columns,
                )
            threading = tolerant_period(threading_shown)
            local_staff = [value - y0 for value in anchor.staff]
            local_columns = [value - x0 for value in anchor.columns]
            columns_at_y = single.track_columns(crop, local_columns, local_staff[-1])
            separators = grid_separators(crop, columns_at_y, local_staff[-1])
            treadling, marks = single.decode_treadlings(
                crop, columns_at_y, local_staff[-1], separators,
            )
            bounds = [local_staff[-1]] + separators + [crop.shape[0]]
            treadling_marks = []
            for start, end in zip(bounds, bounds[1:]):
                segment = [{"y": y, "treadle": treadle}
                           for y, treadle, _area in marks if start < y < end]
                if segment:
                    treadling_marks.append(segment)
            decoded = {
                "shafts": 4,
                "treadles": len(anchor.columns) - 1,
                "sourceThreadingOrder": "right-to-left",
                "sourceTreadleOrder": "right-to-left",
                "sourceTieupMarks": "lowered shafts",
                "threading": threading,
                "threadingShown": threading_shown,
                "tieupLowered": lowered,
                "tieupLifted": lifted,
                "tieupVisualTopToBottom": visual,
                "treadling": treadling,
                "possibleTabbyControl": bool(
                    len(treadling) > 1
                    and set(treadling[0]).issubset({len(anchor.columns) - 2, len(anchor.columns) - 1})
                ),
                "diagnostics": {
                    "staffY": local_staff,
                    "tieupColumnsX": local_columns,
                    "separatorY": separators,
                    "markCount": len(marks),
                    "treadlingMarks": treadling_marks,
                    "coordinatesRelativeToBbox": True,
                },
            }
            record["draft"] = decoded
        except Exception as error:  # retain geometry for later/manual recovery
            record["error"] = str(error)
        drafts.append(record)
    # Some sampler plates place one threading at left and two or more detached
    # tie-up/treadling rails at right.  Recover that shared threading across the
    # full staff band and reuse it for each rail.
    for group in grouped:
        if len(group) < 2:
            continue
        local_lengths = [len(drafts[index].get("draft", {}).get("threadingShown", []))
                         for index in group]
        existing = [drafts[index]["draft"]["threadingShown"] for index in group
                    if len(drafts[index].get("draft", {}).get("threadingShown", [])) >= 8]
        shared = max(existing, key=len, default=[])
        if not shared:
            top = min(anchors[index].staff[0] for index in group)
            top_group = [index for index in group
                         if abs(anchors[index].staff[0] - top) <= anchors[index].pitch * 0.8]
            shared = detached_threading(gray, anchors, top_group)
            if len(shared) <= max(local_lengths, default=0):
                continue
        for index in group:
            if "draft" in drafts[index]:
                drafts[index]["draft"]["threadingShown"] = shared
                drafts[index]["draft"]["threading"] = tolerant_period(shared)
                drafts[index]["draft"]["diagnostics"]["sharedDetachedThreading"] = True
    return {"pdfPage": page, "drafts": drafts}


def parse_pages(value: str) -> list[int]:
    pages: set[int] = set()
    for part in value.split(","):
        if "-" in part:
            start, end = map(int, part.split("-", 1))
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def manifest_by_page(path: Path | None) -> dict[int, list[dict]]:
    if path is None or not path.exists():
        return {}
    source = json.loads(path.read_text())
    result: dict[int, list[dict]] = {}
    for chapter in source.get("chapters", []):
        for entry in chapter.get("entries", []):
            for printed_page in entry.get("printedPages", []):
                result.setdefault(int(printed_page) + 26, []).append({
                    "id": entry["id"],
                    "title": entry["title"],
                    "kind": entry.get("kind"),
                    "chapterId": chapter["id"],
                })
    return result


def annotations_by_page(path: Path | None) -> dict[int, dict]:
    if path is None or not path.exists():
        return {}
    source = json.loads(path.read_text())
    return {int(page["pdfPage"]): page for page in source.get("pages", [])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--pages", default="30-228", help="one-based PDF pages/ranges")
    parser.add_argument("--dpi", type=int, default=360)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument(
        "--manifest", type=Path,
        default=Path(__file__).with_name("davison-manifest.json"),
    )
    parser.add_argument(
        "--annotations", type=Path,
        default=Path(__file__).with_name("davison-annotations.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    single = load_single_extractor()
    page_manifest = manifest_by_page(args.manifest)
    page_annotations = annotations_by_page(args.annotations)
    def work(page: int) -> dict:
        gray = single.render(args.source, page, args.dpi)
        result = extract_page(gray, page, single, page_annotations.get(page))
        result["manifestEntries"] = page_manifest.get(page, [])
        result["chartGroupCount"] = len({draft["chartGroup"] for draft in result["drafts"]})
        result["countDelta"] = result["chartGroupCount"] - len(result["manifestEntries"])
        return result

    pages = parse_pages(args.pages)
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as executor:
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
