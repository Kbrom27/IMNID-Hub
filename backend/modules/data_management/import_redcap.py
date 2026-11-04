# pages/dhis2_to_redcap.py
import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
import numpy as np
from datetime import datetime
import time
import json
from typing import Dict, Any, List, Tuple, Optional
import calendar
# Fixed DHIS2 program 
PROGRAM_ID = "pLk3Ht2XMKl"   # Newborn inpatient data

# ------- UI + network defaults -------
REQUEST_TIMEOUT = 300
RETRY_BACKOFF = [1, 2, 4]   # seconds
BATCH_SIZE_REDCAP = 500     # records per POST to REDCap
RECORD_ID_VAR = "in_recid"  # REDCap record id variable (must exist and be non-empty)

# Mapping dictionaries

FACILITY_MAP = {
    "CfL31DPU5Eb": "501",
    "loQZU0vALqo": "521",
    "P2duWRpgRiT": "503",
    "b81e0YHLgGl": "523",
    "wY0L0qixy04": "504",
    "WrD6FsDkAF6": "505",
    "iRKYPXgRkJT": "522",
    "Aixgyp3mGsC": "517",
    "h2LHkncNGZt": "518",
    "OzcHzyjQ8wW": "508",
    "nsNFjtB4YjY": "509",
    "g9Ls20hQCXQ": "519",
    "xKpOsRLDIsG": "511",
    "MYoAnX6QA1H": "520",
    "JlNXtEkqfJ8": "512",
    "WNzF8NcSHLu": "515",
    "Q6ryvdOY3Tj": "516",
}

DOCTOR_MAP = {
    "Meseret": "1",
    "Semenesh": "2",
    "Tigist": "3",
    "Mekedes": "4",
    "Kalu": "5",
    "Taddele": "6",
    "Worku": "7",
    "Enat": "8",
    "Abrehet": "9",
    "Weldemikiel": "10",
    "Hailay": "11",
    "Gebreslasie": "12",
    "lamesgin": "13",
    "Abebech": "14",
    "Alex": "15",
    "Liya": "16",
    "Not applicable": "-9",
}

# Global variable for org unit mapping
ou_name_to_id = {}

# Helpers / networking

def _normalize_base(url: str) -> str:
    url = url.strip()
    if url.endswith("/"):
        url = url[:-1]
    return url

def _join(a: str, b: str) -> str:
    return f"{_normalize_base(a)}/{b.lstrip('/')}"

def fetch_with_retry(session: requests.Session, url: str, max_retries: int = 3, log=None) -> Optional[requests.Response]:
    for attempt in range(max_retries):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            if log:
                log(f"Attempt {attempt + 1} -> HTTP {resp.status_code} for {url}")
            if resp.status_code in (401, 403):
                if log: log("Authentication failed. Check username/password.")
                return None
            time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
        except requests.RequestException as e:
            if log: log(f"Request error (attempt {attempt+1}): {e}")
            time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
    if log: log(f"All attempts failed for {url}")
    return None


# DHIS2: metadata & data

def fetch_metadata(base_api: str, sess: requests.Session, program_id: str, log) -> Dict[str, Any]:
    log("Fetching DHIS2 metadata …")
    metadata = {'tea_map': {}, 'de_map': {}, 'os_map': {}, 'ps_map': {}}

    # TEAs
    tea_url = _join(base_api, "trackedEntityAttributes.json?fields=id,code,name,optionSet[id]&paging=false")
    r = fetch_with_retry(sess, tea_url, log=log)
    if r:
        teas = r.json().get('trackedEntityAttributes', [])
        metadata['tea_map'] = {t['id']: {'code': t.get('code') or t['id'], 'name': t['name']} for t in teas}

    # DEs
    de_url = _join(base_api, "dataElements.json?fields=id,code,name,optionSet[id]&paging=false")
    r = fetch_with_retry(sess, de_url, log=log)
    if r:
        des = r.json().get('dataElements', [])
        metadata['de_map'] = {d['id']: {'code': d.get('code') or d['id'], 'name': d['name']} for d in des}

    # OptionSets
    os_url = _join(base_api, "optionSets.json?fields=id,name,options[id,code,name]&paging=false")
    r = fetch_with_retry(sess, os_url, log=log)
    if r:
        option_sets = r.json().get('optionSets', [])
        metadata['os_map'] = {os['id']: {opt['id']: (opt.get('code') or opt['id']) for opt in os.get('options', [])}
                              for os in option_sets}

    # Program stages
    ps_url = _join(base_api, f"programs/{program_id}.json?fields=id,code,name,programStages[id,code,name,programStageDataElements[dataElement[id]]]&paging=false")
    r = fetch_with_retry(sess, ps_url, log=log)
    if r:
        program_data = r.json()
        metadata['ps_map'] = {
            st['id']: {
                'code': st.get('code') or st['id'],
                'name': st.get('name') or st['id'],
                'data_elements': [de['dataElement']['id'] for de in st.get('programStageDataElements', [])]
            } for st in program_data.get('programStages', [])
        }

    return metadata

def fetch_org_units(base_api: str, sess: requests.Session, log) -> List[Tuple[str, str]]:
    log("Loading Org Units …")
    endpoints = [
        "organisationUnits.json?userDataView=true&fields=id,displayName&paging=false",
        "organisationUnits.json?fields=id,displayName&paging=false"
    ]
    for ep in endpoints:
        r = fetch_with_retry(sess, _join(base_api, ep), log=log)
        if r:
            ous = r.json().get("organisationUnits", [])
            pairs = [(ou.get("id",""), ou.get("displayName") or ou.get("name") or ou.get("id")) for ou in ous]
            pairs = [(i,n) for (i,n) in pairs if i and n]
            pairs.sort(key=lambda x: x[1].lower())
            if pairs:
                log(f"Found {len(pairs)} Org Units.")
                return pairs
    log("No Org Units found or access denied.")
    return []

#def fetch_teis(base_api: str, sess: requests.Session, program_id: str, ou: str, log) -> List[Dict[str, Any]]:
def fetch_teis(base_api: str, sess: requests.Session, program_id: str, ou: str, log, start_date: str = '', end_date: str = '') -> List[Dict[str, Any]]:
    log(f"Fetching TEIs for program={program_id}, OU={ou} …")
    #params = [f"program={program_id}", f"ou={ou}", "fields=:all", "paging=false", "pageSize=10000"]
    #url = _join(base_api, f"trackedEntityInstances.json?{'&'.join(params)}")
    #r = fetch_with_retry(sess, url, log=log)

    params = [f"program={program_id}", f"ou={ou}", "fields=:all", "paging=false", "pageSize=10000"]

    # Add optional program/enrollment date filtering if provided (DHIS2 expects YYYY-MM-DD)
    if start_date:
        params.append(f"programStartDate={start_date}")
    if end_date:
        params.append(f"programEndDate={end_date}")

    url = _join(base_api, f"trackedEntityInstances.json?{'&'.join(params)}")
    log(f"Fetching TEIs with URL: {url}")
    r = fetch_with_retry(sess, url, log=log)

    if not r:
        return []
    return r.json().get('trackedEntityInstances', []) or []

def fetch_tei_events(base_api: str, sess: requests.Session, tei_uid: str, log) -> List[Dict[str, Any]]:
    url = _join(base_api, f"events.json?trackedEntityInstance={tei_uid}&fields=:all&paging=false")
    r = fetch_with_retry(sess, url, log=log)
    if not r:
        return []
    return r.json().get('events', []) or []

# =========================
# Transform helpers
# =========================
def convert_dates(value):
    """Convert dates to REDCap format (YYYY-MM-DD)."""
    if pd.isna(value) or value == '':
        return ''
    try:
        if 'T' in str(value):
            dt = datetime.strptime(value.split('T')[0], '%Y-%m-%d')
        else:
            dt = datetime.strptime(str(value), '%Y-%m-%d')
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return str(value)

def convert_time(value):
    if pd.isna(value) or value == '':
        return ''
    return str(value)

def convert_booleans(value):
    if pd.isna(value) or value == '' or value is None:
        return 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ('true', '1', 'yes', 'y', 'on'):
            return 1
        if v in ('false', '0', 'no', 'n', 'off'):
            return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) == 1 else 0
    return 0


#def convert_boo(value):
#    if pd.isna(value) or value == '' or value is None:
#        return ""
#    if isinstance(value, str):
#        v = value.strip().lower()
#        if v in ('true', '1', 'yes', 'y', 'on'):
#            return 1
#        if v in ('false', '0', 'no', 'n', 'off'):
#            return 0
#        return ""
#    if isinstance(value, bool):
#        return 1 if value else 0
#    if isinstance(value, (int, float)):
#        return 1 if int(value) == 1 else 0
#        return ""
#    return ""



def convert_boo(value: Any) -> str | int:
    # Handle missing or null-like values → empty string
    if (
        value is None
        or value == ""
        or (isinstance(value, str) and value.strip().lower() == "null")
        or pd.isna(value)
    ):
        return ""

    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y", "on"}:
            return 1
        if v in {"false", "0", "no", "n", "off"}:
            return 0
        return ""   # anything else → empty

    if isinstance(value, bool):
        return 1 if value else 0

    if isinstance(value, (int, float)):
        if int(value) == 1:
            return 1
        if int(value) == 0:
            return 0
        return ""   # unexpected numbers → empty

    return "" 





def convert_rp_id(value):
    if pd.isna(value) or value == '':
        return ''
    try:
        return f"{int(float(str(value).strip())):02d}"
    except Exception:
        return value

def _get_date_from_widget(widget) -> str:
    """
    Safely read a date string from a DateEntry widget.
    Returns '' when empty. Date format: YYYY-MM-DD.
    """
    try:
        return widget.get().strip()
    except Exception:
        try:
            return str(widget.get_date())
        except Exception:
            return ''

def _validate_date_str(s: str) -> bool:
    """Return True if s is empty or a valid YYYY-MM-DD date."""
    if not s:
        return True
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def convert_record_id_with_facility(dhis2_recid: str, facility_code: str) -> str:
    """
    Build a REDCap record id from DHIS2 recid which now has format:
    letters (2-4 chars) + 10-digit_number
    
    Process:
    1. Remove all letters (org unit code)
    2. Extract the 10-digit number
    3. Replace first 3 digits with 3-digit facility code
    4. Keep remaining 7 digits
    """
    if dhis2_recid is None:
        return ''
    
    s = str(dhis2_recid).strip()
    if s == '':
        return ''
    
    # Keep only digits in facility code, ensure exactly 3 digits
    fc = ''.join(ch for ch in str(facility_code or '') if ch.isdigit())
    if len(fc) >= 3:
        fc = fc[:3]
    else:
        fc = fc.zfill(3)
    
    # Remove ALL letters (org unit code prefix)
    # Keep only digits from the input
    digits = ''.join(ch for ch in s if ch.isdigit())
    
    if digits == '':
        return fc + s  # fallback if id contains no digits
    
    # Ensure we have at least 10 digits
    if len(digits) < 10:
        digits = digits.zfill(10)
    
    # For standard case: we have 10+ digits
    if len(digits) >= 10:
        # Take first 10 digits (in case there are more)
        ten_digits = digits[:10]
        # Replace first 3 with facility code, keep last 7
        new_recid = fc + ten_digits[3:]
    else:
        # Unexpected case: less than 10 digits
        new_recid = fc + digits
    
    return new_recid


def convert_temperature(value):
    if pd.isna(value) or value == '':
        return ''
    try:
        return str(float(value))
    except Exception:
        return value

def _generic_copy_by_header(dhis2_row: pd.Series, redcap_row: Dict[str, Any], redcap_headers: List[str]) -> Dict[str, Any]:
    for col in dhis2_row.index:
        if col not in redcap_headers:
            continue
        if redcap_row.get(col, '') not in ('', None):
            continue
        val = dhis2_row.get(col, '')
        if col.endswith(('_dt', '_date')) or col in ('in_dob', 'in_doa'):
            redcap_row[col] = convert_dates(val)
        elif col.endswith(('_tm', '_time')):
            redcap_row[col] = convert_time(val)
        elif col.endswith('_doc') or '___' in col or col.startswith('chk_'):
            redcap_row[col] = convert_booleans(val)
        elif 'temp' in col or col.endswith('_cel'):
            redcap_row[col] = convert_temperature(val)
        elif col == 'in_rp_id':
            redcap_row[col] = convert_rp_id(val)
        else:
            redcap_row[col] = '' if pd.isna(val) else str(val)
    return redcap_row

def resolve_facility(dhis2_val: str, FACILITY_MAP: Dict[str, str]) -> str:
    if not dhis2_val or pd.isna(dhis2_val):
        return ''
    
    # First check if the value is a UID that maps to a facility name
    # Create reverse lookup for UID to name
    uid_to_name = {}
    for name, code in FACILITY_MAP.items():
        # Check if we have a mapping from UID to facility name in our global ou_name_to_id
        for label, uid in ou_name_to_id.items():
            if name in label:
                uid_to_name[uid] = name
    
    # If the value is a UID that maps to a facility name, use that name
    if dhis2_val in uid_to_name:
        facility_name = uid_to_name[dhis2_val]
        return FACILITY_MAP.get(facility_name, dhis2_val)
    
    # If value is a known facility name, map it to the code
    if dhis2_val in FACILITY_MAP:
        return FACILITY_MAP[dhis2_val]
    
    # Try to find a partial match in facility names
    for facility_name in FACILITY_MAP.keys():
        if facility_name.lower() in dhis2_val.lower() or dhis2_val.lower() in facility_name.lower():
            return FACILITY_MAP[facility_name]
    
    # Fallback: just return original
    return str(dhis2_val)

def resolve_doctor(dhis2_val: str) -> str:
    if not dhis2_val:
        return ''
    return DOCTOR_MAP.get(dhis2_val.strip(), dhis2_val)


# Stage-specific mapping 
def map_program_stage_to_columns(dhis2_row: pd.Series, redcap_row: Dict[str, Any], program_stage_uid: str, redcap_headers: List[str]) -> Dict[str, Any]:
    # Admission — l39SlVGlQGs
    if program_stage_uid == "l39SlVGlQGs":
        redcap_row['in_rec_typ'] = dhis2_row.get('in_rec_typ', '')
        redcap_row['in_rec_typ_tm'] = dhis2_row.get('in_rec_typ_tm', '')
        raw_facility = str(dhis2_row.get('in_facid', '') or '').strip()
        redcap_row['in_facid'] = resolve_facility(raw_facility, FACILITY_MAP)

        redcap_row['in_dcid'] = dhis2_row.get('in_dcid', '')
        raw_doc = str(dhis2_row.get('in_dcnam_et', '') or '').strip()
        redcap_row['in_dcnam_et'] = resolve_doctor(raw_doc)
        redcap_row['in_frm_dt'] = convert_dates(dhis2_row.get('in_frm_dt', ''))
        redcap_row['in_frm_tm'] = convert_time(dhis2_row.get('in_frm_tm', ''))
        redcap_row['in_frm_dt_pap'] = convert_dates(dhis2_row.get('in_frm_dt_pap', ''))
        redcap_row['in_rp_id'] = convert_rp_id(dhis2_row.get('in_rp_id', ''))
        redcap_row['in_rp_nam'] = dhis2_row.get('in_rp_nam', '')
        redcap_row['in_rp_pos'] = dhis2_row.get('in_rp_pos', '')
        redcap_row['in_rp_pos_oth'] = dhis2_row.get('in_rp_pos_oth', '')
        redcap_row['in_bynam_fst'] = dhis2_row.get('in_bynam_fst', '')
        redcap_row['in_bynam_lst'] = dhis2_row.get('in_bynam_lst', '')
        redcap_row['in_byid_doc___1'] = convert_booleans(dhis2_row.get('in_byid_doc___1', ''))
        redcap_row['in_byid_doc___2'] = convert_booleans(dhis2_row.get('in_byid_doc___2', ''))
        redcap_row['in_byid_doc____1'] = convert_booleans(dhis2_row.get('in_byid_doc____1', ''))
        redcap_row['in_byid_doc____3'] = convert_booleans(dhis2_row.get('in_byid_doc____3', ''))
        redcap_row['in_byid'] = dhis2_row.get('in_byid', '')
        redcap_row['in_regid'] = dhis2_row.get('in_regid', '')
        redcap_row['in_mnam_fst'] = dhis2_row.get('in_mnam_fst', '')
        redcap_row['in_mnam_lst'] = dhis2_row.get('in_mnam_lst', '')
        redcap_row['in_radm'] = dhis2_row.get('in_radm', '')
        redcap_row['in_ph_num'] = dhis2_row.get('in_ph_num', '')
        redcap_row['in_ph_1'] = dhis2_row.get('in_ph_1', '')
        redcap_row['in_ph_2'] = dhis2_row.get('in_ph_2', '')
        redcap_row['in_gis'] = dhis2_row.get('in_gis', '')
        redcap_row['in_gis_doc_et___1'] = convert_booleans(dhis2_row.get('in_gis_doc_et___1', ''))
        redcap_row['in_gis_doc_et___2'] = convert_booleans(dhis2_row.get('in_gis_doc_et___2', ''))
        redcap_row['in_gis_doc_et___3'] = convert_booleans(dhis2_row.get('in_gis_doc_et___3', ''))
        redcap_row['in_gis_doc_et___4'] = convert_booleans(dhis2_row.get('in_gis_doc_et___4', ''))
        redcap_row['in_gis_sta_et'] = dhis2_row.get('in_gis_sta_et', '')
        redcap_row['in_gis_zon_et'] = dhis2_row.get('in_gis_zon_et', '')
        redcap_row['in_gis_wored_et'] = dhis2_row.get('in_gis_wored_et', '')
        redcap_row['in_gis_add'] = dhis2_row.get('in_gis_add', '')
        redcap_row['in_dob'] = convert_dates(dhis2_row.get('in_dob', ''))
        redcap_row['in_tob_doc'] = convert_booleans(dhis2_row.get('in_tob_doc', ''))
        redcap_row['in_tob'] = convert_time(dhis2_row.get('in_tob', ''))
        redcap_row['in_doa'] = convert_dates(dhis2_row.get('in_doa', ''))
        redcap_row['in_toa_doc'] = convert_booleans(dhis2_row.get('in_toa_doc', ''))
        redcap_row['in_toa'] = convert_time(dhis2_row.get('in_toa', ''))
        redcap_row['in_bloc'] = dhis2_row.get('in_bloc', '')
        redcap_row['in_bloc_ot'] = dhis2_row.get('in_bloc_ot', '')
        redcap_row['in_bloc_othfac'] = dhis2_row.get('in_bloc_othfac', '')
        redcap_row['in_bloc_othfac_typ_new'] = dhis2_row.get('in_bloc_othfac_typ_new', '')
        redcap_row['in_bloc_othfac_nam'] = dhis2_row.get('in_bloc_othfac_nam', '')
        redcap_row['in_admwt_doc'] = convert_booleans(dhis2_row.get('in_admwt_doc', ''))
        redcap_row['in_admwt'] = dhis2_row.get('in_admwt', '')
        redcap_row['in_admreas_1'] = dhis2_row.get('in_admreas_1', '')
        redcap_row['in_admreas_oth_1'] = dhis2_row.get('in_admreas_oth_1', '')
        redcap_row['in_admreas_2'] = dhis2_row.get('in_admreas_2', '')
        redcap_row['in_admreas_oth_2'] = dhis2_row.get('in_admreas_oth_2', '')
        redcap_row['in_admreas_3'] = dhis2_row.get('in_admreas_3', '')
        redcap_row['in_admreas_oth_3'] = dhis2_row.get('in_admreas_oth_3', '')

    elif program_stage_uid == "UK7jsDbVpj6":
               # Maternal and Infant Details fields
        redcap_row['in_m_dob_doc'] = dhis2_row.get('in_m_dob_doc', '')
        redcap_row['in_m_dob_dy'] = dhis2_row.get('in_m_dob_dy', '')
        redcap_row['in_m_dob_mo'] = dhis2_row.get('in_m_dob_mo', '')
        redcap_row['in_m_dob_yr'] = dhis2_row.get('in_m_dob_yr', '')
        redcap_row['in_m_age_doc'] = dhis2_row.get('in_m_age_doc', '')
        redcap_row['in_m_age'] = dhis2_row.get('in_m_age', '')
        redcap_row['in_m_aliv'] = convert_booleans(dhis2_row.get('in_m_aliv', ''))
        redcap_row['in_m_cod'] = dhis2_row.get('in_m_cod', '')
        redcap_row['in_bord_1'] = dhis2_row.get('in_bord_1', '')
        redcap_row['in_bnum'] = dhis2_row.get('in_bnum', '')
        redcap_row['in_bnum_oth'] = dhis2_row.get('in_bnum_oth', '')
        redcap_row['in_bnum_ord'] = dhis2_row.get('in_bnum_ord', '')
        redcap_row['in_delmode'] = dhis2_row.get('in_delmode', '')
        redcap_row['in_corts_admin'] = dhis2_row.get('in_corts_admin', '')
        redcap_row['in_hiv_mstat'] = dhis2_row.get('in_hiv_mstat', '')
        redcap_row['in_hiv_mtrt'] = dhis2_row.get('in_hiv_mtrt', '')
        redcap_row['in_hiv_bytrt'] = dhis2_row.get('in_hiv_bytrt', '')
        redcap_row['in_m_chrc___1'] = convert_booleans(dhis2_row.get('in_m_chrc___1', ''))
        redcap_row['in_m_chrc___2'] = convert_booleans(dhis2_row.get('in_m_chrc___2', ''))
        redcap_row['in_m_chrc___4'] = convert_booleans(dhis2_row.get('in_m_chrc___4', ''))
        redcap_row['in_m_chrc___99'] = convert_booleans(dhis2_row.get('in_m_chrc___99', ''))
        redcap_row['in_m_chrc____1'] = convert_booleans(dhis2_row.get('in_m_chrc____1', ''))
        redcap_row['in_m_chrc____3'] = convert_booleans(dhis2_row.get('in_m_chrc____3', ''))
        redcap_row['in_m_dia'] = dhis2_row.get('in_m_dia', '')
        redcap_row['in_m_dia_typ'] = dhis2_row.get('in_m_dia_typ', '')
        redcap_row['in_m_htn'] = dhis2_row.get('in_m_htn', '')
        redcap_row['in_m_othchrc'] = dhis2_row.get('in_m_othchrc', '')
        redcap_row['in_m_cov_tst'] = dhis2_row.get('in_m_cov_tst', '')
        redcap_row['in_m_cov_rslt'] = dhis2_row.get('in_m_cov_rslt', '')
        redcap_row['in_m_cov_dt'] = convert_dates(dhis2_row.get('in_m_cov_dt', ''))
        redcap_row['in_m_cov_sym'] = dhis2_row.get('in_m_cov_sym', '')
        redcap_row['in_m_cov_sym_typ'] = dhis2_row.get('in_m_cov_sym_typ', '')
        redcap_row['in_m_cov_fev'] = dhis2_row.get('in_m_cov_fev', '')
        redcap_row['in_m_cov_anos'] = dhis2_row.get('in_m_cov_anos', '')
        redcap_row['in_m_cov_rspsym'] = dhis2_row.get('in_m_cov_rspsym', '')
        redcap_row['in_by_cov_tst'] = dhis2_row.get('in_by_cov_tst', '')
        redcap_row['in_by_cov_rslt'] = dhis2_row.get('in_by_cov_rslt', '')
        redcap_row['in_by_cov_dt'] = convert_dates(dhis2_row.get('in_by_cov_dt', ''))
        redcap_row['in_by_cov_tst_reas'] = dhis2_row.get('in_by_cov_tst_reas', '')
        redcap_row['in_bwt_doc'] = convert_booleans(dhis2_row.get('in_bwt_doc', ''))
        redcap_row['in_bwt'] = dhis2_row.get('in_bwt', '')
        redcap_row['in_ga_doc'] = dhis2_row.get('in_ga_doc', '')
        redcap_row['in_ga_doc_typ'] = dhis2_row.get('in_ga_doc_typ', '')
        redcap_row['in_ga_mo'] = dhis2_row.get('in_ga_mo', '')
        redcap_row['in_ga_wk'] = dhis2_row.get('in_ga_wk', '')
        redcap_row['in_ga_dy'] = dhis2_row.get('in_ga_dy', '')
        redcap_row['in_ga_meth_doc'] = convert_booleans(dhis2_row.get('in_ga_meth_doc', ''))
        redcap_row['in_ga_meth_typ'] = dhis2_row.get('in_ga_meth_typ', '')
        redcap_row['in_ga_pn_typ'] = dhis2_row.get('in_ga_pn_typ', '')
        redcap_row['in_ga_pn_oth'] = dhis2_row.get('in_ga_pn_oth', '')
        redcap_row['in_sex'] = dhis2_row.get('in_sex', '')
        
        # Sibling information
        for i in range(1, 8):
            redcap_row[f'in_sib{i}_otcm'] = dhis2_row.get(f'in_sib{i}_otcm', '')
            redcap_row[f'in_sib{i}_de'] = dhis2_row.get(f'in_sib{i}_de', '')
            redcap_row[f'in_sib{i}_adm'] = dhis2_row.get(f'in_sib{i}_adm', '')
            redcap_row[f'in_sib{i}_id'] = dhis2_row.get(f'in_sib{i}_id', '')
            redcap_row[f'in_sib{i}_byid'] = dhis2_row.get(f'in_sib{i}_byid', '')
            redcap_row[f'in_sib{i}_regid'] = dhis2_row.get(f'in_sib{i}_regid', '')
            
            for j in range(1, 4):
                redcap_row[f'in_sib{i}_id_doc___{j}'] = convert_booleans(dhis2_row.get(f'in_sib{i}_id_doc___{j}', ''))
            
            redcap_row[f'in_sib{i}_id_doc____1'] = convert_booleans(dhis2_row.get(f'in_sib{i}_id_doc____1', ''))
            redcap_row[f'in_sib{i}_id_doc____3'] = convert_booleans(dhis2_row.get(f'in_sib{i}_id_doc____3', ''))







    elif program_stage_uid == "j0HI2eJjvbj":
        # Observation and Nursing Care 1
        redcap_row['in_tmp_adm_doc'] = dhis2_row.get('in_tmp_adm_doc', '')
        redcap_row['in_tmp_adm_typ'] = dhis2_row.get('in_tmp_adm_typ', '')
        redcap_row['in_tmp_adm_cel'] = convert_temperature(dhis2_row.get('in_tmp_adm_cel', ''))
        redcap_row['in_tmp_adm_fah'] = dhis2_row.get('in_tmp_adm_fah', '')
        redcap_row['in_tmp_adm_unk'] = dhis2_row.get('in_tmp_adm_unk', '')
        redcap_row['in_tmp_adm_wrp'] = dhis2_row.get('in_tmp_adm_wrp', '')
        redcap_row['in_o2_satur_adm_doc'] = dhis2_row.get('in_o2_satur_adm_doc', '')
        redcap_row['in_o2_satur_adm'] = dhis2_row.get('in_o2_satur_adm', '')
        redcap_row['in_o2_satur_adm_thpy'] = dhis2_row.get('in_o2_satur_adm_thpy', '')
        redcap_row['in_rds'] = dhis2_row.get('in_rds', '')
        redcap_row['in_chloro_admin'] = dhis2_row.get('in_chloro_admin', '')
        redcap_row['in_vitk_admin'] = dhis2_row.get('in_vitk_admin', '')
        redcap_row['in_glu_adm_doc'] = dhis2_row.get('in_glu_adm_doc', '')
        redcap_row['in_glu_adm_typ'] = dhis2_row.get('in_glu_adm_typ', '')
        redcap_row['in_glu_adm_mmol'] = convert_temperature(dhis2_row.get('in_glu_adm_mmol', ''))
        redcap_row['in_glu_adm_mgdl'] = dhis2_row.get('in_glu_adm_mgdl', '')
        redcap_row['in_glu_adm_unk'] = convert_temperature(dhis2_row.get('in_glu_adm_unk', ''))
        
    elif program_stage_uid == "aCrttmnx7FI":
        #Microbiology and Lab
        redcap_row['in_bld_doc'] = dhis2_row.get('in_bld_doc', '')
        redcap_row['in_bld_col_dt'] = convert_dates(dhis2_row.get('in_bld_col_dt', ''))
        redcap_row['in_bld_col_tm_doc'] = dhis2_row.get('in_bld_col_tm_doc', '')
        redcap_row['in_bld_col_tm'] = convert_time(dhis2_row.get('in_bld_col_tm', ''))
        redcap_row['in_bld_res_dt'] = convert_dates(dhis2_row.get('in_bld_res_dt', ''))
        redcap_row['in_bld_res_tm_doc'] = dhis2_row.get('in_bld_res_tm_doc', '')
        redcap_row['in_bld_res_tm'] = convert_time(dhis2_row.get('in_bld_res_tm', ''))
        redcap_row['in_bld_org'] = dhis2_row.get('in_bld_org', '')
        redcap_row['in_bld_org_oth'] = dhis2_row.get('in_bld_org_oth', '')
        redcap_row['in_bld_org_nam'] = dhis2_row.get('in_bld_org_nam', '')
        redcap_row['in_bld_ast_doc'] = dhis2_row.get('in_bld_ast_doc', '')
        redcap_row['in_bld_ast_bp'] = dhis2_row.get('in_bld_ast_bp', '')
        redcap_row['in_bld_ast_crpn'] = dhis2_row.get('in_bld_ast_crpn', '')
        redcap_row['in_bld_ast_gent'] = dhis2_row.get('in_bld_ast_gent', '')
        redcap_row['in_bld_ast_amk'] = dhis2_row.get('in_bld_ast_amk', '')
        redcap_row['in_bld_ast_cefx'] = dhis2_row.get('in_bld_ast_cefx', '')
        redcap_row['in_bld_ast_cefz'] = dhis2_row.get('in_bld_ast_cefz', '')
        redcap_row['in_bld_ast_cefo'] = dhis2_row.get('in_bld_ast_cefo', '')
        redcap_row['in_bld_ast_pip'] = dhis2_row.get('in_bld_ast_pip', '')
        redcap_row['in_bld_ast_metro'] = dhis2_row.get('in_bld_ast_metro', '')
        redcap_row['in_bld_ast_vanc'] = dhis2_row.get('in_bld_ast_vanc', '')
        redcap_row['in_bld_ast_clind'] = dhis2_row.get('in_bld_ast_clind', '')
        redcap_row['in_bld_ast_amp'] = dhis2_row.get('in_bld_ast_amp', '')
        redcap_row['in_bld_ast_amox'] = dhis2_row.get('in_bld_ast_amox', '')
        redcap_row['in_bld_ast_fluc'] = dhis2_row.get('in_bld_ast_fluc', '')
        redcap_row['in_bld_ast_mpem'] = dhis2_row.get('in_bld_ast_mpem', '')
        redcap_row['in_bld_ast_levo'] = dhis2_row.get('in_bld_ast_levo', '')
        redcap_row['in_bld_ast_oth_1'] = dhis2_row.get('in_bld_ast_oth_1', '')
        redcap_row['in_bld_ast_oth_2'] = dhis2_row.get('in_bld_ast_oth_2', '')
        redcap_row['in_bld_ast_oth_3'] = dhis2_row.get('in_bld_ast_oth_3', '')
        redcap_row['in_bld_ast_oth_4'] = dhis2_row.get('in_bld_ast_oth_4', '')
        redcap_row['in_bld_ast_oth_5'] = dhis2_row.get('in_bld_ast_oth_5', '')
        redcap_row['in_bld_ast_oth_1_nam'] = dhis2_row.get('in_bld_ast_oth_1_nam', '')
        redcap_row['in_bld_ast_oth_2_nam'] = dhis2_row.get('in_bld_ast_oth_2_nam', '')
        redcap_row['in_bld_ast_oth_3_nam'] = dhis2_row.get('in_bld_ast_oth_3_nam', '')
        redcap_row['in_bld_ast_oth_4_nam'] = dhis2_row.get('in_bld_ast_oth_4_nam', '')
        redcap_row['in_bld_ast_oth_5_nam'] = dhis2_row.get('in_bld_ast_oth_5_nam', '')
        redcap_row['in_bld_org_mult'] = dhis2_row.get('in_bld_org_mult', '')
        redcap_row['in_bld_org_mult_nam'] = dhis2_row.get('in_bld_org_mult_nam', '')
        
        # CSF fields
        redcap_row['in_csf_doc'] = dhis2_row.get('in_csf_doc', '')
        redcap_row['in_csf_col_dt'] = convert_dates(dhis2_row.get('in_csf_col_dt', ''))
        redcap_row['in_csf_col_tm_doc'] = dhis2_row.get('in_csf_col_tm_doc', '')
        redcap_row['in_csf_col_tm'] = convert_time(dhis2_row.get('in_csf_col_tm', ''))
        redcap_row['in_csf_res_dt'] = convert_dates(dhis2_row.get('in_csf_res_dt', ''))
        redcap_row['in_csf_res_tm_doc'] = dhis2_row.get('in_csf_res_tm_doc', '')
        redcap_row['in_csf_res_tm'] = convert_time(dhis2_row.get('in_csf_res_tm', ''))
        redcap_row['in_csf_org'] = dhis2_row.get('in_csf_org', '')
        redcap_row['in_csf_org_oth'] = dhis2_row.get('in_csf_org_oth', '')
        redcap_row['in_csf_org_nam'] = dhis2_row.get('in_csf_org_nam', '')
        redcap_row['in_csf_ast_doc'] = dhis2_row.get('in_csf_ast_doc', '')
        redcap_row['in_csf_ast_bp'] = dhis2_row.get('in_csf_ast_bp', '')
        redcap_row['in_csf_ast_crpn'] = dhis2_row.get('in_csf_ast_crpn', '')
        redcap_row['in_csf_ast_gent'] = dhis2_row.get('in_csf_ast_gent', '')
        redcap_row['in_csf_ast_amk'] = dhis2_row.get('in_csf_ast_amk', '')
        redcap_row['in_csf_ast_cefx'] = dhis2_row.get('in_csf_ast_cefx', '')
        redcap_row['in_csf_ast_cefz'] = dhis2_row.get('in_csf_ast_cefz', '')
        redcap_row['in_csf_ast_cefo'] = dhis2_row.get('in_csf_ast_cefo', '')
        redcap_row['in_csf_ast_pip'] = dhis2_row.get('in_csf_ast_pip', '')
        redcap_row['in_csf_ast_metro'] = dhis2_row.get('in_csf_ast_metro', '')
        redcap_row['in_csf_ast_vanc'] = dhis2_row.get('in_csf_ast_vanc', '')
        redcap_row['in_csf_ast_clind'] = dhis2_row.get('in_csf_ast_clind', '')
        redcap_row['in_csf_ast_amp'] = dhis2_row.get('in_csf_ast_amp', '')
        redcap_row['in_csf_ast_amox'] = dhis2_row.get('in_csf_ast_amox', '')
        redcap_row['in_csf_ast_fluc'] = dhis2_row.get('in_csf_ast_fluc', '')
        redcap_row['in_csf_ast_mpem'] = dhis2_row.get('in_csf_ast_mpem', '')
        redcap_row['in_csf_ast_levo'] = dhis2_row.get('in_csf_ast_levo', '')
        redcap_row['in_csf_ast_oth_1'] = dhis2_row.get('in_csf_ast_oth_1', '')
        redcap_row['in_csf_ast_oth_2'] = dhis2_row.get('in_csf_ast_oth_2', '')
        redcap_row['in_csf_ast_oth_3'] = dhis2_row.get('in_csf_ast_oth_3', '')
        redcap_row['in_csf_ast_oth_4'] = dhis2_row.get('in_csf_ast_oth_4', '')
        redcap_row['in_csf_ast_oth_5'] = dhis2_row.get('in_csf_ast_oth_5', '')
        redcap_row['in_csf_ast_oth_1_nam'] = dhis2_row.get('in_csf_ast_oth_1_nam', '')
        redcap_row['in_csf_ast_oth_2_nam'] = dhis2_row.get('in_csf_ast_oth_2_nam', '')
        redcap_row['in_csf_ast_oth_3_nam'] = dhis2_row.get('in_csf_ast_oth_3_nam', '')
        redcap_row['in_csf_ast_oth_4_nam'] = dhis2_row.get('in_csf_ast_oth_4_nam', '')
        redcap_row['in_csf_ast_oth_5_nam'] = dhis2_row.get('in_csf_ast_oth_5_nam', '')
        redcap_row['in_csf_org_mult'] = dhis2_row.get('in_csf_org_mult', '')
        redcap_row['in_csf_org_mult_nam'] = dhis2_row.get('in_csf_org_mult_nam', '')


    elif program_stage_uid == "ed8ErpgTCwx":
        #Intervention
        redcap_row['in_kmc_admin'] = dhis2_row.get('in_kmc_admin', '')
        redcap_row['in_kmc_stdt'] = convert_dates(dhis2_row.get('in_kmc_stdt', ''))
        redcap_row['in_kmc_endt'] = convert_dates(dhis2_row.get('in_kmc_endt', ''))
        redcap_row['in_kmc_typ_new___1'] = convert_booleans(dhis2_row.get('in_kmc_typ_new___1', ''))
        redcap_row['in_kmc_typ_new___2'] = convert_booleans(dhis2_row.get('in_kmc_typ_new___2', ''))
        redcap_row['in_kmc_typ_new____1'] = convert_booleans(dhis2_row.get('in_kmc_typ_new____1', ''))
        redcap_row['in_kmc_typ_new____3'] = convert_booleans(dhis2_row.get('in_kmc_typ_new____3', ''))
        redcap_row['in_kmc_typ'] = dhis2_row.get('in_kmc_typ', '')
        
        redcap_row['in_o2_admin'] = dhis2_row.get('in_o2_admin', '')
        redcap_row['in_o2_num'] = dhis2_row.get('in_o2_num', '')
        for i in range(1, 4):
            redcap_row[f'in_o2_satur_doc_{i}'] = dhis2_row.get(f'in_o2_satur_doc_{i}', '')
            redcap_row[f'in_o2_satur_num_{i}'] = dhis2_row.get(f'in_o2_satur_num_{i}', '')
            redcap_row[f'in_o2_rss_doc_{i}'] = dhis2_row.get(f'in_o2_rss_doc_{i}', '')
            redcap_row[f'in_o2_rss_{i}'] = dhis2_row.get(f'in_o2_rss_{i}', '')
            redcap_row[f'in_o2_tm_doc_{i}___1'] = convert_booleans(dhis2_row.get(f'in_o2_tm_doc_{i}___1', ''))
            redcap_row[f'in_o2_tm_doc_{i}___2'] = convert_booleans(dhis2_row.get(f'in_o2_tm_doc_{i}___2', ''))
            redcap_row[f'in_o2_tm_doc_{i}____1'] = convert_booleans(dhis2_row.get(f'in_o2_tm_doc_{i}____1', ''))
            redcap_row[f'in_o2_tm_doc_{i}____3'] = convert_booleans(dhis2_row.get(f'in_o2_tm_doc_{i}____3', ''))
            redcap_row[f'in_o2_stdt_{i}'] = convert_dates(dhis2_row.get(f'in_o2_stdt_{i}', ''))
            redcap_row[f'in_o2_sttm_{i}'] = convert_time(dhis2_row.get(f'in_o2_sttm_{i}', ''))
            redcap_row[f'in_o2_endt_{i}'] = convert_dates(dhis2_row.get(f'in_o2_endt_{i}', ''))
            redcap_row[f'in_o2_entm_{i}'] = convert_time(dhis2_row.get(f'in_o2_entm_{i}', ''))
        
        redcap_row['in_cp_admin'] = dhis2_row.get('in_cp_admin', '')
        redcap_row['in_cp_num'] = dhis2_row.get('in_cp_num', '')
        redcap_row['in_cp_typ'] = dhis2_row.get('in_cp_typ', '')
        redcap_row['in_cp_typ_pwr'] = dhis2_row.get('in_cp_typ_pwr', '')
        for i in range(1, 4):
            redcap_row[f'in_cp_satur_doc_{i}'] = dhis2_row.get(f'in_cp_satur_doc_{i}', '')
            redcap_row[f'in_cp_satur_num_{i}'] = dhis2_row.get(f'in_cp_satur_num_{i}', '')
            redcap_row[f'in_cp_rss_doc_{i}'] = dhis2_row.get(f'in_cp_rss_doc_{i}', '')
            redcap_row[f'in_cp_rss_{i}'] = dhis2_row.get(f'in_cp_rss_{i}', '')
            redcap_row[f'in_cp_tm_doc_{i}___1'] = convert_booleans(dhis2_row.get(f'in_cp_tm_doc_{i}___1', ''))
            redcap_row[f'in_cp_tm_doc_{i}___2'] = convert_booleans(dhis2_row.get(f'in_cp_tm_doc_{i}___2', ''))
            redcap_row[f'in_cp_tm_doc_{i}____1'] = convert_booleans(dhis2_row.get(f'in_cp_tm_doc_{i}____1', ''))
            redcap_row[f'in_cp_tm_doc_{i}____3'] = convert_booleans(dhis2_row.get(f'in_cp_tm_doc_{i}____3', ''))
            redcap_row[f'in_cp_stdt_{i}'] = convert_dates(dhis2_row.get(f'in_cp_stdt_{i}', ''))
            redcap_row[f'in_cp_sttm_{i}'] = convert_time(dhis2_row.get(f'in_cp_sttm_{i}', ''))
            redcap_row[f'in_cp_endt_{i}'] = convert_dates(dhis2_row.get(f'in_cp_endt_{i}', ''))
            redcap_row[f'in_cp_entm_{i}'] = convert_time(dhis2_row.get(f'in_cp_entm_{i}', ''))
            redcap_row[f'in_cp_enwhy_{i}'] = dhis2_row.get(f'in_cp_enwhy_{i}', '')
        
        redcap_row['in_mv_admin'] = dhis2_row.get('in_mv_admin', '')
        redcap_row['in_mv_num'] = dhis2_row.get('in_mv_num', '')
        for i in range(1, 4):
            redcap_row[f'in_mv_satur_doc_{i}'] = dhis2_row.get(f'in_mv_satur_doc_{i}', '')
            redcap_row[f'in_mv_satur_num_{i}'] = dhis2_row.get(f'in_mv_satur_num_{i}', '')
            redcap_row[f'in_mv_rss_doc_{i}'] = dhis2_row.get(f'in_mv_rss_doc_{i}', '')
            redcap_row[f'in_mv_rss_{i}'] = dhis2_row.get(f'in_mv_rss_{i}', '')
            redcap_row[f'in_mv_tm_doc_{i}___1'] = convert_booleans(dhis2_row.get(f'in_mv_tm_doc_{i}___1', ''))
            redcap_row[f'in_mv_tm_doc_{i}___2'] = convert_booleans(dhis2_row.get(f'in_mv_tm_doc_{i}___2', ''))
            redcap_row[f'in_mv_tm_doc_{i}____1'] = convert_booleans(dhis2_row.get(f'in_mv_tm_doc_{i}____1', ''))
            redcap_row[f'in_mv_tm_doc_{i}____3'] = convert_booleans(dhis2_row.get(f'in_mv_tm_doc_{i}____3', ''))
            redcap_row[f'in_mv_stdt_{i}'] = convert_dates(dhis2_row.get(f'in_mv_stdt_{i}', ''))
            redcap_row[f'in_mv_sttm_{i}'] = convert_time(dhis2_row.get(f'in_mv_sttm_{i}', ''))
            redcap_row[f'in_mv_endt_{i}'] = convert_dates(dhis2_row.get(f'in_mv_endt_{i}', ''))
            redcap_row[f'in_mv_entm_{i}'] = convert_time(dhis2_row.get(f'in_mv_entm_{i}', ''))
        
        # Antibiotic treatment
        redcap_row['in_abx_admin'] = dhis2_row.get('in_abx_admin', '')
        redcap_row['in_abx_typ___1'] = convert_booleans(dhis2_row.get('in_abx_typ___1', ''))
        redcap_row['in_abx_typ___2'] = convert_booleans(dhis2_row.get('in_abx_typ___2', ''))
        redcap_row['in_abx_typ___3'] = convert_booleans(dhis2_row.get('in_abx_typ___3', ''))
        redcap_row['in_abx_typ___4'] = convert_booleans(dhis2_row.get('in_abx_typ___4', ''))
        redcap_row['in_abx_typ___5'] = convert_booleans(dhis2_row.get('in_abx_typ___5', ''))
        redcap_row['in_abx_typ___6'] = convert_booleans(dhis2_row.get('in_abx_typ___6', ''))
        redcap_row['in_abx_typ___7'] = convert_booleans(dhis2_row.get('in_abx_typ___7', ''))
        redcap_row['in_abx_typ___8'] = convert_booleans(dhis2_row.get('in_abx_typ___8', ''))
        redcap_row['in_abx_typ___9'] = convert_booleans(dhis2_row.get('in_abx_typ___9', ''))
        redcap_row['in_abx_typ___10'] = convert_booleans(dhis2_row.get('in_abx_typ___10', ''))
        redcap_row['in_abx_typ___11'] = convert_booleans(dhis2_row.get('in_abx_typ___11', ''))
        redcap_row['in_abx_typ___12'] = convert_booleans(dhis2_row.get('in_abx_typ___12', ''))
        redcap_row['in_abx_typ___13'] = convert_booleans(dhis2_row.get('in_abx_typ___13', ''))
        redcap_row['in_abx_typ___14'] = convert_booleans(dhis2_row.get('in_abx_typ___14', ''))
        redcap_row['in_abx_typ___15'] = convert_booleans(dhis2_row.get('in_abx_typ___15', ''))
        redcap_row['in_abx_typ___16'] = convert_booleans(dhis2_row.get('in_abx_typ___16', ''))
        redcap_row['in_abx_typ___17'] = convert_booleans(dhis2_row.get('in_abx_typ___17', ''))
        redcap_row['in_abx_typ___18'] = convert_booleans(dhis2_row.get('in_abx_typ___18', ''))
        redcap_row['in_abx_typ___19'] = convert_booleans(dhis2_row.get('in_abx_typ___19', ''))
        redcap_row['in_abx_typ___20'] = convert_booleans(dhis2_row.get('in_abx_typ___20', ''))
        redcap_row['in_abx_typ___21'] = convert_booleans(dhis2_row.get('in_abx_typ___21', ''))
        redcap_row['in_abx_typ____1'] = convert_booleans(dhis2_row.get('in_abx_typ____1', ''))
        redcap_row['in_abx_typ____3'] = convert_booleans(dhis2_row.get('in_abx_typ____3', ''))
        redcap_row['in_abx_typ___99'] = convert_booleans(dhis2_row.get('in_abx_typ___99', ''))
        
        # Antibiotic treatment details
        #antibiotics = ['gent', 'clox', 'cipro', 'cefx', 'amk', 'amox', 'bp', 
        #              'metro', 'cefo', 'mpen', 'vanc', 'crpn', 'ceflx', 'cefxm', 
        #              'cefz', 'clind', 'fluc', 'levo', 'pip', 'taz', 'oth']
        
        #for abx in antibiotics:
        #    redcap_row[f'in_abx_{abx}_dt'] = convert_dates(dhis2_row.get(f'in_abx_{abx}_dt', ''))
        #    redcap_row[f'in_abx_{abx}_tm_doc'] = dhis2_row.get(f'in_abx_{abx}_tm_doc', '')
        #    redcap_row[f'in_abx_{abx}_tm'] = convert_time(dhis2_row.get(f'in_abx_{abx}_tm', ''))
            
            
            #for i in range(1, 4):
            #redcap_row[f'in_abx_{abx}trt___1'] = convert_booleans(dhis2_row.get(f'in_abx_{abx}trt___1', ''))
            #redcap_row[f'in_abx_{abx}trt___2'] = convert_booleans(dhis2_row.get(f'in_abx_{abx}trt___2', ''))
            #redcap_row[f'in_abx_{abx}trt___3'] = convert_booleans(dhis2_row.get(f'in_abx_{abx}trt___3', ''))
            #redcap_row[f'in_abx_{abx}trt____1'] = convert_booleans(dhis2_row.get(f'in_abx_{abx}trt____1', ''))
            #redcap_row[f'in_abx_{abx}trt____3'] = convert_booleans(dhis2_row.get(f'in_abx_{abx}trt____3', ''))

        redcap_row[f'in_abx_gent_dt'] = convert_dates(dhis2_row.get('in_abx_gent_dt', ''))
        redcap_row[f'in_abx_gent_tm_doc'] = convert_boo(dhis2_row.get('in_abx_gent_tm_doc', ''))
        redcap_row[f'in_abx_gent_tm'] = convert_time(dhis2_row.get('in_abx_gent_tm', ''))
        redcap_row[f'in_abx_clox_dt'] = convert_dates(dhis2_row.get('in_abx_clox_dt', ''))
        redcap_row[f'in_abx_clox_tm_doc'] = convert_boo(dhis2_row.get('in_abx_clox_tm_doc', ''))
        redcap_row[f'in_abx_clox_tm'] = convert_time(dhis2_row.get('in_abx_clox_tm', '')) 
        redcap_row[f'in_abx_cipro_dt'] = convert_dates(dhis2_row.get('in_abx_cipro_dt', ''))
        redcap_row[f'in_abx_cipro_tm_doc'] = convert_boo(dhis2_row.get('in_abx_cipro_tm_doc', ''))
        redcap_row[f'in_abx_cipro_tm'] = convert_time(dhis2_row.get('in_abx_cipro_tm', '')) 
        redcap_row[f'in_abx_cefx_dt'] = convert_dates(dhis2_row.get('in_abx_cefx_dt', ''))
        redcap_row[f'in_abx_cefx_tm_doc'] = convert_boo(dhis2_row.get('in_abx_cefx_tm_doc', ''))
        redcap_row[f'in_abx_cefx_tm'] = convert_time(dhis2_row.get('in_abx_cefx_tm', '')) 
        redcap_row[f'in_abx_amk_dt'] = convert_dates(dhis2_row.get('in_abx_amk_dt', ''))
        redcap_row[f'in_abx_amk_tm_doc'] = convert_boo(dhis2_row.get('in_abx_amk_tm_doc', ''))
        redcap_row[f'in_abx_amk_tm'] = convert_time(dhis2_row.get('in_abx_amk_tm', '')) 
        redcap_row[f'in_abx_amox_dt'] = convert_dates(dhis2_row.get('in_abx_amox_dt', ''))
        redcap_row[f'in_abx_amox_tm_doc'] = convert_boo(dhis2_row.get('in_abx_amox_tm_doc', ''))
        redcap_row[f'in_abx_amox_tm'] = convert_time(dhis2_row.get('in_abx_amox_tm', '')) 
        redcap_row[f'in_abx_bp_dt'] = convert_dates(dhis2_row.get('in_abx_bp_dt', ''))
        redcap_row[f'in_abx_bp_tm_doc'] = convert_boo(dhis2_row.get('in_abx_bp_tm_doc', ''))
        redcap_row[f'in_abx_bp_tm'] = convert_time(dhis2_row.get('in_abx_bp_tm', '')) 
        redcap_row[f'in_abx_metro_dt'] = convert_dates(dhis2_row.get('in_abx_metro_dt', ''))
        redcap_row[f'in_abx_metro_tm_doc'] = convert_boo(dhis2_row.get('in_abx_metro_tm_doc', ''))
        redcap_row[f'in_abx_metro_tm'] = convert_time(dhis2_row.get('in_abx_metro_tm', '')) 
        redcap_row[f'in_abx_cefo_dt'] = convert_dates(dhis2_row.get('in_abx_cefo_dt', ''))
        redcap_row[f'in_abx_cefo_tm_doc'] = convert_boo(dhis2_row.get('in_abx_cefo_tm_doc', ''))
        redcap_row[f'in_abx_cefo_tm'] = convert_time(dhis2_row.get('in_abx_cefo_tm', ''))
        redcap_row[f'in_abx_mpen_dt'] = convert_dates(dhis2_row.get('in_abx_mpen_dt', ''))
        redcap_row[f'in_abx_mpen_tm_doc'] = convert_boo(dhis2_row.get('in_abx_mpen_tm_doc', ''))
        redcap_row[f'in_abx_mpen_tm'] = convert_time(dhis2_row.get('in_abx_mpen_tm', '')) 
        redcap_row[f'in_abx_vanc_dt'] = convert_dates(dhis2_row.get('in_abx_vanc_dt', ''))
        redcap_row[f'in_abx_vanc_tm_doc'] = convert_boo(dhis2_row.get('in_abx_vanc_tm_doc', ''))
        redcap_row[f'in_abx_vanc_tm'] = convert_time(dhis2_row.get('in_abx_vanc_tm', '')) 
        redcap_row[f'in_abx_crpn_dt'] = convert_dates(dhis2_row.get('in_abx_crpn_dt', ''))
        redcap_row[f'in_abx_crpn_tm_doc'] = convert_boo(dhis2_row.get('in_abx_crpn_tm_doc', ''))
        redcap_row[f'in_abx_crpn_tm'] = convert_time(dhis2_row.get('in_abx_crpn_tm', '')) 
        redcap_row[f'in_abx_ceflx_dt'] = convert_dates(dhis2_row.get('in_abx_ceflx_dt', ''))
        redcap_row[f'in_abx_ceflx_tm_doc'] = convert_boo(dhis2_row.get('in_abx_ceflx_tm_doc', ''))
        redcap_row[f'in_abx_ceflx_tm'] = convert_time(dhis2_row.get('in_abx_ceflx_tm', ''))  
        redcap_row[f'in_abx_cefxm_dt'] = convert_dates(dhis2_row.get('in_abx_cefxm_dt', ''))
        redcap_row[f'in_abx_cefxm_tm_doc'] = convert_boo(dhis2_row.get('in_abx_cefxm_tm_doc', ''))
        redcap_row[f'in_abx_cefxm_tm'] = convert_time(dhis2_row.get('in_abx_cefxm_tm', '')) 
        redcap_row[f'in_abx_cefz_dt'] = convert_dates(dhis2_row.get('in_abx_cefz_dt', ''))
        redcap_row[f'in_abx_cefz_tm_doc'] = convert_boo(dhis2_row.get('in_abx_cefz_tm_doc', ''))
        redcap_row[f'in_abx_cefz_tm'] = convert_time(dhis2_row.get('in_abx_cefz_tm', ''))
        redcap_row[f'in_abx_clind_dt'] = convert_dates(dhis2_row.get('in_abx_clind_dt', ''))
        redcap_row[f'in_abx_clind_tm_doc'] = convert_boo(dhis2_row.get('in_abx_clind_tm_doc', ''))
        redcap_row[f'in_abx_clind_tm'] = convert_time(dhis2_row.get('in_abx_clind_tm', ''))
        redcap_row[f'in_abx_fluc_dt'] = convert_dates(dhis2_row.get('in_abx_fluc_dt', ''))
        redcap_row[f'in_abx_fluc_tm_doc'] = convert_boo(dhis2_row.get('in_abx_fluc_tm_doc', ''))
        redcap_row[f'in_abx_fluc_tm'] = convert_time(dhis2_row.get('in_abx_fluc_tm', ''))
        redcap_row[f'in_abx_levo_dt'] = convert_dates(dhis2_row.get('in_abx_levo_dt', ''))
        redcap_row[f'in_abx_levo_tm_doc'] = convert_boo(dhis2_row.get('in_abx_levo_tm_doc', ''))
        redcap_row[f'in_abx_levo_tm'] = convert_time(dhis2_row.get('in_abx_levo_tm', ''))
        redcap_row[f'in_abx_pip_dt'] = convert_dates(dhis2_row.get('in_abx_pip_dt', ''))
        redcap_row[f'in_abx_pip_tm_doc'] = convert_boo(dhis2_row.get('in_abx_pip_tm_doc', ''))
        redcap_row[f'in_abx_pip_tm'] = convert_time(dhis2_row.get('in_abx_pip_tm', ''))
        redcap_row[f'in_abx_taz_dt'] = convert_dates(dhis2_row.get('in_abx_taz_dt', ''))
        redcap_row[f'in_abx_taz_tm_doc'] = convert_boo(dhis2_row.get('in_abx_taz_tm_doc', ''))
        redcap_row[f'in_abx_taz_tm'] = convert_time(dhis2_row.get('in_abx_taz_tm', ''))
        redcap_row[f'in_abx_oth_dt'] = convert_dates(dhis2_row.get('in_abx_oth_dt', ''))
        redcap_row[f'in_abx_oth_tm_doc'] = convert_boo(dhis2_row.get('in_abx_oth_tm_doc', ''))
        redcap_row[f'in_abx_oth_tm'] = convert_time(dhis2_row.get('in_abx_oth_tm', ''))


        redcap_row[f'in_abx_amo_dt'] = convert_dates(dhis2_row.get('in_abx_amo_dt', ''))
        redcap_row[f'in_abx_amp_tm_doc'] = convert_boo(dhis2_row.get('in_abx_amp_tm_doc', ''))
        redcap_row[f'in_abx_amp_tm'] = convert_time(dhis2_row.get('in_abx_amp_tm', ''))
        # Other treatments
        redcap_row['in_apn_trt'] = dhis2_row.get('in_apn_trt', '')
        redcap_row['in_apn_trt_typ_new___1'] = convert_booleans(dhis2_row.get('in_apn_trt_typ_new___1', ''))
        redcap_row['in_apn_trt_typ_new___2'] = convert_booleans(dhis2_row.get('in_apn_trt_typ_new___2', ''))
        redcap_row['in_apn_trt_typ_new___3'] = convert_booleans(dhis2_row.get('in_apn_trt_typ_new___3', ''))
        redcap_row['in_apn_trt_typ_new____1'] = convert_booleans(dhis2_row.get('in_apn_trt_typ_new____1', ''))
        redcap_row['in_apn_trt_typ_new____3'] = convert_booleans(dhis2_row.get('in_apn_trt_typ_new____3', ''))
        redcap_row['in_apn_trt_typ'] = dhis2_row.get('in_apn_trt_typ', '')
        redcap_row['in_apn_trt_oth'] = dhis2_row.get('in_apn_trt_oth', '')
        
        redcap_row['in_pt_admin'] = dhis2_row.get('in_pt_admin', '')
        redcap_row['in_pt_num'] = dhis2_row.get('in_pt_num', '')
        for i in range(1, 4):
            redcap_row[f'in_pt_stdt_{i}'] = convert_dates(dhis2_row.get(f'in_pt_stdt_{i}', ''))
            redcap_row[f'in_pt_endt_{i}'] = convert_dates(dhis2_row.get(f'in_pt_endt_{i}', ''))
        
        redcap_row['in_iv_admin'] = dhis2_row.get('in_iv_admin', '')
        redcap_row['in_iv_num'] = dhis2_row.get('in_iv_num', '')
        redcap_row['in_iv_stdt'] = convert_dates(dhis2_row.get('in_iv_stdt', ''))
        redcap_row['in_iv_endt'] = convert_dates(dhis2_row.get('in_iv_endt', ''))
        
        redcap_row['in_tx_admin'] = dhis2_row.get('in_tx_admin', '')
        redcap_row['in_tx_num'] = dhis2_row.get('in_tx_num', '')
        for i in range(1, 4):
            redcap_row[f'in_tx_dt_{i}'] = convert_dates(dhis2_row.get(f'in_tx_dt_{i}', ''))


    elif program_stage_uid == "VsVlpG1V2ub":
        #Observation and Nursing Care 2
        redcap_row['in_tmp_lo_doc'] = dhis2_row.get('in_tmp_lo_doc', '')
        redcap_row['in_tmp_lo_dt'] = convert_dates(dhis2_row.get('in_tmp_lo_dt', ''))
        redcap_row['in_tmp_lo_tm_doc'] = convert_booleans(dhis2_row.get('in_tmp_lo_tm_doc', ''))
        redcap_row['in_tmp_lo_tm'] = convert_time(dhis2_row.get('in_tmp_lo_tm', ''))
        redcap_row['in_tmp_lo_typ'] = dhis2_row.get('in_tmp_lo_typ', '')
        redcap_row['in_tmp_lo_cel'] = convert_temperature(dhis2_row.get('in_tmp_lo_cel', ''))
        redcap_row['in_tmp_lo_fah'] = dhis2_row.get('in_tmp_lo_fah', '')
        redcap_row['in_tmp_lo_unk'] = dhis2_row.get('in_tmp_lo_unk', '')
        
        redcap_row['in_tmp_hi_doc'] = dhis2_row.get('in_tmp_hi_doc', '')
        redcap_row['in_tmp_hi_dt'] = convert_dates(dhis2_row.get('in_tmp_hi_dt', ''))
        redcap_row['in_tmp_hi_tm_doc'] = convert_booleans(dhis2_row.get('in_tmp_hi_tm_doc', ''))
        redcap_row['in_tmp_hi_tm'] = convert_time(dhis2_row.get('in_tmp_hi_tm', ''))
        redcap_row['in_tmp_hi_typ'] = dhis2_row.get('in_tmp_hi_typ', '')
        redcap_row['in_tmp_hi_cel'] = convert_temperature(dhis2_row.get('in_tmp_hi_cel', ''))
        redcap_row['in_tmp_hi_fah'] = dhis2_row.get('in_tmp_hi_fah', '')
        redcap_row['in_tmp_hi_unk'] = dhis2_row.get('in_tmp_hi_unk', '')
        
        redcap_row['in_o2_lo_doc'] = dhis2_row.get('in_o2_lo_doc', '')
        redcap_row['in_o2_lo'] = dhis2_row.get('in_o2_lo', '')
        redcap_row['in_o2_hi_doc'] = dhis2_row.get('in_o2_hi_doc', '')
        redcap_row['in_o2_hi'] = dhis2_row.get('in_o2_hi', '')
        
        redcap_row['in_bmlk_stdt'] = convert_dates(dhis2_row.get('in_bmlk_stdt', ''))
        redcap_row['in_fed_stdt'] = convert_dates(dhis2_row.get('in_fed_stdt', ''))
        redcap_row['in_fed_dis'] = dhis2_row.get('in_fed_dis', '')
        
        redcap_row['in_glu_lo_doc'] = dhis2_row.get('in_glu_lo_doc', '')
        redcap_row['in_glu_lo_typ'] = dhis2_row.get('in_glu_lo_typ', '')
        redcap_row['in_glu_lo_mmol'] = dhis2_row.get('in_glu_lo_mmol', '')
        redcap_row['in_glu_lo_mgdl'] = dhis2_row.get('in_glu_lo_mgdl', '')
        redcap_row['in_glu_lo_unk'] = dhis2_row.get('in_glu_lo_unk', '')
        
        redcap_row['in_glu_hi_doc'] = dhis2_row.get('in_glu_hi_doc', '')
        redcap_row['in_glu_hi_typ'] = dhis2_row.get('in_glu_hi_typ', '')
        redcap_row['in_glu_hi_mmol'] = dhis2_row.get('in_glu_hi_mmol', '')
        redcap_row['in_glu_hi_mgdl'] = dhis2_row.get('in_glu_hi_mgdl', '')
        redcap_row['in_glu_hi_unk'] = dhis2_row.get('in_glu_hi_unk', '')
        
        redcap_row['in_bil_doc'] = dhis2_row.get('in_bil_doc', '')
        redcap_row['in_bil_hi_doc'] = dhis2_row.get('in_bil_hi_doc', '')
        redcap_row['in_bil_hi'] = dhis2_row.get('in_bil_hi', '')
        redcap_row['in_bil_meth'] = dhis2_row.get('in_bil_meth', '')
        
        redcap_row['in_seiz_doc'] = dhis2_row.get('in_seiz_doc', '')
        redcap_row['in_aed_admin'] = dhis2_row.get('in_aed_admin', '')
        redcap_row['in_aed_typ_new___1'] = convert_booleans(dhis2_row.get('in_aed_typ_new___1', ''))
        redcap_row['in_aed_typ_new___2'] = convert_booleans(dhis2_row.get('in_aed_typ_new___2', ''))
        redcap_row['in_aed_typ_new___3'] = convert_booleans(dhis2_row.get('in_aed_typ_new___3', ''))
        redcap_row['in_aed_typ_new___4'] = convert_booleans(dhis2_row.get('in_aed_typ_new___4', ''))
        redcap_row['in_aed_typ_new____1'] = convert_booleans(dhis2_row.get('in_aed_typ_new____1', ''))
        redcap_row['in_aed_typ_new____3'] = convert_booleans(dhis2_row.get('in_aed_typ_new____3', ''))
        redcap_row['in_aed_typ'] = dhis2_row.get('in_aed_typ', '')


    elif program_stage_uid == "TOicTEwzSGj":
        #Discharge
        redcap_row['in_dis_stat'] = dhis2_row.get('in_dis_stat', '')
        redcap_row['in_dis_otcm'] = dhis2_row.get('in_dis_otcm', '')
        redcap_row['in_dis_ref'] = dhis2_row.get('in_dis_ref', '')
        redcap_row['in_dis_dod'] = convert_dates(dhis2_row.get('in_dis_dod', ''))
        redcap_row['in_dis_tod_doc'] = dhis2_row.get('in_dis_tod_doc', '')
        redcap_row['in_dis_tod'] = convert_time(dhis2_row.get('in_dis_tod', ''))
        redcap_row['in_dis_wt_doc'] = dhis2_row.get('in_dis_wt_doc', '')
        redcap_row['in_dis_wt'] = dhis2_row.get('in_dis_wt', '')
        redcap_row['in_fu_app'] = dhis2_row.get('in_fu_app', '')
        redcap_row['in_fu_loc'] = dhis2_row.get('in_fu_loc', '')
        redcap_row['in_fu_loc_new'] = dhis2_row.get('in_fu_loc_new', '')
        redcap_row['in_fu_oth'] = dhis2_row.get('in_fu_oth', '')
        redcap_row['in_fu_why_y'] = dhis2_row.get('in_fu_why_y', '')
        redcap_row['in_fu_why_n'] = dhis2_row.get('in_fu_why_n', '')
        
        # Diagnosis fields
        for i in range(1, 4):
            redcap_row[f'in_dx_prim_{i}'] = dhis2_row.get(f'in_dx_prim_{i}', '')
            redcap_row[f'in_dx_prim_cong_{i}'] = dhis2_row.get(f'in_dx_prim_cong_{i}', '')
            redcap_row[f'in_dx_prim_othcong_{i}'] = dhis2_row.get(f'in_dx_prim_othcong_{i}', '')
            redcap_row[f'in_dx_prim_prem_{i}'] = dhis2_row.get(f'in_dx_prim_prem_{i}', '')
            redcap_row[f'in_dx_prim_othprem_{i}'] = dhis2_row.get(f'in_dx_prim_othprem_{i}', '')
            redcap_row[f'in_dx_prim_if_{i}'] = dhis2_row.get(f'in_dx_prim_if_{i}', '')
            redcap_row[f'in_dx_prim_othif_{i}'] = dhis2_row.get(f'in_dx_prim_othif_{i}', '')
            redcap_row[f'in_dx_prim_if_org_{i}'] = dhis2_row.get(f'in_dx_prim_if_org_{i}', '')
            redcap_row[f'in_dx_prim_if_org_oth_{i}'] = dhis2_row.get(f'in_dx_prim_if_org_oth_{i}', '')
            redcap_row[f'in_dx_prim_if_org_nam_{i}'] = dhis2_row.get(f'in_dx_prim_if_org_nam_{i}', '')
            redcap_row[f'in_dx_prim_aqif_{i}'] = dhis2_row.get(f'in_dx_prim_aqif_{i}', '')
            redcap_row[f'in_dx_prim_intp_{i}'] = dhis2_row.get(f'in_dx_prim_intp_{i}', '')
            redcap_row[f'in_dx_prim_othintp_{i}'] = dhis2_row.get(f'in_dx_prim_othintp_{i}', '')
            redcap_row[f'in_dx_prim_jnd_{i}'] = dhis2_row.get(f'in_dx_prim_jnd_{i}', '')
            redcap_row[f'in_dx_prim_oth_{i}'] = dhis2_row.get(f'in_dx_prim_oth_{i}', '')
            
            redcap_row[f'in_dx_sec_{i}'] = dhis2_row.get(f'in_dx_sec_{i}', '')
            redcap_row[f'in_dx_sec_lobwt_{i}'] = dhis2_row.get(f'in_dx_sec_lobwt_{i}', '')
            redcap_row[f'in_dx_sec_cong_{i}'] = dhis2_row.get(f'in_dx_sec_cong_{i}', '')
            redcap_row[f'in_dx_sec_othcong_{i}'] = dhis2_row.get(f'in_dx_sec_othcong_{i}', '')
            redcap_row[f'in_dx_sec_prem_{i}'] = dhis2_row.get(f'in_dx_sec_prem_{i}', '')
            redcap_row[f'in_dx_sec_othprem_{i}'] = dhis2_row.get(f'in_dx_sec_othprem_{i}', '')
            redcap_row[f'in_dx_sec_if_{i}'] = dhis2_row.get(f'in_dx_sec_if_{i}', '')
            redcap_row[f'in_dx_sec_othif_{i}'] = dhis2_row.get(f'in_dx_sec_othif_{i}', '')
            redcap_row[f'in_dx_sec_if_org_{i}'] = dhis2_row.get(f'in_dx_sec_if_org_{i}', '')
            redcap_row[f'in_dx_sec_if_org_oth_{i}'] = dhis2_row.get(f'in_dx_sec_if_org_oth_{i}', '')
            redcap_row[f'in_dx_sec_if_org_nam_{i}'] = dhis2_row.get(f'in_dx_sec_if_org_nam_{i}', '')
            redcap_row[f'in_dx_sec_aqif_{i}'] = dhis2_row.get(f'in_dx_sec_aqif_{i}', '')
            redcap_row[f'in_dx_sec_intp_{i}'] = dhis2_row.get(f'in_dx_sec_intp_{i}', '')
            redcap_row[f'in_dx_sec_othintp_{i}'] = dhis2_row.get(f'in_dx_sec_othintp_{i}', '')
            redcap_row[f'in_dx_sec_jnd_{i}'] = dhis2_row.get(f'in_dx_sec_jnd_{i}', '')
            redcap_row[f'in_dx_sec_oth_{i}'] = dhis2_row.get(f'in_dx_sec_oth_{i}', '')


    # Map DHIS2 event status -> REDCap form complete field
    status_val = str(dhis2_row.get('status', '')).upper()

    if program_stage_uid == "l39SlVGlQGs":  # Admission stage
        redcap_row['admission_information_complete'] = 2 if status_val == "COMPLETED" else 0

    elif program_stage_uid == "UK7jsDbVpj6":  # Maternal & Infant
        redcap_row['maternal_birth_and_infant_details_complete'] = 2 if status_val == "COMPLETED" else 0

    elif program_stage_uid == "j0HI2eJjvbj":  # Observations 1
        redcap_row['observations_and_nursing_care_1_complete'] = 2 if status_val == "COMPLETED" else 0

    elif program_stage_uid == "aCrttmnx7FI":  # Microbiology
        redcap_row['microbiology_and_labs_complete'] = 2 if status_val == "COMPLETED" else 0

    elif program_stage_uid == "ed8ErpgTCwx":  # Interventions
        redcap_row['interventions_complete'] = 2 if status_val == "COMPLETED" else 0

    elif program_stage_uid == "VsVlpG1V2ub":  # Observations 2
        redcap_row['observations_and_nursing_care_2_complete'] = 2 if status_val == "COMPLETED" else 0

    elif program_stage_uid == "TOicTEwzSGj":  # Discharge
        redcap_row['discharge_and_final_diagnosis_complete'] = 2 if status_val == "COMPLETED" else 0


    return redcap_row

def transform_to_redcap(dhis2_df: pd.DataFrame, redcap_template_headers: List[str], log) -> pd.DataFrame:
    """
    Build one REDCap row per in_recid, applying stage-by-stage mapping
    in the order you specified. Keeps TEA variables (e.g., in_recid) intact.
    """
    if RECORD_ID_VAR not in dhis2_df.columns:
        raise ValueError(f"DHIS2 dataset does not contain '{RECORD_ID_VAR}'. Ensure TEA code is '{RECORD_ID_VAR}'.")

    if 'program_stage_uid' not in dhis2_df.columns:
        raise ValueError("DHIS2 dataset does not contain 'program_stage_uid'. Check earlier steps.")

    order = [
        "l39SlVGlQGs",  # Admission
        "UK7jsDbVpj6",  # Maternal & Infant
        "j0HI2eJjvbj",  # Observations 1
        "aCrttmnx7FI",  # Microbiology
        "ed8ErpgTCwx",  # Interventions
        "VsVlpG1V2ub",  # Observations 2
        "TOicTEwzSGj",  # Discharge
    ]

    
    if RECORD_ID_VAR not in redcap_template_headers:
        redcap_template_headers = list(redcap_template_headers) + [RECORD_ID_VAR]

    redcap_data = pd.DataFrame(columns=redcap_template_headers)
    unique_ids = dhis2_df[RECORD_ID_VAR].dropna().astype(str).str.strip()
    unique_ids = unique_ids[unique_ids != ""].unique()

    for recid in unique_ids:
        instance_rows = dhis2_df[dhis2_df[RECORD_ID_VAR].astype(str) == recid]
        redcap_row = {col: '' for col in redcap_template_headers}
        # --- Build new recid with facility prefix ---
        facility_code = ''
        try:
            admission_rows = instance_rows[instance_rows['program_stage_uid'] == "l39SlVGlQGs"]
            if not admission_rows.empty:
                adm_row = admission_rows.iloc[0]
                raw_fac = adm_row.get('in_facid', '') or adm_row.get('org_unit', '') or ''
                facility_code = resolve_facility(str(raw_fac), FACILITY_MAP)
        except Exception:
            facility_code = ''

        try:
            new_recid = convert_record_id_with_facility(str(recid), facility_code)
        except Exception:
            new_recid = str(recid)

        redcap_row[RECORD_ID_VAR] = new_recid


        # apply mapping in order
        for stage_uid in order:
            rows = instance_rows[instance_rows['program_stage_uid'] == stage_uid]
            for _, r in rows.iterrows():
                redcap_row = map_program_stage_to_columns(r, redcap_row, stage_uid, redcap_template_headers)

        redcap_data = pd.concat([redcap_data, pd.DataFrame([redcap_row])], ignore_index=True)


    # Drop unnamed column if present
    if 'Unnamed: 929' in redcap_data.columns:
        redcap_data = redcap_data.drop(columns=['Unnamed: 929'])

    # Ensure string types for safe JSON
    redcap_data = redcap_data.replace({np.nan: ''})
    for col in redcap_data.columns:
        if redcap_data[col].dtype == 'object':
            redcap_data[col] = redcap_data[col].astype(str)

    
    empty_id = redcap_data[redcap_data[RECORD_ID_VAR].astype(str).str.strip() == ""]
    if not empty_id.empty:
        sample = empty_id.head(5)[[RECORD_ID_VAR]]
        raise ValueError(f"Found {len(empty_id)} rows with empty '{RECORD_ID_VAR}'. Examples: {sample.to_dict(orient='records')}")

    log(f"Transformed to REDCap shape: {redcap_data.shape[0]} rows x {redcap_data.shape[1]} columns")
    return redcap_data




def build_dhis2_rows_for_transform(
    teis: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    base_api: str,
    sess: requests.Session,
    log
) -> pd.DataFrame:
   
    records = []
    for idx, tei in enumerate(teis, start=1):
        tei_uid = tei.get('trackedEntityInstance')
        log(f"Processing TEI {idx}/{len(teis)}: {tei_uid}")
        base_record = {
            'tei_id': tei_uid,
            'org_unit': tei.get('orgUnit', ''),
            'created': tei.get('created', ''),
            'last_updated': tei.get('lastUpdated', '')
        }

        # attributes -> use TEA codes as columns (like your export)
        for attr in tei.get('attributes', []):
            attr_id = attr.get('attribute')
            tea_info = metadata['tea_map'].get(attr_id, {'code': f"attr_{attr_id}", 'name': f"Attribute {attr_id}"})
            base_record[tea_info['code']] = attr.get('value', '')

        # Pull events for TEI
        events = fetch_tei_events(base_api, sess, tei_uid, log)
        if not events:

            event_record = base_record.copy()
            event_record.update({
                'event_id': '',
                'program_stage_uid': '',
                'program_stage': '',
                'event_date': '',
                'status': ''
            })
            records.append(event_record)
            continue

        for ev in events:
            event_record = base_record.copy()
            ps_uid = ev.get('programStage', '')
            stage_info = metadata['ps_map'].get(ps_uid, {'code': f"stage_{ps_uid}", 'name': f"Stage {ps_uid}"})
            event_record.update({
                'event_id': ev.get('event', ''),
                'program_stage_uid': ps_uid,
                'program_stage': stage_info['code'],
                'event_date': ev.get('eventDate', ''),
                'status': ev.get('status', '')
            })
            for dv in ev.get('dataValues', []):
                de_id = dv.get('dataElement')
                de_info = metadata['de_map'].get(de_id, {'code': f"de_{de_id}", 'name': f"DE {de_id}"})
                event_record[de_info['code']] = dv.get('value', '')
            records.append(event_record)

    if not records:
        return pd.DataFrame([])

    df = pd.DataFrame(records)

    # bring common columns to front (optional)
    front = ['tei_id', 'org_unit', 'created', 'last_updated', 'event_id', 'program_stage_uid', 'program_stage', 'event_date', 'status']
    others = [c for c in df.columns if c not in front]
    df = df[front + others]
    return df


# REDCap uploader

def _sanitize_for_json(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure strict JSON (no NaN/Infinity) and strings where appropriate."""
    clean = []
    for rec in records:
        new_rec = {}
        for k, v in rec.items():
            if v is None or (isinstance(v, float) and (np.isnan(v))):
                new_rec[k] = ""
            elif isinstance(v, (list, dict)):
                new_rec[k] = json.dumps(v, ensure_ascii=False)
            else:
                new_rec[k] = v
        clean.append(new_rec)
    return clean

def upload_to_redcap(redcap_api_url: str, api_token: str, df: pd.DataFrame, log, record_id_var: str = RECORD_ID_VAR) -> Tuple[bool, str]:
    
    if df.empty:
        return False, "No data to upload."

    if record_id_var not in df.columns:
        return False, f"REDCap upload aborted: record id field '{record_id_var}' missing from dataframe."

    # Preflight: ensure non-empty record ids
    empties = df[df[record_id_var].astype(str).str.strip() == ""]
    if not empties.empty:
        return False, f"REDCap upload aborted: {len(empties)} rows have empty '{record_id_var}'."

    # Prepare records array: one dict per row
    records = df.to_dict(orient='records')

    # Strict JSON: remove NaN/None and complex types
    records = _sanitize_for_json(records)

    total = len(records)
    log(f"Uploading {total} REDCap rows in batches of {BATCH_SIZE_REDCAP} … (using '{record_id_var}' as record id)")

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    ok_count = 0
    for i in range(0, total, BATCH_SIZE_REDCAP):
        chunk = records[i:i+BATCH_SIZE_REDCAP]
        try:
            payload = {
                "token": api_token,
                "content": "record",
                "format": "json",
                "type": "flat",
                "overwriteBehavior": "normal",
                # DO NOT send forceAutoNumber — keep explicit record IDs
                "data": json.dumps(chunk, ensure_ascii=False, allow_nan=False),
                "returnContent": "count",
                "returnFormat": "json"
            }
        except ValueError as ve:
            return False, f"JSON serialization error (NaN/Inf present): {ve}"

        try:
            r = requests.post(redcap_api_url, data=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                body = r.text[:800]
                # Try to extract structured error if present
                try:
                    j = r.json()
                    if isinstance(j, dict) and "error" in j:
                        body = j["error"]
                except Exception:
                    pass
                log(f"REDCap HTTP {r.status_code}: {body}")
                return False, f"REDCap upload failed with HTTP {r.status_code}: {body}"
            resp = r.json()
            cnt = resp.get("count", 0) if isinstance(resp, dict) else 0
            ok_count += cnt
            log(f"Batch {(i//BATCH_SIZE_REDCAP)+1}: uploaded {cnt} records.")
        except Exception as e:
            return False, f"REDCap upload error: {e}"

    return True, f"Uploaded {ok_count} records to REDCap."


def run_pipeline(
    dhis_url: str,
    dhis_user: str,
    dhis_pass: str,
    redcap_url: str,
    redcap_token: str,
    org_unit: str,
    template_path: str = "",
    start_date: str = "",
    end_date: str = "",
    log=None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if log is None:
        log = lambda msg: None

    dhis_url = (dhis_url or "").strip()
    dhis_user = (dhis_user or "").strip()
    dhis_pass = (dhis_pass or "").strip()
    redcap_url = (redcap_url or "").strip()
    redcap_token = (redcap_token or "").strip()
    org_unit = (org_unit or "").strip()
    template_path = (template_path or "").strip()
    start_date = (start_date or "").strip()
    end_date = (end_date or "").strip()

    if not all([dhis_url, dhis_user, dhis_pass, redcap_url, redcap_token]):
        raise ValueError("Please fill all required DHIS2 and REDCap fields.")
    if not org_unit:
        raise ValueError("Please provide and select an Org Unit.")

    base = _normalize_base(dhis_url)
    if base.endswith("/api"):
        base_api = base
        base_root = base[:-4]
    else:
        base_root = base
        base_api = _join(base_root, "api")

    sess = requests.Session()
    sess.auth = HTTPBasicAuth(dhis_user, dhis_pass)
    sess.headers.update({'Content-Type': 'application/json'})

    # Test DHIS2 connectivity
    info_url = _join(base_api, "system/info")
    r = fetch_with_retry(sess, info_url, log=log)
    if not r:
        raise RuntimeError("Failed to connect to DHIS2. Check URL/credentials.")
    log(f"DHIS2 OK: {info_url}")

    pid = PROGRAM_ID
    log(f"\n=== Program {pid} ===")
    md = fetch_metadata(base_api, sess, pid, log)

    # validate formats
    if not _validate_date_str(start_date):
        raise ValueError("Start date must be YYYY-MM-DD or blank.")
    if not _validate_date_str(end_date):
        raise ValueError("End date must be YYYY-MM-DD or blank.")

    # validate order
    if start_date and end_date:
        if datetime.strptime(start_date, "%Y-%m-%d") > datetime.strptime(end_date, "%Y-%m-%d"):
            raise ValueError("Start date must be on or before End date.")

    # call fetch_teis with date range
    teis = fetch_teis(base_api, sess, pid, org_unit, log, start_date=start_date, end_date=end_date)
    log(f"TEIs found: {len(teis)}")

    if not teis:
        log("No TEIs found to transform/upload.")
        return {
            "status": "success",
            "message": "No TEIs found to transform/upload.",
            "records": 0,
            "transformed_df": pd.DataFrame(),
        }

    df_events = build_dhis2_rows_for_transform(teis, md, base_api, sess, log)
    if df_events.empty:
        log("No events built from TEIs.")
        return {
            "status": "success",
            "message": "No events built from TEIs.",
            "records": 0,
            "transformed_df": pd.DataFrame(),
        }

    # Determine headers
    template_headers: Optional[List[str]] = None
    if template_path:
        try:
            hdrs = pd.read_csv(template_path, nrows=0).columns.tolist()
            template_headers = hdrs
            log(f"Loaded REDCap template with {len(hdrs)} columns.")
        except Exception as e:
            log(f"Template load failed; will infer headers from data. Error: {e}")

    if template_headers is None:
        template_headers = sorted(set(df_events.columns.tolist() + [RECORD_ID_VAR]))

    # Transform using mapping
    redcap_df = transform_to_redcap(df_events, template_headers, log)

    if dry_run:
        log(f"DRY RUN: {len(redcap_df)} records transformed (upload skipped).")
        return {
            "status": "success",
            "message": f"DRY RUN: {len(redcap_df)} records transformed.",
            "records": len(redcap_df),
            "transformed_df": redcap_df,
        }

    # Upload to REDCap
    ok, msg = upload_to_redcap(redcap_url, redcap_token, redcap_df, log, record_id_var=RECORD_ID_VAR)
    if not ok:
        raise RuntimeError(f"REDCap Upload Failed: {msg}")

    return {
        "status": "success",
        "message": msg,
        "records": len(redcap_df),
        "transformed_df": redcap_df,
    }

