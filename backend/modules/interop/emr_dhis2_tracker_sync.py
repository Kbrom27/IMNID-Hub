from __future__ import annotations

import csv
import datetime
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from clients.openmrs_client import ApiClient, normalize_base_url
from config import (
    BLANK_MARKERS,
    DETAIL_COLUMNS,
    FACILITIES,
    FACILITY_CODES,
    MATERNAL_PROGRAM,
    NEONATAL_PROGRAM,
)
from export.extractors import (
    build_patient_row,
    clean_csv_cell,
    determine_program_from_visit_type,
    get_patients_by_visit_type,
    normalize_date_filter,
    sanitize_filename,
    validate_date_range,
)
from import_.importer import import_rows
from transform.mapping import set_mapping_files
from transform.pipeline import transform_rows
from utils import require_value_mapping_csv, require_xlsx_file


def _save_chk(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.datetime.now().isoformat()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_openmrs_api(base_url: str, username: str, password: str) -> ApiClient:
    api = ApiClient(base_url=normalize_base_url(base_url), username=username, password=password)
    try:
        api.session_ok = api.login_session()
    except Exception:
        api.session_ok = False
        api.get_json(f"{api.base_url}/session")
    return api


def fetch_openmrs_export_rows(
    api: ApiClient,
    visit_types: Sequence[Dict[str, Any]],
    visit_type_name: str,
    start_date: Optional[str],
    end_date: Optional[str],
    org_unit_code: str,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[List[str], List[Dict[str, str]]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    selected_visit = next(
        (visit_type for visit_type in visit_types if visit_type.get("name") == visit_type_name),
        None,
    )
    if not selected_visit:
        raise RuntimeError(f"Visit type '{visit_type_name}' was not found on the current server.")

    if log_callback:
        log_callback(f"Loading visits for '{visit_type_name}'...")
    visits = api.get_visits(
        visit_start_date=start_date,
        visit_end_date=end_date,
        visit_type_uuid=selected_visit["uuid"],
    )
    patients = get_patients_by_visit_type(
        visits=visits,
        visit_type_uuid=selected_visit["uuid"],
        visit_start_date=start_date,
        visit_end_date=end_date,
    )
    if not patients:
        headers = [clean_csv_cell(column) for column in DETAIL_COLUMNS]
        return headers, []

    if log_callback:
        log_callback(f"Matched {len(patients)} patient(s). Fetching full patient details...")

    program_value = determine_program_from_visit_type(visit_type_name)
    all_obs_columns: List[str] = []
    seen_obs_columns = set()
    buffered_rows: List[Tuple[List[str], Dict[str, str]]] = []

    concurrency = min(8, max(1, len(patients)))
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                build_patient_row,
                api,
                patient_uuid,
                display,
                org_unit_code,
                program_value,
                visit_date,
            ): (patient_uuid, display)
            for patient_uuid, display, visit_date in patients
        }
        total_p = len(patients)
        completed = 0
        for future in as_completed(futures):
            completed += 1
            fixed_row, obs_values = future.result()
            if not fixed_row:
                continue
            for column in obs_values:
                if column not in seen_obs_columns:
                    seen_obs_columns.add(column)
                    all_obs_columns.append(column)
            buffered_rows.append((fixed_row, obs_values))
            if log_callback and (completed % 10 == 0 or completed == total_p):
                log_callback(f"Fetched details for {completed}/{total_p} patients ({len(buffered_rows)} eligible)...")

    headers = [clean_csv_cell(column) for column in DETAIL_COLUMNS + all_obs_columns]
    rows: List[Dict[str, str]] = []
    for fixed_row, obs_values in buffered_rows:
        row_values = [clean_csv_cell(value) for value in fixed_row]
        for column in all_obs_columns:
            row_values.append(clean_csv_cell(obs_values.get(column, "")))
        rows.append(dict(zip(headers, row_values)))

    return headers, rows


def write_temporary_export_csv(
    path: Path,
    headers: Sequence[str],
    rows: Sequence[Dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(headers), quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pick_bahmni_mapping_files(
    program_value: str,
    custom_mapping: Optional[Path] = None,
    custom_dict: Optional[Path] = None,
    custom_value: Optional[Path] = None,
    resources_dir: Optional[Path] = None,
) -> Tuple[Path, Path, Path]:
    res = resources_dir or (Path(__file__).resolve().parent / "Resources")
    is_maternal = (
        program_value == MATERNAL_PROGRAM
        or "maternal" in str(program_value).lower()
        or "mid" in str(program_value).lower()
    )
    if custom_mapping and Path(custom_mapping).is_file():
        mapping_path = Path(custom_mapping)
    else:
        if is_maternal:
            mapping_path = res / "EMR-DHIS2 Tracker Maternal Mapping.xlsx"
            if not mapping_path.is_file():
                mapping_path = res / "EMR-DHIS2 Tracker MID Mapping.xlsx"
        else:
            mapping_path = res / "EMR-DHIS2 Tracker Neonatal Mapping.xlsx"
            if not mapping_path.is_file():
                mapping_path = res / "EMR-DHIS2 Tracker NID Mapping.xlsx"

    if custom_dict and Path(custom_dict).is_file():
        dict_path = Path(custom_dict)
    else:
        if is_maternal:
            dict_path = res / "MID data disctionary.xlsx"
        else:
            dict_path = res / "NCF data disctionary.xlsx"

    if custom_value and Path(custom_value).is_file():
        value_path = Path(custom_value)
    else:
        if is_maternal:
            value_path = res / "EMR-DHIS2 Tracker Maternal Value Mappings.csv"
            if not value_path.is_file() or value_path.stat().st_size < 200:
                mid_val = res / "Axum Value Mapping" / "MID" / "EMR-DHIS2 Tracker Maternal Value Mappings.csv"
                if mid_val.is_file() and mid_val.stat().st_size > 200:
                    value_path = mid_val
                elif (res / "EMR-DHIS2 Tracker Value Mappings_Tula.csv").is_file():
                    value_path = res / "EMR-DHIS2 Tracker Value Mappings_Tula.csv"
                elif (res / "EMR-DHIS2 Tracker Value Mappings.csv").is_file():
                    value_path = res / "EMR-DHIS2 Tracker Value Mappings.csv"
        else:
            value_path = res / "EMR-DHIS2 Tracker Neonatal Value Mappings.csv"
            if not value_path.is_file() or value_path.stat().st_size < 200:
                ncf_val = res / "Axum Value Mapping" / "NCF" / "EMR-DHIS2 Tracker Neonatal Value Mappings.csv"
                if ncf_val.is_file() and ncf_val.stat().st_size > 200:
                    value_path = ncf_val
                elif (res / "EMR-DHIS2 Tracker Value Mappings_ax_old.csv").is_file():
                    value_path = res / "EMR-DHIS2 Tracker Value Mappings_ax_old.csv"
                elif (res / "EMR-DHIS2 Tracker Value Mappings.csv").is_file():
                    value_path = res / "EMR-DHIS2 Tracker Value Mappings.csv"

    for p in (mapping_path, dict_path, value_path):
        if not p.is_file():
            raise RuntimeError(f"Required mapping file not found: {p}")

    return mapping_path, dict_path, value_path


def run_bahmni_sync(
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
    mapping_path: Optional[Path] = None,
    dict_path: Optional[Path] = None,
    value_mapping_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    checkpoint_file: Optional[Path] = None,
    dry_run: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    start_time = time.time()
    default_export_base = Path("/data/exports") if Path("/data/exports").exists() else Path("exports")
    work_dir = Path(output_dir) if output_dir else (default_export_base / f"job_bahmni_{int(time.time() * 1000)}")
    work_dir.mkdir(parents=True, exist_ok=True)

    norm_start = normalize_date_filter(start_date)
    norm_end = normalize_date_filter(end_date)
    validate_date_range(norm_start, norm_end)

    if not facility_name.strip() and not facility_code.strip():
        raise ValueError("Facility name or code is required.")
    resolved_fac_code = facility_code.strip() or FACILITY_CODES.get(facility_name.strip(), facility_name.strip())

    program_value = determine_program_from_visit_type(visit_type_name)
    if not program_value:
        raise ValueError(f"Cannot determine DHIS2 program from visit type '{visit_type_name}'.")

    resolved_map, resolved_dict, resolved_val = pick_bahmni_mapping_files(
        program_value, mapping_path, dict_path, value_mapping_path
    )
    set_mapping_files(resolved_map, resolved_dict, resolved_val)

    if log_callback:
        log_callback(f"Connecting to EMR at {emr_base_url}...")
    api = create_openmrs_api(emr_base_url, emr_username, emr_password)
    visit_types = api.get_visit_types()

    headers, export_rows = fetch_openmrs_export_rows(
        api=api,
        visit_types=visit_types,
        visit_type_name=visit_type_name,
        start_date=norm_start,
        end_date=norm_end,
        org_unit_code=resolved_fac_code,
        log_callback=log_callback,
    )

    export_path = work_dir / "openmrs_export.csv"
    write_temporary_export_csv(export_path, headers, export_rows)
    if log_callback:
        log_callback(f"Saved EMR export with {len(export_rows)} patient rows to {export_path}")

    transformed_path = work_dir / "dhis2_tracker_import.csv"
    row_count, transform_counts, missing = transform_rows(export_path, transformed_path)
    if log_callback:
        log_callback(f"Transformed {row_count} rows. Missing fields: {missing}")

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

    checkpoint_data = {
        "status": "in_progress",
        "system": "Bahmni (OpenMRS 2.x)",
        "facility_name": facility_name,
        "facility_code": resolved_fac_code,
        "program": program_value,
        "visit_type": visit_type_name,
        "patients_extracted": len(export_rows),
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
    if checkpoint_file:
        try:
            _save_chk(checkpoint_file, checkpoint_data)
        except Exception:
            pass

    if log_callback:
        log_callback(f"{'[DRY RUN] ' if dry_run else ''}Importing {row_count} rows to DHIS2 at {dhis2_url}...")
    counts = import_rows(
        base_url=dhis2_url,
        username=dhis2_username,
        password=dhis2_password,
        input_path=transformed_path,
        log_path=Path(counts["log_file"]),
        dry_run=dry_run,
        log_callback=log_callback,
    )

    elapsed = round(time.time() - start_time, 2)
    checkpoint_data = {
        "status": "completed" if counts.get("row_errors", 0) == 0 else "completed_with_errors",
        "system": "Bahmni (OpenMRS 2.x)",
        "facility_name": facility_name,
        "facility_code": resolved_fac_code,
        "program": program_value,
        "visit_type": visit_type_name,
        "patients_extracted": len(export_rows),
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
        "patients_extracted": len(export_rows),
        "transformed_rows": row_count,
        "transform_counts": transform_counts,
        "missing_fields": missing,
        "dhis2_import_stats": counts,
        "checkpoint": checkpoint_data,
        "dry_run": dry_run,
    }
