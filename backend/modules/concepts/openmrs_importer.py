"""OpenMRS 3.x Concept Importer.

Pushes concept JSON files into an OpenMRS 3.x instance using the REST API
(/ws/rest/v1/concept). Supports dry run, interactive class checking/remapping,
and multi-pass resolution (base concepts, answers, concept sets).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Callable, Optional, Any
import requests

CODED_DATATYPES = {"coded"}


def error_detail(exc: Exception) -> str:
    """Extract useful OpenMRS error message from a requests exception."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            data = resp.json()
            err = data.get("error", {})
            msg = err.get("message", "")
            field_errors = err.get("fieldErrors") or err.get("globalErrors")
            if field_errors:
                msg += " | " + json.dumps(field_errors)
            if msg:
                return f"HTTP {resp.status_code}: {msg}"
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
    return str(exc)


def extract_concept_name(entry: dict) -> str:
    """Extract concept name supporting both IMNID schema and raw OpenMRS REST payloads."""
    if not isinstance(entry, dict):
        return ""
    if "fully_specified_name" in entry and entry["fully_specified_name"]:
        return str(entry["fully_specified_name"]).strip()
    if "name" in entry and entry["name"]:
        if isinstance(entry["name"], str):
            return entry["name"].strip()
        if isinstance(entry["name"], dict) and "name" in entry["name"]:
            return str(entry["name"]["name"]).strip()
    if "display" in entry and entry["display"]:
        return str(entry["display"]).strip()
    if "names" in entry and isinstance(entry["names"], list):
        for n in entry["names"]:
            if isinstance(n, dict):
                if n.get("conceptNameType") == "FULLY_SPECIFIED" and n.get("name"):
                    return str(n["name"]).strip()
        for n in entry["names"]:
            if isinstance(n, dict) and n.get("name"):
                return str(n["name"]).strip()
            if isinstance(n, str) and n.strip():
                return n.strip()
    return ""


class OpenMRSClient:
    """Thin wrapper around the OpenMRS REST API for concept import/export operations."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json; charset=UTF-8",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def test_connection(self) -> dict:
        r = self.session.get(self._url("/ws/rest/v1/session"), timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("authenticated"):
            raise RuntimeError(
                "Server responded but authentication failed (check username/password)."
            )
        return data

    def get_concept(self, uuid: str) -> dict:
        r = self.session.get(
            self._url(f"/ws/rest/v1/concept/{uuid}"),
            params={"v": "full"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_concept_classes(self) -> dict[str, dict]:
        """Returns dict of lowercase name -> {uuid, name}."""
        results = []
        url = self._url("/ws/rest/v1/conceptclass")
        params = {"v": "default"}
        while url:
            r = self.session.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("results", []))
            next_url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    next_url = link.get("uri")
                    break
            url = next_url
            params = None
        return {c["name"].strip().lower(): c for c in results}

    def create_concept_class(
        self, name: str, description: str = "Created by concept importer"
    ) -> dict:
        r = self.session.post(
            self._url("/ws/rest/v1/conceptclass"),
            data=json.dumps({"name": name, "description": description}),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def find_concept_by_name(self, name: str) -> Optional[str]:
        """Search for an existing concept with this exact name.
        Returns uuid string, or None if not found, or 'AMBIGUOUS' if 2+ matches."""
        r = self.session.get(
            self._url("/ws/rest/v1/concept"),
            params={"q": name, "v": "full"},
            timeout=30,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        target = name.strip().lower()
        matches = []
        for c in results:
            names = [
                n["name"].strip().lower()
                for n in c.get("names", [])
                if n.get("conceptNameType") == "FULLY_SPECIFIED"
            ]
            if target in names:
                matches.append(c["uuid"])
        matches = list(dict.fromkeys(matches))
        if len(matches) == 0:
            return None
        if len(matches) == 1:
            return matches[0]
        return "AMBIGUOUS"

    def create_concept(self, entry: dict, resolved_class_name: str) -> dict:
        locale = entry.get("locale") or "en"
        if entry.get("names") and isinstance(entry["names"], list):
            names = entry["names"]
        else:
            concept_name = extract_concept_name(entry)
            names = [
                {
                    "name": concept_name,
                    "locale": locale,
                    "conceptNameType": "FULLY_SPECIFIED",
                }
            ]
            if entry.get("short_name"):
                names.append(
                    {
                        "name": entry["short_name"],
                        "locale": locale,
                        "conceptNameType": "SHORT",
                    }
                )
            for syn in entry.get("synonyms", []):
                names.append({"name": syn, "locale": locale})

        cls_name = resolved_class_name or entry.get("conceptClass") or entry.get("concept_class") or "Misc"
        body = {
            "names": names,
            "datatype": entry.get("datatype"),
            "conceptClass": cls_name,
        }
        for k in ("units", "allowDecimal", "lowAbsolute", "hiAbsolute", "lowNormal", "hiNormal", "lowCritical", "hiCritical"):
            if k in entry and entry[k] is not None:
                body[k] = entry[k]
        if entry.get("description"):
            body["descriptions"] = [
                {"description": entry["description"], "locale": locale}
            ]
        if entry.get("uuid"):
            body["uuid"] = entry["uuid"]

        r = self.session.post(
            self._url("/ws/rest/v1/concept"), data=json.dumps(body), timeout=30
        )
        if r.status_code >= 400 and entry.get("uuid"):
            body.pop("uuid", None)
            r = self.session.post(
                self._url("/ws/rest/v1/concept"),
                data=json.dumps(body),
                timeout=30,
            )
        r.raise_for_status()
        return r.json()

    def set_answers(self, concept_uuid: str, answer_uuids: list[str]) -> dict:
        body = {"answers": answer_uuids}
        r = self.session.post(
            self._url(f"/ws/rest/v1/concept/{concept_uuid}"),
            data=json.dumps(body),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def set_members(self, concept_uuid: str, member_uuids: list[str]) -> dict:
        body = {"set": True, "setMembers": member_uuids}
        r = self.session.post(
            self._url(f"/ws/rest/v1/concept/{concept_uuid}"),
            data=json.dumps(body),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


def check_concept_classes(
    client: OpenMRSClient,
    concepts: list[dict],
    concept_sets: Optional[list[dict]] = None,
) -> dict[str, Any]:
    existing = client.get_concept_classes()
    required = set()
    for c in concepts:
        cls = c.get("concept_class") or c.get("conceptClass")
        if cls:
            required.add(cls)
    for c in concept_sets or []:
        cls = c.get("concept_class") or c.get("conceptClass")
        if cls:
            required.add(cls)

    missing = sorted([c for c in required if c.strip().lower() not in existing])
    class_map = {c: c for c in required if c.strip().lower() in existing}
    return {
        "existing": sorted(v["name"] for v in existing.values()),
        "missing": missing,
        "class_map": class_map,
        "all_classes_exist": len(missing) == 0,
    }


def run_concept_import(
    client: OpenMRSClient,
    concepts: list[dict],
    concept_sets: Optional[list[dict]] = None,
    class_map: Optional[dict[str, str]] = None,
    dry_run: bool = True,
    auto_create_missing_classes: bool = True,
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[int, int, str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
    out_report_path: Optional[str | Path] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    prog = progress_fn or (lambda cur, tot, msg: None)
    is_canceled = is_canceled_fn or (lambda: False)

    concept_sets = concept_sets or []
    effective_class_map = dict(class_map or {})

    # Check/resolve missing classes
    try:
        existing_classes = client.get_concept_classes()
        required_classes = set()
        for c in concepts + concept_sets:
            cls = c.get("concept_class") or c.get("conceptClass")
            if cls:
                required_classes.add(cls)

        for cls in required_classes:
            if cls not in effective_class_map:
                if cls.strip().lower() in existing_classes:
                    effective_class_map[cls] = cls
                elif auto_create_missing_classes and not dry_run:
                    try:
                        client.create_concept_class(cls)
                        effective_class_map[cls] = cls
                        log(f"Created missing concept class on server: {cls}")
                    except Exception as e:
                        log(f"Could not create class {cls}: {error_detail(e)}")
                        effective_class_map[cls] = cls
                else:
                    effective_class_map[cls] = cls
    except Exception as e:
        log(f"Class pre-check note: {error_detail(e)}")

    name_cache: dict[str, Optional[str]] = {}
    results = []

    def resolve_name(name: str) -> Optional[str]:
        key = name.strip().lower()
        if key in name_cache:
            return name_cache[key]
        res = client.find_concept_by_name(name)
        name_cache[key] = res
        return res

    prefix = "[DRY RUN] " if dry_run else ""
    log(
        f"\n{'='*60}\n{prefix}Starting import: {len(concepts)} concepts, "
        f"{len(concept_sets)} concept sets\n{'='*60}"
    )

    created, reused, failed, ambiguous = 0, 0, 0, 0
    total = len(concepts) + len(concept_sets)
    step = 0

    # Pass 1: base concepts
    for c in concepts:
        if is_canceled():
            log("Stopped by user cancellation.")
            break
        step += 1
        name = extract_concept_name(c)
        if not name:
            continue
        prog(step, total, f"Importing concept: {name}")
        raw_class = c.get("concept_class") or c.get("conceptClass") or ""
        resolved_class = effective_class_map.get(raw_class, raw_class)

        existing = resolve_name(name)
        if existing == "AMBIGUOUS":
            ambiguous += 1
            log(f"{prefix}AMBIGUOUS: multiple existing concepts named '{name}' - skipped.")
            results.append(
                {
                    "type": "concept",
                    "name": name,
                    "status": "AMBIGUOUS",
                    "detail": "multiple matches on server",
                }
            )
            continue
        if existing:
            reused += 1
            log(f"{prefix}EXISTS: '{name}' already on server (uuid={existing}) - reusing.")
            results.append(
                {
                    "type": "concept",
                    "name": name,
                    "status": "REUSED",
                    "detail": existing,
                }
            )
            continue

        if dry_run:
            log(
                f"{prefix}Would create concept '{name}' (class={resolved_class}, datatype={c.get('datatype')})"
            )
            results.append(
                {
                    "type": "concept",
                    "name": name,
                    "status": "WOULD_CREATE",
                    "detail": "",
                }
            )
            name_cache[name.strip().lower()] = "DRY-RUN-PLACEHOLDER"
            created += 1
            continue

        try:
            res = client.create_concept(c, resolved_class)
            new_uuid = res["uuid"]
            name_cache[name.strip().lower()] = new_uuid
            created += 1
            log(f"{prefix}CREATED: '{name}' -> {new_uuid}")
            results.append(
                {
                    "type": "concept",
                    "name": name,
                    "status": "CREATED",
                    "detail": new_uuid,
                }
            )
        except Exception as e:
            failed += 1
            detail = error_detail(e)
            log(f"{prefix}FAILED: '{name}' - {detail}")
            results.append(
                {
                    "type": "concept",
                    "name": name,
                    "status": "FAILED",
                    "detail": detail,
                }
            )

    # Pass 2: answers for coded concepts
    if not is_canceled():
        log(f"\n{prefix}Resolving answers for coded concepts...")
        for c in concepts:
            if is_canceled():
                break
            if c.get("datatype", "").strip().lower() not in CODED_DATATYPES:
                continue
            if not c.get("answers"):
                continue
            name = extract_concept_name(c)
            if not name:
                continue
            concept_uuid = name_cache.get(name.strip().lower())
            if not concept_uuid or concept_uuid in (
                "AMBIGUOUS",
                "DRY-RUN-PLACEHOLDER",
            ):
                continue
            answer_uuids = []
            unresolved = []
            for ans_name in c["answers"]:
                auuid = resolve_name(ans_name)
                if auuid and auuid not in ("AMBIGUOUS", "DRY-RUN-PLACEHOLDER"):
                    answer_uuids.append(auuid)
                else:
                    unresolved.append(ans_name)
            if unresolved:
                log(
                    f"{prefix}  '{name}': could not resolve answer(s): {', '.join(unresolved)}"
                )
            if not answer_uuids:
                continue
            if dry_run:
                log(f"{prefix}  Would set {len(answer_uuids)} answer(s) on '{name}'")
                continue
            try:
                client.set_answers(concept_uuid, answer_uuids)
                log(f"  Set {len(answer_uuids)} answer(s) on '{name}'")
            except Exception as e:
                log(f"  FAILED setting answers on '{name}': {error_detail(e)}")

    # Pass 3: concept sets
    if not is_canceled() and concept_sets:
        log(f"\n{prefix}Processing concept sets...")
        for s in concept_sets:
            if is_canceled():
                break
            step += 1
            name = extract_concept_name(s)
            if not name:
                continue
            prog(step, total, f"Importing concept set: {name}")
            raw_class = s.get("concept_class") or s.get("conceptClass") or "ConvSet"
            resolved_class = effective_class_map.get(raw_class, raw_class)

            set_uuid = resolve_name(name)
            if not set_uuid or set_uuid == "DRY-RUN-PLACEHOLDER":
                if dry_run:
                    log(f"{prefix}Would create concept set '{name}'")
                    name_cache[name.strip().lower()] = "DRY-RUN-PLACEHOLDER"
                    results.append(
                        {
                            "type": "concept_set",
                            "name": name,
                            "status": "WOULD_CREATE",
                            "detail": "",
                        }
                    )
                else:
                    try:
                        s_entry = dict(s)
                        s_entry["datatype"] = "N/A"
                        res = client.create_concept(s_entry, resolved_class)
                        set_uuid = res["uuid"]
                        name_cache[name.strip().lower()] = set_uuid
                        created += 1
                        log(f"{prefix}CREATED SET: '{name}' -> {set_uuid}")
                        results.append(
                            {
                                "type": "concept_set",
                                "name": name,
                                "status": "CREATED",
                                "detail": set_uuid,
                            }
                        )
                    except Exception as e:
                        failed += 1
                        detail = error_detail(e)
                        log(f"{prefix}FAILED SET: '{name}' - {detail}")
                        results.append(
                            {
                                "type": "concept_set",
                                "name": name,
                                "status": "FAILED",
                                "detail": detail,
                            }
                        )
                        continue

            member_uuids = []
            unresolved = []
            for mem_name in s.get("members", []):
                muuid = resolve_name(mem_name)
                if muuid and muuid not in ("AMBIGUOUS", "DRY-RUN-PLACEHOLDER"):
                    member_uuids.append(muuid)
                else:
                    unresolved.append(mem_name)
            if unresolved:
                log(
                    f"{prefix}  '{name}': could not resolve member(s): {', '.join(unresolved)}"
                )
            if member_uuids and not dry_run and set_uuid:
                try:
                    client.set_members(set_uuid, member_uuids)
                    log(f"  Set {len(member_uuids)} member(s) on set '{name}'")
                except Exception as e:
                    log(f"  FAILED setting members on '{name}': {error_detail(e)}")

    if out_report_path and results:
        rp = Path(out_report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        with open(rp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["type", "name", "status", "detail"]
            )
            writer.writeheader()
            writer.writerows(results)

    return {
        "created": created,
        "reused": reused,
        "failed": failed,
        "ambiguous": ambiguous,
        "total": len(results),
        "results": results,
    }
