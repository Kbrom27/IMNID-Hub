from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from backend.core.database import list_server_connections, get_server_connection
from backend.core.connections import test_system_connection, normalize_container_url
from backend.core.config import settings

router = APIRouter(prefix="/api/connections", tags=["Connections"])

class TestConnectionRequest(BaseModel):
    system: str
    base_url: Optional[str] = ""
    username: Optional[str] = ""
    secret: Optional[str] = ""

def _get_env_url(system: str) -> str:
    s = system.lower()
    if s in ("openmrs", "openmrs3"):
        return settings.OPENMRS_URL
    elif s == "bahmni":
        return settings.BAHMNI_URL
    elif s == "dhis2_online":
        return settings.DHIS2_ONLINE_URL or settings.DHIS2_URL
    elif s == "dhis2_offline":
        return settings.DHIS2_OFFLINE_URL
    elif s in ("dhis2_moh", "moh", "moh_dhis2"):
        return settings.DHIS2_MOH_URL
    elif s == "dhis2":
        return settings.DHIS2_URL
    elif s == "redcap":
        return settings.REDCAP_URL
    elif s == "mediator":
        return settings.MEDIATOR_URL
    return ""

def _is_configured(url: Optional[str], secret: Optional[str] = None) -> bool:
    if not url or not url.strip():
        return False
    u = url.lower()
    if "example.org" in u or "example.com" in u:
        return False
    if secret and "yourdhis2passwordhere" in secret.lower():
        return False
    return True

@router.get("/status")
def get_all_connection_statuses():
    conns = list_server_connections()
    results = {}
    for c in conns:
        sys_key = c["system"]
        full = get_server_connection(sys_key)
        if full:
            raw_url = full.get("raw_base_url") or c.get("base_url") or ""
            eff_url = full.get("base_url") or normalize_container_url(raw_url)
            secret_val = full.get("secret")
            is_conf = _is_configured(raw_url, secret_val)

            env_val = _get_env_url(sys_key)
            env_url = env_val if (env_val and env_val.rstrip("/") != raw_url.rstrip("/")) else None

            if not is_conf:
                res = {
                    "ok": False,
                    "status": "not_configured",
                    "latency_ms": 0,
                    "error": f"{full['name']} is not configured or uses a placeholder URL",
                }
                status_state = "not_configured"
            else:
                res = test_system_connection(
                    system=sys_key,
                    base_url=eff_url,
                    username=full.get("username"),
                    secret=secret_val
                )
                status_state = "connected" if res.get("ok") else "unreachable"

            results[sys_key] = {
                "name": full["name"],
                "base_url": eff_url,
                "username": full.get("username"),
                "result": res,
                # Additive fields per UI specification
                "configured_url": raw_url,
                "effective_url": eff_url,
                "source": "vault",
                "env_url": env_url,
                "configured": is_conf,
                "status": status_state,
            }
    if "dhis2_online" in results and "dhis2" not in results:
        results["dhis2"] = results["dhis2_online"]
    return results

@router.post("/test")
def test_single_connection(req: TestConnectionRequest):
    saved = get_server_connection(req.system)

    # 1. Base URL resolution: if empty, use saved URL
    base_url_to_use = req.base_url.strip() if req.base_url else ""
    if not base_url_to_use:
        if saved and saved.get("base_url"):
            base_url_to_use = saved["base_url"]
        else:
            env_val = _get_env_url(req.system)
            if env_val:
                base_url_to_use = normalize_container_url(env_val)

    # 2. Secret resolution (Never return or log secret)
    secret_to_use = req.secret
    if not secret_to_use or "•" in secret_to_use:
        if saved:
            secret_to_use = saved.get("secret", "")

    # If still no URL or placeholder, return status "not_configured" (not an error)
    if not base_url_to_use or not _is_configured(base_url_to_use, secret_to_use):
        return {
            "ok": False,
            "status": "not_configured",
            "latency_ms": 0,
            "error": f"{req.system} is not configured or uses a placeholder URL",
        }

    # 3. Username resolution: if empty, use saved username
    username_to_use = req.username if (req.username is not None and req.username != "") else (saved.get("username", "") if saved else "")

    res = test_system_connection(
        system=req.system,
        base_url=base_url_to_use,
        username=username_to_use,
        secret=secret_to_use
    )
    return res
