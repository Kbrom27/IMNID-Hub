import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import pandas as pd

from backend.core.config import settings
from backend.core.database import get_server_connection
from backend.core.jobs.engine import JobContext
from backend.core.storage import resolve_output_dir

from backend.modules.data_management.data_cleaning import transform_file_to_one_row_per_tei
from backend.modules.data_management.data_dictionary import DataDictionaryExportPage
from backend.modules.data_management.data_export import DataExportPage
from backend.modules.data_management.data_export_analysis import DataExportPage as AnalysisExportPage
from backend.modules.data_management.dhis2_sync import (
    SyncMetadata,
    sync_data_offline_to_online,
    build_plain_language_report,
)
from backend.modules.data_management.import_dhis2 import (
    DHIS2Metadata,
    import_csv_to_dhis2,
    read_csv_safe,
)
from backend.modules.data_management.import_redcap import (
    PROGRAM_ID as REDCAP_PROGRAM_ID,
    transform_to_redcap,
    build_dhis2_rows_for_transform,
    upload_to_redcap,
    fetch_teis as fetch_redcap_teis,
    fetch_tei_events as fetch_redcap_tei_events,
    fetch_metadata as fetch_redcap_metadata,
)
from backend.modules.data_management.metadata_import import (
    DHIS2MetadataImporter,
    get_metadata_file_info,
)
from backend.modules.data_management.mother_neonate_linker import (
    Dhis2Client as LinkerClient,
    MotherNeonateLinker,
    PROGRAM_MOTHER,
    PROGRAM_NEONATE,
    MotherRecord,
    NeonateRecord,
    find_match,
)
from backend.modules.data_management.ncf_nid_sync import (
    DHIS2Client as NcfNidClient,
    sync_all as sync_all_ncf_nid,
    sync_tei as sync_tei_ncf_nid,
)

logger = logging.getLogger("imnid.data_management")


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


def get_redcap_credentials() -> Dict[str, str]:
    conn = get_server_connection("redcap")
    if conn:
        return {
            "base_url": conn.get("base_url") or settings.REDCAP_URL,
            "token": conn.get("secret") or settings.REDCAP_TOKEN or "",
        }
    return {
        "base_url": settings.REDCAP_URL,
        "token": settings.REDCAP_TOKEN or "",
    }


# ==============================================================================
# 1. Metadata Import
# ==============================================================================
def run_metadata_import_worker(
    ctx: JobContext,
    dhis2_base_url: str,
    api_version: str,
    username: str,
    password: str,
    json_file_path: str,
    import_mode: str = "COMMIT",
    import_strategy: str = "CREATE_AND_UPDATE",
    identifier: str = "UID",
    merge_mode: str = "MERGE",
    atomic_mode: bool = False,
    exec_mode: str = "Direct (Synchronous)",
):
    if not dhis2_base_url or not username or not password:
        raise ValueError("DHIS2 URL, username, and password are required.")
    if not json_file_path or not os.path.exists(json_file_path):
        raise ValueError(f"Metadata file does not exist: {json_file_path}")

    ctx.log(f"Starting Metadata Import for {json_file_path} (Mode: {import_mode}, Strategy: {import_strategy})")
    ctx.update_progress(10, 100, "Reading metadata package...")

    importer = DHIS2MetadataImporter(log_callback=lambda msg: ctx.log(msg))

    try:
        ctx.update_progress(30, 100, f"Sending metadata to DHIS2 ({import_mode})...")
        importer._run_import(
            dhis2_base_url=dhis2_base_url,
            api_version=api_version,
            username=username,
            password=password,
            json_file_path=json_file_path,
            import_mode=import_mode,
            import_strategy=import_strategy,
            identifier=identifier,
            merge_mode=merge_mode,
            exec_mode=exec_mode,
            atomic_mode=atomic_mode,
        )
        ctx.update_progress(100, 100, f"Metadata import ({import_mode}) completed successfully.")
        ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"Metadata import error: {str(e)}")
        ctx.status = "failed"


# ==============================================================================
# 2. DHIS2 Sync (Offline to Online)
# ==============================================================================
def run_dhis2_sync_worker(
    ctx: JobContext,
    source_url: str,
    source_user: str,
    source_pass: str,
    target_url: str,
    target_user: str,
    target_pass: str,
    org_unit_id: str,
    program_id: str = "",
    program_ids: Optional[List[str]] = None,
    start_date: str = "",
    end_date: str = "",
    dry_run: bool = True,
):
    if not source_url or not source_user or not source_pass:
        raise ValueError("DHIS2 source URL, username, and password are required.")
    if not target_url or not target_user or not target_pass:
        raise ValueError("DHIS2 target URL, username, and password are required.")

    selected_progs = []
    if program_ids and isinstance(program_ids, list):
        selected_progs = [p for p in program_ids if p]
    elif program_id:
        selected_progs = [program_id]

    is_specific = bool(org_unit_id and str(org_unit_id).strip().upper() not in ["ALL", ""])
    org_mode = "SPECIFIC" if is_specific else "ALL"
    selected_org_uid = org_unit_id if is_specific else None

    ctx.log(f"Starting DHIS2 Direct Sync (Dry Run: {dry_run}) from {source_url} to {target_url}")
    ctx.log(f"  • Programs: {selected_progs}")
    ctx.log(f"  • Facility Scope: {org_mode} (UID: {selected_org_uid or 'All'})")
    ctx.update_progress(5, 100, "Initializing sync...")

    def log_fn(msg, tag=None):
        ctx.log(f"[{tag}] {msg}" if tag else msg)

    def status_fn(msg):
        ctx.update_progress(message=msg)

    def progress_fn(current, total):
        ctx.update_progress(progress=current, total=total)

    def is_cancelled():
        return ctx.is_canceled()

    try:
        report = sync_data_offline_to_online(
            offline_config={"url": source_url, "username": source_user, "password": source_pass},
            online_config={"url": target_url, "username": target_user, "password": target_pass},
            selected_programs=selected_progs,
            org_mode=org_mode,
            selected_org_uid=selected_org_uid,
            start_date=start_date or None,
            end_date=end_date or None,
            log_callback=log_fn,
            status_callback=status_fn,
            dry_run=dry_run,
        )

        report_file = settings.exports_dir / f"dhis2_sync_report_{ctx.job_id}.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            if isinstance(report, dict):
                f.write(json.dumps(report, indent=2))
            else:
                f.write(str(report or "Sync finished with no report output."))

        ctx.artifacts["report_file"] = str(report_file.name)
        ctx.update_progress(100, 100, "DHIS2 Sync complete.")
        ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"DHIS2 Sync failed: {str(e)}")
        ctx.status = "failed"


# ==============================================================================
# 3. Data Export (Tracker Export for Syncing)
# ==============================================================================
def run_data_export_worker(
    ctx: JobContext,
    base_url: str,
    username: str,
    password: str,
    program_name: str,
    program_id: str,
    ou_mode: str,
    ou_ids: List[str],
    start: str,
    end: str,
    status_filter: str = "ALL",
    event_status_filter: str = "ALL",
    output_format: str = "csv",
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
):
    if not base_url or not username or not password:
        raise ValueError("DHIS2 URL, username, and password are required.")

    ctx.log(f"Starting Data Export for program '{program_name}' ({program_id})")
    def on_progress(completed, total, ou_name, total_teis):
        if total > 0:
            pct = 20 + int((completed / total) * 75)
            ctx.update_progress(
                progress=pct,
                total=100,
                message=f"[{completed}/{total}] {ou_name}: {total_teis} total TEIs"
            )

    exporter = DataExportPage(
        base_url=base_url,
        username=username,
        password=password,
        log_callback=lambda msg: ctx.log(msg),
        progress_callback=on_progress,
    )

    ext = "xlsx" if output_format.lower() == "xlsx" else "csv"
    if filename and filename.strip():
        out_filename = filename.strip()
        if not out_filename.lower().endswith(f".{ext}"):
            out_filename += f".{ext}"
    else:
        out_filename = f"dhis2_export_{program_id}_{ctx.job_id}.{ext}"

    dest_dir = resolve_output_dir(output_dir, settings.exports_dir)

    try:
        ctx.update_progress(20, 100, "Fetching tracker entities...")
        res = exporter.export(
            program_name=program_name,
            ou_mode=ou_mode,
            ou_ids=ou_ids,
            start=start or "",
            end=end or "",
            out_dir=str(dest_dir),
            filename=out_filename,
            status_filter=status_filter,
            event_status_filter=event_status_filter,
            program_id=program_id,
        )
        records = res.get("records", 0) if isinstance(res, dict) else 0
        if records == 0 or (isinstance(res, dict) and res.get("status") == "no_data"):
            ctx.update_progress(100, 100, "Export completed: 0 records found matching the specified filters.")
            ctx.status = "completed"
        else:
            ctx.artifacts["output_file"] = out_filename
            ctx.set_result_file(out_filename)
            ctx.update_progress(100, 100, f"Export complete ({records} records): {out_filename}")
            ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"Data export failed: {str(e)}")
        ctx.status = "failed"


# ==============================================================================
# 4. DHIS2 to REDCap Sync (Newborn Inpatient Data)
# ==============================================================================
def run_redcap_import_worker(
    ctx: JobContext,
    dhis2_url: str,
    dhis2_user: str,
    dhis2_pass: str,
    redcap_url: str,
    redcap_token: str,
    template_path: str,
    org_unit: str,
    start_date: str = "",
    end_date: str = "",
    dry_run: bool = True,
):
    if not dhis2_url or not dhis2_user or not dhis2_pass:
        raise ValueError("DHIS2 URL, username, and password are required.")
    if not redcap_url or not redcap_token:
        raise ValueError("REDCap URL and API token are required.")
    if not org_unit:
        raise ValueError("Organisation unit (facility) is required.")

    mode_label = "Dry Run (Preview Only)" if dry_run else "Commit (Upload to REDCap)"
    ctx.log("=================================================================")
    ctx.log(f"Starting DHIS2 to REDCap Sync ({mode_label})")
    ctx.log(f" • Source DHIS2: {dhis2_url}")
    ctx.log(f" • Destination REDCap: {redcap_url}")
    ctx.log(f" • Org Unit (Facility): {org_unit}")
    if start_date or end_date:
        ctx.log(f" • Date Range: {start_date or 'Any'} to {end_date or 'Any'}")
    if template_path:
        ctx.log(f" • Template CSV: {os.path.basename(template_path)}")
    else:
        ctx.log(" • Template CSV: None (headers will be automatically inferred)")
    ctx.log("=================================================================")
    ctx.update_progress(10, 100, "Connecting to DHIS2 and fetching metadata...")

    try:
        from .import_redcap import run_pipeline
        result = run_pipeline(
            dhis_url=dhis2_url,
            dhis_user=dhis2_user,
            dhis_pass=dhis2_pass,
            redcap_url=redcap_url,
            redcap_token=redcap_token,
            org_unit=org_unit,
            template_path=template_path,
            start_date=start_date,
            end_date=end_date,
            log=lambda msg: ctx.log(msg),
            dry_run=dry_run,
        )

        df = result.get("transformed_df")
        record_count = result.get("records", len(df) if df is not None else 0)

        if df is not None and not df.empty:
            out_filename = f"redcap_preview_{ctx.job_id}.csv"
            out_path = settings.exports_dir / out_filename
            df.to_csv(out_path, index=False)
            ctx.set_result_file(str(out_path))

        ctx.meta["redcap_summary"] = {
            "records": record_count,
            "status": result.get("status"),
            "message": result.get("message"),
        }

        ctx.log("=================================================================")
        if dry_run:
            ctx.log("DHIS2 to REDCap Transform Preview Complete.")
            ctx.log(f"  • Transformed Records: {record_count}")
            ctx.update_progress(
                progress=100,
                total=record_count,
                success_count=record_count,
                fail_count=0,
                message=f"Dry-run preview complete: {record_count} records transformed.",
            )
        else:
            ctx.log("DHIS2 to REDCap Synchronization Complete.")
            ctx.log(f"  • Records Uploaded to REDCap: {record_count}")
            ctx.update_progress(
                progress=100,
                total=record_count,
                success_count=record_count,
                fail_count=0,
                message=f"Sync complete: {record_count} records uploaded to REDCap.",
            )
        ctx.log("=================================================================")
        ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"DHIS2 to REDCap sync failed: {str(e)}")
        ctx.status = "failed"


# ==============================================================================
# 5. DHIS2 Tracker Data Import
# ==============================================================================
def run_csv_import_worker(
    ctx: JobContext,
    dhis2_url: str,
    username: str,
    password: str,
    csv_path: str,
    dry_run: bool = True,
):
    if not dhis2_url or not username or not password:
        raise ValueError("DHIS2 URL, username, and password are required.")
    if not csv_path or not os.path.exists(csv_path):
        raise ValueError(f"CSV file does not exist: {csv_path}")

    mode_label = "Dry Run (Validation Only)" if dry_run else "Commit (Live Import)"
    filename = os.path.basename(csv_path)
    ctx.log("=================================================================")
    ctx.log(f"Starting DHIS2 Tracker Data Import ({mode_label})")
    ctx.log(f" • Target DHIS2: {dhis2_url}")
    ctx.log(f" • File: {filename}")
    ctx.log("=================================================================")
    ctx.update_progress(5, 100, "Reading CSV and validating encoding...")

    class JobContextHandler(logging.Handler):
        def emit(self, record):
            try:
                ctx.log(record.getMessage())
            except Exception:
                pass

    import_logger = logging.getLogger("modules.data_management.import_dhis2")
    handler = JobContextHandler()
    import_logger.addHandler(handler)
    import_logger.setLevel(logging.INFO)

    def on_progress(current, total, tei_id, successes=0, failures=0):
        pct = 25 + int((current / max(1, total)) * 70)
        ctx.update_progress(
            progress=pct,
            total=total,
            success_count=successes,
            fail_count=failures,
            message=f"Uploading TEI [{current}/{total}]: {tei_id}",
        )

    try:
        ctx.update_progress(15, 100, "Connecting to DHIS2 and fetching metadata...")
        res = import_csv_to_dhis2(
            base_api=dhis2_url,
            username=username,
            password=password,
            csv_path=csv_path,
            verbose=True,
            log_callback=lambda m: ctx.log(m),
            progress_callback=on_progress,
            dry_run=dry_run,
        )

        ctx.meta["import_summary"] = res
        ctx.log("=================================================================")
        if dry_run:
            ctx.log("DHIS2 Tracker Data Import Validation Complete.")
            ctx.log(f"  • Total Rows: {res.get('total_rows', 0)}")
            ctx.log(f"  • Valid TEIs: {res.get('total_teis', 0)}")
            ctx.log(f"  • Total Enrollments: {res.get('total_enrollments', 0)}")
            ctx.log(f"  • Total Events: {res.get('total_events', 0)}")
            ctx.log(f"  • Skipped Rows: {len(res.get('skipped_rows', []))}")
            ctx.update_progress(
                progress=100,
                total=res.get('total_teis', 0),
                success_count=res.get('total_teis', 0),
                fail_count=len(res.get('skipped_rows', [])),
                message=f"Dry-run validation complete: {res.get('total_teis', 0)} TEIs ready.",
            )
        else:
            ctx.log("DHIS2 Tracker Data Import Complete.")
            ctx.log(f"  • Total Rows: {res.get('total_rows', 0)}")
            ctx.log(f"  • Successfully Imported TEIs: {res.get('successes', 0)}")
            ctx.log(f"  • Failures: {res.get('failures', 0)}")
            if res.get('skipped_rows'):
                ctx.log(f"  • Skipped Rows: {len(res['skipped_rows'])}")
            if res.get('failed_teis'):
                ctx.log(f"  • Failed TEIs: {len(res['failed_teis'])}")
            ctx.update_progress(
                progress=100,
                total=res.get('total_teis', 0),
                success_count=res.get('successes', 0),
                fail_count=res.get('failures', 0),
                message=f"Import complete: {res.get('successes', 0)} succeeded, {res.get('failures', 0)} failed.",
            )
        ctx.log("=================================================================")
        ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"DHIS2 Tracker Data Import failed: {str(e)}")
        ctx.status = "failed"
    finally:
        import_logger.removeHandler(handler)


# ==============================================================================
# 6. Analytical Data Export
# ==============================================================================
def run_analysis_export_worker(
    ctx: JobContext,
    base_url: str,
    username: str,
    password: str,
    program_name: str,
    program_id: str,
    ou_mode: str,
    ou_ids: List[str],
    start: str,
    end: str,
    status_filter: str = "ALL",
    event_status_filter: str = "ALL",
    output_format: str = "csv",
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
):
    if not base_url or not username or not password:
        raise ValueError("DHIS2 URL, username, and password are required.")

    ctx.log(f"Starting Analytical Export for '{program_name}' ({program_id})")
    def on_progress(completed, total, ou_name, total_teis):
        if total > 0:
            pct = 20 + int((completed / total) * 75)
            ctx.update_progress(
                progress=pct,
                total=100,
                message=f"[{completed}/{total}] {ou_name}: {total_teis} total TEIs"
            )

    exporter = AnalysisExportPage(
        base_url=base_url,
        username=username,
        password=password,
        log_callback=lambda msg: ctx.log(msg),
        progress_callback=on_progress,
    )

    ext = "xlsx" if output_format.lower() == "xlsx" else "csv"
    if filename and filename.strip():
        out_filename = filename.strip()
        if not out_filename.lower().endswith(f".{ext}"):
            out_filename += f".{ext}"
    else:
        out_filename = f"analysis_export_{program_id}_{ctx.job_id}.{ext}"

    dest_dir = resolve_output_dir(output_dir, settings.exports_dir)

    try:
        ctx.update_progress(20, 100, "Extracting and unfolding stages...")
        res = exporter.export(
            program_name=program_name,
            ou_mode=ou_mode,
            ou_ids=ou_ids,
            start=start or "",
            end=end or "",
            out_dir=str(dest_dir),
            filename=out_filename,
            status_filter=status_filter,
            event_status_filter=event_status_filter,
            program_id=program_id,
        )
        records = res.get("records", 0) if isinstance(res, dict) else 0
        if records == 0 or (isinstance(res, dict) and res.get("status") == "no_data"):
            ctx.update_progress(100, 100, "Export completed: 0 records found matching the specified filters.")
            ctx.status = "completed"
        else:
            ctx.artifacts["output_file"] = out_filename
            ctx.set_result_file(out_filename)
            ctx.update_progress(100, 100, f"Analysis export complete ({records} records): {out_filename}")
            ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"Analysis export failed: {str(e)}")
        ctx.status = "failed"


# ==============================================================================
# 7. Data Transformation (One Row per TEI)
# ==============================================================================
def run_data_cleaning_worker(
    ctx: JobContext,
    input_csv: str,
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
):
    in_name = Path(input_csv).name
    ctx.log("=================================================================")
    ctx.log("Starting Data Transformation (One Row per TEI)")
    ctx.log(f" • Input File: {in_name}")

    ext = "csv"
    if filename and filename.strip():
        out_filename = filename.strip()
        if not out_filename.lower().endswith(f".{ext}"):
            out_filename += f".{ext}"
    else:
        stem = Path(in_name).stem
        out_filename = f"transformed_{stem}_{ctx.job_id}.{ext}"

    dest_dir = resolve_output_dir(output_dir, settings.exports_dir)
    output_csv = str(dest_dir / out_filename)

    ctx.log(f" • Output File: {out_filename}")
    ctx.log("=================================================================")
    ctx.update_progress(progress=15, total=100, message="Reading CSV extract and standardizing columns...")

    try:
        import pandas as pd
        in_df = pd.read_csv(input_csv, dtype=str, keep_default_na=False, na_values=[])
        in_rows, in_cols = len(in_df), len(in_df.columns)
        ctx.log(f"Loaded input dataset: {in_rows} rows, {in_cols} columns")

        ctx.update_progress(progress=40, total=100, message="Detecting TEI identifiers and unfolding repeated stages...")
        transform_file_to_one_row_per_tei(input_csv, output_csv)

        out_df = pd.read_csv(output_csv, dtype=str, keep_default_na=False, na_values=[])
        out_rows, out_cols = len(out_df), len(out_df.columns)

        ctx.set_result_file(output_csv)
        ctx.log("=================================================================")
        ctx.log("Data Transformation Complete:")
        ctx.log(f"  • Input Events/Rows: {in_rows}")
        ctx.log(f"  • Transformed Unique TEIs: {out_rows}")
        ctx.log(f"  • Total Wide Columns: {out_cols}")
        ctx.log(f"  • Generated File: {out_filename}")
        ctx.log("=================================================================")

        ctx.update_progress(
            progress=100,
            total=out_rows,
            success_count=out_rows,
            fail_count=0,
            message=f"Transformation complete: {out_rows} unique TEIs generated ({out_cols} columns).",
        )
        ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"Data transformation failed: {str(e)}")
        ctx.status = "failed"


# ==============================================================================
# 8. Data Dictionary Export
# ==============================================================================
def run_data_dictionary_worker(
    ctx: JobContext,
    dhis2_url: str,
    username: str,
    password: str,
    program_name: str,
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
):
    if not dhis2_url or not username or not password:
        raise ValueError("DHIS2 URL, username, and password are required.")
    if not program_name:
        raise ValueError("Program name is required.")

    ctx.log(f"Starting Data Dictionary Export for program '{program_name}'")
    ctx.update_progress(15, 100, "Connecting to DHIS2...")

    if filename and filename.strip():
        out_filename = filename.strip()
        if not out_filename.lower().endswith(".xlsx"):
            out_filename += ".xlsx"
    else:
        out_filename = f"data_dictionary_{program_name.replace(' ', '_')}_{ctx.job_id}.xlsx"

    dest_dir = resolve_output_dir(output_dir, settings.exports_dir)

    exporter = DataDictionaryExportPage(
        url=dhis2_url,
        username=username,
        password=password,
        program_name=program_name,
        filename=out_filename,
        directory=str(dest_dir),
        log_callback=lambda msg: ctx.log(msg),
    )

    try:
        ctx.update_progress(40, 100, "Extracting data elements and option sets...")
        res = exporter.export_data()
        ctx.artifacts["output_file"] = out_filename
        ctx.set_result_file(out_filename)
        ctx.update_progress(100, 100, f"Data dictionary saved: {out_filename}")
        ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"Data dictionary export failed: {str(e)}")
        ctx.status = "failed"


# ==============================================================================
# 9. NCF to NID Sync
# ==============================================================================
def run_ncf_nid_sync_worker(
    ctx: JobContext,
    dhis2_url: str,
    username: str,
    password: str,
    org_unit_id: Optional[str] = None,
    tei_uid: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    dry_run: bool = True,
    verbose: bool = False,
):
    if not dhis2_url or not username or not password:
        raise ValueError("DHIS2 URL, username, and password are required.")

    ctx.log(f"Starting NCF -> NID Sync (Dry Run: {dry_run}, Verbose: {verbose})")
    ctx.update_progress(5, 100, "Connecting to DHIS2 API...")

    client = NcfNidClient(server=dhis2_url, username=username, password=password)

    # Route sync engine logs into job live logs
    class JobLogHandler(logging.Handler):
        def emit(self, record):
            try:
                msg = self.format(record)
                ctx.log(msg)
            except Exception:
                pass

    log_handler = JobLogHandler()
    log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    sync_logger = logging.getLogger("backend.modules.data_management.ncf_nid_sync")
    old_level = sync_logger.level
    sync_logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    sync_logger.addHandler(log_handler)

    def on_progress(pct: int, msg: str, counters: dict):
        total_cnt = counters.get("updated", 0) + counters.get("created", 0) + counters.get("skipped", 0) + counters.get("errors", 0)
        success_cnt = counters.get("updated", 0) + counters.get("created", 0)
        fail_cnt = counters.get("errors", 0)
        ctx.update_progress(
            progress=pct,
            total=total_cnt,
            message=msg,
            success_count=success_cnt,
            fail_count=fail_cnt,
        )
        ctx.meta["counters"] = counters

    try:
        ctx.update_progress(10, 100, "Initializing NCF-NID sync...")
        res = sync_all_ncf_nid(
            client=client,
            ou=org_unit_id or None,
            tei_uid=tei_uid or None,
            start_date=start_date or None,
            end_date=end_date or None,
            dry_run=dry_run,
            progress_callback=on_progress,
            stop_check=lambda: ctx.is_canceled(),
        )

        final_counters = {
            "updated": res.get("updated", 0),
            "created": res.get("created", 0),
            "skipped": res.get("skipped", 0),
            "errors": res.get("errors", 0),
        }
        ctx.meta["counters"] = final_counters

        report_file = settings.exports_dir / f"ncf_nid_sync_{ctx.job_id}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump({
                "job_id": ctx.job_id,
                "completed_at": datetime.now().isoformat(),
                "dry_run": dry_run,
                "org_unit_id": org_unit_id,
                "tei_uid": tei_uid,
                "start_date": start_date,
                "end_date": end_date,
                "result": res,
            }, f, indent=2, default=str)

        ctx.set_result_file(str(report_file))
        total_items = res.get("total", final_counters["updated"] + final_counters["created"] + final_counters["skipped"] + final_counters["errors"])
        ctx.update_progress(
            progress=100,
            total=total_items,
            success_count=final_counters["updated"] + final_counters["created"],
            fail_count=final_counters["errors"],
            message=f"NCF-NID sync finished. Updated: {final_counters['updated']}, Created: {final_counters['created']}, Skipped: {final_counters['skipped']}, Errors: {final_counters['errors']}",
        )
        ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"NCF-NID sync failed: {str(e)}")
        ctx.status = "failed"
    finally:
        sync_logger.removeHandler(log_handler)
        sync_logger.setLevel(old_level)



# ==============================================================================
# 10. Mother-Neonate Linker
# ==============================================================================
def run_mother_neonate_linker_worker(
    ctx: JobContext,
    dhis2_url: str,
    username: str,
    password: str,
    org_unit_id: str,
    org_unit_name: str,
    rel_type_id: str,
    start_date: str = "",
    end_date: str = "",
    threshold: float = 0.85,
    dry_run: bool = True,
):
    if not dhis2_url or not username or not password:
        raise ValueError("DHIS2 URL, username, and password are required.")
    if not org_unit_id:
        raise ValueError("Organisation unit is required.")

    ctx.log(f"Starting Mother-Neonate Linker at {org_unit_name} (Dry run: {dry_run}, Threshold: {threshold})")
    ctx.update_progress(progress=5, total=100, message="Connecting to DHIS2...")

    client = LinkerClient(base_url=dhis2_url, username=username, password=password)
    linker = MotherNeonateLinker(client=client, log_callback=lambda msg: ctx.log(msg))

    try:
        ctx.update_progress(progress=15, total=100, message=f"Fetching TEIs and matching records at {org_unit_name}...")
        res = linker._run_worker(
            ou_id=org_unit_id,
            ou_display=org_unit_name,
            rel_type_id=rel_type_id,
            start_date=start_date or None,
            end_date=end_date or None,
            threshold=threshold,
            dry_run=dry_run,
        )

        # Save summary report JSON so user can download/inspect
        try:
            export_file = settings.exports_dir / f"mother_neonate_link_{ctx.job_id}.json"
            with open(export_file, "w", encoding="utf-8") as f:
                json.dump({
                    "job_id": ctx.job_id,
                    "org_unit_id": org_unit_id,
                    "org_unit_name": org_unit_name,
                    "rel_type_id": rel_type_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "threshold": threshold,
                    "dry_run": dry_run,
                    "summary": res.get("summary", ""),
                    "metrics": res,
                }, f, indent=2)
            ctx.set_result_file(export_file)
        except Exception as fe:
            ctx.log(f"Warning: could not write summary file: {fe}", level="WARNING")

        if "counters" not in ctx.meta:
            ctx.meta["counters"] = {}
        ctx.meta["counters"].update(res)

        successes = res.get("linked", 0) + res.get("already_linked", 0)
        failures = res.get("failed", 0)
        total_proc = res.get("total", 0)

        ctx.update_progress(
            progress=100,
            total=total_proc,
            message=f"Linking completed: {res.get('linked', 0)} newly linked, {res.get('already_linked', 0)} already linked, {failures} failed, {res.get('unmatched', 0)} unmatched.",
            success_count=successes,
            fail_count=failures,
        )
        ctx.status = "completed"
    except Exception as e:
        ctx.add_error(f"Mother-Neonate linking failed: {str(e)}")
        ctx.status = "failed"

