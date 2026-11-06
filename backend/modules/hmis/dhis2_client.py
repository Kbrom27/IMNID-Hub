"""Authenticated DHIS2 REST client for HMIS reporting and metadata discovery."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger("hmis_dhis2_client")

_DHIS2_PATHS = ["", "/dhis", "/dhis2", "/imnid", "/hmis", "/tracker"]


def normalize_dhis2_url(url: str) -> str:
    """Strip accidental /api or /api/ suffix."""
    url = (url or "").strip().rstrip("/")
    for suffix in ("/api", "/api/"):
        if url.endswith(suffix.rstrip("/")):
            url = url[: -len(suffix.rstrip("/"))]
    return url


class DHIS2Client:
    """Authenticated DHIS2 REST client with retry and SSL options."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        timeout: int = 30,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.base = normalize_dhis2_url(url)
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.log = log_fn or LOGGER.info

        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = verify_ssl
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        retry = Retry(
            total=2,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        if not verify_ssl:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self._version: Optional[int] = None

    @property
    def api_version(self) -> int:
        if self._version is None:
            try:
                info = self.get("system/info")
                ver = str(info.get("version", "2.38"))
                parts = ver.split(".")
                self._version = int(parts[1]) if parts[0] == "2" else int(parts[0])
            except Exception:
                self._version = 38
        return self._version

    def get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base}/api/{endpoint.lstrip('/')}"
        resp = self.session.get(url, params=params or {}, timeout=self.timeout)
        if resp.status_code == 401:
            raise PermissionError("Authentication failed — check DHIS2 username/password.")
        if resp.status_code == 403:
            raise PermissionError(f"Access denied to DHIS2 endpoint: {endpoint}")
        resp.raise_for_status()
        return resp.json()

    def post(self, endpoint: str, payload: dict, params: Optional[dict] = None) -> dict:
        url = f"{self.base}/api/{endpoint.lstrip('/')}"
        resp = self.session.post(
            url, json=payload, params=params or {}, timeout=self.timeout
        )
        if resp.status_code == 401:
            raise PermissionError("Authentication failed — check DHIS2 credentials.")
        if resp.status_code == 403:
            raise PermissionError(f"Access denied to endpoint: {endpoint}")
        resp.raise_for_status()
        return resp.json()

    def paginate(
        self, endpoint: str, params: dict, data_key: str, page_size: int = 250
    ) -> list:
        req_params = {**params, "pageSize": page_size, "page": 1, "totalPages": "true"}
        items: list = []
        while True:
            data = self.get(endpoint, req_params)
            chunk = data.get(data_key, [])
            items.extend(chunk)
            pager = data.get("pager", {})
            page_count = pager.get("pageCount")
            cur_page = pager.get("page", req_params["page"])
            if page_count is not None:
                if cur_page >= page_count or not chunk:
                    break
            else:
                if len(chunk) < page_size or not chunk:
                    break
            req_params["page"] += 1
        return items

    def diagnose(self) -> Optional[str]:
        """Try common URL variations to locate a working DHIS2 base."""
        raw_base = self.base
        parsed = requests.utils.urlparse(raw_base)
        schemes = ["https", "http"] if parsed.scheme == "https" else ["http", "https"]
        host = parsed.netloc or parsed.path
        path = parsed.path if parsed.netloc else ""

        candidates = []
        for scheme in schemes:
            for ctx in _DHIS2_PATHS:
                base_try = f"{scheme}://{host}{path}{ctx}".rstrip("/")
                if base_try not in candidates:
                    candidates.append(base_try)

        for base in candidates:
            test_url = f"{base}/api/system/info"
            try:
                r = requests.get(
                    test_url,
                    auth=(self.username, self.password),
                    headers={"Accept": "application/json"},
                    timeout=10,
                    verify=self.verify_ssl,
                )
                if r.status_code == 200:
                    self.base = base
                    return base
            except Exception:
                continue
        return None

    def discover_metadata(self) -> dict:
        """Connects and extracts programs, organization units hierarchy, and datasets."""
        # 1. Programs
        prog_data = self.get(
            "programs",
            {"filter": "programType:eq:WITH_REGISTRATION", "fields": "id,name", "paging": "false"},
        )
        programs = sorted(
            [{"id": p["id"], "name": p["name"]} for p in prog_data.get("programs", [])],
            key=lambda x: x["name"].lower(),
        )

        # 2. Org Units
        ous_data = self.get("organisationUnits", {"fields": "id,name,level", "paging": "false"})
        ou_list = ous_data.get("organisationUnits", [])
        levels = sorted({int(o.get("level", 0)) for o in ou_list if o.get("level") is not None})
        root_level = levels[0] if levels else 1
        region_level = root_level + 1
        facility_level = levels[-1] if levels else region_level + 1

        regions = sorted(
            [{"id": o["id"], "name": o["name"]} for o in ou_list if int(o.get("level", 0)) == region_level],
            key=lambda x: x["name"].lower(),
        )
        facilities = sorted(
            [{"id": o["id"], "name": o["name"]} for o in ou_list if int(o.get("level", 0)) == facility_level],
            key=lambda x: x["name"].lower(),
        )

        # 3. Datasets
        ds_data = self.get("dataSets", {"fields": "id,name", "paging": "false"})
        datasets = sorted(
            [{"id": d["id"], "name": d["name"]} for d in ds_data.get("dataSets", [])],
            key=lambda x: x["name"].lower(),
        )

        # 4. Program Matches
        prog_map = {p["name"].strip().lower(): p["id"] for p in programs}
        matched_rmh = prog_map.get("maternal inpatient data")
        matched_nh = prog_map.get("neonatal care form")

        return {
            "status": "connected",
            "base_url": self.base,
            "api_version": self.api_version,
            "region_level": region_level,
            "facility_level": facility_level,
            "regions_count": len(regions),
            "facilities_count": len(facilities),
            "programs_count": len(programs),
            "datasets_count": len(datasets),
            "regions": regions,
            "facilities": facilities,
            "programs": programs,
            "datasets": datasets,
            "matched_programs": {
                "RMH": {"name": "Maternal Inpatient Data", "id": matched_rmh},
                "NH": {"name": "Neonatal Care Form", "id": matched_nh},
            },
        }
