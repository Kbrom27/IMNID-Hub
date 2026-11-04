from __future__ import annotations

import csv
import datetime
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import sys

_interop_dir = str(Path(__file__).resolve().parent.parent)
if _interop_dir not in sys.path:
    sys.path.insert(0, _interop_dir)

from o3app.clients.openmrs_client import ApiClient, normalize_base_url
from o3app.config import (
    FACILITIES,
    FACILITY_CODES,
    MATERNAL_PROGRAM,
    NEONATAL_PROGRAM,
    O3_METADATA_PATH,
    O3_SCHEMA_ROOT,
    RESOURCES_DIR,
    normalize_program_value,
)
from o3app.import_.importer import import_rows
from o3app.export.extractors import sanitize_filename
from o3app.extract import (
    determine_program_from_visit_type,
    get_patients_by_visit_type,
    normalize_date_filter,
    validate_date_range,
    write_o3_patients_csv,
)
from o3app.mappings import DEFAULT_MATERNAL_DICTIONARY, DEFAULT_NEONATAL_DICTIONARY
from o3app.schemas import FormRegistry, load_default_forms
from o3app.transform.mapping import set_mapping_files
from o3app.transform.pipeline import transform_rows
from o3app.utils import read_xlsx_rows


def _save_chk(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.datetime.now().isoformat()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_o3_api(base_url: str, username: str, password: str) -> ApiClient:
    api = ApiClient(base_url=normalize_base_url(base_url), username=username, password=password)
    try:
        api.session_ok = api.login_session()
    except Exception:
        api.session_ok = False
        api.get_json(f"{api.base_url}/session")
    return api


def load_form_registry(schema_root: Optional[Path] = None, log_callback: Optional[Callable[[str], None]] = None) -> FormRegistry:
    root = schema_root or O3_SCHEMA_ROOT
    if not root.is_dir():
        if log_callback:
            log_callback(
                f"Warning: O3 form schemas folder not found at {root}; "
                "obs columns will use backend concept names instead of form labels."
            )
        return FormRegistry([])
    registry = load_default_forms(root)
    if log_callback:
        log_callback(f"Loaded {len(registry.forms)} form schemas from {root}.")
    return registry


def pick_o3_mapping_files(
    program_value: str,
    custom_mapping: Optional[Path] = None,
    custom_dict: Optional[Path] = None,
    custom_value: Optional[Path] = None,
    mapping_dir: Optional[Path] = None,
) -> Tuple[Path, Path, Path]:
    o3_dir = mapping_dir or (RESOURCES_DIR / "O3")
    metadata_json = O3_METADATA_PATH if O3_METADATA_PATH.is_file() else (RESOURCES_DIR.parent / "Metadata" / "metadata.json")

    if custom_mapping and Path(custom_mapping).is_file():
        mapping_path = Path(custom_mapping)
    else:
        if program_value == MATERNAL_PROGRAM:
            mapping_path = o3_dir / "EMR-DHIS2 Tracker O3 Maternal Mapping.xlsx"
        else:
            mapping_path = o3_dir / "EMR-DHIS2 Tracker O3 Neonatal Mapping.xlsx"

    if custom_dict and Path(custom_dict).is_file():
        dictionary_path = Path(custom_dict)
    else:
        if program_value == MATERNAL_PROGRAM:
            dictionary_path = metadata_json if metadata_json.is_file() else DEFAULT_MATERNAL_DICTIONARY
            if not dictionary_path.is_file():
                dictionary_path = RESOURCES_DIR / "MID data disctionary.xlsx"
        else:
            dictionary_path = metadata_json if metadata_json.is_file() else DEFAULT_NEONATAL_DICTIONARY
            if not dictionary_path.is_file():
                dictionary_path = RESOURCES_DIR / "NCF data disctionary.xlsx"

    if custom_value and Path(custom_value).is_file():
        value_path = Path(custom_value)
    else:
        value_path = o3_dir / "EMR-DHIS2 Tracker O3 Value Mappings.csv"

    for path in (mapping_path, dictionary_path, value_path):
        if not path.is_file():
            raise RuntimeError(f"Required file not found: {path}")

    return mapping_path, dictionary_path, value_path


def run_o3_export(
    api: ApiClient,
    visit_types: Sequence[Dict[str, Any]],
    visit_type_name: str,
    facility_name: str,
    facility_code: str,
    start_date: str,
    end_date: str,
    output_path: Path,
    schema_root: Optional[Path] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[Path, str, int]:
    norm_start = normalize_date_filter(start_date)
    norm_end = normalize_date_filter(end_date)
    validate_date_range(norm_start, norm_end)

    resolved_code = facility_code.strip() or FACILITY_CODES.get(facility_name.strip(), facility_name.strip())
    if not resolved_code:
        raise ValueError("Please provide a valid facility name or code.")

    selected_visit = next((vt for vt in visit_types if vt.get("name") == visit_type_name), None)
    if not selected_visit:
        raise RuntimeError(f"Visit type '{visit_type_name}' was not found on the server.")

    program_value = determine_program_from_visit_type(visit_type_name)
    if not program_value:
        raise RuntimeError(
            "Could not determine the DHIS2 program from the visit type. Use a visit type "
            "containing 'Delivery'/'Labour' for maternal or 'NICU' for neonatal data."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    registry = load_form_registry(schema_root=schema_root, log_callback=log_callback)

    visits = api.get_visits(
        visit_start_date=norm_start,
        visit_end_date=norm_end,
        visit_type_uuid=selected_visit["uuid"],
    )
    patients = get_patients_by_visit_type(
        visits=visits,
        visit_type_uuid=selected_visit["uuid"],
        visit_start_date=norm_start,
        visit_end_date=norm_end,
        visit_type_name=visit_type_name,
    )
    if not patients:
        return output_path, program_value, 0

    if log_callback:
        log_callback(f"Matched {len(patients)} patients for '{visit_type_name}'.")

    count = write_o3_patients_csv(
        api=api,
        registry=registry,
        patients=patients,
        output_filename=output_path,
        org_unit_code=resolved_code,
        program_value=program_value,
        fetch_concurrency=4,
    )
    return output_path, program_value, count


def run_o3_transform(
    input_path: Path,
    output_path: Optional[Path] = None,
    custom_mapping: Optional[Path] = None,
    custom_dict: Optional[Path] = None,
    custom_value: Optional[Path] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[Path, int, Dict[str, int], Dict[str, List[str]]]:
    with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "program" not in reader.fieldnames:
            raise RuntimeError("The O3 export does not contain a 'program' column.")
        row = next(reader, None)
        if row is None:
            raise RuntimeError("The O3 export has no data rows.")
        program_value = normalize_program_value(row.get("program", ""))

    mapping_path, dictionary_path, value_path = pick_o3_mapping_files(
        program_value, custom_mapping, custom_dict, custom_value
    )

    out_path = output_path or input_path.with_name("dhis2_tracker_import.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    set_mapping_files(mapping_path, dictionary_path, value_path)
    row_count, counts, missing = transform_rows(input_path, out_path)

    if log_callback:
        log_callback(f"Transformed {row_count} row(s) to {out_path.name}")
        for prog, fields in missing.items():
            if fields:
                log_callback(f"  {prog}: {len(fields)} mapped field(s) could not be matched.")

    return out_path, row_count, counts, missing


def run_o3_import(
    dhis2_url: str,
    dhis2_username: str,
    dhis2_password: str,
    input_path: Path,
    log_path: Optional[Path] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    resolved_log = log_path or (input_path.parent / "dhis2_import_value_issues.csv")
    if log_callback:
        log_callback(f"{'[DRY RUN] ' if dry_run else ''}Importing {input_path.name} to DHIS2...")
    counts = import_rows(
        base_url=dhis2_url,
        username=dhis2_username,
        password=dhis2_password,
        input_path=input_path,
        log_path=resolved_log,
        dry_run=dry_run,
        log_callback=log_callback,
    )
    if log_callback:
        log_callback(f"{'[DRY RUN] ' if dry_run else ''}Import complete: {counts.get('processed', 0)} processed, errors: {counts.get('row_errors', 0)}")
    return counts


def run_o3_sync(
    emr_base_url: str,
    emr_username: str,
    emr_password: str,
    facility_name: str,
    facility_code: str,
    visit_type_name: str,
    start_date: str,
    end_date: str,
    dhis2_url: str,
    dhis2_username: str,
    dhis2_password: str,
    custom_mapping: Optional[Path] = None,
    custom_dict: Optional[Path] = None,
    custom_value: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    checkpoint_file: Optional[Path] = None,
    dry_run: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    start_time = time.time()
    default_export_base = Path("/data/exports") if Path("/data/exports").exists() else Path("exports")
    work_dir = Path(output_dir) if output_dir else (default_export_base / f"job_o3_{int(time.time() * 1000)}")
    work_dir.mkdir(parents=True, exist_ok=True)
    resolved_code = facility_code.strip() or FACILITY_CODES.get(facility_name.strip(), facility_name.strip())

    if log_callback:
        log_callback("Step 1/3: Connecting to OpenMRS 3 and exporting patients...")
    api = create_o3_api(emr_base_url, emr_username, emr_password)
    visit_types = api.get_visit_types()

    export_path = work_dir / "openmrs3_export.csv"
    export_path, program_value, count = run_o3_export(
        api=api,
        visit_types=visit_types,
        visit_type_name=visit_type_name,
        facility_name=facility_name,
        facility_code=facility_code,
        start_date=start_date,
        end_date=end_date,
        output_path=export_path,
        log_callback=log_callback,
    )

    if count == 0:
        if checkpoint_file:
            _save_chk(
                checkpoint_file,
                {
                    "status": "no_patients_found",
                    "system": "OpenMRS 3.x (O3)",
                    "facility_code": resolved_code,
                    "visit_type": visit_type_name,
                    "program": program_value,
                    "can_resume": False,
                },
            )
        return {
            "status": "success",
            "message": "No patients matched the selected visit type and date range.",
            "program": program_value,
            "facility_code": resolved_code,
            "patients_extracted": 0,
            "eligible_records_exported": 0,
            "transformed_rows": 0,
            "dhis2_import_stats": {},
            "artifacts": {},
        }

    if log_callback:
        log_callback("Step 2/3: Transforming exported patients...")
    transformed_path = work_dir / "dhis2_tracker_import.csv"
    transformed_path, row_count, transform_counts, missing = run_o3_transform(
        input_path=export_path,
        output_path=transformed_path,
        custom_mapping=custom_mapping,
        custom_dict=custom_dict,
        custom_value=custom_value,
        log_callback=log_callback,
    )

    counts: Dict[str, Any] = {
        "processed": 0,
        "created_entities": 0,
        "updated_entities": 0,
        "created_enrollments": 0,
        "upserted_events": 0,
        "unsynced_values": 0,
        "row_errors": 0,
        "skipped": 0,
        "log_file": str(work_dir / "dhis2_import_value_issues.csv"),
    }

    resolved_fac_code = facility_code.strip() or FACILITY_CODES.get(facility_name.strip(), facility_name.strip())
    if checkpoint_file:
        try:
            intermediate_checkpoint = {
                "status": "in_progress",
                "system": "OpenMRS 3.x (O3)",
                "facility_name": facility_name,
                "facility_code": resolved_fac_code,
                "program": program_value,
                "visit_type": visit_type_name,
                "patients_extracted": count,
                "transformed_rows": row_count,
                "dhis2_import_stats": counts,
                "artifacts": {
                    "work_dir": str(work_dir),
                    "export_csv": str(export_path),
                    "transformed_csv": str(transformed_path),
                    "import_log_csv": counts.get("log_file", ""),
                },
                "updated_at": datetime.datetime.now().isoformat(),
                "can_resume": True,
            }
            checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_file.write_text(json.dumps(intermediate_checkpoint, indent=2), encoding="utf-8")
        except Exception:
            pass

    if not dry_run:
        if log_callback:
            log_callback("Step 3/3: Importing transformed records to DHIS2...")
        counts = run_o3_import(
            dhis2_url=dhis2_url,
            dhis2_username=dhis2_username,
            dhis2_password=dhis2_password,
            input_path=transformed_path,
            log_path=Path(counts["log_file"]),
            log_callback=log_callback,
        )
    else:
        if log_callback:
            log_callback(f"[DRY-RUN] Preview complete for {row_count} rows. No writes to DHIS2.")

    elapsed = round(time.time() - start_time, 2)
    resolved_fac_code = facility_code.strip() or FACILITY_CODES.get(facility_name.strip(), facility_name.strip())

    checkpoint_data = {
        "status": "completed" if counts.get("row_errors", 0) == 0 else "completed_with_errors",
        "system": "OpenMRS 3.x (O3)",
        "facility_name": facility_name,
        "facility_code": resolved_fac_code,
        "program": program_value,
        "visit_type": visit_type_name,
        "patients_extracted": count,
        "dhis2_import_stats": counts,
        "artifacts": {
            "work_dir": str(work_dir),
            "export_csv": str(export_path),
            "transformed_csv": str(transformed_path),
            "import_log_csv": counts.get("log_file", ""),
        },
        "updated_at": datetime.datetime.now().isoformat(),
        "can_resume": counts.get("row_errors", 0) > 0,
    }

    if checkpoint_file:
        try:
            checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_file.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")
        except Exception as e:
            if log_callback:
                log_callback(f"Warning saving checkpoint: {e}")

    return {
        "status": checkpoint_data["status"],
        "execution_time_seconds": elapsed,
        "patients_extracted": count,
        "transformed_rows": row_count,
        "transform_counts": transform_counts,
        "missing_fields": missing,
        "dhis2_import_stats": counts,
        "checkpoint": checkpoint_data,
        "dry_run": dry_run,
        "export_csv": str(export_path),
        "transformed_csv": str(transformed_path),
    }
