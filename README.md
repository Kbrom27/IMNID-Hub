# IMNID Hub - Integrated Health Data & Interoperability Platform

[![System Parity](https://img.shields.io/badge/Feature%20Parity-50%2F50%20(100%25)-brightgreen.svg)](#feature-matrix)
[![Architecture](https://img.shields.io/badge/Architecture-FastAPI%20%2B%20React%20%2B%20Docker-blue.svg)](#architecture)
[![License](https://img.shields.io/badge/License-Proprietary-orange.svg)](#license)

**IMNID Hub** is an enterprise-grade, unified web platform designed for the Ethiopian Maternal, Neonatal, and Child Health clinical and research ecosystem. It consolidates five previously disconnected desktop applications, CLI scripts, and microservices into a single, cohesive, modern web application:

1. **SmartCare to OpenMRS 3.x Migration** (legacy patient records transformation & ingestion)
2. **IMNID Data Management** (DHIS2 Tracker synchronization, REDCap pipelines, wide flattening, analysis exports)
3. **EMR to DHIS2 Interoperability & Mediator** (Bahmni 0.93 & OpenMRS 3.x to DHIS2 Tracker sync with checkpointing)
4. **OpenMRS Concept & Form Management** (interactive form designer, schema compilers, concept set synchronization)
5. **HMIS Reporting Suite** (MOH Delivery Register RMH 01.2 & NICU Register NH 04.2 with Ethiopian calendar support)

---

## Architecture Overview

```
                                      +-----------------------------------------+
                                      |            Browser Client               |
                                      |  (React 18 + Vite + TailwindCSS + SSE)  |
                                      |             Port: 3000                  |
                                      +--------------------+--------------------+
                                                           |
                                               HTTP / SSE  |
                                                           v
                                      +-----------------------------------------+
                                      |           IMNID Hub Backend             |
                                      |          FastAPI (Port: 8085)           |
                                      |-----------------------------------------|
                                      | - JWT Auth & Encrypted Credential Vault |
                                      | - Background Job Engine & SSE Dispatch  |
                                      | - Unified Modules:                      |
                                      |   * SmartCare Migration Engine          |
                                      |   * Data Management Services            |
                                      |   * EMR-DHIS2 Sync Core                 |
                                      |   * Concept & Form Tools Compiler       |
                                      |   * HMIS Aggregator (RMH & NH)          |
                                      +----------+-------------------+----------+
                                                 |                   |
                     Internal Docker Bridge      |                   |
                     HTTP Proxy                  v                   v
+-------------------------------+  +-----------------------------+  +-------------------------------+
|     EMR-DHIS2 Mediator        |  |     Shared Volumes          |  |       External Health         |
|   FastAPI Service (Port: 8000)|  |  - /data/db (SQLite)        |  |          Systems              |
|-------------------------------|  |  - /data/uploads            |  |-------------------------------|
| - Scheduled Background Sync   |  |  - /data/exports            |  | - OpenMRS 3.x / Bahmni 0.93   |
| - Checkpoint Engine           |  |  - /data/logs               |  | - DHIS2 Tracker & Aggregate   |
| - Standalone Sync Endpoints   |  |  - /data/checkpoints        |  | - REDCap API                  |
+-------------------------------+  +-----------------------------+  +-------------------------------+
```

---

## Key Features & 100% Migration Parity (50 / 50 Features)

### 1. SmartCare to OpenMRS 3.x Migration (SC-01 .. SC-07)
- **SC-01**: OpenMRS 3.x live connection and session verification (`POST /api/smartcare/connect`).
- **SC-02**: SmartCare patient extract CSV file upload with validation (`POST /api/smartcare/upload`).
- **SC-03**: Pre-import dry-run transformation and anomaly detection (`POST /api/smartcare/dry-run`).
- **SC-04**: Luhn algorithm check-digit MRN formatting (`XXXXXX-C`).
- **SC-05**: RFC-4122 canonical UUID normalizer for 32-character GUIDs.
- **SC-06**: Live batch migration worker with real-time SSE progress streaming (`POST /api/smartcare/import`).
- **SC-07**: Instant asynchronous job cancellation (`POST /api/jobs/{id}/cancel`).

### 2. IMNID Data Management (DM-01 .. DM-10)
- **DM-01**: DHIS2 metadata package importer with conflict detection (`POST /api/data-management/metadata-import`).
- **DM-02**: Bi-directional DHIS2 Tracker synchronization (`POST /api/data-management/dhis2-sync`).
- **DM-03**: Tracker synchronization data export (`POST /api/data-management/export-sync`).
- **DM-04**: Automated REDCap to DHIS2 Tracker ETL pipeline (`POST /api/data-management/import-redcap`).
- **DM-05**: Bulk CSV to DHIS2 Tracker importer (`POST /api/data-management/import-csv`).
- **DM-06**: Wide analytical data export with human-readable labels (`POST /api/data-management/export-analysis`).
- **DM-07**: Pure Pandas one-row-per-TEI wide flattening engine (`POST /api/data-management/clean-tei`).
- **DM-08**: Multi-tab Excel data dictionary generator (`POST /api/data-management/data-dictionary`).
- **DM-09**: Neonatal Clinical Form (NCF) to Neonatal Inpatient Database (NID) sync (`POST /api/data-management/ncf-nid-sync`).
- **DM-10**: Deterministic Mother-Neonate relationship linker (`POST /api/data-management/link-mother-neonate`).

### 3. EMR-DHIS2 Interoperability & Standalone Mediator (INT-01 .. INT-11)
- **INT-01**: Bahmni 0.93 EMR encounter extract pipeline (`POST /api/interop/bahmni/export`).
- **INT-02**: Bahmni encounter data transformer (`POST /api/interop/bahmni/transform`).
- **INT-03**: Bahmni to DHIS2 Tracker direct importer (`POST /api/interop/bahmni/import`).
- **INT-04**: Full Bahmni-DHIS2 automated sync pipeline with dry-run support (`POST /api/interop/bahmni/sync`).
- **INT-05**: OpenMRS 3.x FHIR/REST encounter extractor (`POST /api/interop/openmrs/export`).
- **INT-06**: OpenMRS 3.x encounter data transformer (`POST /api/interop/openmrs/transform`).
- **INT-07**: OpenMRS 3.x to DHIS2 automated sync pipeline (`POST /api/interop/openmrs/sync`).
- **INT-08**: Checkpoint Stop & Resume engine (`GET/POST /api/interop/checkpoints`).
- **INT-09**: Interactive Concept & Value Mapping manager (`GET/POST /api/interop/mappings`).
- **INT-10**: Standalone Mediator service management (`GET /api/interop/mediator/status`).
- **INT-11**: EMR sync audit log viewer and export (`GET /api/interop/logs`).

### 4. OpenMRS Concept & Form Management (CM-01 .. CM-15)
- **CM-01**: Interactive Drag-and-Drop Web Form Designer (`GET/POST /api/concept-management/form-designer`).
- **CM-02**: Concept CSV/JSON validation and syntax checking (`POST /api/concept-management/concepts/validate`).
- **CM-03**: OpenMRS 3.x concept batch creation and update (`POST /api/concept-management/concepts/import`).
- **CM-04**: Concept mapping manager (`SAME-AS`, `NARROWER-THAN`, `BROADER-THAN`).
- **CM-05**: Concept Set organizer with ordered member resolution (`POST /api/concept-management/concept-sets`).
- **CM-06**: Concept class and datatype dictionary manager (`GET /api/concept-management/classes-datatypes`).
- **CM-07**: Interactive Schema Builder with live preview (`POST /api/concept-management/schemas/build`).
- **CM-08**: Schema validation against OpenMRS 3.x form schema specification (`POST /api/concept-management/schemas/validate`).
- **CM-09**: Form schema parser and AST visualizer (`POST /api/concept-management/schemas/parse`).
- **CM-10**: Schema format conversion between O3 Form Engine JSON and markdown tables (`POST /api/concept-management/schemas/convert`).
- **CM-11**: Form-to-Concept binding auditor (`POST /api/concept-management/schemas/audit-concepts`).
- **CM-12**: Bulk schema folder importer and packager (`POST /api/concept-management/schemas/bulk-import`).
- **CM-13**: Schema concept merger and conflict resolver (`POST /api/concept-management/schemas/merge`).
- **CM-14**: Form retirement and unretirement workflow (`POST /api/concept-management/forms/retire`).
- **CM-15**: Complete form package export with metadata bundle zip (`POST /api/concept-management/forms/export`).

### 5. HMIS Reporting Tools (HM-01 .. HM-07)
- **HM-01**: DHIS2 metadata discovery and Ethiopian calendar month converter (`POST /api/hmis/connect`).
- **HM-02**: RMH (01.2) Delivery Register generation from DHIS2 Tracker long-format CSV (`POST /api/hmis/rmh/delivery-register-csv`).
- **HM-03**: RMH (01.2) Delivery Register direct generation from live DHIS2 API (`POST /api/hmis/rmh/delivery-register-dhis2`).
- **HM-04**: RMH (01.2) Monthly Aggregate Report with tally preview and DHIS2 import payload (`POST /api/hmis/rmh/aggregate-report`).
- **HM-05**: NH (04.2) NICU Register generation from DHIS2 Tracker long-format CSV (`POST /api/hmis/nh/nicu-register-csv`).
- **HM-06**: NH (04.2) NICU Register direct generation from live DHIS2 API (`POST /api/hmis/nh/nicu-register-dhis2`).
- **HM-07**: NH (04.2) Monthly Aggregate Report with tally preview and DHIS2 import payload (`POST /api/hmis/nh/aggregate-report`).

---

## Quickstart & Deployment

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) (v24.0+)
- [Docker Compose](https://docs.docker.com/compose/) (v2.20+)

### 1. Clone & Configure Environment
```bash
cd "/home/kbrom/Work/IMNID/IMNID Developments/IMNID-Hub"
cp .env.example .env
```
Review `.env` and configure credentials:
```ini
ADMIN_INITIAL_PASSWORD=ChangeMeNow123!
FRONTEND_PORT=3000
BACKEND_PORT=8085
MEDIATOR_PORT=8000
# DHIS2 Online (Central) & Offline (Local)
DHIS2_ONLINE_URL=https://imnid.aau.edu.et/dhis
DHIS2_OFFLINE_URL=http://host.docker.internal:8080/dhis
OPENMRS_URL=http://host.docker.internal:8080/openmrs
BAHMNI_URL=http://host.docker.internal:8080/openmrs
```

### 2. Launch Containers
```bash
docker compose up --build -d
```

### 3. Verify Health
Check container status:
```bash
docker compose ps
```
All three containers (`imnid_hub_backend`, `imnid_hub_frontend`, `imnid_hub_mediator`) should report `healthy` or `running`.

---

## Access Points

| Component | Port | URL | Description |
|-----------|------|-----|-------------|
| **Frontend Web App** | `3000` | `http://localhost:3000` | Interactive Web UI with full dark/light theme, live terminal logs, and tabular data previews |
| **Backend API** | `8085` | `http://localhost:8085` | Core REST API with OpenAPI documentation |
| **Backend Swagger Docs** | `8085` | `http://localhost:8085/docs` | Interactive Swagger UI for testing API endpoints |
| **Mediator API** | `8000` | `http://localhost:8000` | Standalone EMR-DHIS2 Sync Mediator |
| **Mediator Swagger Docs** | `8000` | `http://localhost:8000/docs` | Mediator Swagger specification and health probes |

### Default Credentials
- **Username**: `admin`
- **Password**: Defined in `.env` (`ChangeMeNow123!`)

---

## Master Verification Suite

IMNID Hub includes an automated, end-to-end Master Verification Suite testing all 50 features across all 5 modules with side-by-side behavioral assertions against source repository baseline logic.

### Running All Tests in Docker
```bash
docker exec imnid_hub_backend python /app/tests/run_all_tests.py
```

### Sample Output
```
================================================================================
                       MASTER VERIFICATION GRAND SUMMARY                        
================================================================================
Module Name                                   | Scope           | Status      
--------------------------------------------------------------------------------
SmartCare Migration (SC-01..SC-07)            | 7 Features      | PASSED [OK] 
Data Management (DM-01..DM-10)                | 10 Features     | PASSED [OK] 
Interop & Mediator (INT-01..INT-11)           | 11 Features     | PASSED [OK] 
Concept & Form Mgmt (CM-01..CM-15)            | 15 Features     | PASSED [OK] 
HMIS Reporting (HM-01..HM-07)                 | 7 Features      | PASSED [OK] 
================================================================================
TOTAL FEATURE PARITY: 50 / 50 FEATURES VERIFIED (100.0%)
EXECUTION DURATION  : 20.68 seconds
================================================================================

>>> ALL 5 MODULE TEST SUITES PASSED WITH ZERO ERRORS. SYSTEM FULLY VALIDATED. <<<
```

### Running Individual Module Tests
- **SmartCare Migration**: `python3 tests/smoke_smartcare.py`
- **Data Management (10 features)**: `docker exec imnid_hub_backend python /app/tests/e2e_data_management.py`
- **EMR-DHIS2 Interoperability (11 features)**: `docker exec imnid_hub_backend python /app/tests/test_phase4_e2e.py`
- **Concept & Form Management (15 features)**: `docker exec imnid_hub_backend python /app/tests/test_phase5_smoke.py`
- **HMIS Reporting (7 features)**: `docker exec imnid_hub_backend python /app/tests/test_phase6_smoke.py`

---

## Directory Structure

```
IMNID-Hub/
├── backend/                  # FastAPI Application Root
│   ├── app.py                # Main Application Entry Point & Router Assembly
│   ├── core/                 # Auth, Database, Security, Job Engine, Config
│   ├── modules/              # 5 Consolidated Modules
│   │   ├── smartcare/        # SmartCare to OpenMRS 3.x Migration
│   │   ├── data_management/  # DHIS2, REDCap, Sync, Linker, Clean, Exports
│   │   ├── interop/          # Bahmni, OpenMRS 3.x, Mediator, Checkpoints
│   │   ├── concept_mgmt/     # Forms Designer, Concepts, Schemas, Mergers
│   │   └── hmis/             # RMH 01.2 & NH 04.2 Register and Aggregate Reports
│   ├── requirements.txt      # Python Dependencies
│   └── Dockerfile            # Backend Docker Image
├── frontend/                 # React 18 + Vite Web Application
│   ├── src/
│   │   ├── pages/            # View Pages (SmartCare, DataMgmt, Interop, Concepts, HMIS, Jobs)
│   │   ├── components/       # UI Primitives, Navigation, Terminals, Cards, Badges
│   │   └── services/         # Axios API Clients & SSE Listeners
│   ├── package.json          # Node Dependencies
│   └── Dockerfile            # Nginx Production Frontend Image
├── mediator/                 # Standalone Interoperability Mediator Microservice
│   ├── main.py               # Mediator FastAPI Application
│   ├── requirements.txt      # Mediator Dependencies
│   └── Dockerfile            # Mediator Docker Image
├── tests/                    # Master & Individual Test Suites
│   ├── run_all_tests.py      # Master Test Runner (50 Features)
│   ├── e2e_data_management.py# Data Management E2E (DM-01..DM-10)
│   ├── test_phase4_e2e.py    # Interoperability E2E (INT-01..INT-11)
│   ├── test_phase5_smoke.py  # Concept & Form Tools Smoke (CM-01..CM-15)
│   ├── test_phase6_smoke.py  # HMIS Reporting Smoke (HM-01..HM-07)
│   └── smoke_smartcare.py    # SmartCare Parity Verification (SC-01..SC-07)
├── docs/                     # Documentation & Parity Mappings
│   ├── MIGRATION_MAP.md      # Exhaustive 50-Feature Parity Contract
│   └── port_diffs/           # Behavioral Side-by-Side Equivalence Logs
├── docker-compose.yml        # Production Multi-Container Orchestration
├── .env.example              # Template Environment File
└── README.md                 # Complete System Guide
```

---

## Source Repositories & Data Integrity

The original source repositories:
- `Smartcare-Openmrs03`
- `IMNID Data Management App`
- `EMR-DHIS2 Tracker Interoperability`
- `Openmrs Concept Management`
- `HMIS Report`

remain **100% read-only and preserved**. All features, logic, and schemas have been migrated directly into `IMNID-Hub` without altering or removing source project files.

---

## Handover & Maintenance

1. **Database Persistence**: SQLite database and job states are persisted in the named Docker volume `imnid_data`.
2. **File Retention**: Uploads and exports are persisted in `imnid_uploads` and `imnid_exports`.
3. **Log Rotation**: Application logs and SSE stream archives are stored in `imnid_logs`.
4. **Stopping Services**: Run `docker compose down` (use `-v` only if you intend to wipe database volumes).
5. **Restarting Services**: Run `docker compose up -d`. All containers will automatically reattach to existing persistent volumes.
