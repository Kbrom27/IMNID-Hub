import json
import logging
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Generator, List

from backend.core.config import settings
from backend.core.database import get_db_connection

logger = logging.getLogger("imnid.jobs")

class JobContext:
    def __init__(self, job_id: str, module: str, action: str):
        self.job_id = job_id
        self.module = module
        self.action = action
        self.cancel_event = threading.Event()
        self.log_queue: queue.Queue = queue.Queue(maxsize=1000)
        self.log_file_path = settings.logs_dir / f"{job_id}.log"
        self._lock = threading.Lock()

        # In-memory tracking
        self.status = "pending"
        self.progress = 0
        self.total = 0
        self.success_count = 0
        self.fail_count = 0
        self.message = "Initialized"
        self.errors: List[str] = []
        self.result_file: Optional[str] = None
        self.artifacts: Dict[str, Any] = {}
        self.meta: Dict[str, Any] = {}
        self.job = self
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None

    def is_cancelled(self) -> bool:
        return self.is_canceled()

    def log(self, text: str, level: str = "INFO"):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {text}"
        try:
            self.log_queue.put_nowait({"timestamp": timestamp, "level": level, "text": text})
        except queue.Full:
            pass
        try:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass

    def update_progress(self, progress: Optional[int] = None, total: Optional[int] = None, message: Optional[str] = None,
                        success_count: Optional[int] = None, fail_count: Optional[int] = None, **kwargs):
        with self._lock:
            if progress is not None:
                self.progress = max(0, min(100, progress))
            if total is not None:
                self.total = total
            if message is not None:
                self.message = message
            if success_count is not None:
                self.success_count = success_count
            if fail_count is not None:
                self.fail_count = fail_count
            for k, v in kwargs.items():
                self.artifacts[k] = v

        self.log(f"Progress {self.progress}% - {self.message}")
        self._persist()

    def add_error(self, error: str):
        with self._lock:
            self.errors.append(error)
            self.fail_count += 1
        self.log(error, level="ERROR")
        self._persist()

    def set_result_file(self, file_path: str):
        with self._lock:
            self.result_file = file_path
        self._persist()

    def is_canceled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self):
        self.cancel_event.set()
        self.status = "canceled"
        self.message = "Job canceled by operator"
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.log("Job cancellation requested by user", level="WARN")
        self._persist()

    def _persist(self):
        try:
            conn = get_db_connection()
            conn.execute(
                """
                INSERT INTO jobs (id, module, action, status, progress, total, success_count, fail_count,
                                 message, errors, result_file, created_at, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    progress = excluded.progress,
                    total = excluded.total,
                    success_count = excluded.success_count,
                    fail_count = excluded.fail_count,
                    message = excluded.message,
                    errors = excluded.errors,
                    result_file = excluded.result_file,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at
                """,
                (
                    self.job_id, self.module, self.action, self.status, self.progress, self.total,
                    self.success_count, self.fail_count, self.message, json.dumps(self.errors),
                    self.result_file, self.created_at, self.started_at, self.completed_at
                )
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to persist job {self.job_id}: {e}")

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "id": self.job_id,
                "module": self.module,
                "action": self.action,
                "status": self.status,
                "progress": self.progress,
                "total": self.total,
                "success_count": self.success_count,
                "fail_count": self.fail_count,
                "message": self.message,
                "errors": list(self.errors),
                "result_file": self.result_file,
                "artifacts": dict(self.artifacts),
                "meta": dict(self.meta),
                "result": dict(self.artifacts),
                "created_at": self.created_at,
                "started_at": self.started_at,
                "completed_at": self.completed_at
            }


class JobEngine:
    def __init__(self):
        self.jobs: Dict[str, JobContext] = {}
        self._lock = threading.Lock()
        self._cleanup_stale_jobs_on_startup()

    def _cleanup_stale_jobs_on_startup(self):
        try:
            from backend.core.database import init_db
            init_db()
            conn = get_db_connection()
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    message = 'Interrupted: service restarted',
                    completed_at = ?
                WHERE status IN ('running', 'pending')
                """,
                (now,),
            )
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            if affected > 0:
                logger.info(f"Marked {affected} interrupted stale job(s) as failed on startup.")
        except Exception as e:
            logger.warning(f"Could not perform startup cleanup of stale jobs: {e}")


    def submit_job(self, *args, **kwargs):
        job_type = kwargs.pop("job_type", None) or kwargs.pop("action", None) or (args[0] if len(args) > 0 else "general")
        description = kwargs.pop("description", None) or kwargs.pop("title", None) or (args[1] if len(args) > 1 else job_type)
        worker_fn = kwargs.pop("worker_fn", None) or kwargs.pop("worker_func", None) or (args[2] if len(args) > 2 else None)
        module = kwargs.pop("module", "data_management")
        worker_args = kwargs.pop("worker_args", None)
        _ = kwargs.pop("user_id", None)

        call_kwargs = worker_args if isinstance(worker_args, dict) else kwargs

        class _JobRef(str):
            @property
            def job_id(self):
                return str(self)

        def target(ctx: JobContext):
            if worker_fn:
                return worker_fn(ctx, **call_kwargs)

        jid = self.start_job(module=module, action=job_type, target=target)
        return _JobRef(jid)

    def start_job(self, module: str, action: str, target: Callable[[JobContext], None]) -> str:
        job_id = str(uuid.uuid4())[:8]
        ctx = JobContext(job_id=job_id, module=module, action=action)
        with self._lock:
            self.jobs[job_id] = ctx
        ctx._persist()

        def runner():
            ctx.started_at = datetime.now(timezone.utc).isoformat()
            ctx.status = "running"
            ctx.log(f"Started job {job_id} ({module}: {action})")
            ctx._persist()
            try:
                ret = target(ctx)
                if isinstance(ret, dict):
                    for k, v in ret.items():
                        if k not in ctx.artifacts and v is not None:
                            ctx.artifacts[k] = v
                if "counters" in ctx.meta and "counters" not in ctx.artifacts:
                    ctx.artifacts["counters"] = ctx.meta["counters"]
                elif "counters" in ctx.artifacts and "counters" not in ctx.meta:
                    ctx.meta["counters"] = ctx.artifacts["counters"]

                if not ctx.is_canceled() and ctx.status != "failed":
                    ctx.status = "completed"
                    ctx.progress = 100
                    if not ctx.message or ctx.message == "Processing...":
                        ctx.message = "Job finished successfully"
                    if not ctx.result_file and "output_file" in ctx.artifacts:
                        ctx.result_file = str(ctx.artifacts["output_file"])
                    ctx.log("Job finished successfully.")
            except Exception as ex:
                ctx.status = "failed"
                ctx.message = f"Execution error: {str(ex)}"
                ctx.add_error(f"Unhandled exception: {str(ex)}")
                ctx.log(f"Execution aborted: {ex}", level="ERROR")
            finally:
                ctx.completed_at = datetime.now(timezone.utc).isoformat()
                ctx._persist()

        thread = threading.Thread(target=runner, name=f"job-{job_id}", daemon=True)
        thread.start()
        return job_id

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if job_id in self.jobs:
                return self.jobs[job_id].to_dict()

        conn = get_db_connection()
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["errors"] = json.loads(d.get("errors") or "[]")
            return d
        return None

    def list_jobs(self, limit: int = 50, module: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        query = "SELECT * FROM jobs"
        params = []
        if module:
            query += " WHERE module = ?"
            params.append(module)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()

        result = []
        for r in rows:
            d = dict(r)
            d["errors"] = json.loads(d.get("errors") or "[]")
            result.append(d)
        return result

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id].cancel()
                return True
        conn = get_db_connection()
        conn.execute("UPDATE jobs SET status = 'canceled', message = 'Canceled' WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        return False

    def stream_job_events(self, job_id: str) -> Generator[str, None, None]:
        with self._lock:
            ctx = self.jobs.get(job_id)

        if not ctx:
            data = self.get_job(job_id)
            if data:
                yield f"event: status\ndata: {json.dumps(data)}\n\n"
                yield f"data: {json.dumps({'type': 'state', 'data': data})}\n\n"
            return

        last_progress = -1
        last_status = ""
        while True:
            while not ctx.log_queue.empty():
                try:
                    log_item = ctx.log_queue.get_nowait()
                    line = log_item.get('text', '') if isinstance(log_item, dict) else str(log_item)
                    yield f"event: log\ndata: {json.dumps({'line': line, 'item': log_item})}\n\n"
                    yield f"data: {json.dumps({'type': 'log', 'data': log_item})}\n\n"
                except queue.Empty:
                    break

            current_progress = ctx.progress
            current_status = ctx.status
            if current_progress != last_progress or current_status != last_status:
                last_progress = current_progress
                last_status = current_status
                state_data = ctx.to_dict()
                yield f"event: progress\ndata: {json.dumps({'progress': current_progress, 'total': ctx.total, 'message': ctx.message})}\n\n"
                yield f"event: status\ndata: {json.dumps(state_data)}\n\n"
                yield f"data: {json.dumps({'type': 'state', 'data': state_data})}\n\n"

            if ctx.status in ("completed", "failed", "canceled"):
                while not ctx.log_queue.empty():
                    try:
                        log_item = ctx.log_queue.get_nowait()
                        line = log_item.get('text', '') if isinstance(log_item, dict) else str(log_item)
                        yield f"event: log\ndata: {json.dumps({'line': line, 'item': log_item})}\n\n"
                        yield f"data: {json.dumps({'type': 'log', 'data': log_item})}\n\n"
                    except queue.Empty:
                        break
                state_data = ctx.to_dict()
                yield f"event: status\ndata: {json.dumps(state_data)}\n\n"
                yield f"data: {json.dumps({'type': 'state', 'data': state_data})}\n\n"
                break

            time.sleep(0.2)

job_engine = JobEngine()

