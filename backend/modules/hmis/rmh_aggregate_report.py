"""
================================================================================
  PROJECT  : IMNID — Maternal Health DHIS2 Registry
  FILE     : aggregate_report.py
  PURPOSE  : Compute the Ethiopian MoH "01.2 — Reproductive and Maternal
             Health" aggregate monthly report from DHIS2 tracker data and
             POST the result to a DHIS2 aggregate dataset.

  REPORT   : 01.2 - Reproductive and Maternal Health | Monthly
             Family Planning · ANC · Delivery · PNC · C-Section
             Abortion · Fistula · Maternal Deaths · Teenage Pregnancy

  REQUIRES : pip install requests pandas openpyxl
             Primary tracker : "Maternal Inpatient Data" (delivery/PNC/labs)
             ANC/FP/Abortion indicators need their own program UIDs.

  AUTH     (priority: CLI → env vars → credentials file → interactive)
    CLI  : --url https://imnid.aau.edu.et/dhis --username X --password Y
    File : dhis2_credentials.json

  QUICK START:
    # 1. Preview report — prints computed values, saves Excel
    python aggregate_report.py \\
      --delivery-program <UID> \\
      --org-unit <OU_UID_or_NAME> \\
      --period 202410 \\
      --preview report_oct2024.xlsx

    # 2. Submit to DHIS2 aggregate (dry-run first)
    python aggregate_report.py \\
      --delivery-program <UID> \\
      --org-unit <OU_UID_or_NAME> \\
      --period 202410 \\
      --dataset <AGGREGATE_DATASET_UID> \\
      --dry-run

    # 3. Submit for real
    python aggregate_report.py \\
      --delivery-program <UID> \\
      --org-unit <OU_UID_or_NAME> \\
      --period 202410 \\
      --dataset <AGGREGATE_DATASET_UID> \\
      --submit
================================================================================
"""

import argparse
import getpass
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from typing import Any, Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("ERROR: 'requests' not installed.  pip install requests")
    sys.exit(1)

try:
    import openpyxl
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

warnings.filterwarnings("ignore")
CRED_FILE = Path("dhis2_credentials.json")

# ── Tracker column names after API→RAW renaming ───────────────────────────────
# These match the CSV export names (same as RAW dict in delivery_register.py).
# NOTE: column names are built live by fetch_tracker_df() as "{Stage}_{DE name}"
# using the real program metadata, so the values below are the ACTUAL DHIS2
# names (verified against Metadata/dhis2_metadata_for_openmrs_3x.json).
_DEL_MODE    = "Delivery summary_Mode of Delivery maternal"
_OUTCOME     = "Delivery summary_birth outcome"
_OBS_COND    = "Delivery summary_Obstetric condition at delivery"
_UTEROTONICS = "Delivery summary_Uterotonics given"
_STILLBIRTH  = "Delivery summary_Stillbirth"
_DEL_DATE    = "Delivery summary_event_date"
_PNC_DATE    = "Postpartum care_event_date"
_DISC_COND   = "Discharge Summary_Condition of Discharge"
_AGE         = "Age"
_GEST_AGE    = "Maternal History_Gestational Age (From LMP in weeks)"
_PPFP        = "Postpartum care_FP Counseling and Method Provided pp"


# ── Indicator computation helpers ─────────────────────────────────────────────

def _col(df: pd.DataFrame, col: str) -> pd.Series:
    """Return column as string series, or empty series if missing."""
    if col in df.columns:
        return df[col].astype(str).fillna("")
    return pd.Series("", index=df.index)


def _str_match(df: pd.DataFrame, col: str, patterns: list[str]) -> int:
    s = _col(df, col)
    mask = pd.Series(False, index=df.index)
    for p in patterns:
        mask |= s.str.contains(p, case=False, na=False)
    return int(mask.sum())


def _get_field_val(row: Any, de_uid: str, col_name: str = "") -> str:
    """Retrieve string value from a row dictionary or Series by DE UID or column fallback."""
    v = row.get(de_uid) if hasattr(row, "get") else None
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    if col_name and hasattr(row, "get"):
        cv = row.get(col_name)
        if cv is not None and str(cv).strip() != "":
            return str(cv).strip()
    return ""


def _has_code_or_label(
    row: Any,
    de_uid: str,
    target_codes: set[str],
    target_labels: Optional[set[str]] = None,
    col_name: str = "",
) -> bool:
    """Check if row contains target codes or target labels for a data element."""
    if not hasattr(row, "get"):
        return False

    # 1. Check accumulated sets across all events for this TEI
    all_v = row.get(f"{de_uid}_all")
    if isinstance(all_v, (set, list)):
        for tc in target_codes:
            if tc.lower() in all_v:
                return True

    if target_labels:
        all_l = row.get(f"{de_uid}_all_labels")
        if isinstance(all_l, (set, list)):
            for tl in target_labels:
                for item in all_l:
                    if tl.lower() in item:
                        return True

    # 2. Check current row's primary value
    v = _get_field_val(row, de_uid, col_name).lower()
    if v:
        parts = [p.strip() for p in v.split(",")]
        for tc in target_codes:
            if tc.lower() in parts or tc.lower() == v:
                return True
        if target_labels:
            for tl in target_labels:
                if tl.lower() in v:
                    return True

    # 3. Check label field if present
    lbl = str(row.get(f"{de_uid}_label", "")).strip().lower()
    if lbl and target_labels:
        for tl in target_labels:
            if tl.lower() in lbl:
                return True

    return False


def _ages(df: pd.DataFrame) -> pd.Series:
    a = _numeric(df, _AGE)
    if "vbaNV9kiRFp" in df.columns:
        a = a.fillna(_numeric(df, "vbaNV9kiRFp"))
    if "Age" in df.columns:
        a = a.fillna(_numeric(df, "Age"))
    return a


def _age_mask(df: pd.DataFrame, low: int, high: int | None) -> pd.Series:
    a = _ages(df)
    return (a >= low) if high is None else ((a >= low) & (a <= high))


def _gest_weeks(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df.get(_GEST_AGE, pd.Series(dtype=float)), errors="coerce")


def _delivery_dates(df: pd.DataFrame) -> pd.Series:
    """Delivery date series: the 'Date of Delivery' value, falling back to the
    delivery event date, enrollment date, or incident date."""
    col1 = "Delivery summary_Date of Delivery"
    dval = pd.to_datetime(df[col1], errors="coerce") if col1 in df.columns else pd.Series(pd.NaT, index=df.index)
    if "hjQZsV03OYe" in df.columns:
        dval = dval.fillna(pd.to_datetime(df["hjQZsV03OYe"], errors="coerce"))
    devt = pd.to_datetime(df[_DEL_DATE], errors="coerce") if _DEL_DATE in df.columns else pd.Series(pd.NaT, index=df.index)
    denr = pd.to_datetime(df.get("enrollment_date"), errors="coerce") if "enrollment_date" in df.columns else pd.Series(pd.NaT, index=df.index)
    dinc = pd.to_datetime(df.get("incident_date"), errors="coerce") if "incident_date" in df.columns else pd.Series(pd.NaT, index=df.index)
    return dval.fillna(devt).fillna(denr).fillna(dinc)


def _pnc_days(df: pd.DataFrame) -> pd.Series:
    """Days from delivery to PNC event; NaN if either date missing."""
    d0 = _delivery_dates(df)
    d1 = pd.to_datetime(df.get(_PNC_DATE), errors="coerce")
    if d0 is None or d1 is None:
        return pd.Series(np.nan, index=df.index)
    diff = (d1 - d0).dt.days
    return diff.where((diff >= 0) & (diff <= 7))   # only valid ≤7 day PNC


def _str_age_match(df, col, patterns, low, high):
    return int((_str_match_mask(df, col, patterns) & _age_mask(df, low, high)).sum())


def _str_match_mask(df: pd.DataFrame, col: str, patterns: list[str]) -> pd.Series:
    s = _col(df, col)
    mask = pd.Series(False, index=df.index)
    for p in patterns:
        mask |= s.str.contains(p, case=False, na=False)
    return mask


# ── Indicator class ───────────────────────────────────────────────────────────

class Indicator:
    """One row in the HMIS 01.2 aggregate report."""
    __slots__ = ("code", "label", "section", "source", "_fn")

    def __init__(self, code, label, section, source="DEL", compute=None):
        self.code    = code
        self.label   = label
        self.section = section
        self.source  = source   # which program supplies the data
        self._fn     = compute

    def compute(self, df: pd.DataFrame):
        """Return int value, or None if not computable from the supplied DataFrame."""
        if self._fn is None or df is None or df.empty:
            return None
        try:
            v = self._fn(df)
            return int(v) if v is not None else None
        except Exception:
            return None


# ── Full indicator list — mirrors the PDF row by row ─────────────────────────

INDICATORS: list[Indicator] = [

    # ════════════════════════════════════════════════════════════════════════════
    # FAMILY PLANNING
    # ════════════════════════════════════════════════════════════════════════════
    # New acceptors by age
    Indicator("MAT_CAR_Age.1.1", "Contraceptive new acceptors 10-14 yrs",   "FP", source="FP"),
    Indicator("MAT_CAR_Age.1.2", "Contraceptive new acceptors 15-19 yrs",   "FP", source="FP"),
    Indicator("MAT_CAR_Age.1.3", "Contraceptive new acceptors 20-24 yrs",   "FP", source="FP"),
    Indicator("MAT_CAR_Age.1.4", "Contraceptive new acceptors 25-29 yrs",   "FP", source="FP"),
    Indicator("MAT_CAR_Age.1.5", "Contraceptive new acceptors 30-49 yrs",   "FP", source="FP"),
    # Repeat acceptors by age
    Indicator("MAT_CAR_Age.2.1", "Contraceptive repeat acceptors 10-14 yrs","FP", source="FP"),
    Indicator("MAT_CAR_Age.2.2", "Contraceptive repeat acceptors 15-19 yrs","FP", source="FP"),
    Indicator("MAT_CAR_Age.2.3", "Contraceptive repeat acceptors 20-24 yrs","FP", source="FP"),
    Indicator("MAT_CAR_Age.2.4", "Contraceptive repeat acceptors 25-29 yrs","FP", source="FP"),
    Indicator("MAT_CAR_Age.2.5", "Contraceptive repeat acceptors 30-49 yrs","FP", source="FP"),
    # New acceptors by method
    Indicator("MAT_CAR_Mtd.1.1", "New acceptors - Oral Contraceptives",  "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.1.2", "New acceptors - Injectables",          "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.1.3", "New acceptors - Implants",             "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.1.4", "New acceptors - IUCD",                 "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.1.5", "New acceptors - Vasectomy",            "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.1.6", "New acceptors - Tubal ligation",       "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.1.7", "New acceptors - Others",               "FP", source="FP"),
    # Repeat acceptors by method
    Indicator("MAT_CAR_Mtd.2.1", "Repeat acceptors - Oral Contraceptives","FP", source="FP"),
    Indicator("MAT_CAR_Mtd.2.2", "Repeat acceptors - Injectables",        "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.2.3", "Repeat acceptors - Implants",           "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.2.4", "Repeat acceptors - IUCD",               "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.2.5", "Repeat acceptors - Vasectomy",          "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.2.6", "Repeat acceptors - Tubal ligation",     "FP", source="FP"),
    Indicator("MAT_CAR_Mtd.2.7", "Repeat acceptors - Others",             "FP", source="FP"),
    # IPPCAR — Immediate Postpartum (derived from Postpartum care stage)
    Indicator("MAT_IPPCAR_Age.1", "PPFP acceptors 10-14 yrs", "FP", source="DEL",
              compute=lambda df: int((_age_mask(df, 10, 14) & _col(df,_PPFP).ne("")).sum())),
    Indicator("MAT_IPPCAR_Age.2", "PPFP acceptors 15-19 yrs", "FP", source="DEL",
              compute=lambda df: int((_age_mask(df, 15, 19) & _col(df,_PPFP).ne("")).sum())),
    Indicator("MAT_IPPCAR_Age.3", "PPFP acceptors 20-24 yrs", "FP", source="DEL",
              compute=lambda df: int((_age_mask(df, 20, 24) & _col(df,_PPFP).ne("")).sum())),
    Indicator("MAT_IPPCAR_Age.4", "PPFP acceptors 25-29 yrs", "FP", source="DEL",
              compute=lambda df: int((_age_mask(df, 25, 29) & _col(df,_PPFP).ne("")).sum())),
    Indicator("MAT_IPPCAR_Age.5", "PPFP acceptors 30-49 yrs", "FP", source="DEL",
              compute=lambda df: int((_age_mask(df, 30, 49) & _col(df,_PPFP).ne("")).sum())),
    # IPPCAR by method
    Indicator("MAT_IPPCAR_Mtd.1", "PPFP - Oral Contraceptives","FP", source="DEL",
              compute=lambda df: _str_match(df,_PPFP,["oral","pill","oc"])),
    Indicator("MAT_IPPCAR_Mtd.2", "PPFP - Implants",            "FP", source="DEL",
              compute=lambda df: _str_match(df,_PPFP,["implant"])),
    Indicator("MAT_IPPCAR_Mtd.3", "PPFP - IUCD",                "FP", source="DEL",
              compute=lambda df: _str_match(df,_PPFP,["iucd","iud"])),
    Indicator("MAT_IPPCAR_Mtd.4", "PPFP - Tubal ligation",      "FP", source="DEL",
              compute=lambda df: _str_match(df,_PPFP,["tubal","ligation","btl"])),
    Indicator("MAT_IPPCAR_Mtd.5", "PPFP - Others",              "FP", source="DEL",
              compute=lambda df: _str_match(df,_PPFP,["other"])),
    # PRLAFP — premature removal (not in delivery tracker)
    Indicator("MAT_LAFPPR.1.1",  "Premature LAFP removal - Implants",     "FP", source="FP"),
    Indicator("MAT_LAFPPR.1.2",  "Premature LAFP removal - IUCD",         "FP", source="FP"),
    Indicator("MAT_LAFPPR.1.3",  "Premature LAFP removal - Others",       "FP", source="FP"),
    Indicator("MAT_TLAFPR.",     "Total LAFP removals in reporting period","FP", source="FP"),

    # ════════════════════════════════════════════════════════════════════════════
    # ANC — requires separate ANC tracker program
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("MAT_ANC1_GA.1.1",  "ANC1 ≤12 weeks gestational age",          "ANC", source="ANC"),
    Indicator("MAT_ANC1_GA.1.2",  "ANC1 >12 and ≤16 weeks",                  "ANC", source="ANC"),
    Indicator("MAT_ANC1_GA.1.3",  "ANC1 >16 weeks",                          "ANC", source="ANC"),
    Indicator("MAT_ANC1_MA.1.1",  "ANC1 by age 10-14 yrs",                   "ANC", source="ANC"),
    Indicator("MAT_ANC1_MA.1.2",  "ANC1 by age 15-19 yrs",                   "ANC", source="ANC"),
    Indicator("MAT_ANC1_MA.1.3",  "ANC1 by age ≥20 yrs",                     "ANC", source="ANC"),
    Indicator("MAT_ANC4+_MA.1.1", "ANC4+ by age 10-14 yrs",                  "ANC", source="ANC"),
    Indicator("MAT_ANC4+_MA.1.2", "ANC4+ by age 15-19 yrs",                  "ANC", source="ANC"),
    Indicator("MAT_ANC4+_MA.1.3", "ANC4+ by age ≥20 yrs",                    "ANC", source="ANC"),
    Indicator("MAT_ANC4+_GA.1.1", "ANC4+ ≤30 weeks gestational age",         "ANC", source="ANC"),
    Indicator("MAT_ANC4+_GA.1.2", "ANC4+ >30 weeks gestational age",         "ANC", source="ANC"),
    Indicator("MAT_ANC8+.",        "ANC 8 or more contacts",                  "ANC", source="ANC"),
    Indicator("MAT_SYPH.1.1",     "Syphilis tested - Reactive",               "ANC", source="DEL",
              compute=lambda df: _str_match(df,"Laboratory_VDRL",["reactive","positive"])),
    Indicator("MAT_SYPH.1.2",     "Syphilis tested - Non-Reactive",           "ANC", source="DEL",
              compute=lambda df: _str_match(df,"Laboratory_VDRL",["non-reactive","non reactive","negative"])),
    Indicator("MAT_SYPH.RX.1.",   "Pregnant women treated for syphilis",      "ANC", source="ANC"),
    Indicator("MAT_Hepa.1",       "Hepatitis B tested - Reactive",            "ANC", source="DEL",
              compute=lambda df: _str_match(df,"Laboratory_HBsAg",["reactive","positive"])),
    Indicator("MAT_Hepa.2",       "Hepatitis B tested - Non-Reactive",        "ANC", source="DEL",
              compute=lambda df: _str_match(df,"Laboratory_HBsAg",["non-reactive","non reactive","negative"])),
    Indicator("MAT_Prp.1.",       "HBV prophylaxis received",                 "ANC", source="ANC"),

    # ════════════════════════════════════════════════════════════════════════════
    # DELIVERY
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("L&D_SBA.1.", "Total births attended by skilled health personnel", "DEL",
              compute=lambda df: len(df)),

    Indicator("MAT_PPH.1.1", "PPH - Home",     "DEL",
              compute=lambda df: 0,   # inpatient facility records only
              ),
    Indicator("MAT_PPH.1.2", "PPH - Facility", "DEL",
              compute=lambda df: _str_match(df, _OBS_COND, ["pph","postpartum haemorrhage","postpartum hemorrhage","hemorrhage"])),

    Indicator("MAT_UTER.1.1", "Uterotonics - Oxytocin",    "DEL",
              compute=lambda df: _str_match(df, _UTEROTONICS, ["oxytocin"])),
    Indicator("MAT_UTER.1.2", "Uterotonics - Misoprostol", "DEL",
              compute=lambda df: _str_match(df, _UTEROTONICS, ["misoprostol","mesoprostol"])),
    Indicator("MAT_UTER.1.3", "Uterotonics - Ergometrin",  "DEL",
              compute=lambda df: _str_match(df, _UTEROTONICS, ["ergometrin","ergometrine","ergot"])),
    Indicator("MAT_UTER.1.4", "Uterotonics - Others",      "DEL",
              compute=lambda df: _str_match(df, _UTEROTONICS, ["other"])),

    Indicator("MAT_SBR.SB.", "Number of stillbirths", "DEL",
              compute=lambda df: _str_match(df, _OUTCOME,
                                             ["stillbirth","still birth","still-birth","macerat","fresh still"])),
    Indicator("MAT_SBR.LB.", "Number of live births",  "DEL",
              compute=lambda df: _str_match(df, _OUTCOME,
                                             ["alive","live birth","live"])),

    Indicator("MAT_B&D_IBN.1.", "Institutional birth notifications given",  "DEL",
              compute=lambda df: len(df)),
    Indicator("MAT_B&D_IDN.2.", "Institutional death notifications given",  "DEL",
              compute=lambda df: _str_match(df, _DISC_COND, ["death","died","dead","expired"])),

    # ════════════════════════════════════════════════════════════════════════════
    # PNC — from Postpartum care stage within Maternal Inpatient program
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("MAT_EPNC.1.2", "PNC within 24hrs (1 day)",       "PNC",
              compute=lambda df: int((_pnc_days(df) <= 1).sum())),
    Indicator("MAT_EPNC.1.3", "PNC 25-48hrs (1-2 days)",        "PNC",
              compute=lambda df: int(((_pnc_days(df) > 1)  & (_pnc_days(df) <= 2)).sum())),
    Indicator("MAT_EPNC.1.4", "PNC 49-72hrs (2-3 days)",        "PNC",
              compute=lambda df: int(((_pnc_days(df) > 2)  & (_pnc_days(df) <= 3)).sum())),
    Indicator("MAT_EPNC.1.5", "PNC 73hrs-7days (4-7 days)",     "PNC",
              compute=lambda df: int(((_pnc_days(df) > 3)  & (_pnc_days(df) <= 7)).sum())),

    # ════════════════════════════════════════════════════════════════════════════
    # CESAREAN SECTION
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("MAT_CS.1.", "Women giving birth by caesarean section", "CS",
              compute=lambda df: _str_match(df, _DEL_MODE,
                                             ["cesare","c/s","c-section","lscs","cs"])),

    # ════════════════════════════════════════════════════════════════════════════
    # ABORTION — requires Abortion/Comprehensive Abortion Care program
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("MAT_CAC_SAC.1", "Safe abortions 10-14 yrs", "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_SAC.2", "Safe abortions 15-19 yrs", "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_SAC.3", "Safe abortions 20-24 yrs", "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_SAC.4", "Safe abortions 25-29 yrs", "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_SAC.5", "Safe abortions ≥30 yrs",   "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_PAC.1", "Post-abortion care 10-14 yrs", "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_PAC.2", "Post-abortion care 15-19 yrs", "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_PAC.3", "Post-abortion care 20-24 yrs", "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_PAC.4", "Post-abortion care 25-29 yrs", "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC_PAC.5", "Post-abortion care ≥30 yrs",   "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC.Tr.1.1", "Abortion care - 1st trimester (<12 wks)",    "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC.Tr.1.2", "Abortion care - 2nd trimester (12-28 wks)",  "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC.MA.1.1", "Post-abortion FP - Oral Contraceptives",     "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC.MA.1.2", "Post-abortion FP - Injectables",             "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC.MA.1.3", "Post-abortion FP - Implants",                "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC.MA.1.4", "Post-abortion FP - IUCD",                    "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC.MA.1.6", "Post-abortion FP - Tubal ligation",          "ABORTION", source="ABORTION"),
    Indicator("MAT_CAC.MA.1.7", "Post-abortion FP - Others",                  "ABORTION", source="ABORTION"),

    # ════════════════════════════════════════════════════════════════════════════
    # OBSTETRIC FISTULA
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("MAT_OFC_Ide__Age.1", "Fistula identified 10-14 yrs", "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Ide__Age.2", "Fistula identified 15-19 yrs", "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Ide__Age.3", "Fistula identified 20-24 yrs", "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Ide__Age.4", "Fistula identified 25-29 yrs", "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Ide__Age.5", "Fistula identified ≥30 yrs",   "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Treat__Age.1","Fistula treated 10-14 yrs",   "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Treat__Age.2","Fistula treated 15-19 yrs",   "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Treat__Age.3","Fistula treated 20-24 yrs",   "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Treat__Age.4","Fistula treated 25-29 yrs",   "FISTULA", source="FISTULA"),
    Indicator("MAT_OFC_Treat__Age.5","Fistula treated ≥30 yrs",     "FISTULA", source="FISTULA"),

    # ════════════════════════════════════════════════════════════════════════════
    # INSTITUTIONAL MATERNAL DEATHS
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("MAT_IMD.1.", "Maternal deaths in health facility", "MAT_DEATHS",
              compute=lambda df: _str_match(df, _DISC_COND, ["death","died","dead","expired","maternal death"])),

    # ════════════════════════════════════════════════════════════════════════════
    # TEENAGE PREGNANCY
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("MAT_TngP_TPR.1", "Teenage girls tested positive for pregnancy 10-14 yrs", "TEEN",
              compute=lambda df: int(_age_mask(df, 10, 14).sum())),
    Indicator("MAT_TngP_TPR.2", "Teenage girls tested positive for pregnancy 15-19 yrs", "TEEN",
              compute=lambda df: int(_age_mask(df, 15, 19).sum())),
    Indicator("MAT_Tngtst.",    "Total women tested positive for pregnancy",              "TEEN",
              compute=lambda df: len(df)),
]


# ── DHIS2 Client ─────────────────────────────────────────────────────────────

def _normalise_url(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    return url


class DHIS2Client:
    def __init__(self, url: str, username: str, password: str,
                 verify_ssl: bool = True, timeout: int = 60):
        self.base    = _normalise_url(url)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth   = (username, password)
        self.session.verify = verify_ssl
        self.session.headers.update({"Accept": "application/json",
                                     "Content-Type": "application/json"})
        retry = Retry(total=3, backoff_factor=1.0,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET", "POST"])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://",  adapter)
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(self, endpoint: str, params: dict = None) -> dict:
        url  = f"{self.base}/api/{endpoint}"
        resp = self.session.get(url, params=params or {}, timeout=self.timeout)
        if resp.status_code == 401:
            raise PermissionError("Authentication failed.")
        if resp.status_code == 403:
            raise PermissionError(f"Access denied: {endpoint}")
        resp.raise_for_status()
        return resp.json()

    def post(self, endpoint: str, payload: dict, params: dict = None) -> dict:
        url  = f"{self.base}/api/{endpoint}"
        resp = self.session.post(url, json=payload, params=params or {},
                                 timeout=self.timeout)
        if resp.status_code == 401:
            raise PermissionError("Authentication failed.")
        resp.raise_for_status()
        return resp.json()

    def paginate(self, endpoint: str, params: dict, data_key: str,
                 page_size: int = 250) -> list:
        params = {**params, "pageSize": page_size, "page": 1, "totalPages": "true"}
        items: list = []
        while True:
            data   = self.get(endpoint, params)
            chunk  = data.get(data_key, [])
            items.extend(chunk)
            pager = data.get("pager", {})
            page_count = pager.get("pageCount")
            cur_page = pager.get("page", params["page"])
            print(f"\r  Page {cur_page:>3}  |  this page: {len(chunk):>4}"
                  f"  |  total: {len(items):>6}", end="", flush=True)
            if page_count is not None:
                if cur_page >= page_count or not chunk:
                    print()
                    break
            else:
                if len(chunk) < page_size or not chunk:
                    print()
                    break
            params["page"] += 1
            time.sleep(0.05)
        return items


# ── Credentials helper ────────────────────────────────────────────────────────

def resolve_credentials(args) -> tuple[str, str, str]:
    url  = getattr(args, "url",      None) or os.getenv("DHIS2_URL")
    user = getattr(args, "username", None) or os.getenv("DHIS2_USER")
    pw   = getattr(args, "password", None) or os.getenv("DHIS2_PASS")

    if CRED_FILE.exists():
        saved = json.loads(CRED_FILE.read_text())
        url  = url  or saved.get("url")
        user = user or saved.get("username")
        pw   = pw   or saved.get("password")

    if not url:
        url  = input("DHIS2 URL   : ").strip()
    if not user:
        user = input("Username    : ").strip()
    if not pw:
        pw   = getpass.getpass("Password    : ")
    return url, user, pw


# ── Tracker data fetch ────────────────────────────────────────────────────────

def fetch_tracker_df(client: DHIS2Client, program_uid: str, ou_uid: str,
                     ou_mode: str, start: str, end: str,
                     page_size: int = 250) -> pd.DataFrame:
    """Pull TEIs from DHIS2 tracker and return a flat DataFrame."""
    params = {
        "program": program_uid,
        "ouMode":  ou_mode,
        "fields": (
            "trackedEntity,orgUnit,attributes,"
            "enrollments[enrollment,enrolledAt,incidentAt,status,"
            "  events[event,programStage,occurredAt,status,"
            "    dataValues[dataElement,value]]]"
        ),
        "totalPages": "true",
    }
    if ou_uid:  params["orgUnit"] = ou_uid

    if start:
        try:
            from datetime import datetime, timedelta
            s_buf = (datetime.fromisoformat(str(start)[:10]) - timedelta(days=30)).strftime("%Y-%m-%d")
            params["enrollmentEnrolledAfter"] = s_buf
        except Exception:
            params["enrollmentEnrolledAfter"] = start
    if end:
        try:
            from datetime import datetime, timedelta
            e_buf = (datetime.fromisoformat(str(end)[:10]) + timedelta(days=7)).strftime("%Y-%m-%d")
            params["enrollmentEnrolledBefore"] = e_buf
        except Exception:
            params["enrollmentEnrolledBefore"] = end

    print(f"Fetching tracker data  (program={program_uid}, ouMode={ou_mode}) ...")
    probe    = client.get("tracker/trackedEntities", {**params, "pageSize": 1, "page": 1})
    data_key = "instances" if "instances" in probe else "trackedEntities"
    teis     = client.paginate("tracker/trackedEntities", params, data_key, page_size)
    print(f"  {len(teis):,} TEIs fetched")

    # Fetch metadata to build UID → column-name maps
    print("Fetching program metadata ...")
    prog  = client.get(f"programs/{program_uid}", params={
        "fields": (
            "name,programTrackedEntityAttributes[trackedEntityAttribute[id,name,formName]],"
            "programStages[id,name,"
            "  programStageDataElements[dataElement[id,name,"
            "    optionSet[id,name,options[code,name]]]]]"
        )
    })
    attr_map: dict[str, str] = {}
    for ptea in prog.get("programTrackedEntityAttributes", []):
        a = ptea.get("trackedEntityAttribute", {})
        name = (a.get("name") or "").strip()
        if not name:
            name = (a.get("formName") or "").strip()
        if a.get("id") and name:
            attr_map[a["id"]] = name

    de_map: dict[tuple, str] = {}
    de_opts: dict[tuple, dict] = {}   # (stage_uid, de_uid) -> {code: label}
    stage_map: dict[str, str] = {}
    for stage in prog.get("programStages", []):
        s_uid  = stage["id"]
        s_name = stage.get("name", "").strip()
        stage_map[s_uid] = s_name
        for psde in stage.get("programStageDataElements", []):
            de = psde.get("dataElement", {})
            if de.get("id") and de.get("name"):
                col_name = f"{s_name}_{de['name'].strip()}"
                de_map[(s_uid, de["id"])] = col_name
                opts = {}
                opt_set = (de.get("optionSet") or {}).get("options") or []
                for o in opt_set:
                    code = str(o.get("code", ""))
                    name = (o.get("name") or o.get("code") or "").strip()
                    if code:
                        opts[code] = name
                if opts:
                    de_opts[(s_uid, de["id"])] = opts

    # Flatten TEIs → rows
    rows = []
    for tei in teis:
        for enr in tei.get("enrollments", []):
            row: dict = {
                "tei_uid":         tei.get("trackedEntity", ""),
                "org_unit":        tei.get("orgUnit", ""),
                "enrollment_date": (enr.get("enrolledAt") or "")[:10],
                "incident_date":   (enr.get("incidentAt") or "")[:10],
            }
            for attr in tei.get("attributes", []):
                a_uid = attr.get("attribute", "")
                a_val = str(attr.get("value", "")).strip()
                if a_uid:
                    row[a_uid] = a_val
                col = attr_map.get(a_uid)
                if col:
                    row[col] = a_val
                if col and col.lower() == "age":
                    row["Age"] = a_val

            # Most-recent event per stage
            best: dict[str, dict] = {}
            for evt in enr.get("events", []):
                s = evt.get("programStage", "")
                if s not in best or evt.get("occurredAt","") > best[s].get("occurredAt",""):
                    best[s] = evt

            for s_uid, evt in best.items():
                s_name = stage_map.get(s_uid, "")
                if s_name:
                    occ = evt.get("occurredAt", "")
                    row[f"{s_name}_event_id"]     = evt.get("event", "")
                    row[f"{s_name}_event_date"]   = occ[:10] if occ else ""
                    row[f"{s_name}_event_status"] = evt.get("status", "")

            # Process all events in enrollment to ensure no clinical data, lab tests, or PNC visits are missed
            for evt in enr.get("events", []):
                s_uid  = evt.get("programStage", "")
                s_name = stage_map.get(s_uid, "")
                for dv in evt.get("dataValues", []):
                    de_id = dv.get("dataElement", "")
                    if not de_id:
                        continue
                    val = str(dv.get("value", "")).strip()
                    opts = de_opts.get((s_uid, de_id))
                    label = val
                    if opts:
                        labels = []
                        for part in val.split(","):
                            part = part.strip()
                            if part in opts:
                                labels.append(opts[part])
                            elif part:
                                labels.append(part)
                        label = ", ".join(labels)

                    # Store primary values by UID, (stage_uid, de_uid), and column name
                    row[de_id] = val
                    row[f"{de_id}_raw"] = val
                    row[f"{de_id}_label"] = label
                    row[f"{s_uid}_{de_id}"] = val
                    col = de_map.get((s_uid, de_id))
                    if col:
                        row[col] = label

                    # Collect all values across all events for this TEI enrollment
                    all_key = f"{de_id}_all"
                    if all_key not in row:
                        row[all_key] = set()
                    row[all_key].add(val.lower())
                    for p in val.split(","):
                        row[all_key].add(p.strip().lower())

                    all_lbl_key = f"{de_id}_all_labels"
                    if all_lbl_key not in row:
                        row[all_lbl_key] = set()
                    row[all_lbl_key].add(label.lower())
                    for p in label.split(","):
                        row[all_lbl_key].add(p.strip().lower())

            rows.append(row)

    df = pd.DataFrame(rows)

    # Coerce types
    if "Age" in df.columns:
        df["Age"] = pd.to_numeric(df["Age"], errors="coerce")

    # Filter to the reporting window by the ACTUAL delivery date or enrollment date
    if (start or end) and not df.empty:
        d_del = _delivery_dates(df)
        d_enr = pd.to_datetime(df.get("enrollment_date"), errors="coerce")
        d_inc = pd.to_datetime(df.get("incident_date"), errors="coerce")
        d = d_del.fillna(d_enr).fillna(d_inc)

        mask_d = pd.Series(True, index=df.index)
        mask_enr = pd.Series(True, index=df.index)
        has_enr = d_enr.notna()

        if start:
            s_dt = pd.to_datetime(start)
            mask_d &= (d >= s_dt)
            mask_enr &= (d_enr >= s_dt)
        if end:
            e_dt = pd.to_datetime(end)
            mask_d &= (d <= e_dt)
            mask_enr &= (d_enr <= e_dt)

        mask = mask_d | (has_enr & mask_enr)
        n_all = len(df)
        df = df[mask].reset_index(drop=True)
        print(f"  {len(df):,} deliveries within {start or '…'} → {end or '…'} "
              f"(of {n_all:,} TEIs fetched)")

    print(f"  DataFrame: {df.shape[0]:,} rows × {df.shape[1]} columns")
    return df


def diagnose_values(df: pd.DataFrame):
    """Print unique values for every column the indicators rely on."""
    key_cols = [
        _DEL_MODE, _OUTCOME, _OBS_COND, _UTEROTONICS,
        _STILLBIRTH, _DISC_COND, _DEL_DATE, _PNC_DATE,
        _PPFP,
        "Laboratory_VDRL", "Laboratory_HBsAg",
        _AGE,
    ]
    print("\n── Value diagnostics ────────────────────────────────────────────────")
    for col in key_cols:
        if col not in df.columns:
            print(f"  {col!r:<60}  COLUMN MISSING")
            continue
        vals = df[col].dropna()
        vals = vals[vals.astype(str).str.strip() != ""]
        unique = vals.value_counts().head(10)
        if unique.empty:
            print(f"  {col!r:<60}  (all empty)")
        else:
            print(f"\n  {col!r}  ({len(vals)} non-empty values)")
            for v, cnt in unique.items():
                print(f"      {cnt:>4}×  {str(v)!r}")


# ── DHIS2 aggregate API helpers ───────────────────────────────────────────────

def fetch_default_coc(client: DHIS2Client) -> str:
    """Return the UID of the 'default' category option combo."""
    data = client.get("categoryOptionCombos",
                      {"filter": "name:eq:default", "fields": "id", "paging": "false"})
    cocs = data.get("categoryOptionCombos", [])
    if cocs:
        return cocs[0]["id"]
    raise RuntimeError("Could not find default categoryOptionCombo on this server.")


def lookup_de_uids(client: DHIS2Client, codes: list[str]) -> dict[str, str]:
    """Return {code: uid} for all data elements found by code."""
    if not codes:
        return {}
    # DHIS2 filter:in has a URL-length limit; chunk to 50
    result: dict[str, str] = {}
    for i in range(0, len(codes), 50):
        chunk = codes[i: i + 50]
        clist = ",".join(chunk)
        data  = client.get("dataElements",
                           {"filter": f"code:in:[{clist}]",
                            "fields": "id,code",
                            "paging": "false"})
        for de in data.get("dataElements", []):
            result[de["code"]] = de["id"]
    return result


def build_datavalue_set(values: dict[str, int], de_uid_map: dict[str, str],
                        default_coc: str, dataset_uid: str,
                        period: str, ou_uid: str) -> dict:
    """Assemble compact dataValueSet payload (period/orgUnit at top level)."""
    dv_list = []
    for code, value in values.items():
        uid = de_uid_map.get(code)
        if uid is None:
            continue
        dv_list.append({
            "dataElement":         uid,
            "categoryOptionCombo": default_coc,
            "value":               str(value),
        })
    return {
        "dataSet":    dataset_uid,
        "period":     period,
        "orgUnit":    ou_uid,
        "dataValues": dv_list,
    }


def save_flat_import_json(values: dict[str, int | None],
                          de_uid_map: dict[str, str],
                          default_coc: str,
                          period: str,
                          ou_uid: str,
                          output_path: str):
    """
    Write a flat DHIS2 dataValueSet JSON for manual import via Import/Export app.

    ALL indicators are included regardless of whether a value was computed:
      - Computed value  → that value
      - None (requires another program) → "0" as default; user fills manually

    Data element UIDs:
      - Found in DHIS2  → real 11-char UID
      - Not found       → indicator code used as placeholder; user must replace

    The file also writes a companion _index.json listing every indicator with
    its section, source, and whether it needs manual entry — useful for finding
    which placeholders to resolve.
    """
    dv_list   = []
    index     = []
    resolved  = 0
    for ind in INDICATORS:
        value = values.get(ind.code)
        uid   = de_uid_map.get(ind.code)      # None if not found in DHIS2
        needs_uid   = uid is None
        needs_value = value is None            # requires another program
        if uid is None:
            uid = f"[{ind.code}]"             # visible placeholder

        dv_list.append({
            "dataElement":         uid,
            "categoryOptionCombo": default_coc,
            "period":              period,
            "orgUnit":             ou_uid,
            "value":               str(value if value is not None else 0),
        })
        index.append({
            "code":         ind.code,
            "dataElement":  uid,
            "label":        ind.label,
            "section":      _SECTION_LABELS.get(ind.section, ind.section),
            "source":       ind.source,
            "computedValue": value,
            "needsManualUID":   needs_uid,
            "needsManualValue": needs_value,
        })
        if not needs_uid:
            resolved += 1

    # Main import JSON — all entries, clean DHIS2 format
    Path(output_path).write_text(
        json.dumps({"dataValues": dv_list}, indent=4, ensure_ascii=False)
    )
    print(f"Import JSON saved  → {output_path}  "
          f"({len(dv_list)} entries, {resolved} UIDs resolved)")

    # Index file — human-readable companion
    index_path = output_path.replace(".json", "_index.json")
    Path(index_path).write_text(
        json.dumps(index, indent=4, ensure_ascii=False)
    )
    uid_warn    = len(dv_list) - resolved
    value_warn  = sum(1 for i in index if i["needsManualValue"])
    print(f"Index saved        → {index_path}")
    if uid_warn:
        print(f"  ⚠  {uid_warn} entries need real UIDs  "
              f"(search for '[' in the import file)")
    if value_warn:
        print(f"  ⚠  {value_warn} entries need manual values  "
              f"(set to 0 now — check needsManualValue=true in index)")


def submit_datavalue_set(client: DHIS2Client, payload: dict,
                         dry_run: bool = False) -> dict:
    """POST the dataValueSet to DHIS2 (or print it if dry_run)."""
    if dry_run:
        print("\n── Dry-run payload (would POST to /api/dataValueSets) ──────────")
        print(json.dumps(payload, indent=2))
        return {"status": "DRY_RUN", "imported": len(payload["dataValues"])}
    resp = client.post("dataValueSets", payload,
                       params={"importStrategy": "CREATE_AND_UPDATE"})
    return resp


# ── Excel preview ─────────────────────────────────────────────────────────────

_SECTION_LABELS = {
    "FP":        "Family Planning",
    "ANC":       "Antenatal Care",
    "DEL":       "Delivery",
    "PNC":       "Postnatal Care",
    "CS":        "Cesarean Section",
    "ABORTION":  "Abortion Care",
    "FISTULA":   "Obstetric Fistula",
    "MAT_DEATHS":"Institutional Maternal Deaths",
    "TEEN":      "Teenage Pregnancy",
}

_SECTION_COLOR = {
    "FP":        "B8E4B8",
    "ANC":       "B8D4E4",
    "DEL":       "E4D4B8",
    "PNC":       "D4B8E4",
    "CS":        "E4B8B8",
    "ABORTION":  "E4E4B8",
    "FISTULA":   "B8E4E4",
    "MAT_DEATHS":"F4C2C2",
    "TEEN":      "C2D4F4",
}


_RMH_TEMPLATE_FILENAME = "01.2 - Reproductive and Maternal Health _ Hospital, Health center, Clinic _ Monthly.xls.xlsx"


def resolve_rmh_template_path() -> Optional[Path]:
    """Find the official 01.2 RMH Report template."""
    import sys
    candidates = [
        Path(__file__).parent / "templates" / _RMH_TEMPLATE_FILENAME,
        Path.cwd() / "backend" / "modules" / "hmis" / "templates" / _RMH_TEMPLATE_FILENAME,
    ]
    if getattr(sys, "frozen", False):
        base_dir = Path(getattr(sys, "_MEIPASS", ""))
        candidates.append(base_dir / "backend" / "modules" / "hmis" / "templates" / _RMH_TEMPLATE_FILENAME)
    candidates.append(Path("/home/kbrom/Work/IMNID/IMNID Developments/Report template") / _RMH_TEMPLATE_FILENAME)
    for c in candidates:
        if c.is_file():
            return c
    return None


def write_preview_excel(values: dict[str, Any],
                        period: str, ou_name: str,
                        output_path: str):
    if not HAS_OPENPYXL:
        print("ERROR: openpyxl not installed — cannot write Excel.  pip install openpyxl")
        return

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    json_file = out_file.with_suffix(".json")

    tmpl_path = resolve_rmh_template_path()
    if tmpl_path and tmpl_path.is_file():
        wb = openpyxl.load_workbook(tmpl_path)
        ws = wb.active

        # Update Title in Row 1
        orig_title = str(ws.cell(1, 1).value or "").strip()
        fac_label = ou_name or "All facilities"
        ws.cell(1, 1).value = f"{orig_title}  |  Facility: {fac_label}  |  Period: {period}"
        # Update Period Header in Row 2 Col 3
        ws.cell(2, 3).value = str(period)

        # Load rep metadata rows
        rep_candidates = [
            Path("/home/kbrom/Work/IMNID/IMNID Developments/HMIS Report/rep") / _REP_JSON_RMH,
            Path("/home/kbrom/Work/IMNID/IMNID Developments/rep") / _REP_JSON_RMH,
            Path(__file__).parent / "rep" / _REP_JSON_RMH,
        ]
        rep_rows = []
        for c in rep_candidates:
            if c.is_file():
                try:
                    with open(c, encoding="utf-8") as f:
                        rep_rows = json.load(f).get("rows", [])
                    break
                except Exception:
                    pass

        norm = lambda s: str(s).replace(" ", "").rstrip(".") if s else ""
        norm_vals = {norm(k): v for k, v in values.items()}

        align_center = Alignment(horizontal="center", vertical="center")
        font_num = Font(name="Aptos Narrow", size=11, bold=True)
        font_na = Font(name="Aptos Narrow", size=10, italic=True, color="666666")

        rows_summary = []
        if rep_rows:
            for idx, rep_r in enumerate(rep_rows):
                r_idx = idx + 3
                if r_idx > ws.max_row:
                    break
                st = rep_r.get("status")
                sno = rep_r.get("sno")
                act = rep_r.get("label") or ws.cell(r_idx, 2).value
                cell = ws.cell(r_idx, 3)
                cell.alignment = align_center

                if st == "HEADER":
                    cell.value = None
                    final_v = None
                elif st == "NOT CAPTURED":
                    cell.value = "Not available"
                    cell.font = font_na
                    final_v = "Not available"
                else:
                    v = values.get(f"row_{r_idx}")
                    if v is None and sno:
                        v = values.get(sno)
                    if v is None and sno:
                        v = norm_vals.get(norm(sno))
                    if v is None:
                        v = 0
                    cell.value = v
                    if isinstance(v, (int, float)):
                        cell.font = font_num
                    elif v == "Not available":
                        cell.font = font_na
                    else:
                        cell.font = font_num
                    final_v = v

                rows_summary.append({
                    "sno": sno,
                    "activity": act,
                    "value": final_v,
                    "status": st,
                })
        else:
            for r_idx in range(3, ws.max_row + 1):
                sno = ws.cell(r_idx, 1).value
                cell = ws.cell(r_idx, 3)
                cell.alignment = align_center
                if sno and norm(sno) in norm_vals:
                    v = norm_vals[norm(sno)]
                    cell.value = v
                    if v == "Not available":
                        cell.font = font_na
                    elif isinstance(v, (int, float)):
                        cell.font = font_num
                rows_summary.append({
                    "sno": sno,
                    "activity": ws.cell(r_idx, 2).value,
                    "value": cell.value,
                })

        wb.save(out_file)

        json_payload = {
            "report": "01.2 - Reproductive and Maternal Health Monthly Report",
            "facility": fac_label,
            "period": period,
            "indicators": values,
            "rows": rows_summary,
        }
        json_file.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Filled template saved → {out_file} and {json_file}")
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "01.2 RMH Monthly Report"

    thin = Side(style="thin", color="AAAAAA")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def cell(r, c, value, bold=False, bg=None, wrap=False, align="left"):
        cell_obj = ws.cell(row=r, column=c, value=value)
        cell_obj.font      = Font(bold=bold, size=10)
        cell_obj.alignment = Alignment(horizontal=align, vertical="center",
                                       wrap_text=wrap)
        cell_obj.border    = border
        if bg:
            cell_obj.fill = PatternFill("solid", fgColor=bg)
        return cell_obj

    # Title
    ws.merge_cells("A1:D1")
    cell(1, 1,
         "01.2 - Reproductive and Maternal Health | Monthly Report",
         bold=True, bg="1E4D8C")
    ws.cell(row=1, column=1).font = Font(bold=True, size=12, color="FFFFFF")
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center",
                                                    vertical="center")
    ws.row_dimensions[1].height = 24

    ws.merge_cells("A2:D2")
    cell(2, 1, f"Period: {period}   |   Org unit: {ou_name}", bold=False, bg="D0E4FF")

    # Header row
    for c, hdr in enumerate(["S.No", "Activity", "Value", "Source"], start=1):
        cell(3, c, hdr, bold=True, bg="3A7EBF")
        ws.cell(row=3, column=c).font = Font(bold=True, color="FFFFFF", size=10)

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 55
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 14

    row = 4
    current_section = None
    for ind in INDICATORS:
        if ind.section != current_section:
            current_section = ind.section
            label  = _SECTION_LABELS.get(ind.section, ind.section)
            bg_hdr = _SECTION_COLOR.get(ind.section, "DDDDDD")
            ws.merge_cells(f"A{row}:D{row}")
            cell(row, 1, label, bold=True, bg=bg_hdr)
            ws.row_dimensions[row].height = 16
            row += 1

        bg  = _SECTION_COLOR.get(ind.section, "FFFFFF") + "44"   # lighter tint
        val = values.get(ind.code)
        if val == "Not available":
            val_str = "Not available"
            val_bg = "F4F4F4"
            src = "Not in tracker"
        elif val is not None:
            val_str = str(val)
            val_bg = "C8F4C8"
            src = "DEL tracker" if ind.source == "DEL" else ind.source
        else:
            val_str = "—"
            val_bg = "FFFFFF"
            src = "HEADER"

        cell(row, 1, ind.code,  bg=None)
        cell(row, 2, ind.label, bg=None, wrap=True)
        c_val = cell(row, 3, val_str, bg=val_bg, align="center")
        if val == "Not available":
            c_val.font = Font(italic=True, size=9, color="777777")
        elif val is not None:
            c_val.font = Font(bold=True, size=10)
        cell(row, 4, src, bg=None, align="center")
        ws.row_dimensions[row].height = 15
        row += 1

    # Freeze panes below header
    ws.freeze_panes = "A4"
    wb.save(output_path)
    json_payload = {
        "report": "01.2 - Reproductive and Maternal Health Monthly Report",
        "facility": ou_name,
        "period": period,
        "indicators": values,
    }
    json_file.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Preview saved → {output_path} and {json_file}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="aggregate_report.py",
        description="Generate & submit the 01.2 RMH aggregate monthly report from DHIS2 tracker data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = ap.add_argument_group("Connection")
    grp.add_argument("--url",      help="DHIS2 base URL")
    grp.add_argument("--username", help="DHIS2 username")
    grp.add_argument("--password", help="DHIS2 password")
    grp.add_argument("--no-ssl-verify", action="store_true",
                     help="Disable SSL certificate verification")

    grp = ap.add_argument_group("Tracker source")
    grp.add_argument("--delivery-program", metavar="UID", required=True,
                     help="Tracker program UID for delivery/inpatient data")
    grp.add_argument("--org-unit",  metavar="UID",
                     help="Organisation unit UID for the report")
    grp.add_argument("--ou-mode",   default="SELECTED",
                     choices=["SELECTED","DESCENDANTS","CHILDREN","ALL"],
                     help="Org unit hierarchy mode (default: SELECTED)")
    grp.add_argument("--period",    metavar="YYYYMM",
                     help="Gregorian reporting period, e.g. 202410 for Oct 2024. "
                          "Used for the aggregate submission. Required unless "
                          "--start is given.")
    grp.add_argument("--start",     metavar="YYYY-MM-DD",
                     help="Explicit reporting start date (overrides the "
                          "month derived from --period). Use for Ethiopian / "
                          "non-calendar-month reporting windows.")
    grp.add_argument("--end",       metavar="YYYY-MM-DD",
                     help="Explicit reporting end date (inclusive). "
                          "Default: last day of the --period month.")

    grp = ap.add_argument_group("Output")
    grp.add_argument("--preview", metavar="FILE.xlsx",
                     help="Save Excel preview of computed values")
    grp.add_argument("--json-out", metavar="FILE.json",
                     help="Save raw computed values as JSON (summary format)")
    grp.add_argument("--export-json", metavar="FILE.json",
                     help="Save flat DHIS2 import JSON (period+orgUnit per entry) "
                          "for manual upload via Import/Export app")

    grp = ap.add_argument_group("DHIS2 aggregate submission")
    grp.add_argument("--dataset", metavar="UID",
                     help="Aggregate dataset UID (01.2 RMH dataset in DHIS2)")
    grp.add_argument("--dry-run", action="store_true",
                     help="Print payload without submitting")
    grp.add_argument("--submit",  action="store_true",
                     help="POST values to DHIS2 aggregate (requires --dataset)")
    grp.add_argument("--diagnose-values", action="store_true",
                     help="Print unique values for every key column and exit")
    return ap


def main():
    args   = build_arg_parser().parse_args()
    url, user, pw = resolve_credentials(args)
    verify = not getattr(args, "no_ssl_verify", False)
    client = DHIS2Client(url, user, pw, verify_ssl=verify)

    # Verify connection
    try:
        info = client.get("system/info")
        print(f"Connected  : {info.get('systemName','DHIS2')} v{info.get('version','?')}")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Resolve reporting window → start/end dates.
    # Priority: --start/--end (explicit) > --period month (Gregorian calendar).
    from datetime import datetime
    start = getattr(args, "start", None)
    end   = getattr(args, "end", None)
    period = getattr(args, "period", None)

    if start:
        try:
            datetime.strptime(start, "%Y-%m-%d")
        except Exception:
            print(f"ERROR: --start must be YYYY-MM-DD, got '{start}'")
            sys.exit(1)
    if end:
        try:
            datetime.strptime(end, "%Y-%m-%d")
        except Exception:
            print(f"ERROR: --end must be YYYY-MM-DD, got '{end}'")
            sys.exit(1)

    if start is None and end is None and not period:
        print("ERROR: provide --period YYYYMM, or --start/--end dates.")
        sys.exit(1)

    if period:
        try:
            year, month = int(period[:4]), int(period[4:6])
        except Exception:
            print(f"ERROR: --period must be YYYYMM (e.g. 202410), got '{period}'")
            sys.exit(1)
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        if not start:
            start = f"{year}-{month:02d}-01"
        if not end:
            end = f"{year}-{month:02d}-{last_day:02d}"
    else:
        # start given (with optional end); no --period supplied
        year, month = int(start[:4]), int(start[5:7])
        period = f"{year:04d}{month:02d}"
        if not end:
            import calendar
            end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"

    # Validate ordering
    try:
        if datetime.strptime(end, "%Y-%m-%d") < datetime.strptime(start, "%Y-%m-%d"):
            print(f"ERROR: --end ({end}) is before --start ({start}).")
            sys.exit(1)
    except Exception:
        pass

    print(f"Reporting window : {start} → {end}  (period tag: {period})")

    ou_uid  = args.org_unit or ""
    ou_name = ou_uid

    # Look up org unit name for display
    if ou_uid:
        try:
            ou_info = client.get(f"organisationUnits/{ou_uid}", {"fields": "id,name"})
            ou_name = ou_info.get("name", ou_uid)
        except Exception:
            pass

    # Fetch tracker data
    df = fetch_tracker_df(client,
                          program_uid=args.delivery_program,
                          ou_uid=ou_uid,
                          ou_mode=args.ou_mode,
                          start=start,
                          end=end,
                          page_size=250)

    if df.empty:
        print("No tracker records returned for this period/org unit.")
        sys.exit(1)

    if getattr(args, "diagnose_values", False):
        diagnose_values(df)
        sys.exit(0)

    # Compute all indicators
    print(f"\nComputing {len(INDICATORS)} indicators ...")
    values: dict[str, int | None] = {}
    for ind in INDICATORS:
        values[ind.code] = ind.compute(df)

    # Summary printout
    computed = {k: v for k, v in values.items() if v is not None}
    print(f"  Computed : {len(computed):,}  (others require additional programs)")
    print("\n── Delivery / PNC / CS indicators ──────────────────────────────────")
    for ind in INDICATORS:
        v = values[ind.code]
        if ind.source == "DEL" and v is not None:
            print(f"  {ind.code:<28}  {v:>6}   {ind.label}")

    # Excel preview
    if args.preview:
        write_preview_excel(values, args.period, ou_name, args.preview)

    # JSON summary output
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"period": period, "orgUnit": ou_uid,
                        "generatedAt": pd.Timestamp.now().isoformat(),
                        "values": {k: v for k, v in values.items() if v is not None}},
                       indent=4, ensure_ascii=False))
        print(f"JSON summary saved → {args.json_out}")

    # Flat import JSON — always look up UIDs from DHIS2 for this
    if args.export_json:
        print("\nLooking up data element UIDs for import JSON ...")
        all_codes  = [ind.code for ind in INDICATORS]
        de_map_all = lookup_de_uids(client, all_codes)
        matched    = len(de_map_all)
        print(f"  Matched {matched:,} of {len(all_codes):,} indicator codes to DHIS2 UIDs")
        if matched == 0:
            print("  WARNING: No UIDs found — indicator codes may not exist in this "
                  "DHIS2 instance. The export will use codes as placeholders.")

        try:
            default_coc_uid = fetch_default_coc(client)
        except Exception:
            default_coc_uid = "default"
            print("  WARNING: Could not fetch default COC UID — using placeholder 'default'")

        save_flat_import_json(
            values, de_map_all, default_coc_uid,
            period, ou_uid, args.export_json
        )

    # Aggregate API submission
    if args.dry_run or args.submit:
        if not args.dataset:
            print("ERROR: --dataset <UID> is required for --dry-run / --submit")
            sys.exit(1)

        print("\nLooking up data element UIDs for submission ...")
        codes  = [ind.code for ind in INDICATORS if values.get(ind.code) is not None]
        de_map = lookup_de_uids(client, codes)
        print(f"  Matched {len(de_map):,} of {len(codes):,} codes to DHIS2 data elements")

        default_coc = fetch_default_coc(client)
        payload     = build_datavalue_set(
            {k: v for k, v in values.items() if v is not None},
            de_map, default_coc, args.dataset, period, ou_uid
        )
        print(f"  Data values to submit: {len(payload['dataValues'])}")

        result = submit_datavalue_set(client, payload, dry_run=not args.submit)
        if args.submit:
            status = result.get("status", "?")
            imp    = result.get("importCount", {})
            print(f"\nSubmission result: {status}")
            print(f"  imported={imp.get('imported',0)}  "
                  f"updated={imp.get('updated',0)}  "
                  f"ignored={imp.get('ignored',0)}")

    print("\nDone.")


_REP_JSON_RMH = "01_2_-_Reproductive_and_Maternal_Health_Hospital_Health_center_Clinic_Monthly_DHIS2_mapped.json"


def _load_rmh_rep_rows() -> list[dict]:
    """Load indicator specification rows from rep mapped JSON."""
    candidates = [
        Path("/home/kbrom/Work/IMNID/IMNID Developments/HMIS Report/rep") / _REP_JSON_RMH,
        Path("/home/kbrom/Work/IMNID/IMNID Developments/rep") / _REP_JSON_RMH,
        Path(__file__).parent / "rep" / _REP_JSON_RMH,
    ]
    for c in candidates:
        if c.is_file():
            try:
                with open(c, encoding="utf-8") as f:
                    return json.load(f).get("rows", [])
            except Exception:
                pass
    return []


def get_rmh_indicator_availability() -> dict[str, str]:
    """Load indicator availability mapping from rep assessment JSON."""
    rows = _load_rmh_rep_rows()
    if not rows:
        return {}
    norm = lambda s: str(s).replace(" ", "").rstrip(".") if s else ""
    by_sno = {norm(r.get("sno")): r.get("status") for r in rows if r.get("sno")}
    by_lbl = {norm(r.get("label")).lower(): r.get("status") for r in rows if r.get("label")}
    avail = {}
    for ind in INDICATORS:
        st = by_sno.get(norm(ind.code)) or by_lbl.get(norm(ind.label).lower())
        avail[ind.code] = st or ("COMPUTED" if ind._fn is not None else "NOT CAPTURED")
    return avail


def compute_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Compute all 01.2 MoH Reproductive and Maternal Health indicators from tracker data
    following the exact specification in 01_2_-_Reproductive_and_Maternal_Health_..._DHIS2_mapped.json."""
    rep_rows = _load_rmh_rep_rows()
    norm = lambda s: str(s).replace(" ", "").rstrip(".") if s else ""

    if df is None or df.empty:
        values: dict[str, Any] = {}
        for idx, r in enumerate(rep_rows):
            st = r.get("status")
            sno = r.get("sno")
            r_idx = idx + 3
            val = None if st == "HEADER" else ("Not available" if st == "NOT CAPTURED" else 0)
            if sno and st != "HEADER":
                values[sno] = val
                values[norm(sno)] = val
            values[f"row_{r_idx}"] = val
        return values

    n_records = len(df)

    # Pre-evaluate Mother Age per row
    ages = []
    for _, row in df.iterrows():
        a = row.get("vbaNV9kiRFp") or row.get("Age") or row.get(_AGE)
        try:
            ages.append(float(a) if a is not None and str(a).strip() != "" else None)
        except Exception:
            ages.append(None)

    # 1. Immediate Postpartum Family Planning (PPFP) within 48h
    # Date/stay pp [z7Eb2yFLOBI] in {1, 2} (24h or 25-48h)
    stay_48h = [
        _has_code_or_label(row, "z7Eb2yFLOBI", {"1", "2"}, {"24 hrs stay", "25- 48 hrs", "24", "48"},
                           col_name="Postpartum care_Date/stay pp")
        for _, row in df.iterrows()
    ]

    fp_pills = [
        _has_code_or_label(row, "Q1p7CxWGUoi", {"1"}, {"pills", "pill", "oral"},
                           col_name="Postpartum care_FP Counseling and Method Provided pp")
        for _, row in df.iterrows()
    ]
    fp_implants = [
        _has_code_or_label(row, "Q1p7CxWGUoi", {"3"}, {"implants", "implant"},
                           col_name="Postpartum care_FP Counseling and Method Provided pp")
        for _, row in df.iterrows()
    ]
    fp_iucd = [
        _has_code_or_label(row, "Q1p7CxWGUoi", {"4"}, {"iucd"},
                           col_name="Postpartum care_FP Counseling and Method Provided pp")
        for _, row in df.iterrows()
    ]
    fp_inj = [
        _has_code_or_label(row, "Q1p7CxWGUoi", {"2"}, {"injectables", "injectable"},
                           col_name="Postpartum care_FP Counseling and Method Provided pp")
        for _, row in df.iterrows()
    ]
    fp_condom = [
        _has_code_or_label(row, "Q1p7CxWGUoi", {"5"}, {"condom", "condoms"},
                           col_name="Postpartum care_FP Counseling and Method Provided pp")
        for _, row in df.iterrows()
    ]
    fp_other = [fp_inj[i] or fp_condom[i] for i in range(n_records)]

    has_ppfp = [stay_48h[i] and (fp_pills[i] or fp_implants[i] or fp_iucd[i] or fp_other[i]) for i in range(n_records)]

    # PPFP by Age
    ppfp_age_10_14 = sum(1 for i in range(n_records) if has_ppfp[i] and ages[i] is not None and 10 <= ages[i] <= 14)
    ppfp_age_15_19 = sum(1 for i in range(n_records) if has_ppfp[i] and ages[i] is not None and 15 <= ages[i] <= 19)
    ppfp_age_20_24 = sum(1 for i in range(n_records) if has_ppfp[i] and ages[i] is not None and 20 <= ages[i] <= 24)
    ppfp_age_25_29 = sum(1 for i in range(n_records) if has_ppfp[i] and ages[i] is not None and 25 <= ages[i] <= 29)
    ppfp_age_30_49 = sum(1 for i in range(n_records) if has_ppfp[i] and ages[i] is not None and 30 <= ages[i] <= 49)
    ppfp_age_total = sum(1 for i in range(n_records) if has_ppfp[i] and (ages[i] is None or (10 <= ages[i] <= 49)))

    # PPFP by Method
    ppfp_mtd_oral = sum(1 for i in range(n_records) if stay_48h[i] and fp_pills[i])
    ppfp_mtd_implants = sum(1 for i in range(n_records) if stay_48h[i] and fp_implants[i])
    ppfp_mtd_iucd = sum(1 for i in range(n_records) if stay_48h[i] and fp_iucd[i])
    ppfp_mtd_other = sum(1 for i in range(n_records) if stay_48h[i] and fp_other[i])
    ppfp_mtd_total = ppfp_mtd_oral + ppfp_mtd_implants + ppfp_mtd_iucd + ppfp_mtd_other

    # 2. Antenatal Care (ANC) First Contact by Maternal Age
    has_anc1 = [
        _has_code_or_label(row, "DwoKlEc3tRR", {"1"}, {"yes", "true"},
                           col_name="Maternal History_ANC Contact")
        for _, row in df.iterrows()
    ]
    anc1_10_14 = sum(1 for i in range(n_records) if has_anc1[i] and ages[i] is not None and 10 <= ages[i] <= 14)
    anc1_15_19 = sum(1 for i in range(n_records) if has_anc1[i] and ages[i] is not None and 15 <= ages[i] <= 19)
    anc1_ge_20 = sum(1 for i in range(n_records) if has_anc1[i] and (ages[i] is None or ages[i] >= 20))
    anc1_total = sum(1 for i in range(n_records) if has_anc1[i])

    # 3. ANC 4+ & 8+ Contacts by Maternal Age
    anc_contacts = []
    for _, row in df.iterrows():
        ac = row.get("XY0SSEpmHo0") or row.get("Maternal History_Number of ANC contacts")
        try:
            anc_contacts.append(float(ac) if ac is not None and str(ac).strip() != "" else 0.0)
        except Exception:
            anc_contacts.append(0.0)

    has_anc4 = [anc_contacts[i] >= 4 for i in range(n_records)]
    has_anc8 = [anc_contacts[i] >= 8 for i in range(n_records)]

    anc4_10_14 = sum(1 for i in range(n_records) if has_anc4[i] and ages[i] is not None and 10 <= ages[i] <= 14)
    anc4_15_19 = sum(1 for i in range(n_records) if has_anc4[i] and ages[i] is not None and 15 <= ages[i] <= 19)
    anc4_ge_20 = sum(1 for i in range(n_records) if has_anc4[i] and (ages[i] is None or ages[i] >= 20))
    anc4_total = sum(1 for i in range(n_records) if has_anc4[i])
    anc8_total = sum(1 for i in range(n_records) if has_anc8[i])

    # 4. Syphilis Testing (VDRL [qX792urzmwj])
    vdrl_pos = [
        _has_code_or_label(row, "qX792urzmwj", {"1"}, {"positive", "reactive"}, col_name="Laboratory_VDRL")
        for _, row in df.iterrows()
    ]
    vdrl_neg = [
        _has_code_or_label(row, "qX792urzmwj", {"2"}, {"negative", "non-reactive"}, col_name="Laboratory_VDRL")
        for _, row in df.iterrows()
    ]
    syp_tested = sum(1 for i in range(n_records) if vdrl_pos[i] or vdrl_neg[i])
    syp_reactive = sum(1 for i in range(n_records) if vdrl_pos[i])
    syp_non_reactive = sum(1 for i in range(n_records) if vdrl_neg[i] and not vdrl_pos[i])

    # 5. Hepatitis B Testing (HBsAg [WKXq0p4Nbfl])
    hbsag_pos = [
        _has_code_or_label(row, "WKXq0p4Nbfl", {"1"}, {"positive", "reactive"}, col_name="Laboratory_HBsAg")
        for _, row in df.iterrows()
    ]
    hbsag_neg = [
        _has_code_or_label(row, "WKXq0p4Nbfl", {"2"}, {"negative", "non-reactive"}, col_name="Laboratory_HBsAg")
        for _, row in df.iterrows()
    ]
    hepa_tested = sum(1 for i in range(n_records) if hbsag_pos[i] or hbsag_neg[i])
    hepa_reactive = sum(1 for i in range(n_records) if hbsag_pos[i])
    hepa_non_reactive = sum(1 for i in range(n_records) if hbsag_neg[i] and not hbsag_pos[i])

    # 6. Delivery & Skilled Attendant
    sba_total = n_records

    # 7. Postpartum Hemorrhage (PPH)
    has_pph = [
        _has_code_or_label(row, "CJiTafFo0TS", {"3"}, {"pph", "hemorrhage", "postpartum hemorrhage"},
                           col_name="Delivery summary_Obstetric condition at delivery")
        for _, row in df.iterrows()
    ]
    pph_count = sum(1 for i in range(n_records) if has_pph[i])

    # 8. Uterotonics
    has_oxy = [
        _has_code_or_label(row, "yVRLuRU943e", {"2"}, {"oxytocin"},
                           col_name="Delivery summary_Uterotonics given")
        for _, row in df.iterrows()
    ]
    has_miso = [
        _has_code_or_label(row, "yVRLuRU943e", {"3"}, {"misoprostol", "mesoprostol"},
                           col_name="Delivery summary_Uterotonics given")
        for _, row in df.iterrows()
    ]
    has_ergo = [
        _has_code_or_label(row, "yVRLuRU943e", {"1"}, {"ergometrine", "ergometrin"},
                           col_name="Delivery summary_Uterotonics given")
        for _, row in df.iterrows()
    ]
    uter_oxy = sum(1 for i in range(n_records) if has_oxy[i])
    uter_miso = sum(1 for i in range(n_records) if has_miso[i])
    uter_ergo = sum(1 for i in range(n_records) if has_ergo[i])
    uter_total = sum(1 for i in range(n_records) if has_oxy[i] or has_miso[i] or has_ergo[i])

    # 9. Stillbirths and Live Births
    nb_elements = ["wZig9cek3Gv", "BiFmMp0p2CB", "ZX1tFRjBAEe", "htcUfQyftnv"]
    total_stillbirths = 0
    total_livebirths = 0
    for _, row in df.iterrows():
        for uid in nb_elements:
            if _has_code_or_label(row, uid, {"2"}, {"stillbirth"}):
                total_stillbirths += 1
            elif _has_code_or_label(row, uid, {"1"}, {"alive", "live birth"}):
                total_livebirths += 1
    if total_stillbirths == 0 and total_livebirths == 0:
        total_livebirths = int((_str_match_mask(df, _OUTCOME, ["live", "alive"])).sum()) or n_records
        total_stillbirths = int((_str_match_mask(df, _OUTCOME, ["still"])).sum()) or int((_str_match_mask(df, _STILLBIRTH, ["yes"])).sum())

    # 10. Early Postnatal Care (PNC) within 7 days
    pnc_24h = [
        _has_code_or_label(row, "z7Eb2yFLOBI", {"1"}, {"24 hrs stay", "24"},
                           col_name="Postpartum care_Date/stay pp")
        for _, row in df.iterrows()
    ]
    pnc_48h = [
        _has_code_or_label(row, "z7Eb2yFLOBI", {"2"}, {"25- 48 hrs", "48"},
                           col_name="Postpartum care_Date/stay pp")
        for _, row in df.iterrows()
    ]
    pnc_72h = [
        _has_code_or_label(row, "z7Eb2yFLOBI", {"3"}, {"49-72 hrs", "72"},
                           col_name="Postpartum care_Date/stay pp")
        for _, row in df.iterrows()
    ]
    pnc_7d = [
        _has_code_or_label(row, "z7Eb2yFLOBI", {"4"}, {"73hrs-7 days", "7 days"},
                           col_name="Postpartum care_Date/stay pp")
        for _, row in df.iterrows()
    ]

    epnc_24h = sum(1 for i in range(n_records) if pnc_24h[i])
    epnc_48h = sum(1 for i in range(n_records) if pnc_48h[i])
    epnc_72h = sum(1 for i in range(n_records) if pnc_72h[i])
    epnc_7d = sum(1 for i in range(n_records) if pnc_7d[i])
    epnc_total = sum(1 for i in range(n_records) if pnc_24h[i] or pnc_48h[i] or pnc_72h[i] or pnc_7d[i])

    # 11. Caesarean Section
    cs_total = sum(
        1 for _, row in df.iterrows()
        if _has_code_or_label(row, "lphtwP2ViZU", {"2"}, {"cesarean", "c-section", "cesarean section (c-section)"},
                              col_name="Delivery summary_Mode of Delivery maternal")
    )

    # 12. Institutional Maternal Death
    imd_total = sum(
        1 for _, row in df.iterrows()
        if _has_code_or_label(row, "TjQOcW6tm8k", {"4"}, {"dead", "died"},
                              col_name="Discharge Summary_Condition of Discharge")
    )

    # Map by S.No and Row index
    calculated_by_sno: dict[str, Any] = {
        "MAT_IPPCAR_Age":    ppfp_age_total,
        "MAT_IPPCAR_Age. 1": ppfp_age_10_14,
        "MAT_IPPCAR_Age. 2": ppfp_age_15_19,
        "MAT_IPPCAR_Age. 3": ppfp_age_20_24,
        "MAT_IPPCAR_Age. 4": ppfp_age_25_29,
        "MAT_IPPCAR_Age. 5": ppfp_age_30_49,
        "MAT_IPPCAR_Mtd":    ppfp_mtd_total,
        "MAT_IPPCAR_Mtd. 1": ppfp_mtd_oral,
        "MAT_IPPCAR_Mtd. 2": ppfp_mtd_implants,
        "MAT_IPPCAR_Mtd. 3": ppfp_mtd_iucd,
        "MAT_IPPCAR_Mtd. 5": ppfp_mtd_other,
        "MAT_ANC1_MA.1":     anc1_total,
        "MAT_ANC1_MA.1. 1":  anc1_10_14,
        "MAT_ANC1_MA.1. 2":  anc1_15_19,
        "MAT_ANC1_MA.1. 3":  anc1_ge_20,
        "MAT_ANC4+_MA.1":    anc4_total,
        "MAT_ANC4+_MA.1. 1": anc4_10_14,
        "MAT_ANC4+_MA.1. 2": anc4_15_19,
        "MAT_ANC4+_MA.1. 3": anc4_ge_20,
        "MAT_ANC8+.":        anc8_total,
        "MAT_SYPH.1":        syp_tested,
        "MAT_SYPH.1. 1":     syp_reactive,
        "MAT_SYPH.1. 2":     syp_non_reactive,
        "MAT_Hepa":          hepa_tested,
        "MAT_Hepa. 1":       hepa_reactive,
        "MAT_Hepa. 2":       hepa_non_reactive,
        "L&D_SBA.1.":        sba_total,
        "MAT_PPH.1":         pph_count,
        "MAT_PPH.1. 2":      pph_count,
        "MAT_UTER.1":        uter_total,
        "MAT_UTER.1. 1":     uter_oxy,
        "MAT_UTER.1. 2":     uter_miso,
        "MAT_UTER.1. 3":     uter_ergo,
        "MAT_SBR.SB.":       total_stillbirths,
        "MAT_SBR.LB.":       total_livebirths,
        "MAT_EPNC.1":        epnc_total,
        "MAT_EPNC.1. 2":     epnc_24h,
        "MAT_EPNC.1. 3":     epnc_48h,
        "MAT_EPNC.1. 4":     epnc_72h,
        "MAT_EPNC.1. 5":     epnc_7d,
        "MAT_CS.1.":         cs_total,
        "MAT_IMD.1.":        imd_total,
    }

    values: dict[str, Any] = {}
    for idx, r in enumerate(rep_rows):
        r_idx = idx + 3
        st = r.get("status")
        sno = r.get("sno")

        if st == "HEADER":
            val = None
        elif st == "NOT CAPTURED":
            val = "Not available"
        else:
            val = calculated_by_sno.get(sno)
            if val is None and sno:
                val = calculated_by_sno.get(norm(sno))
            if val is None:
                val = 0

        values[f"row_{r_idx}"] = val
        if sno and st != "HEADER":
            values[sno] = val
            values[norm(sno)] = val

    return values


def build_import_json(
    values: dict[str, Any],
    period: str,
    org_unit_uid: str,
    dataset_uid: str = "",
    de_uid_map: dict[str, str] | None = None,
    default_coc: str = "",
) -> dict:
    """Build DHIS2 dataValueSets import payload."""
    de_map = de_uid_map or {}
    dv_list = []
    for code, val in values.items():
        if val is not None and val != "Not available":
            uid = de_map.get(code, code)
            item = {
                "dataElement": uid,
                "period": period,
                "orgUnit": org_unit_uid,
                "value": str(val),
            }
            if default_coc:
                item["categoryOptionCombo"] = default_coc
            dv_list.append(item)
    res = {
        "period": period,
        "orgUnit": org_unit_uid,
        "dataValues": dv_list,
    }
    if dataset_uid:
        res["dataSet"] = dataset_uid
    return res


def resolve_ou(client: Any, org_unit: str | None, program_uid: str = "") -> tuple[str, str]:
    """Resolve org unit string or ID to (uid, display_name)."""
    if not org_unit:
        return "", "All facilities"
    ou_uid = org_unit
    ou_name = org_unit
    try:
        info = client.get(f"organisationUnits/{org_unit}", params={"fields": "id,name"})
        if "name" in info:
            return info["id"], info["name"]
    except Exception:
        pass
    try:
        ous = client.get(
            "organisationUnits",
            params={"filter": f"name:ilike:{org_unit}", "fields": "id,name", "paging": "false"}
        ).get("organisationUnits", [])
        if ous:
            return ous[0]["id"], ous[0]["name"]
    except Exception:
        pass
    return ou_uid, ou_name


if __name__ == "__main__":
    main()

