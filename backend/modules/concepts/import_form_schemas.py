"""Import Form Schemas into OpenMRS 3.x.

Reads all form schema files from a folder (or single file) and imports each one
into OpenMRS 3.x via the REST API as unpublished (draft) forms.
After import, you can inspect and publish them via the Form Builder.
"""

from __future__ import annotations

import io
import json
import re
import uuid
from pathlib import Path
from backend.core.config import settings
from typing import Callable, Optional

from backend.modules.concepts.openmrs_importer import OpenMRSClient, error_detail

REQUEST_TIMEOUT = 60
RESOURCE_NAME = "JSON schema"


def is_form_schema(data: dict) -> bool:
    """Check if a JSON object looks like an OpenMRS O3 form schema."""
    if not isinstance(data, dict):
        return False
    if "pages" in data:
        return True
    if data.get("processor") == "EncounterFormProcessor":
        return True
    if "name" in data and (
        "sections" in data or "questions" in data or "encounterType" in data
    ):
        return True
    return False


def find_form_files(search_path: Path) -> list[Path]:
    """Find O3 form schema files under search_path.

    Works for both directories and individual .json files.
    Matches any *.json (including *.form.json) and keeps files whose
    content is a valid O3 form schema.
    """
    candidates = []
    if not search_path.exists():
        return candidates

    if search_path.is_file():
        if search_path.suffix.lower() == ".zip":
            import zipfile
            extract_dir = search_path.parent / f"extracted_{search_path.stem}"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(search_path, "r") as zf:
                zf.extractall(extract_dir)
            return find_form_files(extract_dir)
        if search_path.suffix.lower() == ".json":
            try:
                data = json.loads(search_path.read_text(encoding="utf-8"))
                if is_form_schema(data):
                    candidates.append(search_path)
            except Exception:
                pass
        return candidates

    for fpath in sorted(search_path.rglob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        if is_form_schema(data):
            candidates.append(fpath)
    return candidates


def _post_json(client: OpenMRSClient, path: str, data: dict) -> dict:
    url = client._url(path)
    r = client.session.post(
        url,
        json=data,
        timeout=REQUEST_TIMEOUT,
        headers={"Content-Type": "application/json; charset=UTF-8"},
    )
    r.raise_for_status()
    return r.json()


def get_form(client: OpenMRSClient, form_uuid: str) -> Optional[dict]:
    try:
        r = client.session.get(
            client._url(f"/ws/rest/v1/form/{form_uuid}"),
            params={"v": "full"},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def create_form(client: OpenMRSClient, data: dict) -> dict:
    return _post_json(client, "/ws/rest/v1/form", data)


def save_form(client: OpenMRSClient, form_uuid: str, data: dict) -> dict:
    return _post_json(client, f"/ws/rest/v1/form/{form_uuid}", data)


def upload_clobdata(client: OpenMRSClient, schema_str: str) -> dict:
    """Upload schema JSON as a file to clobdata (multipart/form-data)."""
    buf = io.BytesIO(schema_str.encode("utf-8"))
    files = {"file": ("schema.json", buf, "application/json")}
    r = client.session.post(
        client._url("/ws/rest/v1/clobdata"),
        files=files,
        headers={"Content-Type": None, "Accept": "*/*"},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
    content_type = r.headers.get("Content-Type", "")
    text = r.text.strip().strip('"')
    if "json" in content_type:
        try:
            data = r.json()
            if isinstance(data, dict) and data.get("uuid"):
                return data
            elif isinstance(data, str) and re.match(
                r"^[0-9a-fA-F\-]{36}$", data.strip('"')
            ):
                return {"uuid": data.strip('"')}
        except Exception:
            pass
    if re.match(r"^[0-9a-fA-F\-]{36}$", text):
        return {"uuid": text}
    raise RuntimeError(
        f"Unexpected response (HTTP {r.status_code}, Content-Type: {content_type}): {text[:500]}"
    )


def get_form_resources(client: OpenMRSClient, form_uuid: str) -> list[dict]:
    r = client.session.get(
        client._url(f"/ws/rest/v1/form/{form_uuid}/resource"),
        params={"v": "full"},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("results", [])


def create_form_resource(client: OpenMRSClient, form_uuid: str, data: dict) -> dict:
    return _post_json(client, f"/ws/rest/v1/form/{form_uuid}/resource", data)


def delete_form_resource(
    client: OpenMRSClient, form_uuid: str, resource_uuid: str
) -> None:
    r = client.session.delete(
        client._url(f"/ws/rest/v1/form/{form_uuid}/resource/{resource_uuid}"),
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()


def import_single_form(
    client: OpenMRSClient, fpath: Path, log_fn: Callable[[str], None]
) -> dict:
    """Import a single form schema into OpenMRS. Returns dict on success, raises on error."""
    try:
        schema = json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log_fn(f"  SKIP {fpath.name}: could not read ({e})")
        raise RuntimeError(f"Could not read schema JSON: {e}")

    form_name = schema.get("name", fpath.stem.replace(".form", ""))
    form_uuid = schema.get("uuid", "")
    form_version = str(schema.get("version", "1.0"))
    form_description = schema.get("description", form_name)

    if not form_uuid:
        form_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, form_name))
        schema["uuid"] = form_uuid
        try:
            fpath.write_text(
                json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            log_fn(f"  {form_name}: generated and saved missing UUID ({form_uuid})")
        except Exception:
            log_fn(f"  {form_name}: generated UUID ({form_uuid})")

    # Build the form payload
    form_payload = {
        "name": form_name,
        "description": form_description,
        "version": form_version,
        "published": False,
    }
    if schema.get("encounterType"):
        form_payload["encounterType"] = schema["encounterType"]

    # Step 1: Create or update the Form
    existing = get_form(client, form_uuid)
    if existing:
        log_fn(f"  {form_name}: form exists, updating...")
        save_form(client, form_uuid, form_payload)
    else:
        form_payload["uuid"] = form_uuid
        try:
            create_form(client, form_payload)
            log_fn(f"  {form_name}: created form")
        except Exception as e:
            err = error_detail(e)
            log_fn(f"  FAILED creating form {form_name}: {err}")
            raise RuntimeError(f"Failed creating form metadata: {err}")

    # Step 2: Upload schema as clobdata (multipart file upload, matching form builder)
    schema_json_str = json.dumps(schema, indent=2, ensure_ascii=False)
    value_reference = None
    try:
        clob = upload_clobdata(client, schema_json_str)
        value_reference = clob["uuid"]
        log_fn(f"  {form_name}: schema uploaded to clobdata ({value_reference})")
    except Exception as e:
        log_fn(
            f"  WARN uploading clobdata for {form_name}: {error_detail(e)}, using direct schema payload"
        )
        value_reference = schema_json_str

    # Step 3: Remove any existing "JSON schema" resource
    try:
        existing_resources = get_form_resources(client, form_uuid)
        for res in existing_resources:
            res_name = res.get("name", "")
            res_datatype = res.get("dataType", "")
            if (
                res_name in (RESOURCE_NAME, "jsonSchema", "JSON Schema")
                or res_datatype == "AmpathJsonSchema"
            ):
                try:
                    delete_form_resource(client, form_uuid, res["uuid"])
                    log_fn(f"  {form_name}: removed old resource '{res_name}'")
                except Exception as e:
                    log_fn(f"  WARN: could not delete old resource: {error_detail(e)}")
    except Exception as e:
        log_fn(f"  WARN fetching old resources: {error_detail(e)}")

    # Step 4: Create form resource with valueReference (matching form builder)
    try:
        create_form_resource(
            client,
            form_uuid,
            {
                "name": RESOURCE_NAME,
                "dataType": "AmpathJsonSchema",
                "valueReference": value_reference,
            },
        )
        log_fn(f"  {form_name}: imported successfully as unpublished draft")
    except Exception as e:
        err = error_detail(e)
        log_fn(f"  FAILED creating form resource for {form_name}: {err}")
        raise RuntimeError(f"Failed creating form resource: {err}")

    return {
        "name": form_name,
        "uuid": form_uuid,
        "version": form_version,
        "status": "imported",
    }


def import_form_schemas(
    client: OpenMRSClient,
    forms_dir: str | Path,
    dry_run: bool = False,
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[int, int, str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    prog = progress_fn or (lambda cur, tot, msg: None)
    is_canceled = is_canceled_fn or (lambda: False)

    fdir = Path(forms_dir)
    form_files = find_form_files(fdir)

    # Fallback to schemas/<name> under DATA_DIR or /data/schemas if user selected a directory with no schemas
    if not form_files and fdir.is_dir():
        for candidate_root in [Path(settings.DATA_DIR) / "schemas", Path("/data/schemas")]:
            alt_path = candidate_root / fdir.name
            if alt_path.is_dir():
                alt_files = find_form_files(alt_path)
                if alt_files:
                    log(
                        f"Notice: No form schemas found in '{fdir}', but found {len(alt_files)} schemas in '{alt_path}'. Automatically using '{alt_path}'."
                    )
                    fdir = alt_path
                    form_files = alt_files
                    break

    if not form_files:
        log(f"No valid form schema (.json) files found in {fdir}.")
        return {
            "status": "completed",
            "total_files": 0,
            "imported": 0,
            "failed": 0,
            "results": [],
        }

    log(f"Found {len(form_files)} form schema(s) in {fdir}\n")

    prefix = "[DRY RUN] " if dry_run else ""
    results = []
    imported, failed = 0, 0

    for idx, fpath in enumerate(form_files, 1):
        if is_canceled():
            log("Form schema import stopped by user.")
            break

        prog(idx, len(form_files), f"Importing schema: {fpath.name}")
        log(f"\n{prefix}Processing: {fpath.name}")

        if dry_run:
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                name = data.get("name") or fpath.stem
                log(f"{prefix}Validated schema JSON for '{name}'")
                results.append(
                    {"file": fpath.name, "name": name, "status": "WOULD_IMPORT"}
                )
                imported += 1
            except Exception as e:
                failed += 1
                log(f"{prefix}Invalid schema in {fpath.name}: {e}")
                results.append(
                    {"file": fpath.name, "status": "FAILED", "detail": str(e)}
                )
            continue

        try:
            res = import_single_form(client, fpath, log)
            results.append({"file": fpath.name, **res})
            imported += 1
        except Exception as e:
            failed += 1
            d = error_detail(e)
            log(f"FAILED {fpath.name}: {d}")
            results.append({"file": fpath.name, "status": "FAILED", "detail": d})

    log(f"\n{prefix}Done. Imported: {imported}, Failed: {failed}")
    return {
        "status": "completed",
        "total_files": len(form_files),
        "imported": imported,
        "failed": failed,
        "results": results,
    }
