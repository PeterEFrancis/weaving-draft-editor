#!/usr/bin/env python3
"""Prototype CV extractor for Davison-style threading/tie-up/treadling pages.

The extractor expects the common layout used in the early draft plates: one
threading staff and tie-up at the top, followed by one or more treadlings in a
shared vertical grid.  Output uses loom numbering (shaft 1 is the bottom row,
treadle 1 is the left column).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


def render(source: Path, page: int, dpi: int) -> np.ndarray:
    if source.suffix.lower() != ".pdf":
        image = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"Cannot read {source}")
        return image
    exe = shutil.which("pdftoppm")
    if not exe:
        raise RuntimeError("pdftoppm is required for PDF input")
    with tempfile.TemporaryDirectory() as directory:
        prefix = Path(directory) / "page"
        subprocess.run(
            [exe, "-f", str(page), "-l", str(page), "-r", str(dpi),
             "-gray", "-singlefile", str(source), str(prefix)],
            check=True, stdout=subprocess.DEVNULL,
        )
        image = cv2.imread(str(prefix) + ".pgm", cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"Failed to render PDF page {page}")
    return image


def grouped_peaks(values: np.ndarray, threshold: float, gap: int = 2) -> list[int]:
    indexes = np.flatnonzero(values >= threshold)
    if not len(indexes):
        return []
    groups: list[list[int]] = [[int(indexes[0])]]
    for index in indexes[1:]:
        if index - groups[-1][-1] > gap:
            groups.append([])
        groups[-1].append(int(index))
    return [max(group, key=lambda index: values[index]) for group in groups]


def regular_run(points: list[int], count: int, min_step: float, max_step: float) -> list[int]:
    best: tuple[float, list[int]] | None = None
    points = sorted(points)
    for start_index, start in enumerate(points):
        for end in points[start_index + count - 1:]:
            step = (end - start) / (count - 1)
            if not min_step <= step <= max_step:
                continue
            chosen = []
            error = 0.0
            for offset in range(count):
                expected = start + offset * step
                nearest = min(points, key=lambda point: abs(point - expected))
                chosen.append(nearest)
                error += abs(nearest - expected)
            if len(set(chosen)) != count:
                continue
            score = error / step
            if best is None or score < best[0]:
                best = score, chosen
    if best is None:
        raise ValueError(f"No regular run of {count} rulings found")
    return best[1]


def find_staff(gray: np.ndarray, shafts: int) -> list[int]:
    height, width = gray.shape
    top = gray[: int(height * 0.22)]
    ink = cv2.threshold(top, 175, 255, cv2.THRESH_BINARY_INV)[1]
    opened = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, width // 14), 1)),
    )
    strength = (opened > 0).sum(axis=1)
    peaks = grouped_peaks(strength, width * 0.12, gap=3)
    return regular_run(peaks, shafts + 1, height * 0.004, height * 0.012)


def find_tieup_columns(gray: np.ndarray, staff: list[int], treadles: int) -> list[int]:
    height, width = gray.shape
    margin = max(3, int(np.median(np.diff(staff)) * 0.18))
    rows = np.concatenate([
        np.arange(staff[index] + margin, staff[index + 1] - margin)
        for index in range(len(staff) - 1)
    ])
    dark = (gray[rows] < 155).sum(axis=0).astype(float)
    dark = cv2.GaussianBlur(dark.reshape(1, -1), (1, 1), 0).ravel()
    peaks = grouped_peaks(dark, len(rows) * 0.38, gap=3)
    pitch_min = width * 0.005
    pitch_max = width * 0.015
    candidates: list[tuple[float, list[int]]] = []
    for start_index, start in enumerate(peaks):
        for end in peaks[start_index + treadles:]:
            pitch = (end - start) / treadles
            if not pitch_min <= pitch <= pitch_max:
                continue
            run = []
            error = 0.0
            for offset in range(treadles + 1):
                expected = start + offset * pitch
                nearest = min(peaks, key=lambda point: abs(point - expected))
                run.append(nearest)
                error += abs(nearest - expected)
            if len(set(run)) != treadles + 1:
                continue
            edge_bonus = abs(np.mean(run) / width - 0.5)
            candidates.append((error / pitch - edge_bonus, run))
    if not candidates:
        raise ValueError("Tie-up grid not found")
    return min(candidates, key=lambda candidate: candidate[0])[1]


def cell_score(gray: np.ndarray, left: int, top: int, right: int, bottom: int) -> float:
    x_margin = max(3, int((right - left) * 0.18))
    y_margin = max(3, int((bottom - top) * 0.18))
    cell = gray[top + y_margin:bottom - y_margin, left + x_margin:right - x_margin]
    return float(np.mean(255 - cell))


def decode_tieup(gray: np.ndarray, staff: list[int], columns: list[int]) -> tuple[list[list[int]], list[list[int]]]:
    scores = np.array([
        [cell_score(gray, columns[col], staff[row], columns[col + 1], staff[row + 1])
         for col in range(len(columns) - 1)]
        for row in range(len(staff) - 1)
    ], dtype=np.float32)
    _compactness, labels, centers = cv2.kmeans(
        scores.reshape(-1, 1), 2, None,
        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, 0.01),
        10, cv2.KMEANS_PP_CENTERS,
    )
    marked_label = int(np.argmax(centers.ravel()))
    visual = (labels.reshape(scores.shape) == marked_label).astype(int)
    shafts = visual.shape[0]
    visual_left_to_right = [
        sorted(shafts - row for row in range(shafts) if visual[row, col])
        for col in range(visual.shape[1])
    ]
    # Davison numbers the rightmost treadle first.
    return list(reversed(visual_left_to_right)), visual.tolist()


def minimal_period(values: list[int]) -> list[int]:
    for size in range(1, len(values) + 1):
        if all(value == values[index % size] for index, value in enumerate(values)):
            return values[:size]
    return values


def decode_threading(gray: np.ndarray, staff: list[int], columns: list[int]) -> tuple[list[int], list[int]]:
    height, width = gray.shape
    pitch = float(np.median(np.diff(staff)))
    tieup_left, tieup_right = columns[0], columns[-1]
    if np.mean(columns) > width / 2:
        x0, x1 = max(0, tieup_left - int(width * 0.38)), tieup_left
    else:
        x0, x1 = tieup_right, min(width, tieup_right + int(width * 0.38))
    mask = (gray[:, x0:x1] < 125).astype(np.uint8) * 255
    for y in staff:
        mask[max(0, y - 4):min(height, y + 5)] = 0
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
        row = next((row for row in range(len(staff) - 1)
                    if staff[row] < center_y < staff[row + 1]), None)
        if row is not None:
            candidates.append((center_x + x0, len(staff) - 1 - row))
    candidates.sort()
    # Full-height repeat bars survive as one candidate in several rows at the
    # same x. Heddle marks occur in exactly one row.
    filtered = []
    for x, shaft in candidates:
        peers = [other for other, _ in candidates if abs(other - x) < pitch * 0.25]
        if len(peers) == 1:
            filtered.append((x, shaft))
    # Davison explicitly reads the threading from the upper right toward the
    # left; image-space candidates were accumulated left-to-right.
    shown = [shaft for _x, shaft in reversed(filtered)]
    if not shown:
        raise ValueError("No threading marks found")
    return minimal_period(shown), shown


def track_columns(gray: np.ndarray, columns: list[int], top: int) -> np.ndarray:
    height, width = gray.shape
    base = np.asarray(columns, dtype=float)
    band_radius = max(15, height // 180)
    centers = np.arange(top, height, max(40, height // 50))
    shifts: list[float] = []
    accepted_centers: list[int] = []
    search = range(-max(20, int(width * 0.025)), max(10, int(width * 0.01)) + 1)
    for y in centers:
        band = gray[max(top, y - band_radius):min(height, y + band_radius + 1)]
        projection = (band < 185).sum(axis=0)
        scored = []
        for shift in search:
            score = 0
            for expected in base:
                x = int(round(expected + shift))
                score += int(np.max(projection[max(0, x - 2):min(width, x + 3)]))
            scored.append(score)
        best_index = int(np.argmax(scored))
        if scored[best_index] >= band.shape[0] * len(base) * 0.28:
            accepted_centers.append(int(y))
            shifts.append(float(list(search)[best_index]))
    if len(shifts) < 2:
        raise ValueError("Could not track the treadling grid")
    coefficient = np.polyfit(accepted_centers, shifts, 1)
    ys = np.arange(height)
    return base[None, :] + np.polyval(coefficient, ys)[:, None]


def find_separators(gray: np.ndarray, columns_at_y: np.ndarray, top: int) -> list[int]:
    height, width = gray.shape
    right_side = np.mean(columns_at_y[top]) > width / 2
    edge = int(columns_at_y[top, -1] if right_side else columns_at_y[top, 0])
    if right_side:
        crop = gray[top:, max(0, edge - int(width * 0.48)):edge + 5]
    else:
        crop = gray[top:, edge - 5:min(width, edge + int(width * 0.48))]
    # Straight, dark separators are cheapest and most precise when the scan is
    # nearly level. Curved/skewed pages fall through to the Hough fallback.
    ink = cv2.threshold(crop, 170, 255, cv2.THRESH_BINARY_INV)[1]
    opened = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, width // 9), 1)),
    )
    strength = (opened > 0).sum(axis=1)
    straight = grouped_peaks(strength, width * 0.12, gap=5)
    straight = [top + peak for peak in straight if peak > 5]
    if len(straight) >= 2:
        return straight
    edges = cv2.Canny(crop, 40, 120)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 720, 50,
        minLineLength=max(80, width // 12), maxLineGap=max(20, width // 50),
    )
    if lines is None:
        return []
    candidates = []
    crop_width = crop.shape[1]
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        length = abs(int(x2) - int(x1))
        if abs(int(y2) - int(y1)) > max(10, length * 0.02):
            continue
        touches_grid = max(x1, x2) > crop_width * 0.8 if right_side else min(x1, x2) < crop_width * 0.2
        if touches_grid:
            candidates.append(int(round((int(y1) + int(y2)) / 2)))
    if not candidates:
        return []
    candidates.sort()
    groups = [[candidates[0]]]
    for y in candidates[1:]:
        if y - groups[-1][-1] > 15:
            groups.append([])
        groups[-1].append(y)
    return [top + int(round(np.median(group))) for group in groups if np.median(group) > 10]


def decode_treadlings(
    gray: np.ndarray, columns_at_y: np.ndarray, top: int, separators: list[int]
) -> tuple[list[list[int]], list[tuple[int, int, int]]]:
    height, width = gray.shape
    pitch = float(np.median(np.diff(columns_at_y[top])))
    left = max(0, int(np.min(columns_at_y[:, 0]) - pitch * 0.2))
    right = min(width, int(np.max(columns_at_y[:, -1]) + pitch * 0.2))
    mask = (gray[:, left:right] < 135).astype(np.uint8) * 255
    for y in range(top, height):
        for boundary in columns_at_y[y]:
            x = int(round(boundary)) - left
            mask[y, max(0, x - 4):min(mask.shape[1], x + 5)] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 5)))
    count, _labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    marks: list[tuple[int, int, int]] = []
    for index in range(1, count):
        x, y, component_width, component_height, area = stats[index]
        if y + component_height < top:
            continue
        if not (pitch * 0.12 <= component_width <= pitch * 0.65):
            continue
        if not (pitch * 0.55 <= component_height <= pitch * 1.8):
            continue
        if area < pitch * pitch * 0.12:
            continue
        center_x, center_y = centers[index]
        page_x, page_y = center_x + left, int(round(center_y))
        local_columns = columns_at_y[min(height - 1, page_y)]
        treadle = next((col + 1 for col in range(len(local_columns) - 1)
                        if local_columns[col] < page_x < local_columns[col + 1]), None)
        if treadle is not None:
            source_treadle = len(local_columns) - treadle
            marks.append((page_y, source_treadle, int(area)))
    marks.sort()
    bounds = [top] + [y for y in separators if y > top + pitch] + [height]
    sequences = []
    for start, end in zip(bounds, bounds[1:]):
        sequence = [treadle for y, treadle, _area in marks if start < y < end]
        if sequence:
            sequences.append(sequence)
    return sequences, marks


def extract(gray: np.ndarray, shafts: int, treadles: int) -> dict:
    staff = find_staff(gray, shafts)
    columns = find_tieup_columns(gray, staff, treadles)
    tieup_lowered, tieup_visual = decode_tieup(gray, staff, columns)
    all_shafts = set(range(1, shafts + 1))
    tieup_lifted = [sorted(all_shafts - set(lowered)) for lowered in tieup_lowered]
    threading, threading_shown = decode_threading(gray, staff, columns)
    columns_at_y = track_columns(gray, columns, staff[-1])
    separators = find_separators(gray, columns_at_y, staff[-1])
    treadling, marks = decode_treadlings(gray, columns_at_y, staff[-1], separators)
    return {
        "shafts": shafts,
        "treadles": treadles,
        "sourceThreadingOrder": "right-to-left",
        "sourceTreadleOrder": "right-to-left",
        "sourceTieupMarks": "lowered shafts",
        "threading": threading,
        "threadingShown": threading_shown,
        "tieupLowered": tieup_lowered,
        "tieupLifted": tieup_lifted,
        "tieupVisualTopToBottom": tieup_visual,
        "treadling": treadling,
        "diagnostics": {
            "staffY": staff,
            "tieupColumnsX": columns,
            "separatorY": separators,
            "markCount": len(marks),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--page", type=int, default=1, help="one-based PDF page")
    parser.add_argument("--dpi", type=int, default=360)
    parser.add_argument("--shafts", type=int, default=4)
    parser.add_argument("--treadles", type=int, default=6)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = extract(render(args.source, args.page, args.dpi), args.shafts, args.treadles)
    result.update({"source": str(args.source), "pdfPage": args.page})
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
