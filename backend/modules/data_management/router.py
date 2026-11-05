import os
import shutil
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
import requests
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.jobs.engine import job_engine
from backend.routers.auth import get_current_user
from backend.modules.data_management.metadata_import import get_metadata_file_info
from backend.modules.data_management.service import (
    get_dhis2_credentials,
    get_redcap_credentials,
    run_metadata_import_worker,
    run_dhis2_sync_worker,
    run_data_export_worker,
    run_redcap_import_worker,
    run_csv_import_worker,
    run_analysis_export_worker,
    run_data_cleaning_worker,
    run_data_dictionary_worker,
    run_ncf_nid_sync_worker,
    run_mother_neonate_linker_worker,
)
from backend.modules.data_management.mother_neonate_linker import Dhis2Client as LinkerClient
from backend.core.connections import normalize_container_url

router = APIRouter(prefix="/api/data-management", tags=["data-management"])


# ==============================================================================
# File Upload Endpoint
# ==============================================================================
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    upload_dir = settings.uploads_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / file.filename

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = dest_path.stat().st_size
    logger.info(f"File uploaded successfully: {file.filename} ({file_size} bytes)")
    return {
        "status": "success",
        "filename": file.filename,
        "filepath": str(dest_path),
        "size": file_size,
    }


logger = logging.getLogger("imnid.data_management.router")

# ==============================================================================
# DHIS2 Metadata Discovery Endpoints (Programs & Org Units)
# ==============================================================================
@router.get("/dhis2/programs")
async def get_dhis2_programs(
    system: Optional[str] = "dhis2_offline",
    url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(system or "dhis2_offline")
    base_url = normalize_container_url(url or creds["base_url"]).rstrip("/")
    user = username or creds["username"]
    pw = password or creds["password"]

    programs_url = f"{base_url}/api/programs.json"
    auth = (user, pw) if user and pw else None
    try:
        res = requests.get(
            programs_url,
            auth=auth,
            params={"fields": "id,displayName,programType", "paging": "false"},
            timeout=10,
            headers={"Accept": "application/json"}
        )
        if res.status_code == 200:
            data = res.json()
            raw_progs = data.get("programs", [])
            programs = [
                {"id": p["id"], "name": p.get("displayName", p["id"]), "type": p.get("programType")}
                for p in raw_progs
            ]
            return {"ok": True, "programs": programs}
        else:
            return {"ok": False, "error": f"DHIS2 HTTP {res.status_code}", "programs": []}
    except Exception as e:
        logger.warning(f"Failed to fetch DHIS2 programs from {base_url}: {e}")
        fallback = [
            {"id": "pLk3Ht2XMKl", "name": "Maternal Inpatient Data", "type": "WITH_REGISTRATION"},
            {"id": "QYJKpoUeg9F", "name": "Neonatal Inpatient Data", "type": "WITH_REGISTRATION"},
            {"id": "aLoraiFNkng", "name": "Delivery Register", "type": "WITH_REGISTRATION"},
        ]
        return {"ok": False, "error": str(e), "programs": fallback}


@router.get("/dhis2/org-units")
async def get_dhis2_org_units(
    system: Optional[str] = "dhis2_offline",
    url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(system or "dhis2_offline")
    base_url = normalize_container_url(url or creds["base_url"]).rstrip("/")
    user = username or creds["username"]
    pw = password or creds["password"]

    ou_url = f"{base_url}/api/organisationUnits.json"
    auth = (user, pw) if user and pw else None
    try:
        res = requests.get(
            ou_url,
            auth=auth,
            params={"fields": "id,displayName,level,path", "paging": "false", "pageSize": 10000},
            timeout=15,
            headers={"Accept": "application/json"}
        )
        if res.status_code == 200:
            data = res.json()
            raw_ous = data.get("organisationUnits", [])
            ous = [
                {
                    "id": ou["id"],
                    "name": ou.get("displayName", ou["id"]),
                    "level": ou.get("level", 1),
                    "path": ou.get("path", ""),
                    "display": ("  " * max(0, ou.get("level", 1) - 1)) + ou.get("displayName", ou["id"]),
                }
                for ou in sorted(raw_ous, key=lambda x: x.get("path", ""))
            ]
            return {"ok": True, "org_units": ous}
        else:
            return {"ok": False, "error": f"DHIS2 HTTP {res.status_code}", "org_units": []}
    except Exception as e:
        logger.warning(f"Failed to fetch DHIS2 org units from {base_url}: {e}")
        fallback = [
            {"id": "OU_001", "name": "St. Paul's Hospital Millennium Medical College", "level": 4},
            {"id": "OU_002", "name": "Tikur Anbessa Specialized Hospital (TASH)", "level": 4},
            {"id": "OU_003", "name": "Gandhi Memorial Hospital", "level": 4},
            {"id": "OU_004", "name": "Zewditu Memorial Hospital", "level": 4},
            {"id": "OU_005", "name": "Yekatit 12 Hospital Medical College", "level": 4},
        ]
        return {"ok": False, "error": str(e), "org_units": fallback}


# ==============================================================================
# 1. Metadata Import & DHIS2 Connection Testing
# ==============================================================================
class TestDhis2ConnectionRequest(BaseModel):
    system: Optional[str] = "dhis2_online"
    url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/dhis2/test-connection")
async def test_dhis2_connection_endpoint(
    req: TestDhis2ConnectionRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(req.system or "dhis2_online")
    raw_url = req.url or creds["base_url"]
    base_url = normalize_container_url(raw_url).rstrip("/")
    if base_url.endswith("/api"):
        base_url = base_url[:-4]
    user = req.username or creds["username"]
    pw = req.password or creds["password"]

    test_endpoints = [
        "/api/system/info",
        "/api/me",
        "/dhis/api/system/info",
        "/dhis/api/me",
    ]

    last_err = None
    for endpoint in test_endpoints:
        test_url = f"{base_url}{endpoint}"
        try:
            start_t = time.time()
            resp = requests.get(test_url, auth=(user, pw), timeout=10, headers={"Accept": "application/json"})
            latency = int((time.time() - start_t) * 1000)
            if resp.status_code == 200:
                detected_api = "auto-detect"
                version_str = "Unknown"
                try:
                    data = resp.json()
                    version_str = data.get("version", "Unknown")
                    parts = version_str.split(".")
                    if len(parts) >= 2:
                        detected_api = parts[1] if parts[0] == "2" else parts[0]
                except Exception:
                    pass
                return {
                    "ok": True,
                    "message": f"Connection successful ({latency}ms)",
                    "version": version_str,
                    "api_version": detected_api,
                    "endpoint": test_url,
                }
            else:
                last_err = f"HTTP {resp.status_code} at {endpoint}"
        except Exception as e:
            last_err = str(e)

    return {"ok": False, "error": last_err or "Connection failed"}


class FileInfoRequest(BaseModel):
    filepath: str


@router.post("/metadata-import/file-info")
async def metadata_file_info(
    req: FileInfoRequest,
    current_user: dict = Depends(get_current_user),
):
    path = Path(req.filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Metadata file not found on server")
    try:
        info = get_metadata_file_info(str(path))
        return {"ok": True, "info": info}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read metadata file: {str(e)}")


class MetadataImportRequest(BaseModel):
    filepath: str
    target_instance: Optional[str] = "dhis2_online"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    api_version: str = "auto-detect"
    import_mode: str = "COMMIT"
    import_strategy: str = "CREATE_AND_UPDATE"
    identifier: str = "UID"
    merge_mode: str = "MERGE"
    atomic_mode: bool = False
    exec_mode: str = "Direct (Synchronous)"


@router.post("/metadata-import/dry-run")
async def metadata_import_dry_run(
    req: MetadataImportRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(req.target_instance or "dhis2_online")
    raw_url = req.dhis2_url or creds["base_url"]
    url = normalize_container_url(raw_url)
    user = req.username or creds["username"]
    pw = req.password or creds["password"]

    job = job_engine.submit_job(
        job_type="metadata_import_validate",
        description=f"Validate Metadata Import for {Path(req.filepath).name}",
        worker_fn=run_metadata_import_worker,
        dhis2_base_url=url,
        api_version=req.api_version,
        username=user,
        password=pw,
        json_file_path=req.filepath,
        import_mode="VALIDATE",
        import_strategy=req.import_strategy,
        identifier=req.identifier,
        merge_mode=req.merge_mode,
        atomic_mode=req.atomic_mode,
        exec_mode=req.exec_mode,
    )
    return {"status": "submitted", "job_id": job.job_id}


@router.post("/metadata-import/run")
async def metadata_import_run(
    req: MetadataImportRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(req.target_instance or "dhis2_online")
    raw_url = req.dhis2_url or creds["base_url"]
    url = normalize_container_url(raw_url)
    user = req.username or creds["username"]
    pw = req.password or creds["password"]

    import_mode = req.import_mode or "COMMIT"
    job_type = "metadata_import_validate" if import_mode == "VALIDATE" else "metadata_import_commit"
    desc_action = "Validate" if import_mode == "VALIDATE" else "Commit"

    job = job_engine.submit_job(
        job_type=job_type,
        description=f"{desc_action} Metadata Import for {Path(req.filepath).name}",
        worker_fn=run_metadata_import_worker,
        dhis2_base_url=url,
        api_version=req.api_version,
        username=user,
        password=pw,
        json_file_path=req.filepath,
        import_mode=import_mode,
        import_strategy=req.import_strategy,
        identifier=req.identifier,
        merge_mode=req.merge_mode,
        atomic_mode=req.atomic_mode,
        exec_mode=req.exec_mode,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 2. DHIS2 Sync (Offline to Online)
# ==============================================================================
class Dhis2SyncRequest(BaseModel):
    direction: Optional[str] = "offline_to_online"  # 'offline_to_online' or 'online_to_offline'
    source_url: Optional[str] = ""
    source_user: Optional[str] = ""
    source_pass: Optional[str] = ""
    target_url: Optional[str] = ""
    target_user: Optional[str] = ""
    target_pass: Optional[str] = ""
    org_unit_id: str
    program_id: Optional[str] = ""
    program_ids: Optional[List[str]] = None
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""


@router.post("/dhis2-sync/dry-run")
async def dhis2_sync_dry_run(
    req: Dhis2SyncRequest,
    current_user: dict = Depends(get_current_user),
):
    offline_creds = get_dhis2_credentials("dhis2_offline")
    online_creds = get_dhis2_credentials("dhis2_online")

    if req.direction == "online_to_offline":
        default_src = online_creds
        default_tgt = offline_creds
    else:
        default_src = offline_creds
        default_tgt = online_creds

    src_url = normalize_container_url(req.source_url or default_src["base_url"])
    src_user = req.source_user or default_src["username"]
    src_pass = req.source_pass or default_src["password"]

    tgt_url = normalize_container_url(req.target_url or default_tgt["base_url"])
    tgt_user = req.target_user or default_tgt["username"]
    tgt_pass = req.target_pass or default_tgt["password"]

    progs_desc = ", ".join(req.program_ids) if req.program_ids else (req.program_id or "All")
    job = job_engine.submit_job(
        job_type="dhis2_sync_dry_run",
        description=f"Preview DHIS2 Direct Sync ({req.direction}): {progs_desc} at {req.org_unit_id}",
        worker_fn=run_dhis2_sync_worker,
        source_url=src_url,
        source_user=src_user,
        source_pass=src_pass,
        target_url=tgt_url,
        target_user=tgt_user,
        target_pass=tgt_pass,
        org_unit_id=req.org_unit_id,
        program_id=req.program_id or "",
        program_ids=req.program_ids,
        start_date=req.start_date,
        end_date=req.end_date,
        dry_run=True,
    )
    return {"status": "submitted", "job_id": job.job_id}


@router.post("/dhis2-sync/run")
async def dhis2_sync_run(
    req: Dhis2SyncRequest,
    current_user: dict = Depends(get_current_user),
):
    offline_creds = get_dhis2_credentials("dhis2_offline")
    online_creds = get_dhis2_credentials("dhis2_online")

    if req.direction == "online_to_offline":
        default_src = online_creds
        default_tgt = offline_creds
    else:
        default_src = offline_creds
        default_tgt = online_creds

    src_url = normalize_container_url(req.source_url or default_src["base_url"])
    src_user = req.source_user or default_src["username"]
    src_pass = req.source_pass or default_src["password"]

    tgt_url = normalize_container_url(req.target_url or default_tgt["base_url"])
    tgt_user = req.target_user or default_tgt["username"]
    tgt_pass = req.target_pass or default_tgt["password"]

    progs_desc = ", ".join(req.program_ids) if req.program_ids else (req.program_id or "All")
    job = job_engine.submit_job(
        job_type="dhis2_sync_commit",
        description=f"Execute DHIS2 Direct Sync ({req.direction}): {progs_desc} at {req.org_unit_id}",
        worker_fn=run_dhis2_sync_worker,
        source_url=src_url,
        source_user=src_user,
        source_pass=src_pass,
        target_url=tgt_url,
        target_user=tgt_user,
        target_pass=tgt_pass,
        org_unit_id=req.org_unit_id,
        program_id=req.program_id or "",
        program_ids=req.program_ids,
        start_date=req.start_date,
        end_date=req.end_date,
        dry_run=False,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 3. Data Export (Tracker Export for Syncing)
# ==============================================================================
DEFAULT_PROGRAM_MAP = {
    "Maternal Inpatient Data": "aLoraiFNkng",
    "Neonatal care Form": "QYJKpoUeg9F",
    "Newborn Inpatient Data": "pLk3Ht2XMKl",
    "Delivery Register": "aLoraiFNkng",
    "FINC": "flBSKMXQloQ",
    "SLL Assist AI": "yxRNHSagJmU",
}


class DataExportRequest(BaseModel):
    dhis2_url: Optional[str] = None
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    source_instance: Optional[str] = "dhis2_offline"
    program_name: Optional[str] = "Newborn Inpatient Data"
    program_id: Optional[str] = None
    ou_mode: Optional[str] = None
    org_unit_mode: Optional[str] = None
    ou_ids: Optional[List[str]] = None
    org_unit_id: Optional[str] = None
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    status_filter: Optional[str] = None
    status: Optional[str] = None
    event_status_filter: Optional[str] = None
    event_status: Optional[str] = None
    output_format: Optional[str] = None
    format: Optional[str] = None
    output_dir: Optional[str] = None
    filename: Optional[str] = None


@router.post("/data-export/run")
async def data_export_run(
    req: DataExportRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(req.source_instance or "dhis2_offline")
    raw_url = req.dhis2_url or req.base_url or creds["base_url"]
    url = normalize_container_url(raw_url)
    user = req.username or creds["username"]
    pw = req.password or creds["password"]

    prog_name = req.program_name or "Newborn Inpatient Data"
    prog_id = req.program_id or DEFAULT_PROGRAM_MAP.get(prog_name) or "pLk3Ht2XMKl"
    ou_mode = req.ou_mode or req.org_unit_mode or "ALL"
    if req.ou_ids is not None:
        ou_ids = req.ou_ids
    elif req.org_unit_id:
        ou_ids = [req.org_unit_id]
    else:
        ou_ids = []
    status_filter = req.status_filter or req.status or "ALL"
    event_status_filter = req.event_status_filter or req.event_status or "ALL"
    output_format = req.output_format or req.format or "csv"

    job = job_engine.submit_job(
        job_type="tracker_data_export",
        description=f"Export Tracker Data: {prog_name}",
        worker_fn=run_data_export_worker,
        base_url=url,
        username=user,
        password=pw,
        program_name=prog_name,
        program_id=prog_id,
        ou_mode=ou_mode,
        ou_ids=ou_ids,
        start=req.start_date or "",
        end=req.end_date or "",
        status_filter=status_filter,
        event_status_filter=event_status_filter,
        output_format=output_format,
        output_dir=req.output_dir,
        filename=req.filename,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 4. DHIS2 to REDCap Sync (Newborn Inpatient Data)
# ==============================================================================
class RedcapImportRequest(BaseModel):
    source_instance: Optional[str] = "dhis2_online"  # "dhis2_offline" or "dhis2_online"
    dhis2_url: Optional[str] = None
    dhis2_user: Optional[str] = None
    dhis2_pass: Optional[str] = None
    redcap_url: Optional[str] = None
    redcap_token: Optional[str] = None
    template_path: Optional[str] = ""
    org_unit: str
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""


@router.post("/redcap-import/dry-run")
async def redcap_import_dry_run(
    req: RedcapImportRequest,
    current_user: dict = Depends(get_current_user),
):
    dhis_creds = get_dhis2_credentials(req.source_instance or "dhis2_online")
    d_url = normalize_container_url(req.dhis2_url or dhis_creds["base_url"])
    d_user = req.dhis2_user or dhis_creds["username"]
    d_pass = req.dhis2_pass or dhis_creds["password"]

    rcap_creds = get_redcap_credentials()
    rcap_url = normalize_container_url(req.redcap_url or rcap_creds["base_url"])
    rcap_token = req.redcap_token or rcap_creds["token"]

    if not rcap_token and not req.redcap_token:
        raise HTTPException(
            status_code=400,
            detail="REDCap API token is not configured. Please enter it or configure it in Settings > Vault."
        )

    job = job_engine.submit_job(
        job_type="redcap_sync_preview",
        description=f"Preview DHIS2 to REDCap Sync for OU: {req.org_unit}",
        worker_fn=run_redcap_import_worker,
        dhis2_url=d_url,
        dhis2_user=d_user,
        dhis2_pass=d_pass,
        redcap_url=rcap_url,
        redcap_token=rcap_token,
        template_path=req.template_path,
        org_unit=req.org_unit,
        start_date=req.start_date,
        end_date=req.end_date,
        dry_run=True,
    )
    return {"status": "submitted", "job_id": job.job_id}


@router.post("/redcap-import/run")
async def redcap_import_run(
    req: RedcapImportRequest,
    current_user: dict = Depends(get_current_user),
):
    dhis_creds = get_dhis2_credentials(req.source_instance or "dhis2_online")
    d_url = normalize_container_url(req.dhis2_url or dhis_creds["base_url"])
    d_user = req.dhis2_user or dhis_creds["username"]
    d_pass = req.dhis2_pass or dhis_creds["password"]

    rcap_creds = get_redcap_credentials()
    rcap_url = normalize_container_url(req.redcap_url or rcap_creds["base_url"])
    rcap_token = req.redcap_token or rcap_creds["token"]

    if not rcap_token and not req.redcap_token:
        raise HTTPException(
            status_code=400,
            detail="REDCap API token is not configured. Please enter it or configure it in Settings > Vault."
        )

    job = job_engine.submit_job(
        job_type="redcap_sync_commit",
        description=f"Commit DHIS2 to REDCap Sync for OU: {req.org_unit}",
        worker_fn=run_redcap_import_worker,
        dhis2_url=d_url,
        dhis2_user=d_user,
        dhis2_pass=d_pass,
        redcap_url=rcap_url,
        redcap_token=rcap_token,
        template_path=req.template_path,
        org_unit=req.org_unit,
        start_date=req.start_date,
        end_date=req.end_date,
        dry_run=False,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 5. CSV Import to DHIS2
# ==============================================================================
class CsvImportRequest(BaseModel):
    filepath: str
    target_instance: Optional[str] = "dhis2_online"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/csv-import/dry-run")
async def csv_import_dry_run(
    req: CsvImportRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(req.target_instance or "dhis2_online")
    raw_url = req.dhis2_url or creds["base_url"]
    url = normalize_container_url(raw_url)
    user = req.username or creds["username"]
    pw = req.password or creds["password"]

    job = job_engine.submit_job(
        job_type="csv_import_validate",
        description=f"Validate DHIS2 Tracker Import: {Path(req.filepath).name}",
        worker_fn=run_csv_import_worker,
        dhis2_url=url,
        username=user,
        password=pw,
        csv_path=req.filepath,
        dry_run=True,
    )
    return {"status": "submitted", "job_id": job.job_id}


@router.post("/csv-import/run")
async def csv_import_run(
    req: CsvImportRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(req.target_instance or "dhis2_online")
    raw_url = req.dhis2_url or creds["base_url"]
    url = normalize_container_url(raw_url)
    user = req.username or creds["username"]
    pw = req.password or creds["password"]

    job = job_engine.submit_job(
        job_type="csv_import_commit",
        description=f"Commit DHIS2 Tracker Import: {Path(req.filepath).name}",
        worker_fn=run_csv_import_worker,
        dhis2_url=url,
        username=user,
        password=pw,
        csv_path=req.filepath,
        dry_run=False,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 6. Analytical Data Export
# ==============================================================================
class AnalysisExportRequest(BaseModel):
    dhis2_url: Optional[str] = None
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    source_instance: Optional[str] = "dhis2_offline"
    program_name: Optional[str] = "Newborn Inpatient Data"
    program_id: Optional[str] = None
    ou_mode: Optional[str] = None
    org_unit_mode: Optional[str] = None
    ou_ids: Optional[List[str]] = None
    org_unit_id: Optional[str] = None
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    status_filter: Optional[str] = None
    status: Optional[str] = None
    event_status_filter: Optional[str] = None
    event_status: Optional[str] = None
    output_format: Optional[str] = None
    format: Optional[str] = None
    output_dir: Optional[str] = None
    filename: Optional[str] = None


@router.post("/analysis-export/run")
async def analysis_export_run(
    req: AnalysisExportRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(req.source_instance or "dhis2_offline")
    raw_url = req.dhis2_url or req.base_url or creds["base_url"]
    url = normalize_container_url(raw_url)
    user = req.username or creds["username"]
    pw = req.password or creds["password"]

    prog_name = req.program_name or "Newborn Inpatient Data"
    prog_id = req.program_id or DEFAULT_PROGRAM_MAP.get(prog_name) or "pLk3Ht2XMKl"
    ou_mode = req.ou_mode or req.org_unit_mode or "ALL"
    if req.ou_ids is not None:
        ou_ids = req.ou_ids
    elif req.org_unit_id:
        ou_ids = [req.org_unit_id]
    else:
        ou_ids = []
    status_filter = req.status_filter or req.status or "ALL"
    event_status_filter = req.event_status_filter or req.event_status or "ALL"
    output_format = req.output_format or req.format or "csv"

    job = job_engine.submit_job(
        job_type="analysis_data_export",
        description=f"Export for Analysis: {prog_name}",
        worker_fn=run_analysis_export_worker,
        base_url=url,
        username=user,
        password=pw,
        program_name=prog_name,
        program_id=prog_id,
        ou_mode=ou_mode,
        ou_ids=ou_ids,
        start=req.start_date or "",
        end=req.end_date or "",
        status_filter=status_filter,
        event_status_filter=event_status_filter,
        output_format=output_format,
        output_dir=req.output_dir,
        filename=req.filename,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 7. Data Cleaning (One Row per TEI)
# ==============================================================================
class CleaningRequest(BaseModel):
    filepath: str
    output_dir: Optional[str] = None
    filename: Optional[str] = None


@router.post("/cleaning/run")
async def cleaning_run(
    req: CleaningRequest,
    current_user: dict = Depends(get_current_user),
):
    job = job_engine.submit_job(
        job_type="data_cleaning_one_row_per_tei",
        description=f"Transform to One Row per TEI: {Path(req.filepath).name}",
        worker_fn=run_data_cleaning_worker,
        input_csv=req.filepath,
        output_dir=req.output_dir,
        filename=req.filename,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 8. Data Dictionary Export
# ==============================================================================
class DataDictionaryRequest(BaseModel):
    source_instance: Optional[str] = "dhis2_offline"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    program_name: Optional[str] = None
    program_id: Optional[str] = None
    output_dir: Optional[str] = None
    filename: Optional[str] = None


@router.post("/data-dictionary/run")
async def data_dictionary_run(
    req: DataDictionaryRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = get_dhis2_credentials(req.source_instance or "dhis2_offline")
    url = req.dhis2_url or creds["base_url"]
    user = req.username or creds["username"]
    pw = req.password or creds["password"]

    prog_to_run = req.program_id or req.program_name or "Newborn Inpatient Data"
    source_label = "Offline" if (req.source_instance or "dhis2_offline") == "dhis2_offline" else "Online"
    job = job_engine.submit_job(
        job_type="data_dictionary_export",
        description=f"Export Data Dictionary: {req.program_name or prog_to_run} ({source_label})",
        worker_fn=run_data_dictionary_worker,
        dhis2_url=url,
        username=user,
        password=pw,
        program_name=prog_to_run,
        output_dir=req.output_dir,
        filename=req.filename,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 9. NCF to NID Sync
# ==============================================================================
class NcfNidConnectRequest(BaseModel):
    system: Optional[str] = "dhis2_offline"
    server: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/ncf-nid/connect")
async def ncf_nid_connect(
    req: NcfNidConnectRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Connect to DHIS2 for NCF -> NID Sync.
    Tests credentials via me.json and retrieves the full org unit hierarchy
    sorted by path with tree indentation, exactly matching the original sync script.
    """
    system_key = req.system or "dhis2_offline"
    creds = get_dhis2_credentials(system_key)
    raw_url = req.server or creds.get("base_url", "http://localhost:8080")
    base_url = normalize_container_url(raw_url).rstrip("/")
    user = req.username or creds.get("username", "admin")
    pw = req.password if req.password is not None and req.password != "" else creds.get("password", "")

    auth = (user, pw) if user and pw else None
    try:
        # 1. Test credentials & fetch user identity
        me_res = requests.get(
            f"{base_url}/api/me.json",
            auth=auth,
            params={"fields": "id,displayName,username"},
            timeout=15,
            headers={"Accept": "application/json"}
        )
        if me_res.status_code != 200:
            return {
                "ok": False,
                "error": f"Authentication failed on {system_key}: HTTP {me_res.status_code} ({me_res.text[:120]})",
                "org_units": []
            }
        me_data = me_res.json()
        display_user = me_data.get("displayName") or me_data.get("username") or user

        # 2. Fetch full org unit hierarchy (without userOnly restriction, so all facility levels load)
        ou_res = requests.get(
            f"{base_url}/api/organisationUnits.json",
            auth=auth,
            params={"fields": "id,displayName,level,path", "paging": "false", "pageSize": 10000},
            timeout=25,
            headers={"Accept": "application/json"}
        )
        if ou_res.status_code != 200:
            return {
                "ok": False,
                "error": f"Failed fetching org units: HTTP {ou_res.status_code}",
                "org_units": []
            }

        ou_data = ou_res.json()
        raw_ous = ou_data.get("organisationUnits", [])
        # Sort by path so hierarchy is ordered geographically
        ous_sorted = sorted(raw_ous, key=lambda x: x.get("path", ""))
        org_units = [
            {
                "id": u["id"],
                "name": u.get("displayName", u["id"]),
                "level": u.get("level", 1),
                "path": u.get("path", ""),
                "display": ("  " * max(0, u.get("level", 1) - 1)) + u.get("displayName", u["id"]),
            }
            for u in ous_sorted
        ]

        return {
            "ok": True,
            "user": display_user,
            "server": base_url,
            "system": system_key,
            "org_units": org_units,
        }
    except Exception as e:
        logger.error(f"Error connecting to DHIS2 for NCF-NID sync: {e}")
        return {
            "ok": False,
            "error": str(e),
            "org_units": []
        }


class NcfNidSyncRequest(BaseModel):
    system: Optional[str] = "dhis2_offline"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    org_unit_id: Optional[str] = None
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    dry_run: Optional[bool] = False
    verbose: Optional[bool] = False


@router.post("/ncf-nid-sync/dry-run")
async def ncf_nid_sync_dry_run(
    req: NcfNidSyncRequest,
    current_user: dict = Depends(get_current_user),
):
    system_key = req.system or "dhis2_offline"
    creds = get_dhis2_credentials(system_key)
    raw_url = req.dhis2_url or creds["base_url"]
    url = normalize_container_url(raw_url).rstrip("/")
    user = req.username or creds["username"]
    pw = req.password if req.password is not None and req.password != "" else creds["password"]
    source_label = "Offline" if system_key == "dhis2_offline" else "Online"

    job = job_engine.submit_job(
        job_type="ncf_nid_sync_preview",
        description=f"NCF -> NID Sync (Preview/Dry-Run) [{source_label}]",
        worker_fn=run_ncf_nid_sync_worker,
        dhis2_url=url,
        username=user,
        password=pw,
        org_unit_id=req.org_unit_id,
        tei_uid=None,
        start_date=req.start_date,
        end_date=req.end_date,
        dry_run=True,
        verbose=req.verbose or False,
    )
    return {"status": "submitted", "job_id": job.job_id}


@router.post("/ncf-nid-sync/run")
async def ncf_nid_sync_run(
    req: NcfNidSyncRequest,
    current_user: dict = Depends(get_current_user),
):
    system_key = req.system or "dhis2_offline"
    creds = get_dhis2_credentials(system_key)
    raw_url = req.dhis2_url or creds["base_url"]
    url = normalize_container_url(raw_url).rstrip("/")
    user = req.username or creds["username"]
    pw = req.password if req.password is not None and req.password != "" else creds["password"]
    source_label = "Offline" if system_key == "dhis2_offline" else "Online"

    job = job_engine.submit_job(
        job_type="ncf_nid_sync_commit",
        description=f"NCF -> NID Sync (Commit) [{source_label}]",
        worker_fn=run_ncf_nid_sync_worker,
        dhis2_url=url,
        username=user,
        password=pw,
        org_unit_id=req.org_unit_id,
        tei_uid=None,
        start_date=req.start_date,
        end_date=req.end_date,
        dry_run=req.dry_run or False,
        verbose=req.verbose or False,
    )
    return {"status": "submitted", "job_id": job.job_id}


# ==============================================================================
# 10. Mother-Neonate Linker
# ==============================================================================
class MotherNeonateMetaRequest(BaseModel):
    system: Optional[str] = "dhis2_offline"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class MotherNeonateLinkerRequest(BaseModel):
    system: Optional[str] = "dhis2_offline"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    org_unit_id: str
    org_unit_name: str
    rel_type_id: str
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    threshold: float = 0.85


@router.post("/mother-neonate-linker/meta")
async def mother_neonate_meta(
    req: Optional[MotherNeonateMetaRequest] = None,
    current_user: dict = Depends(get_current_user),
):
    system_key = (req.system if req else None) or "dhis2_offline"
    creds = get_dhis2_credentials(system_key)
    raw_url = (req.dhis2_url if req and req.dhis2_url else None) or creds.get("base_url", "http://localhost:8080")
    url = normalize_container_url(raw_url).rstrip("/")
    user = (req.username if req and req.username else None) or creds.get("username", "admin")
    pw = (req.password if req and req.password is not None and req.password != "" else None) or creds.get("password", "")

    try:
        client = LinkerClient(base_url=url, username=user, password=pw)
        me = client.whoami()
        display_user = me.get("displayName") or me.get("username") or user
        raw_ous = client.get_org_units()
        rel_types = client.get_relationship_types()

        formatted_ous = []
        for ou in raw_ous:
            ancestors = ou.get("ancestors", [])
            path_names = " > ".join(a.get("name", "") for a in ancestors if a.get("name"))
            display = f"{ou.get('name', ou['id'])}" + (f"  ({path_names})" if path_names else "")
            formatted_ous.append({
                "id": ou["id"],
                "name": ou.get("name", ou["id"]),
                "level": ou.get("level", 1),
                "display": display,
            })
        formatted_ous.sort(key=lambda x: x["display"].lower())

        return {
            "status": "success",
            "ok": True,
            "user": display_user,
            "server": url,
            "system": system_key,
            "org_units": formatted_ous,
            "relationship_types": rel_types,
        }
    except Exception as e:
        logger.error(f"Error loading mother-neonate metadata from {system_key}: {e}")
        return {
            "status": "error",
            "ok": False,
            "error": str(e),
            "org_units": [],
            "relationship_types": [],
        }


@router.post("/mother-neonate-linker/dry-run")
async def mother_neonate_linker_dry_run(
    req: MotherNeonateLinkerRequest,
    current_user: dict = Depends(get_current_user),
):
    system_key = req.system or "dhis2_offline"
    creds = get_dhis2_credentials(system_key)
    raw_url = req.dhis2_url or creds.get("base_url", "http://localhost:8080")
    url = normalize_container_url(raw_url).rstrip("/")
    user = req.username or creds.get("username", "admin")
    pw = req.password if req.password is not None and req.password != "" else creds.get("password", "")
    source_label = "Offline" if system_key == "dhis2_offline" else "Online"

    job = job_engine.submit_job(
        job_type="mother_neonate_preview",
        description=f"Preview Linking: {req.org_unit_name} [{source_label}]",
        worker_fn=run_mother_neonate_linker_worker,
        dhis2_url=url,
        username=user,
        password=pw,
        org_unit_id=req.org_unit_id,
        org_unit_name=req.org_unit_name,
        rel_type_id=req.rel_type_id,
        start_date=req.start_date,
        end_date=req.end_date,
        threshold=req.threshold,
        dry_run=True,
    )
    return {"status": "submitted", "job_id": job.job_id}


@router.post("/mother-neonate-linker/run")
async def mother_neonate_linker_run(
    req: MotherNeonateLinkerRequest,
    current_user: dict = Depends(get_current_user),
):
    system_key = req.system or "dhis2_offline"
    creds = get_dhis2_credentials(system_key)
    raw_url = req.dhis2_url or creds.get("base_url", "http://localhost:8080")
    url = normalize_container_url(raw_url).rstrip("/")
    user = req.username or creds.get("username", "admin")
    pw = req.password if req.password is not None and req.password != "" else creds.get("password", "")
    source_label = "Offline" if system_key == "dhis2_offline" else "Online"

    job = job_engine.submit_job(
        job_type="mother_neonate_commit",
        description=f"Execute Mother-Neonate Linking: {req.org_unit_name} [{source_label}]",
        worker_fn=run_mother_neonate_linker_worker,
        dhis2_url=url,
        username=user,
        password=pw,
        org_unit_id=req.org_unit_id,
        org_unit_name=req.org_unit_name,
        rel_type_id=req.rel_type_id,
        start_date=req.start_date,
        end_date=req.end_date,
        threshold=req.threshold,
        dry_run=False,
    )
    return {"status": "submitted", "job_id": job.job_id}



# ==============================================================================
# Download Output Artifact Endpoint
# ==============================================================================
@router.get("/download/{filename:path}")
async def download_artifact(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    from backend.core.storage import resolve_export_file, build_file_response

    file_path = resolve_export_file(filename)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return build_file_response(file_path)
