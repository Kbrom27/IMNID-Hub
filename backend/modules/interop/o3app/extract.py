from __future__ import annotations

import csv
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from o3app.clients.openmrs_client import ApiClient
from o3app.config import DETAIL_COLUMNS, MATERNAL_PROGRAM, NEONATAL_PROGRAM, is_patient_eligible_for_program
from o3app.export.extractors import (
    append_unique_value,
    attr_value,
    build_record_id,
    clean_csv_cell,
    clean_mrn_identifier,
    collect_orders_and_medications,
    extract_diagnoses,
    extract_entity_name,
    extract_maternal_mrn_identifier,
    extract_mrn_identifier,
    extract_obs_concept,
    extract_obs_value,
    get_root_obs,
    is_on_or_after_visit,
    normalize_date_filter,
    safe_dict,
    sanitize_filename,
    validate_date_range,
)
from o3app.schemas import FormRegistry, load_default_forms


def determine_program_from_visit_type(visit_type_name: str) -> str:
    normalized = visit_type_name.casefold()
    if any(marker in normalized for marker in ("nicu", "neonatal", "ncu")):
        return NEONATAL_PROGRAM
    if any(marker in normalized for marker in ("delivery", "labour", "labor", "obs", "obstetric")):
        return MATERNAL_PROGRAM
    return ""


def visit_matches_date_range(
    visit: Dict, visit_start_date: Optional[str], visit_end_date: Optional[str]
) -> bool:
    raw_date = visit.get("startDatetime") or visit.get("startDate")
    visit_date = raw_date[:10] if isinstance(raw_date, str) else None
    if visit_date is None:
        return visit_start_date is None and visit_end_date is None
    if visit_start_date and visit_date < visit_start_date:
        return False
    if visit_end_date and visit_date > visit_end_date:
        return False
    return True


def get_patients_by_visit_type(
    visits: Sequence[Dict],
    visit_type_uuid: str,
    visit_start_date: Optional[str],
    visit_end_date: Optional[str],
    visit_type_name: Optional[str] = None,
) -> List[Tuple[str, str, str]]:
    patients: List[Tuple[str, str, str]] = []
    seen = set()
    target_name = (visit_type_name or "").strip().lower()

    for visit in visits:
        vt = safe_dict(visit.get("visitType"))
        vt_uuid = vt.get("uuid", "")
        vt_name = str(vt.get("name") or vt.get("display") or "").strip().lower()

        matches_uuid = bool(visit_type_uuid and vt_uuid == visit_type_uuid)
        matches_name = bool(target_name and (vt_name == target_name or target_name in vt_name or vt_name in target_name))

        if not (matches_uuid or matches_name):
            continue
        if not visit_matches_date_range(visit, visit_start_date, visit_end_date):
            continue
        patient = visit.get("patient") or {}
        patient_uuid = patient.get("uuid")
        if patient_uuid and patient_uuid not in seen:
            seen.add(patient_uuid)
            raw_date = visit.get("startDatetime") or visit.get("startDate") or ""
            visit_date = raw_date[:10] if isinstance(raw_date, str) else ""
            raw_display = str(patient.get("display") or "").strip()
            mrn = extract_mrn_identifier(patient.get("identifiers"))
            if mrn:
                if " - " in raw_display:
                    name_part = raw_display.split(" - ", 1)[1].strip()
                    display = f"{mrn} - {name_part}"
                else:
                    display = f"{mrn} - {raw_display}" if raw_display else mrn
            else:
                if " - " in raw_display:
                    first_part, name_part = raw_display.split(" - ", 1)
                    cleaned_id = clean_mrn_identifier(first_part.strip())
                    display = f"{cleaned_id} - {name_part.strip()}"
                else:
                    display = clean_mrn_identifier(raw_display)
            patients.append((patient_uuid, display, visit_date, patient.get("identifiers")))

    return patients


def o3_concept_label(obs: Dict, registry: FormRegistry) -> str:
    concept = obs.get("concept")
    if isinstance(concept, dict):
        uuid = concept.get("uuid", "")
        label = registry.concept_label(uuid)
        if label:
            return label
    return extract_obs_concept(obs)


def o3_obs_source_label(
    encounter: Optional[Dict],
    registry: FormRegistry,
    template_label: str = "",
) -> str:
    if isinstance(encounter, dict):
        form_name = extract_entity_name(encounter.get("form"))
        if form_name:
            return form_name
        form = encounter.get("form")
        if isinstance(form, dict):
            registered = registry.form_name_for_uuid(str(form.get("uuid") or "").strip())
            if registered:
                return registered
        encounter_type = encounter.get("encounterType") or {}
        registered = registry.form_name_for_encounter_type(
            str(encounter_type.get("uuid") or "").strip()
        )
        if registered:
            return registered
        encounter_type_label = extract_entity_name(encounter.get("encounterType"))
        if encounter_type_label:
            return encounter_type_label
    if template_label:
        return template_label
    return ""


def build_o3_obs_column(concept: str, source_label: str) -> str:
    if source_label:
        return f"{concept} [{source_label}]"
    return concept


def flatten_o3_obs(
    obs_list: Sequence[Dict],
    registry: FormRegistry,
    default_encounter: Optional[Dict] = None,
) -> List[Tuple[str, str, str]]:
    flattened: List[Tuple[str, str, str]] = []

    def visit_obs(
        obs: Dict,
        inherited_encounter: Optional[Dict],
        template_label: str = "",
    ) -> None:
        if not isinstance(obs, dict):
            return
        encounter = obs.get("encounter")
        if not isinstance(encounter, dict) or not encounter:
            encounter = inherited_encounter

        current_template_label = template_label
        group_members = obs.get("groupMembers")
        has_group_members = isinstance(group_members, list) and bool(group_members)
        if not current_template_label and has_group_members:
            current_template_label = o3_concept_label(obs, registry)

        concept = o3_concept_label(obs, registry)
        value = extract_obs_value(obs)
        if concept and value and not has_group_members:
            column = build_o3_obs_column(
                concept,
                o3_obs_source_label(encounter, registry, current_template_label),
            )
            flattened.append((concept, column, value))
        if has_group_members:
            for member in group_members:
                visit_obs(member, encounter, current_template_label)

    for obs in get_root_obs(obs_list):
        visit_obs(obs, default_encounter)

    return flattened


def flatten_o3_encounter_obs(
    encounters: Sequence[Dict],
    registry: FormRegistry,
) -> List[Tuple[str, str, str]]:
    flattened: List[Tuple[str, str, str]] = []
    for encounter in encounters:
        encounter_obs = encounter.get("obs")
        if not isinstance(encounter_obs, list):
            continue
        flattened.extend(flatten_o3_obs(encounter_obs, registry, default_encounter=encounter))
    return flattened


def _extract_person_uuid(person_ref: object) -> str:
    if isinstance(person_ref, dict):
        return str(person_ref.get("uuid") or person_ref.get("person", {}).get("uuid") or "").strip()
    if isinstance(person_ref, str):
        return person_ref.strip()
    return ""


def find_mother_uuid_from_relationships(
    relationships: Sequence[Dict], newborn_uuid: str
) -> Optional[str]:
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        rel_type = rel.get("relationshipType") or {}
        a_is_to_b = str(rel_type.get("aIsToB") or rel_type.get("displayAIsToB") or "").strip().lower()
        b_is_to_a = str(rel_type.get("bIsToA") or rel_type.get("displayBIsToA") or "").strip().lower()
        rel_display = str(rel_type.get("display") or "").strip().lower()
        rel_name = str(rel_type.get("name") or "").strip().lower()
        uuid_a = _extract_person_uuid(rel.get("personA"))
        uuid_b = _extract_person_uuid(rel.get("personB"))

        if uuid_b == newborn_uuid:
            if any(k in a_is_to_b for k in ("mother", "maternal", "parent")) or any(k in rel_display for k in ("mother", "parent")) or any(k in rel_name for k in ("mother", "parent")):
                return uuid_a
        if uuid_a == newborn_uuid:
            if any(k in b_is_to_a for k in ("mother", "maternal", "parent")) or any(k in rel_display for k in ("mother", "parent")) or any(k in rel_name for k in ("mother", "parent")):
                return uuid_b

        display_str = str(rel.get("display") or "").lower()
        if "mother" in display_str or "parent" in display_str:
            if uuid_b == newborn_uuid and uuid_a:
                return uuid_a
            if uuid_a == newborn_uuid and uuid_b:
                return uuid_b

    # Fallback: If only one relationship exists and connects to newborn, return other person
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        uuid_a = _extract_person_uuid(rel.get("personA"))
        uuid_b = _extract_person_uuid(rel.get("personB"))
        if uuid_b == newborn_uuid and uuid_a:
            return uuid_a
        if uuid_a == newborn_uuid and uuid_b:
            return uuid_b
    return None


def extract_maternal_data_for_newborn(
    api: ApiClient,
    registry: FormRegistry,
    mother_uuid: str,
    visit_date: str = "",
) -> List[Tuple[str, str, str]]:
    entries: List[Tuple[str, str, str]] = []

    def add_nicu_field(concept: str, val: str) -> None:
        clean_val = str(val or "").strip()
        if clean_val:
            entries.append((concept, f"{concept} [NICU Admission Careform]", clean_val))

    try:
        mother_person = api.get_patient_person(mother_uuid) or {}
    except Exception:
        mother_person = {}

    mother_identifiers = []
    if hasattr(api, "get_patient_identifiers"):
        try:
            mother_identifiers = api.get_patient_identifiers(mother_uuid) or []
        except Exception:
            mother_identifiers = []

    pref_name = mother_person.get("preferredName") or {}
    gname = str(pref_name.get("givenName") or "").strip()
    fname = str(pref_name.get("familyName") or "").strip()
    mname = str(pref_name.get("middleName") or "").strip()

    mother_dob = str(mother_person.get("birthdate", "") or "").strip()
    mother_age = ""
    if mother_dob and len(mother_dob) >= 4:
        try:
            from datetime import date, datetime
            b_year = int(mother_dob[:4])
            b_month = int(mother_dob[5:7]) if len(mother_dob) >= 7 else 1
            b_day = int(mother_dob[8:10]) if len(mother_dob) >= 10 else 1
            ref_date = None
            if visit_date and len(visit_date) >= 10:
                try:
                    ref_date = datetime.strptime(visit_date[:10], "%Y-%m-%d").date()
                except Exception:
                    ref_date = None
            if not ref_date:
                ref_date = date.today()
            calc_age = ref_date.year - b_year - ((ref_date.month, ref_date.day) < (b_month, b_day))
            if calc_age > 0:
                mother_age = str(calc_age)
        except Exception:
            pass

    if not mother_age:
        raw_age = str(mother_person.get("age", "") or "").strip()
        if raw_age and raw_age != "0":
            mother_age = raw_age

    mother_phone = attr_value(mother_person, "primaryContact") or attr_value(mother_person, "secondaryContact")
    mother_edu = attr_value(mother_person, "Education Details") or attr_value(mother_person, "education_details")
    mother_occ = attr_value(mother_person, "occupation")
    mother_rel = attr_value(mother_person, "caste") or attr_value(mother_person, "religion")
    mother_mrn = extract_maternal_mrn_identifier(mother_identifiers)

    # If MRN not in patient_identifiers, try getting patient by person uuid or patient uuid
    if not mother_mrn and hasattr(api, "get_json"):
        try:
            p_data = api.get_json(f"patient?person={mother_uuid}&v=full")
            p_results = p_data.get("results") if isinstance(p_data, dict) else []
            if p_results and isinstance(p_results, list):
                mother_mrn = extract_maternal_mrn_identifier(p_results[0].get("identifiers", []))
        except Exception:
            pass

    if not mother_mrn and hasattr(api, "get_json"):
        try:
            p_data = api.get_json(f"patient/{mother_uuid}?v=full")
            if isinstance(p_data, dict):
                mother_mrn = extract_maternal_mrn_identifier(p_data.get("identifiers", []))
        except Exception:
            pass

    pref_addr = mother_person.get("preferredAddress") or {}
    mother_reg = str(pref_addr.get("stateProvince") or "").strip()
    mother_zone = str(pref_addr.get("countyDistrict") or "").strip()
    mother_wereda = str(pref_addr.get("cityVillage") or "").strip()
    mother_kebele = str(pref_addr.get("address1") or pref_addr.get("address2") or "").strip()

    mother_phone2 = attr_value(mother_person, "secondaryContact")

    # Demographics: "Mothers Name" takes Given name only
    if gname:
        add_nicu_field("Mother’s Name", gname)
        add_nicu_field("Mother's Name", gname)
        add_nicu_field("Mothers Name", gname)
        entries.append(("Mother's Name", "Mothers Name [NICU Admission Careform]", gname))
        entries.append(("Mother's Name", "Mother's Name [NICU Admission Careform]", gname))

    # Demographics: "Mother's Age" in NICU admission care form from DOB or age
    if mother_age:
        add_nicu_field("Mother's Age", mother_age)
        add_nicu_field("Mother’s Age", mother_age)
        entries.append(("Mother's Age", "Mother's Age [NICU Admission Careform]", mother_age))

    # Demographics: "Last Name of Mother:" from Family name
    if fname:
        add_nicu_field("Last Name of Mother", fname)
        add_nicu_field("Last Name of Mother:", fname)
        entries.append(("Last Name of Mother", "Last Name of Mother: [NICU Admission Careform]", fname))
        entries.append(("Last Name of Mother", "Last Name of Mother [NICU Admission Careform]", fname))

    if mother_dob and len(mother_dob) >= 10:
        add_nicu_field("Maternal date of birth (DOB) information", mother_dob[:10])
        add_nicu_field("Year of Maternal Date of Birth (DOB)", mother_dob[:4])
        add_nicu_field("Month of Maternal Date of Birth (DOB):", mother_dob[5:7])
        add_nicu_field("Day of Maternal Date of Birth (DOB):", mother_dob[8:10])

    # Demographics: "Maternal MRN n" in NICU admission care form from 6-digit MRN
    if mother_mrn:
        add_nicu_field("Maternal MRN", mother_mrn)
        entries.append(("Maternal MRN", "Maternal MRN n [NICU Admission Careform]", mother_mrn))
        entries.append(("Maternal MRN", "Maternal MRN [NICU Admission Careform]", mother_mrn))

    add_nicu_field("Phone number", mother_phone)
    if mother_phone2:
        add_nicu_field("Phone Number 2:", mother_phone2)
    add_nicu_field("Mother's educational status", mother_edu)
    add_nicu_field("Mother's occupation", mother_occ)
    add_nicu_field("Mother's Religion", mother_rel)
    add_nicu_field("Region", mother_reg)
    add_nicu_field("Zone", mother_zone)
    add_nicu_field("Wereda", mother_wereda)
    add_nicu_field("Kebele", mother_kebele)

    try:
        mother_encounters = api.get_patient_encounters(mother_uuid) or []
    except Exception:
        mother_encounters = []
    try:
        mother_obs = api.get_patient_obs(mother_uuid) or []
    except Exception:
        mother_obs = []

    m_encounter_obs = flatten_o3_encounter_obs(mother_encounters, registry)
    seen_pairs = {(c, v) for c, _col, v in m_encounter_obs}
    m_standalone = [
        (c, col, v)
        for c, col, v in flatten_o3_obs(mother_obs, registry)
        if (c, v) not in seen_pairs
    ]
    all_mother_obs = m_encounter_obs + m_standalone

    for concept, _column, val in all_mother_obs:
        c_norm = concept.strip().lower()
        if not val:
            continue

        if c_norm in ("mode of delivery", "mode of delivery:"):
            add_nicu_field("Mode of delivery", val)
        elif c_norm == "antenatal corticosteroids":
            add_nicu_field("Antenatal Corticosteroids", val)
        elif c_norm in ("date of delivery:", "date of delivery"):
            add_nicu_field("Date of delivery", val[:10])
        elif c_norm in ("time of delivery:", "time of delivery", "time"):
            add_nicu_field("Time of birth", val)
        elif c_norm in ("apgar score 1st min", "apgar score 1st min:"):
            add_nicu_field("APGAR score 1st min", val)
            add_nicu_field("APGAR score known?", "Yes")
        elif c_norm in ("apgar score 5th min", "apgar score 5th min:"):
            add_nicu_field("APGAR score 5th min", val)
        elif c_norm in ("apgar score 10th min", "apgar score 10th min:"):
            add_nicu_field("APGAR score 10th min", val)
        elif c_norm in ("number of newborns:", "number of newborns"):
            add_nicu_field("Multiple Births:", val)
            if str(val).strip() in ("1", "Single", "Singleton"):
                add_nicu_field("Is the newborn from a singleton delivery", "Yes")
            else:
                add_nicu_field("Is the newborn from a singleton delivery", "No")
        elif c_norm in ("hiv result:", "hiv result"):
            add_nicu_field("Mother HIV status", val)
        elif "arv rx for mother" in c_norm:
            add_nicu_field("HIV Treatment for Mother:", val)
            add_nicu_field("on HAART", "Yes" if val and val.lower() != "none" else "No")
        elif "arv px for newborn" in c_norm:
            add_nicu_field("HIV Treatment for Baby:", val)
            add_nicu_field("Infant given prophylaxis", "Yes" if val and val.lower() != "none" else "No")
        elif "immunizations and interventions" in c_norm:
            val_lower = val.lower()
            if "vitamin k" in val_lower:
                add_nicu_field("Vitamin K given", "Yes")
            if "chlorhexidine" in val_lower:
                add_nicu_field("Cord Chlorhexidine Administered", "Yes")
            if "ttc" in val_lower or "eye ointment" in val_lower:
                add_nicu_field("TTC eye ointment", "Yes")
            if "breastfeeding" in val_lower:
                add_nicu_field("Breastfeeding initiated within 1 hr of birth", "Yes")
            if "skin to skin" in val_lower or "skin-to-skin" in val_lower:
                add_nicu_field("Placed skin-to-skin at birth", "Yes")
        elif c_norm == "obstetric condition at delivery":
            add_nicu_field("Maternal Status", val)
        elif c_norm in ("parity", "para"):
            add_nicu_field("Para", val)
        elif c_norm == "spontaneous":
            add_nicu_field("Abortion(Spontaneous)", val)
        elif c_norm == "induced":
            add_nicu_field("Abortion(Induced)", val)
        elif c_norm == "lnmp known?":
            add_nicu_field("LNMP known?", val)
        elif c_norm in ("lnmp date", "lnmp"):
            add_nicu_field("LNMP", val[:10])
        elif "current gestational age (from lmp in weeks)" in c_norm:
            add_nicu_field("Weeks:", val)
            add_nicu_field("Gestational Age", val)
        elif "remaining gestational age (from lmp in days)" in c_norm:
            add_nicu_field("Days of the Gestational Age", val)
        elif "early ultrasound" in c_norm and "weeks" in c_norm:
            add_nicu_field("GA by U/S", val)
        elif c_norm in ("anc contact", "anc visit"):
            add_nicu_field("ANC visit", val)
        elif c_norm in ("number of anc contacts", "number of anc visits"):
            add_nicu_field("Number of ANC visits", val)
        elif c_norm in ("place of anc visit", "place of anc follow up"):
            add_nicu_field("Place of ANC follow up", val)
        elif "provisions at the anc" in c_norm:
            if "tt" in val.lower() or "tetanus" in val.lower():
                add_nicu_field("TT Vaccine", "Yes")
        elif "co-existing medical complications" in c_norm:
            add_nicu_field("Maternal Chronic Conditions:", val)
            if "diabetes" in val.lower():
                add_nicu_field("Type of Diabetes", val)
            if "hypertension" in val.lower():
                add_nicu_field("Type of Hypertension", val)
        elif "past obstetric complications" in c_norm:
            add_nicu_field("Significant events during current or previous pregnancy:", val)
            if "stillbirth" in val.lower():
                add_nicu_field("Number of stillbirths", val)
        elif c_norm in ("membrane status", "raptured", "membrane ruptured"):
            add_nicu_field("Membrane ruptured", val)
        elif c_norm in ("duration", "duration of rapture of membrane (in hrs)"):
            add_nicu_field("Duration of rapture of membrane (in hrs)", val)
            add_nicu_field("hours prior to delivery", val)
        elif c_norm in ("amniotic fluid", "amniotic fluid was"):
            add_nicu_field("Amniotic fluid was", val)
        elif c_norm in ("uterine contractions in 10 min", "labor was"):
            add_nicu_field("Labor was", val)
        elif "blood group" in c_norm:
            add_nicu_field("Blood group and Rh", val)
        elif c_norm == "vdrl":
            add_nicu_field("VDRL", val)
        elif c_norm == "hbsag":
            add_nicu_field("HBsAg", val)

    entries.extend(all_mother_obs)
    return entries


def build_o3_patient_row(
    api: ApiClient,
    registry: FormRegistry,
    patient_uuid: str,
    display: str,
    org_unit_code: str,
    program_value: str,
    visit_date: str = "",
    patient_identifiers: Optional[Sequence[Dict]] = None,
) -> Tuple[List[str], Dict[str, str]]:
    identifiers = patient_identifiers
    if identifiers is None and hasattr(api, "get_patient_identifiers"):
        try:
            identifiers = api.get_patient_identifiers(patient_uuid)
        except Exception:
            identifiers = []

    mrn = extract_mrn_identifier(identifiers)
    if mrn:
        patient_id = clean_mrn_identifier(mrn)
        if " - " in display:
            name_part = display.split(" - ", 1)[1].strip()
            display = f"{patient_id} - {name_part}"
        elif not display:
            display = patient_id
    else:
        patient_id = clean_mrn_identifier(display.split(" - ", 1)[0].strip())
        if " - " in display:
            _old_id, name_part = display.split(" - ", 1)
            display = f"{patient_id} - {name_part.strip()}"
        elif not display:
            display = patient_id

    record_id = build_record_id(org_unit_code, patient_id)

    person = api.get_patient_person(patient_uuid) or {}
    if not is_patient_eligible_for_program(
        gender=person.get("gender"),
        age_val=person.get("age"),
        program_value=program_value,
        birthdate=person.get("birthdate"),
        visit_date=visit_date,
    ):
        return [], {}

    obs_list = api.get_patient_obs(patient_uuid) or []
    encounters = api.get_patient_encounters(patient_uuid) or []
    direct_orders = api.get_patient_orders(patient_uuid) or []

    if visit_date:
        encounters = [
            enc for enc in encounters
            if is_on_or_after_visit(enc.get("encounterDatetime") or enc.get("encounterDate"), visit_date)
        ]
        filtered_obs = []
        for obs in obs_list:
            obs_dt = obs.get("obsDatetime")
            if not obs_dt and isinstance(obs.get("encounter"), dict):
                obs_dt = obs.get("encounter", {}).get("encounterDatetime")
            if is_on_or_after_visit(obs_dt, visit_date):
                filtered_obs.append(obs)
        obs_list = filtered_obs
        direct_orders = [
            ord_item for ord_item in direct_orders
            if is_on_or_after_visit(ord_item.get("dateActivated") or ord_item.get("dateCreated") or ord_item.get("scheduledDate"), visit_date)
        ]

    encounter_obs_entries = flatten_o3_encounter_obs(encounters, registry)
    seen_encounter_pairs = {(concept, value) for concept, _column, value in encounter_obs_entries}
    standalone_obs_entries: List[Tuple[str, str, str]] = []
    for concept, column, value in flatten_o3_obs(obs_list, registry):
        if (concept, value) in seen_encounter_pairs:
            continue
        standalone_obs_entries.append((concept, column, value))

    combined_obs_entries = encounter_obs_entries + standalone_obs_entries
    diagnoses = extract_diagnoses(combined_obs_entries)
    orders, medications, lab_results = collect_orders_and_medications(direct_orders, encounters)

    preferred_name = person.get("preferredName") or {}
    middle_name = str(preferred_name.get("middleName", "") or "").strip()
    preferred_address = person.get("preferredAddress") or {}
    cause_of_death = person.get("causeOfDeath", {})
    if isinstance(cause_of_death, dict):
        cause_of_death = cause_of_death.get("display", "")

    middle_name_val = attr_value(person, "middleNameLocal") or middle_name
    father_husband_val = attr_value(person, "Father/Husband Name") or middle_name

    row_visit_date = visit_date
    if not row_visit_date and encounters:
        first_enc_dt = encounters[0].get("encounterDatetime") or encounters[0].get("encounterDate") or ""
        if first_enc_dt:
            row_visit_date = str(first_enc_dt)[:10]

    row = [
        patient_uuid,
        display,
        patient_id,
        org_unit_code,
        record_id,
        program_value,
        str(preferred_name.get("givenName", "")),
        str(preferred_name.get("familyName", "")),
        str(person.get("age", "")),
        str(person.get("gender", "")),
        str(person.get("birthdate", "")),
        str(person.get("deathDate", "")),
        str(cause_of_death or ""),
        str(preferred_address.get("address1", "")),
        str(preferred_address.get("address2", "")),
        str(preferred_address.get("address3", "")),
        str(preferred_address.get("cityVillage", "")),
        str(preferred_address.get("stateProvince", "")),
        str(preferred_address.get("countyDistrict", "")),
        str(safe_dict(person.get("auditInfo")).get("dateCreated", "")),
        attr_value(person, "givenNameLocal"),
        attr_value(person, "familyNameLocal"),
        middle_name_val,
        attr_value(person, "caste"),
        attr_value(person, "class"),
        attr_value(person, "Education Details"),
        attr_value(person, "occupation"),
        attr_value(person, "primaryContact"),
        attr_value(person, "secondaryContact"),
        father_husband_val,
        attr_value(person, "Secondary Identifier"),
        attr_value(person, "landHolding"),
        attr_value(person, "debt"),
        attr_value(person, "distanceFromCenter"),
        attr_value(person, "isUrban"),
        attr_value(person, "cluster"),
        attr_value(person, "Ration Card Type"),
        attr_value(person, "familyIncome"),
        attr_value(person, "email"),
        attr_value(person, "Payment Method"),
        attr_value(person, "CBHI ID"),
        attr_value(person, "Expiry Date"),
        row_visit_date,
        " | ".join(diagnoses),
        " | ".join(lab_results),
        " | ".join(orders),
        " | ".join(medications),
    ]

    obs_values: Dict[str, str] = OrderedDict()
    for _concept, column, value in combined_obs_entries:
        append_unique_value(obs_values, column, value)

    # Encounter timestamp extraction for form event/report dates
    for enc in encounters:
        enc_form_name = o3_obs_source_label(enc, registry)
        if not enc_form_name:
            continue
        raw_dt = (
            enc.get("encounterDatetime")
            or safe_dict(enc.get("auditInfo")).get("dateCreated")
            or enc.get("dateCreated")
            or ""
        )
        if not raw_dt:
            continue
        enc_date = str(raw_dt)[:10]
        enc_time = str(raw_dt)[11:19] if len(str(raw_dt)) >= 19 else ""
        enc_datetime = f"{enc_date} {enc_time}".strip() if enc_time else enc_date

        append_unique_value(obs_values, f"Event Date [{enc_form_name}]", enc_date)
        append_unique_value(obs_values, f"Date [{enc_form_name}]", enc_date)
        append_unique_value(obs_values, f"Date and Time [{enc_form_name}]", enc_datetime)

        if enc_form_name == "NICU Admission Careform":
            append_unique_value(obs_values, "Date of Admission [NICU Admission Careform]", enc_date)
            if enc_time:
                append_unique_value(obs_values, "Time of Admission [NICU Admission Careform]", enc_time)
        elif "Discharge" in enc_form_name:
            append_unique_value(obs_values, f"Date and time of discharge [{enc_form_name}]", enc_datetime)
            append_unique_value(obs_values, f"Date of Discharge [{enc_form_name}]", enc_date)
        elif "Progress" in enc_form_name:
            append_unique_value(obs_values, f"Date progress [{enc_form_name}]", enc_date)
        elif "Referral" in enc_form_name:
            append_unique_value(obs_values, f"Date of referral [{enc_form_name}]", enc_date)

    # For newborns: resolve mother relationship and sync maternal values
    if program_value == NEONATAL_PROGRAM and hasattr(api, "get_patient_relationships"):
        try:
            relationships = api.get_patient_relationships(patient_uuid) or []
            mother_uuid = find_mother_uuid_from_relationships(relationships, patient_uuid)
            if mother_uuid:
                maternal_entries = extract_maternal_data_for_newborn(
                    api, registry, mother_uuid, visit_date
                )
                for _concept, column, val in maternal_entries:
                    if column not in obs_values or not obs_values[column]:
                        obs_values[column] = val
        except Exception:
            pass

    return row, obs_values



def write_o3_patients_csv(
    api: ApiClient,
    registry: FormRegistry,
    patients: Sequence[Tuple],
    output_filename: Path,
    org_unit_code: str,
    program_value: str,
    fetch_concurrency: int = 12,
) -> int:
    all_obs_columns: List[str] = []
    seen_obs_columns = set()
    buffered_rows: List[Tuple[List[str], Dict[str, str]]] = []

    with ThreadPoolExecutor(max_workers=max(1, fetch_concurrency)) as executor:
        futures = {}
        for item in patients:
            patient_uuid = item[0]
            display = item[1]
            visit_date = item[2] if len(item) > 2 else ""
            patient_identifiers = item[3] if len(item) > 3 else None
            fut = executor.submit(
                build_o3_patient_row,
                api,
                registry,
                patient_uuid,
                display,
                org_unit_code,
                program_value,
                visit_date,
                patient_identifiers,
            )
            futures[fut] = (patient_uuid, display)

        for future in list(futures.keys()):
            fixed_row, obs_values = future.result()
            if not fixed_row:
                continue
            for column in obs_values:
                if column not in seen_obs_columns:
                    seen_obs_columns.add(column)
                    all_obs_columns.append(column)
            buffered_rows.append((fixed_row, obs_values))

    output_filename.parent.mkdir(parents=True, exist_ok=True)
    with output_filename.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
        header = [clean_csv_cell(column) for column in DETAIL_COLUMNS + all_obs_columns]
        writer.writerow(header)
        for fixed_row, obs_values in buffered_rows:
            row = [clean_csv_cell(value) for value in fixed_row]
            for column in all_obs_columns:
                row.append(clean_csv_cell(obs_values.get(column, "")))
            writer.writerow(row)

    return len(buffered_rows)
