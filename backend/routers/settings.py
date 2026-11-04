from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from backend.core.database import list_server_connections, get_server_connection, update_server_connection
from backend.core.connections import normalize_container_url
from backend.core.security import mask_secret
from backend.core.config import settings
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/settings", tags=["Settings"])

class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    base_url: str
    username: Optional[str] = ""
    secret: Optional[str] = None

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

@router.get("/connections")
def get_settings_connections():
    conns = list_server_connections()
    output = []
    for c in conns:
        sys_key = c["system"]
        full = get_server_connection(sys_key)
        has_secret = bool(full and full.get("secret"))
        raw_url = c.get("base_url", "")
        eff_url = full.get("base_url") if full else normalize_container_url(raw_url)
        secret_val = full.get("secret") if full else ""
        is_conf = _is_configured(raw_url, secret_val)

        env_val = _get_env_url(sys_key)
        env_url = env_val if (env_val and env_val.rstrip("/") != raw_url.rstrip("/")) else None

        output.append({
            "system": c["system"],
            "name": c["name"],
            "base_url": c["base_url"],
            "username": c.get("username", ""),
            "has_secret": has_secret,
            "secret_masked": mask_secret(full.get("secret", "")) if has_secret else "",
            "updated_at": c["updated_at"],
            # Additive fields per UI specification
            "configured_url": raw_url,
            "effective_url": eff_url,
            "source": "vault",
            "env_url": env_url,
            "configured": is_conf,
            "status": "not_configured" if not is_conf else "checking",
        })
    return output

@router.put("/connections/{system}")
def save_connection_settings(system: str, update: ConnectionUpdate, user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("role") not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Only admins and operators can modify server configurations")

    secret_val = update.secret
    if secret_val and "•" in secret_val:
        # User didn't change masked secret; keep existing
        existing = get_server_connection(system)
        secret_val = existing.get("secret", "") if existing else ""

    update_server_connection(
        system=system,
        base_url=update.base_url,
        username=update.username,
        secret=secret_val,
        name=update.name
    )
    return {"ok": True, "message": f"Saved connection settings for {system}"}
