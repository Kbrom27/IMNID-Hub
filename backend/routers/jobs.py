from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from pathlib import Path
from backend.core.jobs.engine import job_engine
from backend.core.jobs.models import JobListResponse, JobResponse
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])

@router.get("", response_model=JobListResponse)
def list_jobs(limit: int = 50, module: Optional[str] = None):
    items = job_engine.list_jobs(limit=limit, module=module)
    return JobListResponse(jobs=items, total=len(items))

@router.get("/{job_id}")
def get_job_detail(job_id: str):
    job = job_engine.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.get("/{job_id}/stream")
@router.get("/{job_id}/events")
def stream_job_updates(job_id: str):
    return StreamingResponse(
        job_engine.stream_job_events(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot cancel jobs")
    ok = job_engine.cancel_job(job_id)
    return {"ok": True, "message": f"Cancellation signal sent to job {job_id}"}

@router.get("/{job_id}/logs")
def download_job_log(job_id: str):
    from backend.core.config import settings
    log_file = settings.logs_dir / f"{job_id}.log"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(path=str(log_file), filename=f"job_{job_id}.log", media_type="text/plain")

