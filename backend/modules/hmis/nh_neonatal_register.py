"""
================================================================================
  PROJECT  : IMNID — Neonatal Health DHIS2 Registry
  FILE     : neonatal_register.py
  PURPOSE  : Generate a NICU Admission Register (MoH 04.2 Neonatal & Child
             Health style) from a DHIS2 tracker export of the
             "Neonatal Care Form" program (neonatal_data.csv).
  USAGE    : python neonatal_register.py
               [--input  neonatal_data.csv]
               [--output neonatal_register.xlsx]
               [--start  YYYY-MM-DD]  [--end YYYY-MM-DD]
               [--region REGION_NAME] [--facility FACILITY_NAME]
               [--sheet-per-facility]
  OUTPUT   : Excel workbook — one "NICU Register" sheet per facility (or all
             combined) plus a "Tally Summary" sheet.
================================================================================
"""

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side
)
from openpyxl.utils import get_column_letter

warnings.filterwarnings("ignore")

# ── Raw CSV column names (Neonatal Care Form program) ─────────────────────────
# Stage names come from the live program metadata.  Data values are stored as
# option NAMES (labels), matching what a DHIS2 CSV export / API fetch yields.

RAW = {
    "enroll_date":      "enrollment_date",
    "facility":         "org_unit",
    "region":           "parent_org_unit",

    # ── Identification ──────────────────────────────────────────────
    "mrn":              "Neonate MRN",
    "first_name":       "Neonate First Name",
    "last_name":        "Neonate Last Name",
    "sex":              "Neonate sex",
    "maternal_name":    "NICU Admission Careform_Mothers Name",
    "zone":             "NICU Admission Careform_Address of the mother Zone",
    "woreda":           "NICU Admission Careform_Address of the mother Wereda",
    "gote":             "NICU Admission Careform_Address of the mother Gote",
    "kebele":           "NICU Admission Careform_Address of the mother Kebele",

    # ── Admission info ──────────────────────────────────────────────
    "admit_date":       "NICU Admission Careform_Date of Admission n",
    "admit_time":       "NICU Admission Careform_Time of Admission n",
    "admit_weight":     "NICU Admission Careform_Weight at admission n",
    "temperature":      "NICU Admission Careform_Temp at admission",
    "temp_unit":        "NICU Admission Careform_Temperature measured in (°C) or (°F)?",
    "resp_rate":        "NICU Admission Careform_RR at admission",
    "heart_rate":       "NICU Admission Careform_HR at admission",

    # ── Delivery info ───────────────────────────────────────────────
    "ga_weeks":         "NICU Admission Careform_Gestational age at delivery weeks",
    "dob":              "NICU Admission Careform_Date of delivery",
    "time_birth":       "NICU Admission Careform_Time of birth",
    "mode_delivery":    "NICU Admission Careform_Mode of delivery n",
    "place_delivery":   "NICU Admission Careform_Place of delivery",
    "apgar1":           "NICU Admission Careform_APGAR score 1st min",
    "apgar5":           "NICU Admission Careform_APGAR score 5th min",
    "birth_weight":     "NICU Admission Careform_Birth Weight n",
    "bw_category":      "NICU Admission Careform_Birth weight category",

    # ── Maternal condition ──────────────────────────────────────────
    "mother_hiv":       "NICU Admission Careform_Mother HIV status n",
    "hep_b":            "NICU Admission Careform_HBsAg n",
    "vdrl":             "NICU Admission Careform_VDRL n",
    "ga_cat":           "NICU Admission Careform_Gestational Age",
    "chx":              "NICU Admission Careform_Cord Chlorhexidine Administered",

    # ── Admission problem ───────────────────────────────────────────
    "asphyxia":         "NICU Admission Careform_Asphyxia",
    "asphyxia_stage":   "NICU Admission Careform_Asphyxia stage",
    "jaundice":         "NICU Progress Care Form_Jaundice",
    "meconium":         "Neonatal referral form_Meconium sucked from oropharynx",
    "blood_culture":    "Investigation sheet_Blood culture for suspected sepsis",
    "reason1":          "NICU Admission Careform_First Reason for Admission",
    "reason2":          "NICU Admission Careform_Second Reason for Admission",
    "reason3":          "NICU Admission Careform_Third Reason for Admission",

    # ── Management ──────────────────────────────────────────────────
    "cpap":             "CPAP Followup sheet_CPAP Administered",
    "resus_room":       "NICU Admission Careform_Resuscitation  in delivery room",
    "resus_done":       "NICU Admission Careform_If Resuscitated, tick what was done",
    "resus_survived":   "KMC ward follow up sheet_Able to breathe spontaneously (after resuscitation) at 60 minutes after birth?",
    "kmc_done":         "Nurse followup Sheet_Kmc done",
    "antibiotics":      "Medication and Intervention_Antibiotics administered?",
    "anticonvulsants":  "Nurse followup Sheet_Anticonvulsants administered?",
    "phototherapy":     "Medication and Intervention_Phototherapy Administered?",
    "o2_therapy":       "Medication and Intervention_Oxygen Therapy Administered?",
    "glucose":          "NICU Admission Careform_Blood sugar level at admission",
    "transfusion":      "Medication and Intervention_Transfusion given?",

    # ── Discharge ───────────────────────────────────────────────────
    "dis_date":         "Discharge care form_Date and time of discharge",
    "dis_weight":       "Discharge care form_Weight on discharge",
    "dis_age":          "Discharge care form_Age at discharge",
    "dis_status":       "Discharge care form_Newborn status at discharge n",
    "dis_outcome":      "Discharge care form_Discharge Outcome n",
    "dx_primary":       "Discharge care form_Final Discharge Diagnosis/Cause of Death (primary)",
    "dx_specify":       "Discharge care form_If Other Cause of Death or Final Diagnosis - Specify n",
    "feeding_disch":    "Discharge care form_Type of feeding on discharge",
    "bf_1hr":           "NICU Admission Careform_Breastfeeding initiated within 1 hr of birth",

    # ── Remark / referral ──────────────────────────────────────────
    "referred_from":    "NICU Admission Careform_Referring health facility",
    "referral_adm":     "NICU Admission Careform_Reason for referral adm",
    "referred_to":      "Neonatal referral form_Transferred to",
    "referral_reason":  "Neonatal referral form_Reason for NICU referral",
    "kmc_date":         "KMC ward follow up sheet_KMC intiation date",
}

TICK = "√"


# ── Field transform helpers ───────────────────────────────────────────────────

def _g(row, key):
    col = RAW.get(key, "")
    return row[col] if col in row.index else np.nan


def _tick(val):
    """Return √ for any non-empty value."""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    return TICK if s and s.lower() not in ("nan", "none", "no") else ""


def _yes(val):
    """Return √ when a Yes/No style value is 'Yes'."""
    if pd.isna(val):
        return ""
    return TICK if str(val).strip().lower() in ("yes", "true", "1", "y") else ""


def _no(val):
    """Return √ when a Yes/No style value is 'No'."""
    if pd.isna(val):
        return ""
    return TICK if str(val).strip().lower() in ("no", "false", "0", "n") else ""


def _contains(val, kw):
    if pd.isna(val):
        return ""
    return TICK if kw.lower() in str(val).lower() else ""


def _raw(val):
    if pd.isna(val):
        return ""
    return str(val).strip()


def _datetime(d, t):
    ds = str(d)[:10] if pd.notna(d) else ""
    ts = str(t)[:5] if pd.notna(t) else ""
    return f"{ds} {ts}".strip() if ds else ""


def _ddmmyy(d, t):
    """DD/MM/YY - HH:MM display used by the template."""
    try:
        ds = pd.to_datetime(d, errors="coerce")
        dd = f"{ds.day:02d}/{ds.month:02d}/{str(ds.year)[-2:]}" if pd.notna(ds) else ""
    except Exception:
        dd = str(d)[:10] if pd.notna(d) else ""
    ts = str(t)[:5] if pd.notna(t) else ""
    return f"{dd} - {ts}".strip(" -") if dd else ""


def _sex(val):
    if pd.isna(val):
        return ""
    v = str(val).strip().lower()
    if v in ("male", "m", "1"):
        return "M"
    if v in ("female", "f", "2"):
        return "F"
    return ""


def _clean_bw(val):
    try:
        v = float(val)
        if 0 < v < 20:
            v *= 1000
        return int(v)
    except (ValueError, TypeError):
        return ""


def _clean_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return np.nan


def _pn(val):
    """Positive/Negative → P/N."""
    if pd.isna(val):
        return ""
    s = str(val).strip().lower()
    if s in ("positive", "pos", "p", "reactive", "1"):
        return "P"
    if s in ("negative", "neg", "n", "non-reactive", "0"):
        return "N"
    return ""


def _ad(val):
    """Alive/Dead → A/D."""
    if pd.isna(val):
        return ""
    s = str(val).strip().lower()
    if s in ("alive", "1", "a"):
        return "A"
    if s in ("dead", "died", "0", "d"):
        return "D"
    return ""


def _preterm(val):
    """√ when GA category says preterm or GA weeks < 37."""
    if pd.isna(val):
        return ""
    v = str(val).strip().lower()
    if "preterm" in v or "pre term" in v:
        return TICK
    return ""


def _ga_weeks_preterm(val):
    try:
        return TICK if float(val) < 37 else ""
    except (ValueError, TypeError):
        return ""


def _lbw(bw, category):
    """√ when birth weight < 2500 g or category is SGA."""
    if isinstance(bw, int) and 0 < bw < 2500:
        return TICK
    if pd.notna(category) and "sga" in str(category).lower():
        return TICK
    return ""


def _vlbw(bw):
    return TICK if isinstance(bw, int) and 0 < bw <= 2000 else ""


def _resus_bag(val):
    """√ when 'Bag mask ventilation' appears in the resuscitation list."""
    if pd.isna(val):
        return ""
    return TICK if "bag" in str(val).lower() else ""


def _died(val):
    if pd.isna(val):
        return ""
    return TICK if str(val).strip().lower() in ("dead", "died", "0") else ""


def _survived(val):
    if pd.isna(val):
        return ""
    return TICK if str(val).strip().lower() in ("alive", "discharged alive", "1") else ""


def _reason_has(row, keywords):
    """√ when any admission reason (1-3) contains one of keywords."""
    for k in ("reason1", "reason2", "reason3"):
        v = _g(row, k)
        if pd.notna(v):
            s = str(v).lower()
            if any(kw.lower() in s for kw in keywords):
                return TICK
    return ""


def _mode_code(val):
    """Mode of delivery → template write code (1 SVD, 2 CS, 3 forceps, 4 vacuum)."""
    if pd.isna(val):
        return ""
    s = str(val).strip().lower()
    if any(x in s for x in ("normal vertex", "svd", "spontaneous", "vaginal")):
        return "1"
    if any(x in s for x in ("caesar", "cesar", "c-section", "c section")):
        return "2"
    if "forceps" in s:
        return "3"
    if "vacuum" in s:
        return "4"
    if s.isdigit():
        return s
    return ""


def _place_code(val):
    """Place of delivery → code (1 inborn, 2 outborn)."""
    if pd.isna(val):
        return ""
    s = str(val).strip().lower()
    if "inborn" in s or s == "1":
        return "1"
    if "outborn" in s or s == "2":
        return "2"
    return ""


def _dis_status_code(status, outcome):
    """Discharge status → template code (1 recovered, 2 died, 3 transferred, 4 others)."""
    s = str(status).strip().lower() if pd.notna(status) else ""
    o = str(outcome).strip().lower() if pd.notna(outcome) else ""
    if s in ("dead", "died", "0") or "death" in o:
        return "2"
    if "referred" in o or "transfer" in o:
        return "3"
    if s in ("alive", "1") or "discharged" in o or "recovered" in o:
        return "1"
    if s or o:
        return "4"
    return ""


def _death_code(dx):
    """Cause of death → template code (1 prematurity, 2 sepsis, 3 asphyxia, 4 malformation)."""
    if pd.isna(dx):
        return ""
    s = str(dx).strip().lower()
    if "prematur" in s:
        return "1"
    if "sepsis" in s or "infection" in s:
        return "2"
    if "asphyxia" in s or "intrapartum" in s:
        return "3"
    if "malform" in s or "congenital" in s:
        return "4"
    if s.isdigit():
        return s
    return ""


def _los_days(admit, dis):
    """Length of stay in days (0 if unknown)."""
    try:
        a = pd.to_datetime(admit, errors="coerce")
        d = pd.to_datetime(dis, errors="coerce")
        if pd.notna(a) and pd.notna(d):
            return max(int((d - a).days), 0)
    except Exception:
        pass
    return ""


# ── Register row builder ──────────────────────────────────────────────────────

def build_row(row, sn):
    bw   = _clean_bw(_g(row, "birth_weight"))
    dis_age = _g(row, "dis_age")
    status = _raw(_g(row, "dis_status"))

    prem   = TICK if (_ga_weeks_preterm(_g(row, "ga_weeks")) or
                      _reason_has(row, ["preterm", "low birthweight", "small baby"])) else ""
    lbw    = _lbw(bw, _g(row, "bw_category"))
    sepsis = TICK if (_reason_has(row, ["sepsis", "meningitis", "infection"]) or
                      pd.notna(_g(row, "blood_culture"))) else ""
    rds    = _reason_has(row, ["respiratory distress", "rds"])
    asphyxia = TICK if (_yes(_g(row, "asphyxia")) or
                        _reason_has(row, ["asphyxia", "birth injury", "intrapartum"])) else ""
    malform  = _reason_has(row, ["congenital malformation", "malformation"])
    meconium = TICK if (_reason_has(row, ["meconium"]) or
                        pd.notna(_g(row, "meconium"))) else ""
    hyperbil = TICK if (_reason_has(row, ["jaundice", "bilirubin"]) or
                        pd.notna(_g(row, "jaundice"))) else ""

    def _other_reason():
        matched = (prem or lbw or sepsis or rds or asphyxia or malform or
                   meconium or hyperbil)
        if matched:
            return ""
        parts = []
        for k in ("reason1", "reason2", "reason3"):
            v = _raw(_g(row, k))
            if v and "not recorded" not in v.lower() and "not readable" not in v.lower():
                parts.append(v)
        return "; ".join(dict.fromkeys(parts))

    def _extract_newborn_name():
        fn = _raw(_g(row, "first_name"))
        ln = _raw(_g(row, "last_name"))
        name = (fn + " " + ln).strip()
        if name:
            return name
        for k in ["patient_name", "Patient Name", "full_name", "Full Name", "Name", "name", "patient_display"]:
            if k in row and pd.notna(row[k]):
                v = str(row[k]).strip()
                if v and v.lower() not in ("nan", "none", "null", ""):
                    return v
        return ""

    def _extract_maternal_name():
        mn = _raw(_g(row, "maternal_name"))
        if mn:
            return mn
        for k in ["Mothers Name", "Mother Name", "Mother's Name", "maternal_name"]:
            if k in row and pd.notna(row[k]):
                v = str(row[k]).strip()
                if v and v.lower() not in ("nan", "none", "null", ""):
                    return v
        # Try 3-part mother name if present
        m_parts = [
            _raw(row[k]) for k in ["Mothers First Name", "Mothers Father Name", "Mothers Grandfather Name"]
            if k in row and pd.notna(row[k])
        ]
        m_name = " ".join(p for p in m_parts if p).strip()
        return m_name

    return {
        # ── Identification (1-9) ────────────────────────────────────
        "S.No":                      sn,
        "MRN":                       _raw(_g(row, "mrn")),
        "Name of newborn":           _extract_newborn_name(),
        "Sex (M/F)":                 _sex(_g(row, "sex")),
        "Name of mother":            _extract_maternal_name(),
        "Zone":                      _raw(_g(row, "zone")),
        "Woreda":                    _raw(_g(row, "woreda")),
        "Gote":                      _raw(_g(row, "gote")),
        "Kebele":                    _raw(_g(row, "kebele")),

        # ── Admission Information (10-14) ───────────────────────────
        "Admission D/T":             _ddmmyy(_g(row, "admit_date"), _g(row, "admit_time")),
        "Admission Weight (gm)":     _clean_bw(_g(row, "admit_weight")),
        "Temperature (°C)":          _clean_float(_g(row, "temperature")),
        "Respiratory Rate per '":    _raw(_g(row, "resp_rate")),
        "Apical Heart Rate per '":   _raw(_g(row, "heart_rate")),

        # ── Delivery Information (15-20) ────────────────────────────
        "GA (weeks)":                _raw(_g(row, "ga_weeks")),
        "Delivery D/T":              _ddmmyy(_g(row, "dob"), _g(row, "time_birth")),
        "Mode of delivery (code)":   _mode_code(_g(row, "mode_delivery")),
        "Place of delivery (code)":  _place_code(_g(row, "place_delivery")),
        "Apgar 1'/5'":               (f"{_raw(_g(row, 'apgar1'))}/{_raw(_g(row, 'apgar5'))}"
                                       if pd.notna(_g(row, "apgar1")) or pd.notna(_g(row, "apgar5")) else ""),
        "Birth weight (gm)":         bw,

        # ── Maternal Condition (21-25) ──────────────────────────────
        "PITC (P/N)":                _pn(_g(row, "mother_hiv")),
        "Hep B (P/N)":               _pn(_g(row, "hep_b")),
        "Hep C (P/N)":               "",
        "VDRL (P/N)":                _pn(_g(row, "vdrl")),
        "A/D":                       _ad(status),

        # ── Admission Problem (26-34) ───────────────────────────────
        "Prematurity (√)":           prem,
        "Low birth weight (√)":      lbw,
        "Sepsis (√)":                sepsis,
        "RDS (√)":                   rds,
        "Perinatal Asphyxia (√)":    asphyxia,
        "Cong. Malformation (√)":    malform,
        "Meconium Asp (√)":          meconium,
        "Hyperbilirubinemia (√)":    hyperbil,
        "Other (AP) (specify)":      _other_reason(),

        # ── Management (35-46) ──────────────────────────────────────
        "CPAP (√)":                  _yes(_g(row, "cpap")),
        "Resuscitation (√)":         TICK if (_yes(_g(row, "resus_room")) or
                                             pd.notna(_g(row, "resus_done"))) else "",
        "KMC (√)":                   _yes(_g(row, "kmc_done")),
        "Antibiotics (√)":           _yes(_g(row, "antibiotics")),
        "Anticonvulsants (√)":       _yes(_g(row, "anticonvulsants")),
        "Phototherapy (√)":          _yes(_g(row, "phototherapy")),
        "Glucose (√)":               TICK if pd.notna(_g(row, "glucose")) else "",
        "O2 (oxygen) (√)":           _yes(_g(row, "o2_therapy")),
        "Blood Transfusion (√)":     _contains(_g(row, "transfusion"), "blood"),
        "Incubator/thermal (√)":     "",
        "Exchange transfusion (√)":  _contains(_g(row, "transfusion"), "exchange"),
        "Other (Mgmt) (specify)":    "",

        # ── Discharge Information (47-53) ───────────────────────────
        "Discharge D/T":             _ddmmyy(_g(row, "dis_date"), ""),
        "Discharge weight (gm)":     _clean_bw(_g(row, "dis_weight")),
        "Discharge status (code)":   _dis_status_code(_g(row, "dis_status"), _g(row, "dis_outcome")),
        "Survived after resus (√)":  _yes(_g(row, "resus_survived")),
        "If died, age days":         dis_age if _ad(status) == "D" else "",
        "Cause of death (code)":     _death_code(_g(row, "dx_primary")),
        "LOS (days)":                _los_days(_g(row, "admit_date"), _g(row, "dis_date")),

        # ── Counseled on (54-56) ────────────────────────────────────
        "Breast feeding (√)":        TICK if (_yes(_g(row, "bf_1hr")) or
                                             pd.notna(_g(row, "feeding_disch"))) else "",
        "Newborn care (√)":          "",
        "CCD (√)":                   "",

        # ── Remark (57) ─────────────────────────────────────────────
        "Remark":                    _raw(_g(row, "referred_from")) or _raw(_g(row, "referral_adm")),
    }


def build_register(df: pd.DataFrame) -> pd.DataFrame:
    rows, sn = [], 1
    for _, row in df.iterrows():
        rows.append(build_row(row, sn))
        sn += 1
    return pd.DataFrame(rows)


# ── Tally computation ─────────────────────────────────────────────────────────

def compute_tally(reg: pd.DataFrame) -> dict:
    if reg.empty:
        return {
            "Total admissions": 0,
            "Inborn": 0,
            "Outborn": 0,
            "SVD": 0,
            "Caesarean section": 0,
            "Assisted delivery": 0,
            "Weighed at admission": 0,
            "LBW (<2500 g)": 0,
            "VLBW (<=2000 g)": 0,
            "Asphyxia cases": 0,
            "Resuscitated (room)": 0,
            "Bag-mask ventilation": 0,
            "Vitamin K given": 0,
            "TTC eye ointment": 0,
            "Cord CHX given": 0,
            "Breastfeeding <1 hr": 0,
            "Oxygen therapy": 0,
            "Antibiotics given": 0,
            "Phototherapy": 0,
            "CPAP used": 0,
            "KMC done": 0,
            "Blood culture done": 0,
            "Discharged alive": 0,
            "Neonatal deaths": 0,
            "Referred/transferred": 0,
            "Prematurity": 0,
        }

    def ct(col):
        return int((reg[col] == TICK).sum()) if col in reg.columns else 0

    bw = pd.to_numeric(reg["Birth weight (gm)"], errors="coerce").dropna() if "Birth weight (gm)" in reg.columns else pd.Series(dtype=float)
    place = reg["Place of delivery (code)"].astype(str) if "Place of delivery (code)" in reg.columns else pd.Series(dtype=str)
    mode  = reg["Mode of delivery (code)"].astype(str) if "Mode of delivery (code)" in reg.columns else pd.Series(dtype=str)
    disst = reg["Discharge status (code)"].astype(str) if "Discharge status (code)" in reg.columns else pd.Series(dtype=str)

    def _or(cols):
        mask = pd.Series(False, index=reg.index)
        for c in cols:
            if c in reg.columns:
                mask |= (reg[c] == TICK)
        return int(mask.sum())

    return {
        "Total admissions":         len(reg),
        "Inborn":                   int((place == "1").sum()),
        "Outborn":                  int((place == "2").sum()),
        "SVD":                      int((mode == "1").sum()),
        "Caesarean section":        int((mode == "2").sum()),
        "Assisted delivery":        int((mode.isin(["3", "4"])).sum()),
        "Weighed at admission":     int(bw.count()),
        "LBW (<2500 g)":            int((bw < 2500).sum()),
        "VLBW (<=2000 g)":          int((bw <= 2000).sum()),
        "Asphyxia cases":           ct("Perinatal Asphyxia (√)"),
        "Resuscitated (room)":      ct("Resuscitation (√)"),
        "Bag-mask ventilation":     ct("Resuscitation (√)"),
        "Vitamin K given":          0,
        "TTC eye ointment":         0,
        "Cord CHX given":           0,
        "Breastfeeding <1 hr":      ct("Breast feeding (√)"),
        "Oxygen therapy":           ct("O2 (oxygen) (√)"),
        "Antibiotics given":        ct("Antibiotics (√)"),
        "Phototherapy":             ct("Phototherapy (√)"),
        "CPAP used":                ct("CPAP (√)"),
        "KMC done":                 ct("KMC (√)"),
        "Blood culture done":       0,
        "Discharged alive":         int((reg["A/D"].astype(str) == "A").sum()),
        "Neonatal deaths":          int((reg["A/D"].astype(str) == "D").sum()),
        "Referred/transferred":     int((disst == "3").sum()),
        "Prematurity":              ct("Prematurity (√)"),
    }


# ── Excel styles ───────────────────────────────────────────────────────────────

HDR_COLORS = {
    "title":      "1F497D",   # dark blue
    "id":         "4472C4",   # blue
    "admission":  "70AD47",   # green
    "maternal":   "ED7D31",   # orange
    "conditions": "C00000",   # red
    "preventive": "92D050",   # light green
    "interven":   "FFC000",   # amber
    "discharge":  "9DC3E6",   # light blue
    "referral":   "7030A0",   # purple
    "misc":       "595959",   # grey
    "tally":      "FFD700",   # gold
}


def _fill(hex_color, ttype="solid"):
    return PatternFill(fill_type=ttype, fgColor=hex_color)


def _font(bold=False, size=9, color="000000", white=False):
    c = "FFFFFF" if white else color
    return Font(bold=bold, size=size, color=c)


def _border():
    s = Side(style="thin", color="000000")
    return Border(left=s, right=s, top=s, bottom=s)


def _align(h="center", v="center", wrap=True):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


# ── Header structure ───────────────────────────────────────────────────────────
SECTIONS = [
    ("Identification",        (1, 9),   "Identification",    "id"),
    ("Admission Information", (10, 14), "Admission Info",    "admission"),
    ("Delivery Information",  (15, 20), "Delivery Info",     "preventive"),
    ("Maternal Condition",    (21, 25), "Maternal",          "maternal"),
    ("Admission Problem",     (26, 34), "Problem",           "conditions"),
    ("Management",            (35, 46), "Treatment",         "interven"),
    ("Discharge Information", (47, 53), "Discharge",         "discharge"),
    ("Counseled on",          (54, 56), "Counseling",        "referral"),
    ("Remark",                (57, 57), "",                  "misc"),
]

SUB_SECTIONS = {
    (1, 5):   "Identification",
    (6, 9):   "Address",
    (10, 14): "Admission Information",
    (15, 20): "Delivery Information",
    (21, 25): "Maternal Condition",
    (26, 34): "Admission Problem",
    (35, 46): "Management",
    (47, 53): "Discharge Information",
    (54, 56): "Counseled on",
    (57, 57): "Remark",
}

N_COLS = 57


def _col_headers():
    return [
        "S.No", "MRN", "Name of\nnewborn", "Sex\n(M/F)", "Name of\nmother",
        "Zone", "Woreda", "Gote", "Kebele",
        "Admission\ndate & Time\n(DD/MM/YY - 00:00)", "Admission\nWeight\n(gm)",
        "Temp\n(°C)", "RR\nper '", "Apical HR\nper '",
        "GA\n(weeks)", "Delivery\ndate & Time\n(DD/MM/YY - 00:00)",
        "Mode of\ndelivery\n(write code)", "Place of\ndelivery\n(write code)",
        "Apgar\n1' / 5'", "Birth\nweight\n(gm)",
        "PITC\n(P/N)", "Hep B\n(P/N)", "Hep C\n(P/N)", "VDRL\n(P/N)",
        "A = Alive\nor D = Dead",
        "Prematur-\nity (√)", "Low birth\nweight (√)", "Sepsis\n(√)",
        "RDS\n(√)", "Perinatal\nAsphyxia (√)", "Cong.\nMalform. (√)",
        "Meconium\nAsp. (√)", "Hyperbili-\nrubinemia (√)", "Other\n(specify)",
        "CPAP\n(√)", "Resuscit-\nation (√)", "KMC\n(√)", "Antibio-\ntics (√)",
        "Anticon-\nvulsants (√)", "Photo-\ntherapy (√)", "Glucose\n(√)",
        "O2\n(√)", "Blood\nTransf. (√)", "Incubator /\nthermal (√)",
        "Exchange\nTransf. (√)", "Other\n(specify)",
        "Discharge\ndate & Time\n(DD/MM/YY - 00:00)", "Discharge\nweight\n(gm)",
        "Discharge\nstatus\n(write code)", "Survived\nafter resus\n(√)",
        "If died,\nage in\ndays", "Cause of\ndeath\n(write code)", "LOS\n(days)",
        "Breast feeding /\nnutrition (√)", "Newborn\ncare (√)",
        "CCD\n(√)",
        "Remark / Referred\nfrom or referred to",
    ]


COL_WIDTHS = {
    1: 5, 2: 11, 3: 13, 4: 6, 5: 14,           # Identification
    6: 12, 7: 12, 8: 9, 9: 12,                 # Address
    10: 12, 11: 8, 12: 7, 13: 7, 14: 8,        # Admission Info
    15: 7, 16: 12, 17: 8, 18: 8, 19: 7, 20: 8, # Delivery Info
    21: 7, 22: 7, 23: 7, 24: 7, 25: 9,         # Maternal Condition
    26: 8, 27: 8, 28: 6, 29: 6, 30: 9,         # Admission Problem
    31: 8, 32: 7, 33: 8, 34: 11,
    35: 6, 36: 7, 37: 6, 38: 7, 39: 8, 40: 7,  # Management
    41: 6, 42: 6, 43: 7, 44: 8, 45: 8, 46: 10,
    47: 12, 48: 8, 49: 9, 50: 7, 51: 7, 52: 8, 53: 6,  # Discharge
    54: 9, 55: 8, 56: 6, 57: 18,                 # Counseled on + Remark
}


def write_sheet(ws, reg: pd.DataFrame, facility: str, region: str,
                date_from: str, date_to: str):
    """Write one NICU register sheet to ws."""

    TITLE_ROW     = 1
    FACILITY_ROW  = 2
    L1_ROW        = 4
    L2_ROW        = 5
    COL_NAME_ROW  = 6
    COL_NUM_ROW   = 7
    DATA_START_ROW = 8

    n_cols = N_COLS
    cols   = _col_headers()

    # ── Title ────────────────────────────────────────────────────────────────
    ws.merge_cells(start_row=TITLE_ROW, start_column=1, end_row=TITLE_ROW, end_column=n_cols)
    c = ws.cell(TITLE_ROW, 1, "HEALTH CENTRE / CLINIC / HOSPITAL — NICU ADMISSION REGISTER (04.2 Neonatal & Child Health)")
    c.font      = _font(bold=True, size=12, white=True)
    c.fill      = _fill(HDR_COLORS["title"])
    c.alignment = _align()
    ws.row_dimensions[TITLE_ROW].height = 22

    # ── Facility info ────────────────────────────────────────────────────────
    ws.merge_cells(start_row=FACILITY_ROW, start_column=1, end_row=FACILITY_ROW, end_column=n_cols)
    fac_text = (f"Region: {region}    |    Facility: {facility}"
                f"    |    Period: {date_from} to {date_to}")
    c = ws.cell(FACILITY_ROW, 1, fac_text)
    c.font      = _font(bold=True, size=10, white=True)
    c.fill      = _fill("2E75B6")
    c.alignment = _align(h="left")
    ws.row_dimensions[FACILITY_ROW].height = 16

    # ── Level-1 section headers (row 4) ──────────────────────────────────────
    for (label, (sc, ec), _, ck) in SECTIONS:
        ws.merge_cells(start_row=L1_ROW, start_column=sc, end_row=L1_ROW, end_column=ec)
        c = ws.cell(L1_ROW, sc, label)
        c.font      = _font(bold=True, size=8, white=True)
        c.fill      = _fill(HDR_COLORS[ck])
        c.alignment = _align()
        c.border    = _border()
    ws.row_dimensions[L1_ROW].height = 28

    # ── Level-2 sub-section headers (row 5) ──────────────────────────────────
    for (_, (sc, ec), _, ck) in SECTIONS:
        for col_idx in range(sc, ec + 1):
            c = ws.cell(L2_ROW, col_idx)
            c.fill = _fill(HDR_COLORS[ck])
    for (sc, ec), label in SUB_SECTIONS.items():
        ws.merge_cells(start_row=L2_ROW, start_column=sc, end_row=L2_ROW, end_column=ec)
        c = ws.cell(L2_ROW, sc, label)
        c.font      = _font(bold=True, size=7, white=True)
        c.alignment = _align()
        c.border    = _border()
    ws.row_dimensions[L2_ROW].height = 22

    # ── Column name row (row 6) ───────────────────────────────────────────────
    for i, name in enumerate(cols, start=1):
        section_color = next(
            (ck for (_, (sc, ec), _, ck) in SECTIONS if sc <= i <= ec), "misc"
        )
        c = ws.cell(COL_NAME_ROW, i, name)
        c.font      = _font(bold=True, size=7, white=True)
        c.fill      = _fill(HDR_COLORS[section_color])
        c.alignment = _align()
        c.border    = _border()
    ws.row_dimensions[COL_NAME_ROW].height = 42

    # ── Column number row (row 7) ─────────────────────────────────────────────
    for i in range(1, n_cols + 1):
        section_color = next(
            (ck for (_, (sc, ec), _, ck) in SECTIONS if sc <= i <= ec), "misc"
        )
        c = ws.cell(COL_NUM_ROW, i, f"({i})")
        c.font      = _font(bold=True, size=7, white=False)
        c.fill      = _fill(HDR_COLORS[section_color])
        c.alignment = _align()
        c.border    = _border()
    ws.row_dimensions[COL_NUM_ROW].height = 14

    # ── Column widths ─────────────────────────────────────────────────────────
    for i in range(1, n_cols + 1):
        ws.column_dimensions[get_column_letter(i)].width = COL_WIDTHS.get(i, 8)

    # ── Data rows ─────────────────────────────────────────────────────────────
    reg_cols = list(reg.columns)
    for r_idx, row_data in enumerate(reg.itertuples(index=False), start=DATA_START_ROW):
        ws.row_dimensions[r_idx].height = 16
        alt = (r_idx - DATA_START_ROW) % 2 == 1
        for c_idx, val in enumerate(row_data, start=1):
            cell = ws.cell(r_idx, c_idx, "" if pd.isna(val) or val == "" else val)
            cell.font      = _font(size=8)
            cell.alignment = _align(h="center", wrap=False)
            cell.border    = _border()
            if alt:
                cell.fill = _fill("EBF3FB")
            if str(val) == TICK:
                cell.font = _font(bold=True, size=9, color="C00000")

    # ── Tally row ─────────────────────────────────────────────────────────────
    t_row = DATA_START_ROW + len(reg)
    ws.row_dimensions[t_row].height = 18

    tally = compute_tally(reg)
    tally_map = {
        1:  ("TALLY:", True),
        2:  (f"Adm: {tally['Total admissions']}", False),
        18: (f"In:{tally['Inborn']} Out:{tally['Outborn']}", False),
        17: (f"SVD:{tally['SVD']} CS:{tally['Caesarean section']}", False),
        20: (f"LBW:{tally['LBW (<2500 g)']}", False),
        30: (tally["Asphyxia cases"], False),
        36: (tally["Resuscitated (room)"], False),
        37: (tally["KMC done"], False),
        38: (tally["Antibiotics given"], False),
        25: (f"Alive:{tally['Discharged alive']} Dead:{tally['Neonatal deaths']}", False),
    }
    for ci in range(1, n_cols + 1):
        cell = ws.cell(t_row, ci)
        cell.border = _border()
        cell.fill   = _fill(HDR_COLORS["tally"])
        if ci in tally_map:
            val, bold = tally_map[ci]
            cell.value     = val
            cell.font      = _font(bold=bold, size=8)
            cell.alignment = _align()

    ws.freeze_panes = ws.cell(DATA_START_ROW, 3)


# ── Tally summary sheet ────────────────────────────────────────────────────────

def write_tally_sheet(ws, all_tallies: list[dict]):
    ws.title = "Tally Summary"

    if not all_tallies:
        all_tallies = [compute_tally(pd.DataFrame())]
        all_tallies[0]["_facility"] = "Total"

    headers = ["Indicator"] + [t.get("_facility", "Facility") for t in all_tallies] + ["TOTAL"]
    indicators = [k for k in all_tallies[0].keys() if not k.startswith("_")]

    for ci, h in enumerate(headers, start=1):
        c = ws.cell(1, ci, h)
        c.font      = _font(bold=True, size=9, white=True)
        c.fill      = _fill(HDR_COLORS["title"])
        c.alignment = _align(h="left" if ci == 1 else "center")
        c.border    = _border()
    ws.row_dimensions[1].height = 18

    for ri, ind in enumerate(indicators, start=2):
        ws.row_dimensions[ri].height = 15
        vals = [t.get(ind, 0) for t in all_tallies]
        row = [ind] + vals + [sum(v for v in vals if isinstance(v, (int, float)))]
        for ci, val in enumerate(row, start=1):
            c = ws.cell(ri, ci, val)
            c.font      = _font(size=9, bold=(ci == len(row)))
            c.alignment = _align(h="left" if ci == 1 else "center", wrap=False)
            c.border    = _border()
            if ri % 2 == 0:
                c.fill = _fill("F2F2F2")

    ws.column_dimensions["A"].width = 32
    for ci in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 16


# ── Data loading and filtering ─────────────────────────────────────────────────

def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.str.strip()
    if RAW["enroll_date"] in df.columns:
        df[RAW["enroll_date"]] = pd.to_datetime(df[RAW["enroll_date"]], errors="coerce")
    return df


def filter_df(df, start=None, end=None, region=None, facility=None):
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else [])
    df = df.copy()
    dc = RAW["enroll_date"]
    if dc in df.columns:
        dt_col = pd.to_datetime(df[dc], errors="coerce")
        if start:
            df = df[dt_col >= pd.Timestamp(start)]
            dt_col = pd.to_datetime(df[dc], errors="coerce")
        if end:
            df = df[dt_col <= pd.Timestamp(end)]
    if region:
        rcol = RAW["region"]
        if rcol in df.columns:
            reg_series = df[rcol].fillna("").astype(str).str.strip().str.lower()
            df = df[reg_series == region.strip().lower()]
    if facility:
        fcol = RAW["facility"]
        if fcol in df.columns:
            fac_series = df[fcol].fillna("").astype(str).str.strip().str.lower()
            df = df[fac_series == facility.strip().lower()]
    # Only keep rows that look like NICU admissions
    if len(df) > 0:
        keys = [RAW["admit_date"], RAW["dob"], RAW["birth_weight"]]
        mask = pd.Series(False, index=df.index)
        for k in keys:
            if k in df.columns:
                mask |= df[k].notna()
        df = df[mask].reset_index(drop=True)
    return df.reset_index(drop=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Generate NICU Admission Register from Neonatal Care Form CSV export"
    )
    ap.add_argument("--input",  default="neonatal_data.csv",  help="Input CSV path")
    ap.add_argument("--output", default="neonatal_register.xlsx", help="Output Excel path")
    ap.add_argument("--start",  default=None, help="Filter: start date YYYY-MM-DD")
    ap.add_argument("--end",    default=None, help="Filter: end date YYYY-MM-DD")
    ap.add_argument("--region",   default=None, help="Filter: region name")
    ap.add_argument("--facility", default=None, help="Filter: facility name")
    ap.add_argument("--sheet-per-facility", action="store_true",
                    help="Create one sheet per facility (default: all in one sheet)")
    args = ap.parse_args()

    print(f"Loading {args.input} ...")
    df = load(args.input)
    df = filter_df(df, args.start, args.end, args.region, args.facility)
    print(f"Records after filter: {len(df):,}")

    if len(df) == 0:
        print("No records match the filter. Exiting.")
        return

    wb = Workbook()
    wb.remove(wb.active)

    all_tallies = []

    if args.sheet_per_facility:
        fcol = RAW["facility"]
        if fcol in df.columns:
            facilities = df[fcol].dropna().unique()
        else:
            facilities = []
        print(f"Generating {len(facilities)} facility sheet(s)...")
        for fac in sorted(facilities):
            grp = df[df[fcol] == fac]
            region = grp[RAW["region"]].mode()[0] if RAW["region"] in grp.columns and len(grp) else ""
            d_from = str(grp[RAW["enroll_date"]].min().date()) if RAW["enroll_date"] in grp.columns and grp[RAW["enroll_date"]].notna().any() else "—"
            d_to   = str(grp[RAW["enroll_date"]].max().date()) if RAW["enroll_date"] in grp.columns and grp[RAW["enroll_date"]].notna().any() else "—"

            reg = build_register(grp)
            sheet_name = str(fac)[:28].strip()
            ws = wb.create_sheet(title=sheet_name)
            write_sheet(ws, reg, fac, region, d_from, d_to)

            t = compute_tally(reg)
            t["_facility"] = sheet_name
            all_tallies.append(t)
            print(f"  {fac}: {len(reg)} rows")
    else:
        fcol = RAW["facility"]
        fac_list = df[fcol].dropna().unique() if fcol in df.columns else []
        fac_label = fac_list[0] if len(fac_list) == 1 else f"{len(fac_list)} Facilities"
        region = args.region
        if RAW["region"] in df.columns and not region:
            region = df[RAW["region"]].mode()[0]
        d_from = str(df[RAW["enroll_date"]].min().date()) if RAW["enroll_date"] in df.columns and df[RAW["enroll_date"]].notna().any() else "—"
        d_to   = str(df[RAW["enroll_date"]].max().date()) if RAW["enroll_date"] in df.columns and df[RAW["enroll_date"]].notna().any() else "—"

        print(f"Building register for {len(df):,} rows ...")
        reg = build_register(df)
        ws  = wb.create_sheet(title="NICU Register")
        write_sheet(ws, reg, fac_label, str(region), d_from, d_to)

        t = compute_tally(reg)
        t["_facility"] = fac_label
        all_tallies.append(t)

    ws_tally = wb.create_sheet(title="Tally Summary")
    write_tally_sheet(ws_tally, all_tallies)

    wb.save(args.output)
    print(f"\nSaved: {args.output}")

    combined = {k: sum(t.get(k, 0) for t in all_tallies if isinstance(t.get(k), (int, float)))
                for k in all_tallies[0] if not k.startswith("_")}
    print("\n" + "=" * 50)
    print("  TALLY SUMMARY")
    print("=" * 50)
    for k, v in combined.items():
        print(f"  {k:<35} {v:>6}")


if __name__ == "__main__":
    main()
