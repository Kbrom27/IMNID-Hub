"""
=============================================================================
  PROJECT  : IMNID Hub — HMIS OpenMRS 3 Reporting Integration
  FILE     : openmrs_service.py
  PURPOSE  : Fetch and normalize OpenMRS 3 maternal and neonatal records
             into the canonical format required by Ethiopian MoH HMIS
             RMH/NCH registers and monthly aggregate report generators.
=============================================================================
"""

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from openpyxl import Workbook

from backend.core.config import settings
from backend.core.database import get_server_connection
from backend.core.jobs.engine import JobContext

from backend.modules.hmis.rmh_delivery_register import (
    build_register as build_rmh_register,
    compute_tally as compute_rmh_tally,
    filter_df as filter_rmh_df,
    write_sheet as write_rmh_sheet,
    write_tally_sheet as write_rmh_tally_sheet,
    RAW as RMH_RAW,
)
from backend.modules.hmis.rmh_aggregate_report import (
    compute_indicators as compute_rmh_indicators,
    write_preview_excel as write_rmh_preview_excel,
    INDICATORS as RMH_INDICATORS,
)
from backend.modules.hmis.nh_neonatal_register import (
    build_register as build_nh_register,
    compute_tally as compute_nh_tally,
    filter_df as filter_nh_df,
    write_sheet as write_nh_sheet,
    write_tally_sheet as write_nh_tally_sheet,
    RAW as NH_RAW,
)
from backend.modules.hmis.nh_aggregate_report import (
    compute_indicators as compute_nh_indicators,
    write_preview_excel as write_nh_preview_excel,
    INDICATORS as NH_INDICATORS,
)

interop_dir = str(Path(__file__).resolve().parent.parent / "interop")
if interop_dir not in sys.path:
    sys.path.insert(0, interop_dir)

from o3app.sync import create_o3_api, run_o3_export
from clients.openmrs_client import normalize_base_url


def resolve_openmrs_creds(
    req_url: Optional[str] = None,
    req_user: Optional[str] = None,
    req_pw: Optional[str] = None,
) -> Dict[str, str]:
    conn = get_server_connection("openmrs") or {}
    return {
        "base_url": req_url or conn.get("base_url") or settings.OPENMRS_URL,
        "username": req_user or conn.get("username") or settings.OPENMRS_USERNAME,
        "password": req_pw or conn.get("secret") or settings.OPENMRS_PASSWORD,
    }


# ==============================================================================
# Helper to normalize column names regardless of brackets, colons, case
# ==============================================================================
def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Find first matching column from candidate names or keywords."""
    df_cols = list(df.columns)
    df_cols_lower = [str(c).strip().lower() for c in df_cols]

    # 1. Exact match
    for cand in candidates:
        if cand in df.columns:
            return cand

    # 2. Case-insensitive exact match
    for cand in candidates:
        cand_lower = cand.strip().lower()
        if cand_lower in df_cols_lower:
            idx = df_cols_lower.index(cand_lower)
            return df_cols[idx]

    # 3. Keyword / substring match
    for cand in candidates:
        cand_clean = re.sub(r"[^\w\s]", "", cand).strip().lower()
        if not cand_clean:
            continue
        for i, col_name in enumerate(df_cols):
            clean_col = re.sub(r"[^\w\s]", "", str(col_name)).strip().lower()
            if cand_clean in clean_col or clean_col in cand_clean:
                return col_name

    return None


def _safe_mode(series: Any, default: str = "") -> str:
    """Safely obtain the mode of a series/column without raising on empty/NaN."""
    if series is None:
        return default
    try:
        s = pd.Series(series).dropna()
        m = s.mode()
        if not m.empty:
            return str(m.iloc[0])
    except Exception:
        pass
    return default


def _safe_date_range(series: Any) -> Tuple[str, str]:
    """Safely compute (min_date_str, max_date_str) from a series or column."""
    if series is None:
        return ("—", "—")
    try:
        dt_series = pd.to_datetime(series, errors="coerce").dropna()
        if not dt_series.empty:
            return (str(dt_series.min().date()), str(dt_series.max().date()))
    except Exception:
        pass
    return ("—", "—")


# ==============================================================================
# OpenMRS 3 Maternal / Delivery Data Normalizer
# ==============================================================================
def normalize_openmrs_maternal_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DataFrame columns conform to RMH_RAW and rmh_aggregate expectations."""
    df = df.copy()

    mapping_rules = {
        "facility": ["org_unit", "location", "facility", "facility_name"],
        "region": ["state_province", "region", "parent_org_unit", "county_district"],
        "enroll_date": ["visit_date", "registration_date", "startDatetime", "enrollment_date"],
        "mrn": ["patient_id", "MRN", "Record ID", "secondary_identifier", "patient_display"],
        "address": ["city_village", "address1", "address2", "Mothers adress"],
        "age": ["age", "Age"],
        "del_date": [
            "Delivery summary_Date of Delivery:",
            "Delivery summary_Date of Delivery",
            "Date of Delivery [Delivery summary]",
            "Date of delivery [Delivery summary]",
            "visit_date",
        ],
        "del_time": [
            "Delivery summary_Time of Delivery:",
            "Delivery summary_Time of Delivery",
            "Time of Delivery [Delivery summary]",
            "Time of delivery [Delivery summary]",
        ],
        "del_mode": [
            "Delivery summary_Mode of Delivery",
            "Delivery summary_Mode of Delivery maternal",
            "Mode of Delivery maternal [Delivery summary]",
            "Mode of Delivery [Delivery summary]",
            "Mode of delivery [Labour Management]",
            "Labour Management _Mode of delivery",
        ],
        "vacuum": [
            "Delivery summary_Vacuum/Forceps",
            "Vacuum/Forceps [Delivery summary]",
            "Vacuum or Forceps [Delivery summary]",
        ],
        "episiotomy": [
            "Delivery summary_Episiotomy performed:",
            "Delivery summary_Episiotomy performed",
            "Episiotomy performed [Delivery summary]",
        ],
        "cct": [
            "Delivery summary_Controlled Cord Traction (CCT):",
            "Delivery summary_Controlled Cord Traction (CCT)",
            "Controlled Cord Traction (CCT) [Delivery summary]",
        ],
        "uterotonics": [
            "Delivery summary_Uterotonics given",
            "Uterotonics given [Delivery summary]",
        ],
        "obs_cond": [
            "Delivery summary_Obstetric condition at delivery",
            "Obstetric condition at delivery [Delivery summary]",
        ],
        "outcome": [
            "Delivery summary_Outcome",
            "Delivery summary_birth outcome",
            "birth outcome [Delivery summary]",
            "Birth outcome [Delivery summary]",
        ],
        "stillbirth": [
            "Delivery summary_Stillbirth:",
            "Delivery summary_Stillbirth",
            "Stillbirth [Delivery summary]",
        ],
        "apgar1": [
            "Delivery summary_Apgar Score 1st min",
            "Apgar Score 1st min [Delivery summary]",
        ],
        "apgar5": [
            "Delivery summary_Apgar Score 5th min",
            "Apgar Score 5th min [Delivery summary]",
        ],
        "sex": [
            "Delivery summary_Sex",
            "Sex [Delivery summary]",
            "gender",
            "Gender",
        ],
        "birth_weight": [
            "Delivery summary_Birth Weight (grams):",
            "Delivery summary_Birth Weight (grams)",
            "Birth Weight (grams) [Delivery summary]",
            "Birth weight [Delivery summary]",
        ],
        "nb_immun": [
            "Delivery summary_Newborn Immunizations and Interventions",
            "Newborn Immunizations and Interventions [Delivery summary]",
        ],
        "hiv_accept": [
            "Delivery summary_HIV Testing Accepted:",
            "HIV Testing Accepted [Delivery summary]",
        ],
        "hiv_result": [
            "Delivery summary_HIV Result:",
            "HIV Result [Delivery summary]",
        ],
        "art_mother": [
            "Delivery summary_ARV Rx for Mother: (by type)",
            "ARV Rx for Mother [Delivery summary]",
        ],
        "art_newborn": [
            "Delivery summary_ARV Px for Newborn (by type):",
            "ARV Px for Newborn [Delivery summary]",
        ],
        "feeding_opt": [
            "Delivery summary_Feeding Option",
            "Feeding Option [Delivery summary]",
        ],
        "labour_mode": [
            "Labour Management _Mode of delivery",
            "Labour Management_Mode of delivery",
            "Mode of delivery [Labour Management]",
        ],
        "partograph_id": [
            "Delivery Monitoring partograph_event_id",
            "partograph [Delivery Monitoring]",
        ],
        "preeclampsia_id": [
            "PREECLAMPSIA  CHART_event_id",
            "Preeclampsia [Diagnosis]",
        ],
        "dx_complications": [
            "Diagnosis_Obstetric complications",
            "Obstetric complications [Diagnosis]",
            "diagnoses",
        ],
        "pp_uterus": [
            "Postpartum care_Uterus Contracted / Look for PPH",
            "Uterus Contracted / Look for PPH [Postpartum care]",
        ],
        "pp_bf": [
            "Postpartum care_Baby Breastfeeding",
            "Baby Breastfeeding [Postpartum care]",
        ],
        "pp_bcg": [
            "Postpartum care_Immunization (BCG)",
            "Immunization (BCG) [Postpartum care]",
        ],
        "pp_hiv_test": [
            "Postpartum care_HIV Tested",
            "HIV Tested [Postpartum care]",
        ],
        "pp_hiv_result": [
            "Postpartum care_HIV Test Result",
            "HIV Test Result [Postpartum care]",
        ],
        "pp_fp": [
            "Postpartum care_FP Counseling and Method Provided",
            "FP Counseling and Method Provided [Postpartum care]",
        ],
        "pp_action": [
            "Postpartum care_Action Taken",
            "Action Taken [Postpartum care]",
        ],
        "gest_age": [
            "Maternal History_Current Gestational Age (From LMP in weeks)",
            "Current Gestational Age (From LMP in weeks) [Maternal History]",
            "Gestational Age [Delivery summary]",
        ],
        "dc_condition": [
            "Discharge Summary_Condition of Discharge",
            "Condition of Discharge [Discharge Summary]",
        ],
    }

    for raw_key, candidates in mapping_rules.items():
        canonical_name = RMH_RAW.get(raw_key)
        if not canonical_name:
            continue
        found = _find_col(df, candidates)
        if found:
            df[canonical_name] = df[found]

    # Guarantee all RMH_RAW columns exist to prevent KeyErrors in register/aggregates
    for col in RMH_RAW.values():
        if col not in df.columns:
            df[col] = np.nan

    # Additional standard fallbacks
    if "enrollment_date" not in df.columns or df["enrollment_date"].isna().all():
        if "visit_date" in df.columns and df["visit_date"].notna().any():
            df["enrollment_date"] = pd.to_datetime(df["visit_date"], errors="coerce")
        elif RMH_RAW["enroll_date"] in df.columns and df[RMH_RAW["enroll_date"]].notna().any():
            df["enrollment_date"] = pd.to_datetime(df[RMH_RAW["enroll_date"]], errors="coerce")
        else:
            df["enrollment_date"] = pd.Timestamp.now()

    # If both del_mode and outcome are completely empty/NA on an OpenMRS Delivery visit record,
    # fill del_mode with "Spontaneous" so filter_df does not drop valid delivery encounters
    del_mode_col = RMH_RAW["del_mode"]
    outcome_col = RMH_RAW["outcome"]
    if df[del_mode_col].isna().all() and df[outcome_col].isna().all():
        df[del_mode_col] = "Spontaneous"

    # Also align columns that rmh_aggregate_report specifically looks for
    if "Delivery summary_Mode of Delivery" not in df.columns or df["Delivery summary_Mode of Delivery"].isna().all():
        df["Delivery summary_Mode of Delivery"] = df[RMH_RAW["del_mode"]]
    if "Delivery summary_Outcome" not in df.columns or df["Delivery summary_Outcome"].isna().all():
        df["Delivery summary_Outcome"] = df[RMH_RAW["outcome"]]
    if "Delivery summary_Uterotonics given" not in df.columns or df["Delivery summary_Uterotonics given"].isna().all():
        df["Delivery summary_Uterotonics given"] = df[RMH_RAW["uterotonics"]]
    if "Postpartum care_FP Counseling and Method Provided" not in df.columns or df["Postpartum care_FP Counseling and Method Provided"].isna().all():
        df["Postpartum care_FP Counseling and Method Provided"] = df[RMH_RAW["pp_fp"]]
    if "Laboratory_VDRL" not in df.columns:
        vdrl_col = _find_col(df, ["VDRL", "Syphilis", "VDRL n", "Laboratory_VDRL"])
        df["Laboratory_VDRL"] = df[vdrl_col] if vdrl_col else np.nan
    if "Laboratory_HBsAg" not in df.columns:
        hbsag_col = _find_col(df, ["HBsAg", "Hepatitis B", "HBsAg n", "Laboratory_HBsAg"])
        df["Laboratory_HBsAg"] = df[hbsag_col] if hbsag_col else np.nan

    return df


# ==============================================================================
# OpenMRS 3 Neonatal / NICU Data Normalizer
# ==============================================================================
def normalize_openmrs_neonatal_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DataFrame columns conform to NH_RAW and nh_aggregate expectations."""
    df = df.copy()

    mapping_rules = {
        "facility": ["org_unit", "location", "facility", "facility_name"],
        "region": ["state_province", "region", "parent_org_unit", "county_district"],
        "enroll_date": ["visit_date", "registration_date", "admit_date", "startDatetime"],
        "mrn": ["Neonate MRN", "Tracked Entity Attributes :: Neonate MRN", "patient_id", "Record ID"],
        "first_name": ["Neonate First Name", "Tracked Entity Attributes :: Neonate First Name", "first_name"],
        "last_name": ["Neonate Last Name", "Tracked Entity Attributes :: Neonate Last Name", "family_name"],
        "sex": ["Neonate sex", "Tracked Entity Attributes :: Neonate sex", "gender"],
        "maternal_name": ["NICU Admission Careform_Mothers Name", "Mothers Name [NICU Admission Careform]", "fathers_husbands_name"],
        "zone": ["NICU Admission Careform_Address of the mother Zone", "Address of the mother Zone [NICU Admission Careform]", "state_province"],
        "woreda": ["NICU Admission Careform_Address of the mother Wereda", "Address of the mother Wereda [NICU Admission Careform]", "county_district"],
        "gote": ["NICU Admission Careform_Address of the mother Gote", "Address of the mother Gote [NICU Admission Careform]", "address2"],
        "kebele": ["NICU Admission Careform_Address of the mother Kebele", "Address of the mother Kebele [NICU Admission Careform]", "city_village", "address1"],
        "admit_date": ["NICU Admission Careform_Date of Admission n", "Date of Admission n [NICU Admission Careform]", "visit_date"],
        "admit_time": ["NICU Admission Careform_Time of Admission n", "Time of Admission n [NICU Admission Careform]"],
        "admit_weight": ["NICU Admission Careform_Weight at admission n", "Weight at admission [Vitals]", "Weight at admission n"],
        "temperature": ["NICU Admission Careform_Temp at admission", "Temperature (c) [Vitals]", "Temp at admission"],
        "resp_rate": ["NICU Admission Careform_RR at admission", "Respiratory rate [Vitals]", "RR at admission"],
        "heart_rate": ["NICU Admission Careform_HR at admission", "Pulse [Vitals]", "HR at admission"],
        "ga_weeks": ["NICU Admission Careform_Gestational age at delivery weeks", "Gestational age at delivery weeks [NICU Admission Careform]"],
        "dob": ["NICU Admission Careform_Date of delivery", "Date of delivery [NICU Admission Careform]", "birth_date"],
        "time_birth": ["NICU Admission Careform_Time of birth", "Time of birth [NICU Admission Careform]"],
        "mode_delivery": ["NICU Admission Careform_Mode of delivery n", "Mode of delivery n [NICU Admission Careform]"],
        "place_delivery": ["NICU Admission Careform_Place of delivery", "Place of delivery [NICU Admission Careform]"],
        "apgar1": ["NICU Admission Careform_APGAR score 1st min", "APGAR score 1st min [NICU Admission Careform]"],
        "apgar5": ["NICU Admission Careform_APGAR score 5th min", "APGAR score 5th min [NICU Admission Careform]"],
        "birth_weight": ["NICU Admission Careform_Birth Weight n", "Birth Weight n [NICU Admission Careform]"],
        "bw_category": ["NICU Admission Careform_Birth weight category", "Birth weight category [NICU Admission Careform]"],
        "mother_hiv": ["NICU Admission Careform_Mother HIV status n", "Mother HIV status n [NICU Admission Careform]"],
        "hep_b": ["NICU Admission Careform_HBsAg n", "HBsAg n [NICU Admission Careform]"],
        "vdrl": ["NICU Admission Careform_VDRL n", "VDRL n [NICU Admission Careform]"],
        "ga_cat": ["NICU Admission Careform_Gestational Age", "Gestational Age [NICU Admission Careform]"],
        "chx": ["NICU Admission Careform_Cord Chlorhexidine Administered", "Cord Chlorhexidine Administered [NICU Admission Careform]"],
        "asphyxia": ["NICU Admission Careform_Asphyxia", "Asphyxia [NICU Admission Careform]"],
        "asphyxia_stage": ["NICU Admission Careform_Asphyxia stage", "Asphyxia stage [NICU Admission Careform]"],
        "jaundice": ["NICU Progress Care Form_Jaundice", "Jaundice [NICU Progress Care Form]"],
        "blood_culture": ["Investigation sheet_Blood culture for suspected sepsis", "Blood culture for suspected sepsis [Investigation sheet]"],
        "reason1": ["NICU Admission Careform_First Reason for Admission", "First Reason for Admission [NICU Admission Careform]"],
        "reason2": ["NICU Admission Careform_Second Reason for Admission", "Second Reason for Admission [NICU Admission Careform]"],
        "reason3": ["NICU Admission Careform_Third Reason for Admission", "Third Reason for Admission [NICU Admission Careform]"],
        "cpap": ["CPAP Followup sheet_CPAP Administered", "CPAP Administered [CPAP Followup sheet]"],
        "resus_room": ["NICU Admission Careform_Resuscitation  in delivery room", "Resuscitation in delivery room"],
        "resus_done": ["NICU Admission Careform_If Resuscitated, tick what was done", "If Resuscitated, tick what was done"],
        "resus_survived": ["KMC ward follow up sheet_Able to breathe spontaneously (after resuscitation) at 60 minutes after birth?"],
        "kmc_done": ["Nurse followup Sheet_Kmc done", "Kmc done"],
        "antibiotics": ["Medication and Intervention_Antibiotics administered?", "Antibiotics administered?"],
        "anticonvulsants": ["Nurse followup Sheet_Anticonvulsants administered?", "Anticonvulsants administered?"],
        "phototherapy": ["Medication and Intervention_Phototherapy Administered?", "Phototherapy Administered?"],
        "o2_therapy": ["Medication and Intervention_Oxygen Therapy Administered?", "Oxygen Therapy Administered?"],
        "glucose": ["NICU Admission Careform_Blood sugar level at admission", "Blood sugar level at admission"],
        "transfusion": ["Medication and Intervention_Transfusion given?", "Transfusion given?"],
        "dis_date": [
            "Discharge care form_Date and time of discharge",
            "Discharge care form :: Date and time of discharge",
            "Date and time of discharge [Discharge care form]",
        ],
        "dis_weight": [
            "Discharge care form_Weight on discharge",
            "Discharge care form :: Weight on discharge",
            "Weight on discharge [Discharge care form]",
        ],
        "dis_age": [
            "Discharge care form_Age at discharge",
            "Discharge care form :: Age at discharge",
            "Age at discharge [Discharge care form]",
        ],
        "dis_status": [
            "Discharge care form_Newborn status at discharge n",
            "Discharge care form :: Newborn status at discharge n",
            "Newborn status at discharge n [NICU Discharge care form]",
            "Newborn status at discharge n [Discharge care form]",
        ],
        "dis_outcome": [
            "Discharge care form_Discharge Outcome n",
            "Discharge care form :: Discharge Outcome n",
            "Discharge Outcome n [NICU Discharge care form]",
            "Discharge Outcome n [Discharge care form]",
        ],
        "dx_primary": [
            "Discharge care form_Final Discharge Diagnosis/Cause of Death (primary)",
            "Discharge care form :: Final Discharge Diagnosis/Cause of Death (primary)",
            "Final Discharge Diagnosis/Cause of Death (primary) [NICU Discharge care form]",
            "Final Discharge Diagnosis/Cause of Death (primary) [Discharge care form]",
        ],
        "dx_specify": [
            "Discharge care form_If Other Cause of Death or Final Diagnosis - Specify n",
            "If other congenital cause/diagnosis - specify n [NICU Discharge care form]",
        ],
        "feeding_disch": [
            "Discharge care form_Type of feeding on discharge",
            "Discharge care form :: Type of feeding on discharge",
        ],
        "bf_1hr": [
            "NICU Admission Careform_Breastfeeding initiated within 1 hr of birth",
            "Breastfeeding initiated within 1 hr of birth",
        ],
        "referred_from": ["NICU Admission Careform_Referring health facility"],
        "referral_adm": ["NICU Admission Careform_Reason for referral adm"],
        "referred_to": ["Neonatal referral form_Transferred to"],
        "referral_reason": ["Neonatal referral form_Reason for NICU referral"],
        "kmc_date": ["KMC ward follow up sheet_KMC intiation date"],
    }

    for raw_key, candidates in mapping_rules.items():
        canonical_name = NH_RAW.get(raw_key)
        if not canonical_name:
            continue
        found = _find_col(df, candidates)
        if found:
            df[canonical_name] = df[found]

    # Guarantee all NH_RAW columns exist to prevent KeyErrors in register/aggregates
    for col in NH_RAW.values():
        if col not in df.columns:
            df[col] = np.nan

    # Additional standard fallbacks
    if "enrollment_date" not in df.columns or df["enrollment_date"].isna().all():
        if "visit_date" in df.columns and df["visit_date"].notna().any():
            df["enrollment_date"] = pd.to_datetime(df["visit_date"], errors="coerce")
        elif NH_RAW["enroll_date"] in df.columns and df[NH_RAW["enroll_date"]].notna().any():
            df["enrollment_date"] = pd.to_datetime(df[NH_RAW["enroll_date"]], errors="coerce")
        else:
            df["enrollment_date"] = pd.Timestamp.now()

    # Also align columns that nh_aggregate_report specifically looks for
    if "NICU Admission Careform_Date of Admission n" not in df.columns or df["NICU Admission Careform_Date of Admission n"].isna().all():
        df["NICU Admission Careform_Date of Admission n"] = df[NH_RAW["admit_date"]]
    if "Discharge care form_Newborn status at discharge n" not in df.columns or df["Discharge care form_Newborn status at discharge n"].isna().all():
        df["Discharge care form_Newborn status at discharge n"] = df[NH_RAW["dis_status"]]
    if "Discharge care form_Discharge Outcome n" not in df.columns or df["Discharge care form_Discharge Outcome n"].isna().all():
        df["Discharge care form_Discharge Outcome n"] = df[NH_RAW["dis_outcome"]]
    if "Discharge care form_Final Discharge Diagnosis/Cause of Death (primary)" not in df.columns or df["Discharge care form_Final Discharge Diagnosis/Cause of Death (primary)"].isna().all():
        df["Discharge care form_Final Discharge Diagnosis/Cause of Death (primary)"] = df[NH_RAW["dx_primary"]]

    return df


# ==============================================================================
# Live OpenMRS 3 Data Extraction Function
# ==============================================================================
def fetch_openmrs_df(
    base_url: str,
    username: str,
    password: str,
    visit_type_name: str,
    facility_name: str = "Default Facility",
    facility_code: str = "OU001",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> pd.DataFrame:
    """Fetch patient visits and obs from OpenMRS 3 directly into a pandas DataFrame."""
    log = log_fn or print
    norm_url = normalize_base_url(base_url)
    log(f"Connecting to OpenMRS 3 API: {norm_url} (user: {username})")

    api = create_o3_api(norm_url, username, password)
    if not api.login_session():
        raise RuntimeError("Failed to authenticate session with OpenMRS 3.")

    visit_types = api.get_visit_types()
    log(f"Available visit types in OpenMRS 3: {[v.get('name') or v.get('display') for v in visit_types]}")

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        log(f"Extracting '{visit_type_name}' patient records ({start_date or 'all'} to {end_date or 'all'})...")
        _, _, count = run_o3_export(
            api=api,
            visit_types=visit_types,
            visit_type_name=visit_type_name,
            facility_name=facility_name,
            facility_code=facility_code,
            start_date=start_date or "",
            end_date=end_date or "",
            output_path=tmp_path,
            log_callback=log,
        )
        log(f"Extracted {count} patient record(s) from OpenMRS 3.")
        if count == 0 or not tmp_path.exists():
            return pd.DataFrame()
        df = pd.read_csv(tmp_path)
        return df
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


# ==============================================================================
# WORKERS: 1. Delivery Register from OpenMRS 3
# ==============================================================================
def run_rmh_delivery_register_openmrs_worker(
    ctx: JobContext,
    input_file: Optional[str] = None,
    openmrs_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    facility_name: Optional[str] = None,
    facility_code: Optional[str] = None,
    output_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
    sheet_per_facility: bool = False,
) -> dict:
    ctx.log("Starting Delivery Register generation from OpenMRS 3...")
    ctx.update_progress(10, 100, "Preparing OpenMRS data...")

    if input_file:
        file_path = Path(input_file)
        if not file_path.is_file():
            file_path = settings.uploads_dir / input_file
        if not file_path.is_file():
            raise FileNotFoundError(f"Input OpenMRS CSV not found: {input_file}")
        ctx.log(f"Loading OpenMRS export CSV: {file_path.name}")
        df = pd.read_csv(file_path)
    else:
        creds = resolve_openmrs_creds(openmrs_url, username, password)
        df = fetch_openmrs_df(
            base_url=creds["base_url"],
            username=creds["username"],
            password=creds["password"],
            visit_type_name="Delivery",
            facility_name=facility_name or "Hospital",
            facility_code=facility_code or "FAC-01",
            start_date=start,
            end_date=end,
            log_fn=ctx.log,
        )

    ctx.log(f"Raw OpenMRS records: {len(df):,}")
    ctx.update_progress(40, 100, "Mapping OpenMRS 3 fields to MoH Delivery Register...")
    df = normalize_openmrs_maternal_df(df)
    df = filter_rmh_df(df, start=start, end=end, facility=facility_name)
    ctx.log(f"Records after date/facility filtering: {len(df):,}")

    wb = Workbook()
    wb.remove(wb.active)
    all_tallies = []

    if sheet_per_facility and RMH_RAW["facility"] in df:
        facilities = df[RMH_RAW["facility"]].dropna().unique()
        ctx.log(f"Generating {len(facilities)} facility sheet(s)...")
        for fac in sorted(facilities):
            grp = df[df[RMH_RAW["facility"]] == fac]
            reg_name = _safe_mode(grp[RMH_RAW["region"]]) if RMH_RAW["region"] in grp else ""
            d_from, d_to = _safe_date_range(grp[RMH_RAW["enroll_date"]]) if RMH_RAW["enroll_date"] in grp else ("—", "—")

            reg = build_rmh_register(grp)
            sheet_name = str(fac)[:28].strip()
            ws = wb.create_sheet(title=sheet_name)
            write_rmh_sheet(ws, reg, fac, reg_name, d_from, d_to)

            t = compute_rmh_tally(reg)
            t["_facility"] = sheet_name
            all_tallies.append(t)
    else:
        fac_list = df[RMH_RAW["facility"]].dropna().unique() if RMH_RAW["facility"] in df else []
        fac_label = fac_list[0] if len(fac_list) == 1 else (facility_name or "OpenMRS Facility")
        reg_name = _safe_mode(df[RMH_RAW["region"]]) if RMH_RAW["region"] in df else ""
        d_from, d_to = _safe_date_range(df[RMH_RAW["enroll_date"]]) if RMH_RAW["enroll_date"] in df else ("—", "—")

        ctx.log(f"Building Delivery Register for {len(df):,} deliveries...")
        reg = build_rmh_register(df)
        ws = wb.create_sheet(title="Delivery Register")
        write_rmh_sheet(ws, reg, fac_label, str(reg_name), d_from, d_to)

        t = compute_rmh_tally(reg)
        t["_facility"] = fac_label
        all_tallies.append(t)

    ws_tally = wb.create_sheet(title="Tally Summary")
    write_rmh_tally_sheet(ws_tally, all_tallies)

    target_dir = Path(output_dir) if output_dir else settings.exports_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = (output_filename or "delivery_register_openmrs.xlsx").strip()
    if not out_name.lower().endswith(".xlsx"):
        out_name = f"{out_name}.xlsx"
    out_path = target_dir / out_name
    wb.save(out_path)
    ctx.log(f"Successfully generated Delivery Register: {out_path.name}")
    ctx.update_progress(100, 100, "Delivery Register generated.")

    combined_tallies = {}
    if all_tallies:
        combined_tallies = {
            k: sum(t.get(k, 0) for t in all_tallies if isinstance(t.get(k), (int, float)))
            for k in all_tallies[0]
            if not k.startswith("_")
        }

    res = {
        "status": "success",
        "source": "OpenMRS 3",
        "total_records": len(df),
        "output_file": str(out_path),
        "output_dir": str(target_dir),
        "filename": out_path.name,
        "tallies": combined_tallies,
    }
    ctx.result_file = str(out_path)
    ctx.artifacts.update(res)
    return res


# ==============================================================================
# WORKERS: 2. HMIS RMH Report (01.2) from OpenMRS 3
# ==============================================================================
def run_rmh_aggregate_report_openmrs_worker(
    ctx: JobContext,
    input_file: Optional[str] = None,
    openmrs_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    period: str = "201702",
    start: Optional[str] = None,
    end: Optional[str] = None,
    facility_name: Optional[str] = None,
    preview_filename: Optional[str] = None,
    json_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    ctx.log(f"Starting 01.2 RMH Monthly Report calculation from OpenMRS 3 ({period})...")
    ctx.update_progress(10, 100, "Preparing OpenMRS maternal records...")

    if input_file:
        file_path = Path(input_file)
        if not file_path.is_file():
            file_path = settings.uploads_dir / input_file
        if not file_path.is_file():
            raise FileNotFoundError(f"Input OpenMRS CSV not found: {input_file}")
        ctx.log(f"Loading OpenMRS export CSV: {file_path.name}")
        df = pd.read_csv(file_path)
    else:
        creds = resolve_openmrs_creds(openmrs_url, username, password)
        df = fetch_openmrs_df(
            base_url=creds["base_url"],
            username=creds["username"],
            password=creds["password"],
            visit_type_name="Delivery",
            facility_name=facility_name or "Hospital",
            start_date=start,
            end_date=end,
            log_fn=ctx.log,
        )

    ctx.log(f"Loaded {len(df):,} maternal records from OpenMRS 3.")
    df = normalize_openmrs_maternal_df(df)
    df = filter_rmh_df(df, start=start, end=end, facility=facility_name)
    ctx.log(f"Deliveries within reporting period: {len(df):,}")

    ctx.log("Computing MoH 01.2 indicators from OpenMRS data...")
    ctx.update_progress(60, 100, "Computing indicators...")
    computed_values = compute_rmh_indicators(df)
    non_null_count = sum(1 for v in computed_values.values() if v is not None)
    ctx.log(f"Computed {non_null_count} indicators with valid values.")

    target_dir = Path(output_dir) if output_dir else settings.exports_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    prev_name = preview_filename or f"rmh_{period}_openmrs_preview.xlsx"
    prev_path = target_dir / prev_name
    fac_label = facility_name or (df[RMH_RAW["facility"]].iloc[0] if len(df) and RMH_RAW["facility"] in df else "OpenMRS 3 Facility")
    write_rmh_preview_excel(computed_values, period, fac_label, str(prev_path))
    ctx.log(f"Saved indicator preview workbook: {prev_path.name}")

    summary_path = None
    if json_filename:
        summary_path = target_dir / json_filename
        summary_path.write_text(json.dumps(computed_values, indent=2), encoding="utf-8")

    ctx.update_progress(100, 100, "RMH Report complete.")
    res = {
        "status": "success",
        "source": "OpenMRS 3",
        "period": period,
        "facility": fac_label,
        "total_records": len(df),
        "computed_indicators_count": non_null_count,
        "values": computed_values,
        "preview_file": str(prev_path),
        "output_file": str(prev_path),
        "output_dir": str(target_dir),
        "filename": prev_path.name,
    }
    ctx.result_file = str(prev_path)
    ctx.artifacts.update(res)
    return res


# ==============================================================================
# WORKERS: 3. NICU Register from OpenMRS 3
# ==============================================================================
def run_nh_neonatal_register_openmrs_worker(
    ctx: JobContext,
    input_file: Optional[str] = None,
    openmrs_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    facility_name: Optional[str] = None,
    facility_code: Optional[str] = None,
    output_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
    sheet_per_facility: bool = False,
) -> dict:
    ctx.log("Starting NICU Register generation from OpenMRS 3...")
    ctx.update_progress(10, 100, "Preparing OpenMRS neonatal records...")

    if input_file:
        file_path = Path(input_file)
        if not file_path.is_file():
            file_path = settings.uploads_dir / input_file
        if not file_path.is_file():
            raise FileNotFoundError(f"Input OpenMRS CSV not found: {input_file}")
        ctx.log(f"Loading OpenMRS export CSV: {file_path.name}")
        df = pd.read_csv(file_path)
    else:
        creds = resolve_openmrs_creds(openmrs_url, username, password)
        df = fetch_openmrs_df(
            base_url=creds["base_url"],
            username=creds["username"],
            password=creds["password"],
            visit_type_name="NICU",
            facility_name=facility_name or "Hospital",
            facility_code=facility_code or "FAC-01",
            start_date=start,
            end_date=end,
            log_fn=ctx.log,
        )

    ctx.log(f"Raw OpenMRS neonatal records: {len(df):,}")
    ctx.update_progress(40, 100, "Mapping OpenMRS 3 fields to MoH NICU Register...")
    df = normalize_openmrs_neonatal_df(df)
    df = filter_nh_df(df, start=start, end=end, facility=facility_name)
    ctx.log(f"Admissions after date/facility filtering: {len(df):,}")

    wb = Workbook()
    wb.remove(wb.active)
    all_tallies = []

    if sheet_per_facility and NH_RAW["facility"] in df:
        facilities = df[NH_RAW["facility"]].dropna().unique()
        ctx.log(f"Generating {len(facilities)} facility sheet(s)...")
        for fac in sorted(facilities):
            grp = df[df[NH_RAW["facility"]] == fac]
            reg_name = _safe_mode(grp[NH_RAW["region"]]) if NH_RAW["region"] in grp else ""
            d_from, d_to = _safe_date_range(grp[NH_RAW["enroll_date"]]) if NH_RAW["enroll_date"] in grp else ("—", "—")

            reg = build_nh_register(grp)
            sheet_name = str(fac)[:28].strip()
            ws = wb.create_sheet(title=sheet_name)
            write_nh_sheet(ws, reg, fac, reg_name, d_from, d_to)

            t = compute_nh_tally(reg)
            t["_facility"] = sheet_name
            all_tallies.append(t)
    else:
        fac_list = df[NH_RAW["facility"]].dropna().unique() if NH_RAW["facility"] in df else []
        fac_label = fac_list[0] if len(fac_list) == 1 else (facility_name or "OpenMRS Facility")
        reg_name = _safe_mode(df[NH_RAW["region"]]) if NH_RAW["region"] in df else ""
        d_from, d_to = _safe_date_range(df[NH_RAW["enroll_date"]]) if NH_RAW["enroll_date"] in df else ("—", "—")

        ctx.log(f"Building NICU Register for {len(df):,} admissions...")
        reg = build_nh_register(df)
        ws = wb.create_sheet(title="NICU Register")
        write_nh_sheet(ws, reg, fac_label, str(reg_name), d_from, d_to)

        t = compute_nh_tally(reg)
        t["_facility"] = fac_label
        all_tallies.append(t)

    ws_tally = wb.create_sheet(title="Tally Summary")
    write_nh_tally_sheet(ws_tally, all_tallies)

    target_dir = Path(output_dir) if output_dir else settings.exports_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = (output_filename or "nicu_register_openmrs.xlsx").strip()
    if not out_name.lower().endswith(".xlsx"):
        out_name = f"{out_name}.xlsx"
    out_path = target_dir / out_name
    wb.save(out_path)
    ctx.log(f"Successfully generated NICU Register: {out_path.name}")
    ctx.update_progress(100, 100, "NICU Register generated.")

    combined_tallies = {}
    if all_tallies:
        combined_tallies = {
            k: sum(t.get(k, 0) for t in all_tallies if isinstance(t.get(k), (int, float)))
            for k in all_tallies[0]
            if not k.startswith("_")
        }

    res = {
        "status": "success",
        "source": "OpenMRS 3",
        "total_records": len(df),
        "output_file": str(out_path),
        "output_dir": str(target_dir),
        "filename": out_path.name,
        "tallies": combined_tallies,
    }
    ctx.result_file = str(out_path)
    ctx.artifacts.update(res)
    return res


# ==============================================================================
# WORKERS: 4. HMIS NCH Report (04.2) from OpenMRS 3
# ==============================================================================
def run_nh_aggregate_report_openmrs_worker(
    ctx: JobContext,
    input_file: Optional[str] = None,
    openmrs_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    period: str = "201702",
    start: Optional[str] = None,
    end: Optional[str] = None,
    facility_name: Optional[str] = None,
    preview_filename: Optional[str] = None,
    json_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    ctx.log(f"Starting 04.2 NCH Monthly Report calculation from OpenMRS 3 ({period})...")
    ctx.update_progress(10, 100, "Preparing OpenMRS neonatal records...")

    if input_file:
        file_path = Path(input_file)
        if not file_path.is_file():
            file_path = settings.uploads_dir / input_file
        if not file_path.is_file():
            raise FileNotFoundError(f"Input OpenMRS CSV not found: {input_file}")
        ctx.log(f"Loading OpenMRS export CSV: {file_path.name}")
        df = pd.read_csv(file_path)
    else:
        creds = resolve_openmrs_creds(openmrs_url, username, password)
        df = fetch_openmrs_df(
            base_url=creds["base_url"],
            username=creds["username"],
            password=creds["password"],
            visit_type_name="NICU",
            facility_name=facility_name or "Hospital",
            start_date=start,
            end_date=end,
            log_fn=ctx.log,
        )

    ctx.log(f"Loaded {len(df):,} neonatal records from OpenMRS 3.")
    df = normalize_openmrs_neonatal_df(df)
    df = filter_nh_df(df, start=start, end=end, facility=facility_name)
    ctx.log(f"Admissions within reporting period: {len(df):,}")

    ctx.log("Computing MoH 04.2 indicators from OpenMRS data...")
    ctx.update_progress(60, 100, "Computing indicators...")
    computed_values = compute_nh_indicators(df)
    non_null_count = sum(1 for v in computed_values.values() if v is not None)
    ctx.log(f"Computed {non_null_count} indicators with valid values.")

    target_dir = Path(output_dir) if output_dir else settings.exports_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    prev_name = preview_filename or f"nh_{period}_openmrs_preview.xlsx"
    prev_path = target_dir / prev_name
    fac_label = facility_name or (df[NH_RAW["facility"]].iloc[0] if len(df) and NH_RAW["facility"] in df else "OpenMRS 3 Facility")
    write_nh_preview_excel(computed_values, period, fac_label, str(prev_path))
    ctx.log(f"Saved indicator preview workbook: {prev_path.name}")

    summary_path = None
    if json_filename:
        summary_path = target_dir / json_filename
        summary_path.write_text(json.dumps(computed_values, indent=2), encoding="utf-8")

    ctx.update_progress(100, 100, "NCH Report complete.")
    res = {
        "status": "success",
        "source": "OpenMRS 3",
        "period": period,
        "facility": fac_label,
        "total_records": len(df),
        "computed_indicators_count": non_null_count,
        "values": computed_values,
        "preview_file": str(prev_path),
        "output_file": str(prev_path),
        "output_dir": str(target_dir),
        "filename": prev_path.name,
    }
    ctx.result_file = str(prev_path)
    ctx.artifacts.update(res)
    return res
