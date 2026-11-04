#!/usr/bin/env python3
# import_dhis2_fixed.py
# Fixed version - with data validation and proper date formatting

import requests
import json
import datetime
import pandas as pd
from pathlib import Path
from requests.auth import HTTPBasicAuth
import re
import argparse
import sys
from typing import Optional, Dict, Any, List, Set
import logging
try:
    import chardet
except ImportError:
    chardet = None

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ------------------------
# HTTP helpers
# ------------------------

def http_get(url: str, auth, params=None, timeout=30):
    """Enhanced GET with better error handling"""
    try:
        r = requests.get(url, auth=auth, params=params or {}, 
                        headers={"Accept": "application/json"}, timeout=timeout)
        if r.status_code == 401:
            raise Exception("Unauthorized (401). Check DHIS2 URL, username, or password.")
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP GET failed for {url}: {e}")
        raise

def http_post(url: str, auth, payload: dict, timeout=120):
    """Enhanced POST with better error handling"""
    full = f"{url}?strategy=CREATE_AND_UPDATE" if "?" not in url else f"{url}&strategy=CREATE_AND_UPDATE"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        r = requests.post(full, auth=auth, headers=headers, 
                         data=json.dumps(payload), timeout=timeout)
        body = r.json() if r.text else {"raw": "No response body"}
        if not r.ok:
            error_detail = json.dumps(body, indent=2) if isinstance(body, dict) else str(body)
            raise requests.HTTPError(f"HTTP {r.status_code}: {error_detail}")
        return r, body
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP POST failed: {e}")
        raise

# ------------------------
# Utility functions
# ------------------------

def detect_encoding(file_path: str) -> str:
    """Detect file encoding"""
    if chardet is not None:
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                result = chardet.detect(raw_data)
                return result.get('encoding') or 'utf-8'
        except Exception:
            pass
    return 'utf-8'

def read_csv_safe(file_path: str) -> pd.DataFrame:
    """Read CSV with automatic encoding detection"""
    try:
        # First try UTF-8
        return pd.read_csv(file_path, dtype=str, keep_default_na=False, encoding='utf-8')
    except UnicodeDecodeError:
        # If UTF-8 fails, detect encoding
        encoding = detect_encoding(file_path)
        logger.info(f"Detected encoding: {encoding}")
        try:
            return pd.read_csv(file_path, dtype=str, keep_default_na=False, encoding=encoding)
        except:
            # Last resort: try with latin-1
            return pd.read_csv(file_path, dtype=str, keep_default_na=False, encoding='latin-1')

def safe_str(v):
    """Safely convert value to string, handling NaN and None"""
    if v is None:
        return None
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s != "" and s.lower() not in ["nan", "none", "null"] else None

def format_dhis2_date(date_str: str) -> Optional[str]:
    """Convert various date formats to DHIS2 expected format (YYYY-MM-DD)"""
    if not date_str:
        return None
    
    date_str = str(date_str).strip()
    
    # Handle Excel serial dates (like 45678)
    if date_str.isdigit() and len(date_str) == 5:
        try:
            # Convert Excel serial date to datetime
            excel_epoch = datetime.datetime(1899, 12, 30)
            delta = datetime.timedelta(days=int(date_str))
            date_obj = excel_epoch + delta
            return date_obj.strftime("%Y-%m-%d")
        except:
            pass
    
    # Try common date formats
    patterns = [
        (r'(\d{4})-(\d{1,2})-(\d{1,2})', lambda m: f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"),  # 2026-2-17
        (r'(\d{1,2})/(\d{1,2})/(\d{4})', lambda m: f"{int(m[3]):04d}-{int(m[2]):02d}-{int(m[1]):02d}"),  # 17/02/2026
        (r'(\d{1,2})-(\d{1,2})-(\d{4})', lambda m: f"{int(m[3]):04d}-{int(m[2]):02d}-{int(m[1]):02d}"),  # 17-02-2026
        (r'(\d{4})(\d{2})(\d{2})', lambda m: f"{m[1]}-{m[2]}-{m[3]}"),  # 20260217
    ]
    
    for pattern, formatter in patterns:
        match = re.match(pattern, date_str)
        if match:
            try:
                return formatter(match.groups())
            except:
                pass
    
    # Try parsing with pandas
    try:
        date_obj = pd.to_datetime(date_str, errors='coerce')
        if pd.notna(date_obj):
            return date_obj.strftime("%Y-%m-%d")
    except:
        pass
    
    # If it contains time part, extract just the date
    if 'T' in date_str:
        date_part = date_str.split('T')[0]
        if re.match(r'\d{4}-\d{2}-\d{2}', date_part):
            return date_part
    
    logger.warning(f"Could not parse date: '{date_str}'")
    return date_str  # Return original if can't parse

def to_date_or_today(v):
    """Convert to date string or return today"""
    s = safe_str(v)
    if s:
        formatted = format_dhis2_date(s)
        if formatted:
            return formatted
    return datetime.datetime.now().strftime("%Y-%m-%d")

def normalize_stage_name(name: str) -> str:
    """Normalize program stage name for matching"""
    if not name:
        return ""
    return re.sub(r'\s+', ' ', name.strip().lower())

def normalize_for_comparison(s: str) -> str:
    """Normalize string for comparison by removing extra spaces and lowercasing"""
    if not s:
        return ""
    return re.sub(r'\s+', ' ', str(s).strip().lower())

def clean_option_value(value: str, option_map: dict) -> str:
    """Clean option value to match DHIS2 expected format"""
    if not value or not option_map:
        return value
    
    value = str(value).strip()
    
    # Direct match
    if value in option_map:
        return option_map[value]
    
    # Try case-insensitive match
    value_lower = value.lower()
    for opt_name, opt_code in option_map.items():
        if opt_name.lower() == value_lower:
            return opt_code
    
    # Try partial match
    for opt_name, opt_code in option_map.items():
        if value_lower in opt_name.lower() or opt_name.lower() in value_lower:
            logger.debug(f"Partial option match: '{value}' -> '{opt_name}' = '{opt_code}'")
            return opt_code
    
    return value

# ------------------------
# Metadata cache class
# ------------------------

class DHIS2Metadata:
    """Cache and manage DHIS2 metadata"""
    
    def __init__(self, base_api: str, auth):
        if not base_api or not str(base_api).strip():
            raise ValueError("DHIS2 API URL is required.")
        if not auth:
            raise ValueError("DHIS2 authentication credentials are required.")
        self.base_api = base_api
        self.auth = auth
        self.teas: Dict[str, Dict] = {}
        self.des: Dict[str, Dict] = {}
        self.programs: Dict[str, Dict] = {}
        self.program_stages: Dict[str, Dict] = {}
        self.org_units: Dict[str, str] = {}
        self.org_unit_ids: Set[str] = set()
        self.program_stage_lookup: Dict[str, str] = {}
        self.data_elements_by_stage: Dict[str, Set[str]] = {}  # program_stage_id -> set of data element IDs
        
    def fetch_all(self):
        """Fetch all necessary metadata"""
        logger.info("Fetching metadata from DHIS2...")
        
        # Fetch Tracked Entity Attributes
        teas_data = http_get(f"{self.base_api}/trackedEntityAttributes.json", self.auth,
                           {"fields": "id,name,displayName,valueType,optionSet[id,name,options[id,code,name,displayName]]", 
                            "paging": "false"})
        for a in teas_data.get("trackedEntityAttributes", []):
            option_set = a.get("optionSet") or {}
            options = option_set.get("options", []) if option_set else []
            opt_map = {}
            for opt in options:
                opt_map[opt.get("name")] = opt.get("code")
                opt_map[opt.get("code")] = opt.get("code")
                opt_map[opt.get("displayName")] = opt.get("code")
            
            self.teas[a["id"]] = {
                "id": a["id"],
                "name": a.get("name") or a.get("displayName") or "",
                "displayName": a.get("displayName") or "",
                "valueType": a.get("valueType", "TEXT"),
                "options": opt_map
            }
        
        # Fetch Data Elements with their program stage associations
        des_data = http_get(f"{self.base_api}/dataElements.json", self.auth,
                          {"fields": "id,name,displayName,valueType,optionSet[id,name,options[id,code,name,displayName]],programStages[id]", 
                           "paging": "false"})
        for de in des_data.get("dataElements", []):
            option_set = de.get("optionSet") or {}
            options = option_set.get("options", []) if option_set else []
            opt_map = {}
            for opt in options:
                opt_map[opt.get("name")] = opt.get("code")
                opt_map[opt.get("code")] = opt.get("code")
                opt_map[opt.get("displayName")] = opt.get("code")
            
            de_id = de["id"]
            self.des[de_id] = {
                "id": de_id,
                "name": de.get("name") or de.get("displayName") or "",
                "displayName": de.get("displayName") or "",
                "valueType": de.get("valueType", "TEXT"),
                "options": opt_map
            }
            
            # Track which program stages this DE belongs to
            for ps in de.get("programStages", []):
                ps_id = ps["id"]
                if ps_id not in self.data_elements_by_stage:
                    self.data_elements_by_stage[ps_id] = set()
                self.data_elements_by_stage[ps_id].add(de_id)
        
        # Fetch Programs with their stages and data elements
        programs_data = http_get(f"{self.base_api}/programs.json", self.auth,
                               {"fields": "id,displayName,name,trackedEntityType[id],"
                                "programStages[id,displayName,name,programStageDataElements[dataElement[id]]]", 
                                "paging": "false"})
        
        logger.info("Building program stage lookup table...")
        
        for p in programs_data.get("programs", []):
            prog_id = p["id"]
            self.programs[prog_id] = {
                "id": prog_id,
                "name": p.get("displayName") or p.get("name") or "",
                "tet": p.get("trackedEntityType", {}).get("id") if p.get("trackedEntityType") else None
            }
            
            # Process program stages
            for ps in p.get("programStages", []):
                ps_id = ps["id"]
                
                display_name = ps.get("displayName") or ""
                raw_name = ps.get("name") or ""
                
                # Get data elements for this stage
                stage_de_ids = set()
                for psde in ps.get("programStageDataElements", []):
                    de = psde.get("dataElement", {})
                    if de and de.get("id"):
                        stage_de_ids.add(de["id"])
                
                # Store stage info
                self.program_stages[ps_id] = {
                    "id": ps_id,
                    "name": display_name or raw_name,
                    "displayName": display_name,
                    "rawName": raw_name,
                    "program_id": prog_id,
                    "data_elements": stage_de_ids
                }
                
                # Update data_elements_by_stage
                if ps_id not in self.data_elements_by_stage:
                    self.data_elements_by_stage[ps_id] = set()
                self.data_elements_by_stage[ps_id].update(stage_de_ids)
                
                # Create lookup variations
                names_to_try = []
                for name in [display_name, raw_name]:
                    if name:
                        names_to_try.extend([
                            name,
                            name.strip(),
                            name.lower(),
                            name.strip().lower(),
                            re.sub(r'\s+', ' ', name.strip()),
                            re.sub(r'\s+', ' ', name.strip().lower()),
                            re.sub(r'\s+', '', name),
                            re.sub(r'\s+', '', name.lower())
                        ])
                
                for name in set(names_to_try):
                    if name and name not in self.program_stage_lookup:
                        self.program_stage_lookup[name] = ps_id
        
        # Fetch Organisation Units
        ous_data = http_get(f"{self.base_api}/organisationUnits.json", self.auth,
                          {"fields": "id,name,displayName", "paging": "false"})
        for ou in ous_data.get("organisationUnits", []):
            ou_id = ou["id"]
            ou_name = ou.get("displayName") or ou.get("name") or ""
            self.org_units[ou_id] = ou_name
            self.org_unit_ids.add(ou_id)
            norm_name = normalize_for_comparison(ou_name)
            self.org_units[norm_name] = ou_id
        
        logger.info(f"Loaded {len(self.teas)} TEAs, {len(self.des)} DEs, "
                   f"{len(self.program_stages)} program stages, {len(self.org_units)} org units")
        
        # Log program stages
        logger.info("Available program stages in DHIS2:")
        for ps_id, ps_info in self.program_stages.items():
            logger.info(f"  - ID: {ps_id}, Name: '{ps_info['name']}'")
    
    def find_program_stage(self, name: str) -> Optional[str]:
        """Find program stage ID by name with flexible matching"""
        if not name:
            return None
        
        # Try direct match
        if name in self.program_stage_lookup:
            return self.program_stage_lookup[name]
        
        # Try stripped
        name_stripped = name.strip()
        if name_stripped in self.program_stage_lookup:
            return self.program_stage_lookup[name_stripped]
        
        # Try normalized
        name_normalized = re.sub(r'\s+', ' ', name_stripped.lower())
        if name_normalized in self.program_stage_lookup:
            return self.program_stage_lookup[name_normalized]
        
        # Try without spaces
        name_no_spaces = re.sub(r'\s+', '', name_stripped.lower())
        if name_no_spaces in self.program_stage_lookup:
            return self.program_stage_lookup[name_no_spaces]
        
        # Try contains
        for key, ps_id in self.program_stage_lookup.items():
            if name_normalized in key or key in name_normalized:
                return ps_id
        
        return None
    
    def is_data_element_in_stage(self, de_id: str, program_stage_id: str) -> bool:
        """Check if a data element belongs to a program stage"""
        if not de_id or not program_stage_id:
            return False
        
        stage_des = self.data_elements_by_stage.get(program_stage_id, set())
        return de_id in stage_des
    
    def find_org_unit(self, name_or_id: str) -> Optional[str]:
        """Find org unit ID by name or ID"""
        if not name_or_id:
            return None
        if name_or_id in self.org_unit_ids:
            return name_or_id
        norm_name = normalize_for_comparison(name_or_id)
        return self.org_units.get(norm_name)
    
    def find_tea(self, name: str) -> Optional[Dict]:
        """Find TEA by name (normalized)"""
        if not name:
            return None
        norm_name = normalize_for_comparison(name)
        for tea_id, tea in self.teas.items():
            if normalize_for_comparison(tea["name"]) == norm_name:
                return tea
        return None
    
    def find_de(self, name: str) -> Optional[Dict]:
        """Find DE by name (normalized)"""
        if not name:
            return None
        norm_name = normalize_for_comparison(name)
        for de_id, de in self.des.items():
            if normalize_for_comparison(de["name"]) == norm_name:
                return de
        return None

# ------------------------
# Core import logic
# ------------------------

def import_csv_to_dhis2(
    base_api: str,
    username: str,
    password: str,
    csv_path: str,
    verbose: bool = True,
    log_callback = None,
    progress_callback = None,
    dry_run: bool = False,
):
    """Main import function with data validation, progress reporting, and dry-run support"""
    
    def log(msg: str, level: str = "info"):
        if level == "error":
            logger.error(msg)
        elif level == "warning":
            logger.warning(msg)
        else:
            logger.info(msg)
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass
    
    base = base_api.strip().rstrip("/")
    if not base.endswith("/api"):
        base += "/api"
    
    auth = HTTPBasicAuth(username, password)
    
    # Read CSV with encoding handling
    try:
        df = read_csv_safe(csv_path)
        logger.info(f"Read CSV with {len(df)} rows and {len(df.columns)} columns")
    except Exception as e:
        raise RuntimeError(f"Could not read CSV '{csv_path}': {e}")
    
    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Fetch metadata
    metadata = DHIS2Metadata(base, auth)
    metadata.fetch_all()
    
    # Check program stages in CSV
    if "program_stage" not in df.columns:
        logger.error("No 'program_stage' column found in CSV!")
        raise RuntimeError("CSV must contain a 'program_stage' column")
    
    unique_stages = df["program_stage"].dropna().unique()
    logger.info("Program stages found in CSV:")
    stage_mapping = {}
    for stage in unique_stages:
        stage_str = str(stage).strip()
        if not stage_str:
            continue
        found_id = metadata.find_program_stage(stage_str)
        stage_mapping[stage_str] = found_id
        if found_id:
            logger.info(f"  - '{stage_str}' -> {found_id}")
        else:
            logger.warning(f"  - '{stage_str}' -> NOT FOUND")
    
    # Group rows by TEI
    tei_groups: Dict[str, Dict] = {}
    tei_by_record_id: Dict[str, str] = {}
    
    # First pass: collect all TEI IDs
    for idx, row in df.iterrows():
        tei_id = safe_str(row.get("tei_id"))
        record_id = safe_str(row.get("Record ID"))
        mother_record_id = safe_str(row.get("Mother record ID"))
        
        if tei_id and record_id:
            tei_by_record_id[record_id] = tei_id
        if tei_id and mother_record_id:
            tei_by_record_id[mother_record_id] = tei_id
    
    # Track issues
    skipped_rows = []
    data_validation_issues = []
    
    # Second pass: process each row
    for idx, row in df.iterrows():
        row_num = idx + 2  # +2 because of 0-index and header
        try:
            # Get TEI ID
            tei_id = safe_str(row.get("tei_id"))
            if not tei_id:
                record_id = safe_str(row.get("Record ID"))
                mother_record_id = safe_str(row.get("Mother record ID"))
                
                if record_id and record_id in tei_by_record_id:
                    tei_id = tei_by_record_id[record_id]
                elif mother_record_id and mother_record_id in tei_by_record_id:
                    tei_id = tei_by_record_id[mother_record_id]
                else:
                    logger.warning(f"Row {row_num}: No TEI ID found, skipping")
                    skipped_rows.append(row_num)
                    continue
            
            # Get org unit
            org_unit = metadata.find_org_unit(
                safe_str(row.get("org_unit_id")) or 
                safe_str(row.get("org_unit")) or 
                safe_str(row.get("orgUnit"))
            )
            if not org_unit:
                logger.warning(f"Row {row_num}: No org unit found, skipping")
                skipped_rows.append(row_num)
                continue
            
            # Get program
            program_id = safe_str(row.get("program"))
            if not program_id:
                logger.warning(f"Row {row_num}: No program found, skipping")
                skipped_rows.append(row_num)
                continue
            
            # Get enrollment ID
            enrollment_id = safe_str(row.get("enrollment_id"))
            
            # Get program stage
            program_stage_name = safe_str(row.get("program_stage"))
            if not program_stage_name:
                logger.warning(f"Row {row_num}: No program stage found, skipping")
                skipped_rows.append(row_num)
                continue
            
            program_stage_id = metadata.find_program_stage(program_stage_name)
            if not program_stage_id:
                logger.warning(f"Row {row_num}: Could not map program stage '{program_stage_name}'")
                skipped_rows.append(row_num)
                continue
            
            # Initialize TEI group
            if tei_id not in tei_groups:
                tei_groups[tei_id] = {
                    "trackedEntityInstance": tei_id,
                    "orgUnit": org_unit,
                    "trackedEntityType": metadata.programs.get(program_id, {}).get("tet"),
                    "attributes": [],
                    "enrollments": {},
                    "_attr_seen": set()
                }
            
            tei = tei_groups[tei_id]
            
            # Initialize enrollment
            if program_id not in tei["enrollments"]:
                enrollment_date = to_date_or_today(row.get("enrollment_date"))
                incident_date = to_date_or_today(row.get("incident_date") or row.get("enrollment_date"))
                
                tei["enrollments"][program_id] = {
                    "program": program_id,
                    "orgUnit": org_unit,
                    "enrollmentDate": enrollment_date,
                    "incidentDate": incident_date,
                    "status": (safe_str(row.get("enrollment_status")) or "ACTIVE").upper(),
                    "events": []
                }
                if enrollment_id:
                    tei["enrollments"][program_id]["enrollment"] = enrollment_id
            
            enrollment = tei["enrollments"][program_id]
            
            # Process attributes
            for col, val in row.items():
                if pd.isna(val) or val == "":
                    continue
                
                tea = metadata.find_tea(col)
                if tea:
                    value = str(val).strip()
                    
                    # Handle option sets
                    if tea.get("options"):
                        value = clean_option_value(value, tea["options"])
                    
                    # Check if attribute already exists
                    attr_exists = False
                    for attr in tei["attributes"]:
                        if attr["attribute"] == tea["id"]:
                            attr["value"] = value
                            attr_exists = True
                            break
                    
                    if not attr_exists:
                        tei["attributes"].append({
                            "attribute": tea["id"],
                            "value": value
                        })
                        tei["_attr_seen"].add(tea["id"])
            
            # Create event
            event_date = to_date_or_today(row.get("event_date"))
            
            event = {
                "program": program_id,
                "programStage": program_stage_id,
                "orgUnit": org_unit,
                "trackedEntityInstance": tei_id,
                "status": (safe_str(row.get("event_status")) or "COMPLETED").upper(),
                "eventDate": event_date,
                "dataValues": []
            }
            
            # Add event ID if present
            event_id = safe_str(row.get("event_id"))
            if event_id:
                event["event"] = event_id
            
            # Process data elements - only include those that belong to this stage
            data_values_count = 0
            skipped_des = []
            
            for col, val in row.items():
                if pd.isna(val) or val == "":
                    continue
                
                de = metadata.find_de(col)
                if de:
                    # Check if this data element belongs to the current program stage
                    if metadata.is_data_element_in_stage(de["id"], program_stage_id):
                        value = str(val).strip()
                        
                        # Handle option sets
                        if de.get("options"):
                            value = clean_option_value(value, de["options"])
                        
                        # Handle boolean values
                        if de.get("valueType") == "BOOLEAN":
                            if value.lower() in ["yes", "true", "1", "✓", "✔", "✅"]:
                                value = "true"
                            elif value.lower() in ["no", "false", "0", "✗", "❌"]:
                                value = "false"
                        
                        event["dataValues"].append({
                            "dataElement": de["id"],
                            "value": value
                        })
                        data_values_count += 1
                    else:
                        skipped_des.append(f"{col} ({de['id']})")
            
            if skipped_des:
                logger.debug(f"Row {row_num}: Skipped {len(skipped_des)} DEs not in stage: {', '.join(skipped_des[:5])}")
            
            # Only add event if it has data values
            if data_values_count > 0:
                enrollment["events"].append(event)
                logger.debug(f"Row {row_num}: Added event for stage '{program_stage_name}' with {data_values_count} data values")
            else:
                logger.warning(f"Row {row_num}: No valid data values for stage '{program_stage_name}', skipping event")
                data_validation_issues.append(f"Row {row_num}: No valid data elements for stage '{program_stage_name}'")
            
        except Exception as e:
            logger.error(f"Error processing row {row_num}: {e}")
            skipped_rows.append(row_num)
            continue
    
    # Report issues
    if data_validation_issues:
        logger.warning(f"Data validation issues ({len(data_validation_issues)}):")
        for issue in data_validation_issues[:10]:
            logger.warning(f"  {issue}")
    
    if skipped_rows:
        logger.warning(f"Skipped {len(skipped_rows)} rows: {skipped_rows[:20]}")
    
    # Prepare final payloads
    teis_payload = []
    for tei_id, tei_data in tei_groups.items():
        enrollments = list(tei_data.pop("enrollments").values())
        tei_data.pop("_attr_seen", None)
        
        if enrollments:
            tei_data["enrollments"] = enrollments
        
        event_count = sum(len(e.get("events", [])) for e in enrollments)
        logger.info(f"TEI {tei_id}: {len(enrollments)} enrollments, {event_count} events")
        
        teis_payload.append((tei_id, tei_data))
    
    if not teis_payload:
        raise RuntimeError("No valid TEIs to import")

    total_enrollments = sum(len(d.get("enrollments", [])) for _, d in teis_payload)
    total_events = sum(
        sum(len(e.get("events", [])) for e in d.get("enrollments", []))
        for _, d in teis_payload
    )

    if dry_run:
        log(f"[DRY RUN] Completed validation on {len(teis_payload)} TEIs.")
        log(f"[DRY RUN] Enrollments to create: {total_enrollments}, Events to create: {total_events}")
        log(f"[DRY RUN] Skipped rows / issues: {len(skipped_rows)}")
        log("[DRY RUN] No changes were written to DHIS2.")
        return {
            "status": "dry_run_success",
            "dry_run": True,
            "successes": len(teis_payload),
            "failures": len(skipped_rows),
            "timestamp": timestamp,
            "total_rows": len(df),
            "total_teis": len(teis_payload),
            "total_enrollments": total_enrollments,
            "total_events": total_events,
            "skipped_rows": skipped_rows,
            "failed_teis": [],
            "validation_issues": data_validation_issues[:50],
        }
    
    # Import all TEIs
    log(f"Importing {len(teis_payload)} TEIs...")
    successes = 0
    failures = 0
    failed_teis = []
    
    for idx, (tei_id, tei_data) in enumerate(teis_payload, start=1):
        try:
            log(f"[{idx}/{len(teis_payload)}] Uploading TEI {tei_id}...")
            
            payload = {"trackedEntityInstances": [tei_data]}
            response, report = http_post(f"{base}/trackedEntityInstances", auth, payload)
            
            # Save response
            safe_id = tei_id.replace("/", "_").replace(":", "_")
            with open(log_dir / f"tei_{safe_id}_{timestamp}.json", "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            # Parse import summary
            import_summary = report.get("response", {}) if isinstance(report, dict) else {}
            imported = import_summary.get("imported", 0)
            updated = import_summary.get("updated", 0)
            ignored = import_summary.get("ignored", 0)
            
            # Check for errors in events
            enrollments = import_summary.get("enrollments", {})
            if enrollments:
                event_errors = []
                for enr_summary in enrollments.get("importSummaries", []):
                    events = enr_summary.get("events", {})
                    for evt_summary in events.get("importSummaries", []):
                        if evt_summary.get("status") == "ERROR":
                            for conflict in evt_summary.get("conflicts", []):
                                event_errors.append(f"{conflict.get('object')}: {conflict.get('value')}")
                
                if event_errors:
                    log(f"  Events had errors: {', '.join(event_errors[:3])}", "warning")
                    with open(log_dir / f"tei_{safe_id}_{timestamp}_errors.txt", "w") as f:
                        f.write("\n".join(event_errors))
            
            log(f"  Imported: {imported}, Updated: {updated}, Ignored: {ignored}")
            successes += 1
            
        except Exception as e:
            failures += 1
            failed_teis.append(tei_id)
            safe_id = tei_id.replace("/", "_").replace(":", "_")
            with open(log_dir / f"tei_{safe_id}_{timestamp}_error.json", "w", encoding="utf-8") as f:
                f.write(str(e))
            log(f"Failed to import TEI {tei_id}: {e}", "error")
        finally:
            if progress_callback:
                try:
                    progress_callback(idx, len(teis_payload), tei_id, successes, failures)
                except Exception:
                    pass
    
    log(f"Import complete. Successes: {successes}, Failures: {failures}")
    if failed_teis:
        log(f"Failed TEIs: {failed_teis}", "warning")
    
    return {
        "status": "success" if failures == 0 else "partial_success",
        "dry_run": False,
        "successes": successes, 
        "failures": failures, 
        "timestamp": timestamp, 
        "total_rows": len(df),
        "total_teis": len(teis_payload),
        "total_enrollments": total_enrollments,
        "total_events": total_events,
        "skipped_rows": skipped_rows,
        "failed_teis": failed_teis
    }

# ------------------------
# CLI entrypoint
# ------------------------

def main_cli():
    parser = argparse.ArgumentParser(description="Import CSV to DHIS2 Tracker")
    parser.add_argument("--url", required=True, help="DHIS2 API base URL")
    parser.add_argument("--user", required=True, help="DHIS2 username")
    parser.add_argument("--pass", dest="pw", required=True, help="DHIS2 password")
    parser.add_argument("--csv", required=True, help="Path to CSV file to import")
    args = parser.parse_args()
    
    result = import_csv_to_dhis2(args.url, args.user, args.pw, args.csv, verbose=True)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main_cli()
