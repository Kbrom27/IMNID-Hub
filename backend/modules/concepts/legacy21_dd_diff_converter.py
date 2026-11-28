"""OpenMRS 2.1 / Bahmni DD Differences Concept Converter (CM-15).

Converts the "Added (New Only)" sheet of a DHIS2 DD Differences Excel workbook
(e.g. NCF_DD_Differences_with_sections.xlsx), together with an existing server
concepts CSV snapshot (for UUID collision avoidance), into Bahmni / OpenMRS 2.1
import CSV files organised by Stage and Section:

  <output_root>/<parent_folder>/
    <Stage Name>/
      concept_sets.csv          <- stage-level concept set (children = sections)
      <Section Name>/
        concepts.csv            <- N/A answer concepts + DE concepts for section
        concept_sets.csv        <- section-level concept set (children = DEs)

Preserves the exact mapping, option-parsing, Boolean-detection, and
deduplication logic of ncf_dd_to_concepts.py while fixing:
- Stage-level file named ``concept_sets.csv`` (so CM-13 scans and imports it
  alongside section sets in topological order).
- Whitespace-only section cells fall back cleanly to the stage name, and
  self-referencing stage sets are avoided when section == stage.
- Safe Excel row unpacking when trailing blank columns exist.
- Windows-safe folder names (trailing dots/spaces stripped).
- Case-insensitive / BOM-safe ``EMR Concept UUID`` column loading.
- Canonical answer casing and per-DE / per-section deduplication.
"""

from __future__ import annotations

import csv
import os
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from openpyxl import load_workbook

# ─────────────────────────────────────────────────────────────
# DHIS2 → Bahmni datatype map
# ─────────────────────────────────────────────────────────────
DTYPE_MAP: Dict[str, str] = {
    "TEXT":             "Text",
    "MULTI_TEXT":       "Text",
    "DATE":             "Date",
    "DATETIME":         "Datetime",
    "TIME":             "Text",       # Bahmni 0.93 forms represent time as Text
    "NUMBER":           "Numeric",
    "INTEGER":          "Numeric",
    "INTEGER_POSITIVE": "Numeric",
    "BOOLEAN":          "Boolean",
    "PERCENTAGE":       "Numeric",
    "COORDINATE":       "Text",
}
CONCEPT_CLASS = "Misc"

YES_NO_SET = {"yes", "no"}
ADMIN_VALUES = {"not recorded", "not readable", "not applicable", "unknown"}

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

CONCEPTS_COLS_BASE = [
    "uuid", "name", "description", "class", "shortname",
    "datatype", "units", "High Normal", "Low Normal", "Allow Decimal",
    "locale", "synonym.1",
]
CONCEPTS_COLS_TAIL = [
    "reference-term-source", "reference-term-code", "reference-term-relationship",
]
SETS_COLS_BASE = ["uuid", "name", "description", "class", "shortname"]
SETS_COLS_TAIL = [
    "reference-term-source", "reference-term-code", "reference-term-relationship",
]


# ─────────────────────────────────────────────────────────────
# Helpers & Rules
# ─────────────────────────────────────────────────────────────

def is_yes_no_only(parsed_options: List[str]) -> bool:
    """True when the only meaningful values are Yes and No."""
    if not parsed_options:
        return False
    meaningful = {o.lower() for o in parsed_options if o.lower() not in ADMIN_VALUES}
    return meaningful == YES_NO_SET


def load_existing_uuids(existing_csv_path: str | Path) -> Set[str]:
    """Load existing server concept UUIDs from a concepts export CSV."""
    path = Path(existing_csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Existing server concepts CSV not found: {path}")

    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None) or []
        col_map = {str(h or "").strip().lower(): idx for idx, h in enumerate(header)}
        uuid_idx = col_map.get("emr concept uuid")
        if uuid_idx is None:
            uuid_idx = col_map.get("uuid")
        if uuid_idx is None:
            raise ValueError(
                "Existing server concepts CSV is missing the 'EMR Concept UUID' (or 'uuid') column."
            )

        uuids: Set[str] = set()
        for cells in reader:
            if uuid_idx < len(cells):
                val = (cells[uuid_idx] or "").strip()
                if val:
                    uuids.add(val.lower())
        return uuids


def new_uuid(used: Set[str]) -> str:
    while True:
        u = str(uuid.uuid4())
        if u.lower() not in used:
            used.add(u.lower())
            return u


def parse_options(options_str: Any) -> List[str]:
    """'1:Male; 2:Female' → ['Male', 'Female']"""
    if options_str is None or str(options_str).strip().lower() in ("nan", "none", ""):
        return []
    parts = [p.strip() for p in str(options_str).split(";") if p.strip()]
    answers: List[str] = []
    for part in parts:
        m = re.match(r"^-?\d+\s*:\s*(.+)$", part)
        answers.append(m.group(1).strip() if m else part)
    return answers


def all_numeric(values: List[str]) -> bool:
    if not values:
        return False
    for v in values:
        try:
            float(v)
        except (ValueError, TypeError):
            return False
    return True


def resolve_datatype(dhis2_dtype: str, parsed_opts: List[str]) -> str:
    """Determine Bahmni datatype.
      no options          → map from DHIS2 type
      all-numeric options → Numeric
      Yes/No only options → Boolean
      other options       → Coded
    """
    if not parsed_opts:
        return DTYPE_MAP.get((dhis2_dtype or "").strip().upper(), "Text")
    if all_numeric(parsed_opts):
        return "Numeric"
    if is_yes_no_only(parsed_opts):
        return "Boolean"
    return "Coded"


def safe_folder_name(name: str, fallback: str = "_UNNAMED") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", (name or "").strip()).rstrip(". ")
    if not cleaned:
        return fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def write_csv(path: str | Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    """Write CSV quoting all strings so 'N/A' is never read back as NaN."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
            quoting=csv.QUOTE_NONNUMERIC,
        )
        writer.writeheader()
        for row in rows:
            full_row = {
                k: (row.get(k) if row.get(k) is not None else "")
                for k in fieldnames
            }
            writer.writerow(full_row)


# ─────────────────────────────────────────────────────────────
# Core Conversion
# ─────────────────────────────────────────────────────────────

def convert_dd_differences_to_legacy21(
    dd_path: str | Path,
    existing_concepts_path: str | Path,
    output_root: str | Path,
    parent_folder_name: str = "NCF_Added",
    log_fn: Optional[Callable[[str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Convert DD Differences ('Added (New Only)') + existing server concepts CSV
    into Legacy OpenMRS 2.1 / Bahmni import CSVs organised by Stage and Section.
    """
    log = log_fn or (lambda msg: None)
    is_canceled = is_canceled_fn or (lambda: False)

    dd_file = Path(dd_path)
    if not dd_file.is_file():
        raise FileNotFoundError(f"DD Differences Excel file not found: {dd_file}")

    log("Loading existing server concept UUIDs ...")
    used_uuids = load_existing_uuids(existing_concepts_path)
    existing_uuids_count = len(used_uuids)
    log(f"  {existing_uuids_count} existing UUIDs loaded for collision avoidance.")

    log(f"Loading added data elements from '{dd_file.name}' ...")
    wb = load_workbook(str(dd_file), read_only=True, data_only=True)
    try:
        if "Added (New Only)" not in wb.sheetnames:
            raise ValueError(
                "Sheet 'Added (New Only)' not found in the DD differences file. "
                "Make sure you are using a DD Differences Excel file with sections."
            )
        ws = wb["Added (New Only)"]
        de_rows: List[Dict[str, Any]] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            vals = (list(row) + [None] * 6)[:6]
            stage_raw, section_raw, de_id, de_name, dtype, options = vals
            if de_name is None or not str(de_name).strip():
                continue
            stage = str(stage_raw).strip() if stage_raw is not None else ""
            section_clean = str(section_raw).strip() if section_raw is not None else ""
            section = section_clean or stage
            de_rows.append({
                "stage":   stage,
                "section": section,
                "de_id":   str(de_id).strip() if de_id is not None else "",
                "de_name": str(de_name).strip(),
                "dtype":   str(dtype).strip() if dtype is not None and str(dtype).strip() else "TEXT",
                "options": options,
            })
    finally:
        wb.close()

    log(f"  {len(de_rows)} data elements loaded.")

    unique_sections = {(r["stage"], r["section"]) for r in de_rows}
    log(f"  {len(unique_sections)} stage/section groups found.")

    n_bool = sum(
        1 for r in de_rows
        if resolve_datatype(r["dtype"], parse_options(r["options"])) == "Boolean"
    )
    n_coded = sum(
        1 for r in de_rows
        if resolve_datatype(r["dtype"], parse_options(r["options"])) == "Coded"
    )
    log(f"  Boolean (Yes/No) DEs : {n_bool}")
    log(f"  Coded (multi-option) : {n_coded}")

    # ── Build global answer registry (Coded only, deduped case-insensitively) ──
    answer_registry: Dict[str, Dict[str, str]] = {}
    for row in de_rows:
        opts = parse_options(row["options"])
        if resolve_datatype(row["dtype"], opts) != "Coded":
            continue
        for ans in opts:
            key_lower = ans.lower()
            if key_lower not in answer_registry:
                answer_registry[key_lower] = {
                    "uuid": new_uuid(used_uuids),
                    "name": ans,
                }
    log(f"  Unique answer concepts to create: {len(answer_registry)}")

    # ── Group DEs by (stage, section) preserving order ──
    stage_section_des: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    section_uuids: Dict[Tuple[str, str], str] = {}
    stage_sections: Dict[str, List[Tuple[str, str]]] = defaultdict(list)

    for row in de_rows:
        key = (row["stage"], row["section"])
        stage_section_des[key].append(row)
        if key not in section_uuids:
            su = new_uuid(used_uuids)
            section_uuids[key] = su
            stage_sections[row["stage"]].append((row["section"], su))

    # ── Write per-stage and per-section files ──
    parent_name = safe_folder_name(parent_folder_name or "NCF_Added", fallback="NCF_Added")
    output_dir = Path(output_root) / parent_name
    output_dir.mkdir(parents=True, exist_ok=True)

    created_de_names: Set[str] = set()
    total_concepts = 0
    total_sets = 0
    total_sections = 0

    for stage in sorted(stage_sections.keys()):
        if is_canceled():
            log("Conversion canceled by user.")
            break

        stage_folder = output_dir / safe_folder_name(stage, fallback="_NO_STAGE")
        stage_folder.mkdir(parents=True, exist_ok=True)

        for (sec_stage, section), de_list in sorted(stage_section_des.items()):
            if sec_stage != stage:
                continue
            if is_canceled():
                log("Conversion canceled by user.")
                break

            sec_folder = stage_folder / safe_folder_name(section, fallback="_NO_SECTION")
            sec_folder.mkdir(parents=True, exist_ok=True)

            # Answer concepts needed by this section
            needed_answers: Set[str] = set()
            for row in de_list:
                opts = parse_options(row["options"])
                if resolve_datatype(row["dtype"], opts) == "Coded":
                    for ans in opts:
                        needed_answers.add(ans.lower())

            # ── concepts.csv ──
            concepts_rows: List[Dict[str, Any]] = []
            max_ans_cols = 0

            # Answer rows first (only those used by this section)
            for key_lower in sorted(needed_answers):
                info = answer_registry[key_lower]
                concepts_rows.append({
                    "uuid":          info["uuid"],
                    "name":          info["name"],
                    "description":   "",
                    "class":         CONCEPT_CLASS,
                    "shortname":     "",
                    "datatype":      "N/A",
                    "units":         "",
                    "High Normal":   "",
                    "Low Normal":    "",
                    "Allow Decimal": "",
                    "locale":        "en",
                    "synonym.1":     "",
                })

            # DE concept rows
            de_names_in_section: List[str] = []
            seen_section_des: Set[str] = set()
            for row in de_list:
                opts = parse_options(row["options"])
                bahmni_dtype = resolve_datatype(row["dtype"], opts)
                de_lower = row["de_name"].lower()

                if de_lower in created_de_names:
                    # Same DE already emitted in another section/stage: reuse concept, add as child
                    if de_lower not in seen_section_des:
                        seen_section_des.add(de_lower)
                        de_names_in_section.append(row["de_name"])
                    continue

                created_de_names.add(de_lower)

                de_entry: Dict[str, Any] = {
                    "uuid":          new_uuid(used_uuids),
                    "name":          row["de_name"],
                    "description":   f"DHIS2 ID: {row['de_id']}",
                    "class":         CONCEPT_CLASS,
                    "shortname":     "",
                    "datatype":      bahmni_dtype,
                    "units":         "",
                    "High Normal":   "",
                    "Low Normal":    "",
                    "Allow Decimal": "",
                    "locale":        "en",
                    "synonym.1":     "",
                }

                if bahmni_dtype == "Coded":
                    deduped_ans: List[str] = []
                    seen_ans: Set[str] = set()
                    for ans in opts:
                        al = ans.lower()
                        if al not in seen_ans:
                            seen_ans.add(al)
                            deduped_ans.append(answer_registry[al]["name"])
                    for idx, canonical_ans in enumerate(deduped_ans, 1):
                        de_entry[f"answer.{idx}"] = canonical_ans
                    max_ans_cols = max(max_ans_cols, len(deduped_ans))

                concepts_rows.append(de_entry)
                if de_lower not in seen_section_des:
                    seen_section_des.add(de_lower)
                    de_names_in_section.append(row["de_name"])

            ans_cols = [f"answer.{i}" for i in range(1, max_ans_cols + 1)]
            concepts_cols = CONCEPTS_COLS_BASE + ans_cols + CONCEPTS_COLS_TAIL
            write_csv(sec_folder / "concepts.csv", concepts_cols, concepts_rows)
            total_concepts += len(concepts_rows)

            # ── concept_sets.csv (section level) ──
            sec_set: Dict[str, Any] = {
                "uuid":        section_uuids[(stage, section)],
                "name":        section,
                "description": f"Section for stage: {stage}",
                "class":       CONCEPT_CLASS,
                "shortname":   "",
            }
            for idx, name in enumerate(de_names_in_section, 1):
                sec_set[f"child.{idx}"] = name

            ch_cols = [f"child.{i}" for i in range(1, len(de_names_in_section) + 1)]
            sets_cols = SETS_COLS_BASE + ch_cols + SETS_COLS_TAIL
            write_csv(sec_folder / "concept_sets.csv", sets_cols, [sec_set])
            total_sets += 1
            total_sections += 1

            log(
                f"  OK  {stage} / {section} -> "
                f"{len(de_names_in_section)} DEs, {len(needed_answers)} answers"
            )

        # ── concept_sets.csv (stage / form level, compatible with CM-13) ──
        sections_for_stage = [
            (sec_name, sec_uid)
            for sec_name, sec_uid in stage_sections[stage]
            if sec_name.lower() != stage.lower()
        ]
        if sections_for_stage:
            form_set: Dict[str, Any] = {
                "uuid":        new_uuid(used_uuids),
                "name":        stage,
                "description": f"NCF Program Stage: {stage}",
                "class":       CONCEPT_CLASS,
                "shortname":   "",
            }
            for idx, (sec_name, _) in enumerate(sections_for_stage, 1):
                form_set[f"child.{idx}"] = sec_name

            form_ch = [f"child.{i}" for i in range(1, len(sections_for_stage) + 1)]
            form_cols = SETS_COLS_BASE + form_ch + SETS_COLS_TAIL
            write_csv(stage_folder / "concept_sets.csv", form_cols, [form_set])
            total_sets += 1
            log(f"  OK  {stage} -> concept_sets.csv ({len(sections_for_stage)} sections)")

    log("")
    log("=" * 54)
    log("COMPLETE")
    log(f"  Stages processed       : {len(stage_sections)}")
    log(f"  Sections processed     : {total_sections}")
    log(f"  Concept rows written   : {total_concepts}")
    log(f"  Concept set rows       : {total_sets}")
    log(f"  Output root            : {output_dir}")
    log("=" * 54)
    log("Ready for CM-13 Bulk Concept Importer (zip archive or folder tree) or manual Bahmni CSV upload.")

    return {
        "parent_folder": parent_name,
        "output_dir": str(output_dir),
        "stages_count": len(stage_sections),
        "sections_count": total_sections,
        "concepts_count": total_concepts,
        "sets_count": total_sets,
        "de_count": len(de_rows),
        "unique_answers_count": len(answer_registry),
        "boolean_count": n_bool,
        "coded_count": n_coded,
        "existing_uuids_count": existing_uuids_count,
    }
