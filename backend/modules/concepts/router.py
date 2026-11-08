"""Concept and Form Management API Router (Module 4: CM-01 through CM-15)."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.core.jobs.engine import job_engine
from backend.routers.auth import get_current_user

from backend.modules.concepts.service import (
    get_openmrs_client,
    run_bahmni_convert_worker,
    run_bulk_folder_import_worker,
    run_concept_import_worker,
    run_dhis2_metadata_convert_worker,
    run_export_all_worker,
    run_export_form_concepts_worker,
    run_export_set_worker,
    run_generate_enhanced_schemas_worker,
    run_generate_schemas_worker,
    run_import_form_schemas_worker,
    run_legacy21_bulk_import_worker,
    run_legacy21_convert_worker,
    run_legacy21_export_worker,
    run_merge_schemas_worker,
)
from backend.modules.concepts.openmrs_importer import check_concept_classes
from backend.modules.concepts.openmrs_set_exporter import search_concept_sets
from backend.modules.concepts.dhis2_metadata_converter import extract_programs_from_file

router = APIRouter(prefix="/api/concepts", tags=["Concepts & Form Tools"])


# ==============================================================================
# File Upload Endpoint
# ==============================================================================
@router.post("/upload")
async def upload_concept_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    dest = settings.uploads_dir / safe_name

    try:
        if dest.exists():
            dest.unlink(missing_ok=True)
    except Exception:
        dest = settings.uploads_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"

    try:
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception:
        dest = settings.uploads_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    return {
        "status": "success",
        "filename": file.filename,
        "filepath": str(dest),
        "size": dest.stat().st_size,
    }


@router.post("/upload-folder")
async def upload_concept_folder(
    folder_name: str = Form("uploaded_folder"),
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    safe_folder = Path(folder_name).name or "uploaded_folder"
    target_dir = settings.uploads_dir / safe_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for f in files:
        raw_name = f.filename or "file"
        parts = [p for p in Path(raw_name).parts if p not in ("..", "/", "\\")]
        if parts:
            if parts[0].lower() == safe_folder.lower() and len(parts) > 1:
                parts = parts[1:]
            dest = target_dir.joinpath(*parts)
        else:
            dest = target_dir / Path(raw_name).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
        saved_files.append(str(dest))

    return {
        "status": "success",
        "folder_name": safe_folder,
        "folder_path": str(target_dir),
        "total_files": len(saved_files),
        "files": saved_files,
    }


# ==============================================================================
# CM-01: Bahmni CSV to Concept JSON Converter
# ==============================================================================
class BahmniConvertRequest(BaseModel):
    concepts_csv: str
    sets_csv: Optional[str] = None
    output_dir: Optional[str] = None


@router.post("/bahmni-convert")
@router.post("/convert-bahmni")
async def bahmni_convert(
    req: BahmniConvertRequest,
    current_user: dict = Depends(get_current_user),
):
    if not req.concepts_csv or not Path(req.concepts_csv).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Bahmni concepts CSV file not found on server: {req.concepts_csv or '(none provided)'}. Please select or upload the concepts CSV file first."
        )
    if req.sets_csv and not Path(req.sets_csv).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Bahmni concept sets CSV file not found on server: {req.sets_csv}."
        )
    job_id = job_engine.start_job(
        module="concepts",
        action="bahmni_convert",
        target=lambda ctx: run_bahmni_convert_worker(
            ctx,
            concepts_csv=req.concepts_csv,
            sets_csv=req.sets_csv,
            output_dir=req.output_dir,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-02: OpenMRS 3.x Concept & Set Importer
# ==============================================================================
class CheckClassesRequest(BaseModel):
    concepts_file: str
    sets_file: Optional[str] = None
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/check-classes")
async def check_classes(
    req: CheckClassesRequest,
    current_user: dict = Depends(get_current_user),
):
    client = get_openmrs_client(req.base_url, req.username, req.password)
    with open(req.concepts_file, encoding="utf-8") as f:
        concepts = json.load(f)
    concept_sets = []
    if req.sets_file and Path(req.sets_file).is_file():
        with open(req.sets_file, encoding="utf-8") as f:
            concept_sets = json.load(f)

    res = check_concept_classes(client, concepts, concept_sets)
    return res


class ConceptImportRequest(BaseModel):
    concepts_file: str
    sets_file: Optional[str] = None
    dry_run: bool = True
    output_dir: Optional[str] = None
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/import")
async def import_concepts(
    req: ConceptImportRequest,
    current_user: dict = Depends(get_current_user),
):
    if not req.concepts_file or not Path(req.concepts_file).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Concepts JSON file not found on server: {req.concepts_file or '(none provided)'}. Please select or upload the file first."
        )
    if req.sets_file and not Path(req.sets_file).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Concept sets JSON file not found on server: {req.sets_file}."
        )
    job_id = job_engine.start_job(
        module="concepts",
        action="concept_import",
        target=lambda ctx: run_concept_import_worker(
            ctx,
            concepts_file=req.concepts_file,
            sets_file=req.sets_file,
            dry_run=req.dry_run,
            output_dir=req.output_dir,
            base_url=req.base_url,
            username=req.username,
            password=req.password,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-03: Export Concept Set from Live OpenMRS 3.x
# ==============================================================================
class SearchSetsRequest(BaseModel):
    term: str
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/search-sets")
async def search_sets(
    req: SearchSetsRequest,
    current_user: dict = Depends(get_current_user),
):
    client = get_openmrs_client(req.base_url, req.username, req.password)
    results = search_concept_sets(client, req.term)
    return {
        "results": [
            {
                "uuid": c["uuid"],
                "display": c.get("display") or (c.get("names", [{}])[0].get("name", "") if c.get("names") else c.get("uuid", "")),
                "concept_class": (c.get("conceptClass") or {}).get("display", "Set"),
                "members_count": len(c.get("setMembers", [])) if c.get("setMembers") is not None else 0,
            }
            for c in results
        ]
    }


class ExportSetRequest(BaseModel):
    root_uuid: Optional[str] = None
    concept_set_uuid: Optional[str] = None
    concept_set_name: Optional[str] = None
    name: Optional[str] = None
    term: Optional[str] = None
    output_dir: Optional[str] = None
    dry_run: bool = False
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/export-set")
async def export_set(
    req: ExportSetRequest,
    current_user: dict = Depends(get_current_user),
):
    target = (req.concept_set_name or req.name or req.term or req.root_uuid or req.concept_set_uuid or "").strip()
    if not target:
        raise HTTPException(
            status_code=400,
            detail="Concept Set Name or UUID is required. Please provide a concept set name or UUID to export."
        )
    job_id = job_engine.start_job(
        module="concepts",
        action="export_concept_set",
        target=lambda ctx: run_export_set_worker(
            ctx,
            root_uuid=target,
            output_dir=req.output_dir,
            dry_run=req.dry_run,
            base_url=req.base_url,
            username=req.username,
            password=req.password,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-04: DHIS2 Metadata/Excel to Concept Folders
# ==============================================================================
class ExtractProgramsRequest(BaseModel):
    file_path: str


@router.post("/extract-programs")
async def extract_programs_endpoint(
    req: ExtractProgramsRequest,
    current_user: dict = Depends(get_current_user),
):
    path = Path(req.file_path)
    if not path.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"File not found on server: {req.file_path}. Please upload or select a valid file."
        )
    try:
        programs = extract_programs_from_file(path)
        return {
            "status": "ok",
            "file_path": str(path),
            "file_name": path.name,
            "programs": programs,
            "count": len(programs),
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract programs from {path.name}: {str(e)}"
        )


class Dhis2ToConceptsRequest(BaseModel):
    source_type: Optional[str] = "json"  # "json" or "dictionary" / "csv"
    file_path: Optional[str] = None
    excel_paths: Optional[Any] = None
    json_path: Optional[str] = None
    selected_program_ids: Optional[List[str]] = None
    output_dir: Optional[str] = None
    dry_run: bool = False


@router.post("/dhis2-to-concepts")
@router.post("/convert-dhis2")
async def dhis2_to_concepts(
    req: Dhis2ToConceptsRequest,
    current_user: dict = Depends(get_current_user),
):
    json_file = req.json_path
    excel_list = None

    if req.file_path:
        p = Path(req.file_path.strip())
        if req.source_type == "json" or p.suffix.lower() == ".json":
            json_file = str(p)
        else:
            excel_list = [str(p)]

    if req.excel_paths and not excel_list:
        if isinstance(req.excel_paths, list):
            excel_list = [str(p).strip() for p in req.excel_paths if str(p).strip()]
        elif isinstance(req.excel_paths, str):
            excel_list = [p.strip() for p in req.excel_paths.split(",") if p.strip()]

    if not json_file and not excel_list:
        raise HTTPException(
            status_code=400,
            detail="At least one DHIS2 metadata JSON file or Data Dictionary CSV/Excel file must be provided."
        )
    if json_file and not Path(json_file).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"DHIS2 metadata JSON file not found: {json_file}."
        )
    if excel_list:
        for ep in excel_list:
            if not Path(ep).is_file():
                raise HTTPException(
                    status_code=400,
                    detail=f"Data dictionary file not found on server: {ep}."
                )

    job_id = job_engine.start_job(
        module="concepts",
        action="dhis2_to_concepts",
        target=lambda ctx: run_dhis2_metadata_convert_worker(
            ctx,
            excel_paths=excel_list,
            json_path=json_file,
            selected_program_ids=req.selected_program_ids,
            output_dir=req.output_dir,
            dry_run=req.dry_run,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-05: Bulk Import Concepts from Program Folders
# ==============================================================================
class BulkFolderImportRequest(BaseModel):
    program_dir: Optional[str] = None
    folder_path: Optional[str] = None
    dry_run: bool = True
    output_dir: Optional[str] = None
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.get("/concept-directories")
async def get_concept_directories_endpoint(current_user: dict = Depends(get_current_user)):
    """List all detected concept program directories containing concept JSON files."""
    from backend.modules.concepts.bulk_folder_importer import get_available_concept_directories
    return {"directories": get_available_concept_directories()}


@router.post("/scan-bulk-folder")
async def scan_bulk_folder_endpoint(
    req: BulkFolderImportRequest,
    current_user: dict = Depends(get_current_user),
):
    target_dir_raw = (req.program_dir or req.folder_path or "").strip()
    if not target_dir_raw:
        raise HTTPException(status_code=400, detail="Please select or provide a program directory path.")

    from backend.modules.concepts.bulk_folder_importer import resolve_concept_directory, scan_folder
    try:
        resolved_dir = resolve_concept_directory(target_dir_raw)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    steps = scan_folder(resolved_dir)
    total_c = sum(len(s["concepts"]) for s in steps)
    total_s = sum(len(s["concept_sets"]) for s in steps)
    preview = [
        {
            "rel_path": s["rel_path"],
            "concepts_count": len(s["concepts"]),
            "sets_count": len(s["concept_sets"]),
        }
        for s in steps[:20]
    ]
    return {
        "status": "success",
        "resolved_path": str(resolved_dir),
        "folders_count": len(steps),
        "total_concepts": total_c,
        "total_sets": total_s,
        "preview": preview,
    }


@router.post("/bulk-folder-import")
@router.post("/bulk-import")
async def bulk_folder_import(
    req: BulkFolderImportRequest,
    current_user: dict = Depends(get_current_user),
):
    target_dir_raw = (req.program_dir or req.folder_path or "").strip()
    if not target_dir_raw:
        raise HTTPException(
            status_code=400,
            detail="Program directory path is required. Please select or browse a directory containing concept JSON files."
        )

    from backend.modules.concepts.bulk_folder_importer import resolve_concept_directory
    try:
        resolved_dir = resolve_concept_directory(target_dir_raw)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    job_id = job_engine.start_job(
        module="concepts",
        action="bulk_folder_import",
        target=lambda ctx: run_bulk_folder_import_worker(
            ctx,
            program_dir=str(resolved_dir),
            dry_run=req.dry_run,
            output_dir=req.output_dir,
            base_url=req.base_url,
            username=req.username,
            password=req.password,
        ),
    )
    return {
        "status": "submitted",
        "job_id": job_id,
        "resolved_path": str(resolved_dir),
    }


# ==============================================================================
# CM-06: DHIS2 Metadata to O3 Form Schemas
# ==============================================================================
class GenerateSchemasRequest(BaseModel):
    program_name: Optional[str] = "Program"
    metadata_path: Optional[str] = None
    metadata_file: Optional[str] = None
    concepts_path: Optional[str] = None
    concepts_file: Optional[str] = None
    output_dir: Optional[str] = None
    encounter_type: str = ""
    data_dictionary_path: Optional[str] = None
    dry_run: bool = False


@router.post("/generate-schemas")
async def generate_schemas(
    req: GenerateSchemasRequest,
    current_user: dict = Depends(get_current_user),
):
    prog_name = req.program_name or "Program"
    meta_p = (req.metadata_path or req.metadata_file or "").strip()
    conc_p = (req.concepts_path or req.concepts_file or "").strip()

    if not meta_p or not Path(meta_p).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"DHIS2 metadata JSON file not found: {meta_p or '(none provided)'}. Please select or upload the file first."
        )
    if not conc_p or not Path(conc_p).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"OpenMRS concepts CSV file not found: {conc_p or '(none provided)'}. Please select or upload the file first."
        )
    if req.data_dictionary_path and not Path(req.data_dictionary_path).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Data dictionary Excel file not found: {req.data_dictionary_path}."
        )

    job_id = job_engine.start_job(
        module="concepts",
        action="generate_schemas",
        target=lambda ctx: run_generate_schemas_worker(
            ctx,
            program_name=prog_name,
            metadata_path=meta_p,
            concepts_path=conc_p,
            output_dir=req.output_dir,
            encounter_type=req.encounter_type,
            data_dictionary_path=req.data_dictionary_path,
            dry_run=req.dry_run,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-07: Export All Concepts from OpenMRS 3.x
# ==============================================================================
class ExportAllConceptsRequest(BaseModel):
    export_format: Optional[str] = None
    format: Optional[str] = None
    output_dir: Optional[str] = None
    output_file: Optional[str] = None
    output_filename: Optional[str] = None
    dry_run: bool = False
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/export-all")
async def export_all(
    req: ExportAllConceptsRequest,
    current_user: dict = Depends(get_current_user),
):
    fmt = (req.export_format or req.format or "csv").strip().lower()
    if fmt not in ("csv", "json"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid export format: {fmt}. Must be 'csv' or 'json'."
        )

    out_file = (req.output_file or req.output_filename or "").strip() or None

    job_id = job_engine.start_job(
        module="concepts",
        action="export_all_concepts",
        target=lambda ctx: run_export_all_worker(
            ctx,
            export_format=fmt,
            output_dir=req.output_dir,
            output_filename=out_file,
            base_url=req.base_url,
            username=req.username,
            password=req.password,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-08: Advanced Form Schema Generator with Logic
# ==============================================================================
class GenerateEnhancedSchemasRequest(BaseModel):
    program_name: Optional[str] = "Program"
    metadata_path: Optional[str] = None
    metadata_file: Optional[str] = None
    concepts_path: Optional[str] = None
    concepts_file: Optional[str] = None
    output_dir: Optional[str] = None
    encounter_type: str = ""
    data_dictionary_path: Optional[str] = None
    dry_run: bool = False


@router.post("/generate-enhanced-schemas")
@router.post("/enhanced-generator")
async def generate_enhanced_schemas(
    req: GenerateEnhancedSchemasRequest,
    current_user: dict = Depends(get_current_user),
):
    prog_name = req.program_name or "Program"
    meta_p = (req.metadata_path or req.metadata_file or "").strip()
    conc_p = (req.concepts_path or req.concepts_file or "").strip()

    if not meta_p or not Path(meta_p).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"DHIS2 metadata JSON file not found: {meta_p or '(none provided)'}. Please select or upload the file first."
        )
    if not conc_p or not Path(conc_p).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"OpenMRS concepts CSV file not found: {conc_p or '(none provided)'}. Please select or upload the file first."
        )
    if req.data_dictionary_path and not Path(req.data_dictionary_path).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Data dictionary Excel file not found: {req.data_dictionary_path}."
        )

    job_id = job_engine.start_job(
        module="concepts",
        action="generate_enhanced_schemas",
        target=lambda ctx: run_generate_enhanced_schemas_worker(
            ctx,
            program_name=prog_name,
            metadata_path=meta_p,
            concepts_path=conc_p,
            output_dir=req.output_dir,
            encounter_type=req.encounter_type,
            data_dictionary_path=req.data_dictionary_path,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-09: Merge Form Schemas (Rules + Layout)
# ==============================================================================
class MergeSchemasRequest(BaseModel):
    base_dir: str
    fix_dir: Optional[str] = None
    source_dir: Optional[str] = None
    adjusted_dir: Optional[str] = None
    output_dir: Optional[str] = None
    out_dir: Optional[str] = None
    dry_run: bool = False


@router.post("/merge-schemas")
async def merge_schemas(
    req: MergeSchemasRequest,
    current_user: dict = Depends(get_current_user),
):
    target_fix = (req.fix_dir or req.source_dir or req.adjusted_dir or "").strip()
    if not req.base_dir or not Path(req.base_dir).is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Base schemas directory not found: {req.base_dir or '(none provided)'}."
        )
    if not target_fix or not Path(target_fix).is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Adjusted / Fixed schemas directory not found: {target_fix or '(none provided)'}."
        )

    out_d = req.output_dir or req.out_dir or None
    job_id = job_engine.start_job(
        module="concepts",
        action="merge_schemas",
        target=lambda ctx: run_merge_schemas_worker(
            ctx,
            base_dir=req.base_dir,
            fix_dir=target_fix,
            output_dir=out_d,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-09: Export Form Concepts (JSON) from OpenMRS 3.x
# ==============================================================================
class ExportFormConceptsRequest(BaseModel):
    forms_dir: str
    output_dir: Optional[str] = None
    dry_run: bool = False
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/export-form-concepts")
async def export_form_concepts_endpoint(
    req: ExportFormConceptsRequest,
    current_user: dict = Depends(get_current_user),
):
    if not req.forms_dir or not Path(req.forms_dir).is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Forms directory not found on server: {req.forms_dir or '(none provided)'}."
        )

    job_id = job_engine.start_job(
        module="concepts",
        action="export_form_concepts",
        target=lambda ctx: run_export_form_concepts_worker(
            ctx,
            forms_dir=req.forms_dir,
            output_dir=req.output_dir,
            base_url=req.base_url,
            username=req.username,
            password=req.password,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-10: Batch Import Form Schemas to OpenMRS 3.x
# ==============================================================================
class ImportFormSchemasRequest(BaseModel):
    forms_dir: str
    dry_run: bool = False
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/import-schemas")
async def import_form_schemas_endpoint(
    req: ImportFormSchemasRequest,
    current_user: dict = Depends(get_current_user),
):
    target_path = Path(req.forms_dir) if req.forms_dir else None
    if not target_path or not target_path.exists():
        fname = Path(req.forms_dir).name if req.forms_dir else ""
        cand_upload = settings.uploads_dir / fname
        cand_schema_local = Path(settings.DATA_DIR) / "schemas" / fname
        cand_schema_docker = Path("/data/schemas") / fname
        if fname and cand_upload.exists():
            req.forms_dir = str(cand_upload)
        elif fname and cand_schema_local.exists():
            req.forms_dir = str(cand_schema_local)
        elif fname and cand_schema_docker.exists():
            req.forms_dir = str(cand_schema_docker)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Forms directory or file not found on server: {req.forms_dir or '(none provided)'}."
            )

    job_id = job_engine.start_job(
        module="concepts",
        action="import_form_schemas",
        target=lambda ctx: run_import_form_schemas_worker(
            ctx,
            forms_dir=req.forms_dir,
            dry_run=req.dry_run,
            base_url=req.base_url,
            username=req.username,
            password=req.password,
        ),
    )
    return {"status": "submitted", "job_id": job_id}



# ==============================================================================
# CM-11: OpenMRS 2.1 Concept Exporter (Legacy)
# ==============================================================================
class Legacy21ExportRequest(BaseModel):
    output_dir: Optional[str] = None
    filename: Optional[str] = "concepts.csv"
    server_type: Optional[str] = "bahmni"
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/legacy-21/export")
@router.post("/legacy-export")
async def legacy21_export(
    req: Legacy21ExportRequest,
    current_user: dict = Depends(get_current_user),
):
    job_id = job_engine.start_job(
        module="concepts",
        action="legacy21_export",
        target=lambda ctx: run_legacy21_export_worker(
            ctx,
            output_dir=req.output_dir,
            filename=req.filename,
            server_type=req.server_type,
            base_url=req.base_url,
            username=req.username,
            password=req.password,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-12: OpenMRS 2.1 DHIS2 Concept Converter (Legacy)
# ==============================================================================
class Legacy21ConvertRequest(BaseModel):
    input_file: str
    parent_folder: str = "MID"
    output_dir: Optional[str] = None


@router.post("/legacy-21/dhis2-convert")
@router.post("/legacy-convert")
async def legacy21_convert(
    req: Legacy21ConvertRequest,
    current_user: dict = Depends(get_current_user),
):
    job_id = job_engine.start_job(
        module="concepts",
        action="legacy21_convert",
        target=lambda ctx: run_legacy21_convert_worker(
            ctx,
            input_file=req.input_file,
            parent_folder=req.parent_folder,
            output_dir=req.output_dir,
        ),
    )
    return {"status": "submitted", "job_id": job_id}


# ==============================================================================
# CM-13: OpenMRS 2.1 / Bahmni Bulk Concept Importer (Legacy)
# ==============================================================================
class Legacy21BulkImportRequest(BaseModel):
    export_file: Optional[str] = None
    folder: Optional[str] = None
    mode: str = "api"
    apply: bool = False
    server_type: Optional[str] = "bahmni"
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    output_dir: Optional[str] = None
    strict_set_check: bool = False
    check_only: bool = False
    delay_ms: int = 200
    batch_size: int = 100


@router.post("/legacy-21/bulk-import")
@router.post("/legacy-bulk-import")
async def legacy21_bulk_import(
    req: Legacy21BulkImportRequest,
    current_user: dict = Depends(get_current_user),
):
    if not req.folder and not req.check_only:
        raise HTTPException(
            status_code=400,
            detail="Concept folder path or zip archive is required.",
        )

    job_id = job_engine.start_job(
        module="concepts",
        action="legacy21_bulk_import",
        target=lambda ctx: run_legacy21_bulk_import_worker(
            ctx,
            export_file=req.export_file or "",
            folder=req.folder or "",
            mode=req.mode or "api",
            apply=req.apply,
            server_type=req.server_type or "bahmni",
            base_url=req.base_url,
            username=req.username,
            password=req.password,
            output_dir=req.output_dir,
            strict_set_check=req.strict_set_check,
            check_only=req.check_only,
            delay_ms=req.delay_ms or 200,
            batch_size=req.batch_size or 100,
        ),
    )
    return {"status": "submitted", "job_id": job_id}



# ==============================================================================
# Concept Artifact Download
# ==============================================================================
@router.get("/download/{filename:path}")
async def download_concept_artifact(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    from backend.core.storage import resolve_export_file, build_file_response

    file_path = resolve_export_file(filename)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")

    return build_file_response(file_path)

