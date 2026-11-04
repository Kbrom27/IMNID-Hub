import csv
import datetime
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure interop directory is in sys.path so modules resolve seamlessly
interop_dir = str(Path(__file__).resolve().parent)
if interop_dir not in sys.path:
    sys.path.insert(0, interop_dir)

from backend.core.config import settings
from backend.core.database import get_server_connection
from backend.core.jobs.engine import JobContext

from clients.openmrs_client import ApiClient, normalize_base_url
from config import (
    FACILITY_CODES,
    FACILITIES,
    MATERNAL_PROGRAM,
    NEONATAL_PROGRAM,
)
from emr_dhis2_tracker_sync import (
    run_bahmni_sync,
    create_openmrs_api,
    fetch_openmrs_export_rows,
    write_temporary_export_csv,
    pick_bahmni_mapping_files,
)
from export.extractors import (
    sanitize_filename,
    determine_program_from_visit_type,
    normalize_date_filter,
    validate_date_range,
)
from transform.mapping import set_mapping_files
from transform.pipeline import transform_rows
from o3app.sync import (
    create_o3_api,
    load_form_registry,
    pick_o3_mapping_files,
    run_o3_export,
    run_o3_transform,
    run_o3_import,
    run_o3_sync,
)
from import_.importer import import_rows

logger = logging.getLogger("imnid.interop")


def get_checkpoint_path() -> Path:
    return settings.checkpoints_dir / "sync_checkpoint.json"


def resolve_safe_output_dir(
    output_dir: Optional[str],
    fallback_sub: Optional[Path] = None,
    ctx: Optional[JobContext] = None,
) -> Path:
    default_dir = fallback_sub or settings.exports_dir
    if not output_dir or not output_dir.strip():
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir

    raw = output_dir.strip()
    target_path = Path(raw)
    if not target_path.is_absolute():
        target_path = default_dir / target_path
    try:
        target_path.mkdir(parents=True, exist_ok=True)
        test_file = target_path / f".perm_check_{os.getpid()}"
        test_file.touch()
        test_file.unlink()
        return target_path
    except (PermissionError, OSError) as e:
        msg = (
            f"Notice: Output directory '{raw}' cannot be created or written to in the container environment ({e}). "
            f"Saving output safely to '{default_dir}'."
        )
        logger.warning(msg)
        if ctx:
            ctx.log(msg, level="WARNING")
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir


def get_dhis2_credentials(server_key: str = "dhis2") -> Dict[str, str]:
    conn = get_server_connection(server_key)
    if conn:
        return {
            "base_url": conn.get("base_url") or settings.DHIS2_URL,
            "username": conn.get("username") or settings.DHIS2_USERNAME,
            "password": conn.get("secret") or settings.DHIS2_PASSWORD,
        }
    return {
        "base_url": settings.DHIS2_URL,
        "username": settings.DHIS2_USERNAME,
        "password": settings.DHIS2_PASSWORD,
    }


def get_emr_credentials(system: str = "bahmni") -> Dict[str, str]:
    server_key = "openmrs" if system.lower() in ("o3", "openmrs3") else "bahmni"
    conn = get_server_connection(server_key)
    if conn:
        return {
            "base_url": conn.get("base_url") or (settings.OPENMRS_URL if server_key == "openmrs" else settings.BAHMNI_URL),
            "username": conn.get("username") or (settings.OPENMRS_USERNAME if server_key == "openmrs" else settings.BAHMNI_USERNAME),
            "password": conn.get("secret") or (settings.OPENMRS_PASSWORD if server_key == "openmrs" else settings.BAHMNI_PASSWORD),
        }
    if server_key == "openmrs":
        return {
            "base_url": settings.OPENMRS_URL,
            "username": settings.OPENMRS_USERNAME,
            "password": settings.OPENMRS_PASSWORD,
        }
    return {
        "base_url": settings.BAHMNI_URL,
        "username": settings.BAHMNI_USERNAME,
        "password": settings.BAHMNI_PASSWORD,
    }


def get_sync_status() -> Dict[str, Any]:
    checkpoint_file = get_checkpoint_path()
    checkpoint: Dict[str, Any] = {}
    if checkpoint_file.is_file():
        try:
            checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to read checkpoint file: {e}")

    failed_records = []
    log_file = checkpoint.get("artifacts", {}).get("import_log_csv", "")
    if log_file and Path(log_file).is_file():
        try:
            with open(log_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    failed_records.append(dict(row))
        except Exception as e:
            logger.error(f"Failed to read import log file: {e}")

    return {
        "checkpoint": checkpoint,
        "failed_records_count": len(failed_records),
        "failed_records_detail": failed_records,
        "checkpoint_file": str(checkpoint_file),
    }


def get_visit_types(
    system: str = "bahmni",
    url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> List[Dict[str, str]]:
    default_types = [
        {"name": "Delivery", "uuid": "delivery"},
        {"name": "NICU", "uuid": "nicu"},
        {"name": "ANC", "uuid": "anc"},
        {"name": "Labour and Delivery", "uuid": "labour"},
        {"name": "Facility Visit", "uuid": "facility"},
        {"name": "OPD Visit", "uuid": "opd"},
    ]
    try:
        creds = get_emr_credentials(system)
        base_url = url or creds["base_url"]
        user = username or creds["username"]
        pw = password or creds["password"]
        if system.lower() in ("o3", "openmrs3"):
            api = create_o3_api(base_url, user, pw)
        else:
            api = create_openmrs_api(base_url, user, pw)
        vts = api.get_visit_types()
        results = [{"name": vt.get("name", ""), "uuid": vt.get("uuid", "")} for vt in vts if vt.get("name")]
        return results if results else default_types
    except Exception as exc:
        logger.warning(f"Failed to fetch live visit types for {system}: {exc}. Using standard defaults.")
        return default_types


def resolve_optional_file(p_str: Optional[str]) -> Optional[Path]:
    if not p_str or not str(p_str).strip():
        return None
    p = Path(str(p_str).strip())
    if p.is_file():
        return p
    cand = settings.uploads_dir / p.name
    if cand.is_file():
        return cand
    cand2 = settings.exports_dir / p.name
    if cand2.is_file():
        return cand2
    return p


# ==============================================================================
# Bahmni Workflows: 1. Export, 2. Transform, 3. Import, 4. Sync
# ==============================================================================
def run_bahmni_export_worker(
    ctx: JobContext,
    emr_base_url: str,
    emr_username: str,
    emr_password: str,
    facility_name: str,
    facility_code: str,
    visit_type_name: str,
    start_date: str,
    end_date: str,
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    norm_start = normalize_date_filter(start_date)
    norm_end = normalize_date_filter(end_date)
    validate_date_range(norm_start, norm_end)

    resolved_code = facility_code.strip() or FACILITY_CODES.get(facility_name.strip(), facility_name.strip())
    if not resolved_code:
        raise ValueError("Please provide a valid facility name or code.")

    out_dir = resolve_safe_output_dir(output_dir, settings.exports_dir, ctx=ctx)
    out_fname = filename.strip() if filename and filename.strip() else f"openmrs_export_{sanitize_filename(visit_type_name)}_{ctx.job_id}.csv"
    if not out_fname.lower().endswith(".csv"):
        out_fname += ".csv"
    out_path = out_dir / out_fname

    ctx.log(f"Connecting to OpenMRS (Bahmni) at {emr_base_url}...")
    ctx.update_progress(10, 100, "Connecting to EMR...")
    api = create_openmrs_api(emr_base_url, emr_username, emr_password)
    visit_types = api.get_visit_types()

    ctx.update_progress(30, 100, f"Extracting patients for '{visit_type_name}'...")
    headers, rows = fetch_openmrs_export_rows(
        api=api,
        visit_types=visit_types,
        visit_type_name=visit_type_name,
        start_date=norm_start,
        end_date=norm_end,
        org_unit_code=resolved_code,
        log_callback=lambda msg: ctx.log(msg),
    )

    write_temporary_export_csv(out_path, headers, rows)
    ctx.log(f"Export complete. {len(rows)} patient rows written to {out_path.name}")
    ctx.artifacts["output_file"] = out_path.name
    ctx.set_result_file(out_path.name)
    ctx.update_progress(100, 100, f"Export complete ({len(rows)} rows).")
    return {"output_file": str(out_path), "filename": out_path.name, "rows": len(rows)}


def run_bahmni_transform_worker(
    ctx: JobContext,
    input_csv_path: str,
    mapping_path: Optional[str] = None,
    dict_path: Optional[str] = None,
    value_mapping_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    in_path = Path(input_csv_path)
    if not in_path.is_file():
        cand = settings.uploads_dir / input_csv_path
        if cand.is_file():
            in_path = cand
        else:
            cand2 = settings.exports_dir / input_csv_path
            if cand2.is_file():
                in_path = cand2
            else:
                raise FileNotFoundError(f"Input CSV file not found: {input_csv_path}")

    out_dir = resolve_safe_output_dir(output_dir, settings.exports_dir, ctx=ctx)
    out_fname = filename.strip() if filename and filename.strip() else f"dhis2_tracker_import_{ctx.job_id}.csv"
    if not out_fname.lower().endswith(".csv"):
        out_fname += ".csv"
    out_path = out_dir / out_fname

    ctx.log(f"Transforming CSV: {in_path.name} -> {out_path.name}")
    ctx.update_progress(20, 100, "Setting mapping files...")

    program_val = MATERNAL_PROGRAM
    try:
        with in_path.open("r", newline="", encoding="utf-8-sig") as h:
            reader = csv.DictReader(h)
            first_row = next(reader, {}) or {}
            program_val = first_row.get("program", "") or MATERNAL_PROGRAM
    except Exception:
        pass

    custom_val = resolve_optional_file(value_mapping_path)
    if not custom_val or not custom_val.is_file():
        expected_val_name = (
            "EMR-DHIS2 Tracker Maternal Value Mappings.csv" if program_val == MATERNAL_PROGRAM
            else "EMR-DHIS2 Tracker Neonatal Value Mappings.csv"
        )
        storage_file = get_mappings_storage_dir() / expected_val_name
        if storage_file.is_file():
            custom_val = storage_file

    custom_map = resolve_optional_file(mapping_path)
    custom_dict_p = resolve_optional_file(dict_path)

    m_path, d_path, v_path = pick_bahmni_mapping_files(
        program_value=program_val,
        custom_mapping=custom_map,
        custom_dict=custom_dict_p,
        custom_value=custom_val,
    )

    ctx.log(f"Using mapping: {m_path.name}")
    ctx.log(f"Using dictionary: {d_path.name}")
    ctx.log(f"Using value mapping: {v_path.name}")

    set_mapping_files(m_path, d_path, v_path)
    ctx.update_progress(50, 100, "Transforming rows to DHIS2 Tracker schema...")
    row_count, counts, missing_fields = transform_rows(in_path, out_path)

    ctx.log(f"Transformation complete. {row_count} row(s) transformed.")
    ctx.artifacts["output_file"] = out_path.name
    ctx.set_result_file(out_path.name)
    ctx.update_progress(100, 100, f"Transform complete ({row_count} rows).")
    return {
        "output_file": str(out_path),
        "filename": out_path.name,
        "rows": row_count,
        "counts": counts,
        "missing_fields": missing_fields,
    }


def run_bahmni_import_worker(
    ctx: JobContext,
    dhis2_url: str,
    dhis2_username: str,
    dhis2_password: str,
    input_csv_path: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    in_path = Path(input_csv_path)
    if not in_path.is_file():
        cand = settings.uploads_dir / input_csv_path
        if cand.is_file():
            in_path = cand
        else:
            cand2 = settings.exports_dir / input_csv_path
            if cand2.is_file():
                in_path = cand2
            else:
                raise FileNotFoundError(f"Input transformed CSV not found: {input_csv_path}")

    ctx.log(f"Starting DHIS2 import from {in_path.name} to {dhis2_url} (dry_run={dry_run})...")
    ctx.update_progress(20, 100, "Importing to DHIS2 Tracker...")

    log_path = in_path.with_name(f"dhis2_import_log_{ctx.job_id}.csv")
    import_stats = import_rows(
        base_url=dhis2_url,
        username=dhis2_username,
        password=dhis2_password,
        input_path=in_path,
        log_path=log_path,
        dry_run=dry_run,
        log_callback=lambda msg: ctx.log(msg),
    )

    if log_path.is_file() and log_path.stat().st_size > 0:
        ctx.artifacts["import_log"] = log_path.name

    errs = int(import_stats.get("row_errors", 0) or 0)
    proc = int(import_stats.get("processed", 0) or 0)
    succ = max(0, proc - errs)
    ctx.log(
        f"DHIS2 Import finished: {proc} processed, "
        f"{import_stats.get('created_entities', 0)} created, "
        f"{import_stats.get('updated_entities', 0)} updated, "
        f"{import_stats.get('created_enrollments', 0)} enrollments, "
        f"{import_stats.get('upserted_events', 0)} events upserted, "
        f"{errs} row errors."
    )
    ctx.update_progress(
        progress=100,
        total=proc,
        success_count=succ,
        fail_count=errs,
        message="DHIS2 Import complete.",
    )
    return {"import_stats": import_stats}


def run_bahmni_pipeline_worker(
    ctx: JobContext,
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
    dry_run: bool = False,
    output_dir: Optional[str] = None,
    export_filename: Optional[str] = None,
    transform_filename: Optional[str] = None,
    mapping_path: Optional[str] = None,
    dict_path: Optional[str] = None,
    value_mapping_path: Optional[str] = None,
) -> Dict[str, Any]:
    ctx.log(f"Starting Bahmni direct sync for visit type '{visit_type_name}' ({start_date} to {end_date})")
    ctx.update_progress(10, 100, "Extracting patients from Bahmni...")

    work_dir = resolve_safe_output_dir(output_dir, settings.exports_dir / f"job_{ctx.job_id}", ctx=ctx)
    checkpoint_file = get_checkpoint_path()

    if not value_mapping_path:
        expected_val_name = (
            "EMR-DHIS2 Tracker Maternal Value Mappings.csv" if "delivery" in visit_type_name.lower() or "maternal" in visit_type_name.lower()
            else "EMR-DHIS2 Tracker Neonatal Value Mappings.csv"
        )
        storage_file = get_mappings_storage_dir() / expected_val_name
        if storage_file.is_file():
            value_mapping_path = str(storage_file)

    initial_checkpoint = {
        "status": "in_progress",
        "system": "Bahmni (OpenMRS 2.x)",
        "facility_name": facility_name,
        "facility_code": facility_code,
        "visit_type": visit_type_name,
        "start_date": start_date,
        "end_date": end_date,
        "patients_extracted": 0,
        "transformed_rows": 0,
        "dhis2_import_stats": {},
        "artifacts": {"work_dir": str(work_dir)},
        "updated_at": datetime.datetime.now().isoformat(),
        "can_resume": False,
        "message": "Step 1/3: Extracting patients from Bahmni...",
    }
    save_sync_checkpoint(initial_checkpoint)

    try:
        res = run_bahmni_sync(
            emr_base_url=emr_base_url,
            emr_username=emr_username,
            emr_password=emr_password,
            facility_name=facility_name,
            facility_code=facility_code,
            visit_type_name=visit_type_name,
            start_date=start_date,
            end_date=end_date,
            dhis2_url=dhis2_url,
            dhis2_username=dhis2_username,
            dhis2_password=dhis2_password,
            mapping_path=resolve_optional_file(mapping_path),
            dict_path=resolve_optional_file(dict_path),
            value_mapping_path=resolve_optional_file(value_mapping_path),
            output_dir=work_dir,
            checkpoint_file=checkpoint_file,
            dry_run=dry_run,
            log_callback=lambda msg: ctx.log(msg),
        )
    except Exception as exc:
        chk = load_sync_checkpoint()
        chk["status"] = "cancelled" if ctx.is_canceled() else "interrupted"
        chk["error"] = str(exc)
        chk["message"] = "Sync cancelled by operator" if ctx.is_canceled() else f"Sync interrupted: {exc}"
        chk["updated_at"] = datetime.datetime.now().isoformat()
        save_sync_checkpoint(chk)
        raise

    if ctx.is_canceled():
        chk = load_sync_checkpoint()
        chk["status"] = "cancelled"
        chk["message"] = "Sync cancelled by operator"
        chk["updated_at"] = datetime.datetime.now().isoformat()
        save_sync_checkpoint(chk)


    if res.get("export_csv"):
        ctx.artifacts["export_file"] = Path(res["export_csv"]).name
    if res.get("transformed_csv"):
        ctx.artifacts["output_file"] = Path(res["transformed_csv"]).name
        ctx.set_result_file(Path(res["transformed_csv"]).name)

    ctx.update_progress(100, 100, "Bahmni Direct Sync Completed.")
    return res


# ==============================================================================
# OpenMRS 3 Workflows: 1. Export, 2. Transform, 3. Import, 4. Sync
# ==============================================================================
def run_o3_export_worker(
    ctx: JobContext,
    emr_base_url: str,
    emr_username: str,
    emr_password: str,
    facility_name: str,
    facility_code: str,
    visit_type_name: str,
    start_date: str,
    end_date: str,
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    out_dir = resolve_safe_output_dir(output_dir, settings.exports_dir, ctx=ctx)
    out_fname = filename.strip() if filename and filename.strip() else f"openmrs3_export_{sanitize_filename(visit_type_name)}_{ctx.job_id}.csv"
    if not out_fname.lower().endswith(".csv"):
        out_fname += ".csv"
    out_path = out_dir / out_fname

    ctx.log(f"Connecting to OpenMRS 3 at {emr_base_url}...")
    ctx.update_progress(10, 100, "Connecting to OpenMRS 3...")
    api = create_o3_api(emr_base_url, emr_username, emr_password)
    visit_types = api.get_visit_types()

    ctx.update_progress(30, 100, f"Exporting O3 patients for '{visit_type_name}'...")
    output_path, program_val, count = run_o3_export(
        api=api,
        visit_types=visit_types,
        visit_type_name=visit_type_name,
        facility_name=facility_name,
        facility_code=facility_code,
        start_date=start_date,
        end_date=end_date,
        output_path=out_path,
        log_callback=lambda msg: ctx.log(msg),
    )

    ctx.log(f"Export complete. {count} O3 patient rows written to {out_path.name}")
    ctx.artifacts["output_file"] = out_path.name
    ctx.set_result_file(out_path.name)
    ctx.update_progress(100, 100, f"Export complete ({count} patients).")
    return {"output_file": str(out_path), "filename": out_path.name, "rows": count}


def run_o3_transform_worker(
    ctx: JobContext,
    input_csv_path: str,
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
    custom_mapping: Optional[str] = None,
    custom_dict: Optional[str] = None,
    custom_value: Optional[str] = None,
) -> Dict[str, Any]:
    in_path = Path(input_csv_path)
    if not in_path.is_file():
        cand = settings.uploads_dir / input_csv_path
        if cand.is_file():
            in_path = cand
        else:
            cand2 = settings.exports_dir / input_csv_path
            if cand2.is_file():
                in_path = cand2
            else:
                raise FileNotFoundError(f"Input O3 CSV file not found: {input_csv_path}")

    out_dir = resolve_safe_output_dir(output_dir, settings.exports_dir, ctx=ctx)
    out_fname = filename.strip() if filename and filename.strip() else f"dhis2_tracker_import_o3_{ctx.job_id}.csv"
    if not out_fname.lower().endswith(".csv"):
        out_fname += ".csv"
    out_path = out_dir / out_fname

    ctx.log(f"Transforming O3 export: {in_path.name} -> {out_path.name}")
    ctx.update_progress(20, 100, "Verifying O3 mapping files...")

    output_path, row_count, counts, missing = run_o3_transform(
        input_path=in_path,
        output_path=out_path,
        custom_mapping=Path(custom_mapping) if custom_mapping else None,
        custom_dict=Path(custom_dict) if custom_dict else None,
        custom_value=Path(custom_value) if custom_value else None,
        log_callback=lambda msg: ctx.log(msg),
    )

    ctx.log(f"O3 Transformation complete. {row_count} row(s) transformed.")
    ctx.artifacts["output_file"] = out_path.name
    ctx.set_result_file(out_path.name)
    ctx.update_progress(100, 100, f"Transform complete ({row_count} rows).")
    return {
        "output_file": str(out_path),
        "filename": out_path.name,
        "rows": row_count,
        "counts": counts,
        "missing_fields": missing,
    }


def run_o3_import_worker(
    ctx: JobContext,
    dhis2_url: str,
    dhis2_username: str,
    dhis2_password: str,
    input_csv_path: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    in_path = Path(input_csv_path)
    if not in_path.is_file():
        cand = settings.uploads_dir / input_csv_path
        if cand.is_file():
            in_path = cand
        else:
            cand2 = settings.exports_dir / input_csv_path
            if cand2.is_file():
                in_path = cand2
            else:
                raise FileNotFoundError(f"Input transformed CSV not found: {input_csv_path}")

    ctx.log(f"Starting DHIS2 import from {in_path.name} to {dhis2_url} (dry_run={dry_run})...")
    ctx.update_progress(20, 100, "Importing to DHIS2 Tracker...")

    import_stats = run_o3_import(
        input_path=in_path,
        dhis2_url=dhis2_url,
        dhis2_username=dhis2_username,
        dhis2_password=dhis2_password,
        dry_run=dry_run,
        log_callback=lambda msg: ctx.log(msg),
    )

    errs = int(import_stats.get("row_errors", 0) or 0)
    proc = int(import_stats.get("processed", 0) or 0)
    succ = max(0, proc - errs)
    ctx.log(
        f"DHIS2 Import finished: {proc} processed, "
        f"{import_stats.get('created_entities', 0)} created, "
        f"{import_stats.get('updated_entities', 0)} updated, "
        f"{import_stats.get('created_enrollments', 0)} enrollments, "
        f"{import_stats.get('upserted_events', 0)} events upserted, "
        f"{errs} row errors."
    )
    ctx.update_progress(
        progress=100,
        total=proc,
        success_count=succ,
        fail_count=errs,
        message="DHIS2 Import complete.",
    )
    return {"import_stats": import_stats}


def run_o3_pipeline_worker(
    ctx: JobContext,
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
    dry_run: bool = False,
    output_dir: Optional[str] = None,
    export_filename: Optional[str] = None,
    transform_filename: Optional[str] = None,
) -> Dict[str, Any]:
    ctx.log(f"Starting OpenMRS 3 direct sync for visit type '{visit_type_name}' ({start_date} to {end_date})")
    ctx.update_progress(10, 100, "Extracting patients from OpenMRS 3...")

    work_dir = resolve_safe_output_dir(output_dir, settings.exports_dir / f"job_{ctx.job_id}", ctx=ctx)
    checkpoint_file = get_checkpoint_path()

    o3_val = Path(get_mappings_storage_dir() / "EMR-DHIS2 Tracker O3 Value Mappings.csv")
    custom_val = o3_val if o3_val.is_file() else None

    initial_checkpoint = {
        "status": "in_progress",
        "system": "OpenMRS 3.x (O3)",
        "facility_name": facility_name,
        "facility_code": facility_code,
        "visit_type": visit_type_name,
        "start_date": start_date,
        "end_date": end_date,
        "patients_extracted": 0,
        "transformed_rows": 0,
        "dhis2_import_stats": {},
        "artifacts": {"work_dir": str(work_dir)},
        "updated_at": datetime.datetime.now().isoformat(),
        "can_resume": False,
        "message": "Step 1/3: Extracting patients from OpenMRS 3...",
    }
    save_sync_checkpoint(initial_checkpoint)

    try:
        res = run_o3_sync(
            emr_base_url=emr_base_url,
            emr_username=emr_username,
            emr_password=emr_password,
            facility_name=facility_name,
            facility_code=facility_code,
            visit_type_name=visit_type_name,
            start_date=start_date,
            end_date=end_date,
            dhis2_url=dhis2_url,
            dhis2_username=dhis2_username,
            dhis2_password=dhis2_password,
            custom_value=custom_val,
            output_dir=work_dir,
            checkpoint_file=checkpoint_file,
            dry_run=dry_run,
            log_callback=lambda msg: ctx.log(msg),
        )
    except Exception as exc:
        chk = load_sync_checkpoint()
        chk["status"] = "cancelled" if ctx.is_canceled() else "interrupted"
        chk["error"] = str(exc)
        chk["message"] = "Sync cancelled by operator" if ctx.is_canceled() else f"Sync interrupted: {exc}"
        chk["updated_at"] = datetime.datetime.now().isoformat()
        save_sync_checkpoint(chk)
        raise

    if ctx.is_canceled():
        chk = load_sync_checkpoint()
        chk["status"] = "cancelled"
        chk["message"] = "Sync cancelled by operator"
        chk["updated_at"] = datetime.datetime.now().isoformat()
        save_sync_checkpoint(chk)

    if res.get("export_csv"):
        ctx.artifacts["export_file"] = Path(res["export_csv"]).name
    if res.get("transformed_csv"):
        ctx.artifacts["output_file"] = Path(res["transformed_csv"]).name
        ctx.set_result_file(Path(res["transformed_csv"]).name)

    import_stats = res.get("dhis2_import_stats", {})
    proc = int(import_stats.get("processed", 0) or res.get("transformed_rows", 0))
    errs = int(import_stats.get("row_errors", 0))
    succ = max(0, proc - errs)
    ctx.update_progress(
        progress=100,
        total=proc,
        success_count=succ,
        fail_count=errs,
        message=f"OpenMRS 3 Direct Sync Completed ({proc} processed, {errs} errors).",
    )
    return res


def run_resume_worker(
    ctx: JobContext,
    dhis2_url: Optional[str] = None,
    dhis2_username: Optional[str] = None,
    dhis2_password: Optional[str] = None,
) -> Dict[str, Any]:
    checkpoint_file = get_checkpoint_path()
    if not checkpoint_file.is_file():
        raise RuntimeError("No sync checkpoint found to resume from.")

    checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    transformed_csv = checkpoint.get("artifacts", {}).get("transformed_csv")
    if not transformed_csv or not Path(transformed_csv).is_file():
        raise RuntimeError(f"Checkpoint transformed CSV not found: {transformed_csv}")

    resolved_log = checkpoint.get("artifacts", {}).get("import_log_csv") or str(
        Path(transformed_csv).parent / "dhis2_import_value_issues.csv"
    )

    creds = get_dhis2_credentials()
    target_url = dhis2_url or checkpoint.get("dhis2_url") or creds["base_url"]
    target_user = dhis2_username or checkpoint.get("dhis2_username") or creds["username"]
    target_pass = dhis2_password or checkpoint.get("dhis2_password") or creds["password"]

    ctx.log(f"Resuming sync from {transformed_csv} into DHIS2 ({target_url})...")
    ctx.update_progress(30, 100, "Importing transformed records...")

    import_stats = import_rows(
        base_url=target_url,
        username=target_user,
        password=target_pass,
        input_path=Path(transformed_csv),
        log_path=Path(resolved_log),
    )

    checkpoint["status"] = "completed" if import_stats.get("row_errors", 0) == 0 else "completed_with_errors"
    checkpoint["dhis2_import_stats"] = import_stats
    checkpoint["can_resume"] = import_stats.get("row_errors", 0) > 0
    checkpoint["updated_at"] = datetime.datetime.now().isoformat()
    checkpoint_file.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")

    ctx.update_progress(100, 100, f"Resumption complete: {import_stats.get('processed', 0)} rows processed.")
    return {
        "status": "resumed_success",
        "dhis2_import_stats": import_stats,
        "checkpoint": checkpoint,
    }


def load_sync_checkpoint() -> Dict[str, Any]:
    checkpoint_file = get_checkpoint_path()
    if not checkpoint_file.is_file():
        return {"status": "idle", "can_resume": False, "message": "No sync checkpoint recorded yet."}
    try:
        return json.loads(checkpoint_file.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unknown", "can_resume": False}


def save_sync_checkpoint(data: Dict[str, Any]) -> None:
    checkpoint_file = get_checkpoint_path()
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.datetime.now().isoformat()
    checkpoint_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_bahmni_pipeline(
    emr_base_url: str,
    emr_username: str,
    emr_password: str,
    facility_code: str,
    visit_type_name: str,
    start_date: str,
    end_date: str,
    dhis2_url: str,
    dhis2_username: str,
    dhis2_password: str,
    facility_name: str = "",
    work_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    return run_bahmni_sync(
        emr_base_url=emr_base_url,
        emr_username=emr_username,
        emr_password=emr_password,
        facility_name=facility_name,
        facility_code=facility_code,
        visit_type_name=visit_type_name,
        start_date=start_date,
        end_date=end_date,
        dhis2_url=dhis2_url,
        dhis2_username=dhis2_username,
        dhis2_password=dhis2_password,
        output_dir=work_dir,
        checkpoint_file=get_checkpoint_path(),
        dry_run=dry_run,
    )


def run_o3_pipeline(
    emr_base_url: str,
    emr_username: str,
    emr_password: str,
    facility_code: str,
    visit_type_name: str,
    start_date: str,
    end_date: str,
    dhis2_url: str,
    dhis2_username: str,
    dhis2_password: str,
    facility_name: str = "",
    work_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    return run_o3_sync(
        emr_base_url=emr_base_url,
        emr_username=emr_username,
        emr_password=emr_password,
        facility_name=facility_name,
        facility_code=facility_code,
        visit_type_name=visit_type_name,
        start_date=start_date,
        end_date=end_date,
        dhis2_url=dhis2_url,
        dhis2_username=dhis2_username,
        dhis2_password=dhis2_password,
        output_dir=work_dir,
        checkpoint_file=get_checkpoint_path(),
        dry_run=dry_run,
    )


def resume_sync(
    dhis2_url: Optional[str] = None,
    dhis2_username: Optional[str] = None,
    dhis2_password: Optional[str] = None,
) -> Dict[str, Any]:
    checkpoint_file = get_checkpoint_path()
    if not checkpoint_file.is_file():
        raise RuntimeError("No sync checkpoint found to resume from.")
    checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    transformed_csv = checkpoint.get("artifacts", {}).get("transformed_csv")
    if not transformed_csv or not Path(transformed_csv).is_file():
        raise RuntimeError(f"Checkpoint transformed CSV not found: {transformed_csv}")
    resolved_log = checkpoint.get("artifacts", {}).get("import_log_csv") or str(
        Path(transformed_csv).parent / "dhis2_import_value_issues.csv"
    )
    creds = get_dhis2_credentials()
    target_url = dhis2_url or checkpoint.get("dhis2_url") or creds["base_url"]
    target_user = dhis2_username or checkpoint.get("dhis2_username") or creds["username"]
    target_pass = dhis2_password or checkpoint.get("dhis2_password") or creds["password"]

    import_stats = import_rows(
        base_url=target_url,
        username=target_user,
        password=target_pass,
        input_path=Path(transformed_csv),
        log_path=Path(resolved_log),
    )
    checkpoint["status"] = "completed" if import_stats.get("row_errors", 0) == 0 else "completed_with_errors"
    checkpoint["dhis2_import_stats"] = import_stats
    checkpoint["can_resume"] = import_stats.get("row_errors", 0) > 0
    checkpoint["updated_at"] = datetime.datetime.now().isoformat()
    checkpoint_file.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    return {
        "status": "resumed_success",
        "dhis2_import_stats": import_stats,
        "checkpoint": checkpoint,
    }


def get_mappings_storage_dir() -> Path:
    if Path("/data").exists():
        base = Path("/data/mappings")
    else:
        base = Path(settings.DATA_DIR) / "mappings"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_mappings_backups_dir() -> Path:
    b = get_mappings_storage_dir() / "backups"
    b.mkdir(parents=True, exist_ok=True)
    return b


def resolve_value_mapping_file(system: str = "bahmni", program: str = "maternal") -> Tuple[Path, Path, str]:
    res_dir = Path(interop_dir) / "Resources"
    if system.lower() in ("o3", "openmrs3"):
        filename = "EMR-DHIS2 Tracker O3 Value Mappings.csv"
        bundled_path = res_dir / "O3" / filename
    else:
        if program.lower() == "maternal":
            filename = "EMR-DHIS2 Tracker Maternal Value Mappings.csv"
            bundled_path = res_dir / filename
            # Fallback to the real mappings if root file is missing or a 1-row placeholder (< 200 bytes)
            if not bundled_path.is_file() or bundled_path.stat().st_size < 200:
                mid_path = res_dir / "Axum Value Mapping" / "MID" / filename
                if mid_path.is_file() and mid_path.stat().st_size > 200:
                    bundled_path = mid_path
                elif (res_dir / "EMR-DHIS2 Tracker Value Mappings_Tula.csv").is_file():
                    bundled_path = res_dir / "EMR-DHIS2 Tracker Value Mappings_Tula.csv"
        else:
            filename = "EMR-DHIS2 Tracker Neonatal Value Mappings.csv"
            bundled_path = res_dir / filename
            if not bundled_path.is_file() or bundled_path.stat().st_size < 200:
                ncf_path = res_dir / "Axum Value Mapping" / "NCF" / filename
                if ncf_path.is_file() and ncf_path.stat().st_size > 200:
                    bundled_path = ncf_path
                elif (res_dir / "EMR-DHIS2 Tracker Value Mappings_ax_old.csv").is_file():
                    bundled_path = res_dir / "EMR-DHIS2 Tracker Value Mappings_ax_old.csv"

    storage_path = get_mappings_storage_dir() / filename
    if storage_path.is_file():
        return storage_path, bundled_path, filename
    return bundled_path, bundled_path, filename


def is_placeholder_rows(rows: List[Dict[str, str]]) -> bool:
    if not rows:
        return True
    if len(rows) == 1:
        first = rows[0]
        vals = [str(v).strip().lower() for v in first.values() if str(v).strip()]
        if not vals or all(v == "string" for v in vals):
            return True
    return False


def get_value_mappings(system: str = "bahmni", program: str = "maternal", custom_path: Optional[str] = None) -> Dict[str, Any]:
    if custom_path and Path(custom_path).is_file():
        val_path = Path(custom_path)
        filename = val_path.name
        is_storage = str(get_mappings_storage_dir()) in str(val_path)
    else:
        effective_path, bundled_path, filename = resolve_value_mapping_file(system, program)
        val_path = effective_path
        is_storage = (effective_path == get_mappings_storage_dir() / filename)

    rows: List[Dict[str, str]] = []
    fieldnames: List[str] = []
    if val_path.is_file():
        with val_path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for r in reader:
                rows.append(dict(r))
    else:
        fieldnames = ["program", "target_header", "source_value", "dhis2_value", "transform"]

    is_placeholder = is_placeholder_rows(rows)

    return {
        "file_path": str(val_path),
        "filename": filename,
        "is_custom_saved": is_storage,
        "is_placeholder": is_placeholder,
        "fieldnames": fieldnames,
        "count": len(rows),
        "mappings": rows,
    }


def save_value_mappings(
    system: str,
    program: str,
    rows: List[Dict[str, str]],
    custom_filename: Optional[str] = None,
) -> Dict[str, Any]:
    effective_path, bundled_path, default_filename = resolve_value_mapping_file(system, program)
    filename = custom_filename or default_filename
    storage_dir = get_mappings_storage_dir()
    backups_dir = get_mappings_backups_dir()

    dest_path = storage_dir / filename

    # Copy current active file to backups before saving
    backup_source = dest_path if dest_path.is_file() else (bundled_path if bundled_path.is_file() else None)
    backup_path = None
    if backup_source and backup_source.is_file():
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = Path(filename).stem
        backup_path = backups_dir / f"{stem}.{timestamp}.csv"
        shutil.copy2(backup_source, backup_path)

    # Determine fieldnames
    fieldnames = []
    if rows:
        fieldnames = list(rows[0].keys())
    elif dest_path.is_file():
        with dest_path.open("r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            fieldnames = next(reader, [])
    elif bundled_path.is_file():
        with bundled_path.open("r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            fieldnames = next(reader, [])

    if not fieldnames:
        fieldnames = ["program", "target_header", "source_value", "dhis2_value", "transform"]

    with dest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "status": "success",
        "saved_count": len(rows),
        "file_path": str(dest_path),
        "backup_path": str(backup_path) if backup_path else None,
        "filename": filename,
    }


def list_value_mapping_backups(system: str, program: str) -> List[Dict[str, Any]]:
    _, _, filename = resolve_value_mapping_file(system, program)
    stem = Path(filename).stem
    backups_dir = get_mappings_backups_dir()
    backups = []
    if backups_dir.exists():
        for p in sorted(backups_dir.glob(f"{stem}.*.csv"), reverse=True):
            count = 0
            try:
                with p.open("r", encoding="utf-8-sig") as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    count = sum(1 for _ in reader)
            except Exception:
                pass
            backups.append({
                "filename": p.name,
                "path": str(p),
                "created_at": datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                "count": count,
                "size": p.stat().st_size,
            })
    return backups


def restore_value_mapping_backup(system: str, program: str, backup_filename: str) -> Dict[str, Any]:
    _, _, filename = resolve_value_mapping_file(system, program)
    backups_dir = get_mappings_backups_dir()
    storage_dir = get_mappings_storage_dir()

    backup_path = backups_dir / os.path.basename(backup_filename)
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup file not found: {backup_filename}")

    dest_path = storage_dir / filename
    if dest_path.is_file():
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        pre_restore_backup = backups_dir / f"{dest_path.stem}.pre_restore_{timestamp}.csv"
        shutil.copy2(dest_path, pre_restore_backup)

    shutil.copy2(backup_path, dest_path)
    return {
        "status": "success",
        "restored_from": backup_path.name,
        "restored_to": str(dest_path),
    }


def get_available_mapping_files() -> List[Dict[str, Any]]:
    res_dir = Path(interop_dir) / "Resources"
    files = []
    candidates = list(res_dir.rglob("*.csv"))
    storage_dir = get_mappings_storage_dir()
    if storage_dir.exists():
        candidates.extend(list(storage_dir.glob("*.csv")))

    seen_paths = set()
    for c in candidates:
        if "backups" in c.parts or "data" in c.parts:
            continue
        canon = str(c.resolve())
        if canon in seen_paths:
            continue
        seen_paths.add(canon)
        count = 0
        try:
            with c.open("r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                next(reader, None)
                count = sum(1 for _ in reader)
        except Exception:
            pass

        display_name = c.name
        if c.parent != res_dir and c.parent != storage_dir:
            display_name = f"{c.parent.name} / {c.name}"

        files.append({
            "name": display_name,
            "filename": c.name,
            "path": str(c),
            "count": count,
            "is_placeholder": count <= 1,
        })
    return files

