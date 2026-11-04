"""Export Form Concepts.

Reads all form schemas in a folder, extracts EVERY concept UUID referenced
anywhere in each form, fetches full concept details from an OpenMRS 3.x
server, and saves them per-form in a format importable by openmrs_importer.

Concepts are ordered so that answer concepts come before the question
concepts that reference them, to satisfy dependency ordering during import.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from backend.modules.concepts.openmrs_importer import OpenMRSClient, error_detail

REQUEST_TIMEOUT = 30
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def find_form_files(search_dir: Path) -> list[Path]:
    """Find O3 form schema files under search_dir.

    Matches any *.json (including *.form.json) and keeps only files whose
    content looks like an O3 form schema (has a 'pages' key and a uuid).
    """
    candidates = []
    for fpath in sorted(search_dir.rglob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (
            isinstance(data, dict)
            and data.get("pages") is not None
            and data.get("uuid")
        ):
            candidates.append(fpath)
    return candidates


def extract_name(names_list: list, name_type: str) -> str:
    for n in names_list or []:
        if isinstance(n, dict) and n.get("conceptNameType") == name_type:
            return n.get("display", "")
    return ""


def extract_short_name(names_list: list) -> str:
    for n in names_list or []:
        if isinstance(n, dict) and n.get("conceptNameType") == "SHORT":
            return n.get("display", "")
    return ""


def extract_synonyms(names_list: list) -> list[str]:
    return [
        n.get("display", "")
        for n in (names_list or [])
        if isinstance(n, dict) and n.get("conceptNameType") == ""
    ]


def _is_non_concept_path(path: str) -> bool:
    """True if a JSON path points at a UUID that is NOT a concept.

    encounterType   -> encounter-type uuid, not a concept
    referencedForms -> referenced form uuids, not concepts
    """
    return path == ".encounterType" or path.startswith(".referencedForms")


def deep_collect_uuids(obj: object, path: str = "") -> dict[str, list[str]]:
    """Recursively walk the entire JSON tree and find ALL concept UUIDs.

    Returns a dict: uuid -> list of paths where it was found.
    This ensures we capture every concept reference anywhere in the form.
    """
    found: dict[str, list[str]] = {}

    def _recurse(val: object, cur_path: str):
        if isinstance(val, dict):
            for k, v in val.items():
                _recurse(v, f"{cur_path}.{k}")
        elif isinstance(val, list):
            for i, v in enumerate(val):
                _recurse(v, f"{cur_path}[{i}]")
        elif isinstance(val, str) and UUID_RE.match(val):
            found.setdefault(val, []).append(cur_path)

    _recurse(obj, path)
    # Exclude the form schema's own UUID (top-level .uuid — not a concept)
    if isinstance(obj, dict):
        found.pop(str(obj.get("uuid", "")), None)
    # Exclude UUIDs that only appear in non-concept fields (e.g. encounterType)
    found = {
        uuid: paths
        for uuid, paths in found.items()
        if any(not _is_non_concept_path(p) for p in paths)
    }
    return found


def classify_uuids(schema: dict, all_uuids: set[str]):
    """Classify each UUID into answer_uuids, question_uuids, or convset_uuids.

    answer_uuids: concepts that appear in any answers[] array
    convset_uuids: concepts that are the obsGroup grouping concept
    question_uuids: all other concepts (question concepts, etc.)
    """
    answer_uuids: set[str] = set()
    question_uuids: set[str] = set()
    convset_uuids: set[str] = set()

    def _walk_questions(questions_list: list):
        for q in questions_list:
            if not isinstance(q, dict):
                continue
            qopts = q.get("questionOptions", {})
            qconcept = qopts.get("concept", "")
            if qconcept in all_uuids:
                if q.get("type") == "obsGroup":
                    convset_uuids.add(qconcept)
                else:
                    question_uuids.add(qconcept)

            for ans in qopts.get("answers", []) or []:
                aconcept = ans.get("concept", "")
                if aconcept in all_uuids:
                    answer_uuids.add(aconcept)

            if q.get("type") == "obsGroup":
                _walk_questions(q.get("questions", []))

    for page in schema.get("pages", []):
        for section in page.get("sections", []):
            _walk_questions(section.get("questions", []))

    return answer_uuids, question_uuids, convset_uuids


def order_uuids(
    answer_uuids: set[str],
    question_uuids: set[str],
    convset_uuids: set[str],
    all_uuids: set[str],
) -> list[str]:
    """Order UUIDs so answers come first, then questions, then the rest.

    A concept that is BOTH answer and question appears once, in the answer
    group (earlier position).
    """
    ordered = []
    seen = set()

    for group in [answer_uuids, question_uuids]:
        for uuid in sorted(group):
            if uuid not in seen and uuid in all_uuids:
                ordered.append(uuid)
                seen.add(uuid)

    remaining = sorted(all_uuids - seen - convset_uuids)
    ordered.extend(remaining)

    return ordered


def api_concept_to_import_format(api_concept: dict) -> dict:
    names_list = api_concept.get("names", [])
    full_name = extract_name(names_list, "FULLY_SPECIFIED")

    dt = api_concept.get("datatype", {})
    dt_display = dt.get("display") if isinstance(dt, dict) else str(dt)

    cc = api_concept.get("conceptClass", {})
    cc_display = cc.get("display") if isinstance(cc, dict) else str(cc)

    desc = ""
    for d in api_concept.get("descriptions", []) or []:
        if isinstance(d, dict) and d.get("locale") == "en":
            desc = d.get("description", "")
            break

    answer_names = []
    for a in api_concept.get("answers", []) or []:
        if isinstance(a, dict):
            answer_names.append(a.get("display", ""))

    return {
        "uuid": api_concept.get("uuid", ""),
        "fully_specified_name": full_name,
        "short_name": extract_short_name(names_list),
        "description": desc,
        "concept_class": cc_display,
        "datatype": dt_display,
        "synonyms": extract_synonyms(names_list),
        "answers": answer_names,
    }


def api_concept_to_convset_format(api_concept: dict) -> dict:
    names_list = api_concept.get("names", [])
    full_name = extract_name(names_list, "FULLY_SPECIFIED")

    cc = api_concept.get("conceptClass", {})
    cc_display = cc.get("display") if isinstance(cc, dict) else str(cc)

    desc = ""
    for d in api_concept.get("descriptions", []) or []:
        if isinstance(d, dict) and d.get("locale") == "en":
            desc = d.get("description", "")
            break

    members = []
    for m in api_concept.get("setMembers", []) or []:
        if isinstance(m, dict):
            members.append(m.get("display", ""))

    return {
        "uuid": api_concept.get("uuid", ""),
        "fully_specified_name": full_name,
        "short_name": extract_short_name(names_list),
        "description": desc,
        "concept_class": cc_display,
        "members": members,
    }


def export_form_concepts(
    client: OpenMRSClient,
    forms_dir: str | Path,
    out_dir: str | Path,
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[int, int, str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    prog = progress_fn or (lambda cur, tot, msg: None)
    is_canceled = is_canceled_fn or (lambda: False)

    fdir = Path(forms_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    form_files = find_form_files(fdir)
    if not form_files:
        # Check if the folder exists under /data/schemas
        alt_path = Path("/data/schemas") / fdir.name
        if alt_path.is_dir():
            alt_files = find_form_files(alt_path)
            if alt_files:
                log(f"Notice: No form schemas found in '{fdir}', but found {len(alt_files)} schemas in '{alt_path}'. Automatically using '{alt_path}'.")
                fdir = alt_path
                form_files = alt_files

    if not form_files:
        log(f"No form schema (.json) files found in {fdir}")
        log("Tip: OpenMRS 3.x form schemas are JSON files with 'pages' and 'uuid' (found under /data/schemas/...).")
        return {
            "status": "completed",
            "total_forms": 0,
            "total_concepts": 0,
            "total_convsets": 0,
            "results": [],
        }

    log(f"Found {len(form_files)} form schema(s) in {fdir}\n")

    all_api_concepts: dict[str, dict] = {}
    total_exported_concepts = 0
    total_exported_convsets = 0
    form_results = []

    for idx, fpath in enumerate(form_files, 1):
        if is_canceled():
            log("Form concept export stopped by user.")
            break

        rel = fpath.relative_to(fdir)
        rel_stem = rel.stem.replace(".form", "")
        out_folder = out_path / rel.parent / rel_stem

        prog(idx, len(form_files), f"Processing: {rel}")

        try:
            schema = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log(f"  SKIP {rel}: could not read ({e})")
            continue

        uuid_paths = deep_collect_uuids(schema)
        all_uuids = set(uuid_paths.keys())
        if not all_uuids:
            log(f"  {rel}: no concept UUIDs found, skipping.")
            continue

        answer_uuids, question_uuids, convset_uuids = classify_uuids(schema, all_uuids)
        ordered_uuids = order_uuids(answer_uuids, question_uuids, convset_uuids, all_uuids)

        fetch_uuids = [u for u in ordered_uuids if u not in all_api_concepts]
        if fetch_uuids:
            log(f"  {rel}: fetching {len(fetch_uuids)} new concept(s) from server...")
            for u in fetch_uuids:
                if is_canceled():
                    break
                try:
                    cdata = client.get_concept(u)
                    all_api_concepts[u] = cdata
                except Exception as e:
                    log(f"    WARN: could not fetch {u}: {error_detail(e)}")

        if is_canceled():
            break

        concepts_list = []
        convsets_list = []

        for uuid in ordered_uuids:
            api_concept = all_api_concepts.get(uuid)
            if api_concept is None:
                continue
            cc = api_concept.get("conceptClass", {})
            cc_display = cc.get("display") if isinstance(cc, dict) else str(cc)
            if uuid in convset_uuids or cc_display == "ConvSet":
                if uuid not in {c["uuid"] for c in convsets_list}:
                    convsets_list.append(api_concept_to_convset_format(api_concept))
            else:
                if uuid not in {c["uuid"] for c in concepts_list}:
                    concepts_list.append(api_concept_to_import_format(api_concept))

        for uuid in sorted(convset_uuids):
            if uuid not in {c["uuid"] for c in convsets_list}:
                convsets_list.append(
                    {
                        "uuid": uuid,
                        "fully_specified_name": f"Concept {uuid}",
                        "short_name": "",
                        "description": "Placeholder — concept could not be fetched from source server",
                        "concept_class": "ConvSet",
                        "members": [],
                    }
                )

        out_folder.mkdir(parents=True, exist_ok=True)
        concepts_file = out_folder / "concepts_import.json"
        convsets_file = out_folder / "concept_sets_import.json"

        concepts_file.write_text(
            json.dumps(concepts_list, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        convsets_file.write_text(
            json.dumps(convsets_list, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        total_exported_concepts += len(concepts_list)
        total_exported_convsets += len(convsets_list)

        log(f"  {rel}")
        log(
            f"    -> {len(concepts_list)} concepts (answers first), {len(convsets_list)} ConvSets -> {out_folder}"
        )

        form_results.append(
            {
                "form_file": str(rel),
                "folder": str(out_folder),
                "concepts_count": len(concepts_list),
                "convsets_count": len(convsets_list),
                "concepts_file": str(concepts_file),
                "convsets_file": str(convsets_file),
            }
        )

    log(
        f"\nDone. {len(form_results)} forms processed, {len(all_api_concepts)} unique concepts fetched."
    )
    return {
        "status": "completed",
        "total_forms": len(form_files),
        "total_concepts": total_exported_concepts,
        "total_convsets": total_exported_convsets,
        "unique_concepts_fetched": len(all_api_concepts),
        "results": form_results,
    }
