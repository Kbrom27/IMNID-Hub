"""OpenMRS 3.x Concept Set Exporter.

Searches for concept sets on a live OpenMRS 3.x server and exports member concepts,
answers, and nested sets recursively into concepts_export.json and concept_sets_export.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional
import requests

from backend.modules.concepts.openmrs_importer import OpenMRSClient, error_detail


def extract_names(data: dict) -> tuple[Optional[str], str, list[str], str]:
    """Split a concept's 'names' list into (fsn, short_name, synonyms, locale)."""
    fsn = None
    short_name = ""
    synonyms = []
    locale = "en"
    for n in data.get("names", []):
        name_type = (n.get("conceptNameType") or "").upper()
        if name_type == "FULLY_SPECIFIED" and fsn is None:
            fsn = n.get("name")
            locale = n.get("locale") or "en"
        elif name_type == "SHORT" and not short_name:
            short_name = n.get("name")
        else:
            nm = n.get("name")
            if nm and nm != fsn:
                synonyms.append(nm)

    if fsn is None:
        fsn = data.get("display") or ""
    return fsn, short_name, synonyms, locale


def extract_answer_name(ans: dict) -> str:
    """Best-effort to find a sensible name for an answer concept entry."""
    for n in ans.get("names", []):
        if (n.get("conceptNameType") or "").upper() == "FULLY_SPECIFIED":
            return n.get("name")
    return ans.get("display") or ""


def build_concept_entry(data: dict) -> dict:
    fsn, short_name, synonyms, locale = extract_names(data)
    datatype = (data.get("datatype") or {}).get("display") or "N/A"
    concept_class = (data.get("conceptClass") or {}).get("display") or "Misc"

    desc = ""
    for d in data.get("descriptions", []):
        if d.get("description"):
            desc = d.get("description")
            break

    answers = []
    for a in data.get("answers", []):
        aname = extract_answer_name(a)
        if aname:
            answers.append(aname)

    return {
        "uuid": data.get("uuid", ""),
        "fully_specified_name": fsn,
        "short_name": short_name,
        "description": desc,
        "concept_class": concept_class,
        "datatype": datatype,
        "locale": locale,
        "synonyms": synonyms,
        "answers": answers,
    }


def build_set_entry(data: dict) -> dict:
    fsn, short_name, synonyms, locale = extract_names(data)
    concept_class = (data.get("conceptClass") or {}).get("display") or "ConvSet"
    desc = ""
    for d in data.get("descriptions", []):
        if d.get("description"):
            desc = d.get("description")
            break

    members = []
    for m in data.get("setMembers", []):
        mname = extract_answer_name(m)
        if mname:
            members.append(mname)

    return {
        "uuid": data.get("uuid", ""),
        "fully_specified_name": fsn,
        "short_name": short_name,
        "description": desc,
        "concept_class": concept_class,
        "locale": locale,
        "members": members,
    }


def search_concept_sets(client: OpenMRSClient, term: str) -> list[dict]:
    r = client.session.get(
        client._url("/ws/rest/v1/concept"),
        params={"q": term, "v": "full"},
        timeout=30,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    return [c for c in results if c.get("set")]


def export_concept_set(
    client: OpenMRSClient,
    root_uuid: str,
    out_dir: Optional[str | Path] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[int, int, str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    prog = progress_fn or (lambda cur, tot, msg: None)
    is_canceled = is_canceled_fn or (lambda: False)

    log(f"Fetching root concept set: {root_uuid}")
    r = client.session.get(
        client._url(f"/ws/rest/v1/concept/{root_uuid}"),
        params={"v": "full"},
        timeout=30,
    )
    r.raise_for_status()
    root_data = r.json()

    concepts_by_uuid: dict[str, dict] = {}
    sets_by_uuid: dict[str, dict] = {}
    seen_uuids: set[str] = set()

    queue: list[str] = [root_uuid]

    while queue:
        if is_canceled():
            log("Export stopped by user.")
            break
        uuid_val = queue.pop(0)
        if uuid_val in seen_uuids:
            continue
        seen_uuids.add(uuid_val)

        prog(len(seen_uuids), len(seen_uuids) + len(queue), f"Exporting: {uuid_val}")
        try:
            r = client.session.get(
                client._url(f"/ws/rest/v1/concept/{uuid_val}"),
                params={"v": "full"},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log(f"Failed to fetch {uuid_val}: {error_detail(e)}")
            continue

        fsn = data.get("display") or uuid_val
        is_set = bool(data.get("set"))

        if is_set:
            sets_by_uuid[uuid_val] = build_set_entry(data)
            log(f"Set: '{fsn}' ({len(data.get('setMembers', []))} members)")
            for m in data.get("setMembers", []):
                muuid = m.get("uuid")
                if muuid and muuid not in seen_uuids:
                    queue.append(muuid)
        else:
            concepts_by_uuid[uuid_val] = build_concept_entry(data)
            log(f"Concept: '{fsn}'")
            for a in data.get("answers", []):
                auuid = a.get("uuid")
                if auuid and auuid not in seen_uuids:
                    queue.append(auuid)

    concepts_list = list(concepts_by_uuid.values())
    sets_list = list(sets_by_uuid.values())

    out_concepts_file = None
    out_sets_file = None
    if out_dir:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        cf = out_path / "concepts_export.json"
        sf = out_path / "concept_sets_export.json"
        with open(cf, "w", encoding="utf-8") as f:
            json.dump(concepts_list, f, indent=2, ensure_ascii=False)
        with open(sf, "w", encoding="utf-8") as f:
            json.dump(sets_list, f, indent=2, ensure_ascii=False)
        out_concepts_file = str(cf)
        out_sets_file = str(sf)
        log(f"Wrote {len(concepts_list)} concepts to {cf}")
        log(f"Wrote {len(sets_list)} sets to {sf}")

    return {
        "concepts_count": len(concepts_list),
        "concept_sets_count": len(sets_list),
        "concepts": concepts_list,
        "concept_sets": sets_list,
        "concepts_file": out_concepts_file,
        "concept_sets_file": out_sets_file,
    }
