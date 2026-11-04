"""DHIS2 -> OpenMRS 3.x Concept Structure Converter.

Converts either:
  (a) One or more data dictionary Excel exports (.xlsx)
  (b) Full DHIS2 tracker metadata JSON export
into a folder tree of import-ready concept and concept-set JSON files.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Callable, Optional
import openpyxl

DATATYPE_MAP = {
    "TEXT": "Text",
    "LONG_TEXT": "Text",
    "EMAIL": "Text",
    "PHONE_NUMBER": "Text",
    "URL": "Text",
    "USERNAME": "Text",
    "ORGANISATION_UNIT": "Text",
    "TRACKER_ASSOCIATE": "Text",
    "MULTI_TEXT": "Text",
    "FILE_RESOURCE": "Text",
    "IMAGE": "Text",
    "COORDINATE": "Text",
    "AGE_TYPE": "Text",
    "INTEGER": "Numeric",
    "INTEGER_POSITIVE": "Numeric",
    "INTEGER_NEGATIVE": "Numeric",
    "INTEGER_ZERO_OR_POSITIVE": "Numeric",
    "NUMBER": "Numeric",
    "PERCENTAGE": "Numeric",
    "UNIT_INTERVAL": "Numeric",
    "DATE": "Date",
    "AGE": "Date",
    "DATETIME": "Datetime",
    "TIME": "Time",
    "BOOLEAN": "Boolean",
    "TRUE_ONLY": "Boolean",
}


def resolve_datatype(
    raw_value_type: str,
    has_options: bool,
    log_fn: Callable[[str], None],
    element_name: str,
) -> str:
    if has_options:
        return "Coded"
    key = (raw_value_type or "").strip().upper()
    if key in DATATYPE_MAP:
        return DATATYPE_MAP[key]
    log_fn(
        f"    NOTE: unrecognized data type '{raw_value_type}' on '{element_name}' -> defaulting to 'Text'"
    )
    return "Text"


def sanitize_folder_name(name: str, fallback: str = "Unnamed") -> str:
    name = (name or "").strip() or fallback
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = name.strip(" .")
    if not name:
        name = fallback
    return name[:100]


def unique_path(base_dir: Path, name: str) -> Path:
    candidate = base_dir / name
    if not candidate.exists():
        return candidate
    i = 2
    while (base_dir / f"{name} ({i})").exists():
        i += 1
    return base_dir / f"{name} ({i})"


def parse_options_string(options_raw: str) -> list[str]:
    if not options_raw:
        return []
    answers = []
    for chunk in str(options_raw).split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            _, opt_name = chunk.split(":", 1)
            opt_name = opt_name.strip()
        else:
            opt_name = chunk
        if opt_name:
            answers.append(opt_name)
    return answers


def load_dictionary_rows(path: str | Path) -> list[list[Any]]:
    p = Path(path)
    if not p.is_file():
        raise RuntimeError(f"File not found: {path}")

    ext = p.suffix.lower()
    if ext == ".csv":
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                with open(p, mode="r", encoding=enc, errors="replace") as f:
                    return list(csv.reader(f))
            except Exception:
                continue
        raise RuntimeError(f"Could not read CSV file: {path}")
    elif ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        wb = openpyxl.load_workbook(p, data_only=True)
        ws = wb.active
        return list(ws.iter_rows(values_only=True))
    elif ext == ".tsv":
        with open(p, mode="r", encoding="utf-8-sig", errors="replace") as f:
            return list(csv.reader(f, delimiter="\t"))
    else:
        try:
            wb = openpyxl.load_workbook(p, data_only=True)
            return list(wb.active.iter_rows(values_only=True))
        except Exception:
            with open(p, mode="r", encoding="utf-8-sig", errors="replace") as f:
                return list(csv.reader(f))


def extract_programs_from_file(file_path: str | Path) -> list[dict]:
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Case 1: DHIS2 Metadata JSON
    if p.suffix.lower() == ".json":
        with open(p, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        indexer = Dhis2Metadata(data)
        all_stages = data.get("programStages", [])
        progs = []
        for pid, name in indexer.program_names():
            stage_names = [
                s.get("name", "")
                for s in all_stages
                if s.get("program", {}).get("id") == pid and s.get("name")
            ]
            progs.append({
                "id": pid,
                "name": name,
                "stages": stage_names,
                "stages_count": len(stage_names),
                "type": "metadata_json",
            })
        return progs

    # Case 2: Data Dictionary CSV or Excel
    rows = load_dictionary_rows(p)
    if not rows:
        return []

    header = [str(c).strip().lower() if c is not None else "" for c in rows[0]]

    # Check for explicit Program column
    prog_col_idx = None
    for cand in ("program", "program name", "program_name", "prog_name"):
        if cand in header:
            prog_col_idx = header.index(cand)
            break

    if prog_col_idx is not None:
        prog_counts = {}
        for r in rows[1:]:
            if prog_col_idx < len(r) and r[prog_col_idx] is not None:
                val = str(r[prog_col_idx]).strip()
                if val:
                    prog_counts[val] = prog_counts.get(val, 0) + 1
        if prog_counts:
            return [
                {
                    "id": name,
                    "name": name,
                    "elements_count": count,
                    "type": "data_dictionary",
                }
                for name, count in sorted(prog_counts.items())
            ]

    # Inferred single program dictionary
    fallback_name = guess_program_name_from_filename(p) or "Program"
    stage_col_idx = None
    for cand in ("stage name", "stage_name", "stage", "form name", "form_name"):
        if cand in header:
            stage_col_idx = header.index(cand)
            break

    stages_found = set()
    if stage_col_idx is not None:
        for r in rows[1:]:
            if stage_col_idx < len(r) and r[stage_col_idx] is not None:
                sval = str(r[stage_col_idx]).strip()
                if sval:
                    stages_found.add(sval)

    return [
        {
            "id": fallback_name,
            "name": fallback_name,
            "stages_count": len(stages_found) if stages_found else 1,
            "elements_count": max(0, len(rows) - 1),
            "type": "data_dictionary",
        }
    ]


def parse_excel_dictionary(
    path: str | Path,
    program_name_override: Optional[str] = None,
    target_program_name: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    rows = load_dictionary_rows(path)
    if not rows:
        raise RuntimeError(f"Data dictionary file {path} has no rows")

    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    col_idx = {name.lower(): i for i, name in enumerate(header)}

    def col_val(row, *candidates):
        for c in candidates:
            idx = col_idx.get(c.lower())
            if idx is not None and idx < len(row) and row[idx] is not None:
                return str(row[idx]).strip()
        return ""

    program_name = (
        target_program_name
        or program_name_override
        or guess_program_name_from_filename(path)
        or "Program"
    )

    stages: dict[str, dict] = {}
    stage_order: list[str] = []

    for r in rows[1:]:
        row_prog = col_val(r, "Program", "Program Name", "program_name", "prog_name")
        if target_program_name and row_prog and row_prog.lower() != target_program_name.lower():
            continue

        stage_name = col_val(r, "Stage Name", "stage_name", "stage") or "General"
        section_name = col_val(r, "Section Name", "section_name", "section")
        elem_name = col_val(
            r,
            "Data Element Name",
            "data_element_name",
            "element_name",
            "name",
            "field label",
            "variable / field name",
        )
        form_name = col_val(r, "Form Name", "form_name")
        raw_datatype = col_val(r, "Data Type", "data_type", "type", "field type")
        options_raw = col_val(r, "Options", "options", "choices, calculations, or slider labels")

        if not elem_name:
            continue

        answers = parse_options_string(options_raw)

        if stage_name not in stages:
            stages[stage_name] = {
                "order": [],
                "sections": {},
                "has_sections": False,
            }
            stage_order.append(stage_name)

        stage_bucket = stages[stage_name]
        has_real_section = bool(section_name)
        section_key = section_name if has_real_section else stage_name
        if has_real_section:
            stage_bucket["has_sections"] = True

        if section_key not in stage_bucket["sections"]:
            stage_bucket["sections"][section_key] = []
            stage_bucket["order"].append(section_key)

        stage_bucket["sections"][section_key].append(
            {
                "name": elem_name,
                "form_name": form_name,
                "raw_datatype": raw_datatype,
                "answers": answers,
            }
        )

    stages_out = []
    for stage_name in stage_order:
        bucket = stages[stage_name]
        sections_out = []
        for section_name in bucket["order"]:
            sections_out.append(
                {"name": section_name, "elements": bucket["sections"][section_name]}
            )
        stages_out.append(
            {
                "name": stage_name,
                "sections": sections_out,
                "has_sections": bucket["has_sections"],
            }
        )

    return {"name": program_name, "stages": stages_out}


def guess_program_name_from_filename(path: str | Path) -> str:
    stem = Path(path).stem
    stem = re.sub(
        r"(_dhis2_DD_for_openmrs3x|_DD_for_openmrs3x|_dhis2_DD|_DD)$",
        "",
        stem,
        flags=re.IGNORECASE,
    )
    stem = stem.replace("_", " ").strip()
    return stem or Path(path).stem


class Dhis2Metadata:
    """Indexes raw DHIS2 metadata export by ID for fast lookup."""

    def __init__(self, data: dict, log_fn: Optional[Callable[[str], None]] = None):
        self.data = data
        self.log = log_fn or (lambda msg: None)
        self.by_id: dict[str, dict] = {}
        for key in (
            "dataElements",
            "optionSets",
            "options",
            "trackedEntityAttributes",
            "programStages",
            "programStageSections",
            "programs",
        ):
            self.by_id[key] = {
                item["id"]: item for item in data.get(key, []) if "id" in item
            }

    def program_names(self) -> list[tuple[str, str]]:
        return [
            (p["id"], p.get("name", p["id"]))
            for p in self.data.get("programs", [])
        ]

    def _element_from_data_element(self, de_id: str) -> Optional[dict]:
        de = self.by_id["dataElements"].get(de_id)
        if de is None:
            self.log(
                f"    WARNING: dataElement {de_id} referenced but not found in metadata, skipping"
            )
            return None
        return self._build_element(de)

    def _build_element(self, de_or_tea: dict) -> dict:
        name = de_or_tea.get("name", "").strip()
        form_name = de_or_tea.get("formName", "") or ""
        raw_datatype = de_or_tea.get("valueType", "")
        answers = []
        option_set_ref = de_or_tea.get("optionSet")
        if option_set_ref:
            os_id = option_set_ref.get("id")
            os_ = self.by_id["optionSets"].get(os_id)
            if os_:
                opts = []
                orefs = os_.get("options", [])
                if orefs:
                    for oref in orefs:
                        opt = self.by_id["options"].get(oref.get("id"))
                        if opt:
                            opts.append(opt)
                else:
                    for opt_cand in self.by_id["options"].values():
                        if opt_cand.get("optionSet", {}).get("id") == os_id:
                            opts.append(opt_cand)
                opts.sort(key=lambda o: o.get("sortOrder", 0))
                answers = [
                    o.get("name", "").strip() for o in opts if o.get("name")
                ]
        return {
            "name": name,
            "form_name": form_name,
            "raw_datatype": raw_datatype,
            "answers": answers,
        }

    def build_program(self, program_id: str) -> dict:
        prog = self.by_id["programs"].get(program_id)
        if prog is None:
            raise RuntimeError(f"Program id {program_id} not found")
        prog_name = prog.get("name", program_id)
        self.log(f"  Building program: {prog_name}")

        stages_out = []

        teas = prog.get("programTrackedEntityAttributes", [])
        if teas:
            tea_elements = []
            teas_sorted = sorted(teas, key=lambda t: t.get("sortOrder", 0))
            for t in teas_sorted:
                tea_ref = t.get("trackedEntityAttribute")
                if not tea_ref:
                    continue
                tea = self.by_id["trackedEntityAttributes"].get(tea_ref.get("id"))
                if tea is None:
                    continue
                tea_elements.append(self._build_element(tea))
            if tea_elements:
                stages_out.append(
                    {
                        "name": "Tracked Entity Attributes",
                        "sections": [
                            {
                                "name": "Tracked Entity Attributes",
                                "elements": tea_elements,
                            }
                        ],
                        "has_sections": False,
                    }
                )

        stage_refs = prog.get("programStages", [])
        stage_objs = []
        if stage_refs:
            for ref in stage_refs:
                ps = self.by_id["programStages"].get(ref.get("id"))
                if ps:
                    stage_objs.append(ps)
        else:
            for ps in self.by_id["programStages"].values():
                if ps.get("program", {}).get("id") == program_id:
                    stage_objs.append(ps)
        stage_objs.sort(key=lambda s: s.get("sortOrder", 0))

        for ps in stage_objs:
            stage_name = ps.get("name", "").strip() or "Unnamed Stage"
            section_refs = ps.get("programStageSections", [])
            section_objs = []

            if section_refs:
                for sref in section_refs:
                    sec = self.by_id["programStageSections"].get(sref.get("id"))
                    if sec:
                        section_objs.append(sec)
            else:
                for sec in self.by_id["programStageSections"].values():
                    if sec.get("programStage", {}).get("id") == ps.get("id"):
                        section_objs.append(sec)

            if section_objs:
                section_objs.sort(key=lambda s: s.get("sortOrder", 0))

                sections_out = []
                blank_count = 0
                for sec in section_objs:
                    sec_name = (sec.get("name") or "").strip()
                    if not sec_name:
                        blank_count += 1
                        sec_name = (
                            stage_name
                            if blank_count == 1
                            else f"{stage_name} (unnamed section {blank_count})"
                        )
                    elements = []
                    for de_ref in sec.get("dataElements", []):
                        el = self._element_from_data_element(de_ref.get("id"))
                        if el:
                            elements.append(el)
                    sections_out.append({"name": sec_name, "elements": elements})
                stages_out.append(
                    {
                        "name": stage_name,
                        "sections": sections_out,
                        "has_sections": True,
                    }
                )
            else:
                pdes = sorted(
                    ps.get("programStageDataElements", []),
                    key=lambda d: d.get("sortOrder", 0),
                )
                elements = []
                for pde in pdes:
                    de_ref = pde.get("dataElement")
                    if not de_ref:
                        continue
                    el = self._element_from_data_element(de_ref.get("id"))
                    if el:
                        elements.append(el)
                stages_out.append(
                    {
                        "name": stage_name,
                        "sections": [{"name": stage_name, "elements": elements}],
                        "has_sections": False,
                    }
                )

        return {"name": prog_name, "stages": stages_out}


def write_program_output(
    program: dict,
    out_root: Path,
    log_fn: Callable[[str], None],
    global_name_tracker: dict[str, list[str]],
) -> dict:
    prog_dir = out_root / sanitize_folder_name(program["name"], "Program")
    prog_dir.mkdir(parents=True, exist_ok=True)
    log_fn(f"\nProgram: {program['name']}  -> {prog_dir}")

    stage_used_names = set()
    section_count = 0
    concept_count = 0
    stage_set_count = 0

    for stage in program["stages"]:
        stage_folder_name = sanitize_folder_name(stage["name"], "Stage")
        stage_dir = prog_dir / stage_folder_name
        if stage_dir.exists() and stage["name"] not in stage_used_names:
            stage_dir = unique_path(prog_dir, stage_folder_name)
        stage_used_names.add(stage["name"])
        stage_dir.mkdir(parents=True, exist_ok=True)

        section_used_names = set()
        for section in stage["sections"]:
            sec_folder_name = sanitize_folder_name(section["name"], "Section")
            sec_dir = stage_dir / sec_folder_name
            if sec_dir.exists() and section["name"] not in section_used_names:
                sec_dir = unique_path(stage_dir, sec_folder_name)
            section_used_names.add(section["name"])
            sec_dir.mkdir(parents=True, exist_ok=True)

            concepts_out = []
            member_names = []
            for el in section["elements"]:
                fsn = el["name"]
                if not fsn:
                    continue
                short_name = el.get("form_name", "") or ""
                if short_name.strip().lower() == fsn.strip().lower():
                    short_name = ""
                has_options = bool(el.get("answers"))
                datatype = resolve_datatype(
                    el.get("raw_datatype"), has_options, log_fn, fsn
                )

                concepts_out.append(
                    {
                        "uuid": "",
                        "fully_specified_name": fsn,
                        "short_name": short_name,
                        "description": "",
                        "concept_class": "Misc",
                        "datatype": datatype,
                        "locale": "en",
                        "synonyms": [],
                        "answers": el.get("answers", []),
                    }
                )
                member_names.append(fsn)

                key = fsn.strip().lower()
                global_name_tracker.setdefault(key, []).append(
                    f"{program['name']} / {stage['name']} / {section['name']}"
                )

            sets_out = [
                {
                    "uuid": "",
                    "fully_specified_name": section["name"],
                    "short_name": "",
                    "description": "",
                    "concept_class": "ConvSet",
                    "locale": "en",
                    "members": member_names,
                }
            ]

            existing_names = {c["fully_specified_name"] for c in concepts_out}
            for el in section["elements"]:
                for ans in el.get("answers", []):
                    if ans not in existing_names:
                        concepts_out.append(
                            {
                                "uuid": "",
                                "fully_specified_name": ans,
                                "short_name": "",
                                "description": "",
                                "concept_class": "Misc",
                                "datatype": "N/A",
                                "locale": "en",
                                "synonyms": [],
                                "answers": [],
                            }
                        )
                        existing_names.add(ans)

            out_c = sec_dir / "concepts_import.json"
            out_s = sec_dir / "concept_sets_import.json"
            with open(out_c, "w", encoding="utf-8") as f:
                json.dump(concepts_out, f, indent=2, ensure_ascii=False)
            with open(out_s, "w", encoding="utf-8") as f:
                json.dump(sets_out, f, indent=2, ensure_ascii=False)

            section_count += 1
            concept_count += len(concepts_out)

        if stage["has_sections"]:
            stage_set = [
                {
                    "uuid": "",
                    "fully_specified_name": stage["name"],
                    "short_name": "",
                    "description": "",
                    "concept_class": "ConvSet",
                    "locale": "en",
                    "members": [sec["name"] for sec in stage["sections"]],
                }
            ]
            stage_c = stage_dir / "concepts_import.json"
            stage_s = stage_dir / "concept_sets_import.json"
            with open(stage_c, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)
            with open(stage_s, "w", encoding="utf-8") as f:
                json.dump(stage_set, f, indent=2, ensure_ascii=False)
            stage_set_count += 1

    return {
        "program_dir": str(prog_dir),
        "section_count": section_count,
        "concept_count": concept_count,
        "stage_set_count": stage_set_count,
    }


def run_metadata_conversion(
    excel_paths: Optional[list[str | Path]] = None,
    json_path: Optional[str | Path] = None,
    selected_program_ids: Optional[list[str]] = None,
    out_dir: str | Path = Path("./output_concepts"),
    log_fn: Optional[Callable[[str], None]] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    programs = []
    if excel_paths:
        for ep in excel_paths:
            log(f"Reading Data Dictionary: {ep}")
            extracted = extract_programs_from_file(ep)
            if selected_program_ids and extracted:
                matched_progs = [
                    p for p in extracted
                    if p["id"] in selected_program_ids or p["name"] in selected_program_ids
                ]
                if matched_progs:
                    for mp in matched_progs:
                        log(f"  Converting program: {mp['name']}")
                        p = parse_excel_dictionary(ep, target_program_name=mp["name"], log_fn=log)
                        programs.append(p)
                else:
                    p = parse_excel_dictionary(ep, log_fn=log)
                    programs.append(p)
            else:
                p = parse_excel_dictionary(ep, log_fn=log)
                programs.append(p)

    if json_path and Path(json_path).is_file():
        log(f"Reading DHIS2 metadata JSON: {json_path}")
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        indexer = Dhis2Metadata(data, log_fn=log)
        if selected_program_ids:
            prog_ids = [
                pid for pid, name in indexer.program_names()
                if pid in selected_program_ids or name in selected_program_ids
            ]
        else:
            prog_ids = [pid for pid, _ in indexer.program_names()]
        for pid in prog_ids:
            try:
                p = indexer.build_program(pid)
                programs.append(p)
            except Exception as e:
                log(f"Failed to build program {pid}: {e}")

    global_names: dict[str, list[str]] = {}
    reports = []
    for p in programs:
        rep = write_program_output(p, out_path, log, global_names)
        reports.append(rep)

    return {
        "status": "success",
        "programs_converted": len(programs),
        "reports": reports,
        "output_directory": str(out_path),
    }
