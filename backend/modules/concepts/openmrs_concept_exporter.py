"""Export All Concepts from OpenMRS 3.x.

Fetches all concepts from an OpenMRS 3.x server using REST pagination and writes
them to CSV or JSON format.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Callable, Optional
import requests

from backend.modules.concepts.openmrs_importer import OpenMRSClient, error_detail


def _extract_name(names_list: list, name_type: str) -> str:
    for n in names_list or []:
        if isinstance(n, dict) and (n.get("conceptNameType") or "").upper() == name_type:
            return n.get("name") or n.get("display") or ""
    return ""


def _extract_answers(concept: dict) -> str:
    answers = []
    for a in concept.get("answers", []) or []:
        if isinstance(a, dict):
            display = (a.get("display") or a.get("name") or "").strip()
            if display:
                answers.append(display)
        elif isinstance(a, str) and a.strip():
            answers.append(a.strip())
    return "; ".join(answers)


def export_all_concepts(
    client: OpenMRSClient,
    out_dir: str | Path,
    export_format: str = "csv",
    output_filename: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[int, int, str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    prog = progress_fn or (lambda cur, tot, msg: None)
    is_canceled = is_canceled_fn or (lambda: False)

    fmt = (export_format or "csv").strip().lower()
    if fmt not in ("csv", "json"):
        fmt = "csv"

    page_limit = 100
    results: list[dict] = []
    url = client._url("/ws/rest/v1/concept")
    params = {"v": "full", "limit": page_limit}
    page = 1

    log(f"Starting export of all concepts from OpenMRS 3.x in {fmt.upper()} format...")

    while url:
        if is_canceled():
            log("Concept export stopped by user cancellation.")
            break

        log(f"Fetching page {page}...")
        r = client.session.get(url, params=params, timeout=60)
        if r.status_code == 500:
            err = r.text
            if "fromIndex" in err and "toIndex" in err:
                log("Reached end of concept list.")
                break
            raise RuntimeError(f"Server error: {err[:300]}")
        r.raise_for_status()
        data = r.json()
        batch = data.get("results", [])
        results.extend(batch)
        log(f"Got {len(batch)} concepts (total so far: {len(results)})")
        prog(len(results), len(results) + page_limit, f"Fetched {len(results)} concepts")

        next_url = None
        for link in data.get("links", []):
            if link.get("rel") == "next":
                next_url = link.get("uri")
                break
        url = next_url
        params = None
        page += 1

    out_path = Path(out_dir)
    if out_path.suffix.lower() in (".csv", ".json"):
        out_file = out_path
        out_file.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path.mkdir(parents=True, exist_ok=True)
        fname = (output_filename or "").strip() or f"openmrs_all_concepts.{fmt}"
        if not fname.lower().endswith(f".{fmt}"):
            fname = f"{Path(fname).stem}.{fmt}"
        out_file = out_path / fname

    if fmt == "json":
        clean_output = []
        for c in results:
            if is_canceled():
                break
            names = []
            for n in c.get("names") or []:
                if isinstance(n, dict):
                    names.append({
                        "name": n.get("name") or n.get("display", ""),
                        "type": n.get("conceptNameType", ""),
                        "locale": n.get("locale", ""),
                    })
            answers = []
            for a in c.get("answers") or []:
                if isinstance(a, dict):
                    answers.append({
                        "uuid": a.get("uuid", ""),
                        "display": a.get("display") or a.get("name", ""),
                    })
                elif isinstance(a, str):
                    answers.append({"uuid": a, "display": a})
            dt = c.get("datatype", {})
            if isinstance(dt, dict):
                dt = dt.get("display") or dt.get("name") or ""
            cc = c.get("conceptClass", {})
            if isinstance(cc, dict):
                cc = cc.get("display") or cc.get("name") or ""
            clean_output.append({
                "uuid": c.get("uuid", ""),
                "conceptId": c.get("conceptId") or c.get("id") or "",
                "fullySpecifiedName": _extract_name(c.get("names", []), "FULLY_SPECIFIED") or c.get("display", ""),
                "shortName": _extract_name(c.get("names", []), "SHORT"),
                "datatype": dt,
                "conceptClass": cc,
                "names": names,
                "answers": answers,
            })
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(clean_output, f, indent=2, ensure_ascii=False)
    else:
        with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow([
                "Fully Specified Name",
                "Short Name",
                "UUID",
                "Concept ID",
                "Datatype",
                "Concept Class",
                "Answers",
            ])
            for c in results:
                if is_canceled():
                    break
                names = c.get("names") or []
                full_name = _extract_name(names, "FULLY_SPECIFIED") or c.get("display", "")
                short_name = _extract_name(names, "SHORT")
                uuid = c.get("uuid", "")
                concept_id = c.get("conceptId") or c.get("id") or ""
                dt = c.get("datatype", {})
                if isinstance(dt, dict):
                    dt = dt.get("display") or dt.get("name") or ""
                cc = c.get("conceptClass", {})
                if isinstance(cc, dict):
                    cc = cc.get("display") or cc.get("name") or ""
                answers = _extract_answers(c)
                writer.writerow([full_name, short_name, uuid, concept_id, dt, cc, answers])

    log(f"Export complete. Saved {len(results)} concepts to {out_file} ({fmt.upper()})")

    return {
        "status": "completed",
        "total_concepts": len(results),
        "export_format": fmt,
        "output_file": str(out_file),
    }
