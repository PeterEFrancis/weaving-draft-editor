#!/usr/bin/env python3
"""Extract positioned notation cues from Davison's scanned pattern plates."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

import pdfplumber


PRINTED_TO_PDF_OFFSET = 26


def norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper()).replace("0", "O")


def resembles(value: str, target: str, cutoff: float = 0.68) -> bool:
    value = norm(value)
    return bool(value) and difflib.SequenceMatcher(None, value, target).ratio() >= cutoff


def is_tabby(value: str) -> bool:
    value = norm(value)
    return "TABBY" in value or (4 <= len(value) <= 9 and resembles(value, "TABBY", 0.70))


def is_border(value: str) -> bool:
    value = norm(value)
    return "BORDER" in value or value in {"GORDER", "POROER", "BOROER", "PORDER", "BRDER", "GORODER"}


def is_repeat(value: str) -> bool:
    value = norm(value)
    return "REPEAT" in value or value in {"EPEAT", "REPEA", "REPCAT", "NEPEAT", "PEPEAT", "REPEAR"}


def is_continuation(value: str) -> bool:
    value = norm(value)
    return "CONTINU" in value or value in {"ONTINUE", "CONTIMUE", "CONRINUED", "INUED"}


def box(words: list[dict], width: float, height: float) -> dict:
    x0 = min(word["x0"] for word in words)
    top = min(word["top"] for word in words)
    x1 = max(word["x1"] for word in words)
    bottom = max(word["bottom"] for word in words)
    x = (x0 + x1) / 2
    y = (top + bottom) / 2
    return {
        "x": round(x, 2), "y": round(y, 2),
        "xRatio": round(x / width, 5), "yRatio": round(y / height, 5),
        "bbox": [round(x0, 2), round(top, 2), round(x1, 2), round(bottom, 2)],
    }


def lines_for(words: list[dict], tolerance: float = 4.0) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        line = min(lines, key=lambda item: abs(item[0]["top"] - word["top"]), default=None)
        if line is None or abs(line[0]["top"] - word["top"]) > tolerance:
            lines.append([word])
        else:
            line.append(word)
    return [sorted(line, key=lambda item: item["x0"]) for line in lines]


def phrase(line: list[dict], start: int, end: int, width: float, height: float) -> dict:
    words = line[max(0, start):min(len(line), end)]
    return {"raw": " ".join(word["text"] for word in words), **box(words, width, height)}


def extract_page(page, printed_page: int, entry_ids: list[str]) -> dict:
    width, height = float(page.width), float(page.height)
    words = page.extract_words(x_tolerance=2, y_tolerance=3, use_text_flow=False)
    lines = lines_for(words)
    cues: list[dict] = []
    anchors: list[dict] = []
    number_roles: dict[int, str] = {}

    for line in lines:
        values = [norm(word["text"]) for word in line]
        for index, value in enumerate(values):
            if line[index]["text"][:1].isupper() and resembles(value, "THREADING", 0.82):
                label_window = values[index + 1:min(len(line), index + 4)]
                if not any(item in {"NO", "N", "MO"} for item in label_window):
                    continue
                number_index = next(
                    (cursor for cursor in range(index + 1, min(len(line), index + 5))
                     if re.fullmatch(r"\d{1,3}", line[cursor]["text"])),
                    None,
                )
                if number_index is None:
                    continue
                end = number_index + 1 if number_index is not None else index + 1
                item = {"threadingNo": int(line[number_index]["text"]), "confidence": 0.95,
                        **phrase(line, index, end, width, height)}
                anchors.append(item)
                number_roles[id(line[number_index])] = "threading-no"

        for index, value in enumerate(values):
            if is_tabby(value):
                start = index
                mode = "pick"
                if value.startswith("NO"):
                    mode = "none"
                elif value.startswith("USE"):
                    mode = "required"
                elif "ALL" in value or "BOTH" in value:
                    mode = "required"
                elif index and (values[index - 1] == "NO" or values[index - 1].endswith("NO")):
                    start, mode = index - 1, "none"
                elif index and values[index - 1] in {"USE", "SE"}:
                    start, mode = index - 1, "required"
                allowed = {"ON", "ALL", "BOTH", "TREADLINGS", "TREADLING", "UNLESS",
                           "OTHERWISE", "INDICATED", "EXCEPT", "AND", "THE"}
                end = index + 1
                while end < len(line) and (values[end] in allowed or values[end].startswith("TREADL")):
                    end += 1
                scope_words = values[index + 1:end]
                scope = "all-treadlings" if "ALL" in scope_words or "ALL" in value else (
                    "both-treadlings" if "BOTH" in scope_words or "BOTH" in value else "local")
                confidence = 1.0 if "TABBY" in value else 0.8
                cues.append({"type": "tabby", "mode": mode, "scope": scope,
                             "confidence": confidence,
                             **phrase(line, start, end, width, height)})
            elif is_border(value):
                cues.append({"type": "border", "confidence": 1.0 if "BORDER" in value else 0.8,
                             **phrase(line, index, index + 1, width, height)})
            elif is_repeat(value):
                start, end, scope = index, index + 1, "local"
                prior = values[max(0, index - 6):index]
                following = values[index + 1:min(len(line), index + 4)]
                if "ENTIRE" in following and any(resembles(item, "DRAFT") for item in following):
                    end = min(len(line), index + 3)
                    scope = "entire-draft"
                elif "WHOLE" in prior and "USED" in prior:
                    start = max(0, index - 6)
                    scope = "whole-draft"
                cues.append({"type": "repeat", "scope": scope,
                             "confidence": 1.0 if "REPEAT" in value else 0.8,
                             **phrase(line, start, end, width, height)})
            elif is_continuation(value):
                cues.append({"type": "continuation", "confidence": 0.9,
                             **phrase(line, index, index + 1, width, height)})
            elif value == "START":
                cues.append({"type": "start", "confidence": 1.0,
                             **phrase(line, index, index + 1, width, height)})
            elif resembles(value, "TIMES", 0.72):
                number_index = next(
                    (cursor for cursor in range(index - 1, max(-1, index - 4), -1)
                     if re.fullmatch(r"\d{1,2}", line[cursor]["text"])),
                    None,
                )
                if number_index is not None:
                    number_roles[id(line[number_index])] = "multiplier"
                    cues.append({"type": "multiplier", "count": int(line[number_index]["text"]),
                                 "confidence": 0.95,
                                 **phrase(line, number_index, index + 1, width, height)})

    numeric_labels = []
    for word in words:
        raw = word["text"].strip()
        if not re.fullmatch(r"\d{1,4}", raw):
            continue
        value = int(raw)
        role = number_roles.get(id(word), "unclassified")
        if word["top"] > height * 0.94 and value == printed_page:
            role = "printed-page"
        numeric_labels.append({"value": value, "role": role, **box([word], width, height)})

    roman_labels = []
    for word in words:
        raw = norm(word["text"])
        if re.fullmatch(r"(?:X{0,3})(?:IX|IV|V?I{1,3})", raw) and raw:
            roman_labels.append({"variantNo": raw, "confidence": 0.4, **box([word], width, height)})

    cue_types = {}
    for cue in cues:
        cue_types[cue["type"]] = cue_types.get(cue["type"], 0) + 1
    tabby_modes = sorted({cue["mode"] for cue in cues if cue["type"] == "tabby"})
    return {
        "pdfPage": printed_page + PRINTED_TO_PDF_OFFSET,
        "printedPage": printed_page,
        "width": round(width, 2),
        "height": round(height, 2),
        "entryIds": entry_ids,
        "summary": {"cueCounts": cue_types, "tabbyModes": tabby_modes},
        "threadingAnchors": anchors,
        "cues": sorted(cues, key=lambda item: (item["y"], item["x"])),
        "numericLabels": sorted(numeric_labels, key=lambda item: (item["y"], item["x"])),
        "romanLabels": sorted(roman_labels, key=lambda item: (item["y"], item["x"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("davison-manifest.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("davison-annotations.json"))
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    page_entries: dict[int, list[str]] = {}
    for chapter in manifest["chapters"]:
        for entry in chapter["entries"]:
            for printed_page in entry["printedPages"]:
                page_entries.setdefault(printed_page, []).append(entry["id"])

    with pdfplumber.open(args.source) as pdf:
        pages = [extract_page(pdf.pages[printed_page + PRINTED_TO_PDF_OFFSET - 1], printed_page, entry_ids)
                 for printed_page, entry_ids in sorted(page_entries.items())]

    page_by_number = {page["printedPage"]: page for page in pages}
    entries = []
    for chapter in manifest["chapters"]:
        for entry in chapter["entries"]:
            entry_pages = [page_by_number[number] for number in entry["printedPages"]]
            direct = all(len(page["entryIds"]) == 1 for page in entry_pages)
            summary = None
            if direct:
                cues = [cue for page in entry_pages for cue in page["cues"]]
                summary = {
                    "tabbyModes": sorted({cue["mode"] for cue in cues if cue["type"] == "tabby"}),
                    "hasBorder": any(cue["type"] == "border" for cue in cues),
                    "hasRepeat": any(cue["type"] == "repeat" for cue in cues),
                    "hasContinuation": any(cue["type"] == "continuation" for cue in cues),
                    "multipliers": [cue["count"] for cue in cues if cue["type"] == "multiplier"],
                }
            entries.append({
                "entryId": entry["id"], "title": entry["title"],
                "printedPages": entry["printedPages"],
                "assignment": "direct" if direct else "spatial-join-required",
                "summary": summary,
            })

    output = {
        "schemaVersion": 1,
        "source": manifest["title"],
        "coordinateSystem": "PDF points from top-left; ratios are page-relative",
        "pageOffset": {"pdfPage": "printedPage + 26"},
        "limits": [
            "OCR cues are positioned evidence, not guaranteed semantic assignments.",
            "Unclassified numeric labels may be pick multipliers, end counts, citations, or design numbers.",
            "Join cues to extracted diagram bounding boxes with xRatio/yRatio and inspect mixed-tabby pages.",
        ],
        "entries": entries,
        "pages": pages,
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
