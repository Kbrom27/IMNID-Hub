# pages/data_export.py
import os
import time
import json
import requests
import pandas as pd
from requests.auth import HTTPBasicAuth
from datetime import datetime, date, timedelta
import calendar
from collections import OrderedDict
import concurrent.futures
import threading
import tempfile
import csv
import gc
from typing import Optional, List, Dict, Any, Set, Tuple

class _Var:
    def __init__(self, val=""):
        self.val = str(val) if val is not None else ""
    def get(self):
        return self.val
    def set(self, val):
        self.val = str(val) if val is not None else ""
    def strip(self, *args):
        return self.val.strip(*args)
    def __str__(self):
        return self.val

class DataExportPage:
    def __init__(self, base_url: str, username: str, password: str, log_callback=None, progress_callback=None):
        if not base_url or not str(base_url).strip():
            raise ValueError("DHIS2 URL is required.")
        if not username or not str(username).strip():
            raise ValueError("DHIS2 username is required.")
        if not password or not str(password).strip():
            raise ValueError("DHIS2 password is required.")
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.session = None
        self._meta = {}
        self.base_url = str(base_url).strip()
        self.username = str(username).strip()
        self.password = str(password).strip()
        self.base_api = ""
        self.cached_parent_org_units = {}
        self.org_units_map = {}
        self.org_units_name_by_id = {}
        self.org_units_hierarchy = {}
        self._all_ou_names = []

        self.url_var = _Var(self.base_url)
        self.user_var = _Var(self.username)
        self.pw_var = _Var(self.password)
        self.program_var = _Var("Maternal Inpatient Data")
        self.ou_mode_var = _Var("ALL")
        self.start_var = _Var("")
        self.end_var = _Var("")
        self.dir_var = _Var("")
        self.filename_var = _Var("analysis_export.csv")
        self.enrollment_status_var = _Var("ALL")
        self.event_status_var = _Var("ALL")

        # Fields to exclude (patient names for de-identification)
        self.excluded_fields = {
            # Program ID: list of field names to exclude
            "aLoraiFNkng": [  # Maternal Inpatient Data
                "Mothers First Name",
                "Mothers Father Name", 
                "Mothers Grandfather Name"
            ],
            "QYJKpoUeg9F": [  # Neonatal Care Form
                "Neonate First Name",
                "Neonate Last Name",
                "Mothers Name",
                "Mother’s Name"
            ],
            "pLk3Ht2XMKl": [  # Neonatal Inpatient Data
                "First Name of Baby:",
                "Last Name of Baby:",
                "First Name of Mother:",
                "Last Name of Mother:"
            ],
            "flBSKMXQloQ": [  # FINC
                "FINC First Name",
                "FINC Last Name"
            ]
        }

    def log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def _setup_session(self, base_url=None, user=None, pw=None):
        if base_url:
            self.base_url = base_url
            self.url_var.set(base_url)
        if user:
            self.username = user
            self.user_var.set(user)
        if pw:
            self.password = pw
            self.pw_var.set(pw)

        b_url = self.url_var.get().strip().rstrip("/")
        if not b_url.endswith("/api"):
            b_url += "/api"
        self.base_api = b_url
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(self.user_var.get().strip(), self.pw_var.get().strip())
        self.session.headers.update({'Content-Type': 'application/json'})
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

    def _fetch_with_retry(self, url, max_retries=3, silent_auth_fail=False):
        for attempt in range(max_retries):
            try:
                r = self.session.get(url, timeout=60)
                if r.status_code == 200:
                    return r
                if not silent_auth_fail:
                    self.log(f"Attempt {attempt+1} failed: HTTP {r.status_code}")
                if r.status_code == 401:
                    if not silent_auth_fail:
                        self.log("Authentication failed: check username/password")
                    return None
                if r.status_code == 403:
                    if not silent_auth_fail:
                        self.log("Access forbidden (403): User lacks authority for this request scope")
                    return None
                time.sleep(2 ** attempt)
            except requests.exceptions.RequestException as e:
                if not silent_auth_fail:
                    self.log(f"Request failed (attempt {attempt+1}): {e}")
                time.sleep(2 ** attempt)
        if not silent_auth_fail:
            self.log(f"All {max_retries} attempts failed for URL: {url}")
        return None

    def _fetch_all(self, url_base, key_name, page_size=1000, silent_auth_fail=False, silent_log=False):
        """Fetch all paginated results for TEIs or events."""
        all_items, page = [], 1
        while True:
            url = f"{url_base}&page={page}&pageSize={page_size}"
            r = self._fetch_with_retry(url, max_retries=2 if silent_auth_fail else 3, silent_auth_fail=silent_auth_fail)
            if not r:
                break
            try:
                payload = r.json()
            except Exception as e:
                if not silent_auth_fail and not silent_log:
                    self.log(f"JSON parse error: {e}")
                break
            items = payload.get(key_name, [])
            if not items:
                break
            all_items.extend(items)
            if not silent_log:
                self.log(f"Fetched page {page} – total {len(all_items)} {key_name}")
            
            # Check pager info if available from DHIS2
            pager = payload.get("pager", {})
            page_count = pager.get("pageCount")
            server_page_size = pager.get("pageSize", page_size)
            
            # If server returned fewer items than page size, this is the final page
            if len(items) < server_page_size:
                break
            # If pageCount is available and valid
            if page_count is not None and page_count > 1 and page >= page_count:
                break
            page += 1
        return all_items

    # ---------- Metadata ----------
    def _load_org_units(self):
        try:
            self._setup_session()
            # Fetch org units with parent information, level, and path
            url = f"{self.base_api}/organisationUnits.json?fields=id,name,level,path,parent[id,name]&paging=false"
            r = self._fetch_with_retry(url)
            if not r:
                self.log("Failed to fetch organisation units.")
                return
            ous = r.json().get("organisationUnits", [])
            
            # Store hierarchy information
            self.org_units_map = {}
            self.org_units_name_by_id = {}
            self.org_units_hierarchy = {}
            
            for ou in ous:
                ou_id = ou["id"]
                ou_name = ou["name"]
                parent = ou.get("parent", {})
                parent_id = parent.get("id") if parent else None
                parent_name = parent.get("name") if parent else None
                level = ou.get("level")
                path = ou.get("path", "")
                
                self.org_units_map[ou_name] = ou_id
                self.org_units_name_by_id[ou_id] = ou_name
                self.org_units_hierarchy[ou_id] = {
                    "name": ou_name,
                    "parent_id": parent_id,
                    "parent_name": parent_name,
                    "level": level,
                    "path": path
                }
            
            self._all_ou_names = sorted(self.org_units_map.keys())
            pass
            self.log(f"Loaded {len(self._all_ou_names)} organisation units with hierarchy.")
        except Exception as e:
            self.log(f"Failed loading org units: {e}")

    def _fetch_metadata(self, program_id):
        self.log("Fetching metadata…")
        meta = {
            'tea_map': {}, 
            'de_map': {}, 
            'os_map': {}, 
            'ps_map': {}, 
            'org_unit_map': {},
            'org_unit_hierarchy': {},
            'program_ous': [],
            'program_stage_order': [],  # To maintain program stage order
            'data_element_order': {},   # To maintain data element order per program stage
            'tea_order': [],           # To maintain TEA order from program
            'all_data_elements_ordered': []  # All DEs in order across all stages
        }
        try:
            # Fetch program structure with trackedEntityAttributes order and connected organisation units
            r = self._fetch_with_retry(
                f"{self.base_api}/programs/{program_id}.json?"
                f"fields=id,name,organisationUnits[id,name,level,path],programTrackedEntityAttributes[trackedEntityAttribute[id],sortOrder],"
                f"programStages[id,name,repeatable,sortOrder,programStageDataElements[dataElement[id],sortOrder]]"
            )
            
            if r:
                program_data = r.json()
                meta['program_ous'] = program_data.get('organisationUnits', [])
                for ou in meta['program_ous']:
                    ou_id = ou.get('id')
                    ou_name = ou.get('name')
                    if ou_id and ou_id not in self.org_units_name_by_id:
                        self.org_units_name_by_id[ou_id] = ou_name
                    if ou_name and ou_name not in self.org_units_map:
                        self.org_units_map[ou_name] = ou_id
                
                # Get TEAs in order
                tea_attrs = program_data.get('programTrackedEntityAttributes', [])
                # Sort by sortOrder
                sorted_tea_attrs = sorted(tea_attrs, key=lambda x: x.get('sortOrder', 999))
                
                for tea_attr in sorted_tea_attrs:
                    tea_id = tea_attr.get('trackedEntityAttribute', {}).get('id')
                    if tea_id:
                        meta['tea_order'].append(tea_id)
                
                # Get program stages in order
                program_stages = program_data.get('programStages', [])
                sorted_stages = sorted(program_stages, key=lambda x: x.get('sortOrder', 999))
                
                for st in sorted_stages:
                    stage_id = st['id']
                    stage_name = st['name']
                    is_repeatable = bool(st.get('repeatable', False))
                    
                    meta['program_stage_order'].append({
                        'id': stage_id,
                        'name': stage_name,
                        'repeatable': is_repeatable
                    })
                    
                    # Get data elements for this stage in their correct order
                    ps_data_elements = st.get('programStageDataElements', [])
                    sorted_data_elements = sorted(ps_data_elements, key=lambda x: x.get('sortOrder', 999))
                    
                    de_order = []
                    for de_item in sorted_data_elements:
                        de_id = de_item.get('dataElement', {}).get('id')
                        if de_id:
                            de_order.append(de_id)
                            # Add to global ordered list if not already there
                            if de_id not in meta['all_data_elements_ordered']:
                                meta['all_data_elements_ordered'].append(de_id)
                    
                    meta['data_element_order'][stage_id] = de_order
                    meta['ps_map'][stage_id] = {
                        'name': stage_name,
                        'repeatable': is_repeatable,
                        'data_elements': de_order
                    }
            
            # Now fetch ALL TEAs to ensure we have names for all
            # FIX: Prefer name over code for TEAs (unlike Data Elements)
            self.log("Fetching all Tracked Entity Attributes...")
            r = self._fetch_with_retry(
                f"{self.base_api}/trackedEntityAttributes.json?"
                f"fields=id,name,code,shortName,displayName,description,optionSet[id]&paging=false"
            )
            if r:
                teas = r.json().get('trackedEntityAttributes', [])
                for tea in teas:
                    tea_id = tea['id']
                    
                    # FIXED: For TEAs, prefer name over code (unlike DEs)
                    # Priority: displayName > shortName > name > code > id
                    tea_name = (
                        tea.get('displayName') or 
                        tea.get('shortName') or 
                        tea.get('name') or 
                        tea.get('code') or 
                        tea_id
                    )
                    
                    meta['tea_map'][tea_id] = {
                        'name': tea_name, 
                        'optionSet': tea.get('optionSet',{}).get('id')
                    }
                    
                    # Log for debugging
                    if tea_id in meta['tea_order']:
                        self.log(f"TEA {tea_id}: {tea_name}")
            else:
                self.log("Warning: Could not fetch all TEAs")
            
            # Fetch ALL Data Elements to ensure we have names
            self.log("Fetching all Data Elements...")
            r = self._fetch_with_retry(
                f"{self.base_api}/dataElements.json?"
                f"fields=id,name,code,formName,shortName,displayName,optionSet[id]&paging=false"
            )
            if r:
                des = r.json().get('dataElements', [])
                for de in des:
                    de_id = de['id']
                    # For Data Elements: formName > displayName > shortName > code > name > id
                    de_name = (
                        de.get('formName') or 
                        de.get('displayName') or 
                        de.get('shortName') or 
                        de.get('code') or 
                        de.get('name') or 
                        de_id
                    )
                    meta['de_map'][de_id] = {
                        'name': de_name, 
                        'optionSet': de.get('optionSet',{}).get('id')
                    }
            else:
                self.log("Warning: Could not fetch all Data Elements")
            
            # OptionSets -> map codes to labels with better handling
            self.log("Fetching OptionSets...")
            r = self._fetch_with_retry(
                f"{self.base_api}/optionSets.json?"
                f"fields=id,name,options[id,code,name,shortName,displayName]&paging=false"
            )
            if r:
                os_map = {}
                for os_item in r.json().get('optionSets', []):
                    conv = {}
                    for opt in os_item.get('options', []):
                        # Try multiple possible keys
                        code = opt.get('code')
                        opt_id = opt.get('id')
                        name = opt.get('name')
                        short_name = opt.get('shortName')
                        display_name = opt.get('displayName')
                        
                        # Determine display name: displayName > shortName > name
                        display_val = display_name or short_name or name or code or opt_id
                        
                        # Map from code to display name
                        if code:
                            conv[str(code)] = display_val
                        
                        # Also map from ID to display name (some systems use ID as value)
                        if opt_id:
                            conv[str(opt_id)] = display_val
                        
                        # Also map from name to display name
                        if name:
                            conv[str(name)] = display_val
                    
                    os_map[os_item['id']] = conv
                meta['os_map'] = os_map
            else:
                self.log("Warning: Could not fetch OptionSets")
            
            # OU map (name by id) with hierarchy
            r = self._fetch_with_retry(f"{self.base_api}/organisationUnits.json?fields=id,name,level,path,parent[id,name]&paging=false")
            if r:
                for ou in r.json().get('organisationUnits', []):
                    ou_id = ou['id']
                    ou_name = ou['name']
                    parent = ou.get('parent', {})
                    parent_id = parent.get('id') if parent else None
                    parent_name = parent.get('name') if parent else None
                    level = ou.get('level')
                    path = ou.get('path', '')
                    
                    meta['org_unit_map'][ou_id] = ou_name
                    meta['org_unit_hierarchy'][ou_id] = {
                        'name': ou_name,
                        'parent_id': parent_id,
                        'parent_name': parent_name,
                        'level': level,
                        'path': path
                    }
                    self.org_units_name_by_id[ou_id] = ou_name
                    self.org_units_map[ou_name] = ou_id
            
            self.log(f"Metadata loaded: {len(meta['tea_map'])} TEAs, {len(meta['de_map'])} DEs, {len(meta['os_map'])} OptionSets")
                    
        except Exception as e:
            self.log(f"Metadata warning: {e}")
            import traceback
            self.log(traceback.format_exc())
        return meta

    def _fetch_ou_teis(self, base_url, ou_id, ou_name, start_date=None, end_date=None, depth=0):
        """
        Fetch TEIs for an organisation unit with DESCENDANTS mode.
        If DHIS2 caps the result at ~2000 records (len >= 1990),
        adaptively partition the date range into smaller intervals to download 100% of the data.
        """
        url = f"{base_url}&ou={ou_id}&ouMode=DESCENDANTS"
        if start_date:
            url += f"&programStartDate={start_date}"
        if end_date:
            url += f"&programEndDate={end_date}"

        items = self._fetch_all(url, "trackedEntityInstances", page_size=1000, silent_auth_fail=True, silent_log=True)
        if not items and depth == 0:
            # Fallback to SELECTED mode if DESCENDANTS is restricted or returned 0
            fallback_url = f"{base_url}&ou={ou_id}&ouMode=SELECTED"
            if start_date:
                fallback_url += f"&programStartDate={start_date}"
            if end_date:
                fallback_url += f"&programEndDate={end_date}"
            fallback_items = self._fetch_all(fallback_url, "trackedEntityInstances", page_size=1000, silent_auth_fail=True, silent_log=True)
            if fallback_items:
                items = fallback_items

        # If results hit the DHIS2 cap (~2000 records) and depth limit not reached
        if len(items) >= 1990 and depth < 7:
            # Determine effective start and end dates
            s_date = start_date
            e_date = end_date

            if not s_date or not e_date:
                # If no dates provided, establish bounds from 2020 to today
                s_date = s_date or "2020-01-01"
                e_date = e_date or date.today().strftime("%Y-%m-%d")

            try:
                d1 = datetime.strptime(s_date, "%Y-%m-%d").date()
                d2 = datetime.strptime(e_date, "%Y-%m-%d").date()
                days_diff = (d2 - d1).days

                if days_diff >= 1:
                    mid = d1 + timedelta(days=days_diff // 2)
                    mid_str = mid.strftime("%Y-%m-%d")
                    next_day_str = (mid + timedelta(days=1)).strftime("%Y-%m-%d")

                    self.log(f"[{ou_name}] Reached DHIS2 limit of {len(items)} records ({s_date} to {e_date}). "
                             f"Partitioning into [{s_date} to {mid_str}] and [{next_day_str} to {e_date}]...")

                    part1 = self._fetch_ou_teis(base_url, ou_id, ou_name, start_date=s_date, end_date=mid_str, depth=depth + 1)
                    part2 = self._fetch_ou_teis(base_url, ou_id, ou_name, start_date=next_day_str, end_date=e_date, depth=depth + 1)

                    merged = OrderedDict()
                    for tei in part1:
                        tid = tei.get("trackedEntityInstance")
                        if tid:
                            merged[tid] = tei
                    for tei in part2:
                        tid = tei.get("trackedEntityInstance")
                        if tid:
                            merged[tid] = tei

                    return list(merged.values())
            except Exception as e:
                self.log(f"[{ou_name}] Date partitioning error: {e}")

        return items

    def _fetch_teis_for_ous(self, base, ou_list, start_date=None, end_date=None, temp_file=None, stage_max_events=None, status_filter="ALL", event_status_filter="ALL"):
        """
        Fetch TEIs concurrently across a list of org units.
        If temp_file is provided, streams each unique TEI directly to disk (JSON lines)
        and tracks stage_max_events on the fly to prevent Out-Of-Memory crashes.
        """
        total_ous = len(ou_list)
        if total_ous == 0:
            return 0 if temp_file is not None else []

        seen_tei_ids = set()

        def _process_tei_item(tei):
            t_id = tei.get("trackedEntityInstance")
            if not t_id or t_id in seen_tei_ids:
                return False
            seen_tei_ids.add(t_id)

            if stage_max_events is not None:
                enrs = tei.get("enrollments", [])
                if enrs:
                    enr = enrs[0]
                    if status_filter != "COMPLETED" or (enr.get("status") or "").upper() == "COMPLETED":
                        evts = enr.get("events", [])
                        if event_status_filter == "COMPLETED":
                            evts = [e for e in evts if (e.get("status") or "").upper() == "COMPLETED"]
                        counts_by_st = {}
                        for e in evts:
                            ps = e.get("programStage")
                            if ps:
                                counts_by_st[ps] = counts_by_st.get(ps, 0) + 1
                        for ps, c in counts_by_st.items():
                            if ps in stage_max_events:
                                stage_max_events[ps] = max(stage_max_events[ps], c)
                            else:
                                stage_max_events[ps] = c

            if temp_file is not None:
                temp_file.write(json.dumps(tei) + "\n")
            return True

        if total_ous == 1:
            ou = ou_list[0]
            ou_id = ou.get('id') if isinstance(ou, dict) else ou
            ou_name = self.org_units_name_by_id.get(ou_id) or (ou.get('name') if isinstance(ou, dict) else ou_id)
            self.log(f"Fetching TEIs for organisation unit: {ou_name}")
            items = self._fetch_ou_teis(base, ou_id, ou_name, start_date=start_date, end_date=end_date)
            res_teis = []
            for tei in items:
                if _process_tei_item(tei):
                    if temp_file is None:
                        res_teis.append(tei)
            del items
            return len(seen_tei_ids) if temp_file is not None else res_teis

        max_workers = min(8, total_ous)
        self.log(f"Fetching across {total_ous} organisation units using {max_workers} parallel workers...")

        def fetch_ou(ou_item):
            ou_id = ou_item.get('id') if isinstance(ou_item, dict) else ou_item
            ou_name = self.org_units_name_by_id.get(ou_id) or (ou_item.get('name') if isinstance(ou_item, dict) else ou_id)
            items = self._fetch_ou_teis(base, ou_id, ou_name, start_date=start_date, end_date=end_date)
            return ou_id, items

        res_teis = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ou = {executor.submit(fetch_ou, ou): ou for ou in ou_list}
            completed = 0
            for future in concurrent.futures.as_completed(future_to_ou):
                completed += 1
                ou_item = future_to_ou[future]
                ou_id = ou_item.get('id') if isinstance(ou_item, dict) else ou_item
                ou_name = self.org_units_name_by_id.get(ou_id) or (ou_item.get('name') if isinstance(ou_item, dict) else ou_id)
                try:
                    _, items = future.result()
                    new_count = 0
                    if items:
                        for tei in items:
                            if _process_tei_item(tei):
                                new_count += 1
                                if temp_file is None:
                                    res_teis.append(tei)
                        self.log(f"[{completed}/{total_ous}] {ou_name}: {len(items)} TEIs ({new_count} unique)")
                        del items
                    else:
                        self.log(f"[{completed}/{total_ous}] {ou_name}: 0 TEIs")
                    if self.progress_callback:
                        try:
                            self.progress_callback(completed, total_ous, ou_name, len(seen_tei_ids))
                        except Exception:
                            pass
                except Exception as e:
                    self.log(f"[{completed}/{total_ous}] Error fetching for {ou_name}: {e}")

        return len(seen_tei_ids) if temp_file is not None else res_teis

    # ---------- Data pull ----------
    def _fetch_teis(self, program_id, ou_mode, ou_ids, start_date, end_date, enrollment_status="ALL", temp_file=None, stage_max_events=None, status_filter="ALL", event_status_filter="ALL"):
        """
        Fetch TEIs **including enrollments and events** so we don't rely on sparse TEI payloads.
        We request enrollments & events explicitly.
        When enrollment_status is COMPLETED, programStatus=COMPLETED is passed to the API
        so DHIS2 returns TEIs with their completed enrollments (and events) included.
        """
        base = (
            f"{self.base_api}/trackedEntityInstances.json?"
            f"program={program_id}"
            f"&fields=trackedEntityInstance,orgUnit,attributes[attribute,value],"
            f"enrollments[enrollment,orgUnit,orgUnitName,program,status,enrollmentDate,incidentDate,"
            f"events[event,programStage,eventDate,dueDate,status,dataValues[dataElement,value]]]"
            f"relationships[relationship,relationshipType,from[trackedEntityInstance],to[trackedEntityInstance]]"
            f"&includeDeleted=false&includeEnrollments=true&includeEvents=true&skipPaging=false"
        )
        if enrollment_status == "COMPLETED":
            base += "&programStatus=COMPLETED"

        if ou_mode == "ALL":
            # Identify organisation units connected to this program and accessible to user
            self.log("Identifying organisation units connected to this program and accessible to user...")
            program_ous = self._meta.get('program_ous', [])
            if not program_ous:
                p_url = f"{self.base_api}/programs/{program_id}.json?fields=organisationUnits[id,name,level,path]"
                pr = self._fetch_with_retry(p_url, max_retries=2, silent_auth_fail=True)
                if pr:
                    program_ous = pr.json().get('organisationUnits', [])
                if not program_ous:
                    ou_filter_url = f"{self.base_api}/organisationUnits.json?filter=programs.id:eq:{program_id}&fields=id,name,level,path&paging=false"
                    ou_r = self._fetch_with_retry(ou_filter_url, max_retries=2, silent_auth_fail=True)
                    if ou_r:
                        program_ous = ou_r.json().get('organisationUnits', [])
                self._meta['program_ous'] = program_ous

            accessible_ou_ids = set(self._meta.get('org_unit_map', {}).keys())
            if not accessible_ou_ids and hasattr(self, 'org_units_map') and self.org_units_map:
                accessible_ou_ids = set(self.org_units_map.values())

            if accessible_ou_ids and program_ous:
                target_ous = [ou for ou in program_ous if ou.get('id') in accessible_ou_ids]
                if not target_ous:
                    target_ous = program_ous
            elif program_ous:
                target_ous = program_ous
            elif accessible_ou_ids:
                target_ous = [{'id': ou_id, 'name': self._meta.get('org_unit_map', {}).get(ou_id, ou_id)} for ou_id in accessible_ou_ids]
            else:
                target_ous = []

            if not target_ous:
                self.log("Warning: No accessible organisation units found connected to this program.")
                return 0 if temp_file is not None else []

            # Exclude higher-level administrative units (Level 1 National, Level 2 Regional)
            # so only actual facilities (Level 3+) are queried.
            # This prevents querying entire regions with DESCENDANTS (which duplicates facility data,
            # overloads DHIS2, and causes exports to get stuck at 284/290).
            def _get_ou_level(ou_item):
                ou_id = ou_item.get('id') if isinstance(ou_item, dict) else ou_item
                lvl = ou_item.get('level') if isinstance(ou_item, dict) else None
                if lvl is not None:
                    try:
                        return int(lvl)
                    except (ValueError, TypeError):
                        pass
                h = self._meta.get('org_unit_hierarchy', {}).get(ou_id, {})
                lvl = h.get('level')
                if lvl is not None:
                    try:
                        return int(lvl)
                    except (ValueError, TypeError):
                        pass
                h2 = getattr(self, 'org_units_hierarchy', {}).get(ou_id, {})
                lvl = h2.get('level')
                if lvl is not None:
                    try:
                        return int(lvl)
                    except (ValueError, TypeError):
                        pass
                return None

            def _get_ou_path(ou_item):
                ou_id = ou_item.get('id') if isinstance(ou_item, dict) else ou_item
                p = ou_item.get('path') if isinstance(ou_item, dict) else None
                if p:
                    return str(p)
                h = self._meta.get('org_unit_hierarchy', {}).get(ou_id, {})
                if h.get('path'):
                    return str(h['path'])
                h2 = getattr(self, 'org_units_hierarchy', {}).get(ou_id, {})
                return str(h2.get('path') or '')

            has_facilities = any((_get_ou_level(ou) or 0) >= 3 for ou in target_ous)
            ou_id_set = {ou.get('id') if isinstance(ou, dict) else ou for ou in target_ous}
            ancestor_ids = set()
            for ou in target_ous:
                ou_id = ou.get('id') if isinstance(ou, dict) else ou
                path = _get_ou_path(ou)
                if path:
                    for part in path.split('/'):
                        if part and part != ou_id and part in ou_id_set:
                            ancestor_ids.add(part)

            filtered_ous = []
            for ou in target_ous:
                ou_id = ou.get('id') if isinstance(ou, dict) else ou
                lvl = _get_ou_level(ou)
                # If an OU is an ancestor container of other units in the list, exclude it
                if ou_id in ancestor_ids:
                    continue
                # If actual facilities (level >= 3) are present, exclude level 1 and 2
                if has_facilities and lvl is not None and lvl <= 2:
                    continue
                filtered_ous.append(ou)

            if filtered_ous:
                excluded_count = len(target_ous) - len(filtered_ous)
                if excluded_count > 0:
                    self.log(f"Excluded {excluded_count} regional/administrative unit(s) (Level 1/2) so only actual facilities (Level 3+) are queried.")
                target_ous = filtered_ous

            self.log(f"Found {len(target_ous)} organisation unit(s) connected to this program.")
            return self._fetch_teis_for_ous(
                base, target_ous,
                start_date=start_date, end_date=end_date,
                temp_file=temp_file,
                stage_max_events=stage_max_events,
                status_filter=status_filter,
                event_status_filter=event_status_filter
            )

        # Specific organisation unit(s) selected
        selected_ou_ids = ou_ids or []
        return self._fetch_teis_for_ous(
            base, selected_ou_ids,
            start_date=start_date, end_date=end_date,
            temp_file=temp_file,
            stage_max_events=stage_max_events,
            status_filter=status_filter,
            event_status_filter=event_status_filter
        )

    def _map_option_value(self, os_id, val):
        """Map option values to display names with robust handling"""
        if os_id is None or val is None:
            return val
        
        # Get the mapping for this option set
        mapping = self._meta.get('os_map', {}).get(os_id, {})
        if not mapping:
            return val
        
        # Try multiple possible string representations
        sval = str(val).strip()
        
        # Try exact match first
        if sval in mapping:
            return mapping[sval]
        
        # Try case-insensitive match
        for key, display in mapping.items():
            if key.lower() == sval.lower():
                return display
        
        # Try matching without spaces/dashes
        sval_clean = sval.replace(' ', '').replace('-', '').replace('_', '').lower()
        for key, display in mapping.items():
            key_clean = str(key).replace(' ', '').replace('-', '').replace('_', '').lower()
            if key_clean == sval_clean:
                return display
        
        # If no match found, return original value
        return val

    def _get_parent_org_unit(self, ou_id):
        """Get parent (region) for an org unit"""
        if not ou_id:
            return None, None
        
        hierarchy = self._meta.get('org_unit_hierarchy', {}).get(ou_id)
        if hierarchy:
            return hierarchy.get('parent_id'), hierarchy.get('parent_name')
        
        # Try to fetch parent info if not in cache
        try:
            url = f"{self.base_api}/organisationUnits/{ou_id}.json?fields=id,name,parent[id,name]"
            r = self._fetch_with_retry(url)
            if r:
                ou_data = r.json()
                parent = ou_data.get('parent', {})
                return parent.get('id'), parent.get('name')
        except:
            pass
        
        return None, None

    def _should_exclude_field(self, program_id, field_name):
        """Check if a field should be excluded (patient name for de-identification)"""
        excluded = self.excluded_fields.get(program_id, [])
        # Case-insensitive comparison to be safe
        field_lower = field_name.lower().strip()
        for excluded_field in excluded:
            if excluded_field.lower().strip() == field_lower:
                return True
        return False

    # ---------- Export orchestrator ----------
    def export(
        self,
        program_name: str,
        ou_mode: str = "ALL",
        selected_ou_names: Optional[List[str]] = None,
        ou_ids: Optional[List[str]] = None,
        start: str = "",
        end: str = "",
        out_dir: str = "",
        filename: str = "analysis_export.csv",
        status_filter: str = "ALL",
        event_status_filter: str = "ALL",
        program_id: Optional[str] = None,
    ):
        base_url = self.base_url.strip()
        user = self.username.strip()
        pw = self.password.strip()
        if not base_url or not user or not pw:
            raise ValueError("Please provide DHIS2 URL, username and password.")

        program_name = (program_name or "").strip()
        program_ids = {
            "Maternal Inpatient Data": "aLoraiFNkng",
            "Neonatal care Form": "QYJKpoUeg9F",
            "Newborn Inpatient Data": "pLk3Ht2XMKl",
            "FINC": "flBSKMXQloQ",
            "SLL Assist AI": "yxRNHSagJmU"
        }
        norm_map = {k.lower(): v for k, v in program_ids.items()}
        resolved_pid = program_id or program_ids.get(program_name) or norm_map.get(program_name.lower())
        if not resolved_pid and len(program_name) == 11:
            resolved_pid = program_name
        if not resolved_pid:
            raise ValueError("Please select a valid program.")
        program_id = resolved_pid

        ou_ids_to_use = []
        if ou_mode in ("ONE", "SELECTED"):
            if ou_ids:
                ou_ids_to_use = list(ou_ids)
            elif selected_ou_names:
                if any(name not in self.org_units_map for name in selected_ou_names):
                    raise ValueError("Selected organisation unit is not loaded. Click 'Load OUs' first.")
                ou_ids_to_use = [self.org_units_map[name] for name in selected_ou_names]
            else:
                raise ValueError("Please choose at least one organisation unit (or switch to All).")

        start = (start or "").strip()
        end = (end or "").strip()
        for tag, val in [("Start date", start), ("End date", end)]:
            if val:
                try:
                    datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    raise ValueError(f"{tag} must be YYYY-MM-DD")
        if start and end and start > end:
            raise ValueError("Start date must be <= End date.")

        out_dir = (out_dir or "").strip()
        fname = (filename or "").strip()
        if not out_dir:
            raise ValueError("Please choose an output directory.")
        if not fname:
            raise ValueError("Please provide an output file name.")
        if not fname.lower().endswith(".csv"):
            fname += ".csv"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, fname)

        status_flt = (status_filter or "ALL").upper()
        event_status_flt = (event_status_filter or "ALL").upper()

        return self._run_export_worker(
            base_url, user, pw, program_name, program_id, ou_mode, ou_ids_to_use,
            start, end, out_path, status_flt, event_status_flt
        )

    def _export(self):
        ou_ids = []
        ou_mode = self.ou_mode_var.get()
        return self.export(
            program_name=self.program_var.get(),
            ou_mode=ou_mode,
            ou_ids=ou_ids,
            start=self.start_var.get(),
            end=self.end_var.get(),
            out_dir=self.dir_var.get(),
            filename=self.filename_var.get(),
            status_filter=self.enrollment_status_var.get(),
            event_status_filter=self.event_status_var.get(),
        )

    def _run_export_worker(self, base_url, user, pw, program_name, program_id, ou_mode, ou_ids, start, end, out_path, status_filter, event_status_filter):
        try:
            self.log(f"Connecting to: {base_url}")
            self.log(f"Program selected: {program_name} (ID: {program_id})")
            self.log(f"De-identification: Excluding patient name fields")
            
            # Log which fields will be excluded for this program
            excluded_fields = self.excluded_fields.get(program_id, [])
            if excluded_fields:
                self.log(f"Excluding {len(excluded_fields)} patient name fields: {', '.join(excluded_fields)}")
            else:
                self.log("No patient name fields configured for exclusion in this program")
            
            self._setup_session()

            # sanity ping
            ping = self._fetch_with_retry(f"{self.base_api}/system/info")
            if not ping:
                self.log("Error: Failed to connect to DHIS2 API.")
                raise RuntimeError("Failed to connect to DHIS2 API.")

            # Metadata
            self._meta = self._fetch_metadata(program_id)
            if not self._meta['de_map'] or not self._meta['tea_map']:
                self.log("⚠ Warning: Some metadata could not be fetched; continuing…")

            # Initialize stage_max_events tracking dict
            stage_max_events = {st['id']: 0 for st in self._meta.get('program_stage_order', [])}

            with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=True) as temp_tei_file:
                self.log("Fetching TEIs...")
                if status_filter == "COMPLETED":
                    self.log("Enrollment filter: COMPLETED - passing programStatus=COMPLETED to API")

                total_teis = self._fetch_teis(
                    program_id, ou_mode, ou_ids, start, end,
                    enrollment_status=status_filter,
                    temp_file=temp_tei_file,
                    stage_max_events=stage_max_events,
                    status_filter=status_filter,
                    event_status_filter=event_status_filter
                )
                if total_teis == 0:
                    self.log("No tracked entity instances found for the given filters.")
                    return {"status": "no_data", "records": 0}

                self.log(f"Processing {total_teis} unique TEIs…")

                # Build the complete column structure
                column_structure = OrderedDict()

                # 1. Core metadata columns
                core_columns = [
                    "tei_id",
                    "enrollment_id",
                    "enrollment_status",
                    "enrollment_date",
                    "incident_date",
                    "org_unit",
                    "org_unit_id",
                    "parent_org_unit",
                    "parent_org_unit_id",
                ]
                for col in core_columns:
                    column_structure[col] = ""

                # 2. Relationships column
                column_structure["relationships"] = ""

                # 3. TEAs in program order - use proper names, but skip excluded ones
                for tea_id in self._meta.get('tea_order', []):
                    tea_info = self._meta['tea_map'].get(tea_id, {})
                    tea_name = tea_info.get('name', tea_id)
                    if self._should_exclude_field(program_id, tea_name):
                        self.log(f"Excluding patient name field (TEA): {tea_name}")
                        continue
                    tea_name_sanitized = str(tea_name).replace('\n', ' ').replace('\r', ' ').strip()
                    column_structure[tea_name_sanitized] = ""

                # 4. Program stages and their data elements in order
                for stage_info in self._meta.get('program_stage_order', []):
                    stage_id = stage_info['id']
                    stage_name = stage_info['name']
                    stage_name_sanitized = str(stage_name).replace('\n', ' ').replace('\r', ' ').strip()
                    is_repeatable = stage_info.get('repeatable', False)
                    max_cnt = stage_max_events.get(stage_id, 0)
                    is_repeat = is_repeatable or max_cnt > 1
                    de_ids = self._meta['data_element_order'].get(stage_id, [])

                    if is_repeat:
                        num_events = max(1, max_cnt)
                        self.log(f"Repeatable stage '{stage_name}': generating {num_events} event slot(s)")
                        for ev_idx in range(1, num_events + 1):
                            column_structure[f"{stage_name_sanitized}_{ev_idx}_event_id"] = ""
                            column_structure[f"{stage_name_sanitized}_{ev_idx}_event_date"] = ""
                            column_structure[f"{stage_name_sanitized}_{ev_idx}_event_status"] = ""
                            column_structure[f"{stage_name_sanitized}_{ev_idx}_due_date"] = ""
                            for de_id in de_ids:
                                de_info = self._meta['de_map'].get(de_id, {})
                                de_name = de_info.get('name', de_id)
                                if self._should_exclude_field(program_id, de_name):
                                    continue
                                de_name_sanitized = str(de_name).replace('\n', ' ').replace('\r', ' ').strip()
                                column_structure[f"{stage_name_sanitized}_{ev_idx}_{de_name_sanitized}"] = ""
                    else:
                        column_structure[f"{stage_name_sanitized}_event_id"] = ""
                        column_structure[f"{stage_name_sanitized}_event_date"] = ""
                        column_structure[f"{stage_name_sanitized}_event_status"] = ""
                        column_structure[f"{stage_name_sanitized}_due_date"] = ""
                        for de_id in de_ids:
                            de_info = self._meta['de_map'].get(de_id, {})
                            de_name = de_info.get('name', de_id)
                            if self._should_exclude_field(program_id, de_name):
                                continue
                            de_name_sanitized = str(de_name).replace('\n', ' ').replace('\r', ' ').strip()
                            column_structure[f"{stage_name_sanitized}_{de_name_sanitized}"] = ""

                ordered_columns = list(column_structure.keys())
                self.log(f"Column structure has {len(ordered_columns)} columns (after excluding patient names)")

                # Rewind temporary file to stream out rows
                temp_tei_file.flush()
                temp_tei_file.seek(0)

                total_written = 0
                with open(out_path, mode="w", newline="", encoding="utf-8-sig") as csv_f:
                    writer = csv.writer(csv_f)
                    writer.writerow(ordered_columns)

                    for line in temp_tei_file:
                        line = line.strip()
                        if not line:
                            continue
                        tei = json.loads(line)
                        tei_id = tei.get("trackedEntityInstance")
                        if not tei_id:
                            continue

                        enrollments = tei.get("enrollments", [])
                        if not enrollments:
                            continue
                        enr = enrollments[0]
                        if status_filter == "COMPLETED" and (enr.get("status") or "").upper() != "COMPLETED":
                            continue

                        record = {}
                        record["tei_id"] = tei_id

                        # TEI attributes
                        tei_attrs = {}
                        for attr in tei.get("attributes", []):
                            attr_id = attr.get("attribute")
                            val = attr.get("value")
                            if attr_id is None:
                                continue
                            tea_info = self._meta['tea_map'].get(attr_id, {})
                            os_id = tea_info.get('optionSet')
                            val = self._map_option_value(os_id, val)
                            tei_attrs[attr_id] = val

                        for tea_id in self._meta.get('tea_order', []):
                            tea_info = self._meta['tea_map'].get(tea_id, {})
                            tea_name = tea_info.get('name', tea_id)
                            if self._should_exclude_field(program_id, tea_name):
                                continue
                            tea_name_sanitized = str(tea_name).replace('\n', ' ').replace('\r', ' ').strip()
                            if tea_name_sanitized in column_structure:
                                if tea_id in tei_attrs:
                                    record[tea_name_sanitized] = tei_attrs[tea_id]
                            elif tea_name in column_structure:
                                if tea_id in tei_attrs:
                                    record[tea_name] = tei_attrs[tea_id]

                        # Enrollment info
                        org_unit_id = enr.get("orgUnit")
                        org_unit_name = self._meta['org_unit_map'].get(org_unit_id, org_unit_id)
                        parent_org_unit_id, parent_org_unit_name = self._get_parent_org_unit(org_unit_id)

                        record["enrollment_id"] = enr.get("enrollment") or ""
                        record["enrollment_date"] = enr.get("enrollmentDate") or ""
                        record["incident_date"] = enr.get("incidentDate") or ""
                        record["org_unit"] = org_unit_name or ""
                        record["org_unit_id"] = org_unit_id or ""
                        record["parent_org_unit"] = parent_org_unit_name or ""
                        record["parent_org_unit_id"] = parent_org_unit_id or ""
                        record["enrollment_status"] = enr.get("status") or ""

                        # Relationships
                        relationships = tei.get("relationships", [])
                        if relationships:
                            rel_strs = []
                            for rel in relationships:
                                rel_type = rel.get("relationshipType")
                                from_te = rel.get("from", {}).get("trackedEntityInstance")
                                to_te = rel.get("to", {}).get("trackedEntityInstance")
                                rel_strs.append(
                                    f"{rel_type}: "
                                    f"{{'trackedEntityInstance':'{from_te}'}} -> "
                                    f"{{'trackedEntityInstance':'{to_te}'}}"
                                )
                            record["relationships"] = "; ".join(rel_strs)

                        # Events
                        events = enr.get("events", [])
                        if event_status_filter == "COMPLETED":
                            events = [ev for ev in events if (ev.get("status") or "").upper() == "COMPLETED"]

                        events_by_stage = {}
                        for ev in events:
                            stage_id = ev.get("programStage")
                            if stage_id not in events_by_stage:
                                events_by_stage[stage_id] = []
                            events_by_stage[stage_id].append(ev)

                        for stage_info in self._meta.get('program_stage_order', []):
                            stage_id = stage_info['id']
                            stage_name = stage_info['name']
                            stage_name_sanitized = str(stage_name).replace('\n', ' ').replace('\r', ' ').strip()
                            is_repeatable = stage_info.get('repeatable', False)
                            max_cnt = stage_max_events.get(stage_id, 0)
                            is_repeat = is_repeatable or max_cnt > 1

                            stage_events = events_by_stage.get(stage_id, [])
                            stage_events.sort(key=lambda x: x.get("eventDate") or x.get("dueDate") or "")

                            de_ids = self._meta['data_element_order'].get(stage_id, [])

                            if is_repeat:
                                num_events = max(1, max_cnt)
                                for ev_idx in range(1, num_events + 1):
                                    ev = stage_events[ev_idx - 1] if ev_idx - 1 < len(stage_events) else None
                                    if not ev:
                                        continue

                                    record[f"{stage_name_sanitized}_{ev_idx}_event_id"] = ev.get("event") or ""
                                    record[f"{stage_name_sanitized}_{ev_idx}_event_date"] = ev.get("eventDate") or ""
                                    record[f"{stage_name_sanitized}_{ev_idx}_event_status"] = ev.get("status") or ""
                                    record[f"{stage_name_sanitized}_{ev_idx}_due_date"] = ev.get("dueDate") or ""

                                    data_values = ev.get("dataValues", [])
                                    de_dict = {}
                                    for dv in data_values:
                                        de_id = dv.get("dataElement")
                                        val = dv.get("value")
                                        if de_id is None:
                                            continue
                                        de_info = self._meta['de_map'].get(de_id, {})
                                        os_id = de_info.get('optionSet')
                                        val = self._map_option_value(os_id, val)
                                        de_dict[de_id] = val

                                    for de_id in de_ids:
                                        de_info = self._meta['de_map'].get(de_id, {})
                                        de_name = de_info.get('name', de_id)
                                        if self._should_exclude_field(program_id, de_name):
                                            continue
                                        de_name_sanitized = str(de_name).replace('\n', ' ').replace('\r', ' ').strip()
                                        col_name = f"{stage_name_sanitized}_{ev_idx}_{de_name_sanitized}"
                                        if de_id in de_dict:
                                            record[col_name] = de_dict[de_id]
                            else:
                                ev = stage_events[0] if stage_events else None
                                if not ev:
                                    continue

                                record[f"{stage_name_sanitized}_event_id"] = ev.get("event") or ""
                                record[f"{stage_name_sanitized}_event_date"] = ev.get("eventDate") or ""
                                record[f"{stage_name_sanitized}_event_status"] = ev.get("status") or ""
                                record[f"{stage_name_sanitized}_due_date"] = ev.get("dueDate") or ""

                                data_values = ev.get("dataValues", [])
                                de_dict = {}
                                for dv in data_values:
                                    de_id = dv.get("dataElement")
                                    val = dv.get("value")
                                    if de_id is None:
                                        continue
                                    de_info = self._meta['de_map'].get(de_id, {})
                                    os_id = de_info.get('optionSet')
                                    val = self._map_option_value(os_id, val)
                                    de_dict[de_id] = val

                                for de_id in de_ids:
                                    de_info = self._meta['de_map'].get(de_id, {})
                                    de_name = de_info.get('name', de_id)
                                    if self._should_exclude_field(program_id, de_name):
                                        continue
                                    de_name_sanitized = str(de_name).replace('\n', ' ').replace('\r', ' ').strip()
                                    col_name = f"{stage_name_sanitized}_{de_name_sanitized}"
                                    if de_id in de_dict:
                                        record[col_name] = de_dict[de_id]

                        row = [record.get(col, "") for col in ordered_columns]
                        writer.writerow(row)
                        total_written += 1

                        if total_written % 1000 == 0:
                            self.log(f"Exported {total_written}/{total_teis} TEI rows...")

                if total_written == 0:
                    self.log("No events/data found for selected TEIs/enrollments.")
                    return {"status": "no_data", "records": 0}

                msg_done = f"Exported {total_written} TEI rows to {out_path}"
                self.log(msg_done)
                self.log(f"Export finished: {total_written} TEI rows -> {out_path}")
                self.log(f"Total columns in export: {len(ordered_columns)} (patient name fields excluded)")
                return {"status": "success", "records": total_written, "out_path": out_path}

        except Exception as e:
            self.log(f"ERROR: {e}")
            import traceback
            self.log(traceback.format_exc())
            raise