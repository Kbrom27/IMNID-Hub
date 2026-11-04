"""OpenMRS 2.1 DHIS2 Concept Converter (Legacy).

Converts a DHIS2 mapping CSV/Excel into OpenMRS 2.1 format concepts.csv and concept_sets.csv
organized per Stage and Section folders.
Directly reproduces the logic and output format of the original DHI2_concept_converter.py.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Callable, Optional
import pandas as pd

LOGGER = logging.getLogger("legacy21_converter")

WINDOWS_FORBIDDEN_CHARS_RE = re.compile(r'[<>:"/\\|?*]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_RE = re.compile(rf"\b{UUID_PATTERN}\b", flags=re.IGNORECASE)
OPTION_RE = re.compile(
    rf"^\s*(?:\d+\s*:\s*)?(?P<name>.*?)\s*\(\s*(?P<uuid>{UUID_PATTERN})\s*\)\s*$",
    flags=re.IGNORECASE,
)


def sanitize_fs_name(name: str, fallback: str = "_NO_SECTION") -> str:
    """Sanitize a string for filesystem compatibility matching original script."""
    cleaned = WINDOWS_FORBIDDEN_CHARS_RE.sub("_", (name or "").strip())
    cleaned = cleaned.rstrip(". ")
    if not cleaned:
        return fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def parse_emr_options(options_raw: object) -> list[tuple[str, str]]:
    """Parse EMR Options (Answers) like: 1:Married (uuid); 2:Single (uuid).

    Returns list of (option_name, option_uuid)
    """
    if pd.isna(options_raw) or not options_raw:
        return []
    raw = str(options_raw).strip()
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    options: list[tuple[str, str]] = []

    for part in parts:
        match = OPTION_RE.match(part)
        if match:
            name = match.group("name").strip()
            uuid_val = match.group("uuid").strip()
            options.append((name, uuid_val))
            continue

        uuid_match = UUID_RE.search(part)
        if not uuid_match:
            LOGGER.warning(f"Skipping option without UUID: {part}")
            continue

        uuid_val = uuid_match.group(0)
        name_part = part[: uuid_match.start()].strip()
        name_part = re.sub(r"\(?\s*$", "", name_part).strip()
        name_part = re.sub(r"^\s*\d+\s*:\s*", "", name_part).strip()
        options.append((name_part, uuid_val))

    return options


def create_basic_concept(
    uuid_str: str,
    name: str,
    datatype: str = "N/A",
    num_answer_cols: int = 9,
) -> dict:
    """Create a basic concept dictionary matching the original script."""
    concept = {
        "uuid": uuid_str,
        "name": name,
        "description": "",
        "class": "Misc",
        "shortname": "",
        "datatype": datatype,
        "units": "",
        "High Normal": "",
        "Low Normal": "",
        "Allow Decimal": "",
        "locale": "",
        "synonym.1": "",
    }
    for i in range(1, num_answer_cols + 1):
        concept[f"answer.{i}"] = ""
    concept["reference-term-source"] = ""
    concept["reference-term-code"] = ""
    concept["reference-term-relationship"] = ""
    return concept


def create_concept_set_row(
    uuid_str: str,
    name: str,
    child_names: list,
    num_child_cols: int = 13,
) -> dict:
    """Create a concept set row dictionary matching the original script."""
    concept_set = {
        "uuid": uuid_str,
        "name": name,
        "description": "",
        "class": "Misc",
        "shortname": "",
    }
    for i in range(1, num_child_cols + 1):
        concept_set[f"child.{i}"] = ""
    for i, child in enumerate(child_names[:num_child_cols], 1):
        concept_set[f"child.{i}"] = child
    concept_set["reference-term-source"] = ""
    concept_set["reference-term-code"] = ""
    concept_set["reference-term-relationship"] = ""
    return concept_set


def convert_dhis2_to_legacy21(
    input_file: str | Path,
    output_root: str | Path,
    parent_folder_name: str = "MID",
    log_fn: Optional[Callable[[str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
) -> dict:
    """Convert DHIS2 mapping file to OpenMRS 2.1 concepts and concept_sets CSVs.

    Outputs exactly:
      <output_root>/<parent_folder_name>/<stage>/<section>/<section>_concepts.csv
      <output_root>/<parent_folder_name>/<stage>/<section>/<section>_concept_sets.csv
    """
    log = log_fn or (lambda msg: None)
    is_canceled = is_canceled_fn or (lambda: False)

    in_path = Path(input_file)
    if not in_path.is_file():
        raise FileNotFoundError(f"Input mapping file not found: {in_path}")

    log(f"Reading input mapping file: {in_path.name}...")
    if in_path.suffix.lower() == ".csv":
        df = pd.read_csv(in_path, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(in_path, dtype=str)

    df.columns = [c.strip() for c in df.columns]

    required_cols = [
        "DHIS2 Stage Name",
        "DHIS2 Section Name",
        "DHIS2 Data Element Name",
        "EMR Concept UUID",
        "EMR concept Data Type",
        "EMR Options (Answers)",
        "EMR Section UUID",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required columns in mapping file: {', '.join(missing)}"
        )

    df["DHIS2 Stage Name"] = df["DHIS2 Stage Name"].astype(str).str.strip()
    df["DHIS2 Section Name"] = df["DHIS2 Section Name"].astype(str).str.strip()

    stages = df["DHIS2 Stage Name"].dropna().unique()
    total_sections = 0
    total_concepts = 0
    total_concept_sets = 0

    parent_name = (parent_folder_name or "MID").strip()
    out_base = Path(output_root) / parent_name
    out_base.mkdir(parents=True, exist_ok=True)

    log(f"Processing {len(stages)} program stages into parent folder '{parent_name}'...")

    for stage_idx, stage in enumerate(stages, 1):
        if is_canceled():
            log("Conversion canceled by user.")
            break

        stage_label = stage or "_NO_STAGE"
        stage_fs = sanitize_fs_name(stage_label, fallback="_NO_STAGE")
        stage_rows = df[df["DHIS2 Stage Name"] == stage]
        sections = stage_rows["DHIS2 Section Name"].dropna().unique()

        log(f"[{stage_idx}/{len(stages)}] Processing stage '{stage_label}' ({len(sections)} sections)...")

        for section in sections:
            if is_canceled():
                break

            section_label = section or "_NO_SECTION"
            section_fs = sanitize_fs_name(section_label, fallback="_NO_SECTION")
            section_rows = stage_rows[stage_rows["DHIS2 Section Name"] == section]

            emr_section_uuid_series = (
                section_rows["EMR Section UUID"].astype(str).str.strip()
            )
            emr_section_uuid = ""
            if not emr_section_uuid_series.empty:
                uuid_counts = emr_section_uuid_series.value_counts()
                if not uuid_counts.empty:
                    max_count = uuid_counts.max()
                    candidates = uuid_counts[uuid_counts == max_count].index.tolist()
                    emr_section_uuid = candidates[0]

            sec_dir = out_base / stage_fs / section_fs
            sec_dir.mkdir(parents=True, exist_ok=True)

            concepts_data = []
            concept_rows_by_uuid = {}
            option_concepts = []
            max_options = 0

            # 1. First pass: collect option concepts
            for _, row in section_rows.iterrows():
                concept_uuid = row["EMR Concept UUID"]
                data_type = row["EMR concept Data Type"]
                emr_answers = row["EMR Options (Answers)"]

                if pd.isna(concept_uuid):
                    continue
                concept_uuid = str(concept_uuid).strip()

                if data_type == "Coded" and not pd.isna(emr_answers):
                    opts = parse_emr_options(emr_answers)
                    max_options = max(max_options, len(opts))
                    for opt_name, opt_uuid in opts:
                        if opt_uuid not in concept_rows_by_uuid:
                            opt_c = create_basic_concept(
                                opt_uuid,
                                opt_name,
                                datatype="N/A",
                                num_answer_cols=max(9, max_options),
                            )
                            option_concepts.append(opt_c)
                            concept_rows_by_uuid[opt_uuid] = opt_c

            concepts_data.extend(option_concepts)

            # 2. Second pass: create main concepts
            child_names = []
            for _, row in section_rows.iterrows():
                concept_uuid = row["EMR Concept UUID"]
                data_type = row["EMR concept Data Type"]
                emr_answers = row["EMR Options (Answers)"]
                dhis2_name = row["DHIS2 Data Element Name"]

                if pd.isna(concept_uuid):
                    continue
                concept_uuid = str(concept_uuid).strip()

                if concept_uuid in concept_rows_by_uuid:
                    continue

                main_c = create_basic_concept(
                    concept_uuid,
                    dhis2_name,
                    datatype=data_type or "N/A",
                    num_answer_cols=max(9, max_options),
                )

                if data_type == "Coded" and not pd.isna(emr_answers):
                    opts = parse_emr_options(emr_answers)
                    for i, (opt_name, _) in enumerate(opts[: max(9, max_options)], 1):
                        main_c[f"answer.{i}"] = opt_name

                concepts_data.append(main_c)
                concept_rows_by_uuid[concept_uuid] = main_c

                if str(data_type).upper() != "N/A":
                    child_names.append(dhis2_name)

            # 3. Create concept set row
            concept_sets_data = []
            if child_names:
                set_row = create_concept_set_row(
                    emr_section_uuid,
                    section_label,
                    child_names,
                    num_child_cols=max(13, len(child_names)),
                )
                concept_sets_data.append(set_row)
                total_concept_sets += 1

            # Define column orders matching original script
            concepts_columns = [
                "uuid",
                "name",
                "description",
                "class",
                "shortname",
                "datatype",
                "units",
                "High Normal",
                "Low Normal",
                "Allow Decimal",
                "locale",
                "synonym.1",
            ]
            concepts_columns.extend(
                [f"answer.{i}" for i in range(1, max(9, max_options) + 1)]
            )
            concepts_columns.extend(
                [
                    "reference-term-source",
                    "reference-term-code",
                    "reference-term-relationship",
                ]
            )

            concept_sets_columns = [
                "uuid",
                "name",
                "description",
                "class",
                "shortname",
                "child.1",
                "child.2",
                "child.3",
                "child.4",
                "child.5",
                "child.6",
                "child.7",
                "child.8",
                "child.9",
                "child.10",
                "child.11",
                "child.12",
                "child.13",
                "reference-term-source",
                "reference-term-code",
                "reference-term-relationship",
            ]
            if len(child_names) > 13:
                for i in range(14, len(child_names) + 1):
                    concept_sets_columns.insert(-3, f"child.{i}")

            # Write {section_fs}_concepts.csv
            concepts_df = pd.DataFrame(concepts_data, columns=concepts_columns)
            concepts_path = sec_dir / f"{section_fs}_concepts.csv"
            concepts_df.to_csv(concepts_path, index=False, encoding="utf-8-sig")

            total_concepts += len(concepts_data)

            # Write {section_fs}_concept_sets.csv
            if concept_sets_data:
                concept_sets_df = pd.DataFrame(
                    concept_sets_data, columns=concept_sets_columns
                )
                concept_sets_path = sec_dir / f"{section_fs}_concept_sets.csv"
                concept_sets_df.to_csv(concept_sets_path, index=False, encoding="utf-8-sig")

            total_sections += 1

    log(
        f"Conversion completed successfully: {len(stages)} stages, {total_sections} sections, "
        f"{total_concepts} concepts, {total_concept_sets} concept sets."
    )
    return {
        "status": "completed",
        "stages_count": len(stages),
        "sections_count": total_sections,
        "concepts_count": total_concepts,
        "concept_sets_count": total_concept_sets,
        "output_directory": str(out_base),
        "parent_folder": parent_name,
    }
