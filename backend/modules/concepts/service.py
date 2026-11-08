"""Concept and Form Management Service Layer.

Orchestrates asynchronous jobs and worker functions for:
- Bahmni Concept Conversion
- OpenMRS 3.x Import & Export
- DHIS2 Metadata Conversion & Bulk Folder Import
- Form Schema Generation (Basic & Enhanced with rules)
- Form Schema Merging
- Form Concept Export & Schema Import
- OpenMRS 2.1 Legacy Tools
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.config import settings
from backend.core.database import get_server_connection
from backend.core.connections import normalize_container_url
from backend.core.jobs.engine import JobContext

from backend.modules.concepts.bahmni_converter import run_bahmni_conversion
from backend.modules.concepts.openmrs_importer import (
    OpenMRSClient,
    run_concept_import,
    check_concept_classes,
)
from backend.modules.concepts.openmrs_set_exporter import (
    search_concept_sets,
    export_concept_set,
)
from backend.modules.concepts.dhis2_metadata_converter import (
    run_metadata_conversion,
    extract_programs_from_file,
)
from backend.modules.concepts.bulk_folder_importer import run_bulk_folder_import
from backend.modules.concepts.form_schema_generator import (
    generate_forms_for_program,
    generate_form_for_stage,
    read_concepts,
    read_xlsx_rows,
    safe_program_name,
)
from backend.modules.concepts.openmrs_concept_exporter import export_all_concepts
from backend.modules.concepts.enhanced_form_generator import (
    run_enhanced_form_generation,
)
from backend.modules.concepts.merge_form_schemas import run_merge_forms
from backend.modules.concepts.export_form_concepts import export_form_concepts
from backend.modules.concepts.import_form_schemas import import_form_schemas
from backend.modules.concepts.legacy21_exporter import export_legacy21_concepts
from backend.modules.concepts.legacy21_converter import convert_dhis2_to_legacy21

logger = logging.getLogger("imnid.concepts")


def get_openmrs_client(
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> OpenMRSClient:
    if not base_url or not username or not password:
        conn = get_server_connection("openmrs")
        if conn:
            base_url = base_url or conn.get("base_url")
            username = username or conn.get("username")
            password = password or conn.get("secret")

    base_url = base_url or settings.OPENMRS_URL
    username = username or settings.OPENMRS_USERNAME
    password = password or settings.OPENMRS_PASSWORD

    return OpenMRSClient(base_url=base_url, username=username, password=password)


def zip_directory(source_dir: Path, zip_file_path: Path):
    with zipfile.ZipFile(zip_file_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(source_dir):
            for file in files:
                abs_path = Path(root) / file
                rel_path = abs_path.relative_to(source_dir)
                zipf.write(abs_path, rel_path)


# ==============================================================================
# Worker: Bahmni Concept Conversion
# ==============================================================================
def run_bahmni_convert_worker(
    ctx: JobContext,
    concepts_csv: str,
    sets_csv: Optional[str] = None,
    output_dir: Optional[str] = None,
):
    ctx.log(f"Starting Bahmni (CSV) to OpenMRS 3 (JSON) Conversion...")
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    target_out_dir = Path(output_dir) if output_dir else job_export_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)

    try:
        res = run_bahmni_conversion(
            concepts_csv=concepts_csv,
            sets_csv=sets_csv,
            out_dir=target_out_dir,
            log_fn=lambda msg: ctx.log(msg),
        )
        ctx.update_progress(
            progress=100,
            message=f"Converted {res['concepts_count']} concepts and {res['concept_sets_count']} sets.",
        )
        zip_path = settings.exports_dir / f"bahmni_concepts_{ctx.job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            if res.get("concepts_file") and Path(res["concepts_file"]).is_file():
                p = Path(res["concepts_file"])
                zipf.write(p, arcname=p.name)
            if res.get("concept_sets_file") and Path(res["concept_sets_file"]).is_file():
                p = Path(res["concept_sets_file"])
                zipf.write(p, arcname=p.name)

        ctx.set_result_file(str(zip_path))
        ctx.artifacts["concepts_count"] = res["concepts_count"]
        ctx.artifacts["concept_sets_count"] = res["concept_sets_count"]
        ctx.artifacts["output_directory"] = str(target_out_dir)
        ctx.artifacts["concepts_file"] = res.get("concepts_file")
        ctx.artifacts["concept_sets_file"] = res.get("concept_sets_file")
        ctx.log(f"Conversion complete. JSON files written to {target_out_dir}")
    except Exception as e:
        ctx.add_error(f"Bahmni conversion failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Bahmni conversion failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Concept Importer
# ==============================================================================
def run_concept_import_worker(
    ctx: JobContext,
    concepts_file: str,
    sets_file: Optional[str] = None,
    dry_run: bool = True,
    output_dir: Optional[str] = None,
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    ctx.log(f"Starting OpenMRS Concept Importer (dry_run={dry_run})...")
    client = get_openmrs_client(base_url, username, password)

    with open(concepts_file, encoding="utf-8") as f:
        concepts = json.load(f)
    concept_sets = []
    if sets_file and Path(sets_file).is_file():
        with open(sets_file, encoding="utf-8") as f:
            concept_sets = json.load(f)

    target_out_dir = Path(output_dir) if output_dir else settings.exports_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)
    report_path = target_out_dir / f"import_report_{ctx.job_id}.csv"

    def progress_callback(cur, tot, msg):
        pct = int((cur / max(1, tot)) * 100)
        ctx.update_progress(progress=pct, total=tot, message=msg)

    try:
        res = run_concept_import(
            client=client,
            concepts=concepts,
            concept_sets=concept_sets,
            dry_run=dry_run,
            log_fn=lambda msg: ctx.log(msg),
            progress_fn=progress_callback,
            is_canceled_fn=lambda: ctx.is_canceled(),
            out_report_path=report_path,
        )
        ctx.set_result_file(str(report_path))
        ctx.artifacts["created"] = res["created"]
        ctx.artifacts["reused"] = res["reused"]
        ctx.artifacts["failed"] = res["failed"]
        ctx.artifacts["output_report"] = str(report_path)
        ctx.update_progress(
            progress=100,
            message=f"Import completed: {res['created']} created, {res['reused']} reused, {res['failed']} failed.",
        )
    except Exception as e:
        ctx.add_error(f"Import failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Import failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Export Concept Set
# ==============================================================================
def run_export_set_worker(
    ctx: JobContext,
    root_uuid: str,
    output_dir: Optional[str] = None,
    dry_run: bool = False,
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    raw_target = (root_uuid or "").strip()
    ctx.log(f"Resolving concept set: '{raw_target}'...")
    client = get_openmrs_client(base_url, username, password)

    is_probable_uuid = len(raw_target) in (32, 36) and (" " not in raw_target)
    resolved_uuid = None
    root_display = raw_target

    if is_probable_uuid:
        try:
            r = client.session.get(
                client._url(f"/ws/rest/v1/concept/{raw_target}"),
                params={"v": "custom:(uuid,display,set,setMembers:(uuid,display))"},
                timeout=20,
            )
            if r.status_code == 200:
                cdata = r.json()
                resolved_uuid = cdata.get("uuid")
                root_display = cdata.get("display") or resolved_uuid
                ctx.log(f"Found concept set by UUID: '{root_display}' ({resolved_uuid})")
        except Exception:
            pass

    if not resolved_uuid:
        ctx.log(f"Searching OpenMRS for concept set by name: '{raw_target}'...")
        try:
            matches = search_concept_sets(client, raw_target)
        except Exception as e:
            matches = []
            ctx.log(f"Search warning: {str(e)}", level="WARNING")

        if matches:
            exact = next((m for m in matches if (m.get("display") or "").strip().lower() == raw_target.lower()), None)
            matched = exact or matches[0]
            resolved_uuid = matched.get("uuid")
            root_display = matched.get("display") or raw_target
            ctx.log(f"Found concept set: '{root_display}' (UUID: {resolved_uuid})")
        elif not is_probable_uuid:
            raise ValueError(
                f"No concept set found on OpenMRS matching name '{raw_target}'. Please check the name or search for concept sets."
            )
        else:
            resolved_uuid = raw_target

    if dry_run:
        ctx.log(f"[SIMULATION] Dry-run simulation for exporting concept set: '{root_display}' ({resolved_uuid})")
        try:
            r = client.session.get(
                client._url(f"/ws/rest/v1/concept/{resolved_uuid}"),
                params={"v": "full"},
                timeout=30,
            )
            r.raise_for_status()
            root_data = r.json()
            members = root_data.get("setMembers", [])
            concept_class = (root_data.get("conceptClass") or {}).get("display", "Set")
            ctx.log(f"[SIMULATION] Validated Concept Set: '{root_display}'")
            ctx.log(f"[SIMULATION] UUID: {resolved_uuid}")
            ctx.log(f"[SIMULATION] Concept Class: {concept_class}")
            ctx.log(f"[SIMULATION] Direct Members Count: {len(members)}")
            for idx, m in enumerate(members[:10], 1):
                ctx.log(f"  [{idx}] {m.get('display')} ({m.get('uuid')})")
            if len(members) > 10:
                ctx.log(f"  ... and {len(members) - 10} more members.")
            ctx.artifacts["dry_run"] = True
            ctx.artifacts["resolved_set_name"] = root_display
            ctx.artifacts["resolved_set_uuid"] = resolved_uuid
            ctx.artifacts["direct_members_count"] = len(members)
            ctx.update_progress(
                progress=100,
                message=f"[SIMULATION] Verified set '{root_display}' with {len(members)} member concepts. Simulation complete.",
            )
            return
        except Exception as e:
            raise ValueError(f"Simulation check failed for concept set '{root_display}' ({resolved_uuid}): {str(e)}")

    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    target_out_dir = Path(output_dir) if output_dir else job_export_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)

    try:
        res = export_concept_set(
            client=client,
            root_uuid=resolved_uuid,
            out_dir=target_out_dir,
            log_fn=lambda msg: ctx.log(msg),
            is_canceled_fn=lambda: ctx.is_canceled(),
        )

        # Name exported zip file directly after the concept set name
        import re
        clean_name = re.sub(r'[^\w\- ]', '_', root_display.strip()).strip()
        safe_name = re.sub(r'\s+', '_', clean_name)
        if not safe_name:
            safe_name = f"concept_set_{ctx.job_id}"
        zip_filename = f"{safe_name}.zip"
        zip_path = settings.exports_dir / zip_filename

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            if res.get("concepts_file") and Path(res["concepts_file"]).is_file():
                p = Path(res["concepts_file"])
                zipf.write(p, arcname=p.name)
            if res.get("concept_sets_file") and Path(res["concept_sets_file"]).is_file():
                p = Path(res["concept_sets_file"])
                zipf.write(p, arcname=p.name)

        if target_out_dir != settings.exports_dir:
            dest_zip = target_out_dir / zip_filename
            try:
                shutil.copy2(zip_path, dest_zip)
            except Exception as copy_err:
                ctx.log(f"Notice: could not copy zip to {dest_zip}: {copy_err}", level="WARNING")

        ctx.set_result_file(str(zip_path))
        ctx.artifacts["zip_name"] = zip_filename
        ctx.artifacts["concepts_count"] = res["concepts_count"]
        ctx.artifacts["concept_sets_count"] = res["concept_sets_count"]
        ctx.artifacts["output_directory"] = str(target_out_dir)
        ctx.update_progress(
            progress=100,
            message=f"Exported {res['concepts_count']} concepts and {res['concept_sets_count']} sets into '{zip_filename}'.",
        )
    except Exception as e:
        ctx.add_error(f"Export set failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Export set failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: DHIS2 Metadata Conversion
# ==============================================================================
def run_dhis2_metadata_convert_worker(
    ctx: JobContext,
    excel_paths: Optional[List[str]] = None,
    json_path: Optional[str] = None,
    selected_program_ids: Optional[List[str]] = None,
    output_dir: Optional[str] = None,
    dry_run: bool = False,
):
    ctx.log("Starting DHIS2 Metadata Conversion...")
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    target_out_dir = Path(output_dir) if output_dir else job_export_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        ctx.log("[SIMULATION] Dry-run simulation for DHIS2 conversion...")
        programs_found = []
        if json_path and Path(json_path).is_file():
            try:
                progs = extract_programs_from_file(json_path)
                if selected_program_ids:
                    progs = [p for p in progs if p["id"] in selected_program_ids or p["name"] in selected_program_ids]
                programs_found.extend(progs)
            except Exception as e:
                ctx.log(f"[SIMULATION] Error inspecting JSON: {e}", level="WARNING")
        if excel_paths:
            for ep in excel_paths:
                if Path(ep).is_file():
                    try:
                        progs = extract_programs_from_file(ep)
                        if selected_program_ids:
                            progs = [p for p in progs if p["id"] in selected_program_ids or p["name"] in selected_program_ids]
                        programs_found.extend(progs)
                    except Exception as e:
                        ctx.log(f"[SIMULATION] Error inspecting dictionary {ep}: {e}", level="WARNING")

        ctx.log(f"[SIMULATION] Validated {len(programs_found)} program(s) for conversion:")
        for idx, p in enumerate(programs_found, 1):
            ctx.log(f"  [{idx}] Program: {p['name']} (ID: {p['id']}, Stages: {p.get('stages_count', 'N/A')}, Elements: {p.get('elements_count', 'N/A')})")

        ctx.artifacts["dry_run"] = True
        ctx.artifacts["programs_count"] = len(programs_found)
        ctx.artifacts["programs"] = [p["name"] for p in programs_found]
        ctx.update_progress(
            progress=100,
            message=f"[SIMULATION] Verified {len(programs_found)} programs. Ready for conversion.",
        )
        return

    try:
        res = run_metadata_conversion(
            excel_paths=excel_paths,
            json_path=json_path,
            selected_program_ids=selected_program_ids,
            out_dir=target_out_dir,
            log_fn=lambda msg: ctx.log(msg),
        )

        import re
        zip_filename = f"dhis2_concept_folders_{ctx.job_id}.zip"
        if res.get("reports") and len(res["reports"]) == 1:
            pdir_str = res["reports"][0].get("program_dir", "")
            pname = Path(pdir_str).name if pdir_str else ""
            if pname:
                safe_name = re.sub(r'[^\w\- ]', '_', pname).strip()
                zip_filename = f"{safe_name}_concepts.zip"

        zip_path = settings.exports_dir / zip_filename
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for rep in res.get("reports", []):
                pdir_str = rep.get("program_dir")
                if pdir_str and Path(pdir_str).is_dir():
                    pdir = Path(pdir_str)
                    for root, _, files in os.walk(pdir):
                        for f in files:
                            abs_p = Path(root) / f
                            rel_p = abs_p.relative_to(target_out_dir)
                            zipf.write(abs_p, arcname=str(rel_p))

        if target_out_dir != settings.exports_dir:
            dest_zip = target_out_dir / zip_filename
            try:
                shutil.copy2(zip_path, dest_zip)
            except Exception:
                pass

        ctx.set_result_file(str(zip_path))
        ctx.artifacts["zip_name"] = zip_filename
        ctx.artifacts["programs_converted"] = res["programs_converted"]
        ctx.artifacts["output_directory"] = str(target_out_dir)
        ctx.update_progress(
            progress=100,
            message=f"Converted {res['programs_converted']} programs into '{zip_filename}'.",
        )
    except Exception as e:
        ctx.add_error(f"DHIS2 metadata conversion failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"DHIS2 metadata conversion failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Bulk Folder Import
# ==============================================================================
def run_bulk_folder_import_worker(
    ctx: JobContext,
    program_dir: str,
    dry_run: bool = True,
    output_dir: Optional[str] = None,
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    ctx.log(f"Starting Bulk Folder Import from {program_dir} (dry_run={dry_run})...")
    client = get_openmrs_client(base_url, username, password)
    target_out_dir = Path(output_dir) if output_dir else settings.exports_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)
    report_path = target_out_dir / f"bulk_import_report_{ctx.job_id}.csv"

    def progress_callback(cur, tot, msg):
        pct = int((cur / max(1, tot)) * 100)
        ctx.update_progress(progress=pct, total=tot, message=msg)

    try:
        res = run_bulk_folder_import(
            client=client,
            program_dir=program_dir,
            dry_run=dry_run,
            log_fn=lambda msg: ctx.log(msg),
            progress_fn=progress_callback,
            is_canceled_fn=lambda: ctx.is_canceled(),
            out_report_path=report_path,
        )
        ctx.set_result_file(str(report_path))
        ctx.artifacts.update(res)
        ctx.artifacts["output_report"] = str(report_path)
        ctx.update_progress(
            progress=100,
            message=f"Bulk import finished: {res.get('created', 0)} created, {res.get('reused', 0)} reused, {res.get('failed', 0)} failed.",
        )
    except Exception as e:
        ctx.add_error(f"Bulk folder import failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Bulk folder import failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Form Schema Generator (Basic)
# ==============================================================================
def run_generate_schemas_worker(
    ctx: JobContext,
    program_name: str,
    metadata_path: str,
    concepts_path: str,
    output_dir: Optional[str] = None,
    encounter_type: str = "",
    data_dictionary_path: Optional[str] = None,
    dry_run: bool = False,
):
    if dry_run:
        ctx.log(f"[DRY RUN] Simulating O3 Form Schema Generation for program: '{program_name}'")
        try:
            metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
            concepts = read_concepts(Path(concepts_path))
            ctx.log(f"[DRY RUN] Loaded metadata JSON and {len(concepts)} concepts from CSV.")

            program = next(
                (p for p in metadata.get("programs", []) if p.get("name") == program_name),
                None,
            )
            if not program:
                raise ValueError(f"Program not found in metadata: '{program_name}'")

            program_id = program["id"]
            stages = [
                s
                for s in metadata.get("programStages", [])
                if s.get("program", {}).get("id") == program_id
            ]
            if not stages:
                raise ValueError(f"No stages found for program: '{program_name}'")

            ctx.log(f"[DRY RUN] Found {len(stages)} stage(s) for program '{program_name}'.")

            excel_rows_by_stage = None
            if data_dictionary_path and Path(data_dictionary_path).is_file():
                ctx.log(f"[DRY RUN] Reading data dictionary: {Path(data_dictionary_path).name}")
                excel_rows = read_xlsx_rows(Path(data_dictionary_path))
                excel_rows_by_stage = {}
                current_stage = ""
                for row in excel_rows:
                    current_stage = row.get("Stage Name", "").strip() or current_stage
                    if current_stage:
                        excel_rows_by_stage.setdefault(current_stage, []).append(row)

            results = []
            for stage in stages:
                s_name = stage["name"]
                ctx.log(f"[DRY RUN] Simulating stage: {s_name}")
                res = generate_form_for_stage(
                    stage_name=s_name,
                    metadata=metadata,
                    concepts=concepts,
                    encounter_type=encounter_type,
                    excel_rows_by_stage=excel_rows_by_stage,
                )
                unresolved = [
                    row for row in res["report"] if row.get("review_required") == "yes"
                ]
                q_count = res.get("questions_count", 0)
                u_count = len(unresolved)
                results.append({
                    "stage_name": s_name,
                    "questions_count": q_count,
                    "unresolved_count": u_count,
                    "form_uuid": res["form_uuid"],
                })

            ctx.log(f"[DRY RUN] Simulation complete for {len(results)} form(s):")
            for r in results:
                ctx.log(
                    f"  {r['stage_name']}: {r['questions_count']} questions, "
                    f"{r['unresolved_count']} review-required"
                )

            ctx.artifacts["dry_run"] = True
            ctx.artifacts["forms_count"] = len(results)
            ctx.artifacts["stages_summary"] = results
            ctx.update_progress(
                progress=100,
                message=f"[DRY RUN] Verified {len(results)} form(s) for '{program_name}'. No files written.",
            )
        except Exception as e:
            ctx.add_error(f"[DRY RUN] Validation failed: {str(e)}")
            ctx.status = "failed"
            ctx.log(f"[DRY RUN] Validation failed: {str(e)}", level="ERROR")
        return

    ctx.log(f"Generating O3 Form Schemas for {program_name}...")
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    target_out_dir = Path(output_dir) if output_dir else job_export_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)

    try:
        results = generate_forms_for_program(
            program_name=program_name,
            metadata_path=Path(metadata_path),
            concepts_path=Path(concepts_path),
            output_dir=target_out_dir,
            encounter_type=encounter_type,
            data_dictionary_path=Path(data_dictionary_path)
            if data_dictionary_path
            else None,
            log_fn=lambda msg: ctx.log(msg),
        )
        prog_safe = safe_program_name(program_name)
        stage_dir = target_out_dir / prog_safe

        zip_path = settings.exports_dir / f"{prog_safe}_schemas_{ctx.job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            if stage_dir.is_dir():
                for root, _, files in os.walk(stage_dir):
                    for f in files:
                        abs_p = Path(root) / f
                        rel_p = abs_p.relative_to(target_out_dir)
                        zipf.write(abs_p, arcname=str(rel_p))

        ctx.set_result_file(str(zip_path))
        ctx.artifacts["forms_count"] = len(results)
        ctx.artifacts["output_directory"] = str(stage_dir)
        ctx.artifacts["download_url"] = f"/api/concepts/download/{zip_path.name}"
        ctx.artifacts["stages_summary"] = results

        ctx.log(f"Generated {len(results)} form(s) in: {stage_dir}")
        for r in results:
            ctx.log(
                f"  {r['stage_name']}: {r['questions_count']} questions, "
                f"{r['unresolved_count']} review-required"
            )

        ctx.update_progress(
            progress=100, message=f"Generated {len(results)} form schemas."
        )
    except Exception as e:
        ctx.add_error(f"Form schema generation failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Form schema generation failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Export All Concepts from 3.x
# ==============================================================================
def run_export_all_worker(
    ctx: JobContext,
    export_format: str = "csv",
    output_dir: Optional[str] = None,
    output_filename: Optional[str] = None,
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    fmt = (export_format or "csv").strip().lower()
    ctx.log(f"Exporting all concepts in {fmt.upper()} format...")
    client = get_openmrs_client(base_url, username, password)
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    target_out_dir = Path(output_dir) if output_dir else job_export_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)

    def progress_callback(cur, tot, msg):
        ctx.update_progress(total=tot, message=msg)

    try:
        res = export_all_concepts(
            client=client,
            out_dir=target_out_dir,
            export_format=fmt,
            output_filename=output_filename,
            log_fn=lambda msg: ctx.log(msg),
            progress_fn=progress_callback,
            is_canceled_fn=lambda: ctx.is_canceled(),
        )
        ctx.set_result_file(res["output_file"])
        ctx.artifacts["total_concepts"] = res["total_concepts"]
        ctx.artifacts["output_file"] = res["output_file"]
        ctx.artifacts["output_directory"] = str(target_out_dir)
        ctx.artifacts["export_format"] = res["export_format"]
        ctx.update_progress(
            progress=100,
            message=f"Exported {res['total_concepts']} concepts to {Path(res['output_file']).name} ({res['export_format'].upper()}).",
        )
    except Exception as e:
        ctx.add_error(f"Export all concepts failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Export all concepts failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Enhanced Form Schema Generator (With Rules)
# ==============================================================================
def run_generate_enhanced_schemas_worker(
    ctx: JobContext,
    program_name: str,
    metadata_path: str,
    concepts_path: str,
    output_dir: Optional[str] = None,
    encounter_type: str = "",
    data_dictionary_path: Optional[str] = None,
):
    ctx.log(f"Generating Enhanced Schemas with rules for {program_name}...")
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    target_out_dir = Path(output_dir) if output_dir else job_export_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)

    try:
        res = run_enhanced_form_generation(
            metadata_path=metadata_path,
            concepts_path=concepts_path,
            output_dir=target_out_dir,
            program_name=program_name,
            encounter_type=encounter_type,
            data_dictionary_path=data_dictionary_path,
            log_fn=lambda msg: ctx.log(msg),
        )
        stage_dir = Path(res["output_dir"])
        zip_path = settings.exports_dir / f"enhanced_schemas_{ctx.job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            if stage_dir.is_dir():
                for root, _, files in os.walk(stage_dir):
                    for f in files:
                        abs_p = Path(root) / f
                        rel_p = abs_p.relative_to(target_out_dir)
                        zipf.write(abs_p, arcname=str(rel_p))

        ctx.set_result_file(str(zip_path))
        ctx.artifacts.update(res["summary"])
        ctx.artifacts["output_directory"] = str(stage_dir)
        ctx.update_progress(
            progress=100,
            message=f"Generated {res['summary']['stages']} enhanced form schemas with {res['summary']['total_rules']} rules.",
        )
    except Exception as e:
        ctx.add_error(f"Enhanced form schema generation failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Enhanced form schema generation failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Merge Form Schemas
# ==============================================================================
def run_merge_schemas_worker(
    ctx: JobContext,
    base_dir: str,
    fix_dir: str,
    output_dir: Optional[str] = None,
):
    ctx.log(f"Merging form schemas: {base_dir} + {fix_dir}...")
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    target_out_dir = Path(output_dir) if output_dir else job_export_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)

    try:
        res = run_merge_forms(
            base_dir=base_dir,
            fix_dir=fix_dir,
            out_dir=target_out_dir,
            log_fn=lambda msg: ctx.log(msg),
        )
        zip_path = settings.exports_dir / f"merged_schemas_{ctx.job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(target_out_dir):
                for f in files:
                    if f.endswith(".json"):
                        abs_p = Path(root) / f
                        rel_p = abs_p.relative_to(target_out_dir)
                        zipf.write(abs_p, arcname=str(rel_p))

        ctx.set_result_file(str(zip_path))
        ctx.artifacts.update(res)
        ctx.artifacts["output_directory"] = str(target_out_dir)
        ctx.update_progress(
            progress=100,
            message=f"Merged {res['matched_forms']} forms: added {res['added_questions']} questions and {res['added_answers']} answers.",
        )
    except Exception as e:
        ctx.add_error(f"Merge schemas failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Merge schemas failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Export Form Concepts
# ==============================================================================
def run_export_form_concepts_worker(
    ctx: JobContext,
    forms_dir: str,
    output_dir: Optional[str] = None,
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    ctx.log(f"Extracting and exporting concepts referenced in forms: {forms_dir}...")
    client = get_openmrs_client(base_url, username, password)
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    target_out_dir = Path(output_dir) if output_dir else job_export_dir
    target_out_dir.mkdir(parents=True, exist_ok=True)

    try:
        res = export_form_concepts(
            client=client,
            forms_dir=forms_dir,
            out_dir=target_out_dir,
            log_fn=lambda msg: ctx.log(msg),
            is_canceled_fn=lambda: ctx.is_canceled(),
        )
        zip_path = settings.exports_dir / f"form_concepts_{ctx.job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for fr in res.get("results", []):
                for key in ("concepts_file", "convsets_file"):
                    fp_str = fr.get(key)
                    if fp_str:
                        fp = Path(fp_str)
                        if fp.is_file():
                            try:
                                arcname = fp.relative_to(target_out_dir)
                            except ValueError:
                                arcname = Path(fp.parent.name) / fp.name
                            zipf.write(fp, arcname=str(arcname))

        ctx.set_result_file(str(zip_path))
        ctx.artifacts["total_concepts"] = res.get("total_concepts", 0)
        ctx.artifacts["total_convsets"] = res.get("total_convsets", 0)
        ctx.artifacts["output_directory"] = str(target_out_dir)
        ctx.update_progress(
            progress=100,
            message=(
                f"Exported {res.get('total_concepts', 0)} concepts and "
                f"{res.get('total_convsets', 0)} ConvSets from {res.get('total_forms', 0)} forms."
            ),
        )
    except Exception as e:
        ctx.add_error(f"Export form concepts failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Export form concepts failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: Import Form Schemas
# ==============================================================================
def run_import_form_schemas_worker(
    ctx: JobContext,
    forms_dir: str,
    dry_run: bool = False,
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    ctx.log(f"Importing form schemas into OpenMRS 3.x (dry_run={dry_run})...")
    client = get_openmrs_client(base_url, username, password)

    try:
        res = import_form_schemas(
            client=client,
            forms_dir=forms_dir,
            dry_run=dry_run,
            log_fn=lambda msg: ctx.log(msg),
            is_canceled_fn=lambda: ctx.is_canceled(),
        )
        ctx.artifacts.update(res)
        ctx.update_progress(
            progress=100,
            message=f"Imported {res['imported']} schemas, {res['failed']} failed.",
        )
    except Exception as e:
        ctx.add_error(f"Import form schemas failed: {str(e)}")
        ctx.status = "failed"
        ctx.log(f"Import form schemas failed: {str(e)}", level="ERROR")


# ==============================================================================
# Worker: OpenMRS 2.1 Legacy Exporter
# ==============================================================================
def run_legacy21_export_worker(
    ctx: JobContext,
    output_dir: Optional[str] = None,
    filename: Optional[str] = "concepts.csv",
    server_type: Optional[str] = "bahmni",
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    if not base_url or not username or not password:
        target_sys = server_type or "bahmni"
        conn = (
            get_server_connection(target_sys)
            or get_server_connection("bahmni")
            or get_server_connection("openmrs")
        )
        if conn:
            base_url = base_url or conn.get("base_url")
            username = username or conn.get("username")
            password = password or conn.get("secret")

    base_url = normalize_container_url(base_url or "http://172.16.75.128/openmrs")
    username = username or settings.BAHMNI_USERNAME or "superman"
    password = password or settings.BAHMNI_PASSWORD or "Admin123"

    ctx.log(f"Exporting legacy concepts from OpenMRS 2.1: {base_url}...")
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    dest_dir = job_export_dir
    user_out_path = None
    if output_dir and not str(output_dir).strip().startswith("[Local"):
        try:
            p = Path(output_dir)
            p.mkdir(parents=True, exist_ok=True)
            user_out_path = p
        except Exception:
            pass

    fn = filename or "concepts.csv"
    try:
        res = export_legacy21_concepts(
            base_url=base_url,
            username=username,
            password=password,
            out_dir=dest_dir,
            filename=fn,
            log_fn=lambda msg: ctx.log(msg),
            is_canceled_fn=lambda: ctx.is_canceled(),
        )
        if user_out_path:
            import shutil
            shutil.copy2(res["output_file"], user_out_path / res["filename"])
            ctx.log(f"Saved copy to target directory: {user_out_path / res['filename']}")

        ctx.set_result_file(res["output_file"])
        ctx.artifacts["total_concepts"] = res["total_concepts"]
        ctx.artifacts["total_forms"] = res.get("total_forms", 0)
        ctx.update_progress(
            progress=100,
            message=f"Exported {res['total_concepts']} concepts from OpenMRS 2.1.",
        )
    except Exception as e:
        err_msg = f"Legacy 2.1 export failed: {str(e)}"
        ctx.add_error(err_msg)
        ctx.message = err_msg
        ctx.status = "failed"


# ==============================================================================
# Worker: OpenMRS 2.1 DHIS2 Concept Converter
# ==============================================================================
def run_legacy21_convert_worker(
    ctx: JobContext,
    input_file: str,
    parent_folder: str = "MID",
    output_dir: Optional[str] = None,
):
    ctx.log(f"Converting DHIS2 mapping file to OpenMRS 2.1 CSVs...")
    job_export_dir = settings.exports_dir / ctx.job_id
    job_export_dir.mkdir(parents=True, exist_ok=True)

    dest_dir = job_export_dir
    user_out_path = None
    if output_dir and not str(output_dir).strip().startswith("[Local"):
        try:
            p = Path(output_dir)
            p.mkdir(parents=True, exist_ok=True)
            user_out_path = p
        except Exception:
            pass

    try:
        res = convert_dhis2_to_legacy21(
            input_file=input_file,
            output_root=dest_dir,
            parent_folder_name=parent_folder or "MID",
            log_fn=lambda msg: ctx.log(msg),
            is_canceled_fn=lambda: ctx.is_canceled(),
        )

        parent_name = res.get("parent_folder", parent_folder or "MID")

        if user_out_path:
            import shutil
            target_parent = user_out_path / parent_name
            if target_parent.exists():
                shutil.rmtree(target_parent)
            shutil.copytree(dest_dir / parent_name, target_parent)
            ctx.log(f"Saved copy to target directory: {target_parent}")

        zip_path = settings.exports_dir / f"{parent_name}_legacy21_concepts_{ctx.job_id}.zip"
        zip_directory(dest_dir / parent_name, zip_path)
        ctx.set_result_file(str(zip_path))
        ctx.artifacts.update(res)
        ctx.update_progress(
            progress=100,
            message=f"Converted {res['stages_count']} stages and {res['sections_count']} sections into {res['concepts_count']} concepts.",
        )
    except Exception as e:
        err_msg = f"Legacy 2.1 conversion failed: {str(e)}"
        ctx.add_error(err_msg)
        ctx.message = err_msg
        ctx.status = "failed"


# ==============================================================================
# Worker: OpenMRS 2.1 / Bahmni Bulk Concept Importer (CM-13)
# ==============================================================================
def run_legacy21_bulk_import_worker(
    ctx: JobContext,
    export_file: str,
    folder: str,
    mode: str = "api",
    apply: bool = False,
    server_type: Optional[str] = "bahmni",
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    output_dir: Optional[str] = None,
    strict_set_check: bool = False,
    check_only: bool = False,
    delay_ms: int = 200,
    batch_size: int = 100,
):
    from backend.modules.concepts import bahmni_concept_importer as bci

    action_label = "Apply Execution" if apply else "Dry-Run Plan"
    ctx.log(f"Starting Legacy 2.1 Bulk Concept Importer ({mode.upper()} mode, {action_label})...")

    # Resolve output directory
    job_dest_dir = settings.exports_dir / f"legacy21_import_{ctx.job_id}"
    job_dest_dir.mkdir(parents=True, exist_ok=True)

    user_out_path = None
    if output_dir and not str(output_dir).strip().startswith("[Local"):
        try:
            p = Path(output_dir)
            p.mkdir(parents=True, exist_ok=True)
            user_out_path = p
        except Exception:
            pass

    # Resolve export_file
    export_candidate = Path(export_file)
    if not export_candidate.exists():
        for cand in [
            settings.uploads_dir / export_file,
            settings.exports_dir / export_file,
            Path(export_file).resolve(),
        ]:
            if cand.exists() and cand.is_file():
                export_candidate = cand
                break

    if not export_candidate.exists() or not export_candidate.is_file():
        recent_exports = sorted(
            settings.exports_dir.glob("**/concepts*.csv"),
            key=os.path.getmtime,
            reverse=True,
        )
        if recent_exports:
            export_candidate = recent_exports[0]
            ctx.log(f"Auto-selected recent server export: {export_candidate.name}")
        else:
            raise ValueError(f"Server export CSV file not found: {export_file}")

    # Resolve folder (supports directory or zipped directory)
    folder_candidate = Path(folder)
    if not folder_candidate.exists():
        for cand in [
            settings.uploads_dir / folder,
            settings.exports_dir / folder,
            Path(folder).resolve(),
        ]:
            if cand.exists():
                folder_candidate = cand
                break

    if not folder_candidate.exists():
        raise ValueError(f"Import folder or archive not found: {folder}")

    if folder_candidate.is_file() and folder_candidate.suffix.lower() == ".zip":
        extract_dir = job_dest_dir / "unpacked_folder"
        extract_dir.mkdir(parents=True, exist_ok=True)
        ctx.log(f"Unpacking concept folder zip archive: {folder_candidate.name}...")
        with zipfile.ZipFile(folder_candidate, "r") as zf:
            zf.extractall(extract_dir)
        folder_candidate = extract_dir

    ctx.log(f"Target folder for import: {folder_candidate}")
    ctx.log(f"Server snapshot export: {export_candidate}")

    # Resolve server credentials if in API mode or if base_url is supplied
    if mode == "api" or base_url:
        target_sys = server_type or "bahmni"
        conn = (
            get_server_connection(target_sys)
            or get_server_connection("bahmni")
            or get_server_connection("openmrs")
        )
        if conn:
            base_url = base_url or conn.get("base_url")
            username = username or conn.get("username")
            password = password or conn.get("secret")

        base_url = normalize_container_url(base_url or "http://172.16.75.128/openmrs")
        username = username or settings.BAHMNI_USERNAME or "superman"
        password = password or settings.BAHMNI_PASSWORD or "Admin123"

    # Build command arguments for importer
    argv = [
        "--export", str(export_candidate),
        "--folder", str(folder_candidate),
        "--mode", mode,
        "--out-dir", str(job_dest_dir),
        "--delay-ms", str(delay_ms),
        "--batch-size", str(batch_size),
    ]

    if apply:
        argv.append("--apply")
    if strict_set_check:
        argv.append("--strict-set-check")
    if check_only:
        argv.append("--check-only")

    if base_url:
        argv.extend(["--url", base_url])
    if username:
        argv.extend(["--user", username])
    if password:
        argv.extend(["--password", password])
    argv.append("--insecure")

    # Attach live hooks
    bci.SAY_HOOK = lambda msg: ctx.log(msg)
    bci.CANCEL_HOOK = lambda: ctx.is_canceled()

    try:
        ctx.update_progress(progress=10, message="Executing legacy importer logic...")
        exit_code = bci.main(argv)

        # Artifacts discovery
        produced_files = list(job_dest_dir.glob("*.csv")) + list(job_dest_dir.glob("*.txt"))
        ctx.artifacts["files"] = [f.name for f in produced_files]

        if user_out_path:
            for f in produced_files:
                shutil.copy2(f, user_out_path / f.name)
            ctx.log(f"Saved {len(produced_files)} artifact(s) to destination directory: {user_out_path}")

        # Package artifacts into a zip file for simple download
        zip_path = settings.exports_dir / f"legacy21_import_result_{ctx.job_id}.zip"
        zip_directory(job_dest_dir, zip_path)

        ctx.set_result_file(str(zip_path))

        summary_path = job_dest_dir / "summary.txt"
        if summary_path.exists():
            try:
                ctx.artifacts["summary"] = summary_path.read_text(encoding="utf-8")
            except Exception:
                pass

        if exit_code == 2:
            ctx.status = "failed"
            ctx.message = "Bulk import stopped due to error or cancellation."
        elif exit_code == 1:
            ctx.update_progress(
                progress=100,
                message="Import process finished with plan warnings or skipped items (see conflicts_and_errors.csv).",
            )
            ctx.status = "completed"
        else:
            ctx.update_progress(
                progress=100,
                message="Bulk import process completed successfully.",
            )
            ctx.status = "completed"
    except Exception as e:
        err_msg = f"Legacy 2.1 bulk importer failed: {str(e)}"
        ctx.add_error(err_msg)
        ctx.message = err_msg
        ctx.status = "failed"
    finally:
        bci.SAY_HOOK = None
        bci.CANCEL_HOOK = None


