# pages/data_cleaning.py
import re
import pandas as pd
import numpy as np
from typing import Optional, Dict, List


# ==================
# Helpers & heuristics
# ==================

def _norm(s: str) -> str:
    """Normalize arbitrary text to snake_case ascii-like token."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(s)).strip("_")
    return s.lower()

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names to snake_case."""
    df = df.copy()
    df.columns = [_norm(c) for c in df.columns]
    return df

def _detect_column(df: pd.DataFrame, priority_exact: List[str], priority_contains: List[str]) -> Optional[str]:
    cols = list(df.columns)
    # exact hits first
    for cand in priority_exact:
        if cand in cols:
            return cand
    # contains hits
    for pat in priority_contains:
        for c in cols:
            if pat in c:
                return c
    return None

def _first_non_null(series: pd.Series):
    for v in series:
        if pd.notna(v) and v != "":
            return v
    return np.nan

def _best_date_col(df: pd.DataFrame) -> Optional[str]:
    """
    Try to pick a date-ish column for ordering repeated stage rows.
    """
    candidates = [c for c in df.columns if "date" in c]
    ordered_prefs = [
        "eventdate", "event_date", "completeddate", "completed_date",
        "enrollmentdate", "enrollment_date", "incidentdate", "incident_date",
        "lastupdated", "last_updated", "created"
    ]
    for c in ordered_prefs:
        if c in df.columns:
            return c
    return candidates[0] if candidates else None

def _stage_label_from_row(row: pd.Series, stage_col: Optional[str], stage_name_col: Optional[str]) -> str:
    """
    Prefer stage id, else stage name; fallback 'stage'.
    """
    if stage_col and pd.notna(row.get(stage_col, np.nan)):
        return str(row[stage_col])
    if stage_name_col and pd.notna(row.get(stage_name_col, np.nan)):
        return str(row[stage_name_col])
    # sometimes exports use 'programstagename' variations
    for alt in ["programstagename", "program_stage_name", "stage_name"]:
        if alt in row.index and pd.notna(row.get(alt, np.nan)):
            return str(row[alt])
    return "stage"

# ==============================
# Core: long → wide (one row/TEI)
# ==============================

def one_row_per_tei_wide_any(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert an event-level export (possibly many rows per TEI across program stages)
    into a single row per TEI (wide). Works for both maternal & newborn exports.

    - Detects TEI column heuristically (common ids: in_recid, mi_recid, trackedentityinstance, etc.)
    - Detects stage id/name columns if present.
    - For repeated TEI+stage, keeps the latest (by a detected date column) or last seen non-null.
    - Stage-specific columns are suffixed with '__{stage_label}' (normalized).
    """
    if df.empty:
        return df

    df = _normalize_columns(df)

    # TEI column detection (include your common keys)
    tei_col = _detect_column(
        df,
        priority_exact=[
            "in_recid", "mi_recid",              # newborn / maternal you use
            "trackedentityinstance", "tei",      # DHIS2 TEI id
            "recid", "case_id", "mother_id", "infant_id", "child_id"  # fallbacks
        ],
        priority_contains=["trackedentity", "tei", "recid", "beneficiary", "mother", "infant", "child", "patient"]
    )
    if not tei_col:
        # Heuristic: choose a column with many duplicates → likely an ID across many events
        try:
            dup_ratio = {
                c: ((len(df) / df[c].nunique(dropna=True)) if df[c].nunique(dropna=True) else 0)
                for c in df.columns
            }
            tei_col = max(dup_ratio, key=dup_ratio.get)
        except Exception:
            raise ValueError("Unable to detect TEI identifier column.")

    if tei_col not in df.columns:
        raise ValueError("Unable to detect TEI identifier column.")

    # If already one row per TEI, just return as-is
    try:
        if df[tei_col].nunique(dropna=True) == len(df):
            return df
    except Exception:
        pass

    # Stage columns (id and/or name)
    stage_col = _detect_column(
        df,
        priority_exact=["program_stage", "programstage", "stage_id", "stage"],
        priority_contains=["program_stage", "stage"]
    )
    stage_name_col = _detect_column(
        df,
        priority_exact=["program_stage_name", "stage_name", "programstagename"],
        priority_contains=["stage_name", "programstagename"]
    )

    # Columns we don't want to suffix (ids/meta)
    ignore_cols = set([
        tei_col,
        stage_col, stage_name_col,
        "event", "event_uid", "eventid", "event_id",
        "enrollment", "enrollment_id",
        "enrollmentdate", "enrollment_date",
        "incidentdate", "incident_date",
        "orgunit", "org_unit", "orgunitname", "org_unit_name",
        "program", "programname", "program_name",
        "lastupdated", "last_updated", "storedby", "created",
        "status", "completeddate", "completed_date",
        "geometry", "coordinate", "coords"
    ])
    ignore_cols = {c for c in ignore_cols if c in df.columns}

    date_col = _best_date_col(df)

    # Sort so for repeated stage rows we keep the latest (stable keeps last overwrite)
    if date_col and date_col in df.columns:
        df_sorted = df.sort_values(by=[tei_col, date_col], kind="stable")
    else:
        df_sorted = df.sort_values(by=[tei_col], kind="stable")

    out_rows: List[Dict] = []
    for tei, g in df_sorted.groupby(tei_col, sort=False):
        row_out: Dict = {tei_col: tei}
        # iterate in order; later rows overwrite earlier for same TEI
        for _, r in g.iterrows():
            stage_label = _stage_label_from_row(r, stage_col, stage_name_col)
            stage_label = _norm(stage_label) if stage_label else "stage"
            for c, v in r.items():
                if c in ignore_cols:
                    continue
                if pd.isna(v) or v == "":
                    continue
                col_name = f"{c}__{stage_label}"
                row_out[col_name] = v
        out_rows.append(row_out)

    wide = pd.DataFrame(out_rows)
    # Keep TEI column first
    other_cols = [c for c in wide.columns if c != tei_col]
    wide = wide[[tei_col] + other_cols]
    return wide

def transform_file_to_one_row_per_tei(input_csv: str, output_csv: str) -> str:
    """
    Read any DHIS2-like export, produce one row per TEI CSV.
    """
    # Read all as strings to preserve leading zeros / codes
    df = pd.read_csv(input_csv, dtype=str, keep_default_na=False, na_values=[])

    wide = one_row_per_tei_wide_any(df)
    wide.to_csv(output_csv, index=False, encoding='utf-8-sig')
    return output_csv

# Optional CLI
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="One row per TEI transformer (maternal/newborn)")
    parser.add_argument("--input_csv", required=True, help="Path to input CSV")
    parser.add_argument("--output_csv", required=True, help="Path to write transformed CSV")
    args = parser.parse_args()
    print(transform_file_to_one_row_per_tei(args.input_csv, args.output_csv))
