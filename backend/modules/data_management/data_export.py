# pages/data_export.py
"""
IMNID – DHIS2 Tracker Export (Full Version)
- Includes calendar date pickers (no external deps)
- Properly fetches TEIs WITH enrollments (and optionally events)
- Optionally filters by completed enrollments and/or completed events
- Translates option sets for TEI attributes + Data Elements
- Exports wide CSV (one row per event) with TEI + Enrollment context
- Robust logging, retries, pagination, and input validation

Tested against DHIS2 2.38+/2.40-style APIs.
"""

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
from typing import Optional, List, Dict, Any, Set, Tuple
import csv

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
        self.org_units_map = {}
        self.org_units_name_by_id = {}
        self.org_units_meta_by_id = {}
        self._all_ou_names = []

        self.url_var = _Var(self.base_url)
        self.user_var = _Var(self.username)
        self.pw_var = _Var(self.password)
        self.program_var = _Var("Maternal Inpatient Data")
        self.ou_mode_var = _Var("ALL")
        self.start_var = _Var("")
        self.end_var = _Var("")
        self.dir_var = _Var("")
        self.filename_var = _Var("export.csv")
        self.enrollment_status_var = _Var("ALL")
        self.event_status_var = _Var("ALL")

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
            url = f"{self.base_api}/organisationUnits.json?fields=id,name,level,path&paging=false"
            r = self._fetch_with_retry(url)
            if not r:
                self.log("Failed to fetch organisation units.")
                return
            ous = r.json().get("organisationUnits", [])
            self.org_units_map = {ou["name"]: ou["id"] for ou in ous}
            self.org_units_name_by_id = {ou["id"]: ou["name"] for ou in ous}
            self.org_units_meta_by_id = {ou["id"]: {"name": ou["name"], "level": ou.get("level"), "path": ou.get("path")} for ou in ous}
            self._all_ou_names = sorted(self.org_units_map.keys())
            pass
            self.log(f"Loaded {len(self._all_ou_names)} organisation units.")
        except Exception as e:
            self.log(f"Failed loading org units: {e}")

    def _fetch_metadata(self, program_id):
        self.log("Fetching metadata…")
        meta = {'tea_map': {}, 'de_map': {}, 'os_map': {}, 'ps_map': {}, 'org_unit_map': {}}
        try:
            # TEAs
            r = self._fetch_with_retry(f"{self.base_api}/trackedEntityAttributes.json?fields=id,name,optionSet[id]&paging=false")
            if r:
                for tea in r.json().get('trackedEntityAttributes', []):
                    meta['tea_map'][tea['id']] = {'name': tea['name'], 'optionSet': tea.get('optionSet',{}).get('id')}
            # DEs
            r = self._fetch_with_retry(f"{self.base_api}/dataElements.json?fields=id,name,optionSet[id]&paging=false")
            if r:
                for de in r.json().get('dataElements', []):
                    meta['de_map'][de['id']] = {'name': de['name'], 'optionSet': de.get('optionSet',{}).get('id')}
            # OptionSets -> map codes to labels
            r = self._fetch_with_retry(f"{self.base_api}/optionSets.json?fields=id,name,options[id,code,name]&paging=false")
            if r:
                os_map = {}
                for os_item in r.json().get('optionSets', []):
                    conv = {}
                    for opt in os_item.get('options', []):
                        key = opt.get('code') or opt.get('id') or opt.get('name')
                        val = opt.get('name') or opt.get('code') or opt.get('id')
                        if key is not None:
                            conv[str(key)] = val
                    os_map[os_item['id']] = conv
                meta['os_map'] = os_map
            # Program stages and connected org units
            r = self._fetch_with_retry(f"{self.base_api}/programs/{program_id}.json?fields=organisationUnits[id,name,level,path],programStages[id,name,programStageDataElements[dataElement[id]]]")
            if r:
                p_data = r.json()
                meta['program_ous'] = p_data.get('organisationUnits', [])
                for ou in meta['program_ous']:
                    ou_id = ou.get('id')
                    ou_name = ou.get('name')
                    if ou_id and ou_id not in self.org_units_name_by_id:
                        self.org_units_name_by_id[ou_id] = ou_name
                    if ou_name and ou_name not in self.org_units_map:
                        self.org_units_map[ou_name] = ou_id
                    if ou_id:
                        self.org_units_meta_by_id[ou_id] = {'name': ou_name, 'level': ou.get('level'), 'path': ou.get('path')}
                for st in p_data.get('programStages', []):
                    meta['ps_map'][st['id']] = {
                        'name': st['name'],
                        'data_elements': [de['dataElement']['id'] for de in st.get('programStageDataElements', [])]
                    }
            # OU map (name by id)
            r = self._fetch_with_retry(f"{self.base_api}/organisationUnits.json?fields=id,name,level,path&paging=false")
            if r:
                for ou in r.json().get('organisationUnits', []):
                    meta['org_unit_map'][ou['id']] = ou['name']
                    self.org_units_name_by_id[ou['id']] = ou['name']
                    self.org_units_map[ou['name']] = ou['id']
                    self.org_units_meta_by_id[ou['id']] = {'name': ou['name'], 'level': ou.get('level'), 'path': ou.get('path')}
        except Exception as e:
            self.log(f"Metadata warning: {e}")
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

    def _fetch_teis_for_ous(self, base, ou_list, start_date=None, end_date=None, temp_file=None):
        """Fetch TEIs concurrently across a list of org units, streaming to temp_file if provided."""
        total_ous = len(ou_list)
        if total_ous == 0:
            return 0 if temp_file is not None else []

        seen_tei_ids = set()

        def _process_tei_item(tei):
            t_id = tei.get("trackedEntityInstance")
            if not t_id or t_id in seen_tei_ids:
                return False
            seen_tei_ids.add(t_id)
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
    def _fetch_teis(self, program_id, ou_mode, ou_ids, start_date, end_date, temp_file=None):
        """
        Fetch TEIs **including enrollments and events** so we don't rely on sparse TEI payloads.
        When multiple org units are selected each is fetched separately and deduplicated.
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

            # Filter out higher-level parent organisation units (e.g. Level 1 National, Level 2 Regional)
            # to avoid duplicate counting and server timeouts caused by ouMode=DESCENDANTS on regional containers.
            has_facility_level = any(
                (self.org_units_meta_by_id.get(ou.get('id'), {}).get('level') or ou.get('level') or 0) >= 3
                for ou in target_ous
            )
            if has_facility_level:
                filtered_ous = []
                for ou in target_ous:
                    ou_id = ou.get('id')
                    lvl = self.org_units_meta_by_id.get(ou_id, {}).get('level') or ou.get('level') or 0
                    if lvl in (1, 2):
                        continue
                    filtered_ous.append(ou)
                if filtered_ous:
                    target_ous = filtered_ous

            # Also exclude any OU whose ID appears as an ancestor in another target OU's path
            all_paths = [
                self.org_units_meta_by_id.get(ou.get('id'), {}).get('path') or ou.get('path') or ""
                for ou in target_ous
            ]
            filtered_target_ous = []
            for ou in target_ous:
                ou_id = ou.get('id')
                is_ancestor = any(f"/{ou_id}/" in p for p in all_paths if p)
                if not is_ancestor:
                    filtered_target_ous.append(ou)
            if filtered_target_ous:
                target_ous = filtered_target_ous

            self.log(f"Found {len(target_ous)} facility organisation unit(s) connected to this program.")
            return self._fetch_teis_for_ous(base, target_ous, start_date=start_date, end_date=end_date, temp_file=temp_file)

        # Specific organisation unit(s) selected
        selected_ou_ids = ou_ids or []
        return self._fetch_teis_for_ous(base, selected_ou_ids, start_date=start_date, end_date=end_date, temp_file=temp_file)

    def _map_option_value(self, os_id, val):
        if os_id is None or val is None:
            return val
        mapping = self._meta.get('os_map', {}).get(os_id, {})
        # Ensure string match (DHIS2 codes often strings)
        sval = str(val)
        return mapping.get(sval, val)

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
        filename: str = "export.csv",
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
            "SLL Assist AI": "yxRNHSagJmU",
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
                missing = [n for n in selected_ou_names if n not in self.org_units_map]
                if missing:
                    raise ValueError("Some selected organisation units are not loaded. Click 'Load OUs' first.")
                ou_ids_to_use = [self.org_units_map[n] for n in selected_ou_names]
            else:
                raise ValueError("Please select at least one organisation unit (or switch to All).")

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

            # TEIs (with enrollments/events)
            self.log("Fetching TEIs…")
            teis = self._fetch_teis(program_id, ou_mode, ou_ids, start, end)
            if not teis:
                self.log("No tracked entity instances found for the given filters.")
                return {"status": "no_data", "records": 0}

            self.log(f"Processing {len(teis)} TEIs…")
            records = []
            total_events = 0

            for tei in teis:
                tei_id = tei.get("trackedEntityInstance")
                # TEI attributes
                tei_attrs = {}
                for attr in tei.get("attributes", []):
                    attr_id = attr.get("attribute")
                    val = attr.get("value")
                    if attr_id is None:
                        continue
                    name = self._meta['tea_map'].get(attr_id, {}).get('name', attr_id)
                    os_id = self._meta['tea_map'].get(attr_id, {}).get('optionSet')
                    val = self._map_option_value(os_id, val)
                    tei_attrs[name] = val

                enrollments = tei.get("enrollments", [])
                if not enrollments:
                    self.log(f"TEI {tei_id}: no enrollments in payload; skipping")
                    continue

                for enr in enrollments:
                    if status_filter == "COMPLETED" and (enr.get("status") or "").upper() != "COMPLETED":
                        continue

                    enr_base = tei_attrs.copy()
                    enr_base.update({
                        "tei_id": tei_id,
                        "enrollment_id": enr.get("enrollment"),
                        "enrollment_date": enr.get("enrollmentDate"),
                        "incident_date": enr.get("incidentDate"),
                        "org_unit": self._meta['org_unit_map'].get(enr.get("orgUnit"), enr.get("orgUnit")),  # name
                        "org_unit_id": enr.get("orgUnit"),  # always export UID explicitly
                        "enrollment_status": enr.get("status"),
                    })

                    events = enr.get("events", [])
                    if event_status_filter == "COMPLETED":
                        events = [ev for ev in events if (ev.get("status") or "").upper() == "COMPLETED"]

                    self.log(f"  Enrollment {enr_base['enrollment_id']}: {len(events)} events")
                    total_events += len(events)

                    if not events:
                        rec = enr_base.copy()
                        rec.update({
                            "program": program_id,   # keep UID
                            "event_id": None,
                            "event_date": None,
                            "event_status": None,
                            "program_stage": None,
                        })
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
                            rec["relationships"] = "; ".join(rel_strs)
                        records.append(rec)
                        continue

                    for ev in events:
                        rec = enr_base.copy()
                        rec.update({
                            "program": program_id,   # ✅ FIXED: use UID, not displayName
                            "event_id": ev.get("event"),
                            "event_date": ev.get("eventDate") or ev.get("dueDate"),
                            "event_status": ev.get("status"),
                            "program_stage": self._meta['ps_map'].get(ev.get("programStage"), {}).get("name", ev.get("programStage")),
                        })
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
                            rec["relationships"] = "; ".join(rel_strs)
                        for dv in ev.get("dataValues", []):
                            de_id = dv.get("dataElement")
                            val = dv.get("value")
                            if de_id is None:
                                continue
                            de_name = self._meta['de_map'].get(de_id, {}).get('name', de_id)
                            os_id = self._meta['de_map'].get(de_id, {}).get('optionSet')
                            val = self._map_option_value(os_id, val)
                            rec[de_name] = val
                        records.append(rec)

            if not records:
                self.log("No events/data found for selected TEIs/enrollments.")
                return {"status": "no_data", "records": 0}

            df = pd.DataFrame(records)
            # Order common columns first
            front_cols = [c for c in [
                "program", "org_unit","enrollment_status","enrollment_date","incident_date",
                "program_stage","event_status","event_date","event_id","enrollment_id","tei_id", "relationships"
            ] if c in df.columns]
            other_cols = [c for c in df.columns if c not in front_cols]
            df = df[front_cols + other_cols]

            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            msg_done = f"Exported {len(df)} event rows to {out_path}"
            self.log(msg_done)
            return {"status": "success", "records": len(df), "out_path": out_path}

        except Exception as e:
            self.log(f"ERROR: {e}")
            import traceback
            self.log(traceback.format_exc())
            raise