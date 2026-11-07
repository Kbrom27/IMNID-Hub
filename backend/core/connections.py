import os
import sys
import time
import requests
import urllib3
import re
from typing import Dict, Any, Optional

import socket

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def is_running_in_docker() -> bool:
    """
    Check if the current process is running inside a Docker container.
    """
    if getattr(sys, 'frozen', False):
        return False
    if sys.platform == "win32":
        return False
    if os.environ.get("IMNID_RUNNING_IN_DOCKER", "").lower() in ("true", "1", "yes"):
        return True
    if os.environ.get("RUNNING_IN_DOCKER", "").lower() in ("true", "1", "yes"):
        return True
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "rt") as f:
            c = f.read()
            if "docker" in c or "containerd" in c or "kubepods" in c:
                return True
    except Exception:
        pass
    return False

def can_resolve_host(hostname: str) -> bool:
    """
    Checks if a given hostname can be resolved via DNS.
    """
    try:
        socket.gethostbyname(hostname)
        return True
    except Exception:
        return False

def normalize_container_url(url: str) -> str:
    """
    Normalizes URLs for execution:
    - Fixes missing slashes (e.g. 'http:localhost' -> 'http://localhost')
    - Ensures scheme (e.g. 'localhost:8080' -> 'http://localhost:8080')
    - When running natively (outside Docker), 'host.docker.internal' is rewritten
      to 'localhost' so local services (DHIS2, OpenMRS) connect reliably.
    - When running inside Docker, 'localhost' points to the container itself.
      To reach host services, map localhost to 'host.docker.internal' (or gateway IP).
      Preserves 127.0.0.1 on backend container port (8085) and test mock ports (>10000).
    """
    if not url:
        return url
    url = url.strip()
    if re.match(r"^https?:[^\/]", url):
        url = re.sub(r"^(https?):", r"\1://", url)
    elif not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"

    # If running natively or host.docker.internal cannot be resolved, rewrite to localhost
    if not is_running_in_docker() or not can_resolve_host("host.docker.internal"):
        if "host.docker.internal" in url:
            url = url.replace("host.docker.internal", "localhost")

    # Only rewrite localhost -> host.docker.internal IF we are inside a Docker container
    if is_running_in_docker():
        m = re.match(r"^(https?://)(localhost|127\.0\.0\.1)(:\d+)?(/.*)?$", url)
        if m:
            scheme, host, port_str, path = m.groups()
            port = int(port_str[1:]) if port_str else (443 if scheme.startswith("https") else 80)
            
            # If it's the backend itself (port 8085), stay on container localhost
            if port == 8085:
                return url

            # If it's a test mock server on dynamic ephemeral port (>10000) on 127.0.0.1, stay on 127.0.0.1
            if host == "127.0.0.1" and port >= 10000:
                return url

            p_str = port_str or ""
            p_path = path or ""
            target_host = "host.docker.internal" if can_resolve_host("host.docker.internal") else "172.17.0.1"
            return f"{scheme}{target_host}{p_str}{p_path}"

    return url

def test_dhis2(base_url: str, username: Optional[str], password: Optional[str]) -> Dict[str, Any]:
    norm_base = normalize_container_url(base_url)
    url = f"{norm_base.rstrip('/')}/api/system/info"
    start = time.time()
    try:
        auth = (username, password) if username and password else None
        res = requests.get(url, auth=auth, timeout=8, headers={"Accept": "application/json"}, verify=False)
        elapsed = round((time.time() - start) * 1000, 1)
        if res.status_code == 200:
            if "application/json" in res.headers.get("content-type", "").lower():
                try:
                    data = res.json()
                    return {
                        "ok": True,
                        "status": "connected",
                        "latency_ms": elapsed,
                        "details": {
                            "version": data.get("version", "OK"),
                            "buildTime": data.get("buildTime", ""),
                            "systemName": data.get("systemName", "DHIS2")
                        }
                    }
                except Exception:
                    pass
            # Status 200 with HTML login page
            return {
                "ok": False,
                "status": "unauthorized",
                "latency_ms": elapsed,
                "error": "DHIS2 returned HTML login page. Authentication required."
            }
        elif res.status_code in (401, 403):
            return {"ok": False, "status": "unauthorized", "latency_ms": elapsed, "error": f"Invalid DHIS2 credentials (HTTP {res.status_code})"}
        elif res.status_code == 302:
            return {"ok": False, "status": "unauthorized", "latency_ms": elapsed, "error": "DHIS2 redirected to login page. Authentication required."}
        else:
            body_snippet = res.text[:300].strip().replace("\n", " ")
            return {
                "ok": False,
                "status": "error",
                "latency_ms": elapsed,
                "error": f"DHIS2 HTTP {res.status_code}",
                "response_body": body_snippet
            }
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": "unreachable", "latency_ms": 0, "error": "Connection refused or server host unreachable"}
    except Exception as e:
        return {"ok": False, "status": "error", "latency_ms": 0, "error": str(e)}

def test_openmrs(base_url: str, username: Optional[str], password: Optional[str]) -> Dict[str, Any]:
    norm_base = normalize_container_url(base_url)
    url = f"{norm_base.rstrip('/')}/ws/rest/v1/session"
    start = time.time()
    try:
        auth = (username, password) if username and password else None
        res = requests.get(url, auth=auth, timeout=8, verify=False)
        elapsed = round((time.time() - start) * 1000, 1)
        if res.status_code == 200:
            data = res.json()
            if data.get("authenticated") is True:
                user_obj = data.get("user", {})
                return {
                    "ok": True,
                    "status": "connected",
                    "latency_ms": elapsed,
                    "details": {
                        "user": user_obj.get("display", user_obj.get("username", "Authenticated")),
                        "sessionId": data.get("sessionId", "")
                    }
                }
            else:
                return {"ok": False, "status": "unauthorized", "latency_ms": elapsed, "error": "Invalid OpenMRS credentials (unauthenticated session)"}
        elif res.status_code == 401:
            return {"ok": False, "status": "unauthorized", "latency_ms": elapsed, "error": "Invalid OpenMRS credentials (401)"}
        else:
            return {"ok": False, "status": "error", "latency_ms": elapsed, "error": f"OpenMRS HTTP {res.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": "unreachable", "latency_ms": 0, "error": "Connection refused or server host unreachable"}
    except Exception as e:
        return {"ok": False, "status": "error", "latency_ms": 0, "error": str(e)}

def test_bahmni(base_url: str, username: Optional[str], password: Optional[str]) -> Dict[str, Any]:
    # Bahmni shares OpenMRS REST session endpoint
    return test_openmrs(base_url, username, password)

def test_redcap(base_url: str, token: Optional[str]) -> Dict[str, Any]:
    norm_base = normalize_container_url(base_url)
    start = time.time()
    try:
        if not token:
            return {"ok": False, "status": "not_configured", "latency_ms": 0, "error": "REDCap API token not configured"}
        payload = {
            "token": token,
            "content": "version",
            "format": "json"
        }
        res = requests.post(norm_base, data=payload, timeout=8, verify=False)
        elapsed = round((time.time() - start) * 1000, 1)
        if res.status_code == 200 and res.text:
            return {
                "ok": True,
                "status": "connected",
                "latency_ms": elapsed,
                "details": {"version": res.text.strip()}
            }
        else:
            return {"ok": False, "status": "error", "latency_ms": elapsed, "error": f"REDCap response: {res.text[:100]}"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": "unreachable", "latency_ms": 0, "error": "REDCap server host unreachable"}
    except Exception as e:
        return {"ok": False, "status": "error", "latency_ms": 0, "error": str(e)}

def test_mediator(base_url: str) -> Dict[str, Any]:
    norm_base = normalize_container_url(base_url)
    url = f"{norm_base.rstrip('/')}/health"
    start = time.time()
    try:
        res = requests.get(url, timeout=5)
        elapsed = round((time.time() - start) * 1000, 1)
        if res.status_code == 200:
            return {
                "ok": True,
                "status": "connected",
                "latency_ms": elapsed,
                "details": res.json() if res.headers.get("content-type", "").startswith("application/json") else {"status": "healthy"}
            }
        else:
            return {"ok": False, "status": "error", "latency_ms": elapsed, "error": f"Mediator HTTP {res.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": "unreachable", "latency_ms": 0, "error": "Mediator service not responding or offline"}
    except Exception as e:
        return {"ok": False, "status": "error", "latency_ms": 0, "error": str(e)}

def test_system_connection(system: str, base_url: str, username: Optional[str] = None, secret: Optional[str] = None) -> Dict[str, Any]:
    norm_url = normalize_container_url(base_url)
    sys_lower = system.lower()
    if sys_lower in ("dhis2", "dhis2_online", "dhis2_offline", "dhis2_moh", "moh", "moh_dhis2"):
        return test_dhis2(norm_url, username, secret)
    elif sys_lower in ("openmrs", "openmrs3"):
        return test_openmrs(norm_url, username, secret)
    elif sys_lower == "bahmni":
        return test_bahmni(norm_url, username, secret)
    elif sys_lower == "redcap":
        return test_redcap(norm_url, secret)
    elif sys_lower == "mediator":
        return test_mediator(norm_url)
    else:
        return {"ok": False, "status": "unsupported", "error": f"Unknown system {system}"}
