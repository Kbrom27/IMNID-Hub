#!/usr/bin/env python3
"""
DHIS2 Mother - Neonate Relationship Linker
============================================
A Tkinter desktop tool that logs into a DHIS2 instance, lets the user pick a
facility (org unit), a relationship type and an enrollment date range, and
then automatically creates "Mother - Neonate" tracked entity relationships
between the Maternal Inpatient Data (MID) and Neonatal Care Form (NCF)
programs.

MATCHING LOGIC (starts from the Neonate side, per the request):
  0. FIRST, try to match on Maternal MRN: "Maternal MRN n" as captured on the
     NCF NICU Admission Careform stage, compared against the "MRN" tracked
     entity attribute on the MID Mother record. Exact match (trimmed,
     case-insensitive) -> link immediately, no name check needed.
  1. If no MRN match (missing or not found), fall back to name matching.
     For every Neonate enrolled in the selected facility within the date
     range, read the mother's name as captured on the NCF NICU Admission
     Careform stage ("Mothers Name" + "Last Name of Mother:").
  2. For every Mother enrolled in the same facility within the same date
     range, read her name from the MID tracked entity attributes
     ("Mothers First Name" + "Mothers Father Name").
  3. If the full names match EXACTLY (case/whitespace-insensitive) -> link.
  4. If the names are only SIMILAR (fuzzy match >= threshold, spelling
     differences), it falls back to checking the Date of Delivery captured
     in the MID "Delivery summary" stage against the Date of delivery
     captured in the NCF "NICU Admission Careform" stage. If those dates
     match -> link. Otherwise it is left unmatched.
  5. A relationship is created (POST /api/tracker) with the Mother as the
     "from" side and the Neonate as the "to" side, matching how the
     relationship type is configured in the metadata.

IMPORTANT ASSUMPTION (please verify against your instance):
  The Maternal Inpatient Data program has no dedicated "Mother's Last Name"
  attribute. Ethiopian naming convention typically uses First name + Father's
  name as the equivalent of a surname, so this script compares the NCF
  "Last Name of Mother:" data element against the MID "Mothers Father Name"
  attribute. If that is not correct for your data, change TEA_MOTHER_LAST
  below to the correct attribute id.

All the DHIS2 object ids below were read directly out of the metadata.json
export you supplied (programs: "Maternal Inpatient Data" / "Neonatal Care
Form", relationship type: "Mother - Neonate").
"""

import json
import threading
import queue
import difflib
from datetime import datetime



import requests
from requests.auth import HTTPBasicAuth

# --------------------------------------------------------------------------
# Metadata constants (extracted from metadata.json)
# --------------------------------------------------------------------------

PROGRAM_MOTHER = "aLoraiFNkng"      # Maternal Inpatient Data
PROGRAM_NEONATE = "QYJKpoUeg9F"     # Neonatal Care Form

TET_MOTHER = "bek1qr4JiTC"          # Mother tracked entity type
TET_NEONATE = "aRXugBlzIPu"         # Neonate tracked entity type

RELATIONSHIP_TYPE_MOTHER_NEONATE = "Mym9LgC6uWZ"   # "Mother - Neonate "

# Mother (MID) tracked entity attributes
TEA_MOTHER_FIRST = "X9OEn2gPhss"    # Mothers First Name
TEA_MOTHER_LAST = "NZramclXjFR"     # Mothers Father Name  <-- see assumption above
TEA_MOTHER_MRN = "BeoO8RqxxO5"      # MRN

# Maternal MRN, as captured on the neonatal side. This is checked FIRST,
# before any name-based matching. Note: this data element ("Maternal MRN n")
# was originally on the "Neonatal referral form" stage per the metadata
# export, but per facility workflow it is now being entered on the NICU
# Admission Careform stage instead, so we read it from there.
DE_NEONATE_MOTHER_MRN = "WQLyilbfuoD"   # Maternal MRN n

# MID "Delivery summary" stage - Date of Delivery data element
STAGE_MOTHER_DELIVERY = "mdw5BoS50mb"
DE_MOTHER_DOD = "hjQZsV03OYe"       # Date of Delivery

# Neonate (NCF) "NICU Admission Careform" stage - mother's name + DOD as
# captured by the neonatal side
STAGE_NEONATE_ADMISSION = "mv8iC65nP21"
DE_NEONATE_MOTHER_FIRST = "pMrRODYCfQu"   # Mothers Name
DE_NEONATE_MOTHER_LAST = "Mg9CYZFWu7O"    # Last Name of Mother:
DE_NEONATE_DOD = "vKsjdwDyJhC"            # Date of delivery

DEFAULT_FUZZY_THRESHOLD = 0.85

# --------------------------------------------------------------------------
# DHIS2 API helper
# --------------------------------------------------------------------------


class Dhis2Client:
    def __init__(self, base_url: str, username: str, password: str):
        if not base_url or not str(base_url).strip():
            raise ValueError("DHIS2 base_url is required.")
        if not username or not str(username).strip():
            raise ValueError("DHIS2 username is required.")
        if not password or not str(password).strip():
            raise ValueError("DHIS2 password is required.")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(username, password)
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path, params=None, timeout=60):
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, payload, params=None, timeout=60):
        url = f"{self.base_url}{path}"
        resp = self.session.post(url, json=payload, params=params, timeout=timeout)
        return resp

    def whoami(self):
        return self._get("/api/me.json", params={"fields": "id,username"})

    def get_org_units(self):
        data = self._get(
            "/api/organisationUnits.json",
            params={
                "fields": "id,name,level,ancestors[name]",
                "paging": "false",
            },
            timeout=180,
        )
        return data.get("organisationUnits", [])

    def get_relationship_types(self):
        data = self._get(
            "/api/relationshipTypes.json",
            params={"fields": "id,name,fromConstraint,toConstraint", "paging": "false"},
        )
        return data.get("relationshipTypes", [])

    def get_tracked_entity_instances(self, program, org_unit, start_date, end_date,
                                      attributes=None, log=None):
        """Fetch ALL TEIs enrolled in `program` at `org_unit` (exact facility)
        with enrollment date between start_date and end_date, including
        attribute values and nested event data values.

        Some DHIS2 instances silently cap the response at the default page
        size even when paging=false is passed, so this pages through
        explicitly (page=1,2,3...) until a short page is returned, rather
        than trusting paging=false alone.
        """
        base_params = {
            "ou": org_unit,
            "ouMode": "SELECTED",
            "program": program,
            "programStartDate": start_date,
            "programEndDate": end_date,
            "fields": "trackedEntityInstance,orgUnit,"
                      "attributes[attribute,value],"
                      "enrollments[enrollment,enrollmentDate,orgUnit,"
                      "events[programStage,dataValues[dataElement,value]]]",
        }

        all_teis = []
        page = 1
        page_size = 200
        while True:
            params = dict(base_params)
            params["paging"] = "true"
            params["page"] = page
            params["pageSize"] = page_size
            params["totalPages"] = "true"
            data = self._get("/api/trackedEntityInstances.json", params=params, timeout=180)
            batch = data.get("trackedEntityInstances", [])
            all_teis.extend(batch)

            pager = data.get("pager", {})
            total_pages = pager.get("pageCount")
            if log:
                log(f"    ...page {page}: {len(batch)} record(s) "
                    f"(total so far: {len(all_teis)})")

            if total_pages is not None:
                if page >= total_pages or not batch:
                    break
            else:
                # No pager info returned - fall back to "short page means last page"
                if len(batch) < page_size:
                    break
            page += 1

        return all_teis

    def create_relationship(self, relationship_type, from_tei, to_tei):
        payload = {
            "relationships": [
                {
                    "relationshipType": relationship_type,
                    "from": {"trackedEntity": {"trackedEntity": from_tei}},
                    "to": {"trackedEntity": {"trackedEntity": to_tei}},
                }
            ]
        }
        resp = self._post(
            "/api/tracker", payload, params={"async": "false", "importStrategy": "CREATE"}
        )
        return resp


# --------------------------------------------------------------------------
# Matching helpers
# --------------------------------------------------------------------------


def norm(text):
    return (text or "").strip().lower()


def full_name(first, last):
    return f"{norm(first)} {norm(last)}".strip()


def get_attr_value(tei, attribute_id):
    for a in tei.get("attributes", []):
        if a.get("attribute") == attribute_id:
            return a.get("value")
    return None


def get_event_dv(tei, stage_id, de_id):
    for enr in tei.get("enrollments", []):
        for ev in enr.get("events", []):
            if ev.get("programStage") == stage_id:
                for dv in ev.get("dataValues", []):
                    if dv.get("dataElement") == de_id:
                        return dv.get("value")
    return None


def date_only(value):
    if not value:
        return None
    return value[:10]


class MotherRecord:
    def __init__(self, tei):
        self.tei_id = tei["trackedEntityInstance"]
        self.first = get_attr_value(tei, TEA_MOTHER_FIRST)
        self.last = get_attr_value(tei, TEA_MOTHER_LAST)
        self.mrn = get_attr_value(tei, TEA_MOTHER_MRN)
        self.full_name = full_name(self.first, self.last)
        self.dod = date_only(get_event_dv(tei, STAGE_MOTHER_DELIVERY, DE_MOTHER_DOD))


class NeonateRecord:
    def __init__(self, tei):
        self.tei_id = tei["trackedEntityInstance"]
        self.mother_first = get_event_dv(tei, STAGE_NEONATE_ADMISSION, DE_NEONATE_MOTHER_FIRST)
        self.mother_last = get_event_dv(tei, STAGE_NEONATE_ADMISSION, DE_NEONATE_MOTHER_LAST)
        self.mother_mrn = get_event_dv(tei, STAGE_NEONATE_ADMISSION, DE_NEONATE_MOTHER_MRN)
        self.mother_full_name = full_name(self.mother_first, self.mother_last)
        self.dod = date_only(get_event_dv(tei, STAGE_NEONATE_ADMISSION, DE_NEONATE_DOD))


def find_match(neonate, mothers, threshold):
    """Returns (mother_record, method, debug_note).

    Matching order:
      0. Exact Maternal MRN match (highest priority, checked first).
      1. Exact full-name match (first+last), case/whitespace-insensitive.
      2. Fuzzy full-name match (similarity >= threshold) CONFIRMED by an
         identical Date of Delivery on both sides.
      3. Fallback when the neonate record only has the mother's first name
         (no/blank "Last Name of Mother:"), or when no full-name match was
         found above threshold: match on first name alone (fuzzy, >=
         threshold) CONFIRMED by an identical Date of Delivery on both sides.
    """
    if not neonate.mother_first and not neonate.mother_last and not neonate.mother_mrn:
        return None, None, "no mother name or MRN captured on the neonate record"

    candidates = [m for m in mothers if m.first or m.last or m.mrn]
    if not candidates:
        return None, None, "no mothers with name/MRN data in this facility/date range"

    # ---- 0. Maternal MRN match (highest priority - checked before names) ----
    if neonate.mother_mrn:
        n_mrn = norm(neonate.mother_mrn)
        for m in candidates:
            if m.mrn and norm(m.mrn) == n_mrn:
                return m, "MRN match", None

    # ---- 1. exact full-name match ----
    if neonate.mother_full_name:
        for m in candidates:
            if m.full_name and m.full_name == neonate.mother_full_name:
                return m, "exact full name match", None

    # ---- 2. fuzzy full-name match + matching date of delivery ----
    best_full, best_full_score = None, 0.0
    if neonate.mother_full_name:
        for m in candidates:
            if not m.full_name:
                continue
            score = difflib.SequenceMatcher(None, neonate.mother_full_name, m.full_name).ratio()
            if score > best_full_score:
                best_full, best_full_score = m, score

        if best_full and best_full_score >= threshold:
            if neonate.dod and best_full.dod and neonate.dod == best_full.dod:
                return best_full, f"fuzzy full name match ({best_full_score:.2f}) + matching date of delivery", None

    # ---- 3. first-name-only fallback + matching date of delivery ----
    # Used when: last name wasn't captured on the neonate record, OR the
    # full-name fuzzy match above didn't clear the bar / dates didn't agree.
    best_first, best_first_score = None, 0.0
    if neonate.mother_first:
        for m in candidates:
            if not m.first:
                continue
            score = difflib.SequenceMatcher(None, norm(neonate.mother_first), norm(m.first)).ratio()
            if score > best_first_score:
                best_first, best_first_score = m, score

        if best_first and best_first_score >= threshold:
            if neonate.dod and best_first.dod and neonate.dod == best_first.dod:
                return best_first, f"first-name-only match ({best_first_score:.2f}) + matching date of delivery", None

    # ---- nothing matched: build a helpful debug note ----
    notes = []
    if best_full:
        notes.append(
            f"best full-name candidate {best_full.tei_id} '{best_full.full_name}' "
            f"score={best_full_score:.2f} dod={best_full.dod}"
        )
    if best_first:
        notes.append(
            f"best first-name candidate {best_first.tei_id} '{best_first.first}' "
            f"score={best_first_score:.2f} dod={best_first.dod}"
        )
    debug = "; ".join(notes) if notes else "no similarly-named mothers found"
    return None, None, debug


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------


class MotherNeonateLinker:
    def __init__(self, client: Dhis2Client, log_callback=None):
        if client is None:
            raise ValueError("Dhis2Client is required.")
        self.client = client
        self.log_callback = log_callback

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def _run_worker(self, ou_id, ou_display, rel_type_id, start_date, end_date,
                     threshold, dry_run):
        try:
            self.log("=" * 70)
            self.log(f"Facility: {ou_display}")
            self.log(f"Enrollment date range: {start_date} to {end_date}")
            self.log(f"Fuzzy match threshold: {threshold}")
            if dry_run:
                self.log("DRY RUN MODE: no relationships will be created.")

            self.log("Fetching Mothers (Maternal Inpatient Data) enrolled at this facility...")
            mother_teis = self.client.get_tracked_entity_instances(
                PROGRAM_MOTHER, ou_id, start_date, end_date, log=self.log
            )
            mothers = [MotherRecord(t) for t in mother_teis]
            self.log(f"  -> {len(mothers)} mother enrollments found.")

            self.log("Fetching Neonates (Neonatal Care Form) enrolled at this facility...")
            neonate_teis = self.client.get_tracked_entity_instances(
                PROGRAM_NEONATE, ou_id, start_date, end_date, log=self.log
            )
            neonates = [NeonateRecord(t) for t in neonate_teis]
            self.log(f"  -> {len(neonates)} neonate enrollments found.")

            linked = 0
            already_linked = 0
            failed = 0
            skipped_no_mother_name = 0
            unmatched = 0
            already_used_mothers = set()

            for n in neonates:
                if not n.mother_first and not n.mother_last:
                    skipped_no_mother_name += 1
                    continue

                candidate_mothers = [m for m in mothers if m.tei_id not in already_used_mothers]
                match, method, debug_note = find_match(n, candidate_mothers, threshold)

                if not match:
                    unmatched += 1
                    self.log(
                        f"  [no match] Neonate {n.tei_id} - mother name on file: "
                        f"'{n.mother_full_name or n.mother_first}'"
                        + (f", MRN: '{n.mother_mrn}'" if n.mother_mrn else "")
                        + f" (delivery date: {n.dod})"
                        + (f"  |  {debug_note}" if debug_note else "")
                    )
                    continue

                self.log(
                    f"  [MATCH - {method}] Neonate {n.tei_id}  <->  Mother {match.tei_id}  "
                    f"('{n.mother_full_name or n.mother_first}' ~ '{match.full_name}')"
                )

                if dry_run:
                    linked += 1
                    already_used_mothers.add(match.tei_id)
                    continue

                resp = self.client.create_relationship(rel_type_id, match.tei_id, n.tei_id)
                outcome = self._interpret_relationship_response(resp)

                if outcome == "created":
                    linked += 1
                    already_used_mothers.add(match.tei_id)
                    self.log("      -> relationship created.")
                elif outcome == "already_exists":
                    already_linked += 1
                    already_used_mothers.add(match.tei_id)
                    self.log("      -> relationship already exists, skipping (counted as linked).")
                else:
                    failed += 1
                    self.log(f"      -> FAILED (HTTP {resp.status_code}): {resp.text[:500]}")

            summary = (
                f"Done. Newly linked: {linked}. Already linked (found existing): {already_linked}. "
                f"Failed: {failed}. Unmatched: {unmatched}. "
                f"Neonates missing mother name data: {skipped_no_mother_name}. "
                f"(Total neonates processed: {len(neonates)})"
            )
            self.log(summary)
            if hasattr(self, "msg_queue") and self.msg_queue:
                self.msg_queue.put(("run_done", summary))
            return {
                "linked": linked,
                "already_linked": already_linked,
                "failed": failed,
                "unmatched": unmatched,
                "skipped_no_mother_name": skipped_no_mother_name,
                "total": len(neonates),
                "summary": summary
            }

        except Exception as e:
            if hasattr(self, "msg_queue") and self.msg_queue:
                self.msg_queue.put(("run_error", str(e)))
            raise

    @staticmethod
    def _interpret_relationship_response(resp):
        """Returns 'created', 'already_exists', or 'failed'."""
        if resp.status_code in (200, 201):
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                return "created"
            status = body.get("status", "OK")
            if status == "OK":
                return "created"
            # status could be ERROR even with 200 in some versions - fall through to error scan
            body_text = json.dumps(body)
        else:
            body_text = resp.text

        # Look for DHIS2's "relationship already exists" validation error (E4018)
        # regardless of the HTTP status code used to report it (some versions use
        # 409, others wrap it in a 200 tracker import report).
        if "E4018" in body_text or "already exists" in body_text.lower():
            return "already_exists"

        return "failed"


