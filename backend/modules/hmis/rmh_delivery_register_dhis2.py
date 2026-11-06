"""
================================================================================
  PROJECT  : Maternal Health DHIS2 Registry
  FILE     : delivery_register_dhis2.py
  PURPOSE  : Pull tracker data directly from DHIS2 REST API and generate the
             Ethiopian MoH Delivery Register Excel workbook (MoH V1 2021).
             Companion to delivery_register.py — shares the same Excel
             generation logic; only the data source changes.

  REQUIRES : pip install requests openpyxl pandas numpy
             delivery_register.py must be in the same directory

  AUTH     (priority: CLI → env vars → credentials file → interactive prompt)
    CLI  : --url https://your.dhis2.org --username admin --password district
    Env  : DHIS2_URL  DHIS2_USER  DHIS2_PASS
    File : dhis2_credentials.json  →  {"url":..., "username":..., "password":...}

  QUICK START:
    # 1. List available tracker programs
    python delivery_register_dhis2.py --list-programs

    # 2. List org units enrolled in a program
    python delivery_register_dhis2.py --program <UID> --list-org-units

    # 3. Pull all deliveries for one facility, one month
    python delivery_register_dhis2.py \
      --program <UID> \
      --org-unit "Debere Markos referral hospital" \
      --start 2025-01-01 --end 2025-01-31 \
      --output january_register.xlsx

    # 4. One sheet per facility, whole region
    python delivery_register_dhis2.py \
      --program <UID> \
      --org-unit <region_UID> \
      --sheet-per-facility \
      --output amhara_register.xlsx
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
from openpyxl import Workbook

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("ERROR: 'requests' is not installed.\n"
          "Install with:  pip install requests")
    sys.exit(1)

warnings.filterwarnings("ignore")

CRED_FILE = Path("dhis2_credentials.json")

# Common DHIS2 context-path suffixes to probe during auto-detection
_DHIS2_PATHS = ["", "/dhis", "/dhis2", "/imnid", "/hmis", "/tracker"]


def _normalise_url(url: str) -> str:
    """Strip accidental /api or /api/ suffix the user may have included."""
    url = url.rstrip("/")
    for suffix in ("/api", "/api/"):
        if url.endswith(suffix.rstrip("/")):
            url = url[: -len(suffix.rstrip("/"))]
    return url


# ── HTTP client ───────────────────────────────────────────────────────────────

class DHIS2Client:
    """Authenticated DHIS2 REST client with retry, SSL options, and diagnostics."""

    def __init__(self, url: str, username: str, password: str,
                 verify_ssl: bool = True, timeout: int = 30):
        self.base       = _normalise_url(url)
        self.verify_ssl = verify_ssl
        self.timeout    = timeout
        self.session    = requests.Session()
        self.session.auth   = (username, password)
        self.session.verify = verify_ssl
        self.session.headers.update({
            "Accept":       "application/json",
            "Content-Type": "application/json",
        })
        # Only retry on server-side transient errors — NOT on connection errors,
        # because RemoteDisconnected usually means wrong URL/SSL, not a fluke.
        retry = Retry(total=2, backoff_factor=1.0,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET"])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://",  adapter)

        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print("WARNING: SSL certificate verification disabled.")

        self._version: int = None

    @property
    def api_version(self) -> int:
        if self._version is None:
            try:
                info = self.get("system/info")
                ver  = str(info.get("version", "2.38"))
                parts = ver.split(".")
                self._version = int(parts[1]) if parts[0] == "2" else int(parts[0])
            except Exception:
                self._version = 38
        return self._version

    def get(self, endpoint: str, params: dict = None) -> dict:
        url  = f"{self.base}/api/{endpoint}"
        resp = self.session.get(url, params=params or {}, timeout=self.timeout)
        if resp.status_code == 401:
            raise PermissionError("Authentication failed — check username/password.")
        if resp.status_code == 403:
            raise PermissionError(f"Access denied: {endpoint}")
        resp.raise_for_status()
        return resp.json()

    # ── diagnostics ───────────────────────────────────────────────────────────

    def diagnose(self, username: str, password: str) -> bool:
        """
        Try different URL variations to find a working DHIS2 base URL.
        Updates self.base if a working variant is found.
        Returns True if a working URL was found.
        """
        raw_base = self.base
        # Build candidate URLs: both http and https, common context paths
        parsed   = requests.utils.urlparse(raw_base)
        schemes  = ["https", "http"] if parsed.scheme == "https" else ["http", "https"]
        host     = parsed.netloc or parsed.path   # handles bare "server.org"
        path     = parsed.path if parsed.netloc else ""

        candidates = []
        for scheme in schemes:
            for ctx in _DHIS2_PATHS:
                base_try = f"{scheme}://{host}{path}{ctx}".rstrip("/")
                if base_try not in candidates:
                    candidates.append(base_try)

        print("\nRunning connection diagnostics ...")
        print(f"{'URL':<55}  Result")
        print("-" * 75)

        for base in candidates:
            test_url = f"{base}/api/system/info"
            try:
                r = requests.get(
                    test_url,
                    auth=(username, password),
                    headers={"Accept": "application/json"},
                    timeout=10,
                    verify=self.verify_ssl,
                )
                if r.status_code == 200:
                    data = r.json()
                    ver  = data.get("version", "?")
                    print(f"  {test_url:<53}  OK  (DHIS2 {ver})")
                    self.base = base
                    self.session.verify = self.verify_ssl
                    return True
                else:
                    print(f"  {test_url:<53}  HTTP {r.status_code}")
            except requests.exceptions.SSLError as e:
                short = str(e)[:55]
                print(f"  {test_url:<53}  SSL error — try --no-ssl-verify")
            except requests.exceptions.ConnectionError as e:
                reason = "connection refused / timeout"
                if "RemoteDisconnected" in str(e):
                    reason = "remote closed connection"
                print(f"  {test_url:<53}  {reason}")
            except requests.exceptions.Timeout:
                print(f"  {test_url:<53}  timeout")

        return False

    def paginate(self, endpoint: str, params: dict,
                 data_key: str, page_size: int = 250) -> list:
        """Auto-paginate and return all items from `data_key`."""
        params = {**params, "pageSize": page_size, "page": 1}
        all_items: list = []
        while True:
            data  = self.get(endpoint, params)
            items = data.get(data_key, [])
            all_items.extend(items)
            print(f"\r  Page {params['page']:>3}  |  "
                  f"Records this page: {len(items):>4}  |  "
                  f"Total: {len(all_items):>6}", end="", flush=True)
            if len(items) < page_size:
                print()
                break
            params["page"] += 1
            time.sleep(0.05)   # avoid overwhelming the server
        return all_items


# ── Metadata resolver ─────────────────────────────────────────────────────────

class MetadataResolver:
    """
    Fetches program metadata once and builds UID → CSV-column-name mappings.
    The CSV export from DHIS2 names columns as  "{Stage Name}_{DE Name}"
    so we can reconstruct those names from the API's stage/DE names.
    """

    def __init__(self, client: DHIS2Client, program_uid: str,
                 cache_file: str = None):
        self.client       = client
        self.program_uid  = program_uid
        self.cache_file   = Path(cache_file) if cache_file else None

        self.program_name:     str  = ""
        self.stage_uid_to_name: dict = {}   # stage_uid → stage_name
        self.attr_uid_to_col:   dict = {}   # tei_attr_uid → csv_col_name
        self.de_uid_to_col:     dict = {}   # (stage_uid, de_uid) → csv_col_name
        self.de_uid_to_opts:    dict = {}   # (stage_uid, de_uid) → {code: label}
        self.ou_uid_to_name:    dict = {}   # ou_uid → facility name
        self.ou_uid_to_parent:  dict = {}   # ou_uid → parent (region) name

    # ── public ────────────────────────────────────────────────────────────────

    def load(self):
        if (self.cache_file and self.cache_file.exists()
                and self._cache_matches_program()):
            print(f"Loading metadata from cache: {self.cache_file}")
            self._from_cache()
        else:
            if self.cache_file and self.cache_file.exists():
                print(f"Cache {self.cache_file} was for a different program "
                      f"(expected {self.program_uid}) — refetching.")
            print("Fetching program metadata from DHIS2 ...")
            self._fetch_program()
            if self.cache_file:
                self._to_cache()

    def _cache_matches_program(self) -> bool:
        try:
            with open(self.cache_file) as f:
                return json.load(f).get("program_uid") == self.program_uid
        except Exception:
            return False

    def fetch_org_units(self, root_ou_uid: str = None):
        """Populate name/parent lookup for all org units in program."""
        print("Fetching org unit hierarchy ...")
        params = {"fields": "id,name,parent[id,name]", "paging": "false"}
        if root_ou_uid:
            params["filter"] = f"path:like:{root_ou_uid}"
        data = self.client.get("organisationUnits", params=params)
        for ou in data.get("organisationUnits", []):
            uid  = ou["id"]
            self.ou_uid_to_name[uid]   = ou.get("name", "")
            parent = ou.get("parent") or {}
            self.ou_uid_to_parent[uid] = parent.get("name", "")
        print(f"  Org units: {len(self.ou_uid_to_name)}")

    def ou_name(self,    uid: str) -> str:
        return self.ou_uid_to_name.get(uid, uid)

    def ou_parent(self,  uid: str) -> str:
        return self.ou_uid_to_parent.get(uid, "")

    # ── private ───────────────────────────────────────────────────────────────

    def _fetch_program(self):
        prog = self.client.get(
            f"programs/{self.program_uid}",
            params={"fields": (
                "id,name,"
                "programTrackedEntityAttributes[id,name,"
                "  trackedEntityAttribute[id,name,formName]],"
                "programStages[id,name,"
                "  programStageDataElements["
                "    dataElement[id,name,"
                "      optionSet[id,name,options[code,name]]]]"
            )},
        )
        self.program_name = prog.get("name", "")
        print(f"Program : {self.program_name}")

        # TEI attributes (enrollment-level fields like MRN, Age, etc.)
        for ptea in prog.get("programTrackedEntityAttributes", []):
            attr = ptea.get("trackedEntityAttribute", {})
            uid  = attr.get("id", "")
            name = (attr.get("name", "") or "").strip()
            if not name:
                name = (attr.get("formName", "") or "").strip()
            if uid and name:
                self.attr_uid_to_col[uid] = name

        # Stage → data elements  →  "{Stage Name}_{DE Name}" column
        for stage in prog.get("programStages", []):
            s_uid  = stage["id"]
            s_name = stage["name"].strip()
            self.stage_uid_to_name[s_uid] = s_name
            for psde in stage.get("programStageDataElements", []):
                de      = psde.get("dataElement", {})
                de_uid  = de.get("id", "")
                de_name = de.get("name", "").strip()
                if de_uid and de_name:
                    self.de_uid_to_col[(s_uid, de_uid)] = f"{s_name}_{de_name}"
                    opts = {}
                    for o in (de.get("optionSet") or {}).get("options") or []:
                        code = str(o.get("code", ""))
                        label = (o.get("name") or o.get("code") or "").strip()
                        if code:
                            opts[code] = label
                    if opts:
                        self.de_uid_to_opts[(s_uid, de_uid)] = opts

        print(f"  TEI attributes : {len(self.attr_uid_to_col)}")
        print(f"  Stages         : {len(self.stage_uid_to_name)}")
        print(f"  Data elements  : {len(self.de_uid_to_col)}")

    def _to_cache(self):
        payload = {
            "program_uid":      self.program_uid,
            "program_name":      self.program_name,
            "stage_uid_to_name": self.stage_uid_to_name,
            "attr_uid_to_col":   self.attr_uid_to_col,
            "de_uid_to_col":     {f"{k[0]}|{k[1]}": v
                                   for k, v in self.de_uid_to_col.items()},
            "de_uid_to_opts":    {f"{k[0]}|{k[1]}": v
                                   for k, v in self.de_uid_to_opts.items()},
            "ou_uid_to_name":    self.ou_uid_to_name,
            "ou_uid_to_parent":  self.ou_uid_to_parent,
        }
        with open(self.cache_file, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Metadata cached → {self.cache_file}")

    def _from_cache(self):
        with open(self.cache_file) as f:
            c = json.load(f)
        self.program_name      = c.get("program_name", "")
        self.stage_uid_to_name = c.get("stage_uid_to_name", {})
        self.attr_uid_to_col   = c.get("attr_uid_to_col", {})
        self.ou_uid_to_name    = c.get("ou_uid_to_name", {})
        self.ou_uid_to_parent  = c.get("ou_uid_to_parent", {})
        self.de_uid_to_col     = {
            (k.split("|")[0], k.split("|")[1]): v
            for k, v in c.get("de_uid_to_col", {}).items()
        }
        self.de_uid_to_opts    = {
            (k.split("|")[0], k.split("|")[1]): v
            for k, v in c.get("de_uid_to_opts", {}).items()
        }
        print(f"  Program : {self.program_name}  "
              f"({len(self.de_uid_to_col)} data elements, "
              f"{len(self.attr_uid_to_col)} attributes)")


# ── TEI data fetcher & transformer ────────────────────────────────────────────

class TEIFetcher:
    """
    Fetches tracked entity instances from DHIS2 and transforms them into
    a pandas DataFrame matching the structure of maternal_data.csv so that
    delivery_register.py's build_register() can consume it unchanged.
    """

    def __init__(self, client: DHIS2Client, meta: MetadataResolver):
        self.client  = client
        self.meta    = meta
        self.new_api = client.api_version >= 40

    # ── fetch ─────────────────────────────────────────────────────────────────

    def fetch(self, program_uid: str, ou_uid: str = None,
              ou_mode: str = "DESCENDANTS", start: str = None,
              end: str = None, page_size: int = 250) -> list:
        if self.new_api:
            return self._fetch_new(program_uid, ou_uid, ou_mode,
                                   start, end, page_size)
        return self._fetch_old(program_uid, ou_uid, ou_mode,
                               start, end, page_size)

    def _fetch_new(self, program_uid, ou_uid, ou_mode, start, end, ps):
        """DHIS2 ≥ v2.40  /api/tracker/trackedEntities"""
        # ouMode=DESCENDANTS requires an orgUnit; fall back to ALL if none given
        if not ou_uid and ou_mode == "DESCENDANTS":
            ou_mode = "ALL"

        # v41 enrollmentStatus accepts only one value at a time — omit to get all
        if not ou_uid and ou_mode in ("DESCENDANTS", "SELECTED"):
            ou_mode = "ALL"

        params = {
            "program": program_uid,
            "ouMode":  ou_mode,
            "fields": (
                "trackedEntity,orgUnit,attributes,"
                "enrollments[enrollment,enrolledAt,incidentAt,status,"
                "  events[event,programStage,occurredAt,status,"
                "    dataValues[dataElement,value]]]"
            ),
        }
        if ou_uid: params["orgUnit"] = ou_uid
        # NOTE: no server-side date filter — enrollment may precede delivery by
        # months (ANC) or follow it by ~a week. Fetch a superset and filter
        # client-side by the actual "Delivery summary_Date of Delivery" value.

        print("Fetching tracked entities via /api/tracker/trackedEntities ...")
        print(f"  ouMode={ou_mode}")

        # Detect response envelope key (v41 uses "instances", older builds "trackedEntities")
        try:
            probe = self.client.get("tracker/trackedEntities",
                                    {**params, "pageSize": 1, "page": 1})
            data_key = "instances" if "instances" in probe else "trackedEntities"
        except PermissionError:
            raise
        except Exception:
            data_key = "instances"   # safe default for v41

        return self.client.paginate("tracker/trackedEntities",
                                    params, data_key, ps)

    def _fetch_old(self, program_uid, ou_uid, ou_mode, start, end, ps):
        """DHIS2 v2.36–v2.39  /api/trackedEntityInstances"""
        if not ou_uid and ou_mode in ("DESCENDANTS", "SELECTED"):
            ou_mode = "ACCESSIBLE"
        params = {
            "program":              program_uid,
            "ouMode":               ou_mode,
            "includeAllAttributes": "true",
            "fields":               "*,enrollments[*,events[*,dataValues[*]]]",
        }
        if ou_uid: params["ou"] = ou_uid
        # No server-side date filter — see _fetch_new; superset filtered
        # client-side by "Delivery summary_Date of Delivery".

        print("Fetching tracked entities via /api/trackedEntityInstances ...")
        items = self.client.paginate("trackedEntityInstances",
                                     params, "trackedEntityInstances", ps)
        return [self._normalise_old(t) for t in items]

    @staticmethod
    def _normalise_old(tei: dict) -> dict:
        """Convert old API TEI structure to new API format."""
        enrollments = []
        for enr in tei.get("enrollments", []):
            events = []
            for evt in enr.get("events", []):
                events.append({
                    "event":        evt.get("event", ""),
                    "programStage": evt.get("programStage", ""),
                    "occurredAt":   evt.get("eventDate") or evt.get("occurredAt", ""),
                    "status":       evt.get("status", ""),
                    "dataValues":   [
                        {"dataElement": dv["dataElement"], "value": dv["value"]}
                        for dv in evt.get("dataValues", [])
                    ],
                })
            enrollments.append({
                "enrollment": enr.get("enrollment", ""),
                "enrolledAt": enr.get("enrollmentDate") or enr.get("enrolledAt", ""),
                "incidentAt": enr.get("incidentDate", ""),
                "status":     enr.get("status", ""),
                "events":     events,
            })
        return {
            "trackedEntity": (tei.get("trackedEntityInstance")
                              or tei.get("trackedEntity", "")),
            "orgUnit":       tei.get("orgUnit", ""),
            "attributes":    [
                {"attribute": a.get("attribute", ""),
                 "value":     a.get("value", "")}
                for a in tei.get("attributes", [])
            ],
            "enrollments": enrollments,
        }

    # ── transform ─────────────────────────────────────────────────────────────

    @staticmethod
    def filter_by_delivery_date(df: pd.DataFrame, start: str, end: str,
                                del_date_col: str = "Delivery summary_Date of Delivery"
                                ) -> pd.DataFrame:
        """Keep only rows whose ACTUAL delivery date falls in [start, end].

        Uses the 'Date of Delivery' data value, falling back to the delivery
        event date when that value is missing. Rows with no delivery date at
        all are excluded once a window is given.
        """
        if df.empty:
            return df
        if not (start or end):
            return df

        d_val = pd.to_datetime(df[del_date_col], errors="coerce") if del_date_col in df.columns else pd.Series(pd.NaT, index=df.index)
        evt_col = "Delivery summary_event_date"
        d_evt = pd.to_datetime(df[evt_col], errors="coerce") if evt_col in df.columns else pd.Series(pd.NaT, index=df.index)
        d = d_val.fillna(d_evt)
        if d is None:
            print("  (no delivery date column available — returning all rows)")
            return df

        mask = pd.Series(True, index=df.index)
        if start:
            mask &= d >= pd.to_datetime(start)
        if end:
            mask &= d <= pd.to_datetime(end)
        kept = int(mask.sum())
        print(f"  {kept:,} deliveries within {start or '…'} → {end or '…'} "
              f"(of {len(df):,} rows)")
        return df[mask].reset_index(drop=True)

    def to_flat_row(self, tei: dict) -> dict:
        """
        Convert one TEI (new-API format) into a flat dict whose keys match
        the maternal_data.csv column names, so RAW mappings in
        delivery_register.py resolve correctly.
        """
        row: dict = {}
        ou_uid = tei.get("orgUnit", "")

        # Take the most recent enrollment (should usually be one)
        enrollments = sorted(
            tei.get("enrollments", []),
            key=lambda e: e.get("enrolledAt", ""),
            reverse=True,
        )
        if not enrollments:
            return row
        enr = enrollments[0]

        # ── Top-level identifiers ─────────────────────────────────────────────
        row["tei_id"]              = tei.get("trackedEntity", "")
        row["enrollment_id"]       = enr.get("enrollment", "")
        row["enrollment_status"]   = enr.get("status", "")
        enroll_at = enr.get("enrolledAt", "")
        row["enrollment_date"]     = enroll_at[:10] if enroll_at else ""
        incident_at = enr.get("incidentAt", "")
        row["incident_date"]       = incident_at[:10] if incident_at else ""
        row["org_unit"]            = self.meta.ou_name(ou_uid)
        row["org_unit_id"]         = ou_uid
        row["parent_org_unit"]     = self.meta.ou_parent(ou_uid)
        row["parent_org_unit_id"]  = ""

        # ── TEI attributes (enrollment-level: MRN, Age, etc.) ─────────────────
        attrs = tei.get("attributes") or (enr.get("attributes") if enr else []) or []
        for attr in attrs:
            attr_uid = attr.get("attribute", "")
            col = self.meta.attr_uid_to_col.get(attr_uid) or attr.get("displayName")
            val = attr.get("value", "")
            if col:
                row[col] = val
            if attr_uid:
                row[attr_uid] = val

        # ── Events: one per stage (most recent wins if repeated) ───────────────
        best_event: dict[str, dict] = {}   # stage_uid → event dict
        for evt in enr.get("events", []):
            s_uid   = evt.get("programStage", "")
            current = best_event.get(s_uid)
            if not current or (evt.get("occurredAt", "") >
                               current.get("occurredAt", "")):
                best_event[s_uid] = evt

        for s_uid, evt in best_event.items():
            s_name = self.meta.stage_uid_to_name.get(s_uid, "")
            if s_name:
                # Replicate the CSV's {Stage}_event_id / _event_date columns
                row[f"{s_name}_event_id"]     = evt.get("event", "")
                occurred = evt.get("occurredAt", "")
                row[f"{s_name}_event_date"]   = occurred[:10] if occurred else ""
                row[f"{s_name}_event_status"] = evt.get("status", "")

            # Data values → "{Stage Name}_{DE Name}" columns
            for dv in evt.get("dataValues", []):
                col = self.meta.de_uid_to_col.get(
                    (s_uid, dv.get("dataElement", ""))
                )
                if not col:
                    continue
                val = str(dv.get("value", ""))
                opts = self.meta.de_uid_to_opts.get(
                    (s_uid, dv.get("dataElement", ""))
                )
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

        return row

    def to_dataframe(self, teis: list) -> pd.DataFrame:
        print(f"Transforming {len(teis):,} TEI records ...")
        rows = [self.to_flat_row(t) for t in teis]
        df   = pd.DataFrame(rows)

        # Parse dates to match how delivery_register.py expects them
        for col in ["enrollment_date", "incident_date"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        # Numeric age
        if "Age" in df.columns:
            df["Age"] = pd.to_numeric(df["Age"], errors="coerce")
            df.loc[df["Age"] < 10, "Age"] = np.nan

        print(f"DataFrame: {df.shape[0]:,} rows × {df.shape[1]} columns")
        return df


# ── CLI helpers ───────────────────────────────────────────────────────────────

def _read_cred_file(key: str):
    try:
        with open(CRED_FILE) as f:
            return json.load(f).get(key)
    except Exception:
        return None


def resolve_credentials(args) -> tuple:
    url  = (args.url
            or os.environ.get("DHIS2_URL")
            or _read_cred_file("url"))
    user = (args.username
            or os.environ.get("DHIS2_USER")
            or _read_cred_file("username"))
    pw   = (args.password
            or os.environ.get("DHIS2_PASS")
            or _read_cred_file("password"))

    if not url:
        url  = input("DHIS2 URL (e.g. https://your.dhis2.org): ").strip()
    if not user:
        user = input("Username: ").strip()
    if not pw:
        pw   = getpass.getpass("Password: ")

    return url.rstrip("/"), user, pw


def resolve_ou_uid(client: DHIS2Client,
                   name_or_uid: str,
                   *args, **kwargs) -> tuple:
    """Return (uid, name).  Accepts UID or name search string."""
    if not name_or_uid:
        return None, "All facilities"

    name_or_uid = str(name_or_uid).strip()

    # 1. 11-character alphanumeric strings are DHIS2 UIDs
    if len(name_or_uid) == 11 and name_or_uid.isalnum():
        try:
            ou = client.get(f"organisationUnits/{name_or_uid}",
                            params={"fields": "id,name"})
            if ou and "id" in ou:
                return ou["id"], ou.get("name", name_or_uid)
        except Exception:
            pass

    # 2. Exact name match
    try:
        data = client.get("organisationUnits", params={
            "filter": f"name:eq:{name_or_uid}",
            "fields": "id,name",
            "pageSize": 5,
        })
        ous = data.get("organisationUnits", [])
        if ous:
            return ous[0]["id"], ous[0]["name"]
    except Exception:
        pass

    # 3. Case-insensitive name search
    try:
        data = client.get("organisationUnits", params={
            "filter": f"name:ilike:{name_or_uid}",
            "fields": "id,name",
            "pageSize": 20,
        })
        ous = data.get("organisationUnits", [])
        if ous:
            exact = next((o for o in ous if o.get("name", "").strip().lower() == name_or_uid.lower()), None)
            match = exact or ous[0]
            return match["id"], match["name"]
    except Exception:
        pass

    # 4. Fallback if it looks like a UID
    if len(name_or_uid) == 11 and name_or_uid.isalnum():
        return name_or_uid, name_or_uid

    raise ValueError(f"Org unit not found in DHIS2: '{name_or_uid}'")


def cmd_list_programs(client: DHIS2Client):
    data = client.get("programs", params={
        "filter":  "programType:eq:WITH_REGISTRATION",
        "fields":  "id,name,trackedEntityType[name]",
        "paging":  "false",
    })
    progs = data.get("programs", [])
    print(f"\n  {'UID':<14} {'Tracker type':<22} Name")
    print("  " + "-" * 70)
    for p in sorted(progs, key=lambda x: x["name"]):
        tet = (p.get("trackedEntityType") or {}).get("name", "")
        print(f"  {p['id']:<14} {tet:<22} {p['name']}")
    return progs


def cmd_list_org_units(client: DHIS2Client, program_uid: str):
    data = client.get("organisationUnits", params={
        "programs": program_uid,
        "fields":   "id,name,level,parent[name]",
        "paging":   "false",
    })
    ous = sorted(data.get("organisationUnits", []),
                 key=lambda x: (x.get("level", 99), x.get("name", "")))
    print(f"\n  {'UID':<14} {'Level':<7} {'Parent':<26} Name")
    print("  " + "-" * 75)
    for ou in ous:
        parent = (ou.get("parent") or {}).get("name", "")
        print(f"  {ou['id']:<14} {ou.get('level',''):<7} {parent:<26} {ou['name']}")


# ── Excel generation (delegates to companion script) ──────────────────────────

def generate_excel(df: pd.DataFrame, args, meta: MetadataResolver,
                   ou_name: str):
    try:
        from backend.modules.hmis.rmh_delivery_register import (
            build_register, write_sheet, write_tally_sheet,
            compute_tally, RAW,
        )
    except ImportError:
        try:
            from rmh_delivery_register import (
                build_register, write_sheet, write_tally_sheet,
                compute_tally, RAW,
            )
        except ImportError:
            from delivery_register import (
                build_register, write_sheet, write_tally_sheet,
                compute_tally, RAW,
            )

    facility_col = RAW.get("facility", "org_unit")
    region_col   = RAW.get("region",   "parent_org_unit")

    # ── Reconcile API column names → names expected by RAW / delivery_register.py ──
    # The live API DE names differ slightly from the original CSV export names.
    _API_TO_RAW = {
        # delivery mode: API appended "maternal" to distinguish from neonatal mode
        "Delivery summary_Mode of Delivery maternal":      "Delivery summary_Mode of Delivery",
        # outcome: API uses lowercase "birth outcome", CSV used "Outcome"
        "Delivery summary_birth outcome":                  "Delivery summary_Outcome",
        # trailing-colon fields: CSV export included them, API does not
        "Delivery summary_Date of Delivery":               "Delivery summary_Date of Delivery:",
        "Delivery summary_Episiotomy performed":           "Delivery summary_Episiotomy performed:",
        "Delivery summary_Controlled Cord Traction (CCT)": "Delivery summary_Controlled Cord Traction (CCT):",
        "Delivery summary_Stillbirth":                     "Delivery summary_Stillbirth:",
        "Delivery summary_Birth Weight (grams)":           "Delivery summary_Birth Weight (grams):",
        "Delivery summary_HIV Testing Accepted":           "Delivery summary_HIV Testing Accepted:",
        "Delivery summary_HIV Result":                     "Delivery summary_HIV Result:",
        "Delivery summary_ARV Rx for Mother":              "Delivery summary_ARV Rx for Mother: (by type)",
        "Delivery summary_ARV Px for Newborn":             "Delivery summary_ARV Px for Newborn (by type):",
        # labour mode: CSV had a stray space before underscore
        "Labour Management_Mode of delivery":              "Labour Management _Mode of delivery",
    }
    rename_map = {k: v for k, v in _API_TO_RAW.items() if k in df.columns and v not in df.columns}
    if rename_map:
        df = df.rename(columns=rename_map)

    # Ensure enrollment_date column exists under the name RAW expects
    enroll_key = RAW.get("enroll_date", "enrollment_date")
    if enroll_key not in df.columns and "enrollment_date" in df.columns:
        df[enroll_key] = df["enrollment_date"]

    # Keep only rows with delivery data
    del_mode_col = RAW.get("del_mode", "Delivery summary_Mode of Delivery")
    outcome_col  = RAW.get("outcome",  "Delivery summary_Outcome")
    mask = pd.Series(False, index=df.index)
    if del_mode_col in df.columns:
        mask |= df[del_mode_col].notna() & (df[del_mode_col] != "")
    if outcome_col in df.columns:
        mask |= df[outcome_col].notna() & (df[outcome_col] != "")
    df_del = df[mask].reset_index(drop=True)
    print(f"Rows with delivery data: {len(df_del):,} of {len(df):,} total")

    if len(df_del) == 0:
        print("No delivery records to write — falling back to raw TEI rows.\n")

        # ── Diagnostics: show what columns/stages are actually present ────────
        # List unique stage prefixes (everything before the first "_")
        stage_prefixes = sorted({c.split("_")[0] for c in df.columns
                                  if "_" in c and not c.startswith(("org_", "enroll", "incident", "tei"))})
        print("Stage prefixes found in data:")
        for p in stage_prefixes:
            print(f"  {p!r}")

        # Show columns that contain "delivery", "mode", or "outcome" (case-insensitive)
        kw = ["delivery", "mode", "outcome", "labour", "labor", "intrapartum"]
        matched = [c for c in df.columns if any(k in c.lower() for k in kw)]
        if matched:
            print("\nColumns matching delivery/mode/outcome/labour:")
            for c in matched:
                filled = df[c].notna().sum()
                print(f"  {c!r}  ({filled} non-null values)")
        else:
            print("\nNo columns matched delivery/mode/outcome/labour keywords.")
            print("Showing first 30 non-meta columns:")
            meta_cols = {"tei_uid","org_unit","parent_org_unit","enrollment_date","incident_date"}
            others = [c for c in df.columns if c not in meta_cols][:30]
            for c in others:
                print(f"  {c!r}")

        print("\nFix: update RAW['del_mode'] and RAW['outcome'] in delivery_register.py "
              "to match the stage/DE names above.")

        if df.empty:
            print("Also no raw TEI rows to export. Generating empty register workbook.")
            wb = Workbook()
            wb.remove(wb.active)
            ws = wb.create_sheet(title="Delivery Register")
            write_sheet(ws, pd.DataFrame(), str(ou_name), "", "—", "—")
            ws_tally = wb.create_sheet(title="Tally Summary")
            write_tally_sheet(ws_tally, [])
            wb.save(args.output)
            print(f"\nSaved empty register → {args.output}")
            return
        print("\nWriting workbook from the raw TEI rows found (delivery fields blank).")
        df_del = df  # fall back: use everything we have so the file still exists

    def _date_range(grp):
        for dc in ("Delivery summary_Date of Delivery", "Delivery summary_event_date",
                   "enrollment_date"):
            if dc in grp.columns and grp[dc].notna().any():
                d = pd.to_datetime(grp[dc], errors="coerce")
                d = d.dropna()
                if not d.empty:
                    return (str(d.min().date()), str(d.max().date()))
        return "—", "—"

    wb = Workbook()
    wb.remove(wb.active)
    all_tallies = []

    if args.sheet_per_facility and facility_col in df_del.columns:
        facilities = sorted(df_del[facility_col].dropna().unique())
        print(f"Generating {len(facilities)} facility sheet(s) ...")
        for fac in facilities:
            grp      = df_del[df_del[facility_col] == fac]
            region   = (grp[region_col].mode()[0]
                        if region_col in grp.columns and len(grp) else "")
            d_from, d_to = _date_range(grp)
            reg          = build_register(grp)
            sheet_name   = str(fac)[:28].strip()
            ws           = wb.create_sheet(title=sheet_name)
            write_sheet(ws, reg, fac, region, d_from, d_to)
            t            = compute_tally(reg)
            t["_facility"] = sheet_name
            all_tallies.append(t)
            print(f"  {fac}: {len(reg)} rows")
    else:
        fac_list  = (df_del[facility_col].dropna().unique()
                     if facility_col in df_del.columns else [])
        fac_label = (fac_list[0] if len(fac_list) == 1
                     else f"{ou_name} ({len(fac_list)} facilities)")
        region    = (df_del[region_col].mode()[0]
                     if region_col in df_del.columns and len(df_del) else "")
        d_from, d_to = _date_range(df_del)
        print(f"Building combined register for {len(df_del):,} rows ...")
        reg  = build_register(df_del)
        ws   = wb.create_sheet(title="Delivery Register")
        write_sheet(ws, reg, str(fac_label), str(region), d_from, d_to)
        t    = compute_tally(reg)
        t["_facility"] = str(fac_label)
        all_tallies.append(t)

    ws_tally = wb.create_sheet(title="Tally Summary")
    write_tally_sheet(ws_tally, all_tallies)
    wb.save(args.output)
    print(f"\nSaved → {args.output}")

    # Console summary
    if all_tallies:
        combined = {
            k: sum(t[k] for t in all_tallies
                   if isinstance(t.get(k), (int, float)))
            for k in all_tallies[0]
            if not k.startswith("_")
        }
        print("\n" + "=" * 52)
        print(f"  TALLY SUMMARY  [{meta.program_name}]")
        print("=" * 52)
        for k, v in combined.items():
            print(f"  {k:<36} {v:>6}")


# ── Main ───────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="delivery_register_dhis2.py",
        description="Pull DHIS2 tracker data → Ethiopian MoH Delivery Register",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("QUICK START")[1] if "QUICK START" in __doc__ else "",
    )

    # Connection
    grp = ap.add_argument_group("Connection")
    grp.add_argument("--url",      help="DHIS2 base URL")
    grp.add_argument("--username", help="DHIS2 username")
    grp.add_argument("--password", help="DHIS2 password (use env var in production)")
    grp.add_argument("--save-credentials", action="store_true",
                     help=f"Save URL/user/pass to {CRED_FILE} for future runs")
    grp.add_argument("--no-ssl-verify", action="store_true",
                     help="Disable SSL certificate verification (self-signed certs)")
    grp.add_argument("--diagnose", action="store_true",
                     help="Auto-probe URL variations to find a working DHIS2 endpoint")

    # Discovery
    grp = ap.add_argument_group("Discovery")
    grp.add_argument("--list-programs",   action="store_true",
                     help="List all tracker programs and exit")
    grp.add_argument("--list-org-units",  action="store_true",
                     help="List org units for --program and exit")

    # Data selection
    grp = ap.add_argument_group("Data selection")
    grp.add_argument("--program",   metavar="UID",
                     help="Program UID (required for data pull)")
    grp.add_argument("--org-unit",  metavar="UID_or_NAME",
                     help="Filter by org unit (UID or name)")
    grp.add_argument("--ou-mode",   default="DESCENDANTS",
                     choices=["DESCENDANTS", "SELECTED", "CHILDREN", "ALL"],
                     help="Org unit hierarchy mode (default: DESCENDANTS)")
    grp.add_argument("--start",     metavar="YYYY-MM-DD",
                     help="Delivery start date filter (actual Date of Delivery)")
    grp.add_argument("--end",       metavar="YYYY-MM-DD",
                     help="Delivery end date filter (actual Date of Delivery)")

    # Output
    grp = ap.add_argument_group("Output")
    grp.add_argument("--output",    default="delivery_register_dhis2.xlsx",
                     help="Excel output path (default: delivery_register_dhis2.xlsx)")
    grp.add_argument("--sheet-per-facility", action="store_true",
                     help="One worksheet per org unit")

    # Performance
    grp = ap.add_argument_group("Performance / caching")
    grp.add_argument("--page-size",       type=int, default=250,
                     help="TEI records per API page (default: 250)")
    grp.add_argument("--cache-metadata",  default="hmis_delivery_metadata_cache.json",
                     help="Cache metadata JSON path (default: hmis_delivery_metadata_cache.json)")
    grp.add_argument("--refresh-metadata", action="store_true",
                     help="Re-fetch metadata even if cache exists")

    return ap


def main():
    args = build_arg_parser().parse_args()

    # ── Resolve credentials ────────────────────────────────────────────────────
    url, user, pw = resolve_credentials(args)
    verify_ssl = not getattr(args, "no_ssl_verify", False)
    client     = DHIS2Client(url, user, pw, verify_ssl=verify_ssl)

    # ── Verify connection ──────────────────────────────────────────────────────
    try:
        info = client.get("system/info")
        print(
            f"Connected  : {info.get('systemName', 'DHIS2')} "
            f"v{info.get('version', '?')}\n"
            f"Instance   : {info.get('instanceBaseUrl', url)}\n"
            f"API version: {client.api_version}  "
            f"({'new /api/tracker/' if client.api_version >= 40 else 'legacy /api/trackedEntityInstances'})"
        )
    except PermissionError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"\nERROR: {e}\n")
        # ── Connection diagnostics ─────────────────────────────────────────────
        if getattr(args, "diagnose", False):
            found = client.diagnose(user, pw)
            if found:
                print(f"\nWorking base URL found: {client.base}")
                print("Re-run your command with --url", client.base)
            else:
                print("\nNo working DHIS2 endpoint found. Possible causes:")
                print("  • Server only accessible via VPN — connect first")
                print("  • Wrong protocol: try http:// instead of https://")
                print("  • SSL certificate issue: add --no-ssl-verify")
                print("  • Non-standard context path: try --url https://host/dhis2")
        else:
            print("Hint: run with --diagnose to auto-probe URL variations.")
        sys.exit(1)

    if args.save_credentials:
        with open(CRED_FILE, "w") as f:
            json.dump({"url": url, "username": user, "password": pw}, f, indent=2)
        print(f"Credentials saved → {CRED_FILE}  "
              "(NOTE: password stored in plaintext — use env vars in production)")

    # ── Discovery modes ────────────────────────────────────────────────────────
    if args.list_programs:
        cmd_list_programs(client)
        return

    if not args.program:
        print("\nNo --program specified.  Available tracker programs:")
        cmd_list_programs(client)
        print("\nRe-run with:  --program <UID>")
        return

    if args.list_org_units:
        cmd_list_org_units(client, args.program)
        return

    # ── Metadata ───────────────────────────────────────────────────────────────
    cache_path = None if args.refresh_metadata else args.cache_metadata
    meta       = MetadataResolver(client, args.program, cache_file=cache_path)
    meta.load()

    # ── Org unit ───────────────────────────────────────────────────────────────
    ou_uid, ou_name = resolve_ou_uid(client, args.org_unit)
    print(f"Org unit : {ou_name or 'ALL'}")

    if not meta.ou_uid_to_name:
        meta.fetch_org_units(ou_uid)

    # ── Fetch ──────────────────────────────────────────────────────────────────
    fetcher = TEIFetcher(client, meta)
    teis    = fetcher.fetch(
        program_uid=args.program,
        ou_uid=ou_uid,
        ou_mode=args.ou_mode,
        start=args.start,
        end=args.end,
        page_size=args.page_size,
    )
    print(f"Total TEI records: {len(teis):,}")

    if not teis:
        print("No records returned.  "
              "Check program UID, org unit, and date filters.")
        return

    # ── Transform ──────────────────────────────────────────────────────────────
    df = fetcher.to_dataframe(teis)

    # Filter by the ACTUAL delivery date (not enrollment/event date)
    df = TEIFetcher.filter_by_delivery_date(df, args.start, args.end)
    print(f"Rows after delivery-date filter: {len(df):,}")

    # ── Excel output ───────────────────────────────────────────────────────────
    generate_excel(df, args, meta, ou_name or "All facilities")


if __name__ == "__main__":
    main()
