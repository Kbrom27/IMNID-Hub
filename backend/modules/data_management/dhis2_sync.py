# dhis2_sync.py - Enhanced version with complete logging and pagination
import os
import sys
import threading
import requests
import json
import datetime
import calendar
import time
from datetime import date, datetime as dt
import re
from typing import Dict, Set, Optional, List, Any, Callable
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# -------------------------
# Helper functions for normalization
# -------------------------

def normalize_for_comparison(s: str) -> str:
    """Normalize string for comparison by removing extra spaces and lowercasing"""
    if not s:
        return ""
    return re.sub(r'\s+', ' ', str(s).strip().lower())

def safe_str(v):
    """Safely convert value to string"""
    if v is None:
        return None
    s = str(v).strip()
    return s if s != "" and s.lower() != "nan" else None

def ensure_date(s, fallback):
    """Ensure date string is valid"""
    if isinstance(s, str) and len(s) >= 10:
        return s[:10]
    return fallback

# -------------------------
# Metadata cache class for sync
# -------------------------
class SyncMetadata:
    """Cache and manage DHIS2 metadata for sync operations"""
    
    def __init__(self, base_url: str, username: str, password: str):
        if not base_url or not str(base_url).strip():
            raise ValueError("DHIS2 URL is required.")
        if not username or not str(username).strip():
            raise ValueError("DHIS2 username is required.")
        if not password or not str(password).strip():
            raise ValueError("DHIS2 password is required.")
        self.base_url = base_url.rstrip('/')
        if not self.base_url.endswith('/api'):
            self.base_url += '/api'
        self.auth = (username, password)
        self.program_stages: Dict[str, Dict] = {}
        self.program_stage_lookup: Dict[str, str] = {}  # normalized name -> id
        self.programs: Dict[str, Dict] = {}
        self.org_units: Dict[str, str] = {}
        self.attributes: Dict[str, str] = {}
        self._loaded = False
        
    def fetch_all(self):
        """Fetch all necessary metadata from offline instance"""
        logger.info("Fetching metadata from offline DHIS2...")
        
        try:
            # Fetch programs with their stages
            url = f"{self.base_url}/programs.json"
            params = {
                "fields": "id,displayName,name,programStages[id,displayName,name]",
                "paging": "false"
            }
            response = requests.get(url, auth=self.auth, params=params)
            response.raise_for_status()
            data = response.json()
            
            for prog in data.get("programs", []):
                prog_id = prog["id"]
                self.programs[prog_id] = {
                    "id": prog_id,
                    "name": prog.get("displayName") or prog.get("name") or ""
                }
                
                # Process program stages
                for ps in prog.get("programStages", []):
                    ps_id = ps["id"]
                    ps_name = ps.get("displayName") or ps.get("name") or ""
                    
                    self.program_stages[ps_id] = {
                        "id": ps_id,
                        "name": ps_name,
                        "program_id": prog_id
                    }
                    
                    # Create multiple lookup variations
                    variations = [
                        normalize_for_comparison(ps_name),
                        normalize_for_comparison(ps.get("name")),
                        ps_name.lower().strip(),
                        ps_name.strip()
                    ]
                    
                    for key in variations:
                        if key:
                            self.program_stage_lookup[key] = ps_id
            
            # Fetch org units for reference
            ou_url = f"{self.base_url}/organisationUnits.json"
            ou_params = {"fields": "id,name", "paging": "false"}
            ou_response = requests.get(ou_url, auth=self.auth, params=ou_params)
            ou_response.raise_for_status()
            ou_data = ou_response.json()
            
            for ou in ou_data.get("organisationUnits", []):
                self.org_units[ou["id"]] = ou.get("name") or ""

            # Fetch tracked entity attributes for human-readable labels
            try:
                tea_url = f"{self.base_url}/trackedEntityAttributes.json"
                tea_params = {"fields": "id,name,displayName", "paging": "false"}
                tea_response = requests.get(tea_url, auth=self.auth, params=tea_params, timeout=30)
                if tea_response.ok:
                    for tea in tea_response.json().get("trackedEntityAttributes", []):
                        self.attributes[tea["id"]] = tea.get("displayName") or tea.get("name") or ""
                    logger.info(f"✓ Loaded {len(self.attributes)} tracked entity attributes")
            except Exception as e:
                logger.debug(f"Could not load tracked entity attributes: {e}")
            
            self._loaded = True
            logger.info(f"✓ Loaded {len(self.program_stages)} program stages from {len(self.programs)} programs")
            logger.info(f"✓ Loaded {len(self.org_units)} organisation units")
            
        except Exception as e:
            logger.error(f"✗ Failed to fetch metadata: {e}")
            raise
    
    def find_program_stage(self, stage_id_or_name: str) -> Optional[str]:
        """Find program stage ID by ID or name"""
        if not stage_id_or_name:
            return None
            
        # If it's already an ID
        if stage_id_or_name in self.program_stages:
            return stage_id_or_name
            
        # Try normalized lookup
        norm_name = normalize_for_comparison(stage_id_or_name)
        if norm_name in self.program_stage_lookup:
            return self.program_stage_lookup[norm_name]
        
        # Try fuzzy matching
        name_lower = stage_id_or_name.lower().strip()
        for key, ps_id in self.program_stage_lookup.items():
            if name_lower in key or key in name_lower:
                logger.debug(f"Fuzzy matched '{stage_id_or_name}' to '{key}'")
                return ps_id
        
        logger.warning(f"Could not find program stage: '{stage_id_or_name}'")
        return None
    
    def get_program_stage_name(self, stage_id: str) -> str:
        """Get program stage name by ID"""
        return self.program_stages.get(stage_id, {}).get("name", stage_id)


# -------------------------
# Core sync functions
# -------------------------

def merge_attributes(existing_attr_list, new_attr_list):
    """Merge attributes, keeping existing ones"""
    by_id = {a["attribute"]: a for a in existing_attr_list}
    for a in new_attr_list:
        if a.get("attribute") and a.get("value") is not None:
            if a["attribute"] not in by_id:
                by_id[a["attribute"]] = a
    return list(by_id.values())

def clean_tei_and_collect_events_and_relationships(
    tei: Dict, 
    selected_program_ids: Set[str], 
    metadata: SyncMetadata,
    start_date: str = None, 
    end_date: str = None
) -> tuple:
    """
    Clean TEI and collect events with proper program stage handling
    """
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    cleaned = {
        "trackedEntityInstance": tei.get("trackedEntityInstance"),
        "trackedEntityType": tei.get("trackedEntityType"),
        "orgUnit": tei.get("orgUnit"),
        "attributes": tei.get("attributes", []),
        "enrollments": []
    }
    
    all_events = []
    all_relationships = []
    
    # Collect relationships
    for rel in tei.get("relationships", []) or []:
        rel_type = rel.get("relationshipType")
        from_obj = rel.get("from", {})
        to_obj = rel.get("to", {})
        if rel_type and from_obj and to_obj:
            all_relationships.append({
                "relationshipType": rel_type,
                "from": from_obj,
                "to": to_obj
            })
    
    # Prepare date boundaries
    sd = None
    ed = None
    if start_date:
        try:
            sd = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        except Exception:
            sd = None
    if end_date:
        try:
            ed = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        except Exception:
            ed = None
    
    # Process enrollments
    for enr in tei.get("enrollments", []):
        prog = enr.get("program")
        if prog not in selected_program_ids:
            continue
            
        enr_org = enr.get("orgUnit") or tei.get("orgUnit")
        enr_status = enr.get("status") or "ACTIVE"
        enr_enrollment_date = ensure_date(enr.get("enrollmentDate"), today)
        enr_incident_date = ensure_date(enr.get("incidentDate"), enr_enrollment_date)
        
        # Apply date filters
        if sd or ed:
            try:
                enr_dt = datetime.datetime.strptime(enr_enrollment_date, "%Y-%m-%d").date()
            except Exception:
                continue
                
            if sd and ed:
                if enr_dt < sd or enr_dt > ed:
                    continue
            elif sd and not ed:
                if enr_dt < sd:
                    continue
            elif ed and not sd:
                if enr_dt > ed:
                    continue
        
        # Create cleaned enrollment
        cleaned_enr = {
            "enrollment": enr.get("enrollment"),
            "program": prog,
            "orgUnit": enr_org,
            "enrollmentDate": enr_enrollment_date,
            "incidentDate": enr_incident_date,
            "status": enr_status,
            "events": []  # Will collect events for this enrollment
        }
        
        # Process events for this enrollment
        for ev in enr.get("events", []) or []:
            ev_org = ev.get("orgUnit") or enr_org
            ev_status = ev.get("status") or "ACTIVE"
            ev_event_date = ensure_date(ev.get("eventDate"), ensure_date(ev.get("dueDate"), enr_enrollment_date))
            
            # Get program stage - use the ID directly
            program_stage = ev.get("programStage")
            if not program_stage:
                logger.warning(f"Event missing programStage: {ev.get('event')}")
                continue
            
            # Create cleaned event
            cleaned_event = {
                "event": ev.get("event"),
                "trackedEntityInstance": tei.get("trackedEntityInstance"),
                "enrollment": enr.get("enrollment"),
                "program": prog,
                "programStage": program_stage,
                "orgUnit": ev_org,
                "eventDate": ev_event_date,
                "status": ev_status,
            }
            
            if ev.get("completedDate"):
                cleaned_event["completedDate"] = ensure_date(ev.get("completedDate"), ev_event_date)
            
            # Process data values
            dvs = []
            for dv in ev.get("dataValues", []) or []:
                de = dv.get("dataElement")
                val = dv.get("value")
                if de is None or val is None:
                    continue
                dv_out = {"dataElement": de, "value": val}
                if "providedElsewhere" in dv:
                    dv_out["providedElsewhere"] = dv["providedElsewhere"]
                dvs.append(dv_out)
            
            if dvs:
                cleaned_event["dataValues"] = dvs
            
            # Add to enrollment's events list
            cleaned_enr["events"].append(cleaned_event)
            all_events.append(cleaned_event)
        
        # Always retain enrollment that passed the date filter (even if it has 0 events yet)
        cleaned["enrollments"].append(cleaned_enr)
    
    return cleaned, all_events, all_relationships


def fetch_te_is(
    base_url: str, 
    user: str, 
    password: str, 
    program_uid: str, 
    org_mode: str = "ALL", 
    org_uid: str = None, 
    program_start: str = None, 
    program_end: str = None,
    metadata: SyncMetadata = None,
    page_size: int = 1000
):
    """Fetch TEIs with pagination to get ALL records"""
    
    all_teis = []
    page = 1
    
    while True:
        params = {
            "program": program_uid,
            "page": page,
            "pageSize": page_size,
            "totalPages": True,
            "fields": (
                "trackedEntityInstance,trackedEntityType,orgUnit,"
                "attributes[attribute,value,displayName],"
                "enrollments[enrollment,program,orgUnit,enrollmentDate,incidentDate,status,"
                "events[event,program,programStage,orgUnit,enrollment,eventDate,dueDate,"
                "completedDate,status,dataValues[dataElement,value,providedElsewhere]]],"
                "relationships[relationship,relationshipType,from[trackedEntityInstance],to[trackedEntityInstance]]"
            ),
        }
        
        org_mode_upper = str(org_mode).strip().upper() if org_mode else "ALL"
        if org_mode_upper == "ALL":
            params["ouMode"] = "ALL"
        elif org_mode_upper in ["SPECIFIC", "SELECTED"] and org_uid and str(org_uid).upper() != "ALL":
            params["ou"] = org_uid
        
        if program_start:
            params["programStartDate"] = program_start
        if program_end:
            params["programEndDate"] = program_end
        
        url = f"{base_url}/api/trackedEntityInstances.json"
        
        try:
            logger.info(f"  Fetching page {page} (size {page_size})...")
            response = requests.get(url, auth=(user, password), params=params, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            teis = data.get("trackedEntityInstances", [])
            all_teis.extend(teis)
            
            # Get pagination info
            pager = data.get("pager", {})
            total_pages = pager.get("pageCount", 1)
            total_records = pager.get("total", 0)
            
            logger.info(f"    Page {page}: got {len(teis)} TEIs (total so far: {len(all_teis)} of {total_records})")
            
            # Check if we have all pages
            if page >= total_pages:
                break
                
            page += 1
            
        except Exception as e:
            logger.error(f"  ✗ Failed to fetch page {page}: {e}")
            break
    
    logger.info(f"  ✓ Fetched total {len(all_teis)} TEIs for program {program_uid}")
    return all_teis


# -------------------------
# Human-friendly explanation & reporting helpers
# -------------------------

def get_tei_display_label(tei: dict, metadata: SyncMetadata = None) -> str:
    """Extract a friendly label for a TEI (e.g. Name, MRN, Card No, or UID)"""
    if not tei:
        return "Unknown Patient"
    
    tei_id = tei.get("trackedEntityInstance", "")
    attributes = tei.get("attributes", [])
    
    id_attrs = []
    name_attrs = []
    
    for attr in attributes:
        aid = attr.get("attribute", "")
        val = str(attr.get("value", "")).strip()
        disp_name = attr.get("displayName", "")
        if not val or val.lower() == "none" or val.lower() == "nan":
            continue
            
        attr_name = ""
        if disp_name:
            attr_name = disp_name.lower()
        elif metadata and hasattr(metadata, "attributes"):
            attr_name = metadata.attributes.get(aid, "").lower()
            
        # Check by name or common ID patterns
        if any(kw in attr_name for kw in ["full name", "first name", "patient name", "child name", "mother name", "name"]):
            name_attrs.append(val)
        elif any(kw in attr_name for kw in ["card", "mrn", "id", "code", "medical record", "unique"]):
            title = disp_name or (metadata.attributes.get(aid, "ID") if metadata else "ID")
            id_attrs.append(f"{title}: {val}")
        elif len(val) >= 4 and not val.startswith("20") and (" " in val or len(val) < 25):
            if re.search(r"[a-zA-Z]", val) and not name_attrs:
                name_attrs.append(val)
                
    label_parts = []
    if name_attrs:
        label_parts.append(name_attrs[0])
    if id_attrs:
        label_parts.append(id_attrs[0])
        
    if label_parts:
        return f"{' | '.join(label_parts)} [ID: {tei_id}]"
    return f"Patient Record [ID: {tei_id}]"


def translate_dhis2_conflict(conflict_text: str, metadata: SyncMetadata = None) -> dict:
    """Translate raw DHIS2 error strings into clear, non-technical explanations"""
    c = str(conflict_text).strip()
    
    # 1. Non-unique attribute value
    m = re.search(r"Non-unique attribute value ['\"](.*?)['\"] for attribute (.*)", c, re.IGNORECASE)
    if m:
        val = m.group(1)
        attr_id = m.group(2).strip()
        attr_name = ""
        if metadata and hasattr(metadata, "attributes"):
            attr_name = metadata.attributes.get(attr_id, "")
        attr_display = f"'{attr_name}'" if attr_name else "this unique identifier"
        return {
            "what": f"Duplicate Identifier: {val}",
            "why": f"The unique card number or ID '{val}' for {attr_display} is already registered to another patient in the online DHIS2 system.",
            "suggestion": "Check if this patient has already been synchronized, or verify if the card/ID number was accidentally used twice in the clinic."
        }

    # 2. Org unit not in hierarchy
    if re.search(r"Organisation unit .*? is not in hierarchy of current user", c, re.IGNORECASE) or \
       re.search(r"Organisation unit is not in hierarchy", c, re.IGNORECASE):
        m_ou = re.search(r"Organisation unit (.*?) is not in hierarchy", c, re.IGNORECASE)
        ou_id = m_ou.group(1).strip() if (m_ou and m_ou.lastindex) else ""
        ou_name = metadata.org_units.get(ou_id, ou_id) if (metadata and ou_id) else "the designated health facility"
        return {
            "what": f"User Access Denied for Facility: {ou_name}",
            "why": f"Your online DHIS2 user account is not assigned to enter or update data for '{ou_name}'.",
            "suggestion": "Contact your DHIS2 Administrator to grant your user account access to this health facility."
        }

    # 3. Org unit does not exist
    if "organisation unit does not exist" in c.lower() or "could not find organisation unit" in c.lower():
        return {
            "what": "Health Facility Not Found in Online System",
            "why": "The health facility associated with this record does not exist on the online DHIS2 server.",
            "suggestion": "Verify that this health facility is configured with the exact same ID in both offline and online systems."
        }

    # 4. Program stage not repeatable
    m = re.search(r"Program stage (.*?) is not repeatable and an event already exists", c, re.IGNORECASE)
    if m:
        st_id = m.group(1).strip()
        st_name = metadata.get_program_stage_name(st_id) if metadata else st_id
        return {
            "what": f"Duplicate Visit/Form for '{st_name}'",
            "why": f"The clinical form '{st_name}' only permits one record per patient, but an entry is already saved in the online system.",
            "suggestion": "Check the patient's record online to see if this clinical form was already submitted previously."
        }

    # 5. Invalid date
    m = re.search(r"Value ['\"](.*?)['\"] is not a valid date", c, re.IGNORECASE)
    if m:
        val = m.group(1)
        return {
            "what": f"Invalid Date Format: '{val}'",
            "why": f"The date '{val}' is not in the required calendar format (YYYY-MM-DD).",
            "suggestion": "Correct the date in the offline record before attempting to sync again."
        }

    # 6. Invalid integer / number
    if re.search(r"Value ['\"].*?['\"] is not an integer", c, re.IGNORECASE) or \
       re.search(r"Value ['\"].*?['\"] is not a valid number", c, re.IGNORECASE):
        m = re.search(r"Value ['\"](.*?)['\"]", c, re.IGNORECASE)
        val = m.group(1) if m else "entered value"
        return {
            "what": f"Invalid Number: '{val}'",
            "why": f"A numeric field received '{val}', which contains letters or invalid characters.",
            "suggestion": "Check the entered value in the offline form and ensure only numbers are entered."
        }

    # 7. Option set choice mismatch
    m = re.search(r"Value ['\"](.*?)['\"] is not a valid option", c, re.IGNORECASE)
    if m:
        val = m.group(1)
        return {
            "what": f"Dropdown Choice Mismatch: '{val}'",
            "why": f"'{val}' is not one of the allowed dropdown options in the online version of this form.",
            "suggestion": "Check if the offline and online DHIS2 systems have matching dropdown option sets."
        }

    # 8. TEI does not exist
    if "tracked entity instance" in c.lower() and "does not exist" in c.lower():
        return {
            "what": "Patient Record Not Found Online",
            "why": "This clinical visit could not be linked because the main patient record does not exist in the online system.",
            "suggestion": "Ensure the patient's registration record is synchronized before or together with their clinical forms."
        }

    # 9. Future date
    if "future" in c.lower() and "date" in c.lower():
        return {
            "what": "Visit Date is in the Future",
            "why": "The recorded date is in the future, which is not permitted by DHIS2 validation rules.",
            "suggestion": "Correct the visit date in the offline system to the actual date of the examination."
        }

    # 10. Date before enrollment
    if "before enrollment date" in c.lower():
        return {
            "what": "Visit Date is Before Enrollment Date",
            "why": "The clinical form date is earlier than the date the patient was enrolled in the program.",
            "suggestion": "Verify both the enrollment date and event date in the offline system."
        }

    # 11. Already enrolled
    if "enrollment already exists" in c.lower():
        return {
            "what": "Patient is Already Enrolled",
            "why": "The patient already has an active enrollment in this program on the online server.",
            "suggestion": "The patient is already active in this program online. No further action needed."
        }

    # Clean generic prefixes
    clean_msg = re.sub(r'^(Attribute\.value:\s*|DataValue\.value:\s*|Event\.orgUnit:\s*)', '', c)
    return {
        "what": "Validation Conflict",
        "why": clean_msg,
        "suggestion": "Inspect this record in the offline system and ensure all required fields are filled accurately."
    }


def translate_network_or_http_error(err_str: str, server_url: str = "") -> dict:
    """Translate network, HTTP, or timeout errors into plain language"""
    s = str(err_str).lower()
    if "timed out" in s or "timeout" in s:
        return {
            "what": "Connection Timed Out",
            "why": f"The online DHIS2 server took too long to respond (> 2 minutes). The server may be busy or your internet connection is slow.",
            "suggestion": "Check your internet connection and try syncing a smaller date range or fewer programs at a time."
        }
    elif "401" in s or "unauthorized" in s:
        return {
            "what": "Incorrect Login Details",
            "why": "The username or password provided for the online DHIS2 system was rejected by the server.",
            "suggestion": "Check your online DHIS2 username and password in the connection box and try again."
        }
    elif "403" in s or "forbidden" in s:
        return {
            "what": "Permission Denied",
            "why": "Your online account does not have permission to import tracker data.",
            "suggestion": "Contact your DHIS2 Administrator to assign Data Import permissions to your account."
        }
    elif "connection refused" in s or "failed to establish a new connection" in s or "name resolution" in s:
        return {
            "what": "Cannot Reach Online Server",
            "why": f"Could not connect to '{server_url}'. The server may be down or the address is mistyped.",
            "suggestion": "Check that the URL is spelled correctly and that you have an active internet connection."
        }
    else:
        return {
            "what": "Server Communication Error",
            "why": f"An error occurred while communicating with the server: {err_str}",
            "suggestion": "Verify server status and check the detailed technical log file in sync_logs."
        }


def build_plain_language_report(data: dict) -> str:
    """Generate a clean, structured, non-technical plain language report"""
    lines = []
    lines.append("=" * 72)
    lines.append("📊 DHIS2 TRACKER SYNCHRONIZATION REPORT")
    lines.append("=" * 72)
    lines.append(f"🕒 Completed at: {data.get('timestamp_display', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}")
    lines.append(f"⏱️ Duration:     {data.get('duration', 'N/A')}")
    lines.append(f"🏥 Programs:     {', '.join(data.get('programs', []))}")
    lines.append(f"🏢 Org Unit:     {data.get('org_scope_display', 'All')}")
    if data.get('date_range_display'):
        lines.append(f"🗓️ Date Filter:  {data['date_range_display']}")
    lines.append(f"🌐 Offline System: {data.get('offline_url', '')}")
    lines.append(f"🌐 Online System:  {data.get('online_url', '')}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("📈 OVERALL SUMMARY (AT A GLANCE)")
    lines.append("-" * 72)
    
    tei_res = data.get("tei_results", {})
    ev_res = data.get("event_results", {})
    rel_res = data.get("rel_results", {})
    stats = data.get("stats", {})
    
    tei_imported = tei_res.get("imported", 0)
    tei_updated = tei_res.get("updated", 0)
    tei_ignored = tei_res.get("ignored", 0)
    tei_success = tei_imported + tei_updated
    tei_failed = len(tei_res.get("failures", [])) or tei_ignored
    tei_skipped = len(stats.get("skipped_teis", []))
    
    ev_imported = ev_res.get("imported", 0)
    ev_updated = ev_res.get("updated", 0)
    ev_ignored = ev_res.get("ignored", 0)
    ev_success = ev_imported + ev_updated
    ev_failed = len(ev_res.get("failures", [])) or ev_ignored
    
    rel_imported = rel_res.get("imported", 0)
    rel_updated = rel_res.get("updated", 0)
    rel_ignored = rel_res.get("ignored", 0)
    rel_success = rel_imported + rel_updated
    rel_failed = len(rel_res.get("failures", [])) or rel_ignored

    lines.append("👥 Patient Records (Tracked Entity Instances):")
    lines.append(f"   • Total Processed:        {stats.get('teis_after_filtering', 0)}")
    lines.append(f"   • ✅ Successfully Synced:  {tei_success}  ({tei_imported} newly created, {tei_updated} updated)")
    lines.append(f"   • {'❌' if tei_failed > 0 else '✓'} Failed to Sync:       {tei_failed}")
    if tei_skipped > 0:
        lines.append(f"   • ℹ️ Excluded by Filters:  {tei_skipped}  (Outside selected date range)")

    lines.append("")
    lines.append("📋 Clinical Visits & Forms (Events):")
    lines.append(f"   • Total Processed:        {stats.get('events_after_filtering', 0)}")
    lines.append(f"   • ✅ Successfully Synced:  {ev_success}  ({ev_imported} newly created, {ev_updated} updated)")
    lines.append(f"   • {'❌' if ev_failed > 0 else '✓'} Failed to Sync:       {ev_failed}")

    if stats.get("relationships_fetched", 0) > 0 or rel_success > 0 or rel_failed > 0:
        lines.append("")
        lines.append("🔗 Relationships & Links:")
        lines.append(f"   • Total Processed:        {stats.get('relationships_fetched', 0)}")
        lines.append(f"   • ✅ Successfully Synced:  {rel_success}  ({rel_imported} newly created, {rel_updated} updated)")
        lines.append(f"   • {'❌' if rel_failed > 0 else '✓'} Failed to Sync:       {rel_failed}")

    lines.append("")
    total_issues = tei_failed + ev_failed + rel_failed
    if total_issues == 0 and not data.get("error"):
        lines.append("🎉 OVERALL RESULT: ALL ELIGIBLE RECORDS SYNCHRONIZED SUCCESSFULLY! ✅")
        lines.append("   All patient records and clinical visits were saved to the online")
        lines.append("   system with zero errors. No further action is required.")
    elif data.get("error"):
        lines.append("❌ OVERALL RESULT: SYNC ENCOUNTERED A CRITICAL ERROR!")
        fe = data.get("friendly_error", {})
        if isinstance(fe, dict):
            lines.append(f"   Problem: {fe.get('what', data.get('error'))}")
            lines.append(f"   Why:     👉 {fe.get('why', '')}")
            lines.append(f"   Fix:     💡 {fe.get('suggestion', '')}")
        else:
            lines.append(f"   {data.get('error')}")
    else:
        lines.append(f"⚠️ OVERALL RESULT: COMPLETED WITH {total_issues} ISSUE(S) REQUIRING ATTENTION")
        lines.append("   Some records could not be synchronized. Please review the details below.")
    lines.append("-" * 72)
    
    # Detailed Failures Section
    tei_failures = tei_res.get("failures", [])
    ev_failures = ev_res.get("failures", [])
    rel_failures = rel_res.get("failures", [])
    
    if tei_failures or ev_failures or rel_failures:
        lines.append("")
        lines.append("⚠️ DETAILED BREAKDOWN OF FAILED RECORDS (WHAT FAILED & WHY)")
        lines.append("-" * 72)
        lines.append("The records below could not be saved online. Here is what happened in plain")
        lines.append("language and what steps you can take to fix them:")
        lines.append("")
        
        counter = 1
        if tei_failures:
            lines.append("👥 FAILED PATIENT RECORDS:")
            lines.append("")
            for f in tei_failures:
                lines.append(f"  {counter}. 👤 {f.get('label', 'Patient Record')}")
                lines.append(f"     • Health Facility:  {f.get('facility', 'Unknown')}")
                lines.append(f"     • System Record ID: {f.get('tei_id', 'N/A')}")
                for c in f.get("conflicts", []):
                    lines.append(f"     • Problem:  {c.get('what', 'Validation error')}")
                    lines.append(f"     • Why:      👉 {c.get('why', '')}")
                    lines.append(f"     • How to Fix: 💡 {c.get('suggestion', '')}")
                lines.append("")
                counter += 1
                
        if ev_failures:
            lines.append("📋 FAILED CLINICAL VISITS & FORMS:")
            lines.append("")
            for f in ev_failures:
                lines.append(f"  {counter}. 📋 Form: '{f.get('stage', 'Clinical Stage')}' (Date: {f.get('event_date', 'Unknown')})")
                lines.append(f"     • Patient:          {f.get('patient_label', 'Unknown Patient')}")
                lines.append(f"     • Health Facility:  {f.get('facility', 'Unknown')}")
                lines.append(f"     • System Event ID:  {f.get('event_id', 'N/A')}")
                for c in f.get("conflicts", []):
                    lines.append(f"     • Problem:  {c.get('what', 'Validation error')}")
                    lines.append(f"     • Why:      👉 {c.get('why', '')}")
                    lines.append(f"     • How to Fix: 💡 {c.get('suggestion', '')}")
                lines.append("")
                counter += 1

        if rel_failures:
            lines.append("🔗 FAILED RELATIONSHIPS / LINKS:")
            lines.append("")
            for f in rel_failures:
                lines.append(f"  {counter}. 🔗 Link: {f.get('rel_type', 'Relationship')}")
                lines.append(f"     • From: {f.get('from', 'N/A')} ➔ To: {f.get('to', 'N/A')}")
                for c in f.get("conflicts", []):
                    lines.append(f"     • Problem:  {c.get('what', 'Validation error')}")
                    lines.append(f"     • Why:      👉 {c.get('why', '')}")
                    lines.append(f"     • How to Fix: 💡 {c.get('suggestion', '')}")
                lines.append("")
                counter += 1

    # Skipped records section
    skipped = stats.get("skipped_teis", [])
    if skipped:
        lines.append("")
        lines.append(f"ℹ️ EXCLUDED / SKIPPED RECORDS ({len(skipped)} records)")
        lines.append("-" * 72)
        lines.append("These records were found in the offline system but excluded based on your filters:")
        for s in skipped[:15]:
            lines.append(f"  • {s.get('label', s.get('tei_id', 'Record'))} ({s.get('facility', 'Facility')}):")
            lines.append(f"    👉 {s.get('reason', 'Excluded by filter')}")
        if len(skipped) > 15:
            lines.append(f"  ... and {len(skipped) - 15} more records (see technical log for full list).")
        lines.append("")

    lines.append("-" * 72)
    lines.append(f"📁 Technical audit log: {data.get('log_file', 'sync_logs/')}")
    lines.append("========================================================================")
    return "\n".join(lines)


# -------------------------
# Core upload functions with failure parsing
# -------------------------

def upload_teis(
    online_config: dict, 
    teis: List[dict], 
    timestamp: str, 
    log_dir: Path, 
    metadata: SyncMetadata = None, 
    tei_map: dict = None,
    batch_size: int = 25,
    status_callback: Optional[Callable[[str], None]] = None,
    log_callback: Optional[Callable[[str, Optional[str]], None]] = None
) -> dict:
    """Upload TEIs to online instance in reliable batches with retry logic and detailed failure breakdown"""
    if not teis:
        logger.info("  No TEIs to upload")
        return {"imported": 0, "updated": 0, "ignored": 0, "failures": []}
    
    url = f"{online_config['url']}/api/trackedEntityInstances"
    tei_lookup = tei_map or {t.get("trackedEntityInstance"): t for t in teis}
    
    # Split TEIs into manageable batches
    batches = [teis[i:i + batch_size] for i in range(0, len(teis), batch_size)]
    total_batches = len(batches)
    logger.info(f"  Uploading {len(teis)} TEIs in {total_batches} batches (batch size {batch_size}) to {url}")
    
    total_imported = 0
    total_updated = 0
    total_ignored = 0
    all_failures = []
    all_raw_errors = []
    all_batch_reports = []
    
    for b_idx, batch in enumerate(batches, 1):
        batch_label = f"Patient records: Batch {b_idx}/{total_batches} ({len(batch)} records)..."
        if status_callback:
            status_callback(batch_label)
        if log_callback:
            log_callback(f"   → Uploading batch {b_idx}/{total_batches} ({len(batch)} patient records)...", "info")
            
        payload = {"trackedEntityInstances": batch}
        response = None
        last_error = None
        max_retries = 2
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    url,
                    auth=(online_config["username"], online_config["password"]),
                    headers={"Content-Type": "application/json"},
                    params={"strategy": "CREATE_AND_UPDATE"},
                    data=json.dumps(payload),
                    timeout=90
                )
                if response.status_code in [502, 503, 504] and attempt < max_retries:
                    logger.warning(f"  Batch {b_idx} server busy (HTTP {response.status_code}), retrying ({attempt+1}/{max_retries})...")
                    if log_callback:
                        log_callback(f"      ⚠ Server busy (HTTP {response.status_code}), retrying in 3 seconds...", "warning")
                    time.sleep(3)
                    continue
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"  Batch {b_idx} network error ({e}), retrying ({attempt+1}/{max_retries})...")
                    if log_callback:
                        log_callback(f"      ⚠ Network hiccup on batch {b_idx}, retrying in 3 seconds (attempt {attempt+1}/{max_retries})...", "warning")
                    time.sleep(3)
                else:
                    logger.error(f"  ✗ Batch {b_idx} failed after {max_retries+1} attempts: {e}")

        # Check authentication error
        if response is not None and response.status_code in [401, 403]:
            friendly = translate_network_or_http_error(f"HTTP {response.status_code}", online_config.get("url"))
            remaining_teis = len(teis) - (total_imported + total_updated + total_ignored)
            total_ignored += remaining_teis
            all_failures.append({
                "tei_id": "All",
                "label": "All patient records",
                "facility": "All",
                "conflicts": [friendly]
            })
            if log_callback:
                log_callback(f"   ✗ Authentication failed (HTTP {response.status_code}). Stopped remaining batches.", "error")
            return {
                "imported": total_imported,
                "updated": total_updated,
                "ignored": total_ignored,
                "error": f"HTTP {response.status_code} Authentication failed",
                "friendly_error": friendly,
                "failures": all_failures
            }

        if response is None:
            # Batch timed out or network error persisted after all retries
            friendly = translate_network_or_http_error(str(last_error), online_config.get("url"))
            total_ignored += len(batch)
            for tei in batch:
                ref = tei.get("trackedEntityInstance") or "Unknown ID"
                label = get_tei_display_label(tei, metadata)
                ou_id = tei.get("orgUnit")
                facility_name = metadata.org_units.get(ou_id, ou_id or "Unknown") if metadata else ou_id or "Unknown"
                all_failures.append({
                    "tei_id": ref,
                    "label": label,
                    "facility": facility_name,
                    "conflicts": [friendly]
                })
            if log_callback:
                log_callback(f"   ✗ Batch {b_idx}/{total_batches} timed out / failed after retries: {friendly.get('what', 'Network timeout')}", "error")
            continue

        report = response.json() if response.text else {}
        all_batch_reports.append(report)

        if isinstance(report, dict):
            response_data = report.get("response", report)
            b_imported = response_data.get("imported", 0)
            b_updated = response_data.get("updated", 0)
            b_ignored = response_data.get("ignored", 0)

            total_imported += b_imported
            total_updated += b_updated
            total_ignored += b_ignored

            b_failures = 0
            for summary in response_data.get("importSummaries", []):
                ref = summary.get("reference")
                status = summary.get("status")
                counts = summary.get("importCount", {})

                enr_summaries = summary.get("enrollments", {}).get("importSummaries", [])
                has_enr_error = any(es.get("status") == "ERROR" or es.get("conflicts") for es in enr_summaries)

                is_failed = (status == "ERROR") or (counts.get("ignored", 0) > 0) or has_enr_error
                if is_failed:
                    b_failures += 1
                    tei_obj = tei_lookup.get(ref, {})
                    label = get_tei_display_label(tei_obj, metadata)
                    ou_id = tei_obj.get("orgUnit")
                    facility_name = metadata.org_units.get(ou_id, ou_id or "Unknown") if metadata else ou_id or "Unknown"

                    conflicts_list = []
                    for c in summary.get("conflicts", []):
                        val = c.get("value") or c.get("object") or "Unknown conflict"
                        all_raw_errors.append(f"{c.get('object', 'Object')}: {val}")
                        conflicts_list.append(translate_dhis2_conflict(val, metadata))

                    for es in enr_summaries:
                        for c in es.get("conflicts", []):
                            val = c.get("value") or c.get("object") or es.get("description") or "Enrollment issue"
                            all_raw_errors.append(f"Enrollment: {val}")
                            conflicts_list.append(translate_dhis2_conflict(val, metadata))
                        if not es.get("conflicts") and es.get("description"):
                            conflicts_list.append(translate_dhis2_conflict(es.get("description"), metadata))

                    if not conflicts_list:
                        desc = summary.get("description") or "Record was rejected or ignored by the DHIS2 online server."
                        conflicts_list.append(translate_dhis2_conflict(desc, metadata))

                    all_failures.append({
                        "tei_id": ref or "Unknown ID",
                        "label": label,
                        "facility": facility_name,
                        "conflicts": conflicts_list
                    })

            if log_callback:
                if b_failures > 0:
                    log_callback(f"      ✓ Batch {b_idx}/{total_batches}: {b_imported} new, {b_updated} updated, {b_failures} failed", "warning")
                else:
                    log_callback(f"      ✓ Batch {b_idx}/{total_batches}: {b_imported} new, {b_updated} updated (100% success)", "info")
        else:
            total_ignored += len(batch)
            if log_callback:
                log_callback(f"      ✗ Batch {b_idx}/{total_batches}: Unexpected server response", "error")

    report_file = log_dir / f"teis_report_{timestamp}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"total_imported": total_imported, "total_updated": total_updated, "total_ignored": total_ignored, "batch_reports": all_batch_reports}, f, indent=2)
    logger.info(f"  ✓ TEI Report saved: {report_file}")

    if all_raw_errors:
        error_file = log_dir / f"teis_errors_{timestamp}.txt"
        with open(error_file, "w", encoding="utf-8") as f:
            f.write("\n".join(all_raw_errors))
        logger.warning(f"  ⚠ Found {len(all_raw_errors)} errors, saved to {error_file}")

    logger.info(f"  Results - Imported: {total_imported}, Updated: {total_updated}, Ignored: {total_ignored}")
    return {
        "imported": total_imported,
        "updated": total_updated,
        "ignored": total_ignored,
        "failures": all_failures,
        "report_file": str(report_file)
    }


def upload_events(
    online_config: dict, 
    events: List[dict], 
    timestamp: str, 
    log_dir: Path, 
    metadata: SyncMetadata = None, 
    tei_map: dict = None,
    batch_size: int = 100,
    status_callback: Optional[Callable[[str], None]] = None,
    log_callback: Optional[Callable[[str, Optional[str]], None]] = None
) -> dict:
    """Upload events to online instance in reliable batches with retry logic and detailed failure breakdown"""
    if not events:
        logger.info("  No events to upload")
        return {"imported": 0, "updated": 0, "ignored": 0, "failures": []}
    
    unique_events = {}
    for ev in events:
        key = ev.get("event") or f"{ev.get('trackedEntityInstance')}|{ev.get('program')}|{ev.get('programStage')}|{ev.get('eventDate')}"
        unique_events[key] = ev
    
    events_list = list(unique_events.values())
    batches = [events_list[i:i + batch_size] for i in range(0, len(events_list), batch_size)]
    total_batches = len(batches)
    url = f"{online_config['url']}/api/events"
    logger.info(f"  Uploading {len(events_list)} events in {total_batches} batches (batch size {batch_size}) to {url}")
    
    total_imported = 0
    total_updated = 0
    total_ignored = 0
    all_failures = []
    all_raw_errors = []
    all_batch_reports = []
    
    for b_idx, batch in enumerate(batches, 1):
        batch_label = f"Clinical visits: Batch {b_idx}/{total_batches} ({len(batch)} visits)..."
        if status_callback:
            status_callback(batch_label)
        if log_callback:
            log_callback(f"   → Uploading batch {b_idx}/{total_batches} ({len(batch)} clinical visits)...", "info")
            
        payload = {"events": batch}
        response = None
        last_error = None
        max_retries = 2
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    url,
                    auth=(online_config["username"], online_config["password"]),
                    headers={"Content-Type": "application/json"},
                    params={"strategy": "CREATE_AND_UPDATE"},
                    data=json.dumps(payload),
                    timeout=90
                )
                if response.status_code in [502, 503, 504] and attempt < max_retries:
                    logger.warning(f"  Event batch {b_idx} server busy (HTTP {response.status_code}), retrying ({attempt+1}/{max_retries})...")
                    if log_callback:
                        log_callback(f"      ⚠ Server busy (HTTP {response.status_code}), retrying in 3 seconds...", "warning")
                    time.sleep(3)
                    continue
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"  Event batch {b_idx} network error ({e}), retrying ({attempt+1}/{max_retries})...")
                    if log_callback:
                        log_callback(f"      ⚠ Network hiccup on batch {b_idx}, retrying in 3 seconds (attempt {attempt+1}/{max_retries})...", "warning")
                    time.sleep(3)
                else:
                    logger.error(f"  ✗ Event batch {b_idx} failed after {max_retries+1} attempts: {e}")

        if response is not None and response.status_code in [401, 403]:
            friendly = translate_network_or_http_error(f"HTTP {response.status_code}", online_config.get("url"))
            remaining_events = len(events_list) - (total_imported + total_updated + total_ignored)
            total_ignored += remaining_events
            all_failures.append({
                "event_id": "All",
                "stage": "All Forms",
                "event_date": "N/A",
                "patient_label": "All",
                "facility": "All",
                "conflicts": [friendly]
            })
            if log_callback:
                log_callback(f"   ✗ Authentication failed (HTTP {response.status_code}). Stopped remaining event batches.", "error")
            return {
                "imported": total_imported,
                "updated": total_updated,
                "ignored": total_ignored,
                "error": f"HTTP {response.status_code} Authentication failed",
                "friendly_error": friendly,
                "failures": all_failures
            }

        if response is None:
            friendly = translate_network_or_http_error(str(last_error), online_config.get("url"))
            total_ignored += len(batch)
            for ev in batch:
                ref = ev.get("event") or "Unknown ID"
                st_id = ev.get("programStage")
                st_name = metadata.get_program_stage_name(st_id) if metadata else st_id or "Clinical Form"
                ev_date = ev.get("eventDate", "Unknown Date")
                ou_id = ev.get("orgUnit")
                facility_name = metadata.org_units.get(ou_id, ou_id or "Unknown") if metadata else ou_id or "Unknown"
                tei_id = ev.get("trackedEntityInstance", "")
                patient_label = "Unknown Patient"
                if tei_map and tei_id in tei_map:
                    patient_label = get_tei_display_label(tei_map[tei_id], metadata)
                elif tei_id:
                    patient_label = f"Patient ID {tei_id}"
                all_failures.append({
                    "event_id": ref,
                    "stage": st_name,
                    "event_date": ev_date,
                    "patient_label": patient_label,
                    "facility": facility_name,
                    "conflicts": [friendly]
                })
            if log_callback:
                log_callback(f"   ✗ Event batch {b_idx}/{total_batches} timed out / failed after retries: {friendly.get('what', 'Network timeout')}", "error")
            continue

        report = response.json() if response.text else {}
        all_batch_reports.append(report)

        if isinstance(report, dict):
            response_data = report.get("response", report)
            b_imported = response_data.get("imported", 0)
            b_updated = response_data.get("updated", 0)
            b_ignored = response_data.get("ignored", 0)

            total_imported += b_imported
            total_updated += b_updated
            total_ignored += b_ignored

            b_failures = 0
            for summary in response_data.get("importSummaries", []):
                ref = summary.get("reference")
                status = summary.get("status")
                counts = summary.get("importCount", {})

                if status == "ERROR" or counts.get("ignored", 0) > 0:
                    b_failures += 1
                    ev = unique_events.get(ref, {})
                    st_id = ev.get("programStage")
                    st_name = metadata.get_program_stage_name(st_id) if metadata else st_id or "Clinical Form"
                    ev_date = ev.get("eventDate", "Unknown Date")
                    ou_id = ev.get("orgUnit")
                    facility_name = metadata.org_units.get(ou_id, ou_id or "Unknown") if metadata else ou_id or "Unknown"
                    tei_id = ev.get("trackedEntityInstance", "")

                    patient_label = "Unknown Patient"
                    if tei_map and tei_id in tei_map:
                        patient_label = get_tei_display_label(tei_map[tei_id], metadata)
                    elif tei_id:
                        patient_label = f"Patient ID {tei_id}"

                    conflicts_list = []
                    for c in summary.get("conflicts", []):
                        val = c.get("value") or c.get("object") or "Unknown conflict"
                        all_raw_errors.append(f"{c.get('object', 'Object')}: {val}")
                        conflicts_list.append(translate_dhis2_conflict(val, metadata))

                    if not conflicts_list:
                        desc = summary.get("description") or "Clinical visit was ignored or rejected by DHIS2 online server."
                        conflicts_list.append(translate_dhis2_conflict(desc, metadata))

                    all_failures.append({
                        "event_id": ref or "Unknown Event ID",
                        "stage": st_name,
                        "event_date": ev_date,
                        "patient_label": patient_label,
                        "facility": facility_name,
                        "conflicts": conflicts_list
                    })

            if log_callback:
                if b_failures > 0:
                    log_callback(f"      ✓ Batch {b_idx}/{total_batches}: {b_imported} new, {b_updated} updated, {b_failures} failed", "warning")
                else:
                    log_callback(f"      ✓ Batch {b_idx}/{total_batches}: {b_imported} new, {b_updated} updated (100% success)", "info")
        else:
            total_ignored += len(batch)
            if log_callback:
                log_callback(f"      ✗ Batch {b_idx}/{total_batches}: Unexpected server response", "error")

    report_file = log_dir / f"events_report_{timestamp}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"total_imported": total_imported, "total_updated": total_updated, "total_ignored": total_ignored, "batch_reports": all_batch_reports}, f, indent=2)
    logger.info(f"  ✓ Events Report saved: {report_file}")

    if all_raw_errors:
        error_file = log_dir / f"events_errors_{timestamp}.txt"
        with open(error_file, "w", encoding="utf-8") as f:
            f.write("\n".join(all_raw_errors))
        logger.warning(f"  ⚠ Found {len(all_raw_errors)} errors, saved to {error_file}")

    logger.info(f"  Results - Imported: {total_imported}, Updated: {total_updated}, Ignored: {total_ignored}")
    return {
        "imported": total_imported,
        "updated": total_updated,
        "ignored": total_ignored,
        "failures": all_failures,
        "report_file": str(report_file)
    }


def upload_relationships(
    online_config: dict, 
    relationships: List[dict], 
    timestamp: str, 
    log_dir: Path, 
    metadata: SyncMetadata = None,
    batch_size: int = 50,
    status_callback: Optional[Callable[[str], None]] = None,
    log_callback: Optional[Callable[[str, Optional[str]], None]] = None
) -> dict:
    """Upload relationships to online instance in reliable batches with retry logic and detailed failure breakdown"""
    if not relationships:
        logger.info("  No relationships to upload")
        return {"imported": 0, "updated": 0, "ignored": 0, "failures": []}
    
    unique_rels = {}
    for rel in relationships:
        key = f"{rel.get('relationshipType')}|{rel.get('from', {}).get('trackedEntityInstance')}|{rel.get('to', {}).get('trackedEntityInstance')}"
        unique_rels[key] = rel
    
    rels_list = list(unique_rels.values())
    batches = [rels_list[i:i + batch_size] for i in range(0, len(rels_list), batch_size)]
    total_batches = len(batches)
    url = f"{online_config['url']}/api/relationships"
    logger.info(f"  Uploading {len(rels_list)} relationships in {total_batches} batches to {url}")
    
    total_imported = 0
    total_updated = 0
    total_ignored = 0
    all_failures = []
    all_batch_reports = []
    
    for b_idx, batch in enumerate(batches, 1):
        batch_label = f"Relationships: Batch {b_idx}/{total_batches} ({len(batch)} links)..."
        if status_callback:
            status_callback(batch_label)
        if log_callback:
            log_callback(f"   → Uploading batch {b_idx}/{total_batches} ({len(batch)} relationships)...", "info")
            
        payload = {"relationships": batch}
        response = None
        last_error = None
        max_retries = 2
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    url,
                    auth=(online_config["username"], online_config["password"]),
                    headers={"Content-Type": "application/json"},
                    params={"strategy": "CREATE_AND_UPDATE"},
                    data=json.dumps(payload),
                    timeout=90
                )
                if response.status_code in [502, 503, 504] and attempt < max_retries:
                    time.sleep(3)
                    continue
                break
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    logger.error(f"  ✗ Relationship batch {b_idx} failed: {e}")

        if response is None:
            friendly = translate_network_or_http_error(str(last_error), online_config.get("url"))
            total_ignored += len(batch)
            all_failures.append({
                "rel_id": f"Batch {b_idx}",
                "rel_type": "Relationship Links",
                "from": "Patients in batch",
                "to": "Linked entities",
                "conflicts": [friendly]
            })
            continue

        report = response.json() if response.text else {}
        all_batch_reports.append(report)

        if isinstance(report, dict):
            response_data = report.get("response", report)
            total_imported += response_data.get("imported", 0)
            total_updated += response_data.get("updated", 0)
            total_ignored += response_data.get("ignored", 0)

            for summary in response_data.get("importSummaries", []):
                ref = summary.get("reference")
                status = summary.get("status")
                counts = summary.get("importCount", {})

                if status == "ERROR" or counts.get("ignored", 0) > 0:
                    conflicts_list = []
                    for c in summary.get("conflicts", []):
                        val = c.get("value") or c.get("object") or "Unknown conflict"
                        conflicts_list.append(translate_dhis2_conflict(val, metadata))
                    if not conflicts_list and summary.get("description"):
                        conflicts_list.append(translate_dhis2_conflict(summary.get("description"), metadata))

                    all_failures.append({
                        "rel_id": ref or "Unknown Link",
                        "rel_type": "Relationship Link",
                        "from": "Patient A",
                        "to": "Patient B",
                        "conflicts": conflicts_list
                    })

    report_file = log_dir / f"relationships_report_{timestamp}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"total_imported": total_imported, "total_updated": total_updated, "total_ignored": total_ignored, "batch_reports": all_batch_reports}, f, indent=2)
    logger.info(f"  ✓ Relationships Report saved: {report_file}")

    return {
        "imported": total_imported,
        "updated": total_updated,
        "ignored": total_ignored,
        "failures": all_failures,
        "report_file": str(report_file)
    }


# -------------------------
# Main orchestration function
# -------------------------

def sync_data_offline_to_online(
    offline_config: dict,
    online_config: dict,
    selected_programs: List[str],
    org_mode: str,
    selected_org_uid: str = None,
    start_date: str = None,
    end_date: str = None,
    log_callback: Optional[Callable[[str, Optional[str]], None]] = None,
    status_callback: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
) -> dict:
    """
    Main sync function with live reporting and plain-language summary report.
    """
    start_time = datetime.datetime.now()
    log_dir = Path("sync_logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = start_time.strftime("%Y%m%d_%H%M%S")
    
    log_file = log_dir / f"sync_{timestamp}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    def log_both(msg: str, tag: str = None):
        if tag == "error":
            logger.error(msg)
        elif tag == "warning":
            logger.warning(msg)
        else:
            logger.info(msg)
        if log_callback:
            log_callback(msg, tag)
            
    def update_status(text: str):
        if status_callback:
            status_callback(text)

    try:
        log_both("=" * 65, "header")
        log_both("🚀 STARTING DHIS2 TRACKER SYNCHRONIZATION", "header")
        log_both(f"Timestamp:   {start_time.strftime('%Y-%m-%d %H:%M:%S')}", "info")
        log_both(f"Offline:     {offline_config['url']}", "info")
        log_both(f"Online:      {online_config['url']}", "info")
        log_both(f"Programs:    {len(selected_programs)} selected", "info")
        log_both(f"Facility:    {org_mode} (UID: {selected_org_uid or 'All'})", "info")
        if start_date or end_date:
            log_both(f"Date Range:  {start_date or 'Any'} to {end_date or 'Any'}", "info")
        log_both("=" * 65, "header")
        
        update_status("Connecting to offline DHIS2 & fetching metadata...")
        log_both("\n📥 Fetching program and facility metadata from offline DHIS2...", "info")
        
        metadata = SyncMetadata(
            offline_config["url"],
            offline_config["username"],
            offline_config["password"]
        )
        
        try:
            metadata.fetch_all()
            log_both(f"✓ Loaded {len(metadata.programs)} programs, {len(metadata.program_stages)} stages, and {len(metadata.org_units)} facilities.", "success")
        except Exception as e:
            friendly = translate_network_or_http_error(str(e), offline_config["url"])
            log_both(f"✗ Failed to connect to offline DHIS2: {friendly['what']}", "error")
            log_both(f"  👉 {friendly['why']}", "error")
            raise Exception(f"{friendly['what']}: {friendly['why']}")
        
        stats = {
            "teis_fetched": 0,
            "teis_after_filtering": 0,
            "events_fetched": 0,
            "events_after_filtering": 0,
            "relationships_fetched": 0,
            "skipped_teis": [],
            "program_stats": {}
        }
        
        tei_map = {}
        events_all = []
        relationships_all = []
        
        prog_display_names = []
        for prog_id in selected_programs:
            prog_name = metadata.programs.get(prog_id, {}).get("name", prog_id)
            prog_display_names.append(prog_name)
            update_status(f"Fetching records for {prog_name}...")
            log_both(f"\n📊 Reading program records: {prog_name} ({prog_id})", "header")
            
            try:
                teis = fetch_te_is(
                    offline_config["url"],
                    offline_config["username"],
                    offline_config["password"],
                    prog_id,
                    org_mode=org_mode,
                    org_uid=selected_org_uid,
                    program_start=start_date,
                    program_end=end_date,
                    metadata=metadata
                )
                
                log_both(f"  → Fetched {len(teis)} records from offline system", "info")
                stats["teis_fetched"] += len(teis)
                stats["program_stats"][prog_id] = {"raw_teis": len(teis), "processed_teis": 0}
                
            except Exception as e:
                log_both(f"  ✗ Failed to fetch records for {prog_name}: {e}", "error")
                continue
            
            for raw_tei in teis:
                tei_id = raw_tei.get("trackedEntityInstance")
                if not tei_id:
                    continue
                
                raw_event_count = sum(
                    len(enr.get("events", [])) 
                    for enr in raw_tei.get("enrollments", [])
                    if enr.get("program") in selected_programs
                )
                stats["events_fetched"] += raw_event_count
                
                cleaned, events, rels = clean_tei_and_collect_events_and_relationships(
                    raw_tei,
                    set(selected_programs),
                    metadata,
                    start_date=start_date,
                    end_date=end_date
                )
                
                ou_name = metadata.org_units.get(raw_tei.get("orgUnit"), raw_tei.get("orgUnit", "Facility"))
                label = get_tei_display_label(raw_tei, metadata)
                
                if not cleaned.get("enrollments"):
                    stats["skipped_teis"].append({
                        "tei_id": tei_id,
                        "label": label,
                        "facility": ou_name,
                        "reason": f"Enrollment date is outside the date filter ({start_date or 'Start'} to {end_date or 'End'})"
                    })
                    continue
                
                event_count = len(events)
                rel_count = len(rels)
                
                stats["teis_after_filtering"] += 1
                stats["program_stats"][prog_id]["processed_teis"] += 1
                stats["events_after_filtering"] += event_count
                stats["relationships_fetched"] += rel_count
                
                if tei_id not in tei_map:
                    tei_map[tei_id] = cleaned
                else:
                    tei_map[tei_id]["attributes"] = merge_attributes(
                        tei_map[tei_id].get("attributes", []),
                        cleaned.get("attributes", [])
                    )
                    tei_map[tei_id]["enrollments"].extend(cleaned.get("enrollments", []))
                
                events_all.extend(events)
                relationships_all.extend(rels)
        
        log_both("\n" + "-" * 65, "header")
        log_both(f"📦 Records Prepared for Sync: {len(tei_map)} Patients, {len(events_all)} Visits, {len(relationships_all)} Links", "info")
        if stats['skipped_teis']:
            log_both(f"ℹ️ {len(stats['skipped_teis'])} patient records were excluded by date filters.", "warning")
        log_both("-" * 65, "header")
        
        if not tei_map:
            log_both("⚠️ No records found to upload for the selected criteria.", "warning")
            report_data = {
                "timestamp_display": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "duration": "0s",
                "programs": prog_display_names,
                "org_scope_display": metadata.org_units.get(selected_org_uid, selected_org_uid) if selected_org_uid else "All Org Units",
                "date_range_display": f"{start_date} to {end_date}" if (start_date or end_date) else None,
                "offline_url": offline_config["url"],
                "online_url": online_config["url"],
                "stats": stats,
                "tei_results": {"imported": 0, "updated": 0, "ignored": 0, "failures": []},
                "event_results": {"imported": 0, "updated": 0, "ignored": 0, "failures": []},
                "rel_results": {"imported": 0, "updated": 0, "ignored": 0, "failures": []},
                "log_file": str(log_file)
            }
            rep_text = build_plain_language_report(report_data)
            log_both("\n" + rep_text, "report")
            return {
                "success": False,
                "message": "No patient records found matching the selected programs and filters.",
                "tei_count": 0,
                "event_count": 0,
                "relationship_count": 0,
                "stats": stats,
                "log_file": str(log_file),
                "report_text": rep_text,
                "has_failures": False
            }
        
        if dry_run:
            log_both("\n" + "=" * 65, "header")
            log_both("🔍 [DRY RUN PREVIEW] No records were pushed to online server.", "warning")
            log_both(f"   • Prepared Patients: {len(tei_map)}", "info")
            log_both(f"   • Prepared Visits:   {len(events_all)}", "info")
            log_both(f"   • Prepared Links:    {len(relationships_all)}", "info")
            log_both("=" * 65, "header")
            tei_results = {"imported": 0, "updated": 0, "ignored": len(tei_map), "failures": []}
            event_results = {"imported": 0, "updated": 0, "ignored": len(events_all), "failures": []}
            rel_results = {"imported": 0, "updated": 0, "ignored": len(relationships_all), "failures": []}
        else:
            # 1. Upload TEIs
            log_both(f"\n📤 Uploading {len(tei_map)} patient records to online server in batches...", "info")
            tei_results = upload_teis(
                online_config,
                list(tei_map.values()),
                timestamp,
                log_dir,
                metadata=metadata,
                tei_map=tei_map,
                batch_size=25,
                status_callback=update_status,
                log_callback=log_both
            )
            log_both(f"   ✓ Patient upload complete: {tei_results.get('imported', 0)} new, {tei_results.get('updated', 0)} updated, {len(tei_results.get('failures', []))} failed", "info")
            
            # 2. Upload Events
            log_both(f"\n📤 Uploading {len(events_all)} clinical visits to online server in batches...", "info")
            event_results = upload_events(
                online_config,
                events_all,
                timestamp,
                log_dir,
                metadata=metadata,
                tei_map=tei_map,
                batch_size=100,
                status_callback=update_status,
                log_callback=log_both
            )
            log_both(f"   ✓ Visit upload complete: {event_results.get('imported', 0)} new, {event_results.get('updated', 0)} updated, {len(event_results.get('failures', []))} failed", "info")
            
            # 3. Upload Relationships
            rel_results = {"imported": 0, "updated": 0, "ignored": 0, "failures": []}
            if relationships_all:
                log_both(f"\n📤 Uploading {len(relationships_all)} relationship links to online server in batches...", "info")
                rel_results = upload_relationships(
                    online_config,
                    relationships_all,
                    timestamp,
                    log_dir,
                    metadata=metadata,
                    batch_size=50,
                    status_callback=update_status,
                    log_callback=log_both
                )
                log_both(f"   ✓ Relationship upload complete: {rel_results.get('imported', 0)} new, {rel_results.get('updated', 0)} updated, {len(rel_results.get('failures', []))} failed", "info")
        
        end_time = datetime.datetime.now()
        duration_str = str(end_time - start_time).split(".")[0]
        
        has_failures = bool(
            tei_results.get("failures") or 
            event_results.get("failures") or 
            rel_results.get("failures") or
            tei_results.get("error") or
            event_results.get("error")
        )
        
        # Compile Report Data
        report_data = {
            "timestamp_display": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": f"{duration_str}s",
            "programs": prog_display_names,
            "org_scope_display": metadata.org_units.get(selected_org_uid, selected_org_uid) if selected_org_uid else "All Org Units",
            "date_range_display": f"{start_date} to {end_date}" if (start_date or end_date) else None,
            "offline_url": offline_config["url"],
            "online_url": online_config["url"],
            "stats": stats,
            "tei_results": tei_results,
            "event_results": event_results,
            "rel_results": rel_results,
            "log_file": str(log_file)
        }
        
        report_text = build_plain_language_report(report_data)
        
        # Save summary report text file
        summary_file = log_dir / f"summary_report_{timestamp}.txt"
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(report_text)
            
        log_both("\n" + report_text, "report")
        
        return {
            "success": True,
            "tei_count": len(tei_map),
            "event_count": len(events_all),
            "relationship_count": len(relationships_all),
            "tei_results": tei_results,
            "event_results": event_results,
            "rel_results": rel_results,
            "timestamp": timestamp,
            "stats": stats,
            "log_file": str(log_file),
            "report_text": report_text,
            "has_failures": has_failures
        }
        
    finally:
        file_handler.close()
        logger.removeHandler(file_handler)

