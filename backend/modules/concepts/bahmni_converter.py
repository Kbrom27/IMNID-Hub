"""Bahmni -> OpenMRS 3.x Concept Converter.

Reads the old Bahmni-exported concepts.csv and concept_sets.csv files and
converts them into a clean, normalized JSON format that the companion
importer can push into OpenMRS 3.x via the REST API.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Callable, Optional


def find_indexed_columns(fieldnames: list[str], prefix: str) -> list[str]:
    """Find columns like 'synonym.1:en', 'answer.3', 'child.12' etc.
    Returns them sorted by their numeric index."""
    pattern = re.compile(rf"^{re.escape(prefix)}\.(\d+)(:.*)?$", re.IGNORECASE)
    matches = []
    for f in fieldnames:
        m = pattern.match(f)
        if m:
            matches.append((int(m.group(1)), f))
    matches.sort(key=lambda x: x[0])
    return [f for _, f in matches]


def get_col(row: dict[str, str], fieldnames: list[str], *candidates: str) -> str:
    """Return the value of the first matching column name (case-insensitive)."""
    lower_map = {f.lower(): f for f in fieldnames}
    for c in candidates:
        key = lower_map.get(c.lower())
        if key is not None:
            return row.get(key, "").strip()
    return ""


def convert_concepts(path: str | Path, log_fn: Optional[Callable[[str], None]] = None) -> list[dict]:
    log = log_fn or (lambda msg: None)
    log(f"Reading concepts from: {path}")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    log(f"  {len(rows)} data rows found")
    synonym_cols = find_indexed_columns(fieldnames, "synonym")
    answer_cols = find_indexed_columns(fieldnames, "answer")
    log(f"  detected {len(synonym_cols)} synonym columns, {len(answer_cols)} answer columns")

    out = []
    blank_datatype_count = 0
    blank_name_count = 0
    for i, r in enumerate(rows, start=2):
        fsn = get_col(
            r,
            fieldnames,
            "name:en",
            "Fully Specified Name:en",
            "fully specified name:en",
            "name",
        )
        if not fsn:
            blank_name_count += 1
            log(f"  WARNING line {i}: blank name, skipping row")
            continue

        locale = get_col(r, fieldnames, "locale") or "en"
        datatype = get_col(r, fieldnames, "datatype", "Data Type", "data type")
        if not datatype:
            datatype = "N/A"
            blank_datatype_count += 1

        uuid_val = get_col(r, fieldnames, "uuid", "Uuid")
        shortname = get_col(
            r,
            fieldnames,
            "shortname:en",
            "Short Name:en",
            "short name:en",
            "shortname",
        )
        description = get_col(
            r, fieldnames, "description:en", "Description:en", "description"
        )
        concept_class = get_col(
            r, fieldnames, "class", "Data Class", "data class"
        )

        synonyms = [r[c].strip() for c in synonym_cols if r.get(c, "").strip()]
        answers = [r[c].strip() for c in answer_cols if r.get(c, "").strip()]

        out.append(
            {
                "uuid": uuid_val,
                "fully_specified_name": fsn,
                "short_name": shortname,
                "description": description,
                "concept_class": concept_class,
                "datatype": datatype,
                "locale": locale,
                "synonyms": synonyms,
                "answers": answers,
            }
        )

    if blank_datatype_count:
        log(f"  NOTE: {blank_datatype_count} rows had no datatype -> defaulted to 'N/A'")
    if blank_name_count:
        log(f"  NOTE: {blank_name_count} rows had no name and were skipped")

    names_seen: dict[str, int] = {}
    for c in out:
        key = c["fully_specified_name"].strip().lower()
        names_seen.setdefault(key, 0)
        names_seen[key] += 1
    dupes = {k: v for k, v in names_seen.items() if v > 1}
    if dupes:
        log(f"  WARNING: {len(dupes)} duplicate name(s) found INSIDE this file:")
        for k, v in dupes.items():
            log(f"    '{k}' appears {v} times")

    return out


def convert_sets(path: str | Path, log_fn: Optional[Callable[[str], None]] = None) -> list[dict]:
    log = log_fn or (lambda msg: None)
    log(f"Reading concept sets from: {path}")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    log(f"  {len(rows)} data rows found")
    child_cols = find_indexed_columns(fieldnames, "child")
    member_cols = find_indexed_columns(fieldnames, "member")
    cols_to_use = child_cols or member_cols
    log(f"  detected {len(cols_to_use)} member/child columns")

    out = []
    for i, r in enumerate(rows, start=2):
        fsn = get_col(r, fieldnames, "name:en", "Fully Specified Name:en", "name")
        if not fsn:
            log(f"  WARNING line {i}: blank name, skipping row")
            continue

        locale = get_col(r, fieldnames, "locale") or "en"
        uuid_val = get_col(r, fieldnames, "uuid", "Uuid")
        shortname = get_col(
            r, fieldnames, "shortname:en", "Short Name:en", "shortname"
        )
        description = get_col(
            r, fieldnames, "description:en", "Description:en", "description"
        )
        concept_class = get_col(r, fieldnames, "class", "Data Class")

        members = [r[c].strip() for c in cols_to_use if r.get(c, "").strip()]

        out.append(
            {
                "uuid": uuid_val,
                "fully_specified_name": fsn,
                "short_name": shortname,
                "description": description,
                "concept_class": concept_class,
                "locale": locale,
                "members": members,
            }
        )

    return out


def run_bahmni_conversion(
    concepts_csv: str | Path,
    sets_csv: Optional[str | Path] = None,
    out_dir: Optional[str | Path] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    concepts = convert_concepts(concepts_csv, log_fn=log)
    concept_sets = []
    if sets_csv and Path(sets_csv).is_file():
        concept_sets = convert_sets(sets_csv, log_fn=log)

    out_concepts_path = None
    out_sets_path = None
    if out_dir:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        out_concepts = out_path / "concepts_import.json"
        out_sets = out_path / "concept_sets_import.json"

        with open(out_concepts, "w", encoding="utf-8") as f:
            json.dump(concepts, f, indent=2, ensure_ascii=False)
        with open(out_sets, "w", encoding="utf-8") as f:
            json.dump(concept_sets, f, indent=2, ensure_ascii=False)

        out_concepts_path = str(out_concepts)
        out_sets_path = str(out_sets)
        log(f"Wrote {len(concepts)} concepts to: {out_concepts}")
        log(f"Wrote {len(concept_sets)} concept sets to: {out_sets}")

    return {
        "concepts_count": len(concepts),
        "concept_sets_count": len(concept_sets),
        "concepts": concepts,
        "concept_sets": concept_sets,
        "concepts_file": out_concepts_path,
        "concept_sets_file": out_sets_path,
    }
