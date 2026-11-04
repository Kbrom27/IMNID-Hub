"""
=============================================================================
  PROJECT  : IMNID Hub — MOH Aggregate Report Exporter
  FILE     : moh_aggregate.py
  PURPOSE  : Pipeline ported from NICU_IMNID_AGGREGATE_GUI_OPTIMIZED.py to
             fetch MOH DHIS2 analytics for mapped facilities, pivot by period,
             and export multi-sheet Excel + CSV reports.
=============================================================================
"""

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

BATCH_SIZE = 500
ORG_PAGE_SIZE = 1000
ANALYTICS_WORKERS = 8
START_YEAR, START_MONTH = 2017, 7


def generate_periods(year: Optional[int] = None, months: Optional[Any] = None) -> str:
    """Build 'YYYYMM;YYYYMM;...' period list.

    year+months -> only those months of that year (e.g. 2026 with [1, 2, 3] or 1).
    year only   -> all 12 months of that year.
    None        -> full default range (201707 up to the current month).
    """
    if year and months is not None:
        if isinstance(months, (int, str)):
            month_list = [int(months)]
        else:
            month_list = [int(m) for m in months]
        return ";".join(f"{year}{m:02d}" for m in sorted(set(month_list)))
    if year:
        return ";".join(f"{year}{m:02d}" for m in range(1, 13))

    now = datetime.now()
    latest = now.strftime("%Y%m")
    periods = []
    y, m = START_YEAR, START_MONTH
    while True:
        periods.append(f"{y}{m:02d}")
        if f"{y}{m:02d}" == latest:
            break
        m += 1
        if m > 12:
            m = 1
            y += 1
    return ";".join(periods)


class MohAggregatePipeline:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        data_element_uid: str,
        mapping_file: str,
        output_dir: str,
        periods: Optional[List[str] | str] = None,
        output_name: str = "",
        log_fn: Optional[Callable[[str], None]] = None,
        progress_fn: Optional[Callable[[int, int, str], None]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.data_element_uid = data_element_uid
        self.mapping_file = mapping_file
        self.output_dir = output_dir
        self.output_name = output_name or "N_NICU admissions imnid only"
        if isinstance(periods, list):
            self.periods = ";".join(periods)
        elif isinstance(periods, str) and periods:
            self.periods = periods
        else:
            self.periods = generate_periods()

        self.log_fn = log_fn or print
        self.progress_fn = progress_fn or (lambda cur, tot, msg: None)

        self.session: Optional[requests.Session] = None
        self.org_name_map_id: Dict[str, str] = {}
        self.org_norm_map_id: Dict[str, str] = {}
        self.org_id_name: Dict[str, str] = {}
        self.org_level: Dict[str, int] = {}
        self.matched: List[Dict[str, Any]] = []
        self.unmatched: List[str] = []
        self.df_final: Optional[pd.DataFrame] = None
        self.df_raw: Optional[pd.DataFrame] = None

    def log(self, message: str) -> None:
        self.log_fn(message)

    # ------------------------------------------------------------- STEP 1
    def login(self) -> None:
        self.log("=" * 60)
        self.log("STEP 1: DHIS2 Authentication")
        self.log("=" * 60)
        self.progress_fn(5, 100, "Authenticating with DHIS2...")

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

        page_url = f"{self.base_url}/dhis-web-commons-security/login.action"
        csrf = None
        self.log(f"Accessing login endpoint: {page_url}")
        try:
            resp = session.get(page_url, timeout=30)
            if resp.status_code == 200:
                m = re.search(r'name="csrfToken"\s+value="([^"]+)"', resp.text)
                if m:
                    csrf = m.group(1)
                    self.log("[OK] Found CSRF token")
                else:
                    self.log("[i] No CSRF token found in login page")
        except Exception as e:
            self.log(f"[WARN] Web login page access note: {e}")

        login_data = {"j_username": self.username, "j_password": self.password}
        if csrf:
            login_data["csrfToken"] = csrf
        session.headers.update({
            "Referer": page_url,
            "Origin": self.base_url,
            "Content-Type": "application/x-www-form-urlencoded",
        })

        try:
            session.post(page_url, data=login_data, allow_redirects=True, timeout=30)
        except Exception as e:
            self.log(f"[WARN] Form login attempt: {e}")

        # Verification check
        verify = session.get(f"{self.base_url}/api/me", timeout=30)
        if verify.status_code == 200:
            self.log(
                f"[OK] Session verified via cookie! Logged in as: "
                f"{verify.json().get('name', 'Unknown')}"
            )
        else:
            # Fallback to HTTP Basic Auth if web session didn't authenticate
            self.log("[i] Trying HTTP Basic Auth fallback...")
            session.auth = (self.username, self.password)
            verify2 = session.get(f"{self.base_url}/api/me", timeout=30)
            if verify2.status_code == 200:
                self.log(
                    f"[OK] HTTP Basic Auth verified! Logged in as: "
                    f"{verify2.json().get('name', 'Unknown')}"
                )
            else:
                raise RuntimeError(
                    f"Session verification failed with status {verify.status_code} "
                    f"(basic auth: {verify2.status_code}). Please verify username and password."
                )

        self.session = session
        self.progress_fn(15, 100, "Authentication verified.")

    # ------------------------------------------- STEP 2: fetch org units once
    def fetch_org_units(self) -> None:
        self.log("\n" + "=" * 60)
        self.log("STEP 2: Fetching Organisation Units (id/name/level only)")
        self.log("=" * 60)
        self.progress_fn(20, 100, "Fetching DHIS2 organisation units...")

        page = 1
        total = 0
        while True:
            params = {
                "fields": "id,displayName,level",
                "paging": "true",
                "page": page,
                "pageSize": ORG_PAGE_SIZE,
                "order": "level:asc",
            }
            try:
                resp = self.session.get(
                    f"{self.base_url}/api/organisationUnits.json",
                    params=params,
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                units = data.get("organisationUnits", [])
                if not units:
                    break
                for ou in units:
                    name = str(ou["displayName"]).strip()
                    self.org_name_map_id.setdefault(name, ou["id"])
                    norm_name = re.sub(r"\s+", " ", name).lower()
                    self.org_norm_map_id.setdefault(norm_name, ou["id"])
                    self.org_id_name[ou["id"]] = name
                    self.org_level[ou["id"]] = ou.get("level", 0)
                total += len(units)
                self.log(f"   Page {page}: +{len(units)} (running total {total})")
                if page >= data.get("pager", {}).get("pageCount", 0):
                    break
                page += 1
                time.sleep(0.1)
            except Exception as e:
                self.log(f"   Error on page {page}: {e}")
                break

        self.log(f"[OK] Total org units fetched: {total}")
        if not total:
            raise RuntimeError("No organisation units were fetched from DHIS2.")
        self.progress_fn(35, 100, f"Fetched {total} organisation units.")

    # ---------------------------------- STEP 3: match mapping -> facilities
    def match_mapping(self) -> None:
        self.log("\n" + "=" * 60)
        self.log("STEP 3: Matching Mapped Facilities to DHIS2 Org Units")
        self.log("=" * 60)
        self.progress_fn(40, 100, "Matching facility mapping...")

        self.log(f"Reading mapping file: {self.mapping_file}")
        mapping_path = Path(self.mapping_file)
        if not mapping_path.is_file():
            raise FileNotFoundError(f"Mapping file not found: {self.mapping_file}")

        if mapping_path.suffix.lower() in [".xlsx", ".xls"]:
            mapping = pd.read_excel(mapping_path)
        else:
            mapping = pd.read_csv(mapping_path)

        # Look for facility name column
        fac_col = None
        for c in mapping.columns:
            if "facility name" in str(c).strip().lower():
                fac_col = c
                break
        if fac_col is None:
            if "MOH Facility Name" in mapping.columns:
                fac_col = "MOH Facility Name"
            elif len(mapping.columns) > 0:
                fac_col = mapping.columns[0]
                self.log(f"[i] Using '{fac_col}' as facility name column.")

        has_id_col = False
        id_col = None
        for c in mapping.columns:
            if "org unit id" in str(c).strip().lower() or "orgunit id" in str(c).strip().lower():
                has_id_col = True
                id_col = c
                break

        seen_ids = set()

        for _, row in mapping.iterrows():
            if pd.isna(row.get(fac_col)):
                continue
            n = str(row[fac_col]).strip()
            if not n:
                continue

            # 1. Exact name match
            oid = self.org_name_map_id.get(n)

            # 2. Whitespace-normalized & case-insensitive match
            if not oid:
                norm_n = re.sub(r"\s+", " ", n).lower()
                oid = self.org_norm_map_id.get(norm_n)

            # 3. Org Unit ID match if column exists in mapping
            if not oid and has_id_col and pd.notna(row.get(id_col)):
                row_id = str(row[id_col]).strip()
                if row_id in self.org_level or row_id in self.org_id_name:
                    oid = row_id

            # 4. Explicit alias & UID match for Karamara / Karama (Somali region)
            if not oid and ("karama" in n.lower() or "karamara" in n.lower()):
                if "DKsubMyV5Nd" in self.org_level or "DKsubMyV5Nd" in self.org_id_name:
                    oid = "DKsubMyV5Nd"
                else:
                    for u_id, u_name in self.org_id_name.items():
                        if "karamara" in u_name.lower() or "karama" in u_name.lower():
                            oid = u_id
                            break

            if oid:
                if oid not in seen_ids:
                    seen_ids.add(oid)
                    self.matched.append({
                        "name": self.org_id_name.get(oid, n),
                        "id": oid,
                        "level": self.org_level.get(oid),
                    })
            else:
                if n not in self.unmatched:
                    self.unmatched.append(n)

        self.log(f"[OK] Matched facilities for analytics: {len(self.matched)}")
        if self.unmatched:
            self.log(
                f"[WARN] {len(self.unmatched)} mapped names were NOT found "
                f"in DHIS2 org units and were skipped:"
            )
            for n in sorted(self.unmatched)[:10]:
                self.log(f"   - {n}")
            if len(self.unmatched) > 10:
                self.log(f"   ... and {len(self.unmatched) - 10} more")
        if not self.matched:
            raise RuntimeError("No mapped facility matched any DHIS2 organisation unit.")

        self.progress_fn(50, 100, f"Matched {len(self.matched)} facilities.")

    # ----------------------- STEP 4: analytics (parallel, matched only)
    def fetch_analytics(self) -> pd.DataFrame:
        self.log("\n" + "=" * 60)
        self.log("STEP 4: Fetching Analytics for Matched Facilities Only")
        self.log("=" * 60)

        ids = [f["id"] for f in self.matched]
        batches = [ids[i : i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]
        periods_list = [p.strip() for p in self.periods.split(";") if p.strip()]
        if len(periods_list) > 6:
            period_summary = f"{periods_list[0]} .. {periods_list[-1]} ({len(periods_list)} periods)"
        else:
            period_summary = self.periods
        self.log(f"Data element: {self.data_element_uid}")
        self.log(f"Target period(s): {period_summary}")
        self.log(
            f"{len(ids)} facilities -> {len(batches)} analytics "
            f"request(s) (<= {BATCH_SIZE} each)"
        )
        self.progress_fn(55, 100, f"Querying analytics for {len(ids)} facilities ({period_summary})...")

        def fetch(batch_str: str) -> StringIO:
            params = [
                ("dimension", f"dx:{self.data_element_uid}"),
                ("dimension", f"pe:{self.periods}"),
                ("dimension", f"ou:{batch_str}"),
                ("displayProperty", "NAME"),
            ]
            qs = "&".join(f"{k}={v}" for k, v in params)
            resp = self.session.get(
                f"{self.base_url}/api/analytics.csv?{qs}", timeout=180
            )
            resp.raise_for_status()
            if "text/html" in resp.headers.get("Content-Type", ""):
                raise RuntimeError(
                    "Server returned HTML instead of CSV (session authentication may have expired)"
                )
            return StringIO(resp.text)

        frames = []
        n_done = 0
        with ThreadPoolExecutor(max_workers=ANALYTICS_WORKERS) as pool:
            futs = [pool.submit(fetch, ";".join(b)) for b in batches]
            for done in as_completed(futs):
                try:
                    buf = done.result()
                    df = pd.read_csv(buf)
                    if not df.empty:
                        frames.append(df)
                except Exception as e:
                    self.log(f"[X] An analytics batch failed: {e}")
                n_done += 1
                self.log(f"   Batches completed: {n_done}/{len(batches)}")
                prog = 55 + int(25 * (n_done / max(1, len(batches))))
                self.progress_fn(prog, 100, f"Analytics progress: {n_done}/{len(batches)} batches")
                time.sleep(0.05)

        if not frames:
            self.log(
                f"[ERROR] DHIS2 MOH returned 0 analytics records for data element '{self.data_element_uid}' "
                f"across period(s): {period_summary}."
            )
            self.log(
                "[INFO] Note: In MOH DHIS2, IMNID NICU aggregate data (lzhOxCHJMOV) is primarily recorded "
                "under Ethiopian calendar fiscal years (2017–2019). If querying recent Gregorian periods (e.g. 2025/2026), "
                "verify whether facilities have submitted monthly aggregate reports in MOH DHIS2 for those months, "
                "or select 'Full Historical Range' / Year '2018'."
            )
            raise RuntimeError(
                f"No analytics records found in MOH DHIS2 for data element '{self.data_element_uid}' in period(s) [{period_summary}]. "
                "IMNID historical data in MOH DHIS2 is primarily recorded in Ethiopian years 2017–2019. "
                "Please select 'Full Historical Range' or Year '2018'."
            )

        raw = pd.concat(frames, ignore_index=True).drop_duplicates()
        self.log(f"[OK] Total analytics data rows fetched: {raw.shape[0]}")
        return raw

    # ------------------------------ STEP 5: enrich + pivot final report
    def transform(self, raw: pd.DataFrame) -> pd.DataFrame:
        self.log("\n" + "=" * 60)
        self.log("STEP 5: Building Final Report (IMNID facilities only)")
        self.log("=" * 60)
        self.progress_fn(82, 100, "Pivoting and calculating summary metrics...")

        id_info = {f["id"]: f for f in self.matched}

        org_col = None
        for c in raw.columns:
            if "unit" in str(c).strip().lower():
                org_col = c
                break
        if org_col is None:
            org_col = raw.columns[2] if len(raw.columns) > 2 else raw.columns[0]
            self.log(f"[i] No org-unit column detected; using '{org_col}'.")

        raw[org_col] = raw[org_col].astype(str).str.strip()
        raw = raw[raw[org_col].isin(set(id_info))].copy()

        if raw.empty:
            raise RuntimeError(
                "Analytics did not return rows for any of the mapped facilities. "
                "Check the data element ID and period range."
            )

        raw["MOH Facility Name"] = raw[org_col].map(lambda oid: id_info[oid]["name"])
        raw["Org Unit ID"] = raw[org_col]
        raw["Level"] = raw[org_col].map(lambda oid: id_info[oid]["level"])

        pivot = raw.pivot_table(
            index=["MOH Facility Name", "Org Unit ID", "Level"],
            columns="Period",
            values="Value",
            aggfunc="first",
            fill_value=np.nan,
        ).reset_index()

        period_cols = sorted(pivot.columns[3:].tolist())
        pivot = pivot[["MOH Facility Name", "Org Unit ID", "Level"] + period_cols]

        self.log(
            f"Final report matrix: {pivot.shape[0]} facilities x {len(period_cols)} periods"
        )
        if "Value" in raw.columns:
            self.log(
                f"Value check - raw sum: {raw['Value'].sum():,.0f}, "
                f"pivoted sum: {pivot.iloc[:, 3:].sum().sum():,.0f}"
            )

        self.df_final = pivot
        self.df_raw = raw
        return pivot

    # -------------------------------------------------- STEP 6: save outputs
    def save_outputs(self) -> Tuple[str, str]:
        self.log("\n" + "=" * 60)
        self.log("STEP 6: Saving Outputs (IMNID-only facilities)")
        self.log("=" * 60)
        self.progress_fn(92, 100, "Writing Excel workbook and CSV export...")

        base = self.output_name
        if base.lower().endswith(".xlsx"):
            base = base[:-5]
        elif base.lower().endswith(".csv"):
            base = base[:-4]

        final_xlsx = os.path.join(self.output_dir, f"{base}.xlsx")
        final_csv = os.path.join(self.output_dir, f"{base}.csv")

        with pd.ExcelWriter(final_xlsx, engine="openpyxl") as w:
            self.df_final.to_excel(
                w, sheet_name="Facilities by Period", index=False
            )

            total_col = self.df_final.iloc[:, 3:].sum(axis=1, numeric_only=True)
            name_col = self.df_final.columns[0]
            id_col = self.df_final.columns[1]
            level_col = self.df_final.columns[2]
            summary = self.df_final[[name_col, id_col, level_col]].copy()
            total_title = "Total NICU Admissions" if (not self.data_element_uid or "lzhOxCHJMOV" in self.data_element_uid) else "Total Aggregate Value"
            summary[total_title] = total_col
            summary.to_excel(w, sheet_name="Summary", index=False)

            if "Value" in self.df_raw.columns and self.df_raw["Value"].notna().any():
                per = self.df_raw.groupby("Period")["Value"].sum().reset_index()
                per.columns = ["Period", total_title]
                per.to_excel(w, sheet_name="Summary by Period", index=False)

            meta = pd.DataFrame({
                "Metric": [
                    "Data Element",
                    "Periods",
                    "Matched Facilities",
                    "Unmatched Names",
                    "Export Date",
                ],
                "Value": [
                    self.data_element_uid,
                    self.periods,
                    str(len(self.matched)),
                    str(len(self.unmatched)),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ],
            })
            meta.to_excel(w, sheet_name="Metadata", index=False)

        self.log(
            f"[OK] Final Excel workbook saved -> {final_xlsx} "
            f"({len(self.df_final)} facilities)"
        )

        self.df_final.to_csv(final_csv, index=False)
        self.log(f"[OK] Final CSV saved -> {final_csv}")

        self.progress_fn(100, 100, "MOH Aggregate export complete.")
        return final_xlsx, final_csv

    def run(self) -> Tuple[str, str]:
        self.login()
        self.fetch_org_units()
        self.match_mapping()
        raw = self.fetch_analytics()
        self.transform(raw)
        return self.save_outputs()
