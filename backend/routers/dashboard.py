from fastapi import APIRouter
from backend.core.database import get_db_connection, list_server_connections
from backend.core.jobs.engine import job_engine

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("/stats")
def get_dashboard_stats():
    conn = get_db_connection()
    total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    completed_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'completed'").fetchone()[0]
    running_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()[0]
    failed_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('failed', 'canceled')").fetchone()[0]
    conn.close()

    recent_jobs = job_engine.list_jobs(limit=5)
    systems = list_server_connections()

    from backend.core.config import settings

    return {
        "app_env": settings.APP_ENV,
        "job_stats": {
            "total": total_jobs,
            "completed": completed_jobs,
            "running": running_jobs,
            "failed": failed_jobs
        },
        "configured_systems_count": len(systems),
        "recent_jobs": recent_jobs
    }
