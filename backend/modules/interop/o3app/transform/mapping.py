from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from o3app.config import (
        HEADER_SEPARATOR,
        MATERNAL_PROGRAM,
        NEONATAL_PROGRAM,
        PROGRAM_SPECS,
        RESOURCES_DIR,
        SPECIAL_COLUMNS,
        normalize_stage_name,
    )
    from o3app.models import DictionaryField, MappingField
    from o3app.rules.tracker_mapping_rules import set_value_mapping_path
    from o3app.utils import (
        blank_to_empty,
        extract_bracket_label,
        find_mapping_header,
        is_mapping_source_column,
        normalize_label,
        normalized_tokens,
        read_xlsx_rows,
        row_to_dict,
    )
except ImportError:
    from backend.modules.interop.o3app.config import (
        HEADER_SEPARATOR,
        MATERNAL_PROGRAM,
        NEONATAL_PROGRAM,
        PROGRAM_SPECS,
        RESOURCES_DIR,
        SPECIAL_COLUMNS,
        normalize_stage_name,
    )
    from backend.modules.interop.o3app.models import DictionaryField, MappingField
    from backend.modules.interop.o3app.rules.tracker_mapping_rules import set_value_mapping_path
    from backend.modules.interop.o3app.utils import (
        blank_to_empty,
        extract_bracket_label,
        find_mapping_header,
        is_mapping_source_column,
        normalize_label,
        normalized_tokens,
        read_xlsx_rows,
        row_to_dict,
    )


TARGETED_DICTIONARY_STAGE_FALLBACKS = {
    MATERNAL_PROGRAM: {"Laboratory", "Physicians Medication Order"},
    NEONATAL_PROGRAM: set(),
}

AGGREGATE_SOURCE_OVERRIDES = {
    (MATERNAL_PROGRAM, "Laboratory", "Laboratory event date"): "visit_date",
    (MATERNAL_PROGRAM, "Laboratory", "Other Laboratory Investigations"): "lab_results",
    (MATERNAL_PROGRAM, "Physicians Medication Order", "Physician Medication order event date"): "visit_date",
    (MATERNAL_PROGRAM, "Physicians Medication Order", "Medication order date"): "visit_date",
    (MATERNAL_PROGRAM, "Physicians Medication Order", "Ordered medication name"): "medications",
}

FIELD_SOURCE_ALIASES = {
    "neonate first name": "first_name",
    "neonate last name": "family_name",
    "neonate mrn": "patient_id",
    "neonate sex": "gender",
    "mothers first name": "first_name",
    "mother first name": "first_name",
    "mothers father name": "middle_name_local",
    "mother father name": "middle_name_local",
    "mothers grandfather name": "family_name",
    "mother grandfather name": "family_name",
    "mothers adress": "address1",
    "mother adress": "address1",
    "mothers address": "address1",
    "age": "age",
    "mothers phone number": "primary_contact",
    "mother phone number": "primary_contact",
    "mrn": "patient_id",
    "education level": "education_details",
    "occupation": "occupation",
}

_user_mapping_excel_path: Optional[Path] = None
_user_dictionary_excel_path: Optional[Path] = None
_user_value_mapping_csv_path: Optional[Path] = None


def set_mapping_files(
    mapping_excel_path: Path,
    dictionary_excel_path: Path,
    value_mapping_csv_path: Optional[Path] = None,
    program: Optional[str] = None,
) -> None:
    global _user_mapping_excel_path, _user_dictionary_excel_path, _user_value_mapping_csv_path

    _user_mapping_excel_path = mapping_excel_path
    _user_dictionary_excel_path = dictionary_excel_path
    _user_value_mapping_csv_path = value_mapping_csv_path

    from o3app.config import PROGRAM_SPECS as _ps, normalize_program_value

    if program:
        norm_prog = normalize_program_value(program)
        if norm_prog in _ps:
            _ps[norm_prog] = {
                "mapping_path": mapping_excel_path,
                "dictionary_path": dictionary_excel_path,
            }
    else:
        path_str = str(mapping_excel_path).lower()
        if "maternal" in path_str:
            _ps[MATERNAL_PROGRAM] = {
                "mapping_path": mapping_excel_path,
                "dictionary_path": dictionary_excel_path,
            }
        elif "neonatal" in path_str:
            _ps[NEONATAL_PROGRAM] = {
                "mapping_path": mapping_excel_path,
                "dictionary_path": dictionary_excel_path,
            }
        else:
            _ps[MATERNAL_PROGRAM] = {
                "mapping_path": mapping_excel_path,
                "dictionary_path": dictionary_excel_path,
            }
            _ps[NEONATAL_PROGRAM] = {
                "mapping_path": mapping_excel_path,
                "dictionary_path": dictionary_excel_path,
            }

    if value_mapping_csv_path:
        set_value_mapping_path(value_mapping_csv_path)


def source_column_org_unit(header: str) -> str:
    bracket_label = extract_bracket_label(header)
    if bracket_label:
        return bracket_label

    generic_headers = {"emr concept name", "emr concept", "concept name"}
    normalized = normalize_label(header)
    if normalized in generic_headers:
        return ""

    facility_tokens = [
        token
        for token in normalized_tokens(header)
        if token not in {"emr", "concept", "name", "source", "mapping", "column", "facility"}
    ]
    return " ".join(facility_tokens) or header.strip()


def read_dictionary_fields(path: Path, program_value: str = "") -> Dict[Tuple[str, str], DictionaryField]:
    if path.suffix.lower() == ".json":
        import json
        with path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        de_map = {de["id"]: de for de in meta.get("dataElements", [])}
        stage_map = {ps["id"]: ps for ps in meta.get("programStages", [])}
        opt_lookup = {o["id"]: o for o in meta.get("options", [])}
        optset_map = {os["id"]: os for os in meta.get("optionSets", [])}

        ALLOWED_PROGRAM_IDS = {"aLoraiFNkng", "QYJKpoUeg9F"}
        ALLOWED_PROGRAM_NAMES = {"maternal inpatient data", "neonatal care form"}
        prog = None
        target_name = program_value.split("/")[0].strip().lower() if program_value else ""
        target_id = program_value.split("/")[1].strip() if "/" in program_value else ""
        for p in meta.get("programs", []):
            p_id = p.get("id", "")
            p_name = p.get("name", "").lower()
            if p_id not in ALLOWED_PROGRAM_IDS and not any(allowed in p_name for allowed in ALLOWED_PROGRAM_NAMES):
                continue
            if target_id and p_id == target_id:
                prog = p
                break
            if target_name and (target_name in p_name or p_name in target_name):
                prog = p
                break
        if not prog:
            return {}

        fields: Dict[Tuple[str, str], DictionaryField] = {}
        for ps_ref in prog.get("programStages", []):
            stage = stage_map.get(ps_ref["id"], {})
            stage_name = normalize_stage_name(stage.get("name", ""))
            if not stage_name:
                continue
            for ps_de in stage.get("programStageDataElements", []):
                de_id = ps_de.get("dataElement", {}).get("id")
                de = de_map.get(de_id, {})
                data_element_name = de.get("name", "").strip()
                if not data_element_name:
                    continue
                form_name = de.get("formName", "") or data_element_name
                data_type = de.get("valueType", "")
                opt_set = de.get("optionSet")
                options_str = ""
                if opt_set:
                    os_obj = optset_map.get(opt_set.get("id"), {})
                    opt_parts = []
                    for o_ref in os_obj.get("options", []):
                        o_obj = opt_lookup.get(o_ref.get("id"), {})
                        c = str(o_obj.get("code") or "").strip()
                        n = str(o_obj.get("name") or "").strip()
                        if c and n and c != n:
                            opt_parts.append(f"{c}:{n}")
                        elif c or n:
                            opt_parts.append(c or n)
                    options_str = "; ".join(opt_parts)
                fields[(stage_name, data_element_name)] = DictionaryField(
                    stage_name=stage_name,
                    data_element_name=data_element_name,
                    data_element_id=de_id,
                    form_name=form_name,
                    data_type=data_type,
                    options_text=options_str,
                )
        tea_lookup = {tea["id"]: tea for tea in meta.get("trackedEntityAttributes", [])}
        for p_tea in prog.get("programTrackedEntityAttributes", []):
            tea_ref = p_tea.get("trackedEntityAttribute", {})
            t_id = tea_ref.get("id", "")
            full_tea = tea_lookup.get(t_id, {})
            t_name = full_tea.get("name") or tea_ref.get("name") or p_tea.get("displayName") or ""
            for prefix in ("neonatal care form", "maternal inpatient data"):
                if t_name.lower().startswith(prefix):
                    t_name = t_name[len(prefix):].strip()
            if not t_name:
                continue

            form_name = full_tea.get("formName") or t_name
            data_type = full_tea.get("valueType") or tea_ref.get("valueType", "TEXT")
            opt_set = full_tea.get("optionSet") or tea_ref.get("optionSet")
            options_str = ""
            if opt_set:
                os_obj = optset_map.get(opt_set.get("id"), {})
                opt_parts = []
                for o_ref in os_obj.get("options", []):
                    o_obj = opt_lookup.get(o_ref.get("id"), {})
                    c = str(o_obj.get("code") or "").strip()
                    n = str(o_obj.get("name") or "").strip()
                    if c and n and c != n:
                        opt_parts.append(f"{c}:{n}")
                    elif c or n:
                        opt_parts.append(c or n)
                options_str = "; ".join(opt_parts)

            fields[("Tracked Entity Attributes", t_name)] = DictionaryField(
                stage_name="Tracked Entity Attributes",
                data_element_name=t_name,
                data_element_id=t_id,
                form_name=form_name,
                data_type=data_type,
                options_text=options_str,
            )
        return fields

    rows = read_xlsx_rows(path)
    if not rows:
        raise RuntimeError(f"No rows were found in {path.name}.")

    headers = rows[0]
    fields: Dict[Tuple[str, str], DictionaryField] = {}
    for row in rows[1:]:
        item = row_to_dict(row, headers)
        stage_name = normalize_stage_name(item.get("Stage Name", "").strip())
        data_element_name = item.get("Data Element Name", "").strip()
        if not stage_name or not data_element_name:
            continue
        fields[(stage_name, data_element_name)] = DictionaryField(
            stage_name=stage_name,
            data_element_name=data_element_name,
            data_element_id=item.get("Data Element ID", "").strip(),
            form_name=item.get("Form Name", "").strip(),
            data_type=item.get("Data Type", "").strip(),
            options_text=item.get("Options", "").strip(),
        )
    return fields


def read_mapping_fields(path: Path, dictionary_fields: Dict[Tuple[str, str], DictionaryField]) -> List[MappingField]:
    rows = read_xlsx_rows(path)
    if not rows:
        raise RuntimeError(f"No rows were found in {path.name}.")

    headers = rows[0]
    stage_header = find_mapping_header(
        headers,
        ("DHIS2 Program Stage Name", "Program Stage Name", "Stage Name"),
    )
    data_element_header = find_mapping_header(
        headers,
        ("DHIS2 Data Element Name", "Data Element Name"),
    )
    source_headers = [
        header
        for header in headers
        if is_mapping_source_column(header, stage_header, data_element_header)
    ]

    if not stage_header or not data_element_header or not source_headers:
        raise RuntimeError(
            f"{path.name} must contain stage, DHIS2 data element, and EMR concept columns."
        )

    mapping_fields: List[MappingField] = []
    seen_targets = set()

    for row in rows[1:]:
        item = row_to_dict(row, headers)
        stage_name = item.get(stage_header, "").strip()
        data_element_name = item.get(data_element_header, "").strip()
        if not stage_name or not data_element_name:
            continue

        dictionary_field = dictionary_fields.get((stage_name, data_element_name))
        if dictionary_field is None:
            dictionary_field = DictionaryField(
                stage_name=stage_name,
                data_element_name=data_element_name,
                data_element_id="",
                form_name=data_element_name,
                data_type="TEXT",
                options_text="",
            )

        target_header = f"{stage_name}{HEADER_SEPARATOR}{data_element_name}"
        for source_column in source_headers:
            source_name = item.get(source_column, "").strip()
            if not source_name:
                continue

            org_unit = source_column_org_unit(source_column)
            key = (target_header, org_unit, source_name)
            if key in seen_targets:
                continue
            seen_targets.add(key)

            mapping_fields.append(
                MappingField(
                    stage_name=stage_name,
                    data_element_name=data_element_name,
                    target_header=target_header,
                    source_name=source_name,
                    form_name=dictionary_field.form_name,
                    data_type=dictionary_field.data_type,
                    options_text=dictionary_field.options_text,
                    org_unit=org_unit,
                )
            )

    return mapping_fields


def add_dictionary_stage_fallbacks(
    program: str,
    mapping_fields: List[MappingField],
    dictionary_fields: Dict[Tuple[str, str], DictionaryField],
) -> List[MappingField]:
    fallback_stages = TARGETED_DICTIONARY_STAGE_FALLBACKS.get(program, set())
    if not fallback_stages:
        return mapping_fields

    fields = list(mapping_fields)
    seen = {
        (field.target_header, field.org_unit, field.source_name)
        for field in fields
    }
    for (stage_name, data_element_name), dictionary_field in dictionary_fields.items():
        if stage_name not in fallback_stages:
            continue
        source_name = AGGREGATE_SOURCE_OVERRIDES.get(
            (program, stage_name, data_element_name),
            dictionary_field.form_name or data_element_name,
        )
        if not source_name:
            continue
        target_header = f"{stage_name}{HEADER_SEPARATOR}{data_element_name}"
        key = (target_header, "", source_name)
        if key in seen:
            continue
        seen.add(key)
        fields.append(
            MappingField(
                stage_name=stage_name,
                data_element_name=data_element_name,
                target_header=target_header,
                source_name=source_name,
                form_name=dictionary_field.form_name,
                data_type=dictionary_field.data_type,
                options_text=dictionary_field.options_text,
            )
        )

    return fields


def load_program_fields(programs: Optional[object] = None) -> Dict[str, List[MappingField]]:
    from typing import Sequence

    program_fields: Dict[str, List[MappingField]] = {}
    if isinstance(programs, str):
        selected_programs = [programs]
    else:
        selected_programs = programs or tuple(PROGRAM_SPECS.keys())
    for program in selected_programs:
        spec = PROGRAM_SPECS[program]
        dictionary_fields = read_dictionary_fields(spec["dictionary_path"], program)
        mapping_fields = read_mapping_fields(spec["mapping_path"], dictionary_fields)
        program_fields[program] = add_dictionary_stage_fallbacks(
            program,
            mapping_fields,
            dictionary_fields,
        )
    return program_fields
