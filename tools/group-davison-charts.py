#!/usr/bin/env python3
"""Merge extraction parts and bind geometric chart groups to manifest entries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def pitch(record: dict) -> float:
    return float(np.median(np.diff(record["anchor"]["staffY"])))


def same_chart(left: dict, right: dict) -> bool:
    lp, rp = pitch(left), pitch(right)
    if abs(left["anchor"]["staffY"][0] - right["anchor"]["staffY"][0]) > max(lp, rp) * 0.9:
        return False
    a, b = left["anchor"]["threadingSpanX"], right["anchor"]["threadingSpanX"]
    overlap = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    return overlap >= min(a[1] - a[0], b[1] - b[0]) * 0.65


def cluster(records: list[dict]) -> list[list[dict]]:
    if records and all(record.get("chartGroup") for record in records):
        labeled: dict[str, list[dict]] = {}
        for record in records:
            labeled.setdefault(record["chartGroup"], []).append(record)
        return sorted(labeled.values(), key=lambda group: (
            min(item["anchor"]["staffY"][0] for item in group),
            min(item["anchor"]["threadingSpanX"][0] for item in group),
        ))
    groups: list[list[dict]] = []
    for record in records:
        matches = [group for group in groups if any(same_chart(record, item) for item in group)]
        if not matches:
            groups.append([record])
            continue
        target = matches[0]
        target.append(record)
        for other in matches[1:]:
            target.extend(other)
            groups.remove(other)
    return sorted(groups, key=lambda group: (
        min(item["anchor"]["staffY"][0] for item in group),
        min(item["anchor"]["threadingSpanX"][0] for item in group),
    ))


def group_geometry(group: list[dict]) -> dict:
    staffed = [item for item in group if len(item.get("anchor", {}).get("staffY", [])) == 5]
    spanned = [item for item in group if len(item.get("anchor", {}).get("threadingSpanX", [])) == 2]
    return {
        "staffY": ([int(round(np.median([item["anchor"]["staffY"][i] for item in staffed])))
                    for i in range(5)] if staffed else [0, 1, 2, 3, 4]),
        "threadingSpanX": ([min(item["anchor"]["threadingSpanX"][0] for item in spanned),
                            max(item["anchor"]["threadingSpanX"][1] for item in spanned)]
                           if spanned else [0, max(len(item["draft"].get("threading", []))
                                                   for item in group)]),
    }


def bind_page(
    page: dict, entries: list[dict], annotation: dict | None,
    reviewed: list[dict] | None = None,
) -> None:
    if reviewed:
        records = {record["id"]: record for record in page.get("drafts", [])
                   if record.get("draft")}
        entry_by_id = {entry["id"]: entry for entry in entries}
        output = []
        for index, item in enumerate(reviewed, 1):
            group = [records[draft_id] for draft_id in item["draftIds"] if draft_id in records]
            if not group or item["sourceBaseId"] not in entry_by_id:
                continue
            entry = entry_by_id[item["sourceBaseId"]]
            output.append({
                "id": f'davison-p{page["pdfPage"]:03d}-reviewed-g{index:02d}',
                "draftIds": [record["id"] for record in group],
                "geometry": group_geometry(group),
                "sourceBaseId": entry["id"],
                "sourceNumber": entry["sourceNumber"],
                "assignmentConfidence": "reviewed-visual",
            })
        assigned = {item["sourceBaseId"] for item in output}
        assigned_drafts = {draft_id for item in output for draft_id in item["draftIds"]}
        remaining_entries = [entry for entry in entries if entry["id"] not in assigned]
        remaining_drafts = [record for record in page.get("drafts", [])
                            if record.get("draft") and record["id"] not in assigned_drafts]
        if remaining_entries and remaining_drafts:
            remainder = {**page, "drafts": remaining_drafts}
            bind_page(remainder, remaining_entries, annotation)
            output.extend(remainder["chartGroups"])
            assigned.update(item.get("sourceBaseId") for item in remainder["chartGroups"])
        page["chartGroups"] = output
        page["groupingDiagnostics"] = {
            "chartGroups": len(output),
            "manifestEntries": len(entries),
            "unassignedGroupIds": [item["id"] for item in output
                                   if "sourceBaseId" not in item],
            "unassignedEntryIds": [entry["id"] for entry in entries if entry["id"] not in assigned],
        }
        return
    groups = cluster([record for record in page.get("drafts", []) if record.get("draft")])
    if len(entries) == 1 and groups:
        groups = [[record for group in groups for record in group]]
    output = [{
        "id": group[0].get("chartGroup", f'davison-p{page["pdfPage"]:03d}-g{index:02d}'),
        "draftIds": [record["id"] for record in group],
        "geometry": group_geometry(group),
    } for index, group in enumerate(groups, 1)]
    assigned_groups: set[int] = set()
    assigned_entries: set[str] = set()
    by_number = {int(entry["sourceNumber"]): entry for entry in entries
                 if str(entry.get("sourceNumber", "")).isdigit()}
    if page.get("drafts"):
        width, height = page["drafts"][0].get("pagePixelSize", [1, 1])
    else:
        width, height = 1, 1
    candidates = []
    for label in (annotation or {}).get("threadingAnchors", []):
        entry = by_number.get(int(label["threadingNo"]))
        if not entry:
            continue
        x, y = label["xRatio"] * width, label["yRatio"] * height
        for index, item in enumerate(output):
            staff, span = item["geometry"]["staffY"], item["geometry"]["threadingSpanX"]
            p = max(1, float(np.median(np.diff(staff))))
            outside = max(0, span[0] - x, x - span[1])
            distance = abs(y - np.mean(staff)) / p + outside / p
            if abs(y - np.mean(staff)) <= p * 12 and outside <= p * 8:
                candidates.append((distance, index, entry))
    for _distance, index, entry in sorted(candidates, key=lambda item: item[0]):
        if index in assigned_groups or entry["id"] in assigned_entries:
            continue
        output[index].update({
            "sourceBaseId": entry["id"],
            "sourceNumber": entry["sourceNumber"],
            "assignmentConfidence": "ocr-label",
        })
        assigned_groups.add(index)
        assigned_entries.add(entry["id"])
    entry_positions = {entry["id"]: index for index, entry in enumerate(entries)}
    anchors = sorted(
        (index, entry_positions[item["sourceBaseId"]])
        for index, item in enumerate(output)
        if item.get("assignmentConfidence") == "ocr-label"
    )
    if all(left[1] < right[1] for left, right in zip(anchors, anchors[1:])):
        boundaries = [(-1, -1), *anchors, (len(output), len(entries))]
        for (left_group, left_entry), (right_group, right_entry) in zip(boundaries, boundaries[1:]):
            group_indexes = [index for index in range(left_group + 1, right_group)
                             if index not in assigned_groups]
            entry_indexes = [index for index in range(left_entry + 1, right_entry)
                             if entries[index]["id"] not in assigned_entries]
            if len(group_indexes) != len(entry_indexes):
                continue
            for index, entry_index in zip(group_indexes, entry_indexes):
                entry = entries[entry_index]
                output[index].update({
                    "sourceBaseId": entry["id"],
                    "sourceNumber": entry["sourceNumber"],
                    "assignmentConfidence": "ocr-bracketed-order",
                })
                assigned_groups.add(index)
                assigned_entries.add(entry["id"])
    remaining_groups = [index for index in range(len(output)) if index not in assigned_groups]
    remaining_entries = [entry for entry in entries if entry["id"] not in assigned_entries]
    if len(remaining_groups) == len(remaining_entries):
        for index, entry in zip(remaining_groups, remaining_entries):
            output[index].update({
                "sourceBaseId": entry["id"],
                "sourceNumber": entry["sourceNumber"],
                "assignmentConfidence": "complete-page-order",
            })
            assigned_groups.add(index)
            assigned_entries.add(entry["id"])
    page["chartGroups"] = output
    page["groupingDiagnostics"] = {
        "chartGroups": len(output),
        "manifestEntries": len(entries),
        "unassignedGroupIds": [item["id"] for item in output if "sourceBaseId" not in item],
        "unassignedEntryIds": [entry["id"] for entry in entries
                               if entry["id"] not in assigned_entries],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extraction", type=Path, nargs="+")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("davison-manifest.json"))
    parser.add_argument("--annotations", type=Path, default=Path(__file__).with_name("davison-annotations.json"))
    parser.add_argument("--reviewed-groups", type=Path,
                        default=Path(__file__).with_name("davison-reviewed-chart-groups.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = [json.loads(path.read_text()) for path in args.extraction]
    pages: dict[int, dict] = {}
    for source in sources:
        for incoming in source["pages"]:
            page_number = int(incoming["pdfPage"])
            reviewed_incoming = any(
                group.get("sourceBaseId")
                and str(group.get("assignmentConfidence", "")).startswith("reviewed")
                for group in incoming.get("chartGroups", [])
            )
            if page_number not in pages or not reviewed_incoming:
                pages[page_number] = incoming
                continue
            existing = pages[page_number]
            drafts = {draft["id"]: draft for draft in existing.get("drafts", [])}
            drafts.update({draft["id"]: draft for draft in incoming.get("drafts", [])})
            existing["drafts"] = list(drafts.values())
            existing["chartGroups"] = incoming["chartGroups"]
    manifest = json.loads(args.manifest.read_text())
    by_page: dict[int, list[dict]] = {}
    for chapter in manifest["chapters"]:
        if chapter["number"] == 1:
            continue
        for entry in chapter["entries"]:
            for printed_page in entry["printedPages"]:
                by_page.setdefault(int(printed_page) + 26, []).append(entry)
    annotations = json.loads(args.annotations.read_text())
    ann_by_page = {int(page["pdfPage"]): page for page in annotations["pages"]}
    reviewed = json.loads(args.reviewed_groups.read_text()).get("pages", {})
    for page_number, page in pages.items():
        if page_number in by_page:
            embedded_review = [
                {
                    "sourceBaseId": group["sourceBaseId"],
                    "draftIds": group["draftIds"],
                }
                for group in page.get("chartGroups", [])
                if group.get("sourceBaseId")
                and str(group.get("assignmentConfidence", "")).startswith("reviewed")
            ]
            combined_review = {
                item["sourceBaseId"]: item
                for item in reviewed.get(str(page_number), [])
            }
            combined_review.update({item["sourceBaseId"]: item for item in embedded_review})
            bind_page(page, by_page[page_number], ann_by_page.get(page_number),
                      list(combined_review.values()) or None)
        else:
            page["chartGroups"] = []
            page["groupingDiagnostics"] = {
                "chartGroups": 0, "manifestEntries": 0,
                "unassignedGroupIds": [], "unassignedEntryIds": [],
            }
    payload = {**sources[0], "pages": [pages[number] for number in sorted(pages)]}
    diagnostics = [page["groupingDiagnostics"] for page in payload["pages"]]
    payload["groupingDiagnostics"] = {
        "chartGroups": sum(item["chartGroups"] for item in diagnostics),
        "manifestEntries": sum(item["manifestEntries"] for item in diagnostics),
        "unassignedGroups": sum(len(item["unassignedGroupIds"]) for item in diagnostics),
        "unassignedEntries": sum(len(item["unassignedEntryIds"]) for item in diagnostics),
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["groupingDiagnostics"]))


if __name__ == "__main__":
    main()
