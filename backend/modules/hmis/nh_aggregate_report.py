"""
================================================================================
  PROJECT  : IMNID — Neonatal Health DHIS2 Registry
  FILE     : aggregate_report.py
  PURPOSE  : Compute the Ethiopian MoH "04.2 — Neonatal and Child Health"
             aggregate monthly report from DHIS2 tracker data (Neonatal Care
             Form program) and POST the result to a DHIS2 aggregate dataset.

  REPORT   : 04.2 - Neonatal and Child Health | Monthly
             Institutional neonatal death · Pneumonia treatment · KMC ·
             Asphyxia / Resuscitation · NICU admission & outcome · CHX

  SOURCE   : Tracker program "Neonatal Care Form" (NICU admission form).
             Indicators that belong to the IMNCI/OPD side of the 04.2 form
             (pneumonia, diarrhoea, developmental milestone assessment) are
             NOT collected in this program and are marked for manual entry.

  AUTH     (priority: CLI → env vars → credentials file → interactive)
    CLI  : --url https://imnid.aau.edu.et/dhis --username X --password Y
    File : dhis2_credentials.json

  QUICK START:
    # 1. Preview report — prints computed values, saves Excel
    python aggregate_report.py \\
      --program <UID> \\
      --org-unit <OU_UID_or_NAME> \\
      --period 202410 \\
      --preview nh_oct2024.xlsx

    # 2. Submit to DHIS2 aggregate (dry-run first)
    python aggregate_report.py \\
      --program <UID> \\
      --org-unit <OU_UID_or_NAME> \\
      --period 202410 \\
      --dataset <AGGREGATE_DATASET_UID> \\
      --dry-run

    # 3. Submit for real
    python aggregate_report.py \\
      --program <UID> \\
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
from typing import Any

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("ERROR: 'requests' not installed.  pip install requests")
    sys.exit(1)

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

warnings.filterwarnings("ignore")
CRED_FILE = Path("dhis2_credentials.json")

# ── Neonatal Care Form column names (live API names) ──────────────────────────
# Column names are built live by fetch_tracker_df() as "{Stage}_{DE name}".
# They are sourced from neonatal_register.py's RAW dict (with literal
# fallbacks) so the register and this aggregate report never drift apart.
try:
    from backend.modules.hmis.nh_neonatal_register import RAW as _RAW
except ImportError:
    try:
        from nh_neonatal_register import RAW as _RAW
    except ImportError:
        try:
            from neonatal_register import RAW as _RAW
        except ImportError:
            _RAW = {}

def _col_key(key: str, fallback: str) -> str:
    return _RAW.get(key, fallback)

_ASPHYXIA   = _col_key("asphyxia",   "NICU Admission Careform_Asphyxia")
_RESUS_ROOM = _col_key("resus_room", "NICU Admission Careform_Resuscitation  in delivery room")
_RESUS_DONE = _col_key("resus_done", "NICU Admission Careform_If Resuscitated, tick what was done")
_CHX        = _col_key("chx",        "NICU Admission Careform_Cord Chlorhexidine Administered")
_BW         = _col_key("birth_weight","NICU Admission Careform_Birth Weight n")
_GA_CAT     = _col_key("ga_cat",     "NICU Admission Careform_Gestational Age")
_GA_WEEKS   = _col_key("ga_weeks",   "NICU Admission Careform_Gestational age at delivery weeks")
_DOB        = _col_key("dob",        "NICU Admission Careform_Date of delivery")
_ADM_DATE   = _col_key("admit_date", "NICU Admission Careform_Date of Admission n")
_ADM_EVT    = "NICU Admission Careform_event_date"
_KMC_DATE   = _col_key("kmc_date",   "KMC ward follow up sheet_KMC intiation date")
_KMC_DONE   = _col_key("kmc_done",   "Nurse followup Sheet_Kmc done")
_DIS_DATE   = _col_key("dis_date",   "Discharge care form_Date and time of discharge")
_DIS_STATUS = _col_key("dis_status", "Discharge care form_Newborn status at discharge n")
_DIS_OUTCOME= _col_key("dis_outcome","Discharge care form_Discharge Outcome n")
_REFERRED   = _col_key("referred_to","Neonatal referral form_Transferred to")


# ── Indicator computation helpers ─────────────────────────────────────────────

def _col(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return df[col].astype(str).fillna("")
    return pd.Series("", index=df.index)


def _str_match(df: pd.DataFrame, col: str, patterns: list[str]) -> int:
    s = _col(df, col)
    mask = pd.Series(False, index=df.index)
    for p in patterns:
        mask |= s.str.contains(p, case=False, na=False)
    return int(mask.sum())


def _numeric(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce")


def _birth_weight(df: pd.DataFrame) -> pd.Series:
    bw = _numeric(df, _BW)
    bw.loc[(bw > 0) & (bw < 20)] *= 1000   # entered in kg → grams
    return bw


def _preterm(df: pd.DataFrame) -> pd.Series:
    cat = _col(df, _GA_CAT).str.lower().str.contains("preterm", na=False)
    weeks = _numeric(df, _GA_WEEKS)
    return cat | (weeks < 37)


def _admission_dates(df: pd.DataFrame) -> pd.Series:
    """Admission date series: 'Date of Admission' value, falling back to the
    NICU admission event date."""
    dval = pd.to_datetime(df[_ADM_DATE], errors="coerce") if _ADM_DATE in df.columns else pd.Series(pd.NaT, index=df.index)
    devt = pd.to_datetime(df[_ADM_EVT], errors="coerce") if _ADM_EVT in df.columns else pd.Series(pd.NaT, index=df.index)
    return dval.fillna(devt)


def _death_age_days(df: pd.DataFrame) -> pd.Series:
    """Age at death (days) = discharge date − birth date for neonates whose
    discharge status is 'Dead'."""
    dob = pd.to_datetime(df.get(_DOB), errors="coerce")
    dis = pd.to_datetime(df.get(_DIS_DATE), errors="coerce")
    died = _col(df, _DIS_STATUS).str.lower().str.strip() == "dead"
    diff = (dis - dob).dt.days
    return diff.where(died & (diff >= 0))


def _kmc_initiated(df: pd.DataFrame) -> pd.Series:
    kmc_date = _col(df, _KMC_DATE)
    kmc_done = _col(df, _KMC_DONE).str.lower().str.strip()
    return kmc_date.str.strip().ne("") | (kmc_done == "yes")


def _resuscitated(df: pd.DataFrame) -> pd.Series:
    """Neonates resuscitated with bag & mask ventilation."""
    bag = _col(df, _RESUS_DONE).str.lower().str.contains("bag", na=False)
    room = _col(df, _RESUS_ROOM).str.lower().str.strip() == "yes"
    return bag | room


def _survived(df: pd.DataFrame) -> pd.Series:
    return _col(df, _DIS_STATUS).str.lower().str.strip() == "alive"


def _discharged(df: pd.DataFrame) -> pd.Series:
    """Has a discharge form (date and/or outcome recorded)."""
    d_date = _col(df, _DIS_DATE)
    d_out  = _col(df, _DIS_OUTCOME)
    d_stat = _col(df, _DIS_STATUS)
    return (d_date.str.strip().ne("")
            | d_out.str.strip().ne("")
            | d_stat.str.strip().ne(""))


# ── Indicator class ───────────────────────────────────────────────────────────

class Indicator:
    """One row in the HMIS 04.2 aggregate report."""
    __slots__ = ("code", "label", "section", "source", "_fn")

    def __init__(self, code, label, section, source="NCF", compute=None):
        self.code    = code
        self.label   = label
        self.section = section
        self.source  = source
        self._fn     = compute

    def compute(self, df: pd.DataFrame):
        if self._fn is None or df is None or df.empty:
            return None
        try:
            v = self._fn(df)
            return int(v) if v is not None else None
        except Exception:
            return None


# ── Full indicator list — mirrors the 04.2 PDF row by row ─────────────────────
# NCF  = computable from the Neonatal Care Form program
# MANUAL = belongs to the IMNCI/OPD side (pneumonia, diarrhoea, milestones)

INDICATORS: list[Indicator] = [
    # IMNCI/Paediatric OPD — not in the NICU form
    Indicator("Paediatric_OPD.", "NCH - IMNCI/Paediatric OPD services provided",
              "CH", source="MANUAL"),
    Indicator("CH",              "Child Health",                    "CH", source="MANUAL"),

    # ════════════════════════════════════════════════════════════════════════════
    # INSTITUTIONAL NEONATAL DEATH  (from Discharge care form, status = Dead)
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("CH_IND",    "Institutional neonatal death", "NEO_DEATH",
              compute=lambda df: int((_death_age_days(df).notna()).sum())),
    Indicator("CH_IND.1",  "< 24 Hours", "NEO_DEATH",
              compute=lambda df: int((_death_age_days(df) < 1).sum())),
    Indicator("CH_IND.2",  "1-7 Days",   "NEO_DEATH",
              compute=lambda df: int(((_death_age_days(df) >= 1)
                                     & (_death_age_days(df) <= 7)).sum())),
    Indicator("CH_IND.3",  "8 - 28 Days","NEO_DEATH",
              compute=lambda df: int(((_death_age_days(df) >= 8)
                                     & (_death_age_days(df) <= 28)).sum())),

    # ════════════════════════════════════════════════════════════════════════════
    # PNEUMONIA / SICK YOUNG INFANTS — IMNCI/OPD, not collected here
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("CH_TX_PNEU",   "Under-five children with pneumonia received antibiotic treatment",
              "PNEUMONIA", source="MANUAL"),
    Indicator("CH_TX_PNEU.1.", "Number of under 5 children treated for pneumonia",
              "PNEUMONIA", source="MANUAL"),
    Indicator("CH_TX_SYI.1", "Number of sick young infants 0-2 months treated for Critical illness",
              "PNEUMONIA", source="MANUAL"),
    Indicator("CH_TX_SYI.1.1", "Very Severe Diseases", "PNEUMONIA", source="MANUAL"),
    Indicator("CH_TX_SYI.1.2", "Local Bacterial Infection (LBI)", "PNEUMONIA", source="MANUAL"),
    Indicator("CH_TX_SYI.1.3", "Pneumonia", "PNEUMONIA", source="MANUAL"),

    # ════════════════════════════════════════════════════════════════════════════
    # DIARRHOEA — IMNCI/OPD, not collected here
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("CH_TX_DIAR",   "Children treated with Zinc and ORS for diarrhea",
              "DIARRHOEA", source="MANUAL"),
    Indicator("CH_TX_DIAR.1.", "Treated by ORS and zinc", "DIARRHOEA", source="MANUAL"),
    Indicator("CH_TX_DIAR.2.", "Treated by ORS only",     "DIARRHOEA", source="MANUAL"),

    # ════════════════════════════════════════════════════════════════════════════
    # KANGAROO MOTHER CARE  (KMC ward follow up sheet)
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("CH_KMC",    "LBW or premature newborns for whom KMC was initiated after delivery",
              "KMC"),
    Indicator("CH_KMC.1.", "Newborns weighing <2000gm and/or premature for which KMC initiated",
              "KMC",
              compute=lambda df: int((_kmc_initiated(df)
                                      & ((_birth_weight(df) < 2000) | _preterm(df))).sum())),
    Indicator("CH_KMC.2.", "Total newborns weighing <2000gm and/or premature",
              "KMC",
              compute=lambda df: int(((_birth_weight(df) < 2000) | _preterm(df)).sum())),

    # ════════════════════════════════════════════════════════════════════════════
    # ASPHYXIA / RESUSCITATION  (NICU Admission care form)
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("NCH_CHIM_AsfxRS", "Asphyxiated neonates who were resuscitated (with bag & mask) and survived",
              "ASPHYXIA"),
    Indicator("CH_ASPH.1.", "Number of neonates resuscitated and survived",
              "ASPHYXIA",
              compute=lambda df: int((_resuscitated(df) & _survived(df)).sum())),
    Indicator("CH_ASPH.2.", "Total Number of neonates Resuscitated",
              "ASPHYXIA",
              compute=lambda df: int(_resuscitated(df).sum())),

    # NICU service availability — facility question, manual
    Indicator("NCH_CHIM_NICU_YN", "Does the facility provide NICU service?",
              "NICU", source="MANUAL"),

    # ════════════════════════════════════════════════════════════════════════════
    # TREATMENT OUTCOME OF NEONATES ADMITTED TO NICU
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("NCH_CHIM_NICU", "Treatment outcome of neonates admitted to NICU",
              "NICU"),
    Indicator("CH_TX_NICUA.",  "Total neonates admitted to NICU",
              "NICU",
              compute=lambda df: len(df)),
    Indicator("CH_TX_NICUD",   "Total neonates discharged from NICU",
              "NICU",
              compute=lambda df: int(_discharged(df).sum())),
    Indicator("CH_TX_NICUD.1", "Recovered",
              "NICU",
              compute=lambda df: int(((_col(df, _DIS_STATUS).str.lower().str.strip() == "alive")
                                       & (_col(df, _DIS_OUTCOME).str.lower().str.contains("discharged")
                                          | _discharged(df))).sum())),
    Indicator("CH_TX_NICUD.2", "Died",
              "NICU",
              compute=lambda df: int((_death_age_days(df).notna()).sum())),
    Indicator("CH_TX_NICUD.3", "Transferred out",
              "NICU",
              compute=lambda df: int((_col(df, _DIS_OUTCOME).str.lower().str.contains("referred|transfer")
                                      | _col(df, _REFERRED).str.strip().ne("")).sum())),
    Indicator("CH_TX_NICUD.4", "Others",
              "NICU",
              compute=lambda df: int((_discharged(df)
                                      & ~_survived(df)
                                      & _death_age_days(df).isna()
                                      & _col(df, _DIS_OUTCOME).str.lower().str.contains("referred|transfer").eq(False)
                                      & _col(df, _REFERRED).str.strip().eq("")).sum())),

    # ════════════════════════════════════════════════════════════════════════════
    # CHX — cord chlorhexidine (NICU Admission care form)
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("CH_CHX",   "Newborns that received at least one dose of CHX to the cord on the first day after birth",
              "CHX"),
    Indicator("CH_CHX.1.", "Number of Newborns received at least one dose of CHX on the 1st day after birth",
              "CHX",
              compute=lambda df: _str_match(df, _CHX, ["yes"])),

    # ════════════════════════════════════════════════════════════════════════════
    # DEVELOPMENTAL MILESTONE ASSESSMENT — child-health (0-59 months), not here
    # ════════════════════════════════════════════════════════════════════════════
    Indicator("CH_CHDM",    "Children 0 to 59 months Assessed for developmental milestone",
              "MILESTONE", source="MANUAL"),
    Indicator("CH_CHDM.1",  "0 to 24 Months",      "MILESTONE", source="MANUAL"),
    Indicator("CH_CHDM.2",  "24 - 59 Months",      "MILESTONE", source="MANUAL"),
    Indicator("CH_CHDMS",   "Children 0 to 59 months Assessed for developmental milestone by status",
              "MILESTONE", source="MANUAL"),
    Indicator("CH_CHDMS.1", "Suspected Developmental Delay", "MILESTONE", source="MANUAL"),
    Indicator("CH_CHDMS.2", "Developmental Delay",           "MILESTONE", source="MANUAL"),
    Indicator("CH_CHDMS.3", "No Developmental Delay",        "MILESTONE", source="MANUAL"),
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
    """Pull TEIs from DHIS2 tracker and return a flat DataFrame, filtered by
    the NICU admission date."""
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
    if ou_uid:
        params["orgUnit"] = ou_uid

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
    de_opts: dict[tuple, dict] = {}
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
                col = attr_map.get(attr.get("attribute", ""))
                if col:
                    row[col] = attr.get("value", "")

            best: dict[str, dict] = {}
            for evt in enr.get("events", []):
                s = evt.get("programStage", "")
                if s not in best or evt.get("occurredAt", "") > best[s].get("occurredAt", ""):
                    best[s] = evt

            for s_uid, evt in best.items():
                s_name = stage_map.get(s_uid, "")
                if s_name:
                    occ = evt.get("occurredAt", "")
                    row[f"{s_name}_event_id"]     = evt.get("event", "")
                    row[f"{s_name}_event_date"]   = occ[:10] if occ else ""
                    row[f"{s_name}_event_status"] = evt.get("status", "")
                for dv in evt.get("dataValues", []):
                    col = de_map.get((s_uid, dv.get("dataElement", "")))
                    if not col:
                        continue
                    val = str(dv.get("value", ""))
                    opts = de_opts.get((s_uid, dv.get("dataElement", "")))
                    if opts:
                        labels = []
                        for part in val.split(","):
                            part = part.strip()
                            if part in opts:
                                labels.append(opts[part])
                            elif part:
                                labels.append(part)
                        val = ", ".join(labels)
                    row[col] = val
            rows.append(row)

    df = pd.DataFrame(rows)

    if start or end:
        if not df.empty:
            d_adm = _admission_dates(df)
            d_enr = pd.to_datetime(df.get("enrollment_date"), errors="coerce")
            d_inc = pd.to_datetime(df.get("incident_date"), errors="coerce")
            d = d_adm.fillna(d_enr).fillna(d_inc)

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
            print(f"  {len(df):,} admissions within {start or '…'} → {end or '…'} "
                  f"(of {n_all:,} TEIs fetched)")

    print(f"  DataFrame: {df.shape[0]:,} rows × {df.shape[1]} columns")
    return df


def diagnose_values(df: pd.DataFrame):
    key_cols = [
        _ASPHYXIA, _RESUS_ROOM, _RESUS_DONE, _CHX, _BW, _GA_CAT, _GA_WEEKS,
        _DOB, _ADM_DATE, _KMC_DATE, _KMC_DONE, _DIS_DATE, _DIS_STATUS,
        _DIS_OUTCOME, _REFERRED,
    ]
    print("\n── Value diagnostics ────────────────────────────────────────────────")
    for col in key_cols:
        if col not in df.columns:
            print(f"  {col!r:<70}  COLUMN MISSING")
            continue
        vals = df[col].dropna()
        vals = vals[vals.astype(str).str.strip() != ""]
        unique = vals.value_counts().head(10)
        if unique.empty:
            print(f"  {col!r:<70}  (all empty)")
        else:
            print(f"\n  {col!r}  ({len(vals)} non-empty values)")
            for v, cnt in unique.items():
                print(f"      {cnt:>4}×  {str(v)!r}")


# ── DHIS2 aggregate API helpers ───────────────────────────────────────────────

def fetch_default_coc(client: DHIS2Client) -> str:
    data = client.get("categoryOptionCombos",
                      {"filter": "name:eq:default", "fields": "id", "paging": "false"})
    cocs = data.get("categoryOptionCombos", [])
    if cocs:
        return cocs[0]["id"]
    raise RuntimeError("Could not find default categoryOptionCombo on this server.")


def lookup_de_uids(client: DHIS2Client, codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
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
    dv_list   = []
    index     = []
    resolved  = 0
    for ind in INDICATORS:
        value = values.get(ind.code)
        uid   = de_uid_map.get(ind.code)
        needs_uid   = uid is None
        needs_value = value is None
        if uid is None:
            uid = f"[{ind.code}]"

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

    Path(output_path).write_text(
        json.dumps({"dataValues": dv_list}, indent=4, ensure_ascii=False)
    )
    print(f"Import JSON saved  → {output_path}  "
          f"({len(dv_list)} entries, {resolved} UIDs resolved)")

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
    if dry_run:
        print("\n── Dry-run payload (would POST to /api/dataValueSets) ──────────")
        print(json.dumps(payload, indent=2))
        return {"status": "DRY_RUN", "imported": len(payload["dataValues"])}
    resp = client.post("dataValueSets", payload,
                       params={"importStrategy": "CREATE_AND_UPDATE"})
    return resp


# ── Excel preview ─────────────────────────────────────────────────────────────

_SECTION_LABELS = {
    "CH":        "NCH - IMNCI/Paediatric OPD",
    "NEO_DEATH": "Institutional Neonatal Death",
    "PNEUMONIA": "Pneumonia / Critical Illness",
    "DIARRHOEA": "Diarrhoea Treatment",
    "KMC":       "Kangaroo Mother Care",
    "ASPHYXIA":  "Asphyxia / Resuscitation",
    "NICU":      "NICU Admission & Outcome",
    "CHX":       "Cord Chlorhexidine (CHX)",
    "MILESTONE": "Developmental Milestone",
}

_SECTION_COLOR = {
    "CH":        "B8E4B8",
    "NEO_DEATH": "F4C2C2",
    "PNEUMONIA": "E4D4B8",
    "DIARRHOEA": "E4B8B8",
    "KMC":       "D4B8E4",
    "ASPHYXIA":  "E4E4B8",
    "NICU":      "B8D4E4",
    "CHX":       "B8E4E4",
    "MILESTONE": "C2D4F4",
}


def write_preview_excel(values: dict[str, int | None],
                        period: str, ou_name: str,
                        output_path: str):
    if not HAS_OPENPYXL:
        print("ERROR: openpyxl not installed — cannot write Excel.  pip install openpyxl")
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "04.2 NH Monthly Report"

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

    ws.merge_cells("A1:D1")
    cell(1, 1,
         "04.2 - Neonatal and Child Health | Monthly Report",
         bold=True, bg="1E4D8C")
    ws.cell(row=1, column=1).font = Font(bold=True, size=12, color="FFFFFF")
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center",
                                                    vertical="center")
    ws.row_dimensions[1].height = 24

    ws.merge_cells("A2:D2")
    cell(2, 1, f"Period: {period}   |   Org unit: {ou_name}", bold=False, bg="D0E4FF")

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

        bg  = _SECTION_COLOR.get(ind.section, "FFFFFF") + "44"
        val = values.get(ind.code)
        val_str = str(val) if val is not None else "—"
        src = "NCF tracker" if ind.source == "NCF" else "MANUAL"

        cell(row, 1, ind.code,  bg=None)
        cell(row, 2, ind.label, bg=None, wrap=True)
        cell(row, 3, val_str,   bg=("C8F4C8" if val is not None else "F4F4F4"),
             align="center")
        cell(row, 4, src,       bg=None, align="center")
        ws.row_dimensions[row].height = 15
        row += 1

    ws.freeze_panes = "A4"
    wb.save(output_path)
    print(f"Preview saved → {output_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="aggregate_report.py",
        description="Generate & submit the 04.2 NH aggregate monthly report from DHIS2 tracker data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = ap.add_argument_group("Connection")
    grp.add_argument("--url",      help="DHIS2 base URL")
    grp.add_argument("--username", help="DHIS2 username")
    grp.add_argument("--password", help="DHIS2 password")
    grp.add_argument("--no-ssl-verify", action="store_true",
                     help="Disable SSL certificate verification")

    grp = ap.add_argument_group("Tracker source")
    grp.add_argument("--program", metavar="UID", required=True,
                     help="Neonatal Care Form tracker program UID")
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
                          "month derived from --period).")
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
                     help="Aggregate dataset UID (04.2 NH dataset in DHIS2)")
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

    try:
        info = client.get("system/info")
        print(f"Connected  : {info.get('systemName','DHIS2')} v{info.get('version','?')}")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

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
        year, month = int(start[:4]), int(start[5:7])
        period = f"{year:04d}{month:02d}"
        if not end:
            import calendar
            end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"

    try:
        if datetime.strptime(end, "%Y-%m-%d") < datetime.strptime(start, "%Y-%m-%d"):
            print(f"ERROR: --end ({end}) is before --start ({start}).")
            sys.exit(1)
    except Exception:
        pass

    print(f"Reporting window : {start} → {end}  (period tag: {period})")

    ou_uid  = args.org_unit or ""
    ou_name = ou_uid

    if ou_uid:
        try:
            ou_info = client.get(f"organisationUnits/{ou_uid}", {"fields": "id,name"})
            ou_name = ou_info.get("name", ou_uid)
        except Exception:
            pass

    df = fetch_tracker_df(client,
                          program_uid=args.program,
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

    print(f"\nComputing {len(INDICATORS)} indicators ...")
    values: dict[str, int | None] = {}
    for ind in INDICATORS:
        values[ind.code] = ind.compute(df)

    computed = {k: v for k, v in values.items() if v is not None}
    print(f"  Computed : {len(computed):,}  (others require manual entry)")
    print("\n── NCF-computed indicators ─────────────────────────────────────────")
    for ind in INDICATORS:
        v = values[ind.code]
        if ind.source == "NCF" and v is not None:
            print(f"  {ind.code:<28}  {v:>6}   {ind.label}")

    if args.preview:
        write_preview_excel(values, period, ou_name, args.preview)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"period": period, "orgUnit": ou_uid,
                        "generatedAt": pd.Timestamp.now().isoformat(),
                        "values": {k: v for k, v in values.items() if v is not None}},
                       indent=4, ensure_ascii=False))
        print(f"JSON summary saved → {args.json_out}")

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


def compute_indicators(df: pd.DataFrame) -> dict[str, int | None]:
    """Compute all indicators defined in INDICATORS registry for the given tracker dataframe."""
    values: dict[str, int | None] = {}
    for ind in INDICATORS:
        values[ind.code] = ind.compute(df)
    return values


def build_import_json(
    values: dict[str, int | None],
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
        if val is not None:
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

