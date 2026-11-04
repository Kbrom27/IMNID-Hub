import shutil
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.jobs.engine import job_engine
from backend.routers.auth import get_current_user
from backend.modules.smartcare.service import (
    test_openmrs_connection,
    validate_smartcare_csv,
    run_migration_worker
)

router = APIRouter(prefix="/api/smartcare", tags=["SmartCare Migration"])

class ConnectRequest(BaseModel):
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

class DryRunRequest(BaseModel):
    filepath: str
    limit: Optional[int] = 500
    config: Optional[Dict[str, Any]] = None

class ImportRequest(BaseModel):
    filepath: str
    limit: Optional[int] = None
    config: Optional[Dict[str, Any]] = None
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

@router.get("/status")
def get_smartcare_status():
    conn_res = test_openmrs_connection()
    available_files = []
    
    # Check uploads directory
    if settings.uploads_dir.is_dir():
        for p in sorted(settings.uploads_dir.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline()
                    headers = [h.strip() for h in first_line.split(",") if h.strip()]
                    row_count = sum(1 for _ in f)
                available_files.append({
                    "filename": p.name,
                    "filepath": str(p),
                    "size": p.stat().st_size,
                    "total_rows": row_count,
                    "headers": headers,
                    "is_sample": "smartcare_sample" in p.name.lower() or "smoke_test" in p.name.lower(),
                })
            except Exception:
                pass

    return {
        "connection": conn_res,
        "available_files": available_files
    }

@router.get("/files")
def list_available_files():
    status = get_smartcare_status()
    return {"files": status.get("available_files", [])}

@router.post("/connect")
def check_connection(req: ConnectRequest):
    res = test_openmrs_connection(req.base_url, req.username, req.password)
    return res

@router.post("/upload")
async def upload_smartcare_csv(file: UploadFile = File(...), user: Dict[str, Any] = Depends(get_current_user)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    filename = f"smartcare_{uuid.uuid4().hex[:8]}_{file.filename}"
    dest_path = settings.uploads_dir / filename

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")

    # Fast validation of CSV headers
    headers = []
    total_rows = 0
    with open(dest_path, "r", encoding="utf-8", errors="ignore") as f:
        line = f.readline()
        if line:
            headers = [h.strip() for h in line.split(",")]
        total_rows = sum(1 for _ in f)

    return {
        "success": True,
        "filename": filename,
        "filepath": str(dest_path),
        "total_rows": total_rows,
        "headers": headers
    }

@router.post("/dry-run")
def execute_dry_run(req: DryRunRequest, user: Dict[str, Any] = Depends(get_current_user)):
    file_path = Path(req.filepath)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="CSV file not found on server")

    result = validate_smartcare_csv(str(file_path), limit=req.limit, config=req.config)
    
    # Ensure aliases exist for both web UI and desktop parity
    summary = result.get("summary", {})
    summary["total_records"] = summary.get("total_rows", 0)
    summary["warnings_count"] = summary.get("warnings", 0)
    summary["invalid_records"] = summary.get("errors", 0) + summary.get("duplicate_mrns", 0) + summary.get("duplicate_uuids", 0)
    
    samples = result.get("sample_records", [])
    if samples and "sample_transformed" not in result:
        result["sample_transformed"] = samples[0].get("openmrs_payload")

    return result

@router.post("/import")
def start_import_job(req: ImportRequest, user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewers are not permitted to run data migrations")

    file_path = Path(req.filepath)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="CSV file not found on server")

    job_id = job_engine.start_job(
        module="smartcare",
        action="SmartCare to OpenMRS 3.x Migration",
        target=lambda ctx: run_migration_worker(
            ctx=ctx,
            csv_filepath=str(file_path),
            limit=req.limit,
            config=req.config,
            base_url=req.base_url,
            username=req.username,
            password=req.password
        )
    )

    return {
        "success": True,
        "job_id": job_id,
        "message": "Migration job initiated successfully"
    }

@router.get("/errors/{job_id}")
def download_migration_errors(job_id: str):
    error_file = settings.exports_dir / f"smartcare_errors_{job_id}.csv"
    if not error_file.exists():
        raise HTTPException(status_code=404, detail="Error report not found for this job")
    return FileResponse(
        path=str(error_file),
        filename=f"smartcare_errors_{job_id}.csv",
        media_type="text/csv"
    )
