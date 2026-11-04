"""Generate OpenMRS O3 form schemas from DHIS2 tracker metadata.

Provides matching between DHIS2 program stage data elements and OpenMRS concepts CSV,
generating standard O3 JSON form schemas, mapping reports, and review files.
"""

from __future__ import annotations

import csv
import difflib
import json
import re
import uuid
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional
from xml.etree import ElementTree as ET

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CONCEPT_OVERRIDES = {
    "KczDjcq8Cdd": "ANC, Parity",
    "WVUda4sIj1J": "ayh, abortion",
}

YES_NO_ANSWERS = [
    {"concept": "1065AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "label": "Yes"},
    {"concept": "1066AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "label": "No"},
]


def normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def camel_case(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value or "")
    if not words:
        return "question"
    return words[0].lower() + "".join(
        word[:1].upper() + word[1:] for word in words[1:]
    )


def column_name(cell_ref: str) -> str:
    return re.match(r"[A-Z]+", cell_ref).group(0)


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            shared_root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = [
                "".join(item.itertext()) for item in shared_root.findall("x:si", NS)
            ]
        sheet_root = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))

    raw_rows: list[dict[str, str]] = []
    for row in sheet_root.findall(".//x:sheetData/x:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("x:c", NS):
            raw = cell.findtext("x:v", default="", namespaces=NS)
            if cell.get("t") == "s":
                raw = shared[int(raw)]
            elif cell.get("t") == "inlineStr":
                inline = cell.find("x:is", NS)
                raw = "".join(inline.itertext()) if inline is not None else ""
            elif cell.get("t") == "b":
                raw = "true" if raw == "1" else "false"
            values[column_name(cell.get("r"))] = raw
        raw_rows.append(values)

    if not raw_rows:
        raise ValueError("The Excel workbook has no rows.")
    headers = raw_rows[0]
    return [
        {headers[column]: value for column, value in raw.items() if column in headers}
        for raw in raw_rows[1:]
    ]


COLUMN_MAP_NEW_TO_OLD = {
    "Fully Specified Name": "EMR Concept Fully Specified Name",
    "name": "EMR Concept Fully Specified Name",
    "Name": "EMR Concept Fully Specified Name",
    "UUID": "EMR Concept UUID",
    "uuid": "EMR Concept UUID",
    "Datatype": "EMR concept Data Type",
    "datatype": "EMR concept Data Type",
    "Answers": "EMR Options (Answers)",
    "answers": "EMR Options (Answers)",
    "shortname": "EMR Concept short name",
    "Short Name": "EMR Concept short name",
}

OLD_COLUMNS = {
    "EMR Concept Fully Specified Name",
    "EMR Concept UUID",
    "EMR concept Data Type",
    "EMR Options (Answers)",
}


def read_concepts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    if not rows:
        return rows

    first = rows[0]
    if OLD_COLUMNS.issubset(first.keys()):
        return rows

    mapped = []
    for row in rows:
        new_row = {}
        for key, value in row.items():
            if key is None:
                continue
            new_key = COLUMN_MAP_NEW_TO_OLD.get(key, key)
            new_row[new_key] = value
        # Ensure minimum key exists
        if "EMR Concept Fully Specified Name" not in new_row:
            for k in ("name", "Name", "concept_name", "Fully Specified Name"):
                if row.get(k):
                    new_row["EMR Concept Fully Specified Name"] = row[k]
                    break
            else:
                new_row["EMR Concept Fully Specified Name"] = ""
        mapped.append(new_row)
    return mapped


def match_concept(
    data_element_name: str, concepts: list[dict[str, str]]
) -> tuple[dict[str, str] | None, str, float]:
    target = (data_element_name or "").strip()
    if not target:
        return None, "unmatched", 0.0
    for item in concepts:
        c_name = item.get("EMR Concept Fully Specified Name", "").strip()
        if c_name == target:
            return item, "exact", 100.0
    for item in concepts:
        c_name = item.get("EMR Concept Fully Specified Name", "").strip()
        if c_name.casefold() == target.casefold():
            return item, "case-insensitive", 100.0
    normal_target = normalise(target)
    normal_matches = [
        item
        for item in concepts
        if normalise(item.get("EMR Concept Fully Specified Name", "")) == normal_target
    ]
    if len(normal_matches) == 1:
        return normal_matches[0], "normalised", 100.0
    candidates = [
        item.get("EMR Concept Fully Specified Name", "")
        for item in concepts
        if item.get("EMR Concept Fully Specified Name")
    ]
    closest = difflib.get_close_matches(target, candidates, n=1, cutoff=0)
    if not closest:
        return None, "unmatched", 0.0
    name = closest[0]
    score = round(
        difflib.SequenceMatcher(None, target.casefold(), name.casefold()).ratio()
        * 100,
        2,
    )
    item = next(
        (row for row in concepts if row.get("EMR Concept Fully Specified Name") == name),
        None,
    )
    if not item:
        return None, "unmatched", 0.0
    return (item, "fuzzy", score) if score >= 95 else (None, "below-threshold", score)


def rendering_from_datatype(
    concept: dict[str, str] | None, excel_type: str
) -> str:
    datatype = (
        (concept or {}).get("EMR concept Data Type") or excel_type or ""
    ).casefold()
    if "date" in datatype:
        return "date"
    if any(word in datatype for word in ("numeric", "integer", "decimal", "float")):
        return "number"
    return "text"


def determine_rendering(
    source: dict[str, str],
    concept: dict[str, str] | None,
    answer_names: list[str],
    dhis_value_type: str,
) -> str:
    is_yes_no = {label.casefold() for label in answer_names} == {"yes", "no"}
    if is_yes_no:
        return "radio"

    has_options = bool(answer_names)
    if not has_options:
        return rendering_from_datatype(concept, source.get("Data Type", ""))

    if dhis_value_type == "MULTI_TEXT":
        if len(answer_names) <= 5:
            return "checkbox"
        return "checkbox-searchable"

    if len(answer_names) <= 4:
        return "radio"

    return "select"


def excel_option_labels(source: dict[str, str]) -> list[str]:
    labels = []
    for value in source.get("Options", "").split(";"):
        value = re.sub(r"^\s*[^:]+:\s*", "", value).strip()
        if value:
            labels.append(value)
    return labels


def unique_uuid(occupied: set[str]) -> str:
    while True:
        value = str(uuid.uuid4())
        if value not in occupied:
            occupied.add(value)
            return value


def write_csv(
    path: Path, rows: list[dict[str, object]], headers: list[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_concept_map(concepts: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    name_map = {}
    for row in concepts:
        name = row.get("EMR Concept Fully Specified Name", "").strip()
        short = row.get("EMR Concept short name", "").strip()
        uuid_val = row.get("EMR Concept UUID", "").strip()
        if name:
            name_map[name.casefold()] = row
        if short and short.casefold() != name.casefold():
            name_map[short.casefold()] = row
        normal = normalise(name)
        if normal and normal not in name_map:
            name_map[normal] = row
        if uuid_val:
            name_map[uuid_val] = row
    return name_map


def generate_form_for_stage(
    stage_name: str,
    metadata: dict,
    concepts: list[dict[str, str]],
    encounter_type: str,
    excel_rows_by_stage: dict[str, list[dict[str, str]]] | None = None,
) -> dict | None:
    stage = next(
        (
            item
            for item in metadata.get("programStages", [])
            if item.get("name") == stage_name
        ),
        None,
    )
    if not stage:
        raise ValueError(f"DHIS2 program stage not found: {stage_name}")

    stage_id = stage["id"]
    sections = [
        item
        for item in metadata.get("programStageSections", [])
        if item.get("programStage", {}).get("id") == stage_id
    ]
    if not sections:
        psdes = stage.get("programStageDataElements", [])
        if psdes:
            psdes_sorted = sorted(
                psdes, key=lambda psde: psde.get("sortOrder", 999999)
            )
            sections = [
                {
                    "name": stage.get("name", ""),
                    "sortOrder": 0,
                    "dataElements": [
                        {"id": psde["dataElement"]["id"]} for psde in psdes_sorted
                    ],
                }
            ]
        else:
            return None
    sections.sort(
        key=lambda item: (item.get("sortOrder", 999999), item.get("name", ""))
    )

    metadata_des_by_id = {de["id"]: de for de in metadata.get("dataElements", [])}
    concept_map = build_concept_map(concepts)
    occupied = {
        row.get("EMR Concept UUID", "").strip().lower() for row in concepts
    }
    form_uuid = unique_uuid(occupied)
    used_ids: defaultdict[str, int] = defaultdict(int)
    report: list[dict[str, object]] = []
    json_sections: list[dict[str, object]] = []
    mapped_dhis_ids: set[str] = set()

    def lookup(name: str) -> dict[str, str] | None:
        key = (name or "").strip()
        if not key:
            return None
        row = concept_map.get(key.casefold())
        if row:
            return row
        row = concept_map.get(normalise(key))
        if row:
            return row
        candidates = [
            v["EMR Concept Fully Specified Name"]
            for v in concepts
            if v.get("EMR Concept Fully Specified Name")
        ]
        closest = difflib.get_close_matches(key, candidates, n=1, cutoff=0.85)
        if closest:
            return concept_map.get(closest[0].casefold())
        return None

    stage_rows = (excel_rows_by_stage or {}).get(stage_name, [])
    by_dhis_id = {row.get("Data Element ID", "").strip(): row for row in stage_rows}

    for section in sections:
        raw_label = section.get("name", "")
        label = raw_label.strip() or stage_name
        questions: list[dict[str, object]] = []
        for element_ref in section.get("dataElements", []):
            dhis_id = element_ref.get("id", "")
            source = by_dhis_id.get(dhis_id)
            dhis_value_type = ""
            if not source:
                meta_de = metadata_des_by_id.get(dhis_id)
                if meta_de:
                    dhis_value_type = meta_de.get("valueType", "")
                    source = {
                        "Data Element ID": meta_de.get("id", ""),
                        "Data Element Name": meta_de.get("name", ""),
                        "Form Name": meta_de.get("formName", "")
                        or meta_de.get("name", ""),
                        "Data Type": dhis_value_type,
                        "Options": "",
                        "Value Type": dhis_value_type,
                    }
                else:
                    report.append(
                        {
                            "section": label,
                            "section_order": section.get("sortOrder"),
                            "dhis_data_element_id": dhis_id,
                            "status": "missing_excel_row",
                            "review_required": "yes",
                        }
                    )
                    continue
            else:
                meta_de = metadata_des_by_id.get(dhis_id)
                if meta_de:
                    dhis_value_type = meta_de.get("valueType", "")
                    source["Value Type"] = dhis_value_type

            mapped_dhis_ids.add(dhis_id)
            override_name = CONCEPT_OVERRIDES.get(dhis_id)
            concept = lookup(override_name) if override_name else None
            method, score = (
                ("approved-override", 100.0)
                if concept
                else match_concept(source.get("Data Element Name", ""), concepts)[
                    1:
                ]
            )
            if not concept:
                concept, method, score = match_concept(
                    source.get("Data Element Name", ""), concepts
                )

            base_id = camel_case(source.get("Form Name", ""))
            used_ids[base_id] += 1
            question_id = (
                base_id if used_ids[base_id] == 1 else f"{base_id}{used_ids[base_id]}"
            )
            review = concept is None
            report_row = {
                "section": label,
                "section_order": section.get("sortOrder"),
                "dhis_data_element_id": dhis_id,
                "data_element_name": source.get("Data Element Name", ""),
                "form_name": source.get("Form Name", ""),
                "question_id": question_id,
                "matched_concept": (concept or {}).get(
                    "EMR Concept Fully Specified Name", ""
                ),
                "concept_uuid": (concept or {}).get("EMR Concept UUID", ""),
                "concept_datatype": (concept or {}).get(
                    "EMR concept Data Type", ""
                ),
                "match_method": method,
                "confidence": score,
                "status": "matched" if concept else "unmatched",
                "review_required": "yes" if review else "no",
            }
            report.append(report_row)
            if review:
                continue

            option_labels = excel_option_labels(source)
            answer_names = option_labels or [
                part.strip()
                for part in concept.get("EMR Options (Answers)", "").split(";")
                if part.strip()
            ]
            is_yes_no = {label.casefold() for label in answer_names} == {"yes", "no"}
            rendering = determine_rendering(
                source, concept, answer_names, dhis_value_type
            )
            question_options: dict[str, object] = {
                "rendering": rendering,
                "concept": concept["EMR Concept UUID"],
            }
            if rendering == "checkbox-searchable":
                answers = []
                for answer_name in answer_names:
                    ans = lookup(answer_name)
                    if ans:
                        answers.append(
                            {
                                "concept": ans["EMR Concept UUID"],
                                "label": answer_name,
                            }
                        )
                question_options["answers"] = answers
                if answer_names and len(answers) != len(answer_names):
                    report_row["status"] = (
                        "backing_concept_matched_answer_options_need_mapping"
                    )
                    report_row["review_required"] = "yes"
            elif is_yes_no:
                question_options["answers"] = YES_NO_ANSWERS
            elif rendering in ("radio", "select", "checkbox"):
                answers = []
                for answer_name in answer_names:
                    ans = lookup(answer_name)
                    if ans:
                        answers.append(
                            {
                                "concept": ans["EMR Concept UUID"],
                                "label": answer_name,
                            }
                        )
                question_options["answers"] = answers
                if answer_names and len(answers) != len(answer_names):
                    report_row["status"] = (
                        "backing_concept_matched_answer_options_need_mapping"
                    )
                    report_row["review_required"] = "yes"

            questions.append(
                {
                    "label": source.get("Form Name", ""),
                    "id": question_id,
                    "type": "obs",
                    "questionOptions": question_options,
                    "validators": [],
                }
            )
        json_sections.append(
            {"label": label, "isExpanded": "true", "questions": questions}
        )

    for row in stage_rows:
        if row.get("Data Element ID", "").strip() not in mapped_dhis_ids:
            report.append(
                {
                    "dhis_data_element_id": row.get("Data Element ID", ""),
                    "data_element_name": row.get("Data Element Name", ""),
                    "form_name": row.get("Form Name", ""),
                    "status": "not_in_dhis_section",
                    "review_required": "yes",
                }
            )

    safe_name = re.sub(r"[^a-zA-Z0-9]+", "-", stage_name).strip("-").lower()
    schema = {
        "name": stage_name,
        "pages": [{"label": stage_name, "sections": json_sections}],
        "processor": "EncounterFormProcessor",
        "encounterType": encounter_type,
        "referencedForms": [],
        "uuid": form_uuid,
        "description": stage_name,
        "version": "1.0",
    }
    return {
        "schema": schema,
        "report": report,
        "form_uuid": form_uuid,
        "stage_name": stage_name,
        "safe_name": safe_name,
        "questions_count": sum(len(s["questions"]) for s in json_sections),
    }


def safe_program_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()


def generate_forms_for_program(
    program_name: str,
    metadata_path: Path,
    concepts_path: Path,
    output_dir: Path,
    encounter_type: str = "",
    data_dictionary_path: Path | None = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    log = log_fn or (lambda msg: None)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    concepts = read_concepts(concepts_path)

    program = next(
        (
            p
            for p in metadata.get("programs", [])
            if p.get("name") == program_name
        ),
        None,
    )
    if not program:
        raise ValueError(f"Program not found: {program_name}")

    program_id = program["id"]
    stages = [
        s
        for s in metadata.get("programStages", [])
        if s.get("program", {}).get("id") == program_id
    ]
    if not stages:
        raise ValueError(f"No stages found for program: {program_name}")

    excel_rows_by_stage = None
    if data_dictionary_path and data_dictionary_path.exists():
        excel_rows = read_xlsx_rows(data_dictionary_path)
        excel_rows_by_stage = {}
        current_stage = ""
        for row in excel_rows:
            current_stage = row.get("Stage Name", "").strip() or current_stage
            if current_stage:
                excel_rows_by_stage.setdefault(current_stage, []).append(row)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prog_safe = safe_program_name(program_name)
    stage_dir = output_dir / prog_safe
    stage_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for stage in stages:
        stage_name = stage["name"]
        log(f"Generating form schema for stage: {stage_name}")
        result = generate_form_for_stage(
            stage_name=stage_name,
            metadata=metadata,
            concepts=concepts,
            encounter_type=encounter_type,
            excel_rows_by_stage=excel_rows_by_stage,
        )
        if result is None:
            continue
        safe_name = result["safe_name"]
        (stage_dir / f"{safe_name}.form.json").write_text(
            json.dumps(result["schema"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        fields = [
            "section",
            "section_order",
            "dhis_data_element_id",
            "data_element_name",
            "form_name",
            "question_id",
            "matched_concept",
            "concept_uuid",
            "concept_datatype",
            "match_method",
            "confidence",
            "status",
            "review_required",
        ]
        write_csv(
            stage_dir / f"{safe_name}.mapping-report.csv",
            result["report"],
            fields,
        )
        write_csv(
            stage_dir / f"{safe_name}.form-uuid-report.csv",
            [
                {
                    "form_name": stage_name,
                    "form_uuid": result["form_uuid"],
                    "encounter_type": encounter_type,
                }
            ],
            ["form_name", "form_uuid", "encounter_type"],
        )
        unresolved = [
            row for row in result["report"] if row.get("review_required") == "yes"
        ]
        write_csv(
            stage_dir / f"{safe_name}.review-required.csv", unresolved, fields
        )
        result["unresolved_count"] = len(unresolved)
        results.append(result)

    return results
