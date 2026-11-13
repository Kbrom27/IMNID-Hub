"""OpenMRS Concept Drug Formulations Importer.

Imports drug formulations (OpenMRS "drug" table linked to concepts) from either:
  1. OpenMRS Initializer CSV files:
       Uuid, Name, Concept Drug, Concept Dosage Form, Strength
       (optional: Description, Void/Retire, Maximum daily dose, Minimum daily dose)
  2. OpenMRS 3.x Formulations JSON files:
       [{"name": "...", "concept": "@Drug|Name or UUID", "dosageForm": "@Drug form|Name or UUID", "strength": "..."}]

Features:
  - Resolves concepts by 36-char UUID, @Class|Name syntax, or plain name.
  - Automatic fallback resolution for local UUIDs matching server concepts by name or companion dictionaries.
  - Auto-creates missing "Drug form" or "Drug" concepts when needed.
  - Performs deduplication checks on the OpenMRS server (/ws/rest/v1/drug).
  - Supports dry-run simulation mode and detailed CSV audit reporting.
"""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.parse
import uuid as py_uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from backend.core.config import settings
from backend.modules.concepts.openmrs_importer import OpenMRSClient, error_detail

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$|^[0-9A-Za-z]{36}$"
)

# Known fallback mappings for standard concept packages (e.g. initial concepts draft UUIDs)
DEFAULT_UUID_FALLBACKS: Dict[str, Tuple[str, str]] = {
    "cf19b5ce-3f71-430a-a4b0-13bb80f0b392": ("Oxytocin", "Drug"),
    "a0e1a765-9528-4e01-84bd-ce2d74b6446d": ("Caffeine citrate", "Drug"),
    "97e1b095-e796-4ebf-b694-061221984286": ("Carboprost", "Drug"),
    "d736c3aa-a4f0-425d-b943-bbf5ec81b0a6": ("Dinoprostone", "Drug"),
    "077d20f4-f46c-40c0-8ff1-7f6ffc306569": ("Azithromycin", "Drug"),
    "5d7131de-cefd-44d7-9ad5-152d99b02455": ("Poractant alfa", "Drug"),
    "baff0a1b-f2cb-4cac-9ee3-a80b70609df2": ("Levetiracetam", "Drug"),
    "cb8c399b-07e2-4452-937d-51ca7d2dad37": ("Terbutaline", "Drug"),
    "2265709e-c913-43f1-ac0f-6ca7d204f361": ("Cholecalciferol", "Drug"),
    "68bc2d02-30ce-4318-b3f8-adcccb7fe52f": ("Anti-D immunoglobulin", "Drug"),
    "b1245a91-1050-4284-b733-fe9f160407f6": ("Solution for injection", "Drug form"),
    "ce021492-3a23-4cc2-a444-a1c112a7ffff": ("Powder for injection", "Drug form"),
    "cc600340-51fe-4fcf-9f33-f9c811f8ec74": ("Solution for infusion", "Drug form"),
    "27af989f-e95b-4aa3-a125-a37b21d594f3": ("Oral solution", "Drug form"),
}


def build_companion_uuid_map(search_dir: Path) -> Dict[str, Tuple[str, str]]:
    """Scan candidate directories for companion concept CSVs/JSONs to map UUIDs to (name, class)."""
    mapping = dict(DEFAULT_UUID_FALLBACKS)
    check_dirs = [search_dir, search_dir.parent, settings.uploads_dir]

    for d in check_dirs:
        if not d.exists() or not d.is_dir():
            continue
        try:
            for item in d.iterdir():
                if item.suffix.lower() == ".csv":
                    try:
                        with open(item, newline="", encoding="utf-8-sig") as f:
                            rd = csv.reader(f)
                            header = next(rd, None)
                            if header and len(header) >= 3:
                                norm_h = [h.strip().lower() for h in header]
                                if "uuid" in norm_h[0]:
                                    for row in rd:
                                        if len(row) >= 3:
                                            u = row[0].strip()
                                            nm = row[1].strip()
                                            cls = row[2].strip() if len(row) > 2 else "Drug"
                                            if u and nm and UUID_RE.match(u):
                                                mapping[u] = (nm, cls)
                    except Exception:
                        pass
                elif item.suffix.lower() == ".json":
                    try:
                        with open(item, encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                for entry in data:
                                    if isinstance(entry, dict) and entry.get("uuid"):
                                        u = entry["uuid"].strip()
                                        names = entry.get("names", [])
                                        nm = ""
                                        if names and isinstance(names, list) and isinstance(names[0], dict):
                                            nm = names[0].get("name", "")
                                        elif entry.get("name"):
                                            nm = entry["name"] if isinstance(entry["name"], str) else entry["name"].get("name", "")
                                        cls = entry.get("conceptClass") or "Drug"
                                        if isinstance(cls, dict):
                                            cls = cls.get("name", "Drug")
                                        if u and nm and UUID_RE.match(u):
                                            mapping[u] = (nm, cls)
                    except Exception:
                        pass
        except Exception:
            pass

    return mapping


def resolve_drug_input_files(target_path: str | Path, file_format: str = "auto") -> List[Path]:
    """Resolve a target path (file, directory, or zip) into a list of input files."""
    if not target_path:
        raise ValueError("No path provided.")

    raw = str(target_path).strip().strip("'\"")
    if not raw:
        raise ValueError("Empty path provided.")

    p = Path(raw)

    # Check relative to uploads or data directory
    if not p.exists():
        fname = Path(raw).name
        cand_upload = settings.uploads_dir / fname
        cand_data = Path(settings.DATA_DIR) / fname
        if cand_upload.exists():
            p = cand_upload
        elif cand_data.exists():
            p = cand_data
        else:
            raise FileNotFoundError(f"File or directory not found on server: {raw}")

    # Handle zip files
    if p.is_file() and p.suffix.lower() == ".zip":
        extract_dir = settings.uploads_dir / f"extracted_{p.stem}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "r") as zf:
            zf.extractall(extract_dir)
        p = extract_dir

    fmt = (file_format or "auto").lower()

    if p.is_file():
        ext = p.suffix.lower()
        if fmt == "json" and ext == ".json":
            return [p]
        if fmt == "csv" and ext == ".csv":
            return [p]
        if fmt == "auto" and ext in (".csv", ".json"):
            return [p]
        raise ValueError(f"File '{p.name}' does not match expected format ({fmt}).")

    if p.is_dir():
        files: List[Path] = []
        for root, _, names in os.walk(p):
            for n in sorted(names):
                ext = Path(n).suffix.lower()
                if fmt == "json" and ext == ".json":
                    files.append(Path(root) / n)
                elif fmt == "csv" and ext == ".csv":
                    files.append(Path(root) / n)
                elif fmt == "auto" and ext in (".csv", ".json"):
                    files.append(Path(root) / n)
        return files

    raise FileNotFoundError(f"Invalid path: {target_path}")


def scan_drug_files(files: List[Path], file_format: str = "auto") -> Dict[str, Any]:
    """Inspect CSV or JSON files and count candidate drug formulation records."""
    valid_files = []
    total_rows = 0

    for path in files:
        ext = path.suffix.lower()
        if ext == ".json":
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else data.get("drugs", [])
                    count = len(items)
                    if count > 0:
                        valid_files.append({
                            "path": str(path),
                            "filename": path.name,
                            "format": "json",
                            "rows": count,
                        })
                        total_rows += count
            except Exception:
                continue

        elif ext == ".csv":
            try:
                with open(path, newline="", encoding="utf-8-sig") as f:
                    rd = csv.DictReader(f)
                    if not rd.fieldnames:
                        continue
                    norm_fields = {fn.strip().lower(): fn for fn in rd.fieldnames if fn}
                    if "concept drug" not in norm_fields:
                        continue

                    rows_in_file = 0
                    for row in rd:
                        name_key = norm_fields.get("name")
                        name = (row.get(name_key) or "").strip() if name_key else ""
                        if name:
                            rows_in_file += 1

                    valid_files.append({
                        "path": str(path),
                        "filename": path.name,
                        "format": "csv",
                        "rows": rows_in_file,
                    })
                    total_rows += rows_in_file
            except Exception:
                continue

    return {
        "valid_files_count": len(valid_files),
        "total_drug_rows": total_rows,
        "files": valid_files,
    }


def run_concept_drug_import(
    client: OpenMRSClient,
    path: str | Path,
    file_format: str = "auto",
    dry_run: bool = True,
    auto_create_concepts: bool = True,
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[int, int, str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
    out_report_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Import drug formulations into OpenMRS via REST API supporting both JSON and CSV.

    Returns summary dictionary with counts and generated report path.
    """
    def log(msg: str):
        if log_fn:
            log_fn(msg)

    files = resolve_drug_input_files(path, file_format=file_format)
    if not files:
        raise ValueError(f"No matching formulation files found in: {path}")

    log(f"Found {len(files)} candidate formulation file(s) for import.")

    # Load companion mapping for UUID -> (name, class) fallbacks
    parent_dir = files[0].parent if files else Path(settings.DATA_DIR)
    uuid_mapping = build_companion_uuid_map(parent_dir)

    cache: Dict[Tuple[str, str], str] = {}
    class_cache: Dict[str, str] = {}

    def call_api(method: str, endpoint: str, body: Optional[dict] = None, allow_404: bool = False):
        url = client._url(endpoint)
        try:
            r = client.session.request(
                method,
                url,
                json=body if body is not None else None,
                timeout=60,
            )
            if allow_404 and r.status_code == 404:
                return None
            r.raise_for_status()
            if r.content:
                try:
                    return r.json()
                except Exception:
                    return {}
            return {}
        except requests.exceptions.HTTPError as e:
            if allow_404 and e.response is not None and e.response.status_code == 404:
                return None
            err_msg = error_detail(e)
            raise RuntimeError(err_msg)
        except Exception as e:
            raise RuntimeError(str(e))

    def get_class_uuid(class_name: str) -> str:
        """Resolve concept class name to UUID."""
        norm = class_name.strip().lower()
        if norm in class_cache:
            return class_cache[norm]
        res = call_api("GET", "/ws/rest/v1/conceptclass?v=default")
        classes = res.get("results", []) if res else []
        for c in classes:
            c_name = c.get("name") or c.get("display") or ""
            class_cache[c_name.strip().lower()] = c["uuid"]
        if norm in class_cache:
            return class_cache[norm]
        return class_name

    def auto_create_concept(name: str, concept_class: str) -> str:
        """Create a missing concept on OpenMRS."""
        if dry_run:
            mock_id = f"mock-{py_uuid.uuid4().hex[:8]}"
            log(f"    [Dry-run] Would auto-create missing {concept_class} concept: \"{name}\"")
            return mock_id

        cls_uuid = get_class_uuid(concept_class)
        body = {
            "names": [
                {
                    "name": name,
                    "locale": "en",
                    "conceptNameType": "FULLY_SPECIFIED",
                }
            ],
            "datatype": "8d4a4c94-c2cc-11de-8d13-0010c6dffd0f",  # N/A datatype
            "conceptClass": cls_uuid,
        }
        res = call_api("POST", "/ws/rest/v1/concept", body=body)
        created_uuid = res.get("uuid")
        if not created_uuid:
            raise RuntimeError(f"Server did not return UUID for created concept \"{name}\"")
        log(f"    Auto-created missing {concept_class} concept: \"{name}\" (UUID: {created_uuid})")
        return created_uuid

    def resolve_concept(ref: str, preferred_class: str, drug_name: Optional[str] = None) -> str:
        ref = str(ref).strip()
        key = (ref, preferred_class)
        if key in cache:
            return cache[key]

        # 1. Format: @Class|Name
        if ref.startswith("@"):
            cls, name = ref[1:].split("|", 1)
            q = urllib.parse.urlencode({
                "q": name,
                "limit": 100,
                "v": "custom:(uuid,name:(name),conceptClass:(name))",
            })
            res = call_api("GET", f"/ws/rest/v1/concept?{q}")
            hits = [
                c for c in (res.get("results") or [])
                if (c.get("name") or {}).get("name", "").strip().lower() == name.lower()
                and (c.get("conceptClass") or {}).get("name", "").strip().lower() == cls.lower()
            ]
            if len(hits) == 1:
                cache[key] = hits[0]["uuid"]
                return cache[key]
            if len(hits) > 1:
                cache[key] = hits[0]["uuid"]
                return cache[key]

            # Not found on server -> auto-create if permitted
            if auto_create_concepts:
                created_uuid = auto_create_concept(name, cls)
                cache[key] = created_uuid
                return created_uuid
            raise RuntimeError(f"Expected concept @{cls}|{name} not found on server.")

        # 2. Format: UUID
        if UUID_RE.match(ref):
            res = call_api("GET", f"/ws/rest/v1/concept/{ref}?v=custom:(uuid)", allow_404=True)
            if res is not None:
                cache[key] = ref
                return ref

            # UUID returned 404 -> Check companion mapping
            if ref in uuid_mapping:
                mapped_name, mapped_cls = uuid_mapping[ref]
                q = urllib.parse.urlencode({
                    "q": mapped_name,
                    "limit": 100,
                    "v": "custom:(uuid,name:(name),conceptClass:(name))",
                })
                res = call_api("GET", f"/ws/rest/v1/concept?{q}")
                hits = [
                    c for c in (res.get("results") or [])
                    if (c.get("name") or {}).get("name", "").strip().lower() == mapped_name.lower()
                    and (c.get("conceptClass") or {}).get("name", "").strip().lower() == mapped_cls.lower()
                ]
                if hits:
                    cache[key] = hits[0]["uuid"]
                    return cache[key]

                # If mapped concept does not exist on server, auto-create it
                if auto_create_concepts:
                    created_uuid = auto_create_concept(mapped_name, mapped_cls)
                    cache[key] = created_uuid
                    return created_uuid

            # UUID 404 -> check if drug_name stem matches an existing Drug concept
            if preferred_class == "Drug" and drug_name:
                words = drug_name.split()
                for i in range(len(words), 0, -1):
                    cand = " ".join(words[:i]).strip()
                    if len(cand) < 3:
                        continue
                    q = urllib.parse.urlencode({
                        "q": cand,
                        "limit": 10,
                        "v": "custom:(uuid,name:(name),conceptClass:(name))",
                    })
                    res = call_api("GET", f"/ws/rest/v1/concept?{q}")
                    hits = [
                        c for c in (res.get("results") or [])
                        if (c.get("name") or {}).get("name", "").strip().lower() == cand.lower()
                        and (c.get("conceptClass") or {}).get("name", "").strip().lower() == "drug"
                    ]
                    if hits:
                        cache[key] = hits[0]["uuid"]
                        return cache[key]

            raise RuntimeError(f"Concept UUID not found on server: {ref}")

        # 3. Format: plain name
        q = urllib.parse.urlencode({
            "q": ref,
            "limit": 100,
            "v": "custom:(uuid,name:(name),conceptClass:(name))",
        })
        res = call_api("GET", f"/ws/rest/v1/concept?{q}")
        hits = [
            c for c in (res.get("results") or [])
            if (c.get("name") or {}).get("name", "").strip().lower() == ref.lower()
        ]
        if len(hits) > 1:
            same_class = [
                c for c in hits
                if (c.get("conceptClass") or {}).get("name", "").strip().lower() == preferred_class.lower()
            ]
            if len(same_class) == 1:
                hits = same_class

        if len(hits) == 1:
            cache[key] = hits[0]["uuid"]
            return cache[key]

        if not hits and auto_create_concepts:
            created_uuid = auto_create_concept(ref, preferred_class)
            cache[key] = created_uuid
            return created_uuid

        raise RuntimeError(f'Expected exactly 1 concept named "{ref}", found {len(hits)}')

    report_rows: List[List[str]] = []
    counts = {"created": 0, "dry-run ok": 0, "skipped": 0, "failed": 0}

    # Normalize formulation records from files
    records_to_process: List[Tuple[Path, Dict[str, Any]]] = []

    for fpath in files:
        ext = fpath.suffix.lower()
        if ext == ".json":
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else data.get("drugs", [])
                    for item in items:
                        if isinstance(item, dict) and item.get("name"):
                            records_to_process.append((fpath, item))
            except Exception as e:
                log(f"Warning: could not read JSON file {fpath.name}: {e}")

        elif ext == ".csv":
            try:
                with open(fpath, newline="", encoding="utf-8-sig") as f:
                    rd = list(csv.DictReader(f))
                    if rd and rd[0]:
                        norm_keys = {k.strip().lower(): k for k in rd[0].keys() if k}
                        if "concept drug" in norm_keys:
                            for row in rd:
                                rec = {}
                                for k, orig_k in norm_keys.items():
                                    rec[k] = row.get(orig_k, "").strip()
                                if rec.get("name"):
                                    records_to_process.append((fpath, rec))
            except Exception as e:
                log(f"Warning: could not read CSV file {fpath.name}: {e}")

    total_rows = len(records_to_process)
    if total_rows == 0:
        log("No valid formulation records found to process.")
        return {
            "created": 0,
            "dry_run_ok": 0,
            "skipped": 0,
            "failed": 0,
            "total_processed": 0,
            "report_file": str(out_report_path) if out_report_path else None,
        }

    log(f"Processing {len(files)} file(s) with {total_rows} total rows...")
    processed_count = 0

    for fpath, raw_rec in records_to_process:
        if is_canceled_fn and is_canceled_fn():
            log("Job canceled by user.")
            break

        processed_count += 1
        name = raw_rec.get("name", "").strip()
        status, detail = "", ""

        try:
            void_val = str(
                raw_rec.get("void/retire")
                or raw_rec.get("voided")
                or raw_rec.get("retired")
                or ""
            ).strip().lower()

            if void_val in ("true", "yes", "1"):
                status, detail = "skipped", "marked Void/Retire"
            else:
                # Deduplication check: check if drug with this name already exists
                q = urllib.parse.urlencode({"q": name, "v": "custom:(uuid,name)"})
                res = call_api("GET", f"/ws/rest/v1/drug?{q}")
                drug_hits = (res.get("results") or []) if res else []
                if any((d.get("name") or "").strip().lower() == name.lower() for d in drug_hits):
                    status, detail = "skipped", "drug with this name already exists"
                else:
                    concept_drug_ref = (
                        raw_rec.get("concept")
                        or raw_rec.get("concept drug")
                        or raw_rec.get("concept_drug")
                        or ""
                    )
                    if not concept_drug_ref:
                        raise RuntimeError("Missing required Concept Drug reference.")

                    concept_uuid = resolve_concept(concept_drug_ref, "Drug", drug_name=name)

                    dosage_form_ref = (
                        raw_rec.get("dosageForm")
                        or raw_rec.get("dosageform")
                        or raw_rec.get("dosage_form")
                        or raw_rec.get("concept dosage form")
                        or raw_rec.get("concept_dosage_form")
                        or ""
                    )
                    dosage_form_uuid = None
                    if dosage_form_ref:
                        dosage_form_uuid = resolve_concept(dosage_form_ref, "Drug form")

                    payload: Dict[str, Any] = {
                        "name": name,
                        "combination": bool(raw_rec.get("combination", False)),
                        "concept": concept_uuid,
                    }

                    if dosage_form_uuid:
                        payload["dosageForm"] = dosage_form_uuid

                    strength = raw_rec.get("strength")
                    if strength:
                        payload["strength"] = strength

                    description = raw_rec.get("description")
                    if description:
                        payload["description"] = description

                    max_dose = raw_rec.get("maximum daily dose") or raw_rec.get("maximumdailydose")
                    if max_dose:
                        try:
                            payload["maximumDailyDose"] = float(max_dose)
                        except ValueError:
                            payload["maximumDailyDose"] = max_dose

                    min_dose = raw_rec.get("minimum daily dose") or raw_rec.get("minimumdailydose")
                    if min_dose:
                        try:
                            payload["minimumDailyDose"] = float(min_dose)
                        except ValueError:
                            payload["minimumDailyDose"] = min_dose

                    if dry_run:
                        status, detail = "dry-run ok", "validated successfully"
                    else:
                        call_api("POST", "/ws/rest/v1/drug", body=payload)
                        status, detail = "created", "created drug on server"

        except Exception as e:
            status, detail = "failed", str(e)

        counts[status] = counts.get(status, 0) + 1
        report_rows.append([str(fpath), name, status, detail])
        log(f"  {status.upper():10} {name}" + (f" -> {detail}" if detail else ""))

        if progress_fn and total_rows > 0:
            progress_fn(
                processed_count,
                total_rows,
                f"Processed {processed_count}/{total_rows}: {name} ({status})",
            )

    # Save CSV report file
    if out_report_path:
        out_report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_report_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "name", "status", "detail"])
            w.writerows(report_rows)
        log(f"Report saved to: {out_report_path}")

    summary_str = ", ".join(f"{v} {k}" for k, v in counts.items())
    log(f"Import Summary: {summary_str}")

    return {
        "created": counts.get("created", 0),
        "dry_run_ok": counts.get("dry-run ok", 0),
        "skipped": counts.get("skipped", 0),
        "failed": counts.get("failed", 0),
        "total_processed": processed_count,
        "report_file": str(out_report_path) if out_report_path else None,
    }
