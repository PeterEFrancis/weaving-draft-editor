#!/usr/bin/env python3
"""Join Davison CV output to the 417-entry manifest and emit the site catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


TABBY_LIFTS = [[1, 3], [2, 4]]


def page_label(pages: list[int]) -> str:
    return ", ".join(str(page) for page in pages)


def roman(number: int) -> str:
    output = []
    for value, numeral in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while number >= value:
            output.append(numeral)
            number -= value
    return "".join(output)


def valid_lifts(lifts: list[list[int]], shafts: int = 4) -> list[list[int]]:
    output = []
    for lift in lifts:
        normalized = sorted({int(shaft) for shaft in lift if 1 <= int(shaft) <= shafts})
        if 0 < len(normalized) < shafts:
            output.append(normalized)
    return output


def anchor_variants(
    record: dict,
    strip_control: bool = True,
    annotation_issues: list[dict] | None = None,
    excluded_sequence_indexes: set[int] | None = None,
) -> list[dict]:
    draft = record.get("draft")
    if not draft:
        return []
    threading = [int(shaft) for shaft in draft.get("threading", []) if 1 <= int(shaft) <= 4]
    if not threading:
        return []
    tieup = draft.get("tieupLifted", [])
    all_sequences = [list(sequence) for sequence in draft.get("treadling", [])]
    all_sequence_marks = draft.get("diagnostics", {}).get("treadlingMarks", [])
    if all_sequence_marks and isinstance(all_sequence_marks[0], dict):
        flat_marks = all_sequence_marks
        all_sequence_marks = []
        offset = 0
        for index, sequence in enumerate(all_sequences):
            end = len(flat_marks) if index == len(all_sequences) - 1 else offset + len(sequence)
            all_sequence_marks.append(flat_marks[offset:end])
            offset = end
    excluded_sequence_indexes = excluded_sequence_indexes or set()
    retained_indexes = [index for index in range(len(all_sequences))
                        if index not in excluded_sequence_indexes]
    retained_index = {original: current for current, original in enumerate(retained_indexes)}
    sequences = [all_sequences[index] for index in retained_indexes]
    sequence_marks = [all_sequence_marks[index] if index < len(all_sequence_marks) else []
                      for index in retained_indexes]
    cues = record.get("annotations", [])
    tabby = (TABBY_LIFTS if any(
        cue.get("type") == "tabby" and cue.get("mode") != "none" for cue in cues
    ) else None)
    repeats: dict[tuple[int, int], int] = {}
    unresolved_multipliers = []
    page_width, page_height = record.get("pagePixelSize", [1, 1])
    local_top = record.get("bbox", [0, 0, 0, 0])[1]
    staff_y = record.get("anchor", {}).get("staffY", [0, 1])
    pitch = max(1, staff_y[1] - staff_y[0])
    for cue in cues:
        if cue.get("type") != "multiplier" or cue.get("confidence", 0) < 0.9:
            continue
        count = int(cue.get("count", 0))
        if not 2 <= count <= 64:
            continue
        cue_y = cue.get("yRatio", -1) * page_height - local_top
        candidates = [(abs(mark["y"] - cue_y), sequence_index, mark_index)
                      for sequence_index, marks in enumerate(all_sequence_marks)
                      for mark_index, mark in enumerate(marks)]
        if not candidates:
            unresolved_multipliers.append(cue)
            continue
        distance, original_sequence_index, mark_index = min(candidates)
        if original_sequence_index in excluded_sequence_indexes:
            continue
        sequence_index = retained_index.get(original_sequence_index)
        if sequence_index is None:
            unresolved_multipliers.append(cue)
            continue
        if distance <= pitch * 12:
            key = (sequence_index, mark_index)
            if key in repeats and repeats[key] != count:
                unresolved_multipliers.append(cue)
            else:
                repeats[key] = count
        else:
            unresolved_multipliers.append(cue)
    if unresolved_multipliers:
        if annotation_issues is not None:
            annotation_issues.append({
                "extractId": record.get("id"),
                "issue": "high-confidence multiplier lacks a unique treadling mark",
                "multipliers": [int(cue["count"]) for cue in unresolved_multipliers],
            })
        return []
    for sequence_index, sequence in enumerate(sequences):
        if sequence_index >= len(sequence_marks):
            continue
        expanded = []
        for mark_index, treadle in enumerate(sequence):
            expanded.extend([treadle] * repeats.get((sequence_index, mark_index), 1))
        sequences[sequence_index] = expanded
    if strip_control and tabby and draft.get("possibleTabbyControl") and sequences:
        sequences = sequences[1:]
        sequence_marks = sequence_marks[1:]
        tabby = TABBY_LIFTS
    variants = []
    for sequence_index, sequence in enumerate(sequences):
        mapped = [tieup[treadle - 1] for treadle in sequence
                  if 0 < treadle <= len(tieup)]
        lifts = valid_lifts(mapped)
        if len(mapped) != len(sequence) or len(lifts) != len(sequence):
            if annotation_issues is not None:
                annotation_issues.append({
                    "extractId": record.get("id"),
                    "issue": "treadling sequence contains an out-of-range treadle or invalid shed",
                    "sequenceIndex": retained_indexes[sequence_index],
                })
            continue
        variants.append({
            "threading": threading,
            "lifts": lifts,
            "tabby": tabby,
            "extractId": record["id"],
            "confidence": "automatic",
            "appliedMultipliers": len(repeats),
        })
    return variants


def make_pattern(entry: dict, group_id: str, variant: dict, number: int, total: int) -> dict:
    suffix = "" if total == 1 else f"-v{number:02d}"
    title = entry["title"] if total == 1 else f'{entry["title"]} · Treadling {roman(number)}'
    pages = page_label(entry["printedPages"])
    note = (
        f"Transcribed from the scanned draft on source page{'' if len(entry['printedPages']) == 1 else 's'} {pages}. "
        "Faint rules, handwritten repeat counts, and balancing ends should be checked against the supplied source."
    )
    pattern = {
        "id": entry["id"] + suffix,
        "sourceBaseId": entry["id"],
        "groupId": group_id,
        "title": title,
        "pages": pages,
        "description": note,
        "kind": "Source draft",
        "shafts": 4,
        "threading": variant["threading"],
        "lifts": variant["lifts"],
        "extractionConfidence": variant["confidence"],
    }
    if variant.get("tabby"):
        pattern["tabby"] = variant["tabby"]
    if variant.get("appliedMultipliers"):
        pattern["description"] += " Explicit N TIMES annotations were expanded into repeated picks."
    if variant.get("sharedAssignment"):
        pattern["description"] += " This named assignment was inferred from the order of separated treadlings on a shared source draft."
    if variant.get("extractId"):
        pattern["sourceExtractId"] = variant["extractId"]
    if variant.get("chartGroupId"):
        pattern["sourceChartGroupId"] = variant["chartGroupId"]
    if variant.get("assignmentConfidence"):
        pattern["chartAssignmentConfidence"] = variant["assignmentConfidence"]
    return pattern


def load_chapter_one(path: Path | None) -> dict[str, list[dict]]:
    if path is None or not path.exists():
        return {}
    source = json.loads(path.read_text())
    entries = source.get("entries", source if isinstance(source, list) else [])
    if isinstance(entries, dict):
        entries = entries.values()
    output: dict[str, list[dict]] = {}
    for entry in entries:
        threading = entry.get("threading", [])
        lifts = entry.get("lifts")
        if lifts is None:
            tieup = entry.get("tieupLifted", [])
            lifts = [tieup[treadle - 1] for treadle in entry.get("treadling", [])
                     if 0 < treadle <= len(tieup)]
        lifts = valid_lifts(lifts or [])
        if threading and lifts:
            tabby = entry.get("tabby")
            output.setdefault(entry["id"], []).append({
                "threading": threading,
                "lifts": lifts,
                "tabby": (valid_lifts(tabby) if isinstance(tabby, list)
                          else (TABBY_LIFTS if tabby else None)),
                "extractId": entry.get("sourceExtractId"),
                "confidence": entry.get("confidence", "reviewed"),
            })
    return output


def ordered_chart_groups(records: list[dict]) -> list[list[dict]]:
    """Return source charts in page reading order, retaining alternate rails."""
    grouped: dict[str, list[dict]] = {}
    for record in records:
        if record.get("draft"):
            grouped.setdefault(record.get("chartGroup", record["id"]), []).append(record)
    charts = sorted(grouped.values(), key=lambda group: min(
        record["anchor"]["staffY"][0] for record in group
    ))
    rows: list[list[list[dict]]] = []
    for chart in charts:
        record = min(chart, key=lambda item: item["anchor"]["staffY"][0])
        staff = record["anchor"]["staffY"]
        pitch = max(1, staff[1] - staff[0])
        row_staff = (min(rows[-1][0], key=lambda item: item["anchor"]["staffY"][0])
                     ["anchor"]["staffY"][0] if rows else 0)
        if not rows or abs(staff[0] - row_staff) > pitch * 1.5:
            rows.append([])
        rows[-1].append(chart)
    return [chart for row in rows for chart in sorted(
        row, key=lambda group: min(
            record["anchor"]["threadingSpanX"][0] for record in group
        ),
    )]


def distribute(records: list[dict], entries: list[dict]) -> list[list[dict]]:
    """Assign one reading-order source chart to each named entry."""
    if not entries:
        return []
    charts = ordered_chart_groups(records)
    if len(charts) != len(entries):
        raise ValueError(f"detected {len(charts)} chart groups for {len(entries)} manifest entries")
    return charts


def dedupe_variants(variants: list[dict]) -> list[dict]:
    output = []
    seen = set()
    for variant in variants:
        key = (
            tuple(variant["threading"]),
            tuple(tuple(lift) for lift in variant["lifts"]),
            tuple(tuple(lift) for lift in (variant.get("tabby") or [])),
        )
        if key not in seen:
            seen.add(key)
            output.append(variant)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extraction", type=Path, nargs="+")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("davison-manifest.json"))
    parser.add_argument("--chapter-one", type=Path, default=Path(__file__).with_name("davison-chapter-one.json"))
    parser.add_argument("--reviewed-groups", type=Path,
                        default=Path(__file__).with_name("davison-reviewed-chart-groups.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "assets/patterns/handweavers-pattern-book.js")
    parser.add_argument("--allow-unresolved", action="store_true",
                        help="QA only: omit unresolved entries instead of failing")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    extractions = [json.loads(path.read_text()) for path in args.extraction]
    pages = {int(page["pdfPage"]): page
             for extraction in extractions for page in extraction["pages"]}
    chapter_one = load_chapter_one(args.chapter_one)
    reviewed = json.loads(args.reviewed_groups.read_text())
    sequence_exclusions = {key: set(value) for key, value
                           in reviewed.get("sequenceExclusions", {}).items()}
    variants_by_id = {entry["id"]: [] for chapter in manifest["chapters"]
                      for entry in chapter["entries"]}
    for entry_id, variants in chapter_one.items():
        variants_by_id[entry_id].extend(variants)
    annotation_issues = []
    assignment_issues = []

    # Accumulate every listed page before emitting in manifest order, so a
    # continuation page adds alternatives to the same sourceBaseId.
    for chapter in manifest["chapters"]:
        if chapter["number"] == 1:
            continue
        printed_pages = sorted({page for entry in chapter["entries"]
                                for page in entry["printedPages"]})
        for printed_page in printed_pages:
            entries = [entry for entry in chapter["entries"]
                       if printed_page in entry["printedPages"]]
            page = pages.get(printed_page + 26, {})
            records = page.get("drafts", [])
            if "chartGroups" in page:
                by_id = {record["id"]: record for record in records}
                for group in page["chartGroups"]:
                    entry_id = group.get("sourceBaseId")
                    if entry_id not in variants_by_id:
                        continue
                    group_records = [by_id[draft_id] for draft_id in group["draftIds"]
                                     if draft_id in by_id and by_id[draft_id].get("draft")]
                    canonical = max(group_records, key=lambda record: len(
                        record["draft"].get("threadingShown", [])
                    ), default=None)
                    canonical_threading = ([int(shaft) for shaft in canonical["draft"].get("threading", [])
                                            if 1 <= int(shaft) <= 4]
                                           if canonical else [])
                    for record in group_records:
                        issues = []
                        variants = anchor_variants(
                            record,
                            annotation_issues=issues,
                            excluded_sequence_indexes=sequence_exclusions.get(record["id"]),
                        )
                        if canonical_threading:
                            for variant in variants:
                                variant["threading"] = canonical_threading
                        variants_by_id[entry_id].extend({
                            **variant,
                            "chartGroupId": group["id"],
                            "assignmentConfidence": group["assignmentConfidence"],
                        } for variant in variants)
                        annotation_issues.extend({
                            **issue,
                            "sourceBaseId": entry_id,
                            "printedPage": printed_page,
                        } for issue in issues)
                continue
            try:
                distributed = distribute(records, entries)
            except ValueError as error:
                assignment_issues.append({
                    "printedPage": printed_page,
                    "issue": str(error),
                    "sourceBaseIds": [entry["id"] for entry in entries],
                })
                continue
            for entry, assigned in zip(entries, distributed):
                for record in assigned:
                    issues = []
                    variants_by_id[entry["id"]].extend(anchor_variants(
                        record, annotation_issues=issues,
                        excluded_sequence_indexes=sequence_exclusions.get(record["id"]),
                    ))
                    annotation_issues.extend({
                        **issue,
                        "sourceBaseId": entry["id"],
                        "printedPage": printed_page,
                    } for issue in issues)

    patterns = []
    unresolved = []
    for chapter in manifest["chapters"]:
        for entry in chapter["entries"]:
            variants = dedupe_variants(variants_by_id[entry["id"]])
            if not variants:
                unresolved.append(entry["id"])
                continue
            for number, variant in enumerate(variants, 1):
                patterns.append(make_pattern(entry, chapter["id"], variant, number, len(variants)))

    if (unresolved or assignment_issues or annotation_issues) and not args.allow_unresolved:
        raise SystemExit(
            f"Refusing to emit a partial catalog: {len(unresolved)} unresolved source entries; "
            f"{len(assignment_issues)} page assignment mismatches; "
            f"{len(annotation_issues)} unresolved source annotations. "
            "Use --allow-unresolved only for QA."
        )

    catalog = {
        "source": {
            "id": "handweavers-pattern-book",
            "title": manifest["title"],
            "author": manifest["author"],
            "edition": manifest["sourceEdition"],
            "year": 1977,
            "groupLabel": "chapter",
            "note": (
                f"All {len(variants_by_id)} named source entries were transcribed from the supplied scan."
                if not unresolved else
                f"{len(variants_by_id) - len(unresolved)} of {len(variants_by_id)} named source entries "
                "were transcribed from the supplied scan; unresolved entries are omitted."
            ),
        },
        "groups": [{
            "id": chapter["id"],
            "number": chapter["number"],
            "title": chapter["title"],
            "pages": f'{chapter["printedPages"][0]}–{chapter["printedPages"][1]}',
        } for chapter in manifest["chapters"]],
        "patterns": patterns,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "// Generated from tools/davison-manifest.json and scanned-draft extraction.\n"
        "const handweaversPatternBookCatalog = " + json.dumps(catalog, indent=2, ensure_ascii=False) + ";\n"
    )
    print(json.dumps({
        "patterns": len(patterns),
        "sourceEntries": sum(len(chapter["entries"]) for chapter in manifest["chapters"]),
        "unresolved": len(unresolved),
        "unresolvedIds": unresolved,
        "annotationIssues": annotation_issues,
        "assignmentIssues": assignment_issues,
    }))


if __name__ == "__main__":
    main()
