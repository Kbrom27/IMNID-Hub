"""
================================================================================
  PROJECT  : Maternal Health DHIS2 Registry
  FILE     : delivery_register.py
  PURPOSE  : Generate Ethiopian MoH Health Centre/Clinic/Hospital Delivery
             Register (MoH V1 2021) from DHIS2 tracker export (maternal_data.csv)
  USAGE    : python delivery_register.py
               [--input  maternal_data.csv]
               [--output delivery_register.xlsx]
               [--start  YYYY-MM-DD]  [--end YYYY-MM-DD]
               [--region REGION_NAME] [--facility FACILITY_NAME]
               [--sheet-per-facility]
  OUTPUT   : Excel workbook — one "Delivery Register" sheet per facility (or all
             combined) plus a "Tally Summary" sheet
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

# ── Raw CSV column names ─────────────────────────────────────────────────────
RAW = {
    "enroll_date":      "enrollment_date",
    "facility":         "org_unit",
    "region":           "parent_org_unit",
    "mrn":              "MRN",
    "address":          "Mothers adress",
    "age":              "Age",
    "del_date":         "Delivery summary_Date of Delivery:",
    "del_time":         "Delivery summary_Time of Delivery:",
    "del_mode":         "Delivery summary_Mode of Delivery",
    "vacuum":           "Delivery summary_Vacuum/Forceps",
    "episiotomy":       "Delivery summary_Episiotomy performed:",
    "cct":              "Delivery summary_Controlled Cord Traction (CCT):",
    "uterotonics":      "Delivery summary_Uterotonics given",
    "obs_cond":         "Delivery summary_Obstetric condition at delivery",
    "outcome":          "Delivery summary_Outcome",
    "stillbirth":       "Delivery summary_Stillbirth:",
    "apgar1":           "Delivery summary_Apgar Score 1st min",
    "apgar5":           "Delivery summary_Apgar Score 5th min",
    "sex":              "Delivery summary_Sex",
    "birth_weight":     "Delivery summary_Birth Weight (grams):",
    "nb_immun":         "Delivery summary_Newborn Immunizations and Interventions",
    "hiv_accept":       "Delivery summary_HIV Testing Accepted:",
    "hiv_result":       "Delivery summary_HIV Result:",
    "art_mother":       "Delivery summary_ARV Rx for Mother: (by type)",
    "art_newborn":      "Delivery summary_ARV Px for Newborn (by type):",
    "feeding_opt":      "Delivery summary_Feeding Option",
    "labour_mode":      "Labour Management _Mode of delivery",
    "partograph_id":    "Delivery Monitoring partograph_event_id",
    "preeclampsia_id":  "PREECLAMPSIA  CHART_event_id",   # note: double space
    "dx_complications": "Diagnosis_Obstetric complications",
    "pp_uterus":        "Postpartum care_Uterus Contracted / Look for PPH",
    "pp_bf":            "Postpartum care_Baby Breastfeeding",
    "pp_bcg":           "Postpartum care_Immunization (BCG)",
    "pp_hiv_test":      "Postpartum care_HIV Tested",
    "pp_hiv_result":    "Postpartum care_HIV Test Result",
    "pp_fp":            "Postpartum care_FP Counseling and Method Provided",
    "pp_action":        "Postpartum care_Action Taken",
    "gest_age":         "Maternal History_Current Gestational Age (From LMP in weeks)",
    "dc_condition":     "Discharge Summary_Condition of Discharge",
}

SVD_VAL = "Spontaneous Vaginal Delivery (SVD)"
CS_VAL  = "Cesarean Section (C-section)"
TICK    = "√"

# Newborn Immunizations DHIS2 code → clinical meaning
# Codes 1–3: preventive services; 4–6: vaccines; 7: birth notification
NB_CODE_MAP = {"1": "VitK", "2": "TTC", "3": "CHX",
               "4": "BCG",  "5": "OPV", "6": "HBV", "7": "NOTIF"}


# ── Field transform helpers ───────────────────────────────────────────────────

def _g(row, key):
    col = RAW.get(key, "")
    return row[col] if col in row.index else np.nan


def _yn(val):
    if pd.isna(val): return ""
    return TICK if str(val).strip().lower() in ("yes", "true", "1", "y") else ""


def _contains(val, kw):
    if pd.isna(val): return ""
    return TICK if kw.lower() in str(val).lower() else ""


def _notna(val):
    return TICK if pd.notna(val) and str(val).strip() not in ("", "nan") else ""


def _sex(val):
    if pd.isna(val): return ""
    v = str(val).strip().lower()
    return "M" if v == "male" else ("F" if v == "female" else "")


def _stillbirth_code(val):
    if pd.isna(val): return ""
    v = str(val).strip().lower()
    return "1" if "fresh" in v else ("2" if "macerated" in v else "")


def _clean_bw(val):
    try:
        v = float(val)
        if 0 < v < 20: v *= 1000   # entered in kg → convert to grams
        return int(v)
    except (ValueError, TypeError):
        return ""


def _hiv_code(val):
    if pd.isna(val): return ""
    v = str(val).lower()
    if "+ve" in v or "positive" in v: return "P"
    if "-ve" in v or "negative" in v: return "N"
    return ""


def _nb_code(val, targets):
    """Tick if any of targets (set of code strings) appear in comma-separated val."""
    if pd.isna(val): return ""
    parts = {p.strip() for p in str(val).split(",")}
    return TICK if parts & set(targets) else ""


def _vaccines(nb_immun, bcg_pp):
    """Register vaccine codes: 1=BCG 2=OPV 3=HBV."""
    codes = []
    if pd.notna(nb_immun):
        pts = {p.strip() for p in str(nb_immun).split(",")}
        if "4" in pts: codes.append("1")
        if "5" in pts: codes.append("2")
        if "6" in pts: codes.append("3")
    if not codes and pd.notna(bcg_pp) and str(bcg_pp).strip().lower() == "yes":
        codes.append("1")
    return ",".join(codes)


def _utero(val):
    """Standardise uterotonic to register codes 1=Oxytocin 2=Miso 3=Ergometrine 4=Other."""
    if pd.isna(val): return ""
    v = str(val).strip()
    if all(c in "1234, " for c in v):   # already coded
        return v.replace(" ", "")
    vl = v.lower()
    codes = []
    if "oxytocin"    in vl: codes.append("1")
    if "misoprostol" in vl: codes.append("2")
    if "ergometrine" in vl: codes.append("3")
    return ",".join(codes) if codes else "4"


def _dc_flags(val):
    if pd.isna(val): return "", "", ""
    v = str(val).strip().lower()
    return (
        TICK if v in ("improved", "cured") else "",
        TICK if v == "same" else "",
        TICK if v == "dead" else "",
    )


def _death_cause(obs):
    if pd.isna(obs): return ""
    v = str(obs).lower()
    if any(x in v for x in ("hemorrhage", "pph", "aph")): return "1"
    if any(x in v for x in ("eclampsia", "pe/")):          return "2"
    if "obstructed" in v:                                   return "3"
    if any(x in v for x in ("sepsis", "prom")):            return "4"
    if "anemia" in v:                                       return "5"
    return "6"


def _pph(obs, pp_ut):
    a = TICK if pd.notna(obs) and "pph" in str(obs).lower() else ""
    b = TICK if pd.notna(pp_ut) and "pph" in str(pp_ut).lower() else ""
    return a or b


def _other_comp(obs):
    if pd.isna(obs): return ""
    v = str(obs).lower()
    if not any(x in v for x in ("eclampsia", "aph", "antepartum", "pph", "postpartum")):
        return TICK if v.strip() else ""
    return ""


def _fp_method(val):
    if pd.isna(val): return ""
    v = str(val).strip().lower()
    for kw, code in [("implant","Imp"),("iucd","IUCD"),("tubal","TL"),
                     ("pill","POP"),("condom","Oth")]:
        if kw in v: return code
    return ""


def _new_acceptor(val):
    if pd.isna(val): return ""
    return TICK if str(val).strip().lower() not in ("", "nan", "counseled only") else ""


def _preterm(gest):
    try:    return TICK if float(gest) < 37 else ""
    except: return ""


def _bf_code(val):
    if pd.isna(val): return ""
    v = str(val).strip().lower()
    if v in ("yes", "true", "1"): return "1"   # assume < 1hr
    if v in ("no", "false", "0"): return "4"
    return ""


def _del_datetime(d, t):
    ds = str(d)[:10] if pd.notna(d) else ""
    ts = str(t)[:5]  if pd.notna(t) else ""
    return f"{ds} {ts}".strip() if ds else ""


def _partograph(val):
    return "Y" if pd.notna(val) and str(val).strip() not in ("", "nan") else "N"


def _other_proc(lm):
    if pd.isna(lm): return ""
    return TICK if "operative" in str(lm).lower() else ""


def _extract_patient_name(row) -> str:
    """Extract mother/patient name from DHIS2 TEI attributes, CSV export or OpenMRS columns."""
    if not isinstance(row, (dict, pd.Series)):
        return ""

    def _val(keys):
        for k in keys:
            if k in row and pd.notna(row[k]):
                v = str(row[k]).strip()
                if v and v.lower() not in ("nan", "none", "null", ""):
                    return v
        return ""

    # 1. Ethiopian 3-part name attributes (Mothers First Name, Father Name, Grandfather Name)
    first = _val([
        "Mothers First Name", "Mother First Name", "Mother's First Name",
        "Neonate First Name", "First Name", "first_name", "given_name", "firstName",
        "X9OEn2gPhss"
    ])
    father = _val([
        "Mothers Father Name", "Mother Father Name", "Mother's Father Name",
        "Father Name", "Middle Name", "middle_name", "middleName",
        "NZramclXjFR"
    ])
    grand = _val([
        "Mothers Grandfather Name", "Mother Grandfather Name", "Mother's Grandfather Name",
        "Grandfather Name", "Neonate Last Name", "Last Name", "last_name", "familyName", "lastName",
        "DiPJa4otIL7"
    ])

    parts = [p for p in (first, father, grand) if p]
    if parts:
        return " ".join(parts)

    # 2. Combined full name fields
    full = _val([
        "Mothers Name", "Mother Name", "Mother's Name", "maternal_name",
        "Patient Name", "patient_name", "Full Name", "full_name",
        "Name", "name", "client_name", "Client Name", "patient_display"
    ])
    if full:
        return full

    # 3. Dynamic search across all row keys for any key containing name
    cols = row.index if hasattr(row, "index") else row.keys()
    for col in cols:
        col_str = str(col).lower()
        if "name" in col_str and not any(skip in col_str for skip in ["staff", "drug", "facility", "medication", "user", "order", "reason", "org"]):
            val = row[col]
            if pd.notna(val):
                v_str = str(val).strip()
                if v_str and v_str.lower() not in ("nan", "none", "null", ""):
                    return v_str

    return ""


def _extract_newborn_mrn(row) -> str:
    """Extract newborn MRN if present."""
    if not isinstance(row, (dict, pd.Series)):
        return ""
    for k in ["Neonate MRN", "Newborn MRN", "MRN (Newborn)", "Child MRN", "Infant MRN", "newborn_mrn"]:
        if k in row and pd.notna(row[k]):
            v = str(row[k]).strip()
            if v and v.lower() not in ("nan", "none", "null", ""):
                return v
    return ""


# ── Register row builder ──────────────────────────────────────────────────────

def build_row(row, sn):
    obs  = _g(row, "obs_cond")
    dc   = _g(row, "dc_condition")
    nb   = _g(row, "nb_immun")
    ppup = _g(row, "pp_uterus")
    a1   = _g(row, "apgar1")
    a5   = _g(row, "apgar5")
    stable, unstable, died = _dc_flags(dc)
    hiv_res = _hiv_code(_g(row, "hiv_result")) or _hiv_code(_g(row, "pp_hiv_result"))
    a1s = str(int(a1)) if pd.notna(a1) else "?"
    a5s = str(int(a5)) if pd.notna(a5) else "?"
    apgar = f"{a1s}/{a5s}" if pd.notna(a1) or pd.notna(a5) else ""
    bw = _clean_bw(_g(row, "birth_weight"))

    return {
        # ── Identification ──────────────────────────────────────────
        "(1) S.N":                  sn,
        "(2) MRN":                  _g(row, "mrn") or "",
        "(3) Name":                 _extract_patient_name(row),
        "(4) Age":                  int(_g(row, "age")) if pd.notna(_g(row, "age")) else "",
        "(5) Kebele":               _g(row, "address") or "",

        # ── Mode of Delivery ────────────────────────────────────────
        "(6) Delivery Date/Time":   _del_datetime(_g(row,"del_date"), _g(row,"del_time")),
        "(7) Partograph (Y/N)":     _partograph(_g(row, "partograph_id")),
        "(8) SVD":                  TICK if str(_g(row,"del_mode")) == SVD_VAL else "",
        "(9) C/S":                  TICK if str(_g(row,"del_mode")) == CS_VAL  else "",
        "(10) Forceps/Vacuum":      _yn(_g(row, "vacuum")),
        "(11) Episiotomy":          _yn(_g(row, "episiotomy")),
        "(12) Other procedures":    _other_proc(_g(row, "labour_mode")),

        # ── Active management 3rd stage ─────────────────────────────
        "(13) Uterotonic (code)":   _utero(_g(row, "uterotonics")),
        "(14) CCT":                 _yn(_g(row, "cct")),

        # ── Maternal condition ───────────────────────────────────────
        "(15) Stable":              stable,
        "(16) Unstable/Referred":   unstable,
        "(17) Died":                died,
        "(18) Cause of Death":      _death_cause(obs) if died == TICK else "",

        # ── Obstetric Complications ─────────────────────────────────
        "(19) Pre-eclampsia":       _notna(_g(row, "preeclampsia_id")),
        "(20) Eclampsia":           _contains(obs, "Eclampsia"),
        "(21) APH":                 _contains(obs, "APH") or _contains(obs, "Antepartum"),
        "(22) PPH":                 _pph(obs, ppup),
        "(23) Other complications": _other_comp(obs),
        "(24) Referred":            "" ,   # referred flag not reliably coded in this dataset

        # ── Newborn birth outcome ────────────────────────────────────
        "(25) Alive":               _contains(_g(row,"outcome"), "Alive"),
        "(26) Apgar 1'/5'":         apgar,
        "(27) Sex (M/F)":           _sex(_g(row, "sex")),
        "(28) Weight (g)":          bw,
        "(29) Stillbirth (1/2)":    _stillbirth_code(_g(row, "stillbirth")),
        "(30) Live birth died":     "",

        # ── Preventive services: Newborn ─────────────────────────────
        "(31) MRN (Newborn)":       _extract_newborn_mrn(row),
        "(32) Vitamin K":           _nb_code(nb, {"1"}),
        "(33) TTC eye ointment":    _nb_code(nb, {"2"}),
        "(34) Chlorhexidine":       _nb_code(nb, {"3"}),
        "(35) Vaccinated at birth": _vaccines(nb, _g(row, "pp_bcg")),

        # ── Maternal HIV+ care ────────────────────────────────────────
        "(36) HIV testing accepted": _yn(_g(row, "hiv_accept")),
        "(37) HIV re-testing":       "",
        "(38) HIV result (P/N)":     hiv_res,
        "(39) Known HIV+":           _notna(_g(row, "art_mother")),
        "(40) Target population":    "",
        "(41) PMTCT link":           "",
        "(42) Feeding counselled":   _notna(_g(row, "feeding_opt")),
        "(43) Mother's ART":         str(_g(row,"art_mother")) if pd.notna(_g(row,"art_mother")) else "",
        "(44) Newborn AZT+NVP":      _notna(_g(row, "art_newborn")),

        # ── Partner HIV testing ───────────────────────────────────────
        "(45) Partner HIV testing":  "",
        "(46) Partner HIV result":   "",
        "(47) Partner → ART":        "",
        "(48) Partner target pop":   "",

        # ── IPPFP ─────────────────────────────────────────────────────
        "(49) New acceptor":         _new_acceptor(_g(row, "pp_fp")),
        "(50) Repeat acceptor":      "",
        "(51) IPPFP method":         _fp_method(_g(row, "pp_fp")),

        # ── Newborn problems ──────────────────────────────────────────
        "(52) Prematurity":          _preterm(_g(row, "gest_age")),
        "(53) Sepsis/VSD":           "",
        "(54) Resp distress":        "",
        "(55) LBW":                  TICK if isinstance(bw, int) and 0 < bw < 2500 else "",
        "(56) Congenital malform":   "",
        "(57) Other NB":             "",
        "(58) Breastfeeding code":   _bf_code(_g(row, "pp_bf")),

        # ── Treatment and outcome ─────────────────────────────────────
        "(59) O2/Resuscitation":     "",
        "(60) Resuscitated&survived":"",
        "(61) Newborn died":         "",
        "(62) Age at death":         "",
        "(63) NB cause of death":    "",
        "(64) Birth notification":   "",
        "(65) Managed by":           "",
        "(66) Remark":               "",
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
            "Total deliveries": 0,
            "SVD count": 0,
            "C/S count": 0,
            "Forceps/Vacuum": 0,
            "Maternal deaths": 0,
            "Pre-eclampsia": 0,
            "Eclampsia": 0,
            "APH cases": 0,
            "PPH cases": 0,
            "Live births": 0,
            "Stillbirths (total)": 0,
            "Fresh stillbirths": 0,
            "Macerated stillbirths": 0,
            "Newborns weighed": 0,
            "LBW (<2500 g)": 0,
            "VLBW (<=2000 g)": 0,
            "Birth weight 2001–2500 g": 0,
            "Chlorhexidine given": 0,
            "HIV tested": 0,
            "HIV positive": 0,
            "IPPFP new acceptors": 0,
            "Preterm (<37 wks)": 0,
        }

    def ct(col):
        return int((reg[col] == TICK).sum()) if col in reg.columns else 0

    bw_vals = pd.to_numeric(reg["(28) Weight (g)"], errors="coerce").dropna() if "(28) Weight (g)" in reg.columns else pd.Series(dtype=float)
    sb = reg["(29) Stillbirth (1/2)"] if "(29) Stillbirth (1/2)" in reg.columns else pd.Series(dtype=str)

    return {
        "Total deliveries":         len(reg),
        "SVD count":                ct("(8) SVD"),
        "C/S count":                ct("(9) C/S"),
        "Forceps/Vacuum":           ct("(10) Forceps/Vacuum"),
        "Maternal deaths":          ct("(17) Died"),
        "Pre-eclampsia":            ct("(19) Pre-eclampsia"),
        "Eclampsia":                ct("(20) Eclampsia"),
        "APH cases":                ct("(21) APH"),
        "PPH cases":                ct("(22) PPH"),
        "Live births":              ct("(25) Alive"),
        "Stillbirths (total)":      int((sb.isin(["1","2"])).sum()),
        "Fresh stillbirths":        int((sb == "1").sum()),
        "Macerated stillbirths":    int((sb == "2").sum()),
        "Newborns weighed":         int(bw_vals.count()),
        "LBW (<2500 g)":            int((bw_vals < 2500).sum()),
        "VLBW (<=2000 g)":          int((bw_vals <= 2000).sum()),
        "Birth weight 2001–2500 g": int(((bw_vals > 2000) & (bw_vals <= 2500)).sum()),
        "Chlorhexidine given":      ct("(34) Chlorhexidine"),
        "HIV tested":               ct("(36) HIV testing accepted"),
        "HIV positive":             int((reg["(38) HIV result (P/N)"] == "P").sum()),
        "IPPFP new acceptors":      ct("(49) New acceptor"),
        "Preterm (<37 wks)":        ct("(52) Prematurity"),
    }


# ── Excel styles ───────────────────────────────────────────────────────────────

HDR_COLORS = {
    "title":      "1F497D",   # dark blue
    "id":         "4472C4",   # blue
    "delivery":   "70AD47",   # green
    "maternal":   "ED7D31",   # orange
    "obstetric":  "C00000",   # red
    "newborn":    "9DC3E6",   # light blue
    "preventive": "92D050",   # light green
    "hiv":        "FF0000",   # red-tinted
    "partner":    "FFC000",   # amber
    "ippfp":      "7030A0",   # purple
    "nb_prob":    "00B0F0",   # sky blue
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
# Each entry: (display_name, col_keys, level2_label, color_key)
# col_keys map to register column names

SECTIONS = [
    # (L1 label,            col range tuple,  L2 label,          color_key)
    ("Identification",       (1,  5),  "Personal Information",    "id"),
    ("Labor & Maternal Outcome", (6, 18), "Mode of Delivery / Active Mgmt / Maternal Condition", "delivery"),
    ("Obstetric Complications", (19, 24), "Intra-partum Complications", "obstetric"),
    ("Newborn Birth Outcome", (25, 30), "Birth Outcome",          "newborn"),
    ("Preventive Services – Newborn", (31, 35), "Newborn Care",  "preventive"),
    ("Maternal HIV+ Care", (36, 44), "HIV & PMTCT",              "hiv"),
    ("Partner HIV Testing", (45, 48), "Partner Testing",         "partner"),
    ("IPPFP", (49, 51), "Immediate Post-Partum FP",              "ippfp"),
    ("Newborn – Problems & Treatment", (52, 63), "Problems & Outcome", "nb_prob"),
    ("Notification", (64, 64), "",                               "misc"),
    ("Managed by", (65, 65), "",                                 "misc"),
    ("Remark", (66, 66), "",                                     "misc"),
]

# Sub-section labels (Level 2, more granular)
SUB_SECTIONS = {
    (6, 7):   "Delivery Info",
    (8, 12):  "Mode of Delivery",
    (13, 14): "Active Mgmt 3rd Stage",
    (15, 18): "Maternal Condition",
    (19, 24): "Obstetric Complications",
    (25, 30): "Newborn Birth Outcome",
    (31, 35): "Preventive – Newborn",
    (36, 44): "Maternal HIV+ Care & PMTCT",
    (45, 48): "Partner Testing",
    (49, 51): "IPPFP (0–48 hrs)",
    (52, 58): "Newborn Problems Identified",
    (59, 63): "Treatment & Outcome",
}


def _col_headers():
    """Returns list of 66 (short_name, col_number_str) tuples."""
    names = [
        "S.N", "MRN", "Name", "Age", "Kebele",
        "Del Date/Time", "Partograph\n(Y/N)", "SVD\n(√)", "C/S\n(√)", "Forceps/\nVacuum (√)",
        "Episio-\ntomy (√)", "Other\nProc (√)", "Uterotonic\n(code)", "CCT\n(√)",
        "Stable\n(√)", "Unstable/\nRef (√)", "Died\n(√)", "Cause\nDeath",
        "Pre-\neclampsia (√)", "Eclampsia\n(√)", "APH\n(√)", "PPH\n(√)",
        "Other\nComp (√)", "Referred\n(√)",
        "Alive\n(√)", "Apgar\n1'/5'", "Sex\n(M/F)", "Weight\n(g)", "Stillbirth\n(1/2)", "Live\nBirth Died",
        "MRN\n(NB)", "Vit K\n(√)", "TTC\n(√)", "Chlorhex\n(√)", "Vaccines\n(code)",
        "HIV Test\nAccepted (√)", "HIV\nRetest (√)", "HIV\nResult P/N", "Known\nHIV+ (√)",
        "Target\nPop", "PMTCT\nLink", "Feeding\nCounsel (√)", "ART\nMother", "NB\nAZT+NVP",
        "Partner\nHIV Test (√)", "Partner\nResult P/N", "Partner\n→ART (√)", "Partner\nTarget Pop",
        "New\nAcceptor (√)", "Repeat\nAcceptor (√)", "IPPFP\nMethod",
        "Premature\n(√)", "Sepsis/\nVSD (√)", "Resp\nDistress (√)", "LBW\n(√)",
        "Congenit\nMalform (√)", "Other\n(√)", "BF Init\nCode",
        "O2/\nResus (√)", "Resus &\nSurvived (√)", "NB\nDied (√)", "Age at\nDeath",
        "NB Cause\nDeath", "Birth\nNotif (√)", "Managed\nby", "Remark",
    ]
    return names


# ── Sheet writer ───────────────────────────────────────────────────────────────

COL_WIDTHS = {
    1: 5, 2: 12, 3: 16, 4: 5, 5: 12,          # Identification
    6: 16, 7: 10, 8: 5, 9: 5, 10: 9, 11: 9, 12: 9,  # Mode of delivery
    13: 10, 14: 5,                              # Active mgmt
    15: 6, 16: 10, 17: 5, 18: 7,               # Maternal condition
    **{c: 7 for c in range(19, 67)},            # rest: narrow
    26: 10, 27: 6, 28: 9, 29: 10,              # newborn specifics
    35: 9, 43: 10, 51: 9, 66: 20,
}

def write_sheet(ws, reg: pd.DataFrame, facility: str, region: str,
                date_from: str, date_to: str):
    """Write one delivery register sheet to ws."""

    TITLE_ROW     = 1
    FACILITY_ROW  = 2
    L1_ROW        = 4   # main section headers
    L2_ROW        = 5   # sub-section headers
    COL_NAME_ROW  = 6   # column labels
    COL_NUM_ROW   = 7   # (1)(2)…(66)
    DATA_START_ROW= 8

    n_cols = 66
    cols   = _col_headers()

    # ── Title ────────────────────────────────────────────────────────────────
    ws.merge_cells(start_row=TITLE_ROW, start_column=1, end_row=TITLE_ROW, end_column=n_cols)
    c = ws.cell(TITLE_ROW, 1, "HEALTH CENTRE / CLINIC / HOSPITAL — DELIVERY REGISTER (MoH V1 2021)")
    c.font      = _font(bold=True, size=13, white=True)
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
    # Paint same section color first
    for (_, (sc, ec), _, ck) in SECTIONS:
        for col_idx in range(sc, ec + 1):
            c = ws.cell(L2_ROW, col_idx)
            c.fill = _fill(HDR_COLORS[ck])
    # Apply sub-section labels where defined
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
        ws.column_dimensions[get_column_letter(i)].width = COL_WIDTHS.get(i, 6)

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
            # Highlight TICK cells in tick columns (8-12, 14-17, 19-25, 29-34, 36, 39, 42, 44, 49, 52-57, 59-61, 64)
            if str(val) == TICK:
                cell.font = _font(bold=True, size=9, color="C00000")

    # ── Tally row ─────────────────────────────────────────────────────────────
    t_row = DATA_START_ROW + len(reg)
    ws.row_dimensions[t_row].height = 18

    tally = compute_tally(reg)

    # Place key tallies at their corresponding register column positions
    tally_map = {
        1:  ("TALLY:", True),
        2:  (f"Deliveries: {tally['Total deliveries']}", False),
        8:  (tally["SVD count"], False),
        9:  (tally["C/S count"], False),
        17: (tally["Maternal deaths"], False),
        21: (tally["APH cases"], False),
        22: (tally["PPH cases"], False),
        25: (tally["Live births"], False),
        28: (tally["Newborns weighed"], False),
        29: (f"SB:{tally['Stillbirths (total)']}", False),
        34: (tally["Chlorhexidine given"], False),
        36: (tally["HIV tested"], False),
        38: (f"P:{tally['HIV positive']}", False),
        55: (tally["LBW (<2500 g)"], False),
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

    # Freeze panes below headers
    ws.freeze_panes = ws.cell(DATA_START_ROW, 3)


# ── Tally summary sheet ────────────────────────────────────────────────────────

def write_tally_sheet(ws, all_tallies: list[dict]):
    """Write aggregated tally sheet comparing facilities."""
    ws.title = "Tally Summary"

    if not all_tallies:
        all_tallies = [compute_tally(pd.DataFrame())]
        all_tallies[0]["_facility"] = "Total"

    headers = ["Indicator"] + [t.get("_facility", "Facility") for t in all_tallies] + ["TOTAL"]
    indicators = [k for k in all_tallies[0].keys() if not k.startswith("_")]

    # Header row
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
            if ri % 2 == 0: c.fill = _fill("F2F2F2")

    ws.column_dimensions["A"].width = 32
    for ci in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 16


# ── Data loading and filtering ─────────────────────────────────────────────────

def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.str.strip()
    df[RAW["enroll_date"]] = pd.to_datetime(df[RAW["enroll_date"]], errors="coerce")
    # Clean age
    age_col = RAW["age"]
    if age_col in df.columns:
        df[age_col] = pd.to_numeric(df[age_col], errors="coerce")
        df.loc[df[age_col] < 10, age_col] = np.nan
    return df


def filter_df(df, start=None, end=None, region=None, facility=None):
    dc = RAW["enroll_date"]
    if start:
        df = df[df[dc] >= pd.Timestamp(start)]
    if end:
        df = df[df[dc] <= pd.Timestamp(end)]
    if region:
        df = df[df[RAW["region"]].str.strip().str.lower() == region.strip().lower()]
    if facility:
        df = df[df[RAW["facility"]].str.strip().str.lower() == facility.strip().lower()]
    # Only keep rows that have a delivery record
    df = df[df[RAW["del_mode"]].notna() | df[RAW["outcome"]].notna()].copy()
    return df.reset_index(drop=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Generate Ethiopian MoH Delivery Register from DHIS2 CSV export"
    )
    ap.add_argument("--input",  default="maternal_data.csv",       help="Input CSV path")
    ap.add_argument("--output", default="delivery_register.xlsx",  help="Output Excel path")
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
    wb.remove(wb.active)   # remove default empty sheet

    all_tallies = []

    if args.sheet_per_facility:
        facilities = df[RAW["facility"]].dropna().unique()
        print(f"Generating {len(facilities)} facility sheet(s)...")
        for fac in sorted(facilities):
            grp = df[df[RAW["facility"]] == fac]
            region = grp[RAW["region"]].mode()[0] if len(grp) else ""
            d_from = str(grp[RAW["enroll_date"]].min().date()) if grp[RAW["enroll_date"]].notna().any() else "—"
            d_to   = str(grp[RAW["enroll_date"]].max().date()) if grp[RAW["enroll_date"]].notna().any() else "—"

            reg = build_register(grp)
            sheet_name = str(fac)[:28].strip()
            ws = wb.create_sheet(title=sheet_name)
            write_sheet(ws, reg, fac, region, d_from, d_to)

            t = compute_tally(reg)
            t["_facility"] = sheet_name
            all_tallies.append(t)
            print(f"  {fac}: {len(reg)} rows")
    else:
        # All records in one sheet
        fac_list = df[RAW["facility"]].dropna().unique()
        fac_label = fac_list[0] if len(fac_list) == 1 else f"{len(fac_list)} Facilities"
        region    = args.region or df[RAW["region"]].mode()[0] if RAW["region"] in df.columns else ""
        d_from = str(df[RAW["enroll_date"]].min().date()) if df[RAW["enroll_date"]].notna().any() else "—"
        d_to   = str(df[RAW["enroll_date"]].max().date()) if df[RAW["enroll_date"]].notna().any() else "—"

        print(f"Building register for {len(df):,} rows ...")
        reg = build_register(df)
        ws  = wb.create_sheet(title="Delivery Register")
        write_sheet(ws, reg, fac_label, str(region), d_from, d_to)

        t = compute_tally(reg)
        t["_facility"] = fac_label
        all_tallies.append(t)

    # ── Tally summary sheet ───────────────────────────────────────────────────
    ws_tally = wb.create_sheet(title="Tally Summary")
    write_tally_sheet(ws_tally, all_tallies)

    wb.save(args.output)
    print(f"\nSaved: {args.output}")

    # ── Console summary ───────────────────────────────────────────────────────
    combined = {k: sum(t.get(k, 0) for t in all_tallies if isinstance(t.get(k), (int, float)))
                for k in all_tallies[0] if not k.startswith("_")}
    print("\n" + "="*50)
    print("  TALLY SUMMARY")
    print("="*50)
    for k, v in combined.items():
        print(f"  {k:<35} {v:>6}")


if __name__ == "__main__":
    main()
