"""Service layer orchestrating HMIS reporting background workers (HM-01 through HM-07)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from openpyxl import Workbook

from backend.core.config import settings
from backend.core.storage import resolve_output_dir
from backend.core.jobs.engine import JobContext

from backend.modules.hmis.dhis2_client import DHIS2Client
from backend.modules.hmis.ethiopian_calendar import (
    ethiopian_month_window,
    get_calendar_info,
)
from backend.modules.hmis.rmh_delivery_register import (
    build_register,
    compute_tally,
    filter_df as filter_rmh_df,
    load as load_rmh_csv,
    write_sheet as write_rmh_sheet,
    write_tally_sheet as write_rmh_tally_sheet,
    RAW as RMH_RAW,
)
from backend.modules.hmis.rmh_delivery_register_dhis2 import (
    MetadataResolver as RMHMetadataResolver,
    TEIFetcher as RMHTEIFetcher,
    generate_excel as generate_rmh_dhis2_excel,
    resolve_ou_uid as resolve_rmh_ou_uid,
)
from backend.modules.hmis.rmh_aggregate_report import (
    compute_indicators as compute_rmh_indicators,
    fetch_tracker_df as fetch_rmh_tracker_df,
    write_preview_excel as write_rmh_preview_excel,
    build_import_json as build_rmh_import_json,
    resolve_ou as resolve_rmh_agg_ou,
)
from backend.modules.hmis.nh_neonatal_register import (
    build_register as build_nh_register,
    compute_tally as compute_nh_tally,
    filter_df as filter_nh_df,
    load as load_nh_csv,
    write_sheet as write_nh_sheet,
    write_tally_sheet as write_nh_tally_sheet,
    RAW as NH_RAW,
)
from backend.modules.hmis.nh_neonatal_register_dhis2 import (
    MetadataResolver as NHMetadataResolver,
    TEIFetcher as NHTEIFetcher,
    generate_excel as generate_nh_dhis2_excel,
    resolve_ou_uid as resolve_nh_ou_uid,
)
from backend.modules.hmis.nh_aggregate_report import (
    compute_indicators as compute_nh_indicators,
    fetch_tracker_df as fetch_nh_tracker_df,
    write_preview_excel as write_nh_preview_excel,
    build_import_json as build_nh_import_json,
    resolve_ou as resolve_nh_agg_ou,
)
from backend.modules.hmis.moh_aggregate import (
    MohAggregatePipeline,
    generate_periods,
)
from backend.modules.hmis.openmrs_service import (
    run_rmh_delivery_register_openmrs_worker,
    run_rmh_aggregate_report_openmrs_worker,
    run_nh_neonatal_register_openmrs_worker,
    run_nh_aggregate_report_openmrs_worker,
)


def _safe_mode(series: Any, default: str = "") -> str:
    """Safely obtain the mode of a series/column without raising on empty/NaN."""
    if series is None:
        return default
    try:
        s = pd.Series(series).dropna()
        m = s.mode()
        if not m.empty:
            return str(m.iloc[0])
    except Exception:
        pass
    return default


def _safe_date_range(series: Any) -> tuple[str, str]:
    """Safely compute (min_date_str, max_date_str) from a series or column."""
    if series is None:
        return ("—", "—")
    try:
        dt_series = pd.to_datetime(series, errors="coerce").dropna()
        if not dt_series.empty:
            return (str(dt_series.min().date()), str(dt_series.max().date()))
    except Exception:
        pass
    return ("—", "—")


# ==============================================================================
# HM-01: DHIS2 Discovery Helper
# ==============================================================================
def discover_dhis2_metadata(
    url: str,
    username: str,
    password: str,
    verify_ssl: bool = True,
) -> dict:
    client = DHIS2Client(
        url=url,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )
    res = client.discover_metadata()
    res["calendar"] = get_calendar_info()
    return res


# ==============================================================================
# HM-02: RMH Delivery Register from CSV Worker
# ==============================================================================
def run_rmh_delivery_register_csv_worker(
    ctx: JobContext,
    input_file: str,
    output_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    region: Optional[str] = None,
    facility: Optional[str] = None,
    sheet_per_facility: bool = False,
) -> dict:
    ctx.log(f"Loading maternal data CSV: {input_file}")
    df = load_rmh_csv(input_file)
    ctx.log(f"Loaded {len(df):,} records from CSV")

    df = filter_rmh_df(df, start=start, end=end, region=region, facility=facility)
    ctx.log(f"Records after date/facility filters: {len(df):,}")

    if df.empty:
        ctx.log("WARNING: No records found matching the specified filters.")

    wb = Workbook()
    wb.remove(wb.active)  # remove default sheet
    all_tallies = []

    if sheet_per_facility:
        facilities = df[RMH_RAW["facility"]].dropna().unique()
        ctx.log(f"Generating {len(facilities)} facility sheet(s)...")
        for fac in sorted(facilities):
            grp = df[df[RMH_RAW["facility"]] == fac]
            reg_name = _safe_mode(grp[RMH_RAW["region"]]) if RMH_RAW["region"] in grp else ""
            d_from, d_to = _safe_date_range(grp[RMH_RAW["enroll_date"]]) if RMH_RAW["enroll_date"] in grp else ("—", "—")

            reg = build_register(grp)
            sheet_name = str(fac)[:28].strip()
            ws = wb.create_sheet(title=sheet_name)
            write_rmh_sheet(ws, reg, fac, reg_name, d_from, d_to)

            t = compute_tally(reg)
            t["_facility"] = sheet_name
            all_tallies.append(t)
            ctx.log(f"  Processed {fac}: {len(reg)} deliveries")
    else:
        fac_list = df[RMH_RAW["facility"]].dropna().unique() if RMH_RAW["facility"] in df else []
        fac_label = fac_list[0] if len(fac_list) == 1 else (facility or f"{len(fac_list)} Facilities")
        reg_name = region or (_safe_mode(df[RMH_RAW["region"]]) if RMH_RAW["region"] in df else "")
        d_from, d_to = _safe_date_range(df[RMH_RAW["enroll_date"]]) if RMH_RAW["enroll_date"] in df else ("—", "—")

        ctx.log(f"Building register for {len(df):,} deliveries...")
        reg = build_register(df)
        ws = wb.create_sheet(title="Delivery Register")
        write_rmh_sheet(ws, reg, fac_label, str(reg_name), d_from, d_to)

        t = compute_tally(reg)
        t["_facility"] = fac_label
        all_tallies.append(t)

    # Tally Summary sheet
    ws_tally = wb.create_sheet(title="Tally Summary")
    write_rmh_tally_sheet(ws_tally, all_tallies)

    target_dir = resolve_output_dir(output_dir, settings.exports_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = (output_filename or "delivery_register_csv.xlsx").strip()
    if not out_name.lower().endswith(".xlsx"):
        out_name = f"{out_name}.xlsx"
    out_path = target_dir / out_name
    wb.save(out_path)
    ctx.log(f"Successfully generated Delivery Register workbook: {out_path.name}")

    combined_tallies = {}
    if all_tallies:
        combined_tallies = {
            k: sum(t.get(k, 0) for t in all_tallies if isinstance(t.get(k), (int, float)))
            for k in all_tallies[0]
            if not k.startswith("_")
        }

    res = {
        "status": "success",
        "total_records": len(df),
        "output_file": str(out_path),
        "output_dir": str(target_dir),
        "filename": out_path.name,
        "tallies": combined_tallies,
    }


# ==============================================================================
# HM-03: RMH Delivery Register from Live DHIS2 Worker
# ==============================================================================
def run_rmh_delivery_register_dhis2_worker(
    ctx: JobContext,
    base_url: str,
    username: str,
    password: str,
    verify_ssl: bool = True,
    program_uid: str = "Maternal Inpatient Data",
    org_unit: Optional[str] = None,
    ou_mode: str = "DESCENDANTS",
    start: Optional[str] = None,
    end: Optional[str] = None,
    output_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
    sheet_per_facility: bool = False,
    page_size: int = 250,
) -> dict:
    ctx.log(f"Connecting to DHIS2 at: {base_url}")
    client = DHIS2Client(
        url=base_url,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        log_fn=ctx.log,
    )

    ctx.log(f"Resolving program metadata for: {program_uid}")
    # If program_uid is a name, resolve UID
    resolved_prog_uid = program_uid
    try:
        progs = client.get("programs", {"fields": "id,name", "paging": "false"}).get("programs", [])
        for p in progs:
            if p["name"].strip().lower() == program_uid.strip().lower() or p["id"] == program_uid:
                resolved_prog_uid = p["id"]
                ctx.log(f"Resolved program '{p['name']}' -> UID: {resolved_prog_uid}")
                break
    except Exception as e:
        ctx.log(f"Note: program lookup check ({e})")

    cache_file = settings.exports_dir / f"hmis_rmh_meta_{resolved_prog_uid}.json"
    meta = RMHMetadataResolver(client, resolved_prog_uid, cache_file=str(cache_file))
    meta.load()

    ou_uid = None
    ou_name = "All facilities"
    if org_unit:
        try:
            ou_uid, ou_name = resolve_rmh_ou_uid(client, org_unit, resolved_prog_uid)
            ctx.log(f"Resolved org unit: {ou_name} ({ou_uid})")
        except Exception as err:
            ctx.log(f"Warning resolving org unit: {err}")
            if len(org_unit) == 11 and org_unit.isalnum():
                ou_uid = org_unit
            else:
                raise ValueError(f"Could not resolve organisation unit '{org_unit}' to a valid DHIS2 UID.")

    fetcher = RMHTEIFetcher(client, meta)
    ctx.log(f"Fetching TEIs (ouMode={ou_mode})...")
    teis = fetcher.fetch(
        program_uid=resolved_prog_uid,
        ou_uid=ou_uid,
        ou_mode=ou_mode,
        start=start,
        end=end,
        page_size=page_size,
    )
    ctx.log(f"Fetched {len(teis):,} TEI records from DHIS2")

    df = fetcher.to_dataframe(teis)
    df = RMHTEIFetcher.filter_by_delivery_date(df, start, end)
    ctx.log(f"Deliveries in target date range: {len(df):,}")

    target_dir = resolve_output_dir(output_dir, settings.exports_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = (output_filename or "delivery_register_dhis2.xlsx").strip()
    if not out_name.lower().endswith(".xlsx"):
        out_name = f"{out_name}.xlsx"
    out_path = target_dir / out_name

    class DummyArgs:
        output = str(out_path)
        pass_sheet_per_facility = sheet_per_facility
        region = ""

    DummyArgs.sheet_per_facility = sheet_per_facility
    generate_rmh_dhis2_excel(df, DummyArgs, meta, ou_name)
    ctx.log(f"Successfully generated Delivery Register workbook: {out_path.name}")

    return {
        "status": "success",
        "total_records": len(df),
        "output_file": str(out_path),
        "output_dir": str(target_dir),
        "filename": out_path.name,
    }


# ==============================================================================
# HM-04: 01.2 RMH Monthly Aggregate Report Worker
# ==============================================================================
def run_rmh_aggregate_report_worker(
    ctx: JobContext,
    base_url: str,
    username: str,
    password: str,
    verify_ssl: bool = True,
    delivery_program: str = "Maternal Inpatient Data",
    org_unit: Optional[str] = None,
    ou_mode: str = "SELECTED",
    period: str = "202610",
    start: Optional[str] = None,
    end: Optional[str] = None,
    dataset: Optional[str] = None,
    dry_run: bool = True,
    submit: bool = False,
    preview_filename: Optional[str] = None,
    json_filename: Optional[str] = None,
    export_json_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    ctx.log(f"Connecting to DHIS2 at: {base_url}")
    client = DHIS2Client(
        url=base_url,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        log_fn=ctx.log,
    )

    resolved_prog_uid = delivery_program
    try:
        progs = client.get("programs", {"fields": "id,name", "paging": "false"}).get("programs", [])
        for p in progs:
            if p["name"].strip().lower() == delivery_program.strip().lower() or p["id"] == delivery_program:
                resolved_prog_uid = p["id"]
                ctx.log(f"Resolved program '{p['name']}' -> UID: {resolved_prog_uid}")
                break
    except Exception as e:
        ctx.log(f"Note: program lookup check ({e})")

    ou_uid, ou_name = resolve_rmh_agg_ou(client, org_unit, resolved_prog_uid)
    ctx.log(f"Selected Org Unit: {ou_name} ({ou_uid})")

    ctx.log(f"Fetching tracker data for period: {period} ({start} to {end})...")
    df = fetch_rmh_tracker_df(
        client=client,
        program_uid=resolved_prog_uid,
        ou_uid=ou_uid,
        ou_mode=ou_mode,
        start=start,
        end=end,
    )
    ctx.log(f"Fetched {len(df):,} delivery records for aggregation")

    ctx.log("Computing MoH 01.2 indicators...")
    computed_values = compute_rmh_indicators(df)
    non_null_count = sum(1 for v in computed_values.values() if isinstance(v, (int, float)))
    not_avail_count = sum(1 for v in computed_values.values() if v == "Not available")
    ctx.log(f"Computed {non_null_count} indicators with valid values ({not_avail_count} marked Not available)")

    target_dir = resolve_output_dir(output_dir, settings.exports_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Preview Excel
    prev_name = preview_filename or f"rmh_{period}_preview.xlsx"
    prev_path = target_dir / prev_name
    write_rmh_preview_excel(computed_values, period, ou_name, str(prev_path))
    ctx.log(f"Saved indicator preview workbook: {prev_path.name}")

    # JSON summary
    summary_path = None
    if json_filename:
        summary_path = target_dir / json_filename
        summary_path.write_text(json.dumps(computed_values, indent=2), encoding="utf-8")

    # Export payload (dataValueSets)
    import_payload = None
    export_json_path = None
    if dataset or export_json_filename or submit:
        import_payload = build_rmh_import_json(
            computed_values,
            period=period,
            org_unit_uid=ou_uid,
            dataset_uid=dataset or "",
        )
        exp_name = export_json_filename or f"rmh_{period}_import.json"
        export_json_path = target_dir / exp_name
        export_json_path.write_text(json.dumps(import_payload, indent=2), encoding="utf-8")
        ctx.log(f"Built DHIS2 dataValueSets import payload: {export_json_path.name}")

    submit_response = None
    if submit and not dry_run:
        if not dataset:
            raise ValueError("Dataset UID is required to submit to DHIS2 aggregate.")
        ctx.log(f"Submitting {len(import_payload.get('dataValues', []))} dataValues to DHIS2 dataset {dataset}...")
        submit_response = client.post("dataValueSets", import_payload)
        ctx.log(f"DHIS2 Import Status: {submit_response.get('status')} - Imported: {submit_response.get('importCount')}")
    else:
        ctx.log("Dry-Run mode active: No aggregate records were written to DHIS2.")

    return {
        "status": "success",
        "period": period,
        "org_unit": ou_name,
        "org_unit_uid": ou_uid,
        "total_records": len(df),
        "computed_indicators_count": non_null_count,
        "values": computed_values,
        "preview_file": str(prev_path),
        "output_file": str(prev_path),
        "output_dir": str(target_dir),
        "filename": prev_path.name,
        "export_json_file": str(export_json_path) if export_json_path else None,
        "submit_response": submit_response,
    }


# ==============================================================================
# HM-05: NH NICU Register from CSV Worker
# ==============================================================================
def run_nh_neonatal_register_csv_worker(
    ctx: JobContext,
    input_file: str,
    output_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    region: Optional[str] = None,
    facility: Optional[str] = None,
    sheet_per_facility: bool = False,
) -> dict:
    ctx.log(f"Loading neonatal data CSV: {input_file}")
    df = load_nh_csv(input_file)
    ctx.log(f"Loaded {len(df):,} records from CSV")

    df = filter_nh_df(df, start=start, end=end, region=region, facility=facility)
    ctx.log(f"Records after date/facility filters: {len(df):,}")

    wb = Workbook()
    wb.remove(wb.active)
    all_tallies = []

    if sheet_per_facility:
        facilities = df[NH_RAW["facility"]].dropna().unique()
        ctx.log(f"Generating {len(facilities)} facility sheet(s)...")
        for fac in sorted(facilities):
            grp = df[df[NH_RAW["facility"]] == fac]
            reg_name = _safe_mode(grp[NH_RAW["region"]]) if NH_RAW["region"] in grp else ""
            d_from, d_to = _safe_date_range(grp[NH_RAW["enroll_date"]]) if NH_RAW["enroll_date"] in grp else ("—", "—")

            reg = build_nh_register(grp)
            sheet_name = str(fac)[:28].strip()
            ws = wb.create_sheet(title=sheet_name)
            write_nh_sheet(ws, reg, fac, reg_name, d_from, d_to)

            t = compute_nh_tally(reg)
            t["_facility"] = sheet_name
            all_tallies.append(t)
            ctx.log(f"  Processed {fac}: {len(reg)} admissions")
    else:
        fac_list = df[NH_RAW["facility"]].dropna().unique() if NH_RAW["facility"] in df else []
        fac_label = fac_list[0] if len(fac_list) == 1 else (facility or f"{len(fac_list)} Facilities")
        reg_name = region or (_safe_mode(df[NH_RAW["region"]]) if NH_RAW["region"] in df else "")
        d_from, d_to = _safe_date_range(df[NH_RAW["enroll_date"]]) if NH_RAW["enroll_date"] in df else ("—", "—")

        ctx.log(f"Building register for {len(df):,} admissions...")
        reg = build_nh_register(df)
        ws = wb.create_sheet(title="NICU Register")
        write_nh_sheet(ws, reg, fac_label, str(reg_name), d_from, d_to)

        t = compute_nh_tally(reg)
        t["_facility"] = fac_label
        all_tallies.append(t)

    # Tally summary
    ws_tally = wb.create_sheet(title="Tally Summary")
    write_nh_tally_sheet(ws_tally, all_tallies)

    target_dir = resolve_output_dir(output_dir, settings.exports_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = (output_filename or "nicu_register_csv.xlsx").strip()
    if not out_name.lower().endswith(".xlsx"):
        out_name = f"{out_name}.xlsx"
    out_path = target_dir / out_name
    wb.save(out_path)
    ctx.log(f"Successfully generated NICU Register workbook: {out_path.name}")

    combined_tallies = {}
    if all_tallies:
        combined_tallies = {
            k: sum(t.get(k, 0) for t in all_tallies if isinstance(t.get(k), (int, float)))
            for k in all_tallies[0]
            if not k.startswith("_")
        }

    return {
        "status": "success",
        "total_records": len(df),
        "output_file": str(out_path),
        "output_dir": str(target_dir),
        "filename": out_path.name,
        "tallies": combined_tallies,
    }


# ==============================================================================
# HM-06: NH NICU Register from Live DHIS2 Worker
# ==============================================================================
def run_nh_neonatal_register_dhis2_worker(
    ctx: JobContext,
    base_url: str,
    username: str,
    password: str,
    verify_ssl: bool = True,
    program_uid: str = "Neonatal Care Form",
    org_unit: Optional[str] = None,
    ou_mode: str = "DESCENDANTS",
    start: Optional[str] = None,
    end: Optional[str] = None,
    output_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
    sheet_per_facility: bool = False,
    page_size: int = 250,
) -> dict:
    ctx.log(f"Connecting to DHIS2 at: {base_url}")
    client = DHIS2Client(
        url=base_url,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        log_fn=ctx.log,
    )

    ctx.log(f"Resolving neonatal program for: {program_uid}")
    resolved_prog_uid = program_uid
    try:
        progs = client.get("programs", {"fields": "id,name", "paging": "false"}).get("programs", [])
        for p in progs:
            if p["name"].strip().lower() == program_uid.strip().lower() or p["id"] == program_uid:
                resolved_prog_uid = p["id"]
                ctx.log(f"Resolved program '{p['name']}' -> UID: {resolved_prog_uid}")
                break
    except Exception as e:
        ctx.log(f"Note: program lookup check ({e})")

    cache_file = settings.exports_dir / f"hmis_nh_meta_{resolved_prog_uid}.json"
    meta = NHMetadataResolver(client, resolved_prog_uid, cache_file=str(cache_file))
    meta.load()

    ou_uid = None
    ou_name = "All facilities"
    if org_unit:
        try:
            ou_uid, ou_name = resolve_nh_ou_uid(client, org_unit, resolved_prog_uid)
            ctx.log(f"Resolved org unit: {ou_name} ({ou_uid})")
        except Exception as err:
            ctx.log(f"Warning resolving org unit: {err}")
            if len(org_unit) == 11 and org_unit.isalnum():
                ou_uid = org_unit
            else:
                raise ValueError(f"Could not resolve organisation unit '{org_unit}' to a valid DHIS2 UID.")

    fetcher = NHTEIFetcher(client, meta)
    ctx.log(f"Fetching TEIs (ouMode={ou_mode})...")
    teis = fetcher.fetch(
        program_uid=resolved_prog_uid,
        ou_uid=ou_uid,
        ou_mode=ou_mode,
        start=start,
        end=end,
        page_size=page_size,
    )
    ctx.log(f"Fetched {len(teis):,} neonatal TEI records")

    df = fetcher.to_dataframe(teis)
    df = NHTEIFetcher.filter_by_admission_date(
        df, start, end,
        admit_col=NH_RAW.get("admit_date", "NICU Admission Careform_Date of Admission n")
    )
    ctx.log(f"Admissions in target date range: {len(df):,}")

    target_dir = resolve_output_dir(output_dir, settings.exports_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = (output_filename or "nicu_register_dhis2.xlsx").strip()
    if not out_name.lower().endswith(".xlsx"):
        out_name = f"{out_name}.xlsx"
    out_path = target_dir / out_name

    class DummyArgs:
        output = str(out_path)
        pass_sheet_per_facility = sheet_per_facility
        region = ""

    DummyArgs.sheet_per_facility = sheet_per_facility
    generate_nh_dhis2_excel(df, DummyArgs, meta, ou_name)
    ctx.log(f"Successfully generated NICU Register workbook: {out_path.name}")

    return {
        "status": "success",
        "total_records": len(df),
        "output_file": str(out_path),
        "output_dir": str(target_dir),
        "filename": out_path.name,
    }


# ==============================================================================
# HM-07: 04.2 NH Monthly Aggregate Report Worker
# ==============================================================================
def run_nh_aggregate_report_worker(
    ctx: JobContext,
    base_url: str,
    username: str,
    password: str,
    verify_ssl: bool = True,
    program_uid: str = "Neonatal Care Form",
    org_unit: Optional[str] = None,
    ou_mode: str = "SELECTED",
    period: str = "202610",
    start: Optional[str] = None,
    end: Optional[str] = None,
    dataset: Optional[str] = None,
    dry_run: bool = True,
    submit: bool = False,
    preview_filename: Optional[str] = None,
    json_filename: Optional[str] = None,
    export_json_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    ctx.log(f"Connecting to DHIS2 at: {base_url}")
    client = DHIS2Client(
        url=base_url,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        log_fn=ctx.log,
    )

    resolved_prog_uid = program_uid
    try:
        progs = client.get("programs", {"fields": "id,name", "paging": "false"}).get("programs", [])
        for p in progs:
            if p["name"].strip().lower() == program_uid.strip().lower() or p["id"] == program_uid:
                resolved_prog_uid = p["id"]
                ctx.log(f"Resolved program '{p['name']}' -> UID: {resolved_prog_uid}")
                break
    except Exception as e:
        ctx.log(f"Note: program lookup check ({e})")

    ou_uid, ou_name = resolve_nh_agg_ou(client, org_unit, resolved_prog_uid)
    ctx.log(f"Selected Org Unit: {ou_name} ({ou_uid})")

    ctx.log(f"Fetching tracker data for period: {period} ({start} to {end})...")
    df = fetch_nh_tracker_df(
        client=client,
        program_uid=resolved_prog_uid,
        ou_uid=ou_uid,
        ou_mode=ou_mode,
        start=start,
        end=end,
    )
    ctx.log(f"Fetched {len(df):,} neonatal records for aggregation")

    ctx.log("Computing MoH 04.2 indicators...")
    computed_values = compute_nh_indicators(df)
    non_null_count = sum(1 for v in computed_values.values() if isinstance(v, (int, float)))
    not_avail_count = sum(1 for v in computed_values.values() if v == "Not available")
    ctx.log(f"Computed {non_null_count} indicators with valid values ({not_avail_count} marked Not available)")

    target_dir = resolve_output_dir(output_dir, settings.exports_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Preview Excel
    prev_name = preview_filename or f"nh_{period}_preview.xlsx"
    prev_path = target_dir / prev_name
    write_nh_preview_excel(computed_values, period, ou_name, str(prev_path))
    ctx.log(f"Saved indicator preview workbook: {prev_path.name}")

    # JSON summary
    summary_path = None
    if json_filename:
        summary_path = target_dir / json_filename
        summary_path.write_text(json.dumps(computed_values, indent=2), encoding="utf-8")

    # Export payload (dataValueSets)
    import_payload = None
    export_json_path = None
    if dataset or export_json_filename or submit:
        import_payload = build_nh_import_json(
            computed_values,
            period=period,
            org_unit_uid=ou_uid,
            dataset_uid=dataset or "",
        )
        exp_name = export_json_filename or f"nh_{period}_import.json"
        export_json_path = target_dir / exp_name
        export_json_path.write_text(json.dumps(import_payload, indent=2), encoding="utf-8")
        ctx.log(f"Built DHIS2 dataValueSets import payload: {export_json_path.name}")

    submit_response = None
    if submit and not dry_run:
        if not dataset:
            raise ValueError("Dataset UID is required to submit to DHIS2 aggregate.")
        ctx.log(f"Submitting {len(import_payload.get('dataValues', []))} dataValues to DHIS2 dataset {dataset}...")
        submit_response = client.post("dataValueSets", import_payload)
        ctx.log(f"DHIS2 Import Status: {submit_response.get('status')} - Imported: {submit_response.get('importCount')}")
    else:
        ctx.log("Dry-Run mode active: No aggregate records were written to DHIS2.")

    return {
        "status": "success",
        "period": period,
        "org_unit": ou_name,
        "org_unit_uid": ou_uid,
        "total_records": len(df),
        "computed_indicators_count": non_null_count,
        "values": computed_values,
        "preview_file": str(prev_path),
        "output_file": str(prev_path),
        "output_dir": str(target_dir),
        "filename": prev_path.name,
        "export_json_file": str(export_json_path) if export_json_path else None,
        "submit_response": submit_response,
    }


# ==============================================================================
# HM-08: MOH Facility Aggregate Report Exporter Worker
# ==============================================================================
def run_moh_aggregate_worker(
    ctx: JobContext,
    base_url: str,
    username: str,
    password: str,
    data_element_uid: str,
    mapping_file: str,
    output_filename: Optional[str] = None,
    output_dir: Optional[str] = None,
    periods: Optional[List[str] | str] = None,
    year: Optional[int] = None,
    months: Optional[List[int]] = None,
) -> dict:
    ctx.log(f"Starting MOH Facility Aggregate Export to: {base_url}")
    ctx.update_progress(5, 100, "Initializing pipeline...")

    target_mapping = (mapping_file or "").strip() or "Maternal aggregate.xlsx"
    mapping_path = Path(target_mapping)
    if not mapping_path.is_file():
        candidates = [
            Path("/app") / target_mapping,
            Path("/app/backend/modules/hmis/templates") / target_mapping,
            settings.uploads_dir / target_mapping,
            Path(__file__).resolve().parent / "templates" / target_mapping,
            Path(__file__).resolve().parent / "templates" / "Maternal aggregate.xlsx",
            Path("/app/backend/modules/hmis/templates/Maternal aggregate.xlsx"),
            Path("/app/Maternal aggregate.xlsx"),
        ]
        found = False
        for c in candidates:
            if c.is_file():
                mapping_path = c
                found = True
                break
        if not found:
            raise FileNotFoundError(f"Mapping file not found: {target_mapping}")

    active_periods = periods
    if not active_periods and year:
        active_periods = generate_periods(year=year, months=months)
    elif not active_periods:
        active_periods = generate_periods()

    target_dir = resolve_output_dir(output_dir, settings.exports_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = output_filename or "N_NICU_admissions_imnid_only"
    pipeline = MohAggregatePipeline(
        base_url=base_url,
        username=username,
        password=password,
        data_element_uid=data_element_uid,
        mapping_file=str(mapping_path),
        output_dir=str(target_dir),
        periods=active_periods,
        output_name=out_name,
        log_fn=ctx.log,
        progress_fn=ctx.update_progress,
    )

    final_xlsx, final_csv = pipeline.run()

    xlsx_path = Path(final_xlsx)
    csv_path = Path(final_csv)
    ctx.artifacts["output_xlsx"] = xlsx_path.name
    ctx.artifacts["output_csv"] = csv_path.name
    ctx.set_result_file(xlsx_path.name)

    return {
        "status": "success",
        "output_xlsx": str(xlsx_path),
        "output_csv": str(csv_path),
        "filename": xlsx_path.name,
        "csv_filename": csv_path.name,
        "matched_facilities": len(pipeline.matched),
        "unmatched_facilities": len(pipeline.unmatched),
        "periods": pipeline.periods,
    }

