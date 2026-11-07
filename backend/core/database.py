import sqlite3
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from backend.core.config import settings
from backend.core.security import hash_password, encrypt_secret, decrypt_secret
from backend.core.connections import normalize_container_url, is_running_in_docker
import re

def clean_base_url(url: str) -> str:
    if not url:
        return url
    url = url.strip()
    if re.match(r"^https?:[^\/]", url):
        url = re.sub(r"^(https?):", r"\1://", url)
    elif not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    return url

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.db_path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',
        must_change_password INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """
    )

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
    except Exception:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_connections (
        system TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        base_url TEXT NOT NULL,
        username TEXT,
        encrypted_secret TEXT,
        is_active INTEGER DEFAULT 1,
        updated_at TEXT NOT NULL
    );
    """
    )

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        module TEXT NOT NULL,
        action TEXT NOT NULL,
        status TEXT NOT NULL,
        progress INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        fail_count INTEGER DEFAULT 0,
        message TEXT,
        errors TEXT,
        result_file TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT
    );
    """
    )

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS checkpoints (
        module TEXT NOT NULL,
        checkpoint_key TEXT NOT NULL,
        data_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (module, checkpoint_key)
    );
    """
    )

    conn.commit()

    # Seed admin user if empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        now = datetime.now(timezone.utc).isoformat()
        initial_pwd = (settings.ADMIN_INITIAL_PASSWORD or "").strip() or "admin123"
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, must_change_password, created_at) VALUES (?, ?, ?, ?, ?)",
            ("admin", hash_password(initial_pwd), "admin", 1, now)
        )
        conn.commit()

    now = datetime.now(timezone.utc).isoformat()
    online_url = settings.DHIS2_ONLINE_URL or settings.DHIS2_URL or "https://imnid.aau.edu.et/dhis"
    online_user = settings.DHIS2_ONLINE_USERNAME or settings.DHIS2_USERNAME or "admin"
    online_pwd = settings.DHIS2_ONLINE_PASSWORD or settings.DHIS2_PASSWORD or "district"

    offline_url = settings.DHIS2_OFFLINE_URL or "http://localhost:8080/dhis"
    offline_user = settings.DHIS2_OFFLINE_USERNAME or "admin"
    offline_pwd = settings.DHIS2_OFFLINE_PASSWORD or "district"

    moh_url = settings.DHIS2_MOH_URL or "https://dhis.moh.gov.et"
    moh_user = settings.DHIS2_MOH_USERNAME or "kbrom"
    moh_pwd = settings.DHIS2_MOH_PASSWORD or ""

    # Seed default server connections if empty
    cursor.execute("SELECT COUNT(*) FROM server_connections")
    if cursor.fetchone()[0] == 0:
        default_conns = [
            ("dhis2_online", "DHIS2 Online (Central Server)", online_url, online_user, encrypt_secret(online_pwd), 1, now),
            ("dhis2_offline", "DHIS2 Offline (Local Instance)", offline_url, offline_user, encrypt_secret(offline_pwd), 1, now),
            ("dhis2_moh", "DHIS2 MOH (National Aggregate Server)", moh_url, moh_user, encrypt_secret(moh_pwd), 1, now),
            ("openmrs", "OpenMRS 3.x", settings.OPENMRS_URL, settings.OPENMRS_USERNAME, encrypt_secret(settings.OPENMRS_PASSWORD), 1, now),
            ("bahmni", "Bahmni 0.93", settings.BAHMNI_URL, settings.BAHMNI_USERNAME, encrypt_secret(settings.BAHMNI_PASSWORD), 1, now),
            ("redcap", "REDCap", settings.REDCAP_URL, "token_auth", encrypt_secret(settings.REDCAP_TOKEN), 1, now),
            ("mediator", "Mediator", settings.MEDIATOR_URL, "", encrypt_secret(""), 1, now)
        ]
        cursor.executemany(
            """
            INSERT INTO server_connections (system, name, base_url, username, encrypted_secret, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            default_conns
        )
        conn.commit()
    else:
        # Migration: Ensure dhis2_online, dhis2_offline, and dhis2_moh exist if database was already seeded
        legacy_dhis2 = conn.execute("SELECT * FROM server_connections WHERE system = 'dhis2'").fetchone()
        if legacy_dhis2:
            online_url = legacy_dhis2["base_url"] or online_url
            online_user = legacy_dhis2["username"] or online_user
            online_pwd = decrypt_secret(legacy_dhis2["encrypted_secret"]) if legacy_dhis2["encrypted_secret"] else online_pwd
            cursor.execute("DELETE FROM server_connections WHERE system = 'dhis2'")

        has_online = conn.execute("SELECT 1 FROM server_connections WHERE system = 'dhis2_online'").fetchone()
        if not has_online:
            cursor.execute(
                """
                INSERT INTO server_connections (system, name, base_url, username, encrypted_secret, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("dhis2_online", "DHIS2 Online (Central Server)", online_url, online_user, encrypt_secret(online_pwd), 1, now)
            )

        has_offline = conn.execute("SELECT 1 FROM server_connections WHERE system = 'dhis2_offline'").fetchone()
        if not has_offline:
            cursor.execute(
                """
                INSERT INTO server_connections (system, name, base_url, username, encrypted_secret, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("dhis2_offline", "DHIS2 Offline (Local Instance)", offline_url, offline_user, encrypt_secret(offline_pwd), 1, now)
            )

        has_moh = conn.execute("SELECT 1 FROM server_connections WHERE system = 'dhis2_moh'").fetchone()
        if not has_moh:
            cursor.execute(
                """
                INSERT INTO server_connections (system, name, base_url, username, encrypted_secret, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("dhis2_moh", "DHIS2 MOH (National Aggregate Server)", moh_url, moh_user, encrypt_secret(moh_pwd), 1, now)
            )

        # Clean up legacy host.docker.internal in existing installations running natively
        if not is_running_in_docker():
            cursor.execute("UPDATE server_connections SET base_url = REPLACE(base_url, 'host.docker.internal', 'localhost') WHERE base_url LIKE '%host.docker.internal%'")

        conn.commit()

    conn.close()

def get_server_connection(system: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM server_connections WHERE system = ?", (system,)).fetchone()
    # Backwards compatibility: fall back to dhis2_online when 'dhis2' is requested
    if not row and system in ("dhis2", "dhis2_online"):
        row = conn.execute("SELECT * FROM server_connections WHERE system = 'dhis2_online'").fetchone()
        if not row:
            row = conn.execute("SELECT * FROM server_connections WHERE system = 'dhis2'").fetchone()
    if not row and system == "dhis2_offline":
        row = conn.execute("SELECT * FROM server_connections WHERE system = 'dhis2_offline'").fetchone()
    if not row and system in ("dhis2_moh", "moh", "moh_dhis2"):
        row = conn.execute("SELECT * FROM server_connections WHERE system = 'dhis2_moh'").fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["secret"] = decrypt_secret(d.get("encrypted_secret", ""))
    d["raw_base_url"] = d.get("base_url", "")
    d["base_url"] = normalize_container_url(d.get("base_url", ""))
    return d

def update_server_connection(system: str, base_url: str, username: Optional[str], secret: Optional[str], name: Optional[str] = None):
    conn = get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    clean_url = clean_base_url(base_url)
    existing = conn.execute("SELECT * FROM server_connections WHERE system = ?", (system,)).fetchone()
    if existing:
        enc = encrypt_secret(secret) if secret is not None else existing["encrypted_secret"]
        u_name = name or existing["name"]
        u_user = username if username is not None else existing["username"]
        conn.execute(
            """
            UPDATE server_connections
            SET base_url = ?, username = ?, encrypted_secret = ?, name = ?, updated_at = ?
            WHERE system = ?
            """,
            (clean_url, u_user, enc, u_name, now, system)
        )
    else:
        conn.execute(
            """
            INSERT INTO server_connections (system, name, base_url, username, encrypted_secret, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (system, name or system.upper(), clean_url, username or "", encrypt_secret(secret or ""), now)
        )
    conn.commit()
    conn.close()

def list_server_connections() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT system, name, base_url, username, is_active, updated_at FROM server_connections ORDER BY system").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_checkpoint(module: str, checkpoint_key: str, data: Dict[str, Any]):
    conn = get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO checkpoints (module, checkpoint_key, data_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(module, checkpoint_key) DO UPDATE SET data_json = excluded.data_json, updated_at = excluded.updated_at
        """,
        (module, checkpoint_key, json.dumps(data), now)
    )
    conn.commit()
    conn.close()

def get_checkpoint(module: str, checkpoint_key: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    row = conn.execute("SELECT data_json FROM checkpoints WHERE module = ? AND checkpoint_key = ?", (module, checkpoint_key)).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["data_json"])
        except Exception:
            return None
    return None

def update_user_password(user_id: int, new_password: str):
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (hash_password(new_password), user_id)
    )
    conn.commit()
    conn.close()

