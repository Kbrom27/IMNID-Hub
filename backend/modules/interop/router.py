import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.routers.auth import get_current_user
from backend.core.jobs.engine import job_engine
from backend.modules.interop.service import (
    get_dhis2_credentials,
    get_emr_credentials,
    get_sync_status,
    get_value_mappings,
    save_value_mappings,
    list_value_mapping_backups,
    restore_value_mapping_backup,
    get_available_mapping_files,
    get_visit_types,
    run_bahmni_export_worker,
    run_bahmni_transform_worker,
    run_bahmni_import_worker,
    run_bahmni_pipeline_worker,
    run_o3_export_worker,
    run_o3_transform_worker,
    run_o3_import_worker,
    run_o3_pipeline_worker,
    run_resume_worker,
)
from backend.modules.interop.config import FACILITIES, FACILITY_CODES

router = APIRouter(prefix="/api/v1/interop", tags=["EMR-DHIS2 Interoperability"])


# ==============================================================================
# Request Models
# ==============================================================================
class ExportRequest(BaseModel):
    emr_base_url: Optional[str] = None
    emr_username: Optional[str] = None
    emr_password: Optional[str] = None
    facility_name: str
    facility_code: Optional[str] = None
    visit_type_name: str
    start_date: str
    end_date: str
    output_dir: Optional[str] = None
    filename: Optional[str] = None


class TransformRequest(BaseModel):
    input_csv_path: Optional[str] = None
    input_csv: Optional[str] = None
    mapping_path: Optional[str] = None
    mapping_file: Optional[str] = None
    dict_path: Optional[str] = None
    dictionary_file: Optional[str] = None
    value_mapping_path: Optional[str] = None
    value_mapping_file: Optional[str] = None
    custom_mapping: Optional[str] = None
    custom_dict: Optional[str] = None
    custom_value: Optional[str] = None
    output_dir: Optional[str] = None
    filename: Optional[str] = None


class ImportRequest(BaseModel):
    dhis2_target: Optional[str] = "online"  # "online" or "offline"
    target: Optional[str] = None
    dhis2_url: Optional[str] = None
    dhis2_username: Optional[str] = None
    dhis2_password: Optional[str] = None
    input_csv_path: Optional[str] = None
    input_csv: Optional[str] = None
    dry_run: bool = False


class SyncPipelineRequest(BaseModel):
    emr_base_url: Optional[str] = None
    emr_username: Optional[str] = None
    emr_password: Optional[str] = None
    facility_name: str
    facility_code: Optional[str] = None
    visit_type_name: str
    start_date: str
    end_date: str
    target: Optional[str] = None
    dhis2_target: Optional[str] = "online"  # "online" or "offline"
    dhis2_url: Optional[str] = None
    dhis2_username: Optional[str] = None
    dhis2_password: Optional[str] = None
    dry_run: bool = False
    output_dir: Optional[str] = None
    export_filename: Optional[str] = None
    transform_filename: Optional[str] = None
    mapping_path: Optional[str] = None
    dict_path: Optional[str] = None
    value_mapping_path: Optional[str] = None



class ResumeRequest(BaseModel):
    dhis2_url: Optional[str] = None
    dhis2_username: Optional[str] = None
    dhis2_password: Optional[str] = None


class ValueMappingUpdateRequest(BaseModel):
    system: str = "bahmni"
    program: str = "maternal"
    mappings: List[Dict[str, str]]
    custom_filename: Optional[str] = None


class RestoreBackupRequest(BaseModel):
    system: str = "bahmni"
    program: str = "maternal"
    backup_filename: str


# ==============================================================================
# Common & Metadata Endpoints
# ==============================================================================
@router.get("/facilities")
def list_facilities(current_user: Dict = Depends(get_current_user)):
    return {
        "facilities": [{"name": f[0], "code": f[1]} for f in FACILITIES]
    }


@router.get("/visit-types")
def fetch_visit_types(
    system: str = Query(default="bahmni", description="bahmni or o3"),
    url: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
    password: Optional[str] = Query(default=None),
    current_user: Dict = Depends(get_current_user),
):
    try:
        types = get_visit_types(system=system, url=url, username=username, password=password)
        return {"status": "success", "visit_types": types}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load visit types: {str(e)}")


@router.post("/upload")
async def upload_interop_file(
    file: UploadFile = File(...),
    current_user: Dict = Depends(get_current_user),
):
    upload_dir = settings.uploads_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / file.filename

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "status": "success",
        "filename": file.filename,
        "filepath": str(dest_path),
        "size": dest_path.stat().st_size,
    }


@router.get("/directories")
def list_export_directories(current_user: Dict = Depends(get_current_user)):
    std_dirs = [
        "/data/schemas",
        "/data/schemas/Maternal Inpatient Data",
        "/data/schemas/Neonatal Care Form",
        "/data/schemas/enhanced",
        "/data/exports",
        "/data/exports/form-concepts",
        "/data/exports/bahmni",
        "/data/exports/o3",
        "/data/exports/data-export",
        "/data/exports/analysis",
        "/data/exports/archive",
        "/data/uploads",
    ]
    for d in std_dirs:
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    discovered = []
    for base in [Path("/data/schemas"), Path("/data/exports")]:
        if base.exists():
            try:
                for item in sorted(base.iterdir()):
                    if item.is_dir() and not item.name.startswith("."):
                        discovered.append(str(item))
            except Exception:
                pass
    all_dirs = list(dict.fromkeys(std_dirs + discovered))
    return {"directories": all_dirs}


@router.get("/sync/status")
def sync_status(current_user: Dict = Depends(get_current_user)):
    return get_sync_status()


# ==============================================================================
# Bahmni Workflows: 1. Export, 2. Transform, 3. Import, 4. Sync
# ==============================================================================
@router.post("/bahmni/export")
def trigger_bahmni_export(req: ExportRequest, current_user: Dict = Depends(get_current_user)):
    emr_creds = get_emr_credentials("bahmni")
    resolved_emr_url = req.emr_base_url or emr_creds["base_url"]
    resolved_emr_user = req.emr_username or emr_creds["username"]
    resolved_emr_pass = req.emr_password or emr_creds["password"]

    if not resolved_emr_url or not resolved_emr_user:
        raise HTTPException(status_code=400, detail="OpenMRS / Bahmni URL and username are required.")

    fac_code = req.facility_code or FACILITY_CODES.get(req.facility_name, "")
    job_title = f"Bahmni Export: {req.facility_name} ({req.visit_type_name})"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_bahmni_export",
        worker_func=run_bahmni_export_worker,
        worker_args={
            "emr_base_url": resolved_emr_url,
            "emr_username": resolved_emr_user,
            "emr_password": resolved_emr_pass,
            "facility_name": req.facility_name,
            "facility_code": fac_code,
            "visit_type_name": req.visit_type_name,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "output_dir": req.output_dir,
            "filename": req.filename,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}


@router.post("/bahmni/transform")
def trigger_bahmni_transform(req: TransformRequest, current_user: Dict = Depends(get_current_user)):
    input_csv = req.input_csv_path or req.input_csv
    if not input_csv:
        raise HTTPException(status_code=400, detail="Input CSV file path is required.")

    job_title = "Bahmni Transform CSV"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_bahmni_transform",
        worker_func=run_bahmni_transform_worker,
        worker_args={
            "input_csv_path": input_csv,
            "mapping_path": req.mapping_path or req.mapping_file or req.custom_mapping,
            "dict_path": req.dict_path or req.dictionary_file or req.custom_dict,
            "value_mapping_path": req.value_mapping_path or req.value_mapping_file or req.custom_value,
            "output_dir": req.output_dir,
            "filename": req.filename,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}


@router.post("/bahmni/import")
def trigger_bahmni_import(req: ImportRequest, current_user: Dict = Depends(get_current_user)):
    input_csv = req.input_csv_path or req.input_csv
    if not input_csv:
        raise HTTPException(status_code=400, detail="Input CSV file path is required.")

    target_val = getattr(req, "target", None) or getattr(req, "dhis2_target", "online")
    target_key = "dhis2_offline" if target_val == "offline" else "dhis2_online"
    dhis2_creds = get_dhis2_credentials(target_key)
    resolved_dhis2_url = req.dhis2_url or dhis2_creds["base_url"]
    resolved_dhis2_user = req.dhis2_username or dhis2_creds["username"]
    resolved_dhis2_pass = req.dhis2_password or dhis2_creds["password"]

    job_title = f"{'[DRY RUN] ' if req.dry_run else ''}Bahmni Import to DHIS2 ({'Offline' if target_val == 'offline' else 'Online'})"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_bahmni_import",
        worker_func=run_bahmni_import_worker,
        worker_args={
            "dhis2_url": resolved_dhis2_url,
            "dhis2_username": resolved_dhis2_user,
            "dhis2_password": resolved_dhis2_pass,
            "input_csv_path": input_csv,
            "dry_run": req.dry_run,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}


@router.post("/bahmni/sync")
@router.post("/sync/bahmni")
def trigger_bahmni_sync(req: SyncPipelineRequest, current_user: Dict = Depends(get_current_user)):
    target_val = getattr(req, "target", None) or getattr(req, "dhis2_target", "online")
    target_key = "dhis2_offline" if target_val == "offline" else "dhis2_online"
    dhis2_creds = get_dhis2_credentials(target_key)
    emr_creds = get_emr_credentials("bahmni")

    resolved_emr_url = req.emr_base_url or emr_creds["base_url"]
    resolved_emr_user = req.emr_username or emr_creds["username"]
    resolved_emr_pass = req.emr_password or emr_creds["password"]

    resolved_dhis2_url = req.dhis2_url or dhis2_creds["base_url"]
    resolved_dhis2_user = req.dhis2_username or dhis2_creds["username"]
    resolved_dhis2_pass = req.dhis2_password or dhis2_creds["password"]

    if not resolved_emr_url or not resolved_emr_user:
        raise HTTPException(status_code=400, detail="OpenMRS / Bahmni URL and username are required.")
    if not resolved_dhis2_url or not resolved_dhis2_user:
        raise HTTPException(status_code=400, detail="DHIS2 URL and username are required.")

    fac_code = req.facility_code or FACILITY_CODES.get(req.facility_name, "")

    job_title = f"{'[DRY RUN] ' if req.dry_run else ''}Bahmni Sync: {req.facility_name} ({req.visit_type_name})"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_bahmni",
        worker_func=run_bahmni_pipeline_worker,
        worker_args={
            "emr_base_url": resolved_emr_url,
            "emr_username": resolved_emr_user,
            "emr_password": resolved_emr_pass,
            "facility_name": req.facility_name,
            "facility_code": fac_code,
            "visit_type_name": req.visit_type_name,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "dhis2_url": resolved_dhis2_url,
            "dhis2_username": resolved_dhis2_user,
            "dhis2_password": resolved_dhis2_pass,
            "dry_run": req.dry_run,
            "output_dir": req.output_dir,
            "export_filename": req.export_filename,
            "transform_filename": req.transform_filename,
            "mapping_path": req.mapping_path,
            "dict_path": req.dict_path,
            "value_mapping_path": req.value_mapping_path,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}



# ==============================================================================
# OpenMRS 3 Workflows: 1. Export, 2. Transform, 3. Import, 4. Sync
# ==============================================================================
@router.post("/o3/export")
def trigger_o3_export(req: ExportRequest, current_user: Dict = Depends(get_current_user)):
    emr_creds = get_emr_credentials("o3")
    resolved_emr_url = req.emr_base_url or emr_creds["base_url"]
    resolved_emr_user = req.emr_username or emr_creds["username"]
    resolved_emr_pass = req.emr_password or emr_creds["password"]

    if not resolved_emr_url or not resolved_emr_user:
        raise HTTPException(status_code=400, detail="OpenMRS 3 URL and username are required.")

    fac_code = req.facility_code or FACILITY_CODES.get(req.facility_name, "")
    job_title = f"OpenMRS 3 Export: {req.facility_name} ({req.visit_type_name})"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_o3_export",
        worker_func=run_o3_export_worker,
        worker_args={
            "emr_base_url": resolved_emr_url,
            "emr_username": resolved_emr_user,
            "emr_password": resolved_emr_pass,
            "facility_name": req.facility_name,
            "facility_code": fac_code,
            "visit_type_name": req.visit_type_name,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "output_dir": req.output_dir,
            "filename": req.filename,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}


@router.post("/o3/transform")
def trigger_o3_transform(req: TransformRequest, current_user: Dict = Depends(get_current_user)):
    input_csv = req.input_csv_path or req.input_csv
    if not input_csv:
        raise HTTPException(status_code=400, detail="Input CSV file path is required.")

    job_title = "OpenMRS 3 Transform Export"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_o3_transform",
        worker_func=run_o3_transform_worker,
        worker_args={
            "input_csv_path": input_csv,
            "output_dir": req.output_dir,
            "filename": req.filename,
            "custom_mapping": req.custom_mapping or req.mapping_file or req.mapping_path,
            "custom_dict": req.custom_dict or req.dictionary_file or req.dict_path,
            "custom_value": req.custom_value or req.value_mapping_file or req.value_mapping_path,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}


@router.get("/o3/verify-mappings")
def verify_o3_mappings(current_user: Dict = Depends(get_current_user)):
    import openpyxl
    from backend.modules.interop.o3app.config import RESOURCES_DIR, O3_METADATA_PATH

    o3_dir = RESOURCES_DIR / "O3"
    mat_path = o3_dir / "EMR-DHIS2 Tracker O3 Maternal Mapping.xlsx"
    neo_path = o3_dir / "EMR-DHIS2 Tracker O3 Neonatal Mapping.xlsx"
    val_path = o3_dir / "EMR-DHIS2 Tracker O3 Value Mappings.csv"

    missing = [p.name for p in (mat_path, neo_path, val_path) if not p.is_file()]
    if missing:
        raise HTTPException(status_code=404, detail=f"Missing O3 mapping file(s): {', '.join(missing)}")

    wb_mat = openpyxl.load_workbook(mat_path, read_only=True)
    mat_rows = max(0, sum(1 for _ in wb_mat.active.iter_rows(values_only=True)) - 1) if wb_mat.active else 0
    wb_mat.close()

    wb_neo = openpyxl.load_workbook(neo_path, read_only=True)
    neo_rows = max(0, sum(1 for _ in wb_neo.active.iter_rows(values_only=True)) - 1) if wb_neo.active else 0
    wb_neo.close()

    with val_path.open("r", encoding="utf-8", errors="ignore") as f:
        val_rows = max(0, sum(1 for _ in f) - 1)

    meta_ok = O3_METADATA_PATH.is_file()

    return {
        "status": "verified",
        "directory": str(o3_dir),
        "maternal_mapping": {"filename": mat_path.name, "rows": mat_rows},
        "neonatal_mapping": {"filename": neo_path.name, "rows": neo_rows},
        "value_mapping": {"filename": val_path.name, "rows": val_rows},
        "metadata_json": {"filename": O3_METADATA_PATH.name, "exists": meta_ok},
    }


@router.post("/o3/import")
def trigger_o3_import(req: ImportRequest, current_user: Dict = Depends(get_current_user)):
    input_csv = req.input_csv_path or req.input_csv
    if not input_csv:
        raise HTTPException(status_code=400, detail="Input CSV file path is required.")

    target_val = getattr(req, "target", None) or getattr(req, "dhis2_target", "online")
    target_key = "dhis2_offline" if target_val == "offline" else "dhis2_online"
    dhis2_creds = get_dhis2_credentials(target_key)
    resolved_dhis2_url = req.dhis2_url or dhis2_creds["base_url"]
    resolved_dhis2_user = req.dhis2_username or dhis2_creds["username"]
    resolved_dhis2_pass = req.dhis2_password or dhis2_creds["password"]

    job_title = f"{'[DRY RUN] ' if req.dry_run else ''}OpenMRS 3 Import to DHIS2 ({'Offline' if target_val == 'offline' else 'Online'})"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_o3_import",
        worker_func=run_o3_import_worker,
        worker_args={
            "dhis2_url": resolved_dhis2_url,
            "dhis2_username": resolved_dhis2_user,
            "dhis2_password": resolved_dhis2_pass,
            "input_csv_path": input_csv,
            "dry_run": req.dry_run,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}


@router.post("/o3/sync")
@router.post("/sync/o3")
def trigger_o3_sync(req: SyncPipelineRequest, current_user: Dict = Depends(get_current_user)):
    target_val = getattr(req, "target", None) or getattr(req, "dhis2_target", "online")
    target_key = "dhis2_offline" if target_val == "offline" else "dhis2_online"
    dhis2_creds = get_dhis2_credentials(target_key)
    emr_creds = get_emr_credentials("o3")

    resolved_emr_url = req.emr_base_url or emr_creds["base_url"]
    resolved_emr_user = req.emr_username or emr_creds["username"]
    resolved_emr_pass = req.emr_password or emr_creds["password"]

    resolved_dhis2_url = req.dhis2_url or dhis2_creds["base_url"]
    resolved_dhis2_user = req.dhis2_username or dhis2_creds["username"]
    resolved_dhis2_pass = req.dhis2_password or dhis2_creds["password"]

    if not resolved_emr_url or not resolved_emr_user:
        raise HTTPException(status_code=400, detail="OpenMRS 3 URL and username are required.")
    if not resolved_dhis2_url or not resolved_dhis2_user:
        raise HTTPException(status_code=400, detail="DHIS2 URL and username are required.")

    fac_code = req.facility_code or FACILITY_CODES.get(req.facility_name, "")

    job_title = f"{'[DRY RUN] ' if req.dry_run else ''}OpenMRS 3 Sync: {req.facility_name} ({req.visit_type_name})"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_o3",
        worker_func=run_o3_pipeline_worker,
        worker_args={
            "emr_base_url": resolved_emr_url,
            "emr_username": resolved_emr_user,
            "emr_password": resolved_emr_pass,
            "facility_name": req.facility_name,
            "facility_code": fac_code,
            "visit_type_name": req.visit_type_name,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "dhis2_url": resolved_dhis2_url,
            "dhis2_username": resolved_dhis2_user,
            "dhis2_password": resolved_dhis2_pass,
            "dry_run": req.dry_run,
            "output_dir": req.output_dir,
            "export_filename": req.export_filename,
            "transform_filename": req.transform_filename,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}



# ==============================================================================
# Resume & Mappings Endpoints
# ==============================================================================
@router.post("/sync/resume")
def trigger_resume_sync(req: ResumeRequest, current_user: Dict = Depends(get_current_user)):
    job_title = "Resume Interrupted Direct Sync"
    job_id = job_engine.submit_job(
        title=job_title,
        module="interop_resume",
        worker_func=run_resume_worker,
        worker_args={
            "dhis2_url": req.dhis2_url,
            "dhis2_username": req.dhis2_username,
            "dhis2_password": req.dhis2_password,
        },
        user_id=current_user.get("username", "system"),
    )
    return {"job_id": job_id, "title": job_title, "status": "submitted"}


@router.get("/mappings/values")
def get_values(
    system: str = Query(default="bahmni", description="bahmni or o3"),
    program: str = Query(default="maternal", description="maternal or neonatal"),
    custom_path: Optional[str] = Query(default=None),
    current_user: Dict = Depends(get_current_user),
):
    return get_value_mappings(system, program, custom_path=custom_path)


@router.put("/mappings/values")
def update_values(
    payload: ValueMappingUpdateRequest,
    current_user: Dict = Depends(get_current_user),
):
    return save_value_mappings(
        payload.system,
        payload.program,
        payload.mappings,
        payload.custom_filename,
    )


@router.get("/mappings/values/backups")
def get_backups(
    system: str = Query(default="bahmni"),
    program: str = Query(default="maternal"),
    current_user: Dict = Depends(get_current_user),
):
    return {"backups": list_value_mapping_backups(system, program)}


@router.post("/mappings/values/restore")
def restore_backup(
    payload: RestoreBackupRequest,
    current_user: Dict = Depends(get_current_user),
):
    try:
        return restore_value_mapping_backup(payload.system, payload.program, payload.backup_filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/mappings/values/files")
def list_available_files(current_user: Dict = Depends(get_current_user)):
    return {"files": get_available_mapping_files()}


@router.get("/download/{filename:path}")
async def download_artifact(
    filename: str,
    current_user: Dict = Depends(get_current_user),
):
    from backend.core.storage import resolve_export_file, build_file_response

    file_path = resolve_export_file(filename)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return build_file_response(file_path)

