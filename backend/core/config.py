import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Application & Server Ports
    FRONTEND_PORT: int = 3000
    BACKEND_PORT: int = 8085
    MEDIATOR_PORT: int = 8000

    # Application Environment
    APP_ENV: str = "production"

    # Initial Admin Password (must be configured in .env; forced change on first login)
    ADMIN_INITIAL_PASSWORD: str = ""

    # Security & Encryption
    JWT_SECRET: str = "imnid-hub-default-jwt-secret-key-32chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    APP_SECRET_KEY: str = "imnid-hub-encryption-secret-key-32chars!"

    # DHIS2 Online Server (Central / Target Server)
    DHIS2_ONLINE_URL: str = ""
    DHIS2_ONLINE_USERNAME: str = ""
    DHIS2_ONLINE_PASSWORD: str = ""

    # DHIS2 Offline Server (Local / Facility / Source Server)
    DHIS2_OFFLINE_URL: str = "http://host.docker.internal:8080/dhis"
    DHIS2_OFFLINE_USERNAME: str = "admin"
    DHIS2_OFFLINE_PASSWORD: str = "district"

    # DHIS2 MOH Aggregate Server (National Central Server)
    DHIS2_MOH_URL: str = "https://dhis.moh.gov.et"
    DHIS2_MOH_USERNAME: str = "kbrom"
    DHIS2_MOH_PASSWORD: str = ""

    # Default DHIS2 Tracker Server (Legacy / Alias)
    DHIS2_URL: str = ""
    DHIS2_USERNAME: str = ""
    DHIS2_PASSWORD: str = ""

    OPENMRS_URL: str = "http://host.docker.internal:8080/openmrs"
    OPENMRS_USERNAME: str = ""
    OPENMRS_PASSWORD: str = ""

    BAHMNI_URL: str = "http://host.docker.internal:8080/openmrs"
    BAHMNI_USERNAME: str = ""
    BAHMNI_PASSWORD: str = ""

    REDCAP_URL: str = "https://redcap.example.org/api/"
    REDCAP_TOKEN: str = ""

    MEDIATOR_URL: str = "http://mediator:8000"
    BACKEND_URL: str = "http://backend:8085"

    # Storage Paths
    DATA_DIR: str = os.getenv("DATA_DIR", str(Path(__file__).resolve().parent.parent.parent / "data"))

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def uploads_dir(self) -> Path:
        p = Path(self.DATA_DIR) / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def exports_dir(self) -> Path:
        p = Path(self.DATA_DIR) / "exports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def logs_dir(self) -> Path:
        p = Path(self.DATA_DIR) / "logs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def checkpoints_dir(self) -> Path:
        p = Path(self.DATA_DIR) / "checkpoints"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        db_dir = Path(self.DATA_DIR) / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        return db_dir / "imnid.db"

settings = Settings()
