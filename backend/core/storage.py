import os
import mimetypes
from pathlib import Path
from typing import Optional
from fastapi.responses import FileResponse
from backend.core.config import settings


def get_media_type(filename: str) -> str:
    """Return appropriate MIME content type for generated artifacts."""
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lower.endswith(".xls"):
        return "application/vnd.ms-excel"
    if lower.endswith(".csv"):
        return "text/csv; charset=utf-8"
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".zip"):
        return "application/zip"
    if lower.endswith(".txt") or lower.endswith(".log"):
        return "text/plain; charset=utf-8"
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def resolve_output_dir(output_dir: Optional[str], default_dir: Optional[Path] = None) -> Path:
    """
    Safely resolve a server output directory for export jobs.
    If output_dir is omitted or represents a client-side local directory indicator
    (e.g. '[Local Folder] MyFolder'), this safely defaults to settings.exports_dir.
    Relative paths are placed inside settings.exports_dir.
    """
    base = (default_dir or settings.exports_dir).resolve()
    if not output_dir or not str(output_dir).strip():
        base.mkdir(parents=True, exist_ok=True)
        return base

    clean = str(output_dir).strip()
    if clean.startswith("[Local Folder]") or clean.startswith("[local folder]"):
        base.mkdir(parents=True, exist_ok=True)
        return base

    target = Path(clean)
    if not target.is_absolute():
        target = base / target
    target.mkdir(parents=True, exist_ok=True)
    return target


def resolve_export_file(filename: str, include_uploads: bool = False) -> Optional[Path]:
    """
    Safely resolve a requested artifact path to an existing file within settings.exports_dir
    (or optionally settings.uploads_dir). Prevents path traversal and searches subfolders.
    """
    if not filename:
        return None

    exports_dir = settings.exports_dir.resolve()

    # Strip client local folder tags if present
    clean_rel = filename.replace("\\", "/").strip().lstrip("/")
    if clean_rel.startswith("[Local Folder]"):
        clean_rel = clean_rel.split("/", 1)[-1].strip() if "/" in clean_rel else clean_rel

    # 1. Check if an absolute path under exports_dir was passed
    try:
        p = Path(filename).resolve()
        if p.is_file():
            p.relative_to(exports_dir)
            return p
    except (ValueError, Exception):
        pass

    # 2. Check direct relative path under exports_dir (e.g. 'Adare mapping/xx.xlsx')
    try:
        candidate = (exports_dir / clean_rel).resolve()
        candidate.relative_to(exports_dir)
        if candidate.is_file():
            return candidate
    except (ValueError, Exception):
        pass

    # 3. Check base filename directly under exports_dir
    base_name = Path(clean_rel).name
    direct = exports_dir / base_name
    if direct.is_file():
        return direct

    # 4. Search recursively inside exports_dir for base_name
    matches = [m for m in exports_dir.rglob(base_name) if m.is_file()]
    if matches:
        matches.sort(key=lambda m: m.stat().st_mtime, reverse=True)
        return matches[0]

    # 4b. If base_name lacked .xlsx, also check base_name + ".xlsx"
    if not base_name.lower().endswith(".xlsx"):
        xlsx_name = f"{base_name}.xlsx"
        direct_xlsx = exports_dir / xlsx_name
        if direct_xlsx.is_file():
            return direct_xlsx
        xlsx_matches = [m for m in exports_dir.rglob(xlsx_name) if m.is_file()]
        if xlsx_matches:
            xlsx_matches.sort(key=lambda m: m.stat().st_mtime, reverse=True)
            return xlsx_matches[0]

    # 5. Check if file exists under any [Local Folder] folder created in /app or working dir
    try:
        search_roots = [r for r in [Path("/app"), Path.cwd()] if r.exists()]
        for s_root in search_roots:
            app_matches = [
                m for m in s_root.glob(f"**/{base_name}")
                if m.is_file() and not m.name.startswith(".") and ".git" not in str(m)
            ]
            if app_matches:
                app_matches.sort(key=lambda m: m.stat().st_mtime, reverse=True)
                return app_matches[0]
    except Exception:
        pass

    # 6. Optionally fallback to uploads_dir
    if include_uploads:
        uploads_dir = settings.uploads_dir.resolve()
        try:
            candidate = (uploads_dir / clean_rel).resolve()
            candidate.relative_to(uploads_dir)
            if candidate.is_file():
                return candidate
        except (ValueError, Exception):
            pass

        direct_upload = uploads_dir / base_name
        if direct_upload.is_file():
            return direct_upload

        upload_matches = [m for m in uploads_dir.rglob(base_name) if m.is_file()]
        if upload_matches:
            upload_matches.sort(key=lambda m: m.stat().st_mtime, reverse=True)
            return upload_matches[0]

    return None


def build_file_response(file_path: Path, download_name: Optional[str] = None) -> FileResponse:
    """Build a robust FileResponse with explicit attachment disposition and correct MIME type."""
    target_name = download_name or file_path.name
    # If the file on disk is an openxml archive (magic bytes PK\x03\x04), ensure .xlsx extension:
    try:
        if file_path.is_file():
            with open(file_path, "rb") as f:
                magic = f.read(4)
            if magic == b"PK\x03\x04" and not target_name.lower().endswith((".xlsx", ".xlsm", ".zip")):
                target_name = f"{target_name}.xlsx"
    except Exception:
        pass

    media_type = get_media_type(target_name)
    return FileResponse(
        path=str(file_path),
        filename=target_name,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{target_name}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
