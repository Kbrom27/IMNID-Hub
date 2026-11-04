import csv
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from backend.core.config import settings
from backend.core.database import get_server_connection
from backend.core.jobs.engine import JobContext
from backend.modules.smartcare.migrator_core import SmartcareOpenmrsMigrator

logger = logging.getLogger("imnid.smartcare")

def get_migrator(base_url: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None) -> SmartcareOpenmrsMigrator:
    # If not provided, fetch from database server connections
    if not base_url or not username or not password:
        conn = get_server_connection("openmrs")
        if conn:
            base_url = base_url or conn.get("base_url")
            username = username or conn.get("username")
            password = password or conn.get("secret")

    base_url = base_url or settings.OPENMRS_URL
    username = username or settings.OPENMRS_USERNAME
    password = password or settings.OPENMRS_PASSWORD

    return SmartcareOpenmrsMigrator(base_url=base_url, username=username, password=password)

def test_openmrs_connection(base_url: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    migrator = get_migrator(base_url, username, password)
    return migrator.test_connection()

def validate_smartcare_csv(csv_filepath: str, limit: Optional[int] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    migrator = get_migrator()
    return migrator.dry_run(csv_filepath, limit=limit, config=config)

def run_migration_worker(
    ctx: JobContext,
    csv_filepath: str,
    limit: Optional[int] = None,
    config: Optional[Dict[str, Any]] = None,
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
):
    migrator = get_migrator(base_url, username, password)
    ctx.log(f"Starting SmartCare migration worker on file: {csv_filepath}")
    
    # Count total rows
    try:
        with open(csv_filepath, "r", encoding="utf-8", errors="ignore") as f:
            total_lines = sum(1 for _ in f) - 1
            total = min(total_lines, limit) if limit else total_lines
            total = max(1, total)
    except Exception as e:
        ctx.add_error(f"Failed to read CSV file: {str(e)}")
        ctx.status = "failed"
        return

    ctx.update_progress(progress=0, total=total, message=f"Starting migration of {total} records...")

    error_report_file = settings.exports_dir / f"smartcare_errors_{ctx.job_id}.csv"
    created_count = 0
    updated_count = 0
    rejected_count = 0
    fail_count = 0
    errors_list = []

    with open(csv_filepath, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            if ctx.is_canceled():
                ctx.log(f"Migration canceled by operator at row {i}")
                break

            transformed = migrator.transform_row(row, config)
            payload = transformed["payload"]
            meta = transformed["meta"]
            patient_name = meta["full_name"]
            mrn = meta["formatted_mrn"]

            # 1. Check if patient with this MRN already exists in OpenMRS
            existing_patient = migrator.find_patient_by_mrn(mrn)
            if existing_patient:
                existing_name = migrator.extract_patient_name(existing_patient)
                if migrator.is_same_patient_name(existing_name, patient_name):
                    # Same patient name -> Update existing patient
                    res = migrator.update_patient(existing_patient, payload)
                    if res.get("success"):
                        updated_count += 1
                        ctx.log(f"[UPDATED] Row {i}: {patient_name} (MRN: {mrn}) matched existing patient '{existing_name}'. Demographics updated.")
                    else:
                        fail_count += 1
                        err_msg = f"Row {i} ({mrn}): Update failed: {res.get('error')}"
                        ctx.add_error(err_msg)
                        errors_list.append({
                            "row": i,
                            "patient_id": meta["raw_patient_id"],
                            "mrn": mrn,
                            "name": patient_name,
                            "status": "FAILED_UPDATE",
                            "error": res.get("error")
                        })
                else:
                    # Different patient name -> Reject record, do NOT overwrite, import other records
                    rejected_count += 1
                    reject_msg = f"[REJECTED] Row {i}: MRN '{mrn}' already registered to '{existing_name}'. Uploaded record for '{patient_name}' differs. Skipped."
                    ctx.log(reject_msg, level="WARN")
                    with ctx._lock:
                        ctx.errors.append(reject_msg)
                    errors_list.append({
                        "row": i,
                        "patient_id": meta["raw_patient_id"],
                        "mrn": mrn,
                        "name": patient_name,
                        "status": "REJECTED_DIFFERENT_NAME",
                        "error": f"MRN already assigned to '{existing_name}' in OpenMRS"
                    })
            else:
                # Does not exist -> Create new patient in OpenMRS
                res = migrator.import_patient(payload)
                if res.get("success"):
                    created_count += 1
                    ctx.log(f"[CREATED] Row {i}: {patient_name} (MRN: {mrn}) imported successfully.")
                else:
                    fail_count += 1
                    err_msg = f"Row {i} ({mrn}): {res.get('error')}"
                    ctx.add_error(err_msg)
                    errors_list.append({
                        "row": i,
                        "patient_id": meta["raw_patient_id"],
                        "mrn": mrn,
                        "name": patient_name,
                        "status": "FAILED_CREATE",
                        "error": res.get("error")
                    })

            pct = int((i / total) * 100)
            ctx.update_progress(
                progress=pct,
                total=total,
                message=f"Processing row {i}/{total} - {patient_name} (Created: {created_count}, Updated: {updated_count}, Rejected: {rejected_count})",
                success_count=created_count + updated_count,
                created_count=created_count,
                updated_count=updated_count,
                rejected_count=rejected_count,
                fail_count=fail_count
            )

            if limit and i >= limit:
                break

    # Write error report if any rejections or failures occurred
    if errors_list:
        try:
            with open(error_report_file, "w", newline="", encoding="utf-8") as ef:
                writer = csv.DictWriter(ef, fieldnames=["row", "patient_id", "mrn", "name", "status", "error"])
                writer.writeheader()
                writer.writerows(errors_list)
            ctx.set_result_file(str(error_report_file))
            ctx.log(f"Saved rejected/error audit report to {error_report_file.name}")
        except Exception as ex:
            ctx.log(f"Could not write error file: {ex}", level="WARN")

    ctx.log(f"Migration completed. Created: {created_count}, Updated: {updated_count}, Rejected: {rejected_count}, Failed: {fail_count}, Total Processed: {min(i, total)}")

