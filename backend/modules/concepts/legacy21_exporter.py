"""OpenMRS 2.1 Concept Exporter (Legacy CM-11).

Exports concepts, answer options, and associated form metadata from legacy OpenMRS 2.1 instances
via REST pagination into standardized CSV format exactly matching the original OpenMRS 2.1 Concept Exporter.
"""

from __future__ import annotations

import csv
import os
import time
import traceback
from pathlib import Path
from typing import Callable, Optional
import requests
from requests.auth import HTTPBasicAuth
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAX_RETRIES = 3
PAGE_LIMIT = 100


def _get_with_retry(
    url: str,
    auth: HTTPBasicAuth,
    params: dict,
    description: str,
    log_fn: Callable[[str], None],
) -> Optional[requests.Response]:
    """GET with retries on network errors and 5xx. Returns the last Response,
    or None if the request could not be completed at all."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                auth=auth,
                params=params,
                verify=False,
                timeout=(10, 120),
                headers={"Accept": "application/json"},
            )
            # A 500 mentioning fromIndex/toIndex is the normal end-of-list signal on older OpenMRS versions
            if (
                response.status_code >= 500
                and attempt < MAX_RETRIES
                and "fromIndex" not in response.text
            ):
                log_fn(
                    f"{description}: HTTP {response.status_code}, retrying ({attempt + 1}/{MAX_RETRIES})..."
                )
                time.sleep(2 * attempt)
                continue
            return response
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            if attempt < MAX_RETRIES:
                log_fn(
                    f"{description}: {last_error}, retrying ({attempt + 1}/{MAX_RETRIES})..."
                )
                time.sleep(2 * attempt)
    if last_error is not None:
        log_fn(f"{description} failed after {MAX_RETRIES} attempts: {last_error}")
    return None


def fetch_all_concepts(
    base_url: str,
    auth: HTTPBasicAuth,
    log_fn: Callable[[str], None],
    progress_fn: Callable[[float], None],
    is_canceled_fn: Callable[[], bool],
) -> Optional[list[dict]]:
    """Fetch all concepts from OpenMRS with pagination matching original script."""
    all_concepts = []
    start_index = 0

    log_fn(f"Fetching concepts from {base_url}/concept")

    while True:
        if is_canceled_fn():
            log_fn("Concept export stopped by user.")
            break

        params = {
            "v": "custom:(uuid,display,datatype:(uuid,name),conceptClass:(uuid,name),names:(uuid,display,conceptNameType),answers:(uuid,display),conceptId)",
            "limit": PAGE_LIMIT,
            "startIndex": start_index,
        }

        try:
            log_fn(f"Fetching concepts batch: startIndex={start_index}")
            response = _get_with_retry(
                f"{base_url}/concept",
                auth,
                params,
                f"Fetching concepts (startIndex={start_index})",
                log_fn,
            )

            if response is None:
                return None

            log_fn(f"Response status: {response.status_code}")

            if response.status_code in (401, 403):
                log_fn(
                    "Authentication/permission error. Check username/password and that the user has access to concepts."
                )
                return None

            if response.status_code == 500:
                error_text = response.text
                if "fromIndex" in error_text and "toIndex" in error_text:
                    log_fn("Reached end of concepts list (500 error indicates no more data)")
                    break
                else:
                    error_msg = f"Error fetching concepts: {response.status_code}"
                    if response.text:
                        error_msg += f"\nResponse: {response.text[:500]}"
                    log_fn(error_msg)
                    return None

            if response.status_code != 200:
                error_msg = f"Error fetching concepts: {response.status_code}"
                if response.text:
                    error_msg += f"\nResponse: {response.text[:500]}"
                log_fn(error_msg)
                return None

            try:
                data = response.json()
            except ValueError:
                log_fn(f"Server returned a non-JSON response: {response.text[:300]}")
                return None

            results = data.get("results", [])
            log_fn(f"Fetched {len(results)} concepts in this batch")

            if not results:
                log_fn("No more concepts to fetch (empty batch)")
                break

            all_concepts.extend(results)
            start_index += PAGE_LIMIT

            progress = min(40, (start_index / (start_index + 100)) * 40)
            progress_fn(progress)

            if len(results) < PAGE_LIMIT:
                log_fn(f"Got fewer than {PAGE_LIMIT} results, reached end of list")
                break

        except requests.exceptions.Timeout:
            log_fn("Timeout while fetching concepts")
            return None
        except Exception as e:
            log_fn(f"Error fetching concepts: {str(e)}")
            return None

    log_fn(f"Total concepts fetched: {len(all_concepts)}")
    return all_concepts


def fetch_forms(
    base_url: str,
    auth: HTTPBasicAuth,
    log_fn: Callable[[str], None],
    is_canceled_fn: Callable[[], bool],
) -> Optional[dict[str, dict]]:
    """Fetch all forms from OpenMRS with pagination matching original script."""
    all_forms = {}
    start_index = 0

    log_fn(f"Fetching forms from {base_url}/form")

    while True:
        if is_canceled_fn():
            log_fn("Forms fetch stopped by user.")
            break

        params = {
            "v": "custom:(uuid,name,resources:(uuid,name),formFields:(uuid,concept:(uuid)))",
            "limit": PAGE_LIMIT,
            "startIndex": start_index,
        }

        try:
            log_fn(f"Fetching forms batch: startIndex={start_index}")
            response = _get_with_retry(
                f"{base_url}/form",
                auth,
                params,
                f"Fetching forms (startIndex={start_index})",
                log_fn,
            )

            if response is None:
                return None

            log_fn(f"Response status: {response.status_code}")

            if response.status_code in (401, 403):
                log_fn("Authentication/permission error fetching forms.")
                return None

            if response.status_code == 500:
                error_text = response.text
                if "fromIndex" in error_text and "toIndex" in error_text:
                    log_fn("Reached end of forms list (500 error indicates no more data)")
                    break
                else:
                    error_msg = f"Error fetching forms: {response.status_code}"
                    if response.text:
                        error_msg += f"\nResponse: {response.text[:500]}"
                    log_fn(error_msg)
                    return None

            if response.status_code != 200:
                error_msg = f"Error fetching forms: {response.status_code}"
                if response.text:
                    error_msg += f"\nResponse: {response.text[:500]}"
                log_fn(error_msg)
                return None

            try:
                data = response.json()
            except ValueError:
                log_fn(f"Server returned a non-JSON response: {response.text[:300]}")
                return None

            results = data.get("results", [])
            log_fn(f"Fetched {len(results)} forms in this batch")

            if not results:
                log_fn("No more forms to fetch (empty batch)")
                break

            for f in results:
                form_uuid = f.get("uuid")
                form_name = f.get("name")
                concept_uuids = []

                # Collect concepts from formFields (standard OpenMRS 2.x forms)
                for ff in f.get("formFields", []):
                    if isinstance(ff, dict):
                        c = ff.get("concept")
                        if isinstance(c, dict) and c.get("uuid"):
                            concept_uuids.append(c["uuid"])
                        elif isinstance(c, str):
                            concept_uuids.append(c)

                # Also inspect resources for concept associations
                for item in f.get("resources", []):
                    if isinstance(item, dict):
                        c = item.get("concept")
                        if isinstance(c, dict) and c.get("uuid"):
                            concept_uuids.append(c["uuid"])
                        elif isinstance(c, str):
                            concept_uuids.append(c)

                all_forms[form_uuid] = {
                    "name": form_name,
                    "concepts": list(set(concept_uuids)),
                }

            start_index += PAGE_LIMIT
            if len(results) < PAGE_LIMIT:
                log_fn(f"Got fewer than {PAGE_LIMIT} forms, reached end of list")
                break

        except requests.exceptions.Timeout:
            log_fn("Timeout while fetching forms")
            return None
        except Exception as e:
            log_fn(f"Error fetching forms: {str(e)}")
            return None

    log_fn(f"Total forms fetched: {len(all_forms)}")
    return all_forms


def export_legacy21_concepts(
    base_url: str,
    username: str,
    password: str,
    out_dir: str | Path,
    filename: str = "concepts.csv",
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[int, int, str], None]] = None,
    is_canceled_fn: Optional[Callable[[], bool]] = None,
) -> dict:
    """Exports concepts from OpenMRS 2.1 exactly matching openmrs_concept_exporter.py."""
    log = log_fn or (lambda msg: None)
    prog = progress_fn or (lambda cur, tot, msg: None)
    is_canceled = is_canceled_fn or (lambda: False)

    base = base_url.rstrip("/")
    if not base.endswith("/ws/rest/v1"):
        if not base.endswith("/openmrs"):
            base = f"{base}/openmrs/ws/rest/v1"
        else:
            base = f"{base}/ws/rest/v1"

    auth = HTTPBasicAuth(username, password)
    headers = {"Accept": "application/json"}

    log(f"Exporting from: {base}")
    log(f"Username: {username}")

    # Step 0: Test connection
    try:
        r = requests.get(
            f"{base}/session",
            auth=auth,
            headers=headers,
            verify=False,
            timeout=10,
        )
        if r.status_code == 200:
            if r.url and r.url.startswith("https://") and base.startswith("http://"):
                base = "https://" + base[len("http://") :]
                log(f"Auto-upgraded connection to HTTPS: {base}")

            s_data = r.json() if r.text else {}
            if not s_data.get("authenticated"):
                raise RuntimeError(
                    "Server reached, but authentication failed (check username/password)."
                )
            user = s_data.get("user", {})
            if user:
                log(f"Authenticated as: {user.get('display', 'unknown')}")
        else:
            raise RuntimeError(f"Connection failed with status: {r.status_code}")
    except Exception as e:
        log(f"Connection error: {str(e)}")
        raise

    def internal_progress(pct: float):
        prog(int(pct), 100, f"Progress: {int(pct)}%")

    # Step 1: Fetch all concepts
    all_concepts = fetch_all_concepts(
        base, auth, log, internal_progress, is_canceled
    )
    if all_concepts is None:
        raise RuntimeError("Failed to fetch concepts from OpenMRS 2.1.")

    if is_canceled():
        return {"status": "canceled", "total_concepts": 0, "output_file": ""}

    internal_progress(40)

    # Step 2: Fetch forms
    forms_dict = fetch_forms(base, auth, log, is_canceled)
    if forms_dict is None:
        raise RuntimeError("Failed to fetch forms from OpenMRS 2.1.")

    internal_progress(70)

    # Reverse index: concept uuid -> [(form name, form uuid), ...]
    concept_to_forms: dict[str, list[tuple[str, str]]] = {}
    for form_uuid, fdata in forms_dict.items():
        for cuuid in fdata.get("concepts", []):
            if cuuid:
                concept_to_forms.setdefault(cuuid, []).append(
                    (fdata.get("name", ""), form_uuid)
                )

    # Prepare file path
    fn = filename.strip() or "concepts.csv"
    if not fn.endswith(".csv"):
        fn += ".csv"

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    file_path = out_path / fn

    log(f"Writing {len(all_concepts)} concepts to CSV: {file_path}")

    # Write CSV with exact 8 columns from original script
    with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "EMR Concept Fully Specified Name",
                "EMR Concept short name",
                "EMR Concept UUID",
                "EMR Concept ID",
                "EMR concept Data Type",
                "EMR Options (Answers)",
                "EMR Form Name",
                "EMR Form UUID",
            ]
        )

        total_concepts = len(all_concepts)

        for i, c in enumerate(all_concepts):
            if is_canceled():
                break

            # Datatype
            datatype = c.get("datatype", {})
            datatype_name = datatype.get("name", "") if datatype else ""

            # Names
            names_list = c.get("names", [])
            fully_specified_name = ""
            short_name = ""

            for n in names_list:
                if isinstance(n, dict):
                    concept_name_type = n.get("conceptNameType", "")
                    if concept_name_type == "FULLY_SPECIFIED":
                        fully_specified_name = n.get("display", "")
                    elif concept_name_type == "SHORT":
                        short_name = n.get("display", "")

            # Concept ID
            concept_id = c.get("conceptId", "")

            # Options/answers
            options = []
            answers = c.get("answers", [])
            if isinstance(answers, list):
                for a in answers:
                    if isinstance(a, dict):
                        options.append(a.get("display", ""))
            options_str = "; ".join(filter(None, options))

            # Forms containing this concept
            form_names = []
            form_uuids = []
            concept_uuid = c.get("uuid", "")

            if concept_uuid:
                matched = concept_to_forms.get(concept_uuid, [])
                form_names = [name for name, _ in matched]
                form_uuids = [fuuid for _, fuuid in matched]

            form_names_str = "; ".join(filter(None, form_names))
            form_uuids_str = "; ".join(filter(None, form_uuids))

            writer.writerow(
                [
                    fully_specified_name,
                    short_name,
                    concept_uuid,
                    concept_id,
                    datatype_name,
                    options_str,
                    form_names_str,
                    form_uuids_str,
                ]
            )

            if total_concepts > 0:
                prog_pct = 70 + (i / total_concepts) * 30
                if i % 100 == 0 or i == total_concepts - 1:
                    internal_progress(prog_pct)
                    if i % 500 == 0 and i > 0:
                        log(f"Processed {i}/{total_concepts} concepts")

    internal_progress(100)
    log("Export completed successfully!")
    log(f"Total concepts exported: {total_concepts}")
    log(f"Total forms found: {len(forms_dict)}")

    return {
        "status": "completed",
        "total_concepts": total_concepts,
        "total_forms": len(forms_dict),
        "output_file": str(file_path),
        "filename": fn,
    }
