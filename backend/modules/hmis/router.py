"""HMIS Reporting API Router (HMIS RMH, HMIS NCH, NICU Register, Delivery Register, MOH Aggregate)."""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from requests.auth import HTTPBasicAuth
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.database import get_server_connection, list_server_connections
from backend.core.connections import normalize_container_url
from backend.core.jobs.engine import job_engine
from backend.routers.auth import get_current_user

from backend.modules.hmis.service import (
    discover_dhis2_metadata,
    run_rmh_delivery_register_csv_worker,
    run_rmh_delivery_register_dhis2_worker,
    run_rmh_delivery_register_openmrs_worker,
    run_rmh_aggregate_report_worker,
    run_rmh_aggregate_report_openmrs_worker,
    run_nh_neonatal_register_csv_worker,
    run_nh_neonatal_register_dhis2_worker,
    run_nh_neonatal_register_openmrs_worker,
    run_nh_aggregate_report_worker,
    run_nh_aggregate_report_openmrs_worker,
    run_moh_aggregate_worker,
)
from backend.modules.hmis.moh_aggregate import MohAggregatePipeline
from backend.modules.hmis.ethiopian_calendar import (
    ethiopian_month_window,
    get_calendar_info,
)

router = APIRouter(prefix="/api/hmis", tags=["hmis"])


def _resolve_dhis2_creds(
    req_url: Optional[str] = None,
    req_user: Optional[str] = None,
    req_pw: Optional[str] = None,
    system: Optional[str] = "dhis2_online",
) -> Dict[str, str]:
    sys_key = system or "dhis2_online"
    conn = get_server_connection(sys_key)
    if not conn and sys_key in ("dhis2_moh", "moh", "moh_dhis2"):
        conn = get_server_connection("dhis2_moh")
    if not conn and sys_key != "dhis2":
        conn = get_server_connection("dhis2_offline" if "off" in str(sys_key).lower() else "dhis2_online")
    if not conn:
        conn = get_server_connection("dhis2") or {}

    is_moh = sys_key in ("dhis2_moh", "moh", "moh_dhis2")
    fallback_url = settings.DHIS2_MOH_URL if is_moh else settings.DHIS2_URL
    fallback_user = settings.DHIS2_MOH_USERNAME if is_moh else settings.DHIS2_USERNAME
    fallback_pw = settings.DHIS2_MOH_PASSWORD if is_moh else settings.DHIS2_PASSWORD

    return {
        "base_url": req_url or conn.get("base_url") or fallback_url,
        "username": req_user or conn.get("username") or fallback_user,
        "password": req_pw or conn.get("secret") or fallback_pw,
    }


def _resolve_openmrs_creds(
    req_url: Optional[str] = None,
    req_user: Optional[str] = None,
    req_pw: Optional[str] = None,
) -> Dict[str, str]:
    conn = get_server_connection("openmrs") or {}
    return {
        "base_url": req_url or conn.get("base_url") or settings.OPENMRS_URL,
        "username": req_user or conn.get("username") or settings.OPENMRS_USERNAME,
        "password": req_pw or conn.get("secret") or settings.OPENMRS_PASSWORD,
    }


# ==============================================================================
# Server Connections & Metadata Endpoints (DHIS2, OpenMRS, Mappings)
# ==============================================================================
@router.get("/connections")
async def get_hmis_connections(current_user: dict = Depends(get_current_user)):
    """Return configured DHIS2 and OpenMRS connections from the vault."""
    conns = list_server_connections()
    dhis2_online = next((c for c in conns if c["system"] == "dhis2_online"), None)
    dhis2_offline = next((c for c in conns if c["system"] == "dhis2_offline"), None)
    dhis2_moh = next((c for c in conns if c["system"] == "dhis2_moh"), None)
    openmrs = next((c for c in conns if c["system"] == "openmrs"), None)

    def _enrich(c):
        if not c:
            return None
        full = get_server_connection(c["system"]) or {}
        return {
            "system": c["system"],
            "name": c.get("name") or c["system"].upper(),
            "base_url": c.get("base_url") or "",
            "username": c.get("username") or "",
            "has_secret": bool(full.get("secret")),
            "is_active": c.get("is_active", 1),
        }

    return {
        "status": "success",
        "dhis2_online": _enrich(dhis2_online),
        "dhis2_offline": _enrich(dhis2_offline),
        "dhis2_moh": _enrich(dhis2_moh),
        "openmrs": _enrich(openmrs),
        "default_dhis2": "dhis2_online" if dhis2_online and dhis2_online.get("base_url") else "dhis2_offline",
    }


@router.get("/dhis2/programs")
async def get_hmis_dhis2_programs(
    system: Optional[str] = Query("dhis2_online"),
    current_user: dict = Depends(get_current_user),
):
    """Fetch available tracker programs from the saved DHIS2 connection."""
    creds = _resolve_dhis2_creds(system=system)
    base_url = normalize_container_url(creds["base_url"]).rstrip("/")
    user = creds["username"]
    pw = creds["password"]

    if not base_url or not user:
        return {"status": "error", "message": "DHIS2 connection not configured", "programs": []}

    auth = HTTPBasicAuth(user, pw)
    try:
        url = f"{base_url}/api/programs.json?fields=id,displayName,programType&paging=false"
        resp = requests.get(url, auth=auth, headers={"Accept": "application/json"}, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            progs = [
                {"id": p["id"], "name": p.get("displayName") or p["id"], "type": p.get("programType")}
                for p in data.get("programs", [])
            ]
            return {"status": "success", "programs": progs}
        return {"status": "error", "message": f"DHIS2 returned HTTP {resp.status_code}", "programs": []}
    except Exception as exc:
        return {"status": "error", "message": str(exc), "programs": []}


@router.get("/dhis2/org-units")
async def get_hmis_dhis2_org_units(
    system: Optional[str] = Query("dhis2_online"),
    query: Optional[str] = Query(None),
    level: Optional[int] = Query(None),
    limit: int = Query(1000),
    current_user: dict = Depends(get_current_user),
):
    """Fetch organisation units from the saved DHIS2 connection."""
    creds = _resolve_dhis2_creds(system=system)
    base_url = normalize_container_url(creds["base_url"]).rstrip("/")
    user = creds["username"]
    pw = creds["password"]

    if not base_url or not user:
        return {"status": "error", "message": "DHIS2 connection not configured", "org_units": []}

    auth = HTTPBasicAuth(user, pw)
    try:
        params = {"fields": "id,displayName,level,path", "paging": "false"}
        url = f"{base_url}/api/organisationUnits.json"
        resp = requests.get(url, auth=auth, params=params, headers={"Accept": "application/json"}, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            ous = data.get("organisationUnits", [])
            if query:
                q = query.strip().lower()
                ous = [o for o in ous if q in (o.get("displayName") or "").lower()]
            if level is not None:
                ous = [o for o in ous if o.get("level") == level]

            res_list = [
                {"id": o["id"], "name": o.get("displayName") or o["id"], "level": o.get("level", 1), "path": o.get("path", "")}
                for o in ous[:limit]
            ]
            return {"status": "success", "org_units": res_list, "total": len(ous)}
        return {"status": "error", "message": f"DHIS2 returned HTTP {resp.status_code}", "org_units": []}
    except Exception as exc:
        return {"status": "error", "message": str(exc), "org_units": []}


@router.get("/dhis2/data-elements")
async def get_hmis_dhis2_data_elements(
    system: Optional[str] = Query("dhis2_moh"),
    query: Optional[str] = Query(None),
    limit: int = Query(100),
    current_user: dict = Depends(get_current_user),
):
    """Fetch aggregate data elements from the saved DHIS2 connection."""
    creds = _resolve_dhis2_creds(system=system)
    base_url = normalize_container_url(creds["base_url"]).rstrip("/")
    user = creds["username"]
    pw = creds["password"]

    if not base_url or not user:
        return {"status": "error", "message": "DHIS2 connection not configured", "data_elements": []}

    auth = HTTPBasicAuth(user, pw)
    try:
        params = {"fields": "id,displayName,domainType", "paging": "false"}
        if query:
            params["filter"] = f"displayName:ilike:{query.strip()}"
        url = f"{base_url}/api/dataElements.json"
        resp = requests.get(url, auth=auth, params=params, headers={"Accept": "application/json"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            des = [
                {"id": d["id"], "name": d.get("displayName") or d["id"]}
                for d in data.get("dataElements", [])[:limit]
            ]
            return {"status": "success", "data_elements": des}
        return {"status": "error", "message": f"DHIS2 returned HTTP {resp.status_code}", "data_elements": []}
    except Exception as exc:
        return {"status": "error", "message": str(exc), "data_elements": []}


@router.get("/openmrs/visit-types")
async def get_hmis_openmrs_visit_types(current_user: dict = Depends(get_current_user)):
    """Fetch visit types from saved OpenMRS connection."""
    creds = _resolve_openmrs_creds()
    base_url = normalize_container_url(creds["base_url"]).rstrip("/")
    user = creds["username"]
    pw = creds["password"]

    if not base_url:
        return {"status": "error", "message": "OpenMRS connection not configured", "visit_types": []}

    auth = HTTPBasicAuth(user, pw)
    try:
        url = f"{base_url}/ws/rest/v1/visittype?v=custom:(uuid,display,name)"
        resp = requests.get(url, auth=auth, timeout=6)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            types = [
                {"uuid": r.get("uuid"), "name": r.get("name") or r.get("display"), "display": r.get("display") or r.get("name")}
                for r in results
            ]
            return {"status": "success", "visit_types": types}
        return {"status": "error", "message": f"OpenMRS returned HTTP {resp.status_code}", "visit_types": []}
    except Exception as exc:
        return {"status": "error", "message": str(exc), "visit_types": []}


@router.get("/openmrs/locations")
async def get_hmis_openmrs_locations(current_user: dict = Depends(get_current_user)):
    """Fetch locations/facilities from saved OpenMRS connection."""
    creds = _resolve_openmrs_creds()
    base_url = normalize_container_url(creds["base_url"]).rstrip("/")
    user = creds["username"]
    pw = creds["password"]

    if not base_url:
        return {"status": "error", "message": "OpenMRS connection not configured", "locations": []}

    auth = HTTPBasicAuth(user, pw)
    try:
        url = f"{base_url}/ws/rest/v1/location?v=custom:(uuid,display,name)"
        resp = requests.get(url, auth=auth, timeout=6)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            locations = [
                {"uuid": r.get("uuid"), "name": r.get("name") or r.get("display"), "display": r.get("display") or r.get("name")}
                for r in results
            ]
            return {"status": "success", "locations": locations}
        return {"status": "error", "message": f"OpenMRS returned HTTP {resp.status_code}", "locations": []}
    except Exception as exc:
        return {"status": "error", "message": str(exc), "locations": []}


@router.get("/mapping-files")
async def get_hmis_mapping_files(current_user: dict = Depends(get_current_user)):
    """List available Excel/CSV mapping files from templates and uploads."""
    tmpl_dir = Path(__file__).resolve().parent / "templates"
    files = []
    seen = set()

    if tmpl_dir.is_dir():
        for p in tmpl_dir.glob("*.*"):
            if p.suffix.lower() in (".xlsx", ".xls", ".csv") and p.name not in seen:
                seen.add(p.name)
                files.append({
                    "filename": p.name,
                    "location": "template",
                    "size": p.stat().st_size,
                    "is_default": "maternal" in p.name.lower() or "nicu" in p.name.lower(),
                })

    if settings.uploads_dir.is_dir():
        for p in settings.uploads_dir.glob("*.*"):
            if p.suffix.lower() in (".xlsx", ".xls", ".csv") and p.name not in seen:
                seen.add(p.name)
                files.append({
                    "filename": p.name,
                    "location": "upload",
                    "size": p.stat().st_size,
                    "is_default": False,
                })

    return {"status": "success", "mapping_files": files}


# ==============================================================================
# File Upload Endpoint
# ==============================================================================
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    upload_dir = settings.uploads_dir
    dest_path = upload_dir / file.filename

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "status": "success",
        "filename": file.filename,
        "filepath": str(dest_path),
        "size": dest_path.stat().st_size,
    }


# ==============================================================================
# HMIS Discovery & Calendar
# ==============================================================================
class Dhis2ConnectRequest(BaseModel):
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = True


@router.post("/connect")
async def connect_and_discover(
    req: Dhis2ConnectRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_dhis2_creds(req.dhis2_url, req.username, req.password)
    try:
        data = discover_dhis2_metadata(
            url=creds["base_url"],
            username=creds["username"],
            password=creds["password"],
            verify_ssl=req.verify_ssl,
        )
        return {
            "status": "success",
            "dhis2_url": creds["base_url"],
            "discovery": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to connect to DHIS2: {exc}")


@router.get("/ethiopian-calendar")
async def get_ethiopian_calendar(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    info = get_calendar_info(year, month)
    g_start, g_end = ethiopian_month_window(info["year"], info["month"])
    info["gregorian_start"] = g_start
    info["gregorian_end"] = g_end
    info["period_code"] = f"{info['year']}{info['month']:02d}"
    return info


# ==============================================================================
# 1. DELIVERY REGISTER GENERATOR
# ==============================================================================
class RmhDeliveryRegisterDhis2Request(BaseModel):
    system: Optional[str] = "dhis2_online"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = True
    program_uid: str = "Maternal Inpatient Data"
    org_unit: Optional[str] = None
    ou_mode: str = "DESCENDANTS"
    start: Optional[str] = None
    end: Optional[str] = None
    output_filename: Optional[str] = None
    output_dir: Optional[str] = None
    sheet_per_facility: bool = False
    page_size: int = 250


@router.post("/rmh/delivery-register-dhis2")
async def run_rmh_delivery_register_dhis2(
    req: RmhDeliveryRegisterDhis2Request,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_dhis2_creds(req.dhis2_url, req.username, req.password, system=req.system)
    job = job_engine.submit_job(
        job_type="hmis_rmh_register_dhis2",
        description=f"Generate Delivery Register from DHIS2 Tracker ({req.org_unit or 'All OU'})",
        worker_fn=run_rmh_delivery_register_dhis2_worker,
        base_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        verify_ssl=req.verify_ssl,
        program_uid=req.program_uid,
        org_unit=req.org_unit,
        ou_mode=req.ou_mode,
        start=req.start,
        end=req.end,
        output_filename=req.output_filename,
        output_dir=req.output_dir,
        sheet_per_facility=req.sheet_per_facility,
        page_size=req.page_size,
    )
    return {"job_id": job.job_id, "status": "submitted"}


class RmhDeliveryRegisterOpenmrsRequest(BaseModel):
    input_file: Optional[str] = None
    openmrs_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    visit_type: Optional[str] = "Delivery"
    start: Optional[str] = None
    end: Optional[str] = None
    facility_name: Optional[str] = None
    facility_code: Optional[str] = None
    output_filename: Optional[str] = None
    output_dir: Optional[str] = None
    sheet_per_facility: bool = False


@router.post("/rmh/delivery-register-openmrs")
async def run_rmh_delivery_register_openmrs(
    req: RmhDeliveryRegisterOpenmrsRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_openmrs_creds(req.openmrs_url, req.username, req.password)
    job = job_engine.submit_job(
        job_type="hmis_rmh_register_openmrs",
        description=f"Generate Delivery Register from OpenMRS 3 ({req.facility_name or 'OpenMRS'})",
        worker_fn=run_rmh_delivery_register_openmrs_worker,
        input_file=req.input_file,
        openmrs_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        start=req.start,
        end=req.end,
        facility_name=req.facility_name,
        facility_code=req.facility_code,
        output_filename=req.output_filename,
        output_dir=req.output_dir,
        sheet_per_facility=req.sheet_per_facility,
    )
    return {"job_id": job.job_id, "status": "submitted"}


class RmhDeliveryRegisterCsvRequest(BaseModel):
    input_file: str
    output_filename: Optional[str] = None
    output_dir: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    region: Optional[str] = None
    facility: Optional[str] = None
    sheet_per_facility: bool = False


@router.post("/rmh/delivery-register-csv")
async def run_rmh_delivery_register_csv(
    req: RmhDeliveryRegisterCsvRequest,
    current_user: dict = Depends(get_current_user),
):
    input_path = Path(req.input_file)
    if not input_path.is_absolute():
        input_path = settings.uploads_dir / req.input_file

    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {req.input_file}")

    job = job_engine.submit_job(
        job_type="hmis_rmh_register_csv",
        description=f"Generate Delivery Register from CSV ({input_path.name})",
        worker_fn=run_rmh_delivery_register_csv_worker,
        input_file=str(input_path),
        output_filename=req.output_filename,
        output_dir=req.output_dir,
        start=req.start,
        end=req.end,
        region=req.region,
        facility=req.facility,
        sheet_per_facility=req.sheet_per_facility,
    )
    return {"job_id": job.job_id, "status": "submitted"}


# ==============================================================================
# 2. HMIS RMH REPORT GENERATOR (01.2)
# ==============================================================================
class RmhAggregateReportRequest(BaseModel):
    system: Optional[str] = "dhis2_online"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = True
    delivery_program: str = "Maternal Inpatient Data"
    org_unit: Optional[str] = None
    ou_mode: str = "SELECTED"
    period: str = "202610"
    start: Optional[str] = None
    end: Optional[str] = None
    output_filename: Optional[str] = None
    dataset: Optional[str] = None
    dry_run: bool = True
    submit: bool = False
    preview_filename: Optional[str] = None
    json_filename: Optional[str] = None
    export_json_filename: Optional[str] = None
    output_dir: Optional[str] = None


@router.post("/rmh/aggregate-report")
async def run_rmh_aggregate_report(
    req: RmhAggregateReportRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_dhis2_creds(req.dhis2_url, req.username, req.password, system=req.system)
    job = job_engine.submit_job(
        job_type="hmis_rmh_aggregate_report",
        description=f"Compute 01.2 RMH Monthly Report from DHIS2 Tracker ({req.period})",
        worker_fn=run_rmh_aggregate_report_worker,
        base_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        verify_ssl=req.verify_ssl,
        delivery_program=req.delivery_program,
        org_unit=req.org_unit,
        ou_mode=req.ou_mode,
        period=req.period,
        start=req.start,
        end=req.end,
        output_filename=req.output_filename,
        dataset=req.dataset,
        dry_run=req.dry_run,
        submit=req.submit,
        preview_filename=req.preview_filename,
        json_filename=req.json_filename,
        export_json_filename=req.export_json_filename,
        output_dir=req.output_dir,
    )
    return {"job_id": job.job_id, "status": "submitted"}


class RmhAggregateReportOpenmrsRequest(BaseModel):
    input_file: Optional[str] = None
    openmrs_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    visit_type: Optional[str] = "Delivery"
    period: str = "201702"
    start: Optional[str] = None
    end: Optional[str] = None
    facility_name: Optional[str] = None
    output_filename: Optional[str] = None
    preview_filename: Optional[str] = None
    json_filename: Optional[str] = None
    output_dir: Optional[str] = None


@router.post("/rmh/aggregate-report-openmrs")
async def run_rmh_aggregate_report_openmrs(
    req: RmhAggregateReportOpenmrsRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_openmrs_creds(req.openmrs_url, req.username, req.password)
    job = job_engine.submit_job(
        job_type="hmis_rmh_aggregate_openmrs",
        description=f"Compute 01.2 RMH Monthly Report from OpenMRS 3 ({req.period})",
        worker_fn=run_rmh_aggregate_report_openmrs_worker,
        input_file=req.input_file,
        openmrs_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        period=req.period,
        start=req.start,
        end=req.end,
        facility_name=req.facility_name,
        output_filename=req.output_filename,
        preview_filename=req.preview_filename,
        json_filename=req.json_filename,
        output_dir=req.output_dir,
    )
    return {"job_id": job.job_id, "status": "submitted"}


# ==============================================================================
# 3. NICU REGISTER GENERATOR
# ==============================================================================
class NhNeonatalRegisterDhis2Request(BaseModel):
    system: Optional[str] = "dhis2_online"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = True
    program_uid: str = "Neonatal Care Form"
    org_unit: Optional[str] = None
    ou_mode: str = "DESCENDANTS"
    start: Optional[str] = None
    end: Optional[str] = None
    output_filename: Optional[str] = None
    output_dir: Optional[str] = None
    sheet_per_facility: bool = False
    page_size: int = 250


@router.post("/nh/nicu-register-dhis2")
async def run_nh_neonatal_register_dhis2(
    req: NhNeonatalRegisterDhis2Request,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_dhis2_creds(req.dhis2_url, req.username, req.password, system=req.system)
    job = job_engine.submit_job(
        job_type="hmis_nh_register_dhis2",
        description=f"Generate NICU Register from DHIS2 Tracker ({req.org_unit or 'All OU'})",
        worker_fn=run_nh_neonatal_register_dhis2_worker,
        base_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        verify_ssl=req.verify_ssl,
        program_uid=req.program_uid,
        org_unit=req.org_unit,
        ou_mode=req.ou_mode,
        start=req.start,
        end=req.end,
        output_filename=req.output_filename,
        output_dir=req.output_dir,
        sheet_per_facility=req.sheet_per_facility,
        page_size=req.page_size,
    )
    return {"job_id": job.job_id, "status": "submitted"}


class NhNeonatalRegisterOpenmrsRequest(BaseModel):
    input_file: Optional[str] = None
    openmrs_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    visit_type: Optional[str] = "NICU"
    start: Optional[str] = None
    end: Optional[str] = None
    facility_name: Optional[str] = None
    facility_code: Optional[str] = None
    output_filename: Optional[str] = None
    output_dir: Optional[str] = None
    sheet_per_facility: bool = False


@router.post("/nh/nicu-register-openmrs")
async def run_nh_neonatal_register_openmrs(
    req: NhNeonatalRegisterOpenmrsRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_openmrs_creds(req.openmrs_url, req.username, req.password)
    job = job_engine.submit_job(
        job_type="hmis_nh_register_openmrs",
        description=f"Generate NICU Register from OpenMRS 3 ({req.facility_name or 'OpenMRS'})",
        worker_fn=run_nh_neonatal_register_openmrs_worker,
        input_file=req.input_file,
        openmrs_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        start=req.start,
        end=req.end,
        facility_name=req.facility_name,
        facility_code=req.facility_code,
        output_filename=req.output_filename,
        output_dir=req.output_dir,
        sheet_per_facility=req.sheet_per_facility,
    )
    return {"job_id": job.job_id, "status": "submitted"}


class NhNeonatalRegisterCsvRequest(BaseModel):
    input_file: str
    output_filename: Optional[str] = None
    output_dir: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    region: Optional[str] = None
    facility: Optional[str] = None
    sheet_per_facility: bool = False


@router.post("/nh/nicu-register-csv")
async def run_nh_neonatal_register_csv(
    req: NhNeonatalRegisterCsvRequest,
    current_user: dict = Depends(get_current_user),
):
    input_path = Path(req.input_file)
    if not input_path.is_absolute():
        input_path = settings.uploads_dir / req.input_file

    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {req.input_file}")

    job = job_engine.submit_job(
        job_type="hmis_nh_register_csv",
        description=f"Generate NICU Register from CSV ({input_path.name})",
        worker_fn=run_nh_neonatal_register_csv_worker,
        input_file=str(input_path),
        output_filename=req.output_filename,
        output_dir=req.output_dir,
        start=req.start,
        end=req.end,
        region=req.region,
        facility=req.facility,
        sheet_per_facility=req.sheet_per_facility,
    )
    return {"job_id": job.job_id, "status": "submitted"}


# ==============================================================================
# 4. HMIS NCH REPORT GENERATOR (04.2)
# ==============================================================================
class NhAggregateReportRequest(BaseModel):
    system: Optional[str] = "dhis2_online"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = True
    program_uid: str = "Neonatal Care Form"
    org_unit: Optional[str] = None
    ou_mode: str = "SELECTED"
    period: str = "202610"
    start: Optional[str] = None
    end: Optional[str] = None
    output_filename: Optional[str] = None
    dataset: Optional[str] = None
    dry_run: bool = True
    submit: bool = False
    preview_filename: Optional[str] = None
    json_filename: Optional[str] = None
    export_json_filename: Optional[str] = None
    output_dir: Optional[str] = None


@router.post("/nh/aggregate-report")
async def run_nh_aggregate_report(
    req: NhAggregateReportRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_dhis2_creds(req.dhis2_url, req.username, req.password, system=req.system)
    job = job_engine.submit_job(
        job_type="hmis_nh_aggregate_report",
        description=f"Compute 04.2 NCH Monthly Report from DHIS2 Tracker ({req.period})",
        worker_fn=run_nh_aggregate_report_worker,
        base_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        verify_ssl=req.verify_ssl,
        program_uid=req.program_uid,
        org_unit=req.org_unit,
        ou_mode=req.ou_mode,
        period=req.period,
        start=req.start,
        end=req.end,
        output_filename=req.output_filename,
        dataset=req.dataset,
        dry_run=req.dry_run,
        submit=req.submit,
        preview_filename=req.preview_filename,
        json_filename=req.json_filename,
        export_json_filename=req.export_json_filename,
        output_dir=req.output_dir,
    )
    return {"job_id": job.job_id, "status": "submitted"}


class NhAggregateReportOpenmrsRequest(BaseModel):
    input_file: Optional[str] = None
    openmrs_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    visit_type: Optional[str] = "NICU"
    period: str = "201702"
    start: Optional[str] = None
    end: Optional[str] = None
    facility_name: Optional[str] = None
    output_filename: Optional[str] = None
    preview_filename: Optional[str] = None
    json_filename: Optional[str] = None
    output_dir: Optional[str] = None


@router.post("/nh/aggregate-report-openmrs")
async def run_nh_aggregate_report_openmrs(
    req: NhAggregateReportOpenmrsRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_openmrs_creds(req.openmrs_url, req.username, req.password)
    job = job_engine.submit_job(
        job_type="hmis_nh_aggregate_openmrs",
        description=f"Compute 04.2 NCH Monthly Report from OpenMRS 3 ({req.period})",
        worker_fn=run_nh_aggregate_report_openmrs_worker,
        input_file=req.input_file,
        openmrs_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        period=req.period,
        start=req.start,
        end=req.end,
        facility_name=req.facility_name,
        output_filename=req.output_filename,
        preview_filename=req.preview_filename,
        json_filename=req.json_filename,
        output_dir=req.output_dir,
    )
    return {"job_id": job.job_id, "status": "submitted"}


# ==============================================================================
# 5. MOH FACILITY AGGREGATE REPORT EXPORTER
# ==============================================================================
class MohTestConnectionRequest(BaseModel):
    system: Optional[str] = "dhis2_moh"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/moh-aggregate/test-connection")
async def test_moh_aggregate_connection(
    req: MohTestConnectionRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_dhis2_creds(req.dhis2_url, req.username, req.password, system=req.system)
    pipeline = MohAggregatePipeline(
        base_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        data_element_uid="",
        mapping_file="",
        output_dir="",
    )
    try:
        pipeline.login()
        return {
            "status": "success",
            "message": "Connected to MOH DHIS2 successfully and verified session.",
            "base_url": creds["base_url"],
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"MOH DHIS2 connection failed: {exc}")


class MohAggregateRunRequest(BaseModel):
    system: Optional[str] = "dhis2_moh"
    dhis2_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    data_element_uid: str = "lzhOxCHJMOV"
    mapping_file: Optional[str] = "Maternal aggregate.xlsx"
    output_filename: Optional[str] = None
    output_dir: Optional[str] = None
    periods: Optional[List[str]] = None
    year: Optional[int] = None
    months: Optional[List[int]] = None


@router.post("/moh-aggregate/run")
async def run_moh_aggregate_report(
    req: MohAggregateRunRequest,
    current_user: dict = Depends(get_current_user),
):
    creds = _resolve_dhis2_creds(req.dhis2_url, req.username, req.password, system=req.system)
    job = job_engine.submit_job(
        job_type="hmis_moh_aggregate_export",
        description=f"Export MOH Facility Aggregate ({req.data_element_uid})",
        worker_fn=run_moh_aggregate_worker,
        base_url=creds["base_url"],
        username=creds["username"],
        password=creds["password"],
        data_element_uid=req.data_element_uid,
        mapping_file=req.mapping_file,
        output_filename=req.output_filename,
        output_dir=req.output_dir,
        periods=req.periods,
        year=req.year,
        months=req.months,
    )
    return {"job_id": job.job_id, "status": "submitted"}


# ==============================================================================
# TEMPLATES & DOWNLOAD ARTIFACTS
# ==============================================================================
@router.get("/templates")
async def list_hmis_templates(
    current_user: dict = Depends(get_current_user),
):
    tmpl_dir = Path(__file__).resolve().parent / "templates"
    templates = []
    if tmpl_dir.exists():
        for f in sorted(tmpl_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                templates.append({
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "type": "excel" if f.suffix.lower() in [".xlsx", ".xls"] else "csv",
                })
    return {"status": "success", "templates": templates}


@router.get("/templates/{filename:path}")
async def download_hmis_template(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    from backend.core.storage import build_file_response
    tmpl_dir = Path(__file__).resolve().parent / "templates"
    file_path = tmpl_dir / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Template file not found")
    return build_file_response(file_path)


@router.get("/download/{filename:path}")
async def download_hmis_file(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    from backend.core.storage import resolve_export_file, build_file_response

    file_path = resolve_export_file(filename, include_uploads=True)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return build_file_response(file_path)
