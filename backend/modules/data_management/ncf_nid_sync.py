#!/usr/bin/env python3
"""
NCF → NID DHIS2 Tracker Sync Script
=====================================
Syncs data from Neonatal Care Form (NCF) program to Newborn Inpatient Data (NID) program.

Transformation types handled:
  1. DIRECT   - Same DE or same UID, copy value as-is
  2. COMPUTED - Boolean/flag derived from presence/value of NCF field
  3. AGGREGATE_MAX  - Highest value across repeatable NCF stage events
  4. AGGREGATE_MIN  - Lowest value across repeatable NCF stage events
  5. AGGREGATE_COUNT - Count events where a field equals a given value
  6. REPEATABLE_SLOT - Pick Nth event's value for a numbered NID field
  7. MULTI_TEXT_TO_TRUE_ONLY - Split MULTI_TEXT options into TRUE_ONLY fields
  8. VALUE_MAP  - Recode option codes between programs
  9. TIME_KNOWN - If NCF time/value field has a value → NID "is known?" = true
 10. DIRECT_OR_DEFAULT - Copy value if present in NCF, else fallback to default option code
 11. TIME_KNOWN_ELSE_NO - Write Yes (1/true) if NCF field has value, else No (0/false)
 12. MULTI_SELECT_MAP - Map multi-select options in NCF to a single choice option code in NID (with fallback default)

Usage:
  python3 ncf_to_nid_sync.py --server https://your-dhis2.org \
      --username <DHIS2_USER> --password <DHIS2_PASS> \
      [--tei TEI_UID] [--ou ORG_UNIT_UID] [--dry-run] [--log sync.log]
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, date, timedelta, timezone
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth

# ─────────────────────────────────────────────────────────────────
# PROGRAM / STAGE IDENTIFIERS
# ─────────────────────────────────────────────────────────────────
NCF_PROGRAM = "QYJKpoUeg9F"
NID_PROGRAM  = "pLk3Ht2XMKl"
NID_TRACKED_ENTITY_TYPE = "HgEqoFjby5n"   # confirmed from metadata_V3.json

# NCF stage UIDs (some are repeatable)
NCF_STAGE = {
    "NICU_ADMISSION":   "mv8iC65nP21",   # not repeatable
    "INVESTIGATION":    "YHiV8FUkx6I",   # repeatable
    "MEDICATION_INTV":  "YUfRatwZpLn",   # repeatable  (includes Oxygen Therapy)
    "PROGRESS_CARE":    "C5gxE7xp4tt",   # repeatable
    "PROGRESS_REF":     "kS1LZjC3hzj",   # repeatable  (Referral Hospital Progress)
    "NURSE_FOLLOWUP":   "eCyte3bTjHS",   # repeatable
    "KMC_FOLLOWUP":     "TI40LMTou2L",   # repeatable
    "CPAP_FOLLOWUP":    "MfVJ2ne5xrf",   # repeatable
    "REFERRAL_FORM":    "vir7ed0Qkyc",   # not repeatable
    "DISCHARGE_CARE":   "CbH1hYxJdL7",   # not repeatable
}

# NID stage UIDs (none repeatable)
NID_STAGE = {
    "ADMISSION":        "l39SlVGlQGs",
    "MATERNAL":         "UK7jsDbVpj6",
    "OBS_NURSING_1":    "j0HI2eJjvbj",
    "MICROBIOLOGY":     "aCrttmnx7FI",
    "INTERVENTIONS":    "ed8ErpgTCwx",
    "OBS_NURSING_2":    "VsVlpG1V2ub",
    "DISCHARGE":        "TOicTEwzSGj",
}

# Primary NCF source stage for status propagation to each NID stage
NID_TO_NCF_PRIMARY = {
    "ADMISSION":    "NICU_ADMISSION",
    "MATERNAL":     "NICU_ADMISSION",
    "OBS_NURSING_1":"NICU_ADMISSION",
    "MICROBIOLOGY": "INVESTIGATION",
    "INTERVENTIONS":"MEDICATION_INTV",
    "OBS_NURSING_2":"NURSE_FOLLOWUP",
    "DISCHARGE":    "DISCHARGE_CARE",
}

# ─────────────────────────────────────────────────────────────────
# MAPPING TABLE
# Each entry: (nid_stage_key, nid_de_uid, transformation, *params)
#
# transformation types:
#   DIRECT         ncf_stage_key, ncf_de_uid
#   TIME_KNOWN     ncf_stage_key, ncf_de_uid               → "true"/"" based on presence
#   MOTHER_ALIVE   ncf_stage_key, ncf_de_uid, ncf_val_alive, nid_val_yes, nid_val_no
#   VALUE_MAP      ncf_stage_key, ncf_de_uid, {ncf_code: nid_code}
#   MULTI_TO_TRUE  ncf_stage_key, ncf_de_uid, option_code  → TRUE_ONLY
#   AGGREGATE_MAX  ncf_stage_key, ncf_de_uid               → highest numeric value across events
#   AGGREGATE_MIN  ncf_stage_key, ncf_de_uid               → lowest numeric value across events
#   AGGREGATE_MAX_DATE ncf_stage_key, value_de, date_de    → date of event with max value
#   AGGREGATE_MIN_DATE ncf_stage_key, value_de, date_de    → date of event with min value
#   COUNT_YES      ncf_stage_key, ncf_de_uid, match_value  → count events where de == match_value
#   COUNT_YES_CODED  same as COUNT_YES but writes a 1=Once/2=Twice/3=Three/
#                    4=More-than-three code instead of the raw integer
#   REPEATABLE_SLOT ncf_stage_key, ncf_de_uid, slot_index  → value from Nth event (0-based)
#   COMPUTED_PHONE ncf_stage_key, p1_de, p2_de             → 1/2/0 based on which are filled
#   CONSTANT       fixed_value                              → always write this literal value
#                                                              (no NCF source field; used for
#                                                              NID-only fields like the
#                                                              Baseline/Final and
#                                                              Retrospective/Prospective flags)
#   DIRECT_OR_DEFAULT ncf_stage_key, ncf_de_uid, default_val → copy value if present, else default_val
# ─────────────────────────────────────────────────────────────────

MAPPING = [
    # ── Tracked Entity Attributes (copied directly as TEA, not event data) ──
    # These are handled separately via TEI attribute update

    # ════════════════════════════════════════════════════════════════
    # ADMISSION INFORMATION stage
    # ════════════════════════════════════════════════════════════════
    # Direct copies (same UID both sides or direct match)
    ("ADMISSION", "LDkzwSrFMXj",  "DIRECT", "NICU_ADMISSION", "E4G1xedugN5"),   # Woredas
    ("ADMISSION", "qvkfBYluoHR",  "DIRECT", "NICU_ADMISSION", "JatpcsSbqBR"),   # Zone
    ("ADMISSION", "cJ0xK7PYHwq",  "DIRECT", "NICU_ADMISSION", "cJ0xK7PYHwq"),   # Phone 2
    ("ADMISSION", "XphSaUum2pM",  "DIRECT", "NICU_ADMISSION", "iODyc8Ud9oa"),   # Phone 1
    ("ADMISSION", "LQi1M0Nvpzo",  "DIRECT", "NICU_ADMISSION", "r6j58mnPS2h"),   # Readmission
    ("ADMISSION", "Mg9CYZFWu7O",  "DIRECT", "NICU_ADMISSION", "Mg9CYZFWu7O"),   # Last Name Mother
    ("ADMISSION", "ffEgqZe54Hw",  "DIRECT", "NICU_ADMISSION", "pMrRODYCfQu"),   # First Name Mother
    ("ADMISSION", "XwBOaM9MNlo",  "DIRECT", "NICU_ADMISSION", "XwBOaM9MNlo"),   # Registration Number
    ("ADMISSION", "QpCEsINDxGY",  "DIRECT", "NICU_ADMISSION", "QpCEsINDxGY"),   # Baby Hospital ID Number
    ("ADMISSION", "aXWAhs2owzv",  "DIRECT", "NICU_ADMISSION", "QpCEsINDxGY"),   # BHID (Baby Hospital ID) — same NCF source as in_byid
    ("ADMISSION", "p2GxXHvzlnC",  "DIRECT", "NICU_ADMISSION", "oN2duJU7M53"),   # Time of Birth
    ("ADMISSION", "UOmhJkyAK6h",  "DIRECT", "NICU_ADMISSION", "PadsjZCM10U"),   # Date of Admission
    ("ADMISSION", "K5hp1PVB5l4",  "DIRECT", "NICU_ADMISSION", "M9hU9r5Wbai"),   # Time of Admission
    ("ADMISSION", "uqoIf4Pkdpt",  "DIRECT", "NICU_ADMISSION", "uqoIf4Pkdpt"),   # If outborn - where
    ("ADMISSION", "ytlymBoW931",  "DIRECT", "REFERRAL_FORM",  "Dul0W1mNL2o"),   # Referring facility name
    ("ADMISSION", "yxWUMt3sCil",  "DIRECT", "NICU_ADMISSION", "qxnUrl2kb9J"),   # Weight on admission
    ("ADMISSION", "T30GbTiVgFR",  "DIRECT_OR_DEFAULT", "NICU_ADMISSION", "iuIn2zpSUR6", "17"),   # 1st Reason Admission
    ("ADMISSION", "ahDSM6WuoRU",  "DIRECT",            "NICU_ADMISSION", "ahDSM6WuoRU"),   # If other specify (First)
    ("ADMISSION", "OpHw2X58x5i",  "DIRECT_OR_DEFAULT", "NICU_ADMISSION", "lfqijX4DNqR", "17"),   # 2nd Reason Admission
    ("ADMISSION", "F5kSiYBc5X2",  "DIRECT",            "NICU_ADMISSION", "F5kSiYBc5X2"),   # If other specify (Second)
    ("ADMISSION", "gJH6PkYI6IV",  "DIRECT_OR_DEFAULT", "NICU_ADMISSION", "cX0JPpXiZSO", "17"),   # 3rd Reason Admission
    ("ADMISSION", "ZWwpbEsezE9",  "DIRECT",            "NICU_ADMISSION", "ZWwpbEsezE9"),   # If other specify (Third)

    # TIME_KNOWN: if NCF has a time value → NID boolean = true
    ("ADMISSION", "xFosIUSTXYR",  "TIME_KNOWN", "NICU_ADMISSION", "oN2duJU7M53"),  # Is time of birth recorded?
    ("ADMISSION", "UamL5CdWhV6",  "TIME_KNOWN", "NICU_ADMISSION", "M9hU9r5Wbai"),  # Is time of admission recorded?
    ("ADMISSION", "dDoewefeO81",  "TIME_KNOWN", "NICU_ADMISSION", "qxnUrl2kb9J"),  # Is weight on admission documented?

    # Birth location: NCF uses text (1:Inborn;2:Outborn), NID uses coded integer
    ("ADMISSION", "aK5txmRYpVX",  "DIRECT", "NICU_ADMISSION", "MtIwjNsCLYy"),   # Birth Location

    # Phone count: computed from presence of phone fields
    ("ADMISSION", "bQzDp0fVVuF",  "COMPUTED_PHONE", "NICU_ADMISSION", "iODyc8Ud9oa", "cJ0xK7PYHwq"),

    # Baby Hospital ID choice: from MULTI_TEXT p3yshaSikf7 option 1 → TRUE_ONLY bygfdQV06iP
    ("ADMISSION", "bygfdQV06iP",  "MULTI_TO_TRUE", "NICU_ADMISSION", "p3yshaSikf7", "1"),
    ("ADMISSION", "zJ5Se1BXd2K",  "MULTI_TO_TRUE", "NICU_ADMISSION", "p3yshaSikf7", "2"),

    # NID-only fields with no NCF source — every synced record is, by
    # definition, drawn live from the NCF care form, so these are always
    # fixed to FINAL (not Baseline) and PROSPECTIVE (not Retrospective).
    # Confirmed against NID_DD_Jun_28.xlsx option sets:
    #   a4KMy3G3Rwc "BASELINE or FINAL dataset record?"        1=Baseline, 2=Final
    #   qgeLeV87duh "RETROSPECTIVE or PROSPECTIVE record?"     1=Retrospective, 2=Prospective
    ("ADMISSION", "a4KMy3G3Rwc",  "CONSTANT", None, None, "2"),   # Always FINAL
    ("ADMISSION", "qgeLeV87duh",  "CONSTANT", None, None, "2"),   # Always PROSPECTIVE

    # Form entry dates: Date/Time of DHIS2 Form Entry come from the
    # DATE+time portion of the NCF Discharge care form's combined
    # "Date and time of discharge" (VNV2QYQpebO). Date of Paper Form
    # Data Collection is a fixed sentinel date (1999-01-01) — no real
    # paper form is used, so every synced record gets this constant.
    ("ADMISSION", "UFaCpvno9fb",  "DATETIME_SPLIT", "DISCHARGE_CARE", "VNV2QYQpebO", "date"),  # Date of DHIS2 Form Entry
    ("ADMISSION", "lUCBSQsk9oD",  "DATETIME_SPLIT", "DISCHARGE_CARE", "VNV2QYQpebO", "time"),  # Time of DHIS2 Form Entry
    ("ADMISSION", "kzKP9fBVz0U",  "CONSTANT",       None,            None,            "1999-01-01"),  # Date of Paper Form Data Collection

    # ════════════════════════════════════════════════════════════════
    # MATERNAL BIRTH AND INFANT DETAILS stage
    # ════════════════════════════════════════════════════════════════
    ("MATERNAL", "y6NzGv7uAJB",  "DIRECT", "NICU_ADMISSION", "y6NzGv7uAJB"),   # Day of Maternal DOB
    ("MATERNAL", "rp4UbFhExW4",  "DIRECT", "NICU_ADMISSION", "rp4UbFhExW4"),   # Month of Maternal DOB
    ("MATERNAL", "swiUrmwIlu5",  "DIRECT", "NICU_ADMISSION", "swiUrmwIlu5"),   # Year of Maternal DOB
    ("MATERNAL", "TdD5Sk7leqZ",  "DIRECT", "NICU_ADMISSION", "raJhng7bnxV"),   # Maternal Age
    ("MATERNAL", "wtlnVVhfPRZ",  "TIME_KNOWN_ELSE_NO", "NICU_ADMISSION", "raJhng7bnxV"),  # Is maternal age documented?
    ("MATERNAL", "f0507SQiv3z",  "DIRECT", "NICU_ADMISSION", "g3NaBFy0tQT"),   # Singleton delivery?
    ("MATERNAL", "uS9ivgAoAEf",  "DIRECT", "NICU_ADMISSION", "uS9ivgAoAEf"),   # Multiple Births
    ("MATERNAL", "oHIgtGycO0F",  "DIRECT", "NICU_ADMISSION", "oHIgtGycO0F"),   # Order this newborn delivered
    # NB: the per-multiplicity order fields (Twin/Triplet/Quad/Quint) are
    # handled by sync_birth_order — written only to the field matching the
    # actual Multiple Births multiplicity, never blindly to all of them.
    ("MATERNAL", "oCVsXvO6lNl",  "DIRECT", "NICU_ADMISSION", "awLCEuXlXXh"),   # Mode of delivery
    ("MATERNAL", "CoaHboBm1bj",  "DIRECT", "NICU_ADMISSION", "ChqcIjb8y3o"),   # Antenatal Corticosteroids

    # Mother HIV: NCF codes 1=Negative,2=Positive,3=Unknown; NID 0=Negative,-2=Unknown,1=Positive
    ("MATERNAL", "CCcgTQiDl3Q",  "VALUE_MAP", "NICU_ADMISSION", "a3m48HYakSA",
     {"1": "0", "2": "1", "3": "-2"}),

    ("MATERNAL", "fiulNOdrXlk",  "DIRECT", "NICU_ADMISSION", "fiulNOdrXlk"),   # HIV Treatment Mother
    ("MATERNAL", "fYUmasOFGBR",  "DIRECT", "NICU_ADMISSION", "fYUmasOFGBR"),   # HIV Treatment Baby
    ("MATERNAL", "CMtOgb5koHa",  "DIRECT", "NICU_ADMISSION", "NoTohvy21XU"),   # Type of Diabetes
    ("MATERNAL", "RDlYt9U7YqM",  "DIRECT", "NICU_ADMISSION", "wPbQVmmpqtp"),   # Pre-existing Diabetes type
    ("MATERNAL", "HTzD9ZNx51h",  "DIRECT", "NICU_ADMISSION", "XFHTPjMHFHW"),   # Type of Hypertension
    ("MATERNAL", "SX0vx7yXhna",  "DIRECT", "NICU_ADMISSION", "SX0vx7yXhna"),   # If other specify
    ("MATERNAL", "usbIOqcqyGT",  "TIME_KNOWN", "NICU_ADMISSION", "ZiI6RUqXLUl"),  # Is birth weight documented?
    ("MATERNAL", "CzIgD0rsk52",  "DIRECT", "NICU_ADMISSION", "ZiI6RUqXLUl"),   # Birth weight
    ("MATERNAL", "HYvOD03vhOH",  "VALUE_MAP", "NICU_ADMISSION", "rH78R1ZnGgh",
     {"1": "7", "2": "2", "3": "8", "4": "3", "5": "9", "6": "4"}),  # Gestational age documented
    ("MATERNAL", "dVXKpOrj92l",  "DIRECT", "NICU_ADMISSION", "Pq1SDuw0hmo"),   # GA format
    ("MATERNAL", "r5JV9avYdmB",  "DIRECT", "NICU_ADMISSION", "r5JV9avYdmB"),   # Months
    ("MATERNAL", "c3QaY9N6Ll7",  "DIRECT", "NICU_ADMISSION", "c3QaY9N6Ll7"),   # Weeks
    ("MATERNAL", "tsM5JUrghn3",  "DIRECT", "NICU_ADMISSION", "tsM5JUrghn3"),   # Days
    ("MATERNAL", "VA598XGBBTl",  "DIRECT", "NICU_ADMISSION", "VA598XGBBTl"),   # Is the method used to calculate gestational age known? (direct copy)
    ("MATERNAL", "G4TpuEa5Srg",  "VALUE_MAP", "NICU_ADMISSION", "Kqz5fsjcfUS",
     {"1": "3",  # Early ultrasound
      "2": "4",  # Late ultrasound
      "3": "5",  # Postnatal clinical gestational assessment
      "4": "2",  # Fundal height
      "5": "1"}),  # LMP
    ("MATERNAL", "bIWXcTGBLEB",  "DIRECT", "NICU_ADMISSION", "SLUdglg8rAv"),   # Postnatal GA method
    ("MATERNAL", "WAecEfcBvhu",  "DIRECT_OR_DEFAULT", "NICU_ADMISSION", "t8mHfBu4KtV", "-1"),  # Maternal DOB info available
    ("MATERNAL", "ZqiiqkkgvJo",  "DIRECT", "NICU_ADMISSION", "SX0vx7yXhna"),   # If other method

    # Mother alive: NCF 1=Alive,2=Dead → NID 1=Yes,0=No
    ("MATERNAL", "nwUBCXzA7ER",  "VALUE_MAP", "NICU_ADMISSION", "IN4QSEinKma",
     {"1": "1", "2": "0"}),

    # Maternal chronic conditions: NCF MULTI_TEXT → NID TRUE_ONLY per option
    ("MATERNAL", "it3VlxNkWpl",  "MULTI_TO_TRUE", "NICU_ADMISSION", "iLqOrNFXxpe", "1"),  # Diabetes
    ("MATERNAL", "mL7J4TjJCBc",  "MULTI_TO_TRUE", "NICU_ADMISSION", "iLqOrNFXxpe", "2"),  # Hypertension
    ("MATERNAL", "axt5HZFU4FY",  "MULTI_TO_TRUE", "NICU_ADMISSION", "iLqOrNFXxpe", "99"), # Other
    ("MATERNAL", "uxfP04Pc2ya",  "MULTI_TO_TRUE", "NICU_ADMISSION", "iLqOrNFXxpe", "4"),  # None

    # ════════════════════════════════════════════════════════════════
    # OBSERVATIONS AND NURSING CARE 1 stage
    # ════════════════════════════════════════════════════════════════
    ("OBS_NURSING_1", "fD8iWvR7H4R", "TIME_KNOWN",  "NICU_ADMISSION", "RE3wIu5acNt"),   # Was temp recorded?
    ("OBS_NURSING_1", "pIrvv1ToXDV", "DIRECT",      "NICU_ADMISSION", "uRDOCbWbYiE"),   # Temp unit
    ("OBS_NURSING_1", "gZi9y12E9i7", "DIRECT",      "NICU_ADMISSION", "RE3wIu5acNt"),   # Temp on admission °C
    ("OBS_NURSING_1", "O0IEGF2m5UO", "DIRECT",      "NICU_ADMISSION", "O0IEGF2m5UO"),   # Temp on admission °F
    ("OBS_NURSING_1", "kvJUcoHhx7f", "TIME_KNOWN",  "NICU_ADMISSION", "aq7O6Yc09Mq"),   # SpO2 recorded?
    ("OBS_NURSING_1", "xnU9AiiCD9v", "DIRECT",      "NICU_ADMISSION", "aq7O6Yc09Mq"),   # SpO2 on admission
    ("OBS_NURSING_1", "zNgIWKJx15W", "DIRECT",      "NICU_ADMISSION", "O15NBw7eY59"),   # O2 at SpO2 meas.
    ("OBS_NURSING_1", "eyLCAlgGdtN", "DIRECT",      "NICU_ADMISSION", "AGYbHjJgBqq"),   # Severe resp distress
    ("OBS_NURSING_1", "b2mZBOIwpsa", "DIRECT",      "NICU_ADMISSION", "NK7eDXVZGar"),   # Cord Chlorhexidine
    ("OBS_NURSING_1", "x8eUx0RUjnd", "DIRECT",      "NICU_ADMISSION", "YqetSlg7mFF"),   # Vitamin K given
    ("OBS_NURSING_1", "tX82J8ZIcNr", "DIRECT",      "NICU_ADMISSION", "oxCQLegWJ9n"),   # Blood sugar recorded?
    ("OBS_NURSING_1", "mCKT9Cb00FY", "DIRECT",      "NICU_ADMISSION", "dAxrferxaLu"),   # Blood sugar unit
    ("OBS_NURSING_1", "F4NIANzeaTe", "DIRECT",      "NURSE_FOLLOWUP", "gwgZR3r9ZGw"),   # Blood sugar mmol/L
    ("OBS_NURSING_1", "zYFS8Cc5vqp", "DIRECT",      "NICU_ADMISSION", "zYFS8Cc5vqp"),   # Blood sugar mg/dL
    ("OBS_NURSING_1", "dDI7rgJ3bAL", "MULTI_SELECT_MAP", "NICU_ADMISSION", "EBCzcrrTWXN",
     {"5": "1", "4": "2"}, "-1"),  # Was baby skin-to-skin or wraps used AT Admission: 5=STS->1=Skin-to-skin, 4=Plastic wrap->2=Wraps, else -1=Not recorded

    # Temperature: highest across all Nurse followup sheet events
    # NID also asks: highest temp, its date, its unit
    # These are handled in the AGGREGATE section below

    # ════════════════════════════════════════════════════════════════
    # MICROBIOLOGY AND LABS stage  (direct 1:1 where UIDs match)
    # ════════════════════════════════════════════════════════════════
    ("MICROBIOLOGY", "A94ibeuO9GL", "DIRECT", "INVESTIGATION", "GwrkagnbTet"),
    ("MICROBIOLOGY", "i88MgSvgqnM", "DIRECT", "INVESTIGATION", "QMIH3k98zYO"),
    ("MICROBIOLOGY", "Dows1WAk2ur", "TIME_KNOWN", "INVESTIGATION", "zpID5J1LqBk"),
    ("MICROBIOLOGY", "zpID5J1LqBk", "DIRECT", "INVESTIGATION", "zpID5J1LqBk"),
    ("MICROBIOLOGY", "J5iofE2P6EG", "DIRECT", "INVESTIGATION", "wCWXXf0cuUV"),
    ("MICROBIOLOGY", "AZhFeCs5ZUq", "TIME_KNOWN", "INVESTIGATION", "jvWyGXBXJqy"),
    ("MICROBIOLOGY", "KXiepUvdyLO", "DIRECT", "INVESTIGATION", "jvWyGXBXJqy"),
    ("MICROBIOLOGY", "j21h93s37ZN", "DIRECT", "INVESTIGATION", "aCHOclZEx6o"),
    ("MICROBIOLOGY", "HvJ8H9tun4u", "DIRECT", "INVESTIGATION", "HvJ8H9tun4u"),
    ("MICROBIOLOGY", "FF6x7f3oOh3", "DIRECT", "INVESTIGATION", "FF6x7f3oOh3"),
    ("MICROBIOLOGY", "MkM6d6LucW6", "DIRECT", "INVESTIGATION", "p2vmKEiFJEH"),
    ("MICROBIOLOGY", "a7CvTNYyLyL", "DIRECT", "INVESTIGATION", "xiuakJzGNNG"),
    ("MICROBIOLOGY", "uYUebvL7uMz", "DIRECT", "INVESTIGATION", "XQ4jrGAY3bz"),
    ("MICROBIOLOGY", "rZmrLBvHGRi", "TIME_KNOWN", "INVESTIGATION", "hBG7IXOPAXK"),
    ("MICROBIOLOGY", "hBG7IXOPAXK", "DIRECT", "INVESTIGATION", "hBG7IXOPAXK"),
    ("MICROBIOLOGY", "Ji58qFiW33J", "DIRECT", "INVESTIGATION", "xjDgoSDJVF4"),
    ("MICROBIOLOGY", "Uq8uLVHNuyZ", "TIME_KNOWN", "INVESTIGATION", "heAZTBqqvHe"),
    ("MICROBIOLOGY", "DUYonVOd8Hg", "DIRECT", "INVESTIGATION", "heAZTBqqvHe"),
    ("MICROBIOLOGY", "HFqEqonC3vl", "DIRECT", "INVESTIGATION", "DDZkLCIxFK4"),
    ("MICROBIOLOGY", "N523RTo5Dpv", "DIRECT", "INVESTIGATION", "N523RTo5Dpv"),
    ("MICROBIOLOGY", "gAZxt7VhLl4", "DIRECT", "INVESTIGATION", "gAZxt7VhLl4"),
    ("MICROBIOLOGY", "bDPj9rDrklE", "DIRECT", "INVESTIGATION", "biUr77pnCJY"),
    # AST sensitivity panels (abbreviated - add remaining as needed)
    ("MICROBIOLOGY", "M8N5l9xh97p", "DIRECT", "INVESTIGATION", "uQ3E1Y68PBg"),  # Benzathine Pen
    ("MICROBIOLOGY", "MzQJqXyo9s6", "DIRECT", "INVESTIGATION", "ToaMIVl8fND"),  # Crystalline Pen
    ("MICROBIOLOGY", "W2ydMSClwA9", "DIRECT", "INVESTIGATION", "FgNRfZhUuU4"),  # Gentamicin
    ("MICROBIOLOGY", "kyhvbfgKiRf", "DIRECT", "INVESTIGATION", "GMhNUaMsACp"),  # Amikacin
    ("MICROBIOLOGY", "kNPl302EsGH", "DIRECT", "INVESTIGATION", "KoCCnlzXSFD"),  # Ceftriaxone
    ("MICROBIOLOGY", "tSnxyPX23n5", "DIRECT", "INVESTIGATION", "N20IqF3cOOO"),  # Ceftazidime
    ("MICROBIOLOGY", "QQuMZfAPbR2", "DIRECT", "INVESTIGATION", "SAEpregNRn1"),  # Cefotaxime
    ("MICROBIOLOGY", "GShWQwJCFKY", "DIRECT", "INVESTIGATION", "NWKDccZ870v"),  # Piperazine
    ("MICROBIOLOGY", "rjFedxHGbA2", "DIRECT", "INVESTIGATION", "rsal6QYeJ6D"),  # Metronidazole
    ("MICROBIOLOGY", "JF3yK7Zx55a", "DIRECT", "INVESTIGATION", "qBREICcaKtq"),  # Vancomycin
    ("MICROBIOLOGY", "rph7F2M757A", "DIRECT", "INVESTIGATION", "C5mi080ZIVv"),  # Clindamycin
    ("MICROBIOLOGY", "Lb02d9qnaZF", "DIRECT", "INVESTIGATION", "BMYkJ6TNiWl"),  # Ampicillin
    ("MICROBIOLOGY", "jH85onRvOl1", "DIRECT", "INVESTIGATION", "evH4fG3eNrC"),  # Amoxycillin
    ("MICROBIOLOGY", "EIMGNH8irlj", "DIRECT", "INVESTIGATION", "Ut00fUxOEP5"), # Flucloxacillin
    ("MICROBIOLOGY", "A4cMT8V1Yyd", "DIRECT", "INVESTIGATION", "ehW1T2ig6i9"),  # Meropenem
    ("MICROBIOLOGY", "ysPJwQU2qVO", "DIRECT", "INVESTIGATION", "OMW1D2gCx5k"),  # Levofloxacin

    # Microbiology & Labs: Multiple microorganisms (Blood & CSF)
    ("MICROBIOLOGY", "QcdCtWIFg5m", "DIRECT", "INVESTIGATION", "ZjUDWGM0SuH"),  # Were multiple microorganisms cultured from same blood culture?
    ("MICROBIOLOGY", "pwvxOagwPdD", "DIRECT", "INVESTIGATION", "pwvxOagwPdD"),  # If yes - please specify full name other isolated microorg (Blood)
    ("MICROBIOLOGY", "OgCoW3u4sRJ", "DIRECT", "INVESTIGATION", "dw4z9SgVqVh"),  # Were multiple microorganisms cultured from same CSF culture?
    ("MICROBIOLOGY", "n9ZHM3ys5qV", "DIRECT", "INVESTIGATION", "n9ZHM3ys5qV"),  # If yes - please specify full name other isolated microorg (CSF)

    # Microbiology & Labs: Other (1-5) Blood antibiotic susceptibilities & names
    ("MICROBIOLOGY", "hoLTaL2Jq68", "DIRECT", "INVESTIGATION", "VpAMxngdRgn"),  # Other (1) Blood
    ("MICROBIOLOGY", "pn9DNtrxhkp", "DIRECT", "INVESTIGATION", "pn9DNtrxhkp"),  # Name of Antibiotic - Other (1)
    ("MICROBIOLOGY", "jCLYMMPlhf4", "DIRECT", "INVESTIGATION", "uHs1haujzvj"),  # Other (2) Blood
    ("MICROBIOLOGY", "jE0qQTr1TYI", "DIRECT", "INVESTIGATION", "jE0qQTr1TYI"),  # Name of Antibiotic - Other (2)
    ("MICROBIOLOGY", "e2dxgvC6AOI", "DIRECT", "INVESTIGATION", "y0MXuZzxbJE"),  # Other (3) Blood
    ("MICROBIOLOGY", "BkWDkcuVviG", "DIRECT", "INVESTIGATION", "BkWDkcuVviG"),  # Name of Antibiotic - Other (3)
    ("MICROBIOLOGY", "uLFhM9HFqYk", "DIRECT", "INVESTIGATION", "MlOQRiiqGlH"),  # Other (4) Blood
    ("MICROBIOLOGY", "QznMWcaiJUw", "DIRECT", "INVESTIGATION", "QznMWcaiJUw"),  # Name of Antibiotic - Other (4)
    ("MICROBIOLOGY", "PdHeLIkjBOu", "DIRECT", "INVESTIGATION", "QKNXGz1BouP"),  # Other (5) Blood
    ("MICROBIOLOGY", "U3EAigdeLzU", "DIRECT", "INVESTIGATION", "U3EAigdeLzU"),  # Name of Antibiotic - Other (5)

    # Microbiology & Labs: CSF antibiotic susceptibility panel
    ("MICROBIOLOGY", "DYCrPiJLPyt", "DIRECT", "INVESTIGATION", "sYI3IkO7RO7"),  # Benzathine Penicillin CSF
    ("MICROBIOLOGY", "qMPzDPeeqEY", "DIRECT", "INVESTIGATION", "HJSeHerTsS6"),  # Crystalline Penicillin CSF
    ("MICROBIOLOGY", "dhP9lksvu2B", "DIRECT", "INVESTIGATION", "aH6wGvCPUVt"),  # Gentamicin CSF
    ("MICROBIOLOGY", "eYq9kpmK0Hi", "DIRECT", "INVESTIGATION", "fYHguSzedom"),  # Amikacin CSF
    ("MICROBIOLOGY", "lgpbAxWzUJ3", "DIRECT", "INVESTIGATION", "WJwOsnXPmZL"),  # Ceftriaxone CSF
    ("MICROBIOLOGY", "Xd9SWWzgk5d", "DIRECT", "INVESTIGATION", "VZpTsB455jA"),  # Ceftazidime CSF
    ("MICROBIOLOGY", "A0QxW1yllec", "DIRECT", "INVESTIGATION", "SmHsvwqRhau"),  # Cefotaxime CSF
    ("MICROBIOLOGY", "zawZAsLOdFP", "DIRECT", "INVESTIGATION", "Ms1S3mylD1J"),  # Piperazine CSF
    ("MICROBIOLOGY", "cJ1xCPfvYXQ", "DIRECT", "INVESTIGATION", "oRLT8GHNiF4"),  # Metronidazole CSF
    ("MICROBIOLOGY", "LwlKPagezbl", "DIRECT", "INVESTIGATION", "EMgp4iOdpTl"),  # Vancomycin CSF
    ("MICROBIOLOGY", "ni152mGAbv9", "DIRECT", "INVESTIGATION", "vvHj3bCo4DK"),  # Clindamycin CSF
    ("MICROBIOLOGY", "YJXa6kO1bxi", "DIRECT", "INVESTIGATION", "zatOVYpwYBP"),  # Ampicillin CSF
    ("MICROBIOLOGY", "aqIPEXFUxH5", "DIRECT", "INVESTIGATION", "wiGAaxjk2f6"),  # Amoxycillin CSF
    ("MICROBIOLOGY", "uaOhW4HOlvt", "DIRECT", "INVESTIGATION", "IxYNdQDSZc5"),  # Flucloxacillin CSF
    ("MICROBIOLOGY", "thFoJeB96YM", "DIRECT", "INVESTIGATION", "sDDK9dx4Zts"),  # Meropenem CSF
    ("MICROBIOLOGY", "KXy10wDLGqx", "DIRECT", "INVESTIGATION", "fW2YndgNDjm"),  # Levofloxacin CSF

    # Microbiology & Labs: Other (1-5) CSF antibiotic susceptibilities & names
    ("MICROBIOLOGY", "ppa7UxWscHj", "DIRECT", "INVESTIGATION", "BrPAEiSM65a"),  # Other (1) CSF
    ("MICROBIOLOGY", "wFT8aKC8Yg2", "DIRECT", "INVESTIGATION", "wFT8aKC8Yg2"),  # Name of Antibiotic - Other (1) CSF
    ("MICROBIOLOGY", "izY7jIoQpn2", "DIRECT", "INVESTIGATION", "zV6hrZ4BmEE"),  # Other (2) CSF
    ("MICROBIOLOGY", "SkFHm9Mxel1", "DIRECT", "INVESTIGATION", "SkFHm9Mxel1"),  # Name of Antibiotic - Other (2) CSF
    ("MICROBIOLOGY", "uNkiewEwSMZ", "DIRECT", "INVESTIGATION", "hJh5C3yC5i4"),  # Other (3) CSF
    ("MICROBIOLOGY", "KrxXDyZuLQM", "DIRECT", "INVESTIGATION", "KrxXDyZuLQM"),  # Name of Antibiotic - Other (3) CSF
    ("MICROBIOLOGY", "ZkfUeVCv8MF", "DIRECT", "INVESTIGATION", "sTIL4vzhMNp"),  # Other (4) CSF
    ("MICROBIOLOGY", "FlHy9NjAvLg", "DIRECT", "INVESTIGATION", "FlHy9NjAvLg"),  # Name of Antibiotic - Other (4) CSF
    ("MICROBIOLOGY", "kN1CKw9aXdR", "DIRECT", "INVESTIGATION", "mtbwsw8rZp7"),  # Other (5) CSF
    ("MICROBIOLOGY", "XiKNH5umG1o", "DIRECT", "INVESTIGATION", "XiKNH5umG1o"),  # Name of Antibiotic - Other (5) CSF

    # ════════════════════════════════════════════════════════════════
    # INTERVENTIONS stage
    # ════════════════════════════════════════════════════════════════
    # KMC
    # Note: QK7Fi6OwtDC (KMC Administered:), JxGlnPychB0 (KMC Start Date), MTvAG4BV7Ne (KMC End Date),
    # and Type of KMC Practised (D891xeX6TRO, aVBqUrLEpkz, tGDZgz2aIXO) are populated dynamically in sync_kmc().
    ("INTERVENTIONS", "qO53L62uMZT", "DIRECT", "KMC_FOLLOWUP",  "qO53L62uMZT"),  # Any congenital malformation affecting KMC? (shared UID)
    ("INTERVENTIONS", "NngEAfMfXLL", "DIRECT", "KMC_FOLLOWUP",  "NngEAfMfXLL"),  # Able to breathe spontaneously (after resuscitation) at 60 min after birth?
    ("INTERVENTIONS", "dQKpx6JlCyD", "DIRECT", "KMC_FOLLOWUP",  "dQKpx6JlCyD"),  # Needed mechanical ventilation in first 2h after birth or admission?
    ("INTERVENTIONS", "oWFkRISar1P", "DIRECT", "KMC_FOLLOWUP",  "oWFkRISar1P"),  # Needed inotropes in first 2h after birth or admission?

    # Oxygen Therapy
    ("INTERVENTIONS", "krfSVqGrvkH", "DIRECT", "MEDICATION_INTV", "WoGgKeuaq2K"),  # O2 Therapy administered
    # Count of oxygen therapy sessions (events where O2 administered = Yes)
    # C4KvbCZKI1N = "How many times did the newborn receive oxygen therapy?" (NID_DD_Jun_28.xlsx)
    ("INTERVENTIONS", "C4KvbCZKI1N", "COUNT_YES", "MEDICATION_INTV", "WoGgKeuaq2K", "1"),
    # O2 Therapy slot 1 (first MEDICATION_INTV event)
    ("INTERVENTIONS", "XboS5tBfdHR", "TIME_KNOWN", "MEDICATION_INTV", "AUa6XTKUeTx", None),  # O2 SpO2 (1) known?
    ("INTERVENTIONS", "ISYYtYZR6R0", "REPEATABLE_SLOT", "MEDICATION_INTV", "AUa6XTKUeTx", 0, "WoGgKeuaq2K"),  # O2 SpO2 (1)
    ("INTERVENTIONS", "QemrVJP7hro", "REPEATABLE_SLOT", "MEDICATION_INTV", "KEYyyiehKDj", 0, "WoGgKeuaq2K"),  # O2 Start date (1)
    ("INTERVENTIONS", "uYvQLO1ciJT", "REPEATABLE_SLOT", "MEDICATION_INTV", "Z73jCdejW8t", 0, "WoGgKeuaq2K"),  # O2 Start time (1)
    ("INTERVENTIONS", "EWzLMNwEuQc", "REPEATABLE_SLOT", "MEDICATION_INTV", "uIJfI3yfUUd", 0, "WoGgKeuaq2K"),  # O2 End date (1)
    ("INTERVENTIONS", "xNyj9tONL4X", "REPEATABLE_SLOT", "MEDICATION_INTV", "GHWKf1SXPP1", 0, "WoGgKeuaq2K"),  # O2 End time (1)
    # O2 slot 2
    ("INTERVENTIONS", "KhJvPI22Pzj", "TIME_KNOWN", "MEDICATION_INTV", "AUa6XTKUeTx", None),
    ("INTERVENTIONS", "BDH6U3NpeCY", "REPEATABLE_SLOT", "MEDICATION_INTV", "AUa6XTKUeTx", 1, "WoGgKeuaq2K"),  # O2 SpO2 (2)
    ("INTERVENTIONS", "Eiia6qxVk2A", "REPEATABLE_SLOT", "MEDICATION_INTV", "KEYyyiehKDj", 1, "WoGgKeuaq2K"),
    ("INTERVENTIONS", "ZqFDRHLBSwt", "REPEATABLE_SLOT", "MEDICATION_INTV", "Z73jCdejW8t", 1, "WoGgKeuaq2K"),
    ("INTERVENTIONS", "eEUJxXqqEJJ", "REPEATABLE_SLOT", "MEDICATION_INTV", "uIJfI3yfUUd", 1, "WoGgKeuaq2K"),
    ("INTERVENTIONS", "bV1OifyviUw", "REPEATABLE_SLOT", "MEDICATION_INTV", "GHWKf1SXPP1", 1, "WoGgKeuaq2K"),
    # O2 slot 3
    ("INTERVENTIONS", "Vh0ES1o7KNT", "TIME_KNOWN", "MEDICATION_INTV", "AUa6XTKUeTx", None),
    ("INTERVENTIONS", "lvouQI1UVEY", "REPEATABLE_SLOT", "MEDICATION_INTV", "AUa6XTKUeTx", 2, "WoGgKeuaq2K"),
    ("INTERVENTIONS", "IfyYMYw9lmT", "REPEATABLE_SLOT", "MEDICATION_INTV", "KEYyyiehKDj", 2, "WoGgKeuaq2K"),
    ("INTERVENTIONS", "Avxjx7tXEHQ", "REPEATABLE_SLOT", "MEDICATION_INTV", "Z73jCdejW8t", 2, "WoGgKeuaq2K"),
    ("INTERVENTIONS", "QpZFFmS6QcG", "REPEATABLE_SLOT", "MEDICATION_INTV", "uIJfI3yfUUd", 2, "WoGgKeuaq2K"),
    ("INTERVENTIONS", "ES6Zmwi7zT2", "REPEATABLE_SLOT", "MEDICATION_INTV", "GHWKf1SXPP1", 2, "WoGgKeuaq2K"),

    # CPAP
    ("INTERVENTIONS", "wlHEf9FdmJM", "DIRECT", "CPAP_FOLLOWUP", "SJAHJ9wJpgA"),  # CPAP Administered
    # O5jNK2fQZ4b = "How many times did the newborn receive CPAP?" (NID_DD_Jun_28.xlsx)
    ("INTERVENTIONS", "O5jNK2fQZ4b", "COUNT_YES", "CPAP_FOLLOWUP", "SJAHJ9wJpgA", "1"),  # CPAP count
    ("INTERVENTIONS", "QfaF5JRT7Fk", "COUNT_YES_CODED", "MEDICATION_INTV", "lbZdZyHFAxi", "1"),  # MV count (coded: 1=Once..4=More than three)
    ("INTERVENTIONS", "CIKlewzNAxj", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "TI3zMPCl1G7", 0, "SJAHJ9wJpgA"),  # CPAP type
    ("INTERVENTIONS", "RJHDOGujoGB", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "zmW9SFfQ6e0", 0, "SJAHJ9wJpgA"),  # CPAP requires power
    # CPAP slot 1
    ("INTERVENTIONS", "AmpkrjFCWBx", "TIME_KNOWN", "CPAP_FOLLOWUP", "RAkSOtwV5an", None),
    ("INTERVENTIONS", "E7nomh78NBC", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "RAkSOtwV5an", 0, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "yVNrsnUo7AR", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "WsE3Gzhdvwz", 0, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "Ul6aAlFy5Kk", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "eQnqycIokxs", 0, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "ukylqlOcYdR", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "Asq4Lpht0Ga", 0, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "xKlgKlAhKcR", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "FbBHL68X1d1", 0, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "Pa5lXWI6XrD", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "zo86nmm5SqN", 0, "SJAHJ9wJpgA"),
    # CPAP slot 2
    ("INTERVENTIONS", "QQXqNHFoocU", "TIME_KNOWN", "CPAP_FOLLOWUP", "RAkSOtwV5an", None),
    ("INTERVENTIONS", "zaQektG7dWH", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "RAkSOtwV5an", 1, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "ZKKkpJlWmE4", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "WsE3Gzhdvwz", 1, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "NFcGaw2ZNee", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "eQnqycIokxs", 1, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "AHLtjrRJsmq", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "Asq4Lpht0Ga", 1, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "Ve3OYP5OQB1", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "FbBHL68X1d1", 1, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "VM0TQmPTRft", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "zo86nmm5SqN", 1, "SJAHJ9wJpgA"),
    # CPAP slot 3
    ("INTERVENTIONS", "Ff3VcTfyMRh", "TIME_KNOWN", "CPAP_FOLLOWUP", "RAkSOtwV5an", None),
    ("INTERVENTIONS", "WUVkmTs4c37", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "RAkSOtwV5an", 2, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "zHkCW3B50fV", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "WsE3Gzhdvwz", 2, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "y6qsyadmp9n", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "eQnqycIokxs", 2, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "NnDTyGaeRSp", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "Asq4Lpht0Ga", 2, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "k28FJTj5ILk", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "FbBHL68X1d1", 2, "SJAHJ9wJpgA"),
    ("INTERVENTIONS", "pwYbjrLhYb4", "REPEATABLE_SLOT", "CPAP_FOLLOWUP", "zo86nmm5SqN", 2, "SJAHJ9wJpgA"),

    # Mechanical Ventilation
    ("INTERVENTIONS", "OvLxWK7Zlmw", "DIRECT", "MEDICATION_INTV", "lbZdZyHFAxi"),  # MV received
    ("INTERVENTIONS", "Mp7tRVEhO8z", "TIME_KNOWN", "MEDICATION_INTV", "SQ3hSykdzEG", None),
    ("INTERVENTIONS", "LyxGrHVXOpX", "REPEATABLE_SLOT", "MEDICATION_INTV", "SQ3hSykdzEG", 0, "lbZdZyHFAxi"),
    ("INTERVENTIONS", "NGbHl4Od88X", "REPEATABLE_SLOT", "MEDICATION_INTV", "XTyDA9cHpWb", 0, "lbZdZyHFAxi"),
    ("INTERVENTIONS", "kKeKq4lj4o9", "REPEATABLE_SLOT", "MEDICATION_INTV", "yeD59vWM1rx", 0, "lbZdZyHFAxi"),
    ("INTERVENTIONS", "p3AAbAwXscu", "REPEATABLE_SLOT", "MEDICATION_INTV", "u1inO8W6VYv", 0, "lbZdZyHFAxi"),
    ("INTERVENTIONS", "SSmNMgUx3AF", "REPEATABLE_SLOT", "MEDICATION_INTV", "eHItCWGJggA", 0, "lbZdZyHFAxi"),  # MV End Time (1)

    # "Is the start/end time documented?" TRUE_ONLY choice pairs.
    # Each choice (Start Time, End Time) must be checked against its OWN
    # source field independently — start-time presence does not imply
    # end-time presence and vice versa. (Not recorded)/(Not readable)
    # choices have no NCF equivalent (NCF is simply blank-or-filled, no
    # "not recorded"/"not readable" concept) and are intentionally left
    # unmapped, same as the anticonvulsant Not recorded/Not readable
    # options above.
    ("INTERVENTIONS", "QmgpIZ9GXfo", "TRUE_ONLY_SLOT", "MEDICATION_INTV", "Z73jCdejW8t", 0),   # O2 (1) start time documented?
    ("INTERVENTIONS", "LFa1JD7DDfI", "TRUE_ONLY_SLOT", "MEDICATION_INTV", "GHWKf1SXPP1", 0),   # O2 (1) end time documented?
    ("INTERVENTIONS", "AXWXvLgCkDt", "TRUE_ONLY_SLOT", "MEDICATION_INTV", "Z73jCdejW8t", 1),   # O2 (2) start time documented?
    ("INTERVENTIONS", "rZdUtStfOHN", "TRUE_ONLY_SLOT", "MEDICATION_INTV", "GHWKf1SXPP1", 1),   # O2 (2) end time documented?
    ("INTERVENTIONS", "h7V3YgUr2V5", "TRUE_ONLY_SLOT", "MEDICATION_INTV", "Z73jCdejW8t", 2),   # O2 (3) start time documented?
    ("INTERVENTIONS", "UkXZd2m94x9", "TRUE_ONLY_SLOT", "MEDICATION_INTV", "GHWKf1SXPP1", 2),   # O2 (3) end time documented?

    ("INTERVENTIONS", "sQMb3gtuuuH", "TRUE_ONLY_SLOT", "CPAP_FOLLOWUP", "eQnqycIokxs", 0),     # CPAP (1) start time documented?
    ("INTERVENTIONS", "EPAAMBESHU4", "TRUE_ONLY_SLOT", "CPAP_FOLLOWUP", "FbBHL68X1d1", 0),     # CPAP (1) end time documented?
    ("INTERVENTIONS", "o9zRthmzk8Q", "TRUE_ONLY_SLOT", "CPAP_FOLLOWUP", "eQnqycIokxs", 1),     # CPAP (2) start time documented?
    ("INTERVENTIONS", "QGBNo7eBiHD", "TRUE_ONLY_SLOT", "CPAP_FOLLOWUP", "FbBHL68X1d1", 1),     # CPAP (2) end time documented?
    ("INTERVENTIONS", "kKsbddmOLpl", "TRUE_ONLY_SLOT", "CPAP_FOLLOWUP", "eQnqycIokxs", 2),     # CPAP (3) start time documented?
    ("INTERVENTIONS", "VQ15zwMlak8", "TRUE_ONLY_SLOT", "CPAP_FOLLOWUP", "FbBHL68X1d1", 2),     # CPAP (3) end time documented?

    ("INTERVENTIONS", "buYwcbgRBr5", "TRUE_ONLY_SLOT", "MEDICATION_INTV", "yeD59vWM1rx", 0),   # MV (1) start time documented?
    ("INTERVENTIONS", "BNHT4Kqst4t", "TRUE_ONLY_SLOT", "MEDICATION_INTV", "eHItCWGJggA", 0),   # MV (1) end time documented?

    # --- Antibiotics ---
    # NCF: "Antibiotics administered?" (hCb06Jbjqk3, Yes/No) followed by a
    # MULTI_TEXT "select antibiotic(s)" (cRKvNNrQ9iX) with per-antibiotic
    # conditional date/time followups. NID models each antibiotic as its
    # own independent TRUE_ONLY field — same MULTI_TO_TRUE pattern already
    # used for anticonvulsants above. (Not recorded)/(Not readable) choices
    # have no NCF equivalent and are intentionally left unmapped.
    ("INTERVENTIONS", "sxtsEDilKZd", "DIRECT", "MEDICATION_INTV", "hCb06Jbjqk3"),  # Were antibiotics administered?
    ("INTERVENTIONS", "B4HgnvxzolW", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "2"),   # Gentamicin
    ("INTERVENTIONS", "A0ck2DqbJ3t", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "10"),  # Ampicillin
    ("INTERVENTIONS", "Zss8Xkz5OZU", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "17"),  # Cloxacillin
    ("INTERVENTIONS", "amYVYx1lw05", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "18"),  # Ciprofloxacin
    ("INTERVENTIONS", "pzRnfKCqGL3", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "4"),   # Ceftriaxone
    ("INTERVENTIONS", "Vi2XnTmJSea", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "3"),   # Amikacin
    ("INTERVENTIONS", "UT2oqCylYJ0", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "11"),  # Amoxicillin
    ("INTERVENTIONS", "TBYm9sedhX4", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "1"),   # Benzathine Penicillin
    ("INTERVENTIONS", "bSeklCXtYHZ", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "7"),   # Metronidazole
    ("INTERVENTIONS", "LeQmAAUZWLz", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "15"),  # Cefotaxime
    ("INTERVENTIONS", "j1cEvYBhKBR", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "13"),  # Meropenem
    ("INTERVENTIONS", "xM1F4tdKdbS", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "8"),   # Vancomycin
    ("INTERVENTIONS", "jLfJQrVYv89", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "14"),  # Crystalline Penicillin
    ("INTERVENTIONS", "WLo6XUuO9N3", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "19"),  # Cefalexin
    ("INTERVENTIONS", "r4WHyct2RP6", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "20"),  # Cefixime
    ("INTERVENTIONS", "u6BDT4xQrbN", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "5"),   # Ceftazidime
    ("INTERVENTIONS", "cXYa2BZ6Sd7", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "9"),   # Clindamycin
    ("INTERVENTIONS", "t6tCIarpX3B", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "12"),  # Flucloxacillin
    ("INTERVENTIONS", "yPRAzya3BEr", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "16"),  # Levofloxacin
    ("INTERVENTIONS", "sWqXnZwK5GE", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "6"),   # Piperazine
    ("INTERVENTIONS", "ibil3m2l3nJ", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "21"),  # Tazobactam
    ("INTERVENTIONS", "QCO5yFs1pHF", "MULTI_TO_TRUE", "MEDICATION_INTV", "cRKvNNrQ9iX", "99"),  # Other (specify below)

    # "Other" antibiotic follow-ups: NID only has date/time fields for the
    # Other option (no per-named-antibiotic date/time on the NID side).
    ("INTERVENTIONS", "EEmAt1qjy5G", "DIRECT",     "MEDICATION_INTV", "Aedd224yw8Z"),  # Date of OTHER antibiotic
    ("INTERVENTIONS", "B5Eu0vPo37j", "TIME_KNOWN", "MEDICATION_INTV", "QO07oJDPLev"),  # Is time of OTHER antibiotic recorded?
    ("INTERVENTIONS", "djaoUVisYeH", "DIRECT",     "MEDICATION_INTV", "QO07oJDPLev"),  # Time of OTHER antibiotic

    # Per-named-antibiotic date/time/time-known follow-ups. Each antibiotic
    # selected in cRKvNNrQ9iX shows its own conditional NCF date/time
    # fields; NID has a matching date/time-known/time triplet for nearly
    # every antibiotic (a few, like Amikacin, have no date field on the
    # NCF side at all — that's a genuine gap in the source form, not
    # something to work around).
    ("INTERVENTIONS", "h5yK0YcGwlv", "DIRECT",     "MEDICATION_INTV", "kNhuwkCIkwk"),  # Gentamicin date
    ("INTERVENTIONS", "TqC3aXq83BZ", "TIME_KNOWN", "MEDICATION_INTV", "Klw11iKcolt"),  # Gentamicin time known?
    ("INTERVENTIONS", "w5Jia1thPAK", "DIRECT",     "MEDICATION_INTV", "Klw11iKcolt"),  # Gentamicin time

    ("INTERVENTIONS", "LwOKgN4CPlE", "DIRECT",     "MEDICATION_INTV", "vkHs1kbPIZa"),  # Ampicillin date
    ("INTERVENTIONS", "Z3naYgQ8Dbv", "TIME_KNOWN", "MEDICATION_INTV", "GmySZV0Emkf"),  # Ampicillin time known?
    ("INTERVENTIONS", "nZmJTEiQodK", "DIRECT",     "MEDICATION_INTV", "GmySZV0Emkf"),  # Ampicillin time

    ("INTERVENTIONS", "llrKleK3ZAt", "DIRECT",     "MEDICATION_INTV", "bSomtqjWLLQ"),  # Cloxacillin date
    ("INTERVENTIONS", "dzUz7j7z298", "TIME_KNOWN", "MEDICATION_INTV", "QAzky6CUBfM"),  # Cloxacillin time known?
    ("INTERVENTIONS", "V90zFPuLBxI", "DIRECT",     "MEDICATION_INTV", "QAzky6CUBfM"),  # Cloxacillin time

    ("INTERVENTIONS", "YoacMtjohWS", "DIRECT",     "MEDICATION_INTV", "biZc3WWoY6L"),  # Ciprofloxacin date
    ("INTERVENTIONS", "s4KAMfbCR6o", "TIME_KNOWN", "MEDICATION_INTV", "FsdX3zesI74"),  # Ciprofloxacin time known?
    ("INTERVENTIONS", "WzeVAJTWASr", "DIRECT",     "MEDICATION_INTV", "FsdX3zesI74"),  # Ciprofloxacin time

    ("INTERVENTIONS", "Mj8A4NDt5r6", "DIRECT",     "MEDICATION_INTV", "lBrvQq84ipR"),  # Ceftriaxone date
    ("INTERVENTIONS", "Gne8RK54Jh0", "TIME_KNOWN", "MEDICATION_INTV", "cDVawxmul1G"),  # Ceftriaxone time known?
    ("INTERVENTIONS", "rGRczEadxDI", "DIRECT",     "MEDICATION_INTV", "cDVawxmul1G"),  # Ceftriaxone time

    # Amikacin: no date field exists on the NCF side, only time
    ("INTERVENTIONS", "LtJEyTpQ6sQ", "TIME_KNOWN", "MEDICATION_INTV", "FF5xqqWWUOe"),  # Amikacin time known?
    ("INTERVENTIONS", "cUwot44Y7nz", "DIRECT",     "MEDICATION_INTV", "FF5xqqWWUOe"),  # Amikacin time

    ("INTERVENTIONS", "jYhWXbL0a06", "DIRECT",     "MEDICATION_INTV", "rXGdudtqVFq"),  # Amoxicillin date
    ("INTERVENTIONS", "ZnW1beUcv7h", "TIME_KNOWN", "MEDICATION_INTV", "iGW27rfBnLR"),  # Amoxicillin time known?
    ("INTERVENTIONS", "daEVH2CgNrv", "DIRECT",     "MEDICATION_INTV", "iGW27rfBnLR"),  # Amoxicillin time

    ("INTERVENTIONS", "CINMfUeJitR", "DIRECT",     "MEDICATION_INTV", "hdqv5p9bqWI"),  # Benzathine Penicillin date
    ("INTERVENTIONS", "dA3rG9ImxQa", "TIME_KNOWN", "MEDICATION_INTV", "TklgGweECvq"),  # Benzathine Penicillin time known?
    ("INTERVENTIONS", "PRAbrVJo5Hg", "DIRECT",     "MEDICATION_INTV", "TklgGweECvq"),  # Benzathine Penicillin time

    ("INTERVENTIONS", "l8aqSQWz04D", "DIRECT",     "MEDICATION_INTV", "qa6YSv4Kf9l"),  # Metronidazole date
    ("INTERVENTIONS", "X16luunlt7H", "TIME_KNOWN", "MEDICATION_INTV", "jtEXWYcp0Vb"),  # Metronidazole time known?
    ("INTERVENTIONS", "BdHPX0WJwgT", "DIRECT",     "MEDICATION_INTV", "jtEXWYcp0Vb"),  # Metronidazole time

    ("INTERVENTIONS", "oZiSdQNa8cD", "DIRECT",     "MEDICATION_INTV", "Ygn5SG64peE"),  # Cefotaxime date
    ("INTERVENTIONS", "UdFHdjkEGFY", "TIME_KNOWN", "MEDICATION_INTV", "WjHhKV3Qf12"),  # Cefotaxime time known?
    ("INTERVENTIONS", "Y0UDjS32hmW", "DIRECT",     "MEDICATION_INTV", "WjHhKV3Qf12"),  # Cefotaxime time

    ("INTERVENTIONS", "DEFUdZhOA6J", "DIRECT",     "MEDICATION_INTV", "XupzfCcHNel"),  # Meropenem date
    ("INTERVENTIONS", "apZFS6z8jLd", "TIME_KNOWN", "MEDICATION_INTV", "kYAd2ik3DYj"),  # Meropenem time known?
    ("INTERVENTIONS", "g7pK1dx0WaE", "DIRECT",     "MEDICATION_INTV", "kYAd2ik3DYj"),  # Meropenem time

    ("INTERVENTIONS", "q8YnRNaGWqF", "DIRECT",     "MEDICATION_INTV", "lzBPk9a9DSe"),  # Vancomycin date
    ("INTERVENTIONS", "fSFkEJE6L3X", "TIME_KNOWN", "MEDICATION_INTV", "pXlddWP6lGr"),  # Vancomycin time known?
    ("INTERVENTIONS", "LFK7dOq06zD", "DIRECT",     "MEDICATION_INTV", "pXlddWP6lGr"),  # Vancomycin time

    ("INTERVENTIONS", "FOFcObzneNq", "DIRECT",     "MEDICATION_INTV", "xiDTvkYxre3"),  # Crystalline Penicillin date
    ("INTERVENTIONS", "wiBIA5TLnEp", "TIME_KNOWN", "MEDICATION_INTV", "hfwwCxQK1hs"),  # Crystalline Penicillin time known?
    ("INTERVENTIONS", "Q9NjuNI0Abb", "DIRECT",     "MEDICATION_INTV", "hfwwCxQK1hs"),  # Crystalline Penicillin time

    ("INTERVENTIONS", "TUIqGGnxMLW", "DIRECT",     "MEDICATION_INTV", "BxtX3FZfQLw"),  # Cefalexin date
    ("INTERVENTIONS", "pBV1zRIt8q1", "TIME_KNOWN", "MEDICATION_INTV", "r544RXur6BQ"),  # Cefalexin time known?
    ("INTERVENTIONS", "oRJeOC64veV", "DIRECT",     "MEDICATION_INTV", "r544RXur6BQ"),  # Cefalexin time

    ("INTERVENTIONS", "tmLx3JR7vP8", "DIRECT",     "MEDICATION_INTV", "DHTlOTUuV2Z"),  # Cefixime date
    ("INTERVENTIONS", "FBVR2jp0VCs", "TIME_KNOWN", "MEDICATION_INTV", "uIlEgiRMFEB"),  # Cefixime time known?
    ("INTERVENTIONS", "vYeLcbiKPa4", "DIRECT",     "MEDICATION_INTV", "uIlEgiRMFEB"),  # Cefixime time

    ("INTERVENTIONS", "a7JK2xfxMh6", "DIRECT",     "MEDICATION_INTV", "sYulODDX31M"),  # Ceftazidime date
    ("INTERVENTIONS", "aYYAqJf8vGB", "TIME_KNOWN", "MEDICATION_INTV", "Mklcv5Y932f"),  # Ceftazidime time known?
    ("INTERVENTIONS", "s7kgxoYlZZb", "DIRECT",     "MEDICATION_INTV", "Mklcv5Y932f"),  # Ceftazidime time

    ("INTERVENTIONS", "mlKZmWzWhjQ", "DIRECT",     "MEDICATION_INTV", "bY9apQC05Du"),  # Clindamycin date
    ("INTERVENTIONS", "fCuuBCdHbrW", "TIME_KNOWN", "MEDICATION_INTV", "AbThiyzOxau"),  # Clindamycin time known?
    ("INTERVENTIONS", "H3hfJCziRDW", "DIRECT",     "MEDICATION_INTV", "AbThiyzOxau"),  # Clindamycin time

    ("INTERVENTIONS", "zfvoih382pj", "DIRECT",     "MEDICATION_INTV", "dzYHT3MlC2M"),  # Flucloxacillin date
    ("INTERVENTIONS", "wxmUEean00I", "TIME_KNOWN", "MEDICATION_INTV", "G4H2550TGf4"),  # Flucloxacillin time known?
    ("INTERVENTIONS", "kWB8knMTjy2", "DIRECT",     "MEDICATION_INTV", "G4H2550TGf4"),  # Flucloxacillin time

    ("INTERVENTIONS", "wzFQ8hZdAQQ", "DIRECT",     "MEDICATION_INTV", "P3OBBo9JkQG"),  # Levofloxacin date
    ("INTERVENTIONS", "se0OnEpW52S", "TIME_KNOWN", "MEDICATION_INTV", "bReSbTbMgAj"),  # Levofloxacin time known?
    ("INTERVENTIONS", "Y4mF4YZ2vM4", "DIRECT",     "MEDICATION_INTV", "bReSbTbMgAj"),  # Levofloxacin time

    ("INTERVENTIONS", "s7ncQcC0IUW", "DIRECT",     "MEDICATION_INTV", "IEfc1yQA9LW"),  # Piperazine date
    ("INTERVENTIONS", "uUwWx50mv8O", "TIME_KNOWN", "MEDICATION_INTV", "TIZEO4fJcWV"),  # Piperazine time known?
    ("INTERVENTIONS", "cwAmzP3imCz", "DIRECT",     "MEDICATION_INTV", "TIZEO4fJcWV"),  # Piperazine time

    ("INTERVENTIONS", "Scj08W4B44t", "DIRECT",     "MEDICATION_INTV", "wU2UxhhPkBV"),  # Tazobactam date
    ("INTERVENTIONS", "wUHerCy4rce", "TIME_KNOWN", "MEDICATION_INTV", "y8nx5zV4KDx"),  # Tazobactam time known?
    ("INTERVENTIONS", "dkWTmnXQQDZ", "DIRECT",     "MEDICATION_INTV", "y8nx5zV4KDx"),  # Tazobactam time

    # Amikacin first administration date (earliest event in Medication stage)
    ("INTERVENTIONS", "R8Zh5BREt81", "DIRECT",     "MEDICATION_INTV", "q8uwqnZMHnW"),  # What date was Amikacin first administered?
    # Other medication specify name
    ("INTERVENTIONS", "cBfFKA2mpCS", "DIRECT",     "MEDICATION_INTV", "cBfFKA2mpCS"),  # If other - specify name:

    # --- IV Fluids ---
    # Were IV fluids administered? + a single First-Start/Last-End pair
    # (not slotted 1/2/3 like phototherapy/transfusion below) — the start
    # date should be the earliest event with a start date filled, the end
    # date the latest event with an end date filled, across the whole
    # repeatable Medication and Intervention stage.
    ("INTERVENTIONS", "oLglM9pe9Px", "DIRECT", "MEDICATION_INTV", "ozw6rQVJaar"),  # IV fluids administered?
    ("INTERVENTIONS", "UZTT4Jdp4cU", "DIRECT", "MEDICATION_INTV", "oWBSMabMGvz"),  # IV Fluids (First) Start date — earliest event with a start date filled
    ("INTERVENTIONS", "ySYOJwnxmtS", "LAST",   "MEDICATION_INTV", "yPjgb4FCQDY"),  # IV Fluids (Last) End date — latest event with an end date filled

    # --- Transfusion ---
    # Was a transfusion given? (0=No, 1=Blood, 2=Exchange blood) + up to
    # 3 repeatable transfusion-date slots, same REPEATABLE_SLOT pattern as
    # CPAP/oxygen/mechanical ventilation above.
    ("INTERVENTIONS", "zRsdb6F5JpB", "DIRECT", "MEDICATION_INTV", "xEyz81PI8Qt"),  # Transfusion given?
    # It8GlGoFhXi = "How many times was the infant given a blood transfusion
    # or exchange blood transfusion?" (NID_DD_Jun_28.xlsx). Matches either
    # Yes code (1=Blood or 2=Exchange blood), so count both.
    ("INTERVENTIONS", "It8GlGoFhXi", "COUNT_YES", "MEDICATION_INTV", "xEyz81PI8Qt", ("1", "2")),  # Transfusion count
    ("INTERVENTIONS", "JKmwY8IiyxK", "REPEATABLE_SLOT", "MEDICATION_INTV", "EaeeizdCzD4", 0, "xEyz81PI8Qt"),  # Transfusion (1) date
    ("INTERVENTIONS", "h9IF8rHtP0s", "REPEATABLE_SLOT", "MEDICATION_INTV", "EaeeizdCzD4", 1, "xEyz81PI8Qt"),  # Transfusion (2) date
    ("INTERVENTIONS", "Uh5qJQhrZGg", "REPEATABLE_SLOT", "MEDICATION_INTV", "EaeeizdCzD4", 2, "xEyz81PI8Qt"),  # Transfusion (3) date

    # --- Phototherapy ---
    # Was Phototherapy Administered? + up to 3 repeatable start/end date
    # slots.
    ("INTERVENTIONS", "EDwkmS1fKbG", "DIRECT", "MEDICATION_INTV", "Hwe1gdn1UZ4"),  # Phototherapy administered?
    # V7H02RXF5MS = "How many times did the newborn receive phototherapy?" (NID_DD_Jun_28.xlsx)
    ("INTERVENTIONS", "V7H02RXF5MS", "COUNT_YES", "MEDICATION_INTV", "Hwe1gdn1UZ4", "1"),  # Phototherapy count
    ("INTERVENTIONS", "De7xfwCSxix", "REPEATABLE_SLOT", "MEDICATION_INTV", "HKIpLkXegQv", 0, "Hwe1gdn1UZ4"),  # Phototherapy (1) Start date
    ("INTERVENTIONS", "yqbDYqxMNPd", "REPEATABLE_SLOT", "MEDICATION_INTV", "qParN8pyk0S", 0, "Hwe1gdn1UZ4"),  # Phototherapy (1) End date
    ("INTERVENTIONS", "rCP3ZbJ1dFv", "REPEATABLE_SLOT", "MEDICATION_INTV", "HKIpLkXegQv", 1, "Hwe1gdn1UZ4"),  # Phototherapy (2) Start date
    ("INTERVENTIONS", "ru1zCAyFRU5", "REPEATABLE_SLOT", "MEDICATION_INTV", "qParN8pyk0S", 1, "Hwe1gdn1UZ4"),  # Phototherapy (2) End date
    ("INTERVENTIONS", "axCnXyOMVrr", "REPEATABLE_SLOT", "MEDICATION_INTV", "HKIpLkXegQv", 2, "Hwe1gdn1UZ4"),  # Phototherapy (3) Start date
    ("INTERVENTIONS", "H74l4J7TkUu", "REPEATABLE_SLOT", "MEDICATION_INTV", "qParN8pyk0S", 2, "Hwe1gdn1UZ4"),  # Phototherapy (3) End date

    # ════════════════════════════════════════════════════════════════
    # OBSERVATIONS AND NURSING CARE 2 stage
    # All temperature/SpO2/blood-sugar/bilirubin fields here are derived
    # from the repeatable Nurse Followup Sheet (eCyte3bTjHS): find the
    # event with the highest or lowest value of the relevant NCF data
    # element, then pull the value, "documented?" flag, event date, and
    # any companion field (unit, time-of-measurement) from that SAME
    # winning event via AGGREGATE_EXTREME.
    # ════════════════════════════════════════════════════════════════

    # --- Temperature after admission: lowest ---
    # NCF source: dTLOUzugcrv (Temperature n), mDdFiZRXnLq (unit: 1=C,2=F),
    # sg5hNeLwYeO (time of measurement), AXKdz7RhhGx is the event's own
    # date (read via eventDate, not a dataValue).
    ("OBS_NURSING_2", "JGmsAV77Oqb", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "min", "documented"),
    ("OBS_NURSING_2", "covLKweyILn", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "min", "date"),
    ("OBS_NURSING_2", "fpG9sCgZPwk", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "min", ("time_documented", "sg5hNeLwYeO")),
    ("OBS_NURSING_2", "JpZASOdU0S1", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "min", "sg5hNeLwYeO"),
    ("OBS_NURSING_2", "DUGs7lEeSw3", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "min", "mDdFiZRXnLq"),
    ("OBS_NURSING_2", "nIKIu6f5vbW", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "min", ("value_if_unit", "mDdFiZRXnLq", "1")),  # °C
    ("OBS_NURSING_2", "u0PEOL92yek", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "min", ("value_if_unit", "mDdFiZRXnLq", "2")),  # °F

    # --- Temperature after admission: highest ---
    ("OBS_NURSING_2", "VHBLVONKkxa", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "max", "documented"),
    ("OBS_NURSING_2", "tTN0VrL1p0i", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "max", "date"),
    ("OBS_NURSING_2", "IcQuHMXMcTX", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "max", ("time_documented", "sg5hNeLwYeO")),
    ("OBS_NURSING_2", "ckpHYZzQFum", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "max", "sg5hNeLwYeO"),
    ("OBS_NURSING_2", "NVOs4BYcXjO", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "max", "mDdFiZRXnLq"),
    ("OBS_NURSING_2", "sCDFBFReCco", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "max", ("value_if_unit", "mDdFiZRXnLq", "1")),  # °C
    ("OBS_NURSING_2", "hdxCvZFup6E", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "dTLOUzugcrv", "max", ("value_if_unit", "mDdFiZRXnLq", "2")),  # °F

    # --- Oxygen saturation during admission: lowest / highest ---
    # NCF source: DKP2ZTklLce (Oxygen Saturation), single value, no unit split
    ("OBS_NURSING_2", "doPNvPd5YXx", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "DKP2ZTklLce", "min", "documented"),
    ("OBS_NURSING_2", "j4W59YyYG04", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "DKP2ZTklLce", "min", "value"),
    ("OBS_NURSING_2", "Xk97kGaEqfG", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "DKP2ZTklLce", "max", "documented"),
    ("OBS_NURSING_2", "ydFKE4DmfrT", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "DKP2ZTklLce", "max", "value"),

    # --- Blood sugar concentration during admission: lowest / highest ---
    # NCF source: gwgZR3r9ZGw (Blood sugar concentration), AftnPKeAZAX
    # (unit: 1=mmol/L, 2=mg/dL)
    ("OBS_NURSING_2", "QeHhe3Bt0Qe", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "gwgZR3r9ZGw", "min", "documented"),
    ("OBS_NURSING_2", "BLGV9XAxapx", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "gwgZR3r9ZGw", "min", "AftnPKeAZAX"),
    ("OBS_NURSING_2", "d3PkVNa0ozG", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "gwgZR3r9ZGw", "min", ("value_if_unit", "AftnPKeAZAX", "1")),  # mmol/L
    ("OBS_NURSING_2", "GHfKwL7n4v5", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "gwgZR3r9ZGw", "min", ("value_if_unit", "AftnPKeAZAX", "2")),  # mg/dL
    ("OBS_NURSING_2", "uLi1DOCuN3W", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "gwgZR3r9ZGw", "max", "documented"),
    ("OBS_NURSING_2", "azvvufMCLHI", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "gwgZR3r9ZGw", "max", "AftnPKeAZAX"),
    ("OBS_NURSING_2", "pjkHalppWvQ", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "gwgZR3r9ZGw", "max", ("value_if_unit", "AftnPKeAZAX", "1")),  # mmol/L
    ("OBS_NURSING_2", "ed8GeVgGDG7", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "gwgZR3r9ZGw", "max", ("value_if_unit", "AftnPKeAZAX", "2")),  # mg/dL

    # --- Bilirubin: highest only (NID has no "lowest bilirubin" field) ---
    # NCF source: hbuxW3DQ64V (bilirubin value mg/dL), NUAg753t5yq (how
    # measured: 1=Serum, 2=Transcutaneous), tXePphrdJDX (bilirubin tested?
    # — direct copy, not aggregate, since it's a single yes/no not a value)
    ("OBS_NURSING_2", "U7ey9R5QZk1", "DIRECT", "NURSE_FOLLOWUP", "tXePphrdJDX"),   # Was bilirubin tested?
    ("OBS_NURSING_2", "W8PIbjZMBcd", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "hbuxW3DQ64V", "max", "documented"),
    ("OBS_NURSING_2", "p4NR33eio81", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "hbuxW3DQ64V", "max", "value"),
    ("OBS_NURSING_2", "uCXBBUvB2hE", "AGGREGATE_EXTREME", "NURSE_FOLLOWUP", "hbuxW3DQ64V", "max", "NUAg753t5yq"),

    # --- Feeding ---
    ("OBS_NURSING_2", "K0YTHJ99oSo", "DIRECT", "KMC_FOLLOWUP", "RSlquOUbjiA"),     # Breast milk start date
    ("OBS_NURSING_2", "X21J4DGwIYU", "DIRECT", "NURSE_FOLLOWUP", "X21J4DGwIYU"),   # Feeding (other than breast milk) start date
    ("OBS_NURSING_2", "LzkuvexfeMX", "DIRECT", "DISCHARGE_CARE", "X8lscblixAQ"),   # Feeding at discharge

    # --- Seizures / anticonvulsants ---
    ("OBS_NURSING_2", "ZLBeosjc5rb", "DIRECT", "NURSE_FOLLOWUP", "ICDGgj6NEp8"),   # Seizures during stay?
    ("OBS_NURSING_2", "kNmAsHKRdBs", "DIRECT", "NURSE_FOLLOWUP", "R54roEDSasg"),   # Anticonvulsants administered?
    # rpQXTuMAQ2i is MULTI_TEXT (comma-separated option codes); NID splits
    # each option into its own TRUE_ONLY field
    ("OBS_NURSING_2", "mEFBBqZKgya", "MULTI_TO_TRUE", "NURSE_FOLLOWUP", "rpQXTuMAQ2i", "1"),  # Phenobarbitone/Phenobarbital
    ("OBS_NURSING_2", "mQqEpzeSw0w", "MULTI_TO_TRUE", "NURSE_FOLLOWUP", "rpQXTuMAQ2i", "2"),  # Phenytoin
    ("OBS_NURSING_2", "aN9SHmHmYPD", "MULTI_TO_TRUE", "NURSE_FOLLOWUP", "rpQXTuMAQ2i", "3"),  # Diazepam
    ("OBS_NURSING_2", "Ok6ebbG1rHR", "MULTI_TO_TRUE", "NURSE_FOLLOWUP", "rpQXTuMAQ2i", "4"),  # Paraldehyde

    # ════════════════════════════════════════════════════════════════
    # DISCHARGE AND FINAL DIAGNOSIS stage
    # Source is almost entirely the non-repeatable Discharge care form
    # (DISCHARGE_CARE / CbH1hYxJdL7) plus one field from the Neonatal
    # referral form (REFERRAL_FORM).
    # ════════════════════════════════════════════════════════════════
    ("DISCHARGE", "vmOAGuFcaz4", "DIRECT", "DISCHARGE_CARE", "XITh8vyfqaR"),   # Newborn status at discharge
    ("DISCHARGE", "m1ZcWP63LfA", "DIRECT", "DISCHARGE_CARE", "YFp5BRt5BB0"),   # Discharge Outcome
    ("DISCHARGE", "LQgcE3sHaoy", "DIRECT", "REFERRAL_FORM",  "Hme6E8LluaB"),   # If referred/transferred - where?

    # Date and time of discharge: NCF stores one combined DATETIME value;
    # NID wants it split into a DATE field, a TIME field, and a "was the
    # time collected?" flag.
    ("DISCHARGE", "m1z6MhGTj5P",  "DATETIME_SPLIT", "DISCHARGE_CARE", "VNV2QYQpebO", "date"),
    ("DISCHARGE", "lBId1mtjJpg",  "DATETIME_KNOWN", "DISCHARGE_CARE", "VNV2QYQpebO"),
    ("DISCHARGE", "TPvUF0LYvlP",  "DATETIME_SPLIT", "DISCHARGE_CARE", "VNV2QYQpebO", "time"),

    ("DISCHARGE", "xqwIv0cI5qs",  "TIME_KNOWN", "DISCHARGE_CARE", "ZkeSH8X8MKK"),  # Is discharge weight documented?
    ("DISCHARGE", "yBCwmQP0A6a",  "DIRECT",     "DISCHARGE_CARE", "ZkeSH8X8MKK"),  # Discharge Weight (grams)

    ("DISCHARGE", "K2XiqR3lIon",  "DIRECT",       "DISCHARGE_CARE", "sX6phWDgfWp"),   # Follow-up appointment given?
    ("DISCHARGE", "dd6KwqTqIM5",  "DIRECT",       "DISCHARGE_CARE", "eBu2BZquyN2"),   # Reason for follow up -> Please explain concisely why given follow-up
    ("DISCHARGE", "PNmWZYTAn7Q",  "LOCATION_MAP", "DISCHARGE_CARE", "W6x0u5x701I"),   # Place of follow up -> If yes - appointment location

    ("DISCHARGE", "X2m8NB1P83P", "DIRECT", "DISCHARGE_CARE", "hP9hE6B9mVQ"),    # Primary Category
    ("DISCHARGE", "EClz4eZuxH2", "DIRECT", "DISCHARGE_CARE", "Zq5pooW1Osg"),    # Sub-cat: Congenital Malformations
    ("DISCHARGE", "EZ15XIdEBPs", "DIRECT", "DISCHARGE_CARE", "cPjiiWrQ8M2"),    # If other congenital - specify
    ("DISCHARGE", "VCatFN4N9wD", "DIRECT", "DISCHARGE_CARE", "lxtEbLnOxfk"),    # Sub-cat: Prematurity
    ("DISCHARGE", "ohLAfAXxt8g", "DIRECT", "DISCHARGE_CARE", "BBKHOvegTDE"),    # If other prematurity - specify
    ("DISCHARGE", "wn0tHaHcceW", "DIRECT", "DISCHARGE_CARE", "UGz9phsvHt4"),    # Sub-cat: Infection
    ("DISCHARGE", "m787BHmgwCW", "DIRECT", "DISCHARGE_CARE", "phpBqyI101n"),    # If other infection - specify
    ("DISCHARGE", "JZrMgGLM8vJ", "DIRECT", "INVESTIGATION", "aCHOclZEx6o"),     # Culture Positive Organism
    ("DISCHARGE", "nywYHa2KcmQ", "DIRECT", "DISCHARGE_CARE", "WVfS5quHDXh"),    # If other - full species/genus
    ("DISCHARGE", "BCq9TfrWrN4", "DIRECT", "DISCHARGE_CARE", "T2ucrO1a0tQ"),    # If full name available - species/genus
    ("DISCHARGE", "EgtIpbqXwdl", "DIRECT", "DISCHARGE_CARE", "O8ltlWp1X9U"),    # If infection - hospital-acquired?
    ("DISCHARGE", "o1sbIt5YJ8b", "DIRECT", "DISCHARGE_CARE", "kXx9ea03Eb3"),    # Sub-cat: Intrapartum-Related
    ("DISCHARGE", "iDPPfYw6jBG", "DIRECT", "DISCHARGE_CARE", "t8XD03M78mR"),    # If other intrapartum - specify
    ("DISCHARGE", "t2iHoRMo5hn", "DIRECT", "DISCHARGE_CARE", "ANU3lt2Bt3O"),    # Sub-cat: Jaundice (Pathological)
    ("DISCHARGE", "ZUKQilLpwYz", "DIRECT", "DISCHARGE_CARE", "AcMqGvSF3PW"),    # If other cause of death - specify

    ("DISCHARGE", "SFV9YU8VnfV", "DIRECT", "DISCHARGE_CARE", "HLqAvpUoEZ1"),    # Secondary Category
    ("DISCHARGE", "P4aBesmpQ51", "DIRECT", "DISCHARGE_CARE", "P4aBesmpQ51"),    # Was LBW mentioned as cause of death?

    # Secondary diagnosis fields: these data elements are deliberately
    # reused with IDENTICAL UIDs in both the NID Discharge stage and the
    # NCF Discharge care form (confirmed in metadata_V3.json), unlike the
    # Registration Number coincidence elsewhere — a same-UID DIRECT copy
    # is correct here, not a bug.
    ("DISCHARGE", "IPonOamMRtR", "DIRECT", "DISCHARGE_CARE", "IPonOamMRtR"),    # Sub-cat congenital (secondary)
    ("DISCHARGE", "qjX6Hnbg4Zq", "DIRECT", "DISCHARGE_CARE", "qjX6Hnbg4Zq"),    # If other congenital - specify (secondary)
    ("DISCHARGE", "id5Jhs2ss3M", "DIRECT", "DISCHARGE_CARE", "id5Jhs2ss3M"),    # Sub-cat prematurity (secondary)
    ("DISCHARGE", "jZmIGEg8oxc", "DIRECT", "DISCHARGE_CARE", "jZmIGEg8oxc"),    # If other prematurity - specify (secondary)
    ("DISCHARGE", "NZBqF2igHgK", "DIRECT", "DISCHARGE_CARE", "NZBqF2igHgK"),    # Sub-cat infection (secondary)
    ("DISCHARGE", "aP6GmxZuuHx", "DIRECT", "DISCHARGE_CARE", "aP6GmxZuuHx"),    # If other infection - specify (secondary)
    ("DISCHARGE", "tf6jlHpQJ9o", "DIRECT", "DISCHARGE_CARE", "tf6jlHpQJ9o"),    # Culture Positive Organism (secondary)
    ("DISCHARGE", "WVfS5quHDXh", "DIRECT", "DISCHARGE_CARE", "WVfS5quHDXh"),    # If other - species/genus (secondary)
    ("DISCHARGE", "T2ucrO1a0tQ", "DIRECT", "DISCHARGE_CARE", "T2ucrO1a0tQ"),    # If full name - species/genus (secondary)
    ("DISCHARGE", "dbP9sZAwpIY", "DIRECT", "DISCHARGE_CARE", "dbP9sZAwpIY"),    # Hospital-acquired? (secondary)
    ("DISCHARGE", "ZubLTiRFidH", "DIRECT", "DISCHARGE_CARE", "ZubLTiRFidH"),    # Sub-cat intrapartum (secondary)
    ("DISCHARGE", "G6iSlbiHtgf", "DIRECT", "DISCHARGE_CARE", "G6iSlbiHtgf"),    # If other intrapartum - specify (secondary)
    ("DISCHARGE", "SzbXpdA0G1z", "DIRECT", "DISCHARGE_CARE", "SzbXpdA0G1z"),    # Sub-cat jaundice (secondary)
    ("DISCHARGE", "rOKs8wSZWMQ", "DIRECT", "DISCHARGE_CARE", "rOKs8wSZWMQ"),    # If other cause of death - specify (secondary)
]

# ─────────────────────────────────────────────────────────────────
# TEI ATTRIBUTE SYNC: NCF TEA uid → NID TEA uid
# Both sides here must be genuine Tracked Entity Attributes (read from
# trackedEntityInstances[].attributes). Date of Birth is handled
# separately below because its NCF-side source (vKsjdwDyJhC, "Date of
# delivery") is a DATA ELEMENT on the NICU Admission Careform event, not a
# tracked entity attribute — it can't be read from ncf_attrs.
# ─────────────────────────────────────────────────────────────────
TEA_MAPPING = [
    ("LQSiyXRGvT0", "tiMSRGbNJJz"),  # First Name Baby: NCF → NID
    ("r0Dq5ZiCOZE", "RRFJFC0UyrX"),  # Last Name Baby
    ("W8CvotP4K6C", "e84cAeFkDKD"),  # Neonate Sex
    ("Xam97lYmJB7", "UGwDTPoObkT"),  # Record ID
]

# Date of Birth: NCF source is a DATA ELEMENT (vKsjdwDyJhC, "Date of
# delivery") on the non-repeatable NICU Admission Careform stage — read it
# from that stage's event dataValues, not from TEI attributes. NID target
# (eRloSIinbeT, "Date of Birth (DOB):") is a TEI attribute, and is one of
# the NID program's 5 mandatory attributes required at TEI creation.
NCF_DOB_STAGE = "NICU_ADMISSION"
NCF_DOB_DE = "vKsjdwDyJhC"
NID_DOB_TEA = "eRloSIinbeT"

# ─────────────────────────────────────────────────────────────────
# ORG-UNIT LEVEL ADMIN FIELDS (NID ADMISSION stage)
# These NID-only fields have no NCF source: Facility Name, Data
# Officer ID Number and Data Officer Name are fixed per org unit.
# Facility Name (hXuMvI0hz7y) is an ORGANISATION_UNIT field, so its
# value is the org unit UID of the record — same facility as the NCF
# record. Data Officer ID/Name are filled only for org units present
# in ORG_UNIT_OFFICER_MAP, keyed by org unit UID.
# ─────────────────────────────────────────────────────────────────
NID_FACILITY_NAME_DE = "hXuMvI0hz7y"
NID_OFFICER_ID_DE    = "Fa20HhxbgzS"
NID_OFFICER_NAME_DE  = "bvOMmZxX5Qh"

ORG_UNIT_OFFICER_MAP = {
    # org unit UID: (Data Officer ID Number, Data Officer Name)
    "xKpOsRLDIsG": ("04", "Weldemikiel"),  # Mekelle General Hospital
}

# ─────────────────────────────────────────────────────────────────
# GEOGRAPHICAL INFORMATION (NID ADMISSION stage)
# NID captures residence geography as: a master "Do you have ...?"
# flag (E4PKTETHHdR), four TRUE_ONLY checks (one per collected field),
# and separate value fields. The NCF source fields live on the NICU
# Admission Careform. If any of Region/Zone/Wereda/Kebele is filled the
# master flag is Yes and that field's check+value are filled; if none is
# filled the master flag is No.
# ─────────────────────────────────────────────────────────────────
NID_GEO_STAGE = "NICU_ADMISSION"
GEO_REGION_DE  = "S2gHACsOYRD"   # NCF Region   (INTEGER; optionSet codes match NID)
GEO_ZONE_DE    = "JatpcsSbqBR"   # NCF Zone
GEO_WEREDA_DE  = "E4G1xedugN5"   # NCF Wereda
GEO_KEBELE_DE  = "x6ptZCZDFBG"   # NCF Kebele

NID_GEO_MASTER         = "E4PKTETHHdR"   # Do you have geographical information...? 1=Yes,0=No
NID_GEO_REGION_VAL     = "SgGt8h7BApX"   # National Regional State or Administrative Council:
NID_GEO_ADDRESS_VAL    = "c4MJWVqqMxy"   # Address Notes/Directions:
NID_GEO_REGION_FLAG    = "JUthcnj46m6"   # ... (choice=National Regional State or Administrative Council)
NID_GEO_ZONE_FLAG      = "T1AHrDBiC3t"   # ... (choice=Zone)
NID_GEO_WEREDA_FLAG    = "FUfGiIa6wh0"   # ... (choice=Woredas)
NID_GEO_KEBELE_FLAG    = "hM1fkHibq86"   # ... (choice=Other notes on address/directions)
NID_GEO_DOC_MULTI      = "kH2fRrt0y1J"   # What geographical information was collected? (MULTI_TEXT: 1=Region,2=Zone,3=Woredas,4=Other notes)

# TIME_KNOWN targets: most "is ... known/recorded/documented?" fields on
# the NID side are valueType TEXT with a coded 1=Yes/0=No option set (plus
# sometimes -1=Not recorded, -3=Not readable) — these need the literal "1",
# not the word "true". A handful are genuine valueType BOOLEAN fields with
# no option set at all, where DHIS2 expects the literal "true"/"false".
# Confirmed per-field against metadata_V3.json (dataElements[].valueType
# and .optionSet) rather than assumed — do not add to this set without the
# same check, since most candidates turn out to be coded TEXT, not BOOLEAN.
TIME_KNOWN_BOOLEAN_DES = {
    "xFosIUSTXYR",  # Is the time of birth recorded? (BOOLEAN, no optionSet)
    "UamL5CdWhV6",  # Is time of admission recorded? (BOOLEAN, no optionSet)
    "dDoewefeO81",  # Is weight on admission documented? (BOOLEAN, no optionSet)
    "usbIOqcqyGT",  # Is birth weight documented? (BOOLEAN, no optionSet)
    "VA598XGBBTl",  # Is the GA calculation method known? (BOOLEAN, no optionSet)
    "fpG9sCgZPwk",  # Is the time of lowest temp AFTER admission recorded? (BOOLEAN)
    "IcQuHMXMcTX",  # Is the time of highest temp AFTER admission recorded? (BOOLEAN)
    "B5Eu0vPo37j",  # Is the time of OTHER first antibiotic administration recorded? (BOOLEAN)
    "TqC3aXq83BZ",  # Gentamicin time known? (BOOLEAN)
    "Z3naYgQ8Dbv",  # Ampicillin time known? (BOOLEAN)
    "dzUz7j7z298",  # Cloxacillin time known? (BOOLEAN)
    "s4KAMfbCR6o",  # Ciprofloxacin time known? (BOOLEAN)
    "Gne8RK54Jh0",  # Ceftriaxone time known? (BOOLEAN)
    "LtJEyTpQ6sQ",  # Amikacin time known? (BOOLEAN)
    "ZnW1beUcv7h",  # Amoxicillin time known? (BOOLEAN)
    "dA3rG9ImxQa",  # Benzathine Penicillin time known? (BOOLEAN)
    "X16luunlt7H",  # Metronidazole time known? (BOOLEAN)
    "UdFHdjkEGFY",  # Cefotaxime time known? (BOOLEAN)
    "apZFS6z8jLd",  # Meropenem time known? (BOOLEAN)
    "fSFkEJE6L3X",  # Vancomycin time known? (BOOLEAN)
    "wiBIA5TLnEp",  # Crystalline Penicillin time known? (BOOLEAN)
    "pBV1zRIt8q1",  # Cefalexin time known? (BOOLEAN)
    "FBVR2jp0VCs",  # Cefixime time known? (BOOLEAN)
    "aYYAqJf8vGB",  # Ceftazidime time known? (BOOLEAN)
    "fCuuBCdHbrW",  # Clindamycin time known? (BOOLEAN)
    "wxmUEean00I",  # Flucloxacillin time known? (BOOLEAN)
    "se0OnEpW52S",  # Levofloxacin time known? (BOOLEAN)
    "uUwWx50mv8O",  # Piperazine time known? (BOOLEAN)
    "wUHerCy4rce",  # Tazobactam time known? (BOOLEAN)
}

# ─────────────────────────────────────────────────────────────────
# DHIS2 API CLIENT
# ─────────────────────────────────────────────────────────────────
class DHIS2Client:
    def __init__(self, server: str, username: str, password: str):
        if not server or not str(server).strip():
            raise ValueError("DHIS2 server URL is required.")
        if not username or not str(username).strip():
            raise ValueError("DHIS2 username is required.")
        if not password or not str(password).strip():
            raise ValueError("DHIS2 password is required.")
        self.server = server.rstrip("/")
        self.auth = HTTPBasicAuth(username, password)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"Content-Type": "application/json"})

    def _raise_with_detail(self, r: requests.Response):
        """Raise with DHIS2's actual error detail (conflicts/message) instead
        of just the bare status line, which raise_for_status() alone gives.

        DHIS2's error JSON shape varies by endpoint and version — bulk
        import endpoints (POST /events) nest conflicts under
        response.importSummaries[].conflicts, while single-resource
        endpoints (PUT /events/{id}) often use response.errorReports,
        response.response.errorReports (double-nested), or
        validationReport.errorReports instead. This checks all of them and
        always logs the full raw body, so nothing is silently dropped even
        if some future shape isn't explicitly handled below.
        """
        if r.ok:
            return
        log = logging.getLogger(__name__)
        detail = ""
        body = None
        try:
            body = r.json()
        except ValueError:
            detail = (r.text or "")[:500]

        if body is not None:
            if isinstance(body, dict):
                parts = []
                msg = body.get("message")
                if msg:
                    parts.append(msg)

                def _collect_conflicts(node, parts):
                    if not isinstance(node, dict):
                        return
                    for key in ("conflicts", "errorReports"):
                        for c in node.get(key, []) or []:
                            if isinstance(c, dict):
                                text = c.get("value") or c.get("message") or c
                                obj = c.get("object", c.get("errorCode", ""))
                                parts.append(f"{obj}: {text}" if obj else str(text))
                            else:
                                parts.append(str(c))
                    summaries = node.get("importSummaries") or []
                    for s in summaries:
                        if s.get("description"):
                            parts.append(s["description"])
                        _collect_conflicts(s, parts)
                    if node.get("description") and node.get("description") not in parts:
                        parts.append(node["description"])

                # Check every nesting depth DHIS2 versions are known to use:
                # top-level, response, response.response, validationReport
                for node in (
                    body,
                    body.get("response"),
                    (body.get("response") or {}).get("response")
                    if isinstance(body.get("response"), dict) else None,
                    body.get("validationReport"),
                ):
                    _collect_conflicts(node, parts)

                detail = " | ".join(dict.fromkeys(parts)) if parts else json.dumps(body)[:800]
            else:
                detail = str(body)[:500]

        log.debug(f"DHIS2 error response body for {r.url}: "
                  f"{json.dumps(body)[:2000] if body is not None else r.text[:2000]}")
        raise requests.exceptions.HTTPError(
            f"{r.status_code} {r.reason} for url {r.url} — {detail}", response=r
        )

    def get(self, path: str, params: dict = None) -> dict:
        url = f"{self.server}/api/{path}"
        r = self.session.get(url, params=params)
        self._raise_with_detail(r)
        return r.json()

    def post(self, path: str, payload: dict) -> dict:
        url = f"{self.server}/api/{path}"
        r = self.session.post(url, json=payload)
        self._raise_with_detail(r)
        return r.json()

    def put(self, path: str, payload: dict) -> dict:
        url = f"{self.server}/api/{path}"
        r = self.session.put(url, json=payload)
        self._raise_with_detail(r)
        return r.json()

    def get_teis(self, program: str, ou: Optional[str] = None,
                 tei_uid: Optional[str] = None,
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None) -> list:
        """Fetch TEIs enrolled in given program."""
        params = {
            "program": program,
            "ouMode": "ALL" if not ou else "SELECTED",
            "fields": "trackedEntityInstance,orgUnit,attributes[attribute,value]",
            "pageSize": 1000,
        }
        if ou:
            params["ou"] = ou
        if tei_uid:
            params["trackedEntityInstance"] = tei_uid
        if start_date:
            params["programStartDate"] = start_date
        if end_date:
            params["programEndDate"] = end_date

        all_teis = []
        page = 1
        while True:
            params["page"] = page
            data = self.get("trackedEntityInstances.json", params)
            teis = data.get("trackedEntityInstances", [])
            all_teis.extend(teis)
            pager = data.get("pager", {})
            page_count = pager.get("pageCount", 1)
            if page >= page_count or not teis:
                break
            page += 1
        return all_teis

    def get_enrollment(self, tei: str, program: str) -> Optional[dict]:
        """Get enrollment record for a TEI in a program.

        ouMode=ALL is required here: DHIS2's /api/enrollments.json rejects
        the request with a 409 ("At least one organisation unit must be
        specified") if neither ou nor ouMode is set, even when the query is
        already fully scoped by trackedEntityInstance + program.
        """
        params = {"trackedEntityInstance": tei, "program": program,
                  "ouMode": "ALL",
                  "fields": "enrollment,enrollmentDate,incidentDate,status,orgUnit"}
        data = self.get("enrollments.json", params)
        enrollments = data.get("enrollments", [])
        return enrollments[0] if enrollments else None

    def get_events(self, program: str, stage: str, tei: str) -> list:
        """Get all events for a program stage for a TEI.

        ouMode=ALL for the same reason as get_enrollment: this DHIS2
        instance rejects program/programStage/trackedEntityInstance-only
        queries with a 409 unless ou or ouMode is also set.
        """
        params = {
            "program": program,
            "programStage": stage,
            "trackedEntityInstance": tei,
            "ouMode": "ALL",
            "fields": "event,status,program,programStage,enrollment,"
                      "trackedEntityInstance,orgUnit,eventDate,"
                      "dataValues[dataElement,value]",
            "pageSize": 500,
        }
        data = self.get("events.json", params)
        return data.get("events", [])

    def update_event(self, event: dict, dry_run: bool = False) -> dict:
        if dry_run:
            return {"status": "DRY_RUN", "event": event.get("event")}
        return self.put(f"events/{event['event']}", event)

    def create_event(self, event: dict, dry_run: bool = False) -> dict:
        if dry_run:
            return {"status": "DRY_RUN"}
        return self.post("events", event)

    def update_tei(self, tei_payload: dict, dry_run: bool = False) -> dict:
        uid = tei_payload["trackedEntityInstance"]
        if dry_run:
            return {"status": "DRY_RUN", "tei": uid}
        return self.put(f"trackedEntityInstances/{uid}", tei_payload)


# ─────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────

def events_to_de_map(events: list) -> dict:
    """Return {de_uid: value} from the FIRST event (non-repeatable use)."""
    if not events:
        return {}
    dv = events[0].get("dataValues", [])
    return {d["dataElement"]: d["value"] for d in dv}


def events_to_de_list(events: list) -> list[dict]:
    """Return list of {de_uid: value} dicts, one per event, sorted by eventDate."""
    sorted_events = sorted(events, key=lambda e: e.get("eventDate", ""))
    return [{d["dataElement"]: d["value"] for d in e.get("dataValues", [])} for e in sorted_events]


def get_de_value_across_events(events: list, de_uid: str) -> list:
    """Return all non-null values of a DE across all events."""
    values = []
    for ev in events:
        for dv in ev.get("dataValues", []):
            if dv["dataElement"] == de_uid and dv.get("value") not in (None, ""):
                values.append(dv["value"])
    return values


def first_value_across_events(events: list, de_uid: str) -> Optional[str]:
    """Return the first non-empty value of a DE across all events of a
    stage, in event order. For a non-repeatable stage there's at most one
    event anyway, so this is equivalent to reading that one event. For a
    repeatable stage, this is the correct "find wherever it actually is"
    behavior — unlike reading only the chronologically-first event, which
    would silently miss a value recorded on a later event of the same
    stage (e.g. an antibiotic, or its date/time, entered on a 2nd or 3rd
    Medication and Intervention event rather than the 1st)."""
    values = get_de_value_across_events(events, de_uid)
    return values[0] if values else None


def last_value_across_events(events: list, de_uid: str) -> Optional[str]:
    """Return the LAST non-empty value of a DE across all events of a
    stage, in event order. Used for fields like "IV Fluids (Last) End
    date", where NID wants the most recent occurrence rather than the
    first — as opposed to "IV Fluids (First) Start date", which wants
    first_value_across_events instead."""
    values = get_de_value_across_events(events, de_uid)
    return values[-1] if values else None


def aggregate_max(values: list) -> Optional[str]:
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (ValueError, TypeError):
            pass
    return str(max(nums)) if nums else None


def aggregate_min(values: list) -> Optional[str]:
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (ValueError, TypeError):
            pass
    return str(min(nums)) if nums else None


def event_with_extreme(events: list, de_uid: str, want_max: bool) -> Optional[dict]:
    """Return the single event whose de_uid value is the highest (want_max
    =True) or lowest (want_max=False) numeric value across all events, or
    None if no event has a usable numeric value for that DE.

    This is the building block for "highest/lowest X, and what date/time/
    unit was it recorded" fields (e.g. OBS_NURSING_2's highest/lowest
    temperature, oxygen saturation, blood sugar, bilirubin) — aggregate_max/
    aggregate_min alone only return the bare value, not which event (and
    therefore which date, time, or unit) it came from.
    """
    best_event = None
    best_num = None
    for ev in events:
        for dv in ev.get("dataValues", []):
            if dv["dataElement"] != de_uid:
                continue
            val = dv.get("value")
            if val in (None, ""):
                continue
            try:
                num = float(val)
            except (ValueError, TypeError):
                continue
            if best_num is None or (num > best_num if want_max else num < best_num):
                best_num = num
                best_event = ev
    return best_event


def count_matching(events: list, de_uid: str, match_value) -> int:
    """Count events where de_uid's value matches match_value. match_value
    can be a single value or a tuple/list of values to match any of (e.g.
    transfusion has two distinct "Yes" codes — 1=Blood transfusion and
    2=Exchange blood transfusion — both of which should count toward
    "how many times was a transfusion given")."""
    match_values = {str(v) for v in match_value} if isinstance(match_value, (tuple, list)) else {str(match_value)}
    count = 0
    for ev in events:
        for dv in ev.get("dataValues", []):
            if dv["dataElement"] == de_uid and str(dv.get("value", "")) in match_values:
                count += 1
    return count


def multi_text_contains(multi_val: str, option_code: str) -> bool:
    """Check if a MULTI_TEXT value contains a given option code."""
    if not multi_val:
        return False
    # DHIS2 MULTI_TEXT values are comma-separated option codes
    codes = [c.strip() for c in multi_val.split(",")]
    return option_code in codes


def split_datetime(value: str, part: str) -> Optional[str]:
    """Split a DHIS2 DATETIME value (ISO 8601, e.g.
    '2026-06-15T14:30:00.000') into its 'date' (YYYY-MM-DD) or 'time'
    (HH:MM) component. DHIS2 stores DATETIME values in UTC, while the
    NID program records times in local time (UTC+3, Ethiopia) — so the
    returned date/time reflects that 3-hour shift. Used for NCF fields
    that store one combined date+time value where NID expects separate
    DATE and TIME fields."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        # Fallback for any non-standard formatting DHIS2 might return
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", value)
        if not m:
            return None
        dt = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:00+00:00")
    # Naive values are UTC in DHIS2; convert to local time (UTC+3)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone(timedelta(hours=3)))
    return dt.strftime("%Y-%m-%d") if part == "date" else dt.strftime("%H:%M")


def build_dv(de_uid: str, value: Any) -> dict:
    return {"dataElement": de_uid, "value": str(value)}


def create_nid_tei(client: DHIS2Client, ncf_tei_uid: str, ncf_org_unit: str,
                    ncf_attrs: dict, dry_run: bool = False) -> Optional[str]:
    """Create a brand-new NID tracked entity instance + enrollment for an
    NCF record that has no existing NID counterpart.

    The NID program has 5 MANDATORY tracked entity attributes at enrollment
    (confirmed in metadata_V3.json: programTrackedEntityAttributes with
    mandatory=true) — First Name, Last Name, Sex, Date of Birth, and Record
    ID. All five must be set on creation or DHIS2 returns 409.

    First Name, Last Name, Sex, and Record ID come from the NCF TEI's
    attributes via TEA_MAPPING. Date of Birth is different: its NCF source
    (vKsjdwDyJhC, "Date of delivery") is a DATA ELEMENT on the NICU
    Admission Careform event, not a tracked entity attribute, so it's
    fetched separately from that event here.

    Returns the new NID TEI UID, or None if creation failed (always None in
    dry-run, since nothing is actually written and no real UID exists yet).
    """
    log = logging.getLogger(__name__)

    attributes = []
    missing_mandatory = []
    for ncf_attr_uid, nid_attr_uid in TEA_MAPPING:
        val = ncf_attrs.get(ncf_attr_uid)
        if val is not None and val != "":
            attributes.append({"attribute": nid_attr_uid, "value": val})
        else:
            missing_mandatory.append(nid_attr_uid)

    # Date of Birth — sourced from the NCF event data element, not a TEA
    dob_events = client.get_events(NCF_PROGRAM, NCF_STAGE[NCF_DOB_STAGE], ncf_tei_uid)
    dob_val = None
    if dob_events:
        for dv in dob_events[0].get("dataValues", []):
            if dv["dataElement"] == NCF_DOB_DE and dv.get("value") not in (None, ""):
                dob_val = dv["value"]
                break
    if dob_val:
        attributes.append({"attribute": NID_DOB_TEA, "value": dob_val})
    else:
        missing_mandatory.append(NID_DOB_TEA)

    if missing_mandatory:
        log.warning(
            f"NCF TEI {ncf_tei_uid} is missing source value(s) for mandatory "
            f"NID attribute(s) {missing_mandatory} — creation will likely be "
            f"rejected by DHIS2 (409) unless these are optional on your server."
        )

    # Use NCF enrollment date instead of today, so the synced TEI preserves
    # the original enrollment date from source.
    ncf_enroll = client.get_enrollment(ncf_tei_uid, NCF_PROGRAM)
    if ncf_enroll:
        enr_date = ncf_enroll.get("enrollmentDate", datetime.today().strftime("%Y-%m-%d"))
        inc_date = ncf_enroll.get("incidentDate", enr_date)
        ncf_enroll_status = ncf_enroll.get("status", "ACTIVE")
    else:
        enr_date = datetime.today().strftime("%Y-%m-%d")
        inc_date = enr_date
        ncf_enroll_status = "ACTIVE"

    tei_payload = {
        "trackedEntityType": NID_TRACKED_ENTITY_TYPE,
        "orgUnit": ncf_org_unit,
        "attributes": attributes,
        "enrollments": [
            {
                "program": NID_PROGRAM,
                "orgUnit": ncf_org_unit,
                "enrollmentDate": enr_date,
                "incidentDate": inc_date,
                "status": ncf_enroll_status,
            }
        ],
    }

    record_id_key = ncf_attrs.get("Xam97lYmJB7")

    if dry_run:
        log.info(f"[DRY RUN] Would create new NID TEI for key={record_id_key} "
                 f"(source NCF TEI {ncf_tei_uid})")
        return None

    result = client.post("trackedEntityInstances", tei_payload)
    try:
        new_uid = result["response"]["importSummaries"][0]["reference"]
    except (KeyError, IndexError):
        log.error(f"Could not determine new NID TEI UID from response: {result}")
        return None
    log.info(f"Created new NID TEI {new_uid} for key={record_id_key}")
    return new_uid


def get_or_create_nid_tei(client: DHIS2Client, nid_lookup: dict, ncf_tei: dict,
                           dry_run: bool = False) -> tuple[Optional[str], str]:
    """The single rule that decides update vs. create for a given NCF record:

        Record ID exists in NID  → use that NID TEI (sync_tei will UPDATE it)
        Record ID not in NID     → create a new NID TEI (sync_tei then fills it in)

    This is a direct dict lookup by Record ID — not a fuzzy or optional
    "matching" step. Record ID (NCF: Xam97lYmJB7, NID: UGwDTPoObkT) is the
    unique identifier on both sides; if it's present in nid_lookup the
    record is updated, otherwise it's created. The only case this can't
    resolve is an NCF record with no Record ID value at all, since there is
    then nothing to look up or assign on creation.

    Returns (nid_tei_uid, outcome) where outcome is one of:
        "updated_existing", "created_new", "no_record_id", "create_failed"
    nid_tei_uid is None for "no_record_id" and (in dry-run only) "created_new".
    """
    log = logging.getLogger(__name__)
    ncf_uid = ncf_tei["trackedEntityInstance"]
    attrs = {a["attribute"]: a["value"] for a in ncf_tei.get("attributes", [])}
    record_id = attrs.get("Xam97lYmJB7")

    # Mekelle offset: shift Record ID to avoid colliding with existing NID
    # Record ID space. Check both org unit and MKG prefix because the
    # DHIS2 list endpoint and single-TEI endpoint can return different
    # orgUnit values for the same TEI.
    m_offset = re.match(r"^([A-Za-z]+)(\d+)$", record_id or "")
    if m_offset and (ncf_tei.get("orgUnit") == "xKpOsRLDIsG" or m_offset.group(1) == "MKG"):
        prefix = m_offset.group(1)
        seq = int(m_offset.group(2)) + 300
        shifted = f"{prefix}{seq:010d}"
        attrs["Xam97lYmJB7"] = shifted
        record_id = shifted

    if not record_id:
        log.warning(f"NCF TEI {ncf_uid} has no Neonate record ID (Xam97lYmJB7) "
                   f"value — cannot update or create. Skipping.")
        return None, "no_record_id"

    existing_nid_uid = nid_lookup.get(record_id)
    if existing_nid_uid:
        return existing_nid_uid, "updated_existing"

    log.info(f"Record ID {record_id} not found in NID (NCF TEI {ncf_uid}) — creating new NID record.")
    ncf_org_unit = ncf_tei.get("orgUnit")
    new_uid = create_nid_tei(client, ncf_uid, ncf_org_unit, attrs, dry_run=dry_run)
    if not new_uid:
        return None, "created_new" if dry_run else "create_failed"
    return new_uid, "created_new"



def get_or_init_nid_event(client: DHIS2Client, nid_tei: str,
                           nid_enroll: dict, stage_key: str,
                           status: str = "ACTIVE") -> dict:
    """Same rule as get_or_create_nid_tei, applied at the event level:
    an event already exists for this NID TEI + stage → it's returned as-is
    and will be UPDATED (its "event" ID is set, so the save step in
    sync_tei calls update_event); no event exists yet → a blank skeleton
    (no "event" ID) is returned and will be CREATED instead."""
    stage_uid = NID_STAGE[stage_key]
    events = client.get_events(NID_PROGRAM, stage_uid, nid_tei)
    if events:
        return events[0]
    # skeleton — no "event" key, so the save step creates rather than updates
    return {
        "program": NID_PROGRAM,
        "programStage": stage_uid,
        "trackedEntityInstance": nid_tei,
        "enrollment": nid_enroll["enrollment"],
        "orgUnit": nid_enroll["orgUnit"],
        "eventDate": datetime.today().strftime("%Y-%m-%d"),
        "status": status,
        "dataValues": [],
    }


def upsert_dv(event: dict, de_uid: str, value: str):
    """Add or update a dataValue in an event dict."""
    if value is None or value == "":
        return
    for dv in event["dataValues"]:
        if dv["dataElement"] == de_uid:
            dv["value"] = str(value)
            return
    event["dataValues"].append({"dataElement": de_uid, "value": str(value)})


def known_value_for(nid_de: str) -> str:
    """The correct "is known/recorded/documented?" value for a NID data
    element, based on its real DHIS2 value type:
      - genuine BOOLEAN fields (TIME_KNOWN_BOOLEAN_DES) → "true"
      - coded TEXT fields with a 1=Yes/0=No option set (the majority) → "1"
    Using "true" on a coded TEXT field is rejected by DHIS2 with a 409
    ("not a valid option code") — this is what previously failed for
    kvJUcoHhx7f and would have failed identically for the other ~11 coded
    fields using the same TIME_KNOWN/REPEATABLE_SLOT transform.
    """
    return "true" if nid_de in TIME_KNOWN_BOOLEAN_DES else "1"


# ─────────────────────────────────────────────────────────────────
# KMC SLOT ARRAYS  (NID Interventions, up to 30 days)
# Index 0 = day 1, index 1 = day 2, ..., index 29 = day 30.
# These parallel the KMC initiation date / time / duration-in-24h
# columns in the NID INTERVENTIONS stage, confirmed from metadata_New.json.
# ─────────────────────────────────────────────────────────────────
KMC_DATE_SLOTS = [
    "OnCDZXEjrwV","A5iZWIhlSqW","LRiVmI5wqRa","mEoG9c40Jrr","Qq0VgpxChXh",
    "erewhtdMwfb","E6hvOR2kYH7","bhcuoFLGZqM","ATuR4ViRQ2H","irrxtVSmmE9",
    "UYhjrjHPZfy","qeU5FmYmPEB","Vt5wtR0hB7Y","kL45yZXjNna","iLfWZJfGfHI",
    "qAVYBw3yzUG","saX6RSdKlHS","nC9dIsfGaOE","ShM1ch4zBee","erlFhfDjPJr",
    "PZhxgtWBR7T","bRuNtmHqHty","M7z9n8eFRAt","mPiovlkihfL","wugnYAxxLGY",
    "zPO9RcK2o3p","YqZaZ8NztxZ","Z5avWspzkEA","GFkAsGBLXvt","Q67YHq5e3UW",
]
KMC_TIME_SLOTS = [
    "aKsCUxJw5bo","QnYKXKx0XX3","DZl502Rm8yu","oXzRWo3fRZp","QKuj0kPUMNh",
    "PXNIU9Ek41N","avOXTcKozzu","TjkGM4AMF1Z","I4s4i4HECpB","SYovJjk0QH3",
    "zPFT0LJsiRd","WMaX3Z5ZRi5","xNNxZZlZP1W","biFK2G18qAK","gmV9ffU5Edz",
    "CKcqJ1hBC26","p7hZgLIWLmH","Ly2js95DwDR","tO8qR4c7VXX","fQTHtKNUTVk",
    "YHfon72yU5n","sJPPhyHJ78Y","oX6Assvcyo4","WU0WN5DBIlW","xl8hg4Q2wX4",
    "pmQlur6kLqg","xKVwiyzatWd","OILDTKIpuBK","AId8dRWMdgz","esehwMfonTq",
]
KMC_DUR_SLOTS = [
    "zFE3w3cbK0Z","eOeBqVvucAv","gmNv5Bzl9ko","z2vMXEcn6h1","RqAjetChbZJ",
    "mzbWxGpu72S","TjfAcnUrJQz","l26q2hDjVqo","hFoNbgUnYnX","E14apY9Y5JP",
    "DPYhpPzao89","dPgftrvdJiW","YmFq04GAqFn","FGI37WcvVcF","bXmPylVbJgg",
    "T3QRxB7QrJU","oo9WWr9oy1X","ZJYN6gWUYtL","gjVLJ3mIzEn","H2prcyRcSHl",
    "T8utCEOopdl","OVEVzW4YzIO","aklVXFDFu5V","GHQiw4cnSYX","wWZTWmNq3dV",
    "NWydKst4Xny","uGHk7Q90fDN","Z51Bgg35MGA","mSwCXarZMHl","yQ2i6DKNXDg",
]
# NCF source field UIDs within KMC_FOLLOWUP stage
KMC_NCF_INITIATION_DATE = "OnCDZXEjrwV"  # KMC initiation date (per-event)
KMC_NCF_INITIATION_TIME = "aKsCUxJw5bo"  # KMC initiation time (per-event)
KMC_NCF_DURATION        = "uWBdtn6RI6G"  # Total KMC hours/day (per-event)
NCF_KMC_TYPE_PRACTISED  = "tDfQAEzX4dS"  # Type of KMC Practised (per-event)
# NID target UIDs in INTERVENTIONS stage
NID_KMC_INITIATED       = "OKpb4PwIIIw"
NID_KMC_ADMINISTERED    = "QK7Fi6OwtDC"
NID_KMC_START_DATE      = "JxGlnPychB0"
NID_KMC_END_DATE        = "MTvAG4BV7Ne"
NID_KMC_CONTINUOUS      = "D891xeX6TRO"
NID_KMC_INTERMITTENT    = "aVBqUrLEpkz"
NID_KMC_NOT_RECORDED    = "tGDZgz2aIXO"
NID_KMC_NICU_DAYS       = "PizoI3THBAU"
# Direct Breastfeeding DE UIDs (KMC_FOLLOWUP / INTERVENTIONS)
NID_DIRECT_BF_INITIATED  = "rY2AyttwMBx"
NID_DIRECT_BF_START_DATE = "Yq5CmY68qhL"
NID_DIRECT_BF_START_TIME = "MIERkrJWxUU"
NID_BF_INITIATION_TIME   = "DsF9JOVYfwM"
# Breast Milk Feeding DE UIDs (KMC_FOLLOWUP / INTERVENTIONS)
NID_BM_BF_INITIATED      = "vG3ynuhlFvr"
NID_BM_BF_START_DATE     = "RSlquOUbjiA"
NID_BM_BF_START_TIME     = "bMOuGjtvmMk"
NID_BM_BF_TIME_ALT       = "eTfFcAx4rD3"
# Source fields for NICU days computation (date fields from NCF only)
NCF_ADMISSION_DATE_DE    = "PadsjZCM10U"  # "Date of Admission" (NCF NICU_ADMISSION)
NCF_DISCHARGE_DATETIME_DE = "VNV2QYQpebO"  # "Date and time of discharge" DATETIME (NCF DISCHARGE_CARE)


def sync_kmc(ncf_events: dict, nid_evt: dict):
    """Populate the KMC section of the NID INTERVENTIONS event.

    All inputs come from NCF only:
    - KMC_FOLLOWUP events: initiation date, time, and duration per day
    - NICU_ADMISSION: admission date (PadsjZCM10U)
    - DISCHARGE_CARE: discharge datetime (VNV2QYQpebO, date portion only)

    Logic:
    1. Is KMC initiated / administered? = Yes (1) if KMC ward followup has ≥1 event, else No (0).
    2. KMC Start Date = initiation date of 1st KMC_FOLLOWUP event.
    3. KMC End Date = initiation date of last KMC_FOLLOWUP event.
    4. NICU days = discharge_date − admission_date in calendar days
       (written to PizoI3THBAU), capped at 30 available slots.
    5. For each day index 0..nicu_days-1:
         day_date = admission_date + index days
         Look for a KMC ward followup event whose eventDate == day_date.
         If found  → write KMC initiation date, time, and duration into slot[index].
         If not found → write duration 0 into slot[index] (date/time left blank).
    """
    log = logging.getLogger(__name__)

    kmc_evs = ncf_events.get("KMC_FOLLOWUP", [])

    # ── Step 1: Is KMC initiated / administered? ──
    initiated = len(kmc_evs) > 0
    upsert_dv(nid_evt, NID_KMC_INITIATED, "1" if initiated else "0")
    upsert_dv(nid_evt, NID_KMC_ADMINISTERED, "1" if initiated else "0")
    if not initiated:
        log.debug("KMC: no KMC ward followup events — KMC not initiated")
        return

    # ── Step 1b: Populate KMC Start Date and End Date ──
    sorted_kmc_evs = sorted(kmc_evs, key=lambda e: e.get("eventDate", ""))
    init_dates = []
    for ev in sorted_kmc_evs:
        dv_map = {dv["dataElement"]: dv["value"] for dv in ev.get("dataValues", [])}
        d_val = dv_map.get(KMC_NCF_INITIATION_DATE) or (ev.get("eventDate", "")[:10] if ev.get("eventDate") else None)
        if d_val:
            init_dates.append(d_val[:10])

    if init_dates:
        upsert_dv(nid_evt, NID_KMC_START_DATE, init_dates[0])
        upsert_dv(nid_evt, NID_KMC_END_DATE, init_dates[-1])

    # ── Step 1c: Type of KMC Practised ──
    # Check across ALL KMC_FOLLOWUP events for option codes '1' (Continuous) and '2' (Intermittent).
    # If neither is found, check 'Not recorded' (tGDZgz2aIXO).
    kmc_type_vals = get_de_value_across_events(kmc_evs, NCF_KMC_TYPE_PRACTISED)
    has_continuous = any(multi_text_contains(v, "1") for v in kmc_type_vals)
    has_intermittent = any(multi_text_contains(v, "2") for v in kmc_type_vals)

    if has_continuous:
        upsert_dv(nid_evt, NID_KMC_CONTINUOUS, "true")
    if has_intermittent:
        upsert_dv(nid_evt, NID_KMC_INTERMITTENT, "true")
    if not has_continuous and not has_intermittent:
        upsert_dv(nid_evt, NID_KMC_NOT_RECORDED, "true")

    # ── Step 1d: Direct Breastfeeding Initiation ──
    direct_bf_events = []
    for ev in sorted_kmc_evs:
        dv_map = {dv["dataElement"]: dv["value"] for dv in ev.get("dataValues", [])}
        if dv_map.get(NID_DIRECT_BF_INITIATED) == "1":
            direct_bf_events.append((ev, dv_map))

    if direct_bf_events:
        upsert_dv(nid_evt, NID_DIRECT_BF_INITIATED, "1")  # Yes
        ev, dv_map = direct_bf_events[0]  # earliest event
        d_val = dv_map.get(NID_DIRECT_BF_START_DATE) or (ev.get("eventDate", "")[:10] if ev.get("eventDate") else None)
        t_val = dv_map.get(NID_DIRECT_BF_START_TIME)
        if d_val:
            upsert_dv(nid_evt, NID_DIRECT_BF_START_DATE, d_val[:10])
        if t_val:
            upsert_dv(nid_evt, NID_DIRECT_BF_START_TIME, t_val)

    # Breastfeeding initiation time (DsF9JOVYfwM) from earliest event that recorded it
    for ev in sorted_kmc_evs:
        dv_map = {dv["dataElement"]: dv["value"] for dv in ev.get("dataValues", [])}
        bf_time = dv_map.get(NID_BF_INITIATION_TIME) or dv_map.get(NID_DIRECT_BF_START_TIME)
        if bf_time:
            upsert_dv(nid_evt, NID_BF_INITIATION_TIME, bf_time)
            break
    else:
        has_no = any(
            dv_map.get(NID_DIRECT_BF_INITIATED) == "0"
            for dv_map in [{dv["dataElement"]: dv["value"] for dv in ev.get("dataValues", [])} for ev in kmc_evs]
        )
        if has_no:
            upsert_dv(nid_evt, NID_DIRECT_BF_INITIATED, "0")

    # ── Step 1e: Breast Milk Feeding Initiation ──
    bm_bf_events = []
    for ev in sorted_kmc_evs:
        dv_map = {dv["dataElement"]: dv["value"] for dv in ev.get("dataValues", [])}
        if dv_map.get(NID_BM_BF_INITIATED) == "1":
            bm_bf_events.append((ev, dv_map))

    if bm_bf_events:
        upsert_dv(nid_evt, NID_BM_BF_INITIATED, "1")  # Yes
        ev, dv_map = bm_bf_events[0]  # earliest event
        d_val = dv_map.get(NID_BM_BF_START_DATE) or (ev.get("eventDate", "")[:10] if ev.get("eventDate") else None)
        t_val = dv_map.get(NID_BM_BF_START_TIME) or dv_map.get(NID_BM_BF_TIME_ALT)
        if d_val:
            upsert_dv(nid_evt, NID_BM_BF_START_DATE, d_val[:10])
        if t_val:
            upsert_dv(nid_evt, NID_BM_BF_START_TIME, t_val)
            upsert_dv(nid_evt, NID_BM_BF_TIME_ALT, t_val)
    else:
        has_no = any(
            dv_map.get(NID_BM_BF_INITIATED) == "0"
            for dv_map in [{dv["dataElement"]: dv["value"] for dv in ev.get("dataValues", [])} for ev in kmc_evs]
        )
        if has_no:
            upsert_dv(nid_evt, NID_BM_BF_INITIATED, "0")

    # Build lookup: eventDate → event data values dict (for quick access)
    kmc_by_date: dict[str, dict] = {}
    for ev in kmc_evs:
        ev_date = ev.get("eventDate", "")[:10]  # take YYYY-MM-DD part only
        if ev_date:
            dv_map = {dv["dataElement"]: dv["value"] for dv in ev.get("dataValues", [])}
            kmc_by_date[ev_date] = dv_map

    # ── Step 2: NICU days = discharge_date − admission_date ──
    # Both dates come from NCF only:
    #   Admission date: PadsjZCM10U ("Date of Admission") from NICU_ADMISSION
    #   Discharge date: VNV2QYQpebO ("Date and time of discharge", DATETIME)
    #                   from DISCHARGE_CARE — take the date portion (first 10 chars)
    nicu_adm_evs = ncf_events.get("NICU_ADMISSION", [])
    adm_date_str = None
    for ev in nicu_adm_evs:
        for dv in ev.get("dataValues", []):
            if dv["dataElement"] == NCF_ADMISSION_DATE_DE and dv.get("value"):
                adm_date_str = dv["value"][:10]
                break
        if adm_date_str:
            break

    dis_evs = ncf_events.get("DISCHARGE_CARE", [])
    dis_date_str = None
    for ev in dis_evs:
        for dv in ev.get("dataValues", []):
            if dv["dataElement"] == NCF_DISCHARGE_DATETIME_DE and dv.get("value"):
                dis_date_str = dv["value"][:10]
                break
        if dis_date_str:
            break

    nicu_days = None
    if adm_date_str and dis_date_str:
        try:
            from datetime import date as _date
            adm = _date.fromisoformat(adm_date_str)
            dis = _date.fromisoformat(dis_date_str)
            nicu_days = max(0, (dis - adm).days)
        except ValueError as e:
            log.warning(f"KMC: cannot parse admission/discharge dates "
                        f"({adm_date_str}, {dis_date_str}): {e}")
    else:
        if not adm_date_str:
            log.warning("KMC: admission date not found in NCF — cannot compute NICU days; "
                        "filling slots in KMC event order instead")
        if not dis_date_str:
            log.warning("KMC: discharge date not found in NCF — cannot compute NICU days; "
                        "filling slots in KMC event order instead")

    max_slots = len(KMC_DATE_SLOTS)  # 30

    # ── Step 3: Populate per-day slots ──
    if nicu_days is not None:
        days_to_fill = min(nicu_days, max_slots)
        # INTEGER_POSITIVE rejects 0 — only write when there is a
        # positive number of NICU days
        if nicu_days > 0:
            upsert_dv(nid_evt, NID_KMC_NICU_DAYS, str(nicu_days))
        log.debug(f"KMC: NICU days={nicu_days}, filling {days_to_fill} slots")

        from datetime import date as _date, timedelta
        adm = _date.fromisoformat(adm_date_str)

        for i in range(days_to_fill):
            day_date = (adm + timedelta(days=i)).isoformat()
            ev_data = kmc_by_date.get(day_date)

            if ev_data:
                # KMC session was recorded for this calendar day
                init_date = ev_data.get(KMC_NCF_INITIATION_DATE)
                init_time = ev_data.get(KMC_NCF_INITIATION_TIME)
                duration  = ev_data.get(KMC_NCF_DURATION)
                if init_date:
                    upsert_dv(nid_evt, KMC_DATE_SLOTS[i], init_date)
                if init_time:
                    upsert_dv(nid_evt, KMC_TIME_SLOTS[i], init_time)
                if duration is not None:
                    upsert_dv(nid_evt, KMC_DUR_SLOTS[i], str(duration))
                else:
                    upsert_dv(nid_evt, KMC_DUR_SLOTS[i], "0")
            else:
                # No KMC session recorded for this day — duration = 0
                upsert_dv(nid_evt, KMC_DUR_SLOTS[i], "0")
    else:
        # Dates not available — fall back to filling slots in KMC event
        # order (sorted by eventDate), without the day-by-day date mapping
        sorted_kmc = sorted(kmc_evs, key=lambda e: e.get("eventDate", ""))
        for i, ev in enumerate(sorted_kmc[:max_slots]):
            dv_map = {dv["dataElement"]: dv["value"] for dv in ev.get("dataValues", [])}
            init_date = dv_map.get(KMC_NCF_INITIATION_DATE)
            init_time = dv_map.get(KMC_NCF_INITIATION_TIME)
            duration  = dv_map.get(KMC_NCF_DURATION)
            if init_date:
                upsert_dv(nid_evt, KMC_DATE_SLOTS[i], init_date)
            if init_time:
                upsert_dv(nid_evt, KMC_TIME_SLOTS[i], init_time)
            upsert_dv(nid_evt, KMC_DUR_SLOTS[i], str(duration) if duration is not None else "0")


def sync_nicu_days(ncf_events: dict, nid_evt: dict):
    """Write "How many days did the newborn stay in the NICU?" (PizoI3THBAU).

    Independent of KMC: sync_kmc() returns early when the baby has no KMC
    ward follow-up events, which used to leave this field empty for every
    such baby. Days = discharge date − admission date (calendar days).
    Admission date: NCF "Date of Admission" (PadsjZCM10U), falling back to the
    NICU Admission event date. Discharge date: NCF "Date and time of
    discharge" (VNV2QYQpebO), falling back to the Discharge event date.
    The NID field is INTEGER_POSITIVE, so same-day stays (0 days) are skipped.
    """
    log = logging.getLogger(__name__)

    def _first_date(stage_key, de_uid):
        evs = ncf_events.get(stage_key, [])
        for ev in evs:
            for dv in ev.get("dataValues", []):
                if dv["dataElement"] == de_uid and dv.get("value"):
                    return dv["value"][:10]
        for ev in evs:
            if ev.get("eventDate"):
                return ev["eventDate"][:10]
        return None

    adm_str = _first_date("NICU_ADMISSION", NCF_ADMISSION_DATE_DE)
    dis_str = _first_date("DISCHARGE_CARE", NCF_DISCHARGE_DATETIME_DE)
    if not (adm_str and dis_str):
        log.debug("NICU days: admission or discharge date missing — not written")
        return
    try:
        days = (date.fromisoformat(dis_str) - date.fromisoformat(adm_str)).days
    except ValueError as e:
        log.warning(f"NICU days: cannot parse dates ({adm_str}, {dis_str}): {e}")
        return
    if days > 0:
        upsert_dv(nid_evt, NID_KMC_NICU_DAYS, str(days))


def sync_breast_milk_start_fallback(ncf_events: dict, nid_evt: dict):
    """Breast milk start date (NID K0YTHJ99oSo, OBS_NURSING_2).

    Primary source (MAPPING DIRECT rule): KMC ward follow-up "Date of
    initiation of breast milk feeding" (RSlquOUbjiA). When the baby has no
    KMC date, fall back to the Nurse followup Sheet "Breast milk start date"
    (K0YTHJ99oSo; same UID as the NID field).
    """
    if first_value_across_events(ncf_events.get("KMC_FOLLOWUP", []), "RSlquOUbjiA"):
        return
    val = first_value_across_events(ncf_events.get("NURSE_FOLLOWUP", []), "K0YTHJ99oSo")
    if val:
        upsert_dv(nid_evt, "K0YTHJ99oSo", val)


def sync_apnea(ncf_events: dict, nid_evt: dict):
    """Sync Apnea Prevention/Treatment section from NCF MEDICATION_INTV events to NID INTERVENTIONS event.

    NCF Source (MEDICATION_INTV stage):
    - sTJx4TskMEP: Apnea Prevention/Treatment (1=Yes, 0=No)
    - uxPFFuW9wZV: If yes - Apnea Prevention/Treatment Administered (MULTI_TEXT: 1=Caffeine, 2=Aminophylline, 3=Other)
    - bXcWI1nZTvo: If other - specify name:_apnea (TEXT)

    NID Target (INTERVENTIONS stage):
    - mJt53mee1Zv: Apnea Prevention/Treatment: (1=Yes, 0=No, -1=Not recorded)
    - qMD1iivq8wV: choice=Caffeine (TRUE_ONLY)
    - UMlpHTGmEXR: choice=Aminophylline (TRUE_ONLY)
    - DpIhz7I6EMr: choice=Other (TRUE_ONLY)
    - ryAeOjaKhIJ: choice=Not recorded (TRUE_ONLY)
    - bXcWI1nZTvo: If other - specify name:_apnea (TEXT)
    """
    log = logging.getLogger(__name__)
    med_evs = ncf_events.get("MEDICATION_INTV", [])

    apnea_vals = get_de_value_across_events(med_evs, "sTJx4TskMEP")

    if "1" in apnea_vals:
        upsert_dv(nid_evt, "mJt53mee1Zv", "1")  # Yes

        admin_vals = get_de_value_across_events(med_evs, "uxPFFuW9wZV")
        has_caffeine = any(multi_text_contains(v, "1") for v in admin_vals)
        has_aminophylline = any(multi_text_contains(v, "2") for v in admin_vals)
        has_other = any(multi_text_contains(v, "3") for v in admin_vals)

        if has_caffeine:
            upsert_dv(nid_evt, "qMD1iivq8wV", "true")
        if has_aminophylline:
            upsert_dv(nid_evt, "UMlpHTGmEXR", "true")
        if has_other:
            upsert_dv(nid_evt, "DpIhz7I6EMr", "true")
            other_name = first_value_across_events(med_evs, "bXcWI1nZTvo")
            if other_name:
                upsert_dv(nid_evt, "bXcWI1nZTvo", other_name)

        if not has_caffeine and not has_aminophylline and not has_other:
            upsert_dv(nid_evt, "ryAeOjaKhIJ", "true")  # Not recorded

    elif "0" in apnea_vals:
        upsert_dv(nid_evt, "mJt53mee1Zv", "0")  # No
    else:
        # No data recorded in NCF -> Not recorded
        log.debug("Apnea: no data in NCF — setting Not recorded")
        upsert_dv(nid_evt, "mJt53mee1Zv", "-1")  # Not recorded
        upsert_dv(nid_evt, "ryAeOjaKhIJ", "true")  # Not recorded


# ─────────────────────────────────────────────────────────────────
# MAIN SYNC LOGIC
# ─────────────────────────────────────────────────────────────────

def sync_birth_order(ncf_events: dict, mat_evt: dict):
    """Write the birth order (oHIgtGycO0F) to the NID Maternal Birth and Infant
    Details stage if the newborn is from a multiple birth.

    The separate per-multiplicity order fields were retired after 2023-09-11
    in favor of the single field oHIgtGycO0F.
    """
    ncf_evs = ncf_events.get("NICU_ADMISSION", [])
    order = first_value_across_events(ncf_evs, "oHIgtGycO0F")
    if order:
        upsert_dv(mat_evt, "oHIgtGycO0F", order)


def sync_geographic(ncf_events: dict, adm_evt: dict):
    """Fill the NID ADMISSION residence-geography fields from the NCF
    NICU Admission Careform (Region/Zone/Wereda/Kebele).

    Master flag (NID_GEO_MASTER) is Yes (1) if any of the four NCF
    source fields has a value, otherwise No (0). For each source field
    that is filled, its TRUE_ONLY check is set to "true" and (for the
    two fields not already handled by MAPPING DIRECT rules) its value
    field is written: Region → National Regional State value, Kebele →
    Address Notes/Directions. Zone and Woredas value fields are already
    synced by MAPPING DIRECT rules; only their checks are set here.
    """
    geos = {
        "region":  first_value_across_events(ncf_events.get(NID_GEO_STAGE, []), GEO_REGION_DE),
        "zone":    first_value_across_events(ncf_events.get(NID_GEO_STAGE, []), GEO_ZONE_DE),
        "wereda":  first_value_across_events(ncf_events.get(NID_GEO_STAGE, []), GEO_WEREDA_DE),
        "kebele":  first_value_across_events(ncf_events.get(NID_GEO_STAGE, []), GEO_KEBELE_DE),
    }

    any_filled = any(v not in (None, "") for v in geos.values())
    upsert_dv(adm_evt, NID_GEO_MASTER, "1" if any_filled else "0")

    if geos["region"]:
        upsert_dv(adm_evt, NID_GEO_REGION_FLAG, "true")
        upsert_dv(adm_evt, NID_GEO_REGION_VAL, geos["region"])
    if geos["zone"]:
        upsert_dv(adm_evt, NID_GEO_ZONE_FLAG, "true")
    if geos["wereda"]:
        upsert_dv(adm_evt, NID_GEO_WEREDA_FLAG, "true")
    if geos["kebele"]:
        upsert_dv(adm_evt, NID_GEO_KEBELE_FLAG, "true")
        upsert_dv(adm_evt, NID_GEO_ADDRESS_VAL, geos["kebele"])

    # MULTI_TEXT roll-up of the four checks above (option codes, comma-separated)
    doc_codes = [code for code, key in (("1", "region"), ("2", "zone"),
                                        ("3", "wereda"), ("4", "kebele"))
                 if geos[key]]
    if doc_codes:
        upsert_dv(adm_evt, NID_GEO_DOC_MULTI, ",".join(doc_codes))




# ─────────────────────────────────────────────────────────────────
# MAIN SYNC LOGIC
# ─────────────────────────────────────────────────────────────────

def sync_tei(client: DHIS2Client, ncf_tei_uid: str, nid_tei_uid: str,
             dry_run: bool = False, is_new_tei: bool = False):
    log = logging.getLogger(__name__)
    log.info(f"Syncing NCF TEI {ncf_tei_uid} → NID TEI {nid_tei_uid}"
             f"{' (newly created)' if is_new_tei else ''}")

    # ── 1. Fetch all NCF events per stage ──
    ncf_events: dict[str, list] = {}
    for key, stage_uid in NCF_STAGE.items():
        evs = client.get_events(NCF_PROGRAM, stage_uid, ncf_tei_uid)
        ncf_events[key] = evs
        log.debug(f"  NCF stage {key}: {len(evs)} events")

    # ── 2. Fetch NCF TEI attributes ──
    ncf_tei_data = client.get(
        f"trackedEntityInstances/{ncf_tei_uid}.json",
        {"fields": "trackedEntityInstance,attributes[attribute,value],orgUnit"}
    )
    ncf_attrs = {a["attribute"]: a["value"] for a in ncf_tei_data.get("attributes", [])}
    ncf_org_unit = ncf_tei_data.get("orgUnit")

    # Mekelle offset: same logic as in get_or_create_nid_tei — shift
    # the Record ID so NCF values don't collide with the NID Record ID
    # space. Check both org unit and MKG prefix for robustness.
    _raw = ncf_attrs.get("Xam97lYmJB7")
    _m = re.match(r"^([A-Za-z]+)(\d+)$", _raw or "")
    if _m and (ncf_org_unit == "xKpOsRLDIsG" or _m.group(1) == "MKG"):
        _p = _m.group(1)
        _s = int(_m.group(2)) + 300
        ncf_attrs["Xam97lYmJB7"] = f"{_p}{_s:010d}"

    # ── 3. Fetch NID enrollment ──
    nid_enroll = client.get_enrollment(nid_tei_uid, NID_PROGRAM)
    if not nid_enroll:
        log.error(f"No NID enrollment found for TEI {nid_tei_uid}. Skipping.")
        return

    # ── 4. Build NID event buffers (one per NID stage) ──
    nid_events: dict[str, dict] = {}
    for stage_key in NID_STAGE:
        ncf_source_key = NID_TO_NCF_PRIMARY.get(stage_key)
        ncf_evs = ncf_events.get(ncf_source_key, []) if ncf_source_key else []
        ncf_status = ncf_evs[0].get("status", "ACTIVE") if ncf_evs else "ACTIVE"
        nid_events[stage_key] = get_or_init_nid_event(
            client, nid_tei_uid, nid_enroll, stage_key, status=ncf_status
        )

    # ── 4b. NID-only admin fields on the ADMISSION event ──
    # Facility Name is always the record's own org unit (ORGANISATION_UNIT
    # field → value is the org unit UID). Data Officer ID/Name are filled
    # only when this org unit is present in ORG_UNIT_OFFICER_MAP.
    adm_evt = nid_events.get("ADMISSION")
    if adm_evt is not None:
        if ncf_org_unit:
            upsert_dv(adm_evt, NID_FACILITY_NAME_DE, ncf_org_unit)
        officer = ORG_UNIT_OFFICER_MAP.get(ncf_org_unit)
        if officer:
            upsert_dv(adm_evt, NID_OFFICER_ID_DE, officer[0])
            upsert_dv(adm_evt, NID_OFFICER_NAME_DE, officer[1])

    # ── 5. Process MAPPING rules ──
    for rule in MAPPING:
        nid_stage_key = rule[0]
        nid_de = rule[1]
        transform = rule[2]
        ncf_stage_key = rule[3]
        ncf_de = rule[4]

        # Skip if NID stage unknown
        if nid_stage_key not in nid_events:
            log.warning(f"Unknown NID stage key '{nid_stage_key}' — skipping rule for {nid_de}")
            continue

        nid_evt = nid_events[nid_stage_key]
        ncf_evs = ncf_events.get(ncf_stage_key, [])
        ncf_first = events_to_de_map(ncf_evs)
        ncf_all = events_to_de_list(ncf_evs)

        try:
            if transform == "DIRECT":
                val = first_value_across_events(ncf_evs, ncf_de)
                if val is not None:
                    upsert_dv(nid_evt, nid_de, val)

            elif transform == "DIRECT_OR_DEFAULT":
                # Copy value if present in NCF; if missing or empty, write default option code
                default_val = rule[5]
                val = first_value_across_events(ncf_evs, ncf_de)
                if val not in (None, ""):
                    upsert_dv(nid_evt, nid_de, val)
                else:
                    upsert_dv(nid_evt, nid_de, default_val)

            elif transform == "LAST":
                # Same as DIRECT but takes the LAST non-empty value across
                # events instead of the first — e.g. "IV Fluids (Last) End
                # date" should reflect the most recent end date recorded,
                # not the earliest event's value.
                val = last_value_across_events(ncf_evs, ncf_de)
                if val is not None:
                    upsert_dv(nid_evt, nid_de, val)

            elif transform == "CONSTANT":
                # No NCF source field — always write the fixed literal value.
                # Used for NID-only fields like Baseline/Final and
                # Retrospective/Prospective, which have no NCF equivalent and
                # are always fixed to FINAL / PROSPECTIVE for synced records.
                const_val = rule[5]
                upsert_dv(nid_evt, nid_de, const_val)

            elif transform == "TIME_KNOWN":
                # nid_de is the "is known/recorded/documented?" field.
                # ncf_de is the value field; if it has a value, write the
                # correct "known" value for nid_de's actual DHIS2 type
                # (literal "true" for real BOOLEAN fields, coded "1" for
                # the more common TEXT-with-option-set fields).
                val = first_value_across_events(ncf_evs, ncf_de)
                if val not in (None, ""):
                    upsert_dv(nid_evt, nid_de, known_value_for(nid_de))

            elif transform == "TIME_KNOWN_ELSE_NO":
                # Write "Yes" (1/true) if ncf_de has a value; write "No" (0/false) if unrecorded/empty
                val = first_value_across_events(ncf_evs, ncf_de)
                if val not in (None, ""):
                    upsert_dv(nid_evt, nid_de, known_value_for(nid_de))
                else:
                    upsert_dv(nid_evt, nid_de, "false" if nid_de in TIME_KNOWN_BOOLEAN_DES else "0")

            elif transform == "DATETIME_SPLIT":
                # ncf_de is a DHIS2 DATETIME field; rule[5] is "date" or
                # "time" — write just that component to nid_de.
                part = rule[5]
                val = first_value_across_events(ncf_evs, ncf_de)
                if val:
                    split_val = split_datetime(val, part)
                    if split_val:
                        upsert_dv(nid_evt, nid_de, split_val)

            elif transform == "DATETIME_KNOWN":
                # "Is the time of X collected?" — true/coded if the source
                # DATETIME field has any value at all (same semantics as
                # TIME_KNOWN, just named separately since the source is a
                # combined DATETIME rather than a plain value field).
                val = first_value_across_events(ncf_evs, ncf_de)
                if val not in (None, ""):
                    upsert_dv(nid_evt, nid_de, known_value_for(nid_de))

            elif transform == "VALUE_MAP":
                code_map = rule[5]
                val = first_value_across_events(ncf_evs, ncf_de)
                if val is not None:
                    mapped = code_map.get(str(val))
                    if mapped is not None:
                        upsert_dv(nid_evt, nid_de, mapped)
                    else:
                        log.warning(f"No VALUE_MAP entry for '{val}' on DE {ncf_de}")

            elif transform == "MULTI_TO_TRUE":
                # Check across ALL events of this (possibly repeatable) NCF
                # stage, not just the first — e.g. Medication and
                # Intervention is repeatable, so an antibiotic or
                # anticonvulsant could be selected on any one of several
                # events, not necessarily the first.
                option_code = rule[5]
                all_vals = get_de_value_across_events(ncf_evs, ncf_de)
                if any(multi_text_contains(v, option_code) for v in all_vals):
                    upsert_dv(nid_evt, nid_de, "true")

            elif transform == "MULTI_SELECT_MAP":
                # Map NCF multi-select options (rule[5]) to a single NID option code, else fallback (rule[6])
                code_map = rule[5]
                default_val = rule[6] if len(rule) > 6 else "-1"
                all_vals = get_de_value_across_events(ncf_evs, ncf_de)
                found_code = None
                for src_code, target_code in code_map.items():
                    if any(multi_text_contains(v, src_code) for v in all_vals):
                        found_code = target_code
                        break
                if found_code is not None:
                    upsert_dv(nid_evt, nid_de, found_code)
                else:
                    upsert_dv(nid_evt, nid_de, default_val)

            elif transform == "LOCATION_MAP":
                # Map open-text place of follow up (W6x0u5x701I) to coded appointment location (PNmWZYTAn7Q):
                # 1 = Neonatal Inpatient Unit (This Facility)
                # 2 = Neonatal Outpatient Unit (This Facility)
                # 99 = Other
                # -1 = Not recorded
                val = first_value_across_events(ncf_evs, ncf_de)
                if val:
                    val_lower = val.strip().lower()
                    if any(k in val_lower for k in ["inpatient", "in patient", "in-patient", "nicu ward", "ward"]):
                        code = "1"
                    elif any(k in val_lower for k in ["outpatient", "out patient", "out-patient", "opd", "clinic", "kmc"]):
                        code = "2"
                    else:
                        code = "99"
                else:
                    code = "-1"
                upsert_dv(nid_evt, nid_de, code)

            elif transform == "COMPUTED_PHONE":
                p1_de = ncf_de
                p2_de = rule[5]
                p1 = ncf_first.get(p1_de)
                p2 = ncf_first.get(p2_de)
                if p1 and p2:
                    upsert_dv(nid_evt, nid_de, "2")  # Two numbers
                elif p1 or p2:
                    upsert_dv(nid_evt, nid_de, "1")  # One number
                else:
                    upsert_dv(nid_evt, nid_de, "0")  # None

            elif transform == "AGGREGATE_MAX":
                values = get_de_value_across_events(ncf_evs, ncf_de)
                result = aggregate_max(values)
                if result:
                    upsert_dv(nid_evt, nid_de, result)

            elif transform == "AGGREGATE_MIN":
                values = get_de_value_across_events(ncf_evs, ncf_de)
                result = aggregate_min(values)
                if result:
                    upsert_dv(nid_evt, nid_de, result)

            elif transform == "AGGREGATE_EXTREME":
                # Find the single event with the highest/lowest value of
                # ncf_de across the repeatable stage, then pull either the
                # value itself, a "documented?" flag, the event's date, or
                # a companion field (e.g. unit, time-of-measurement) from
                # that SAME winning event — not just any event.
                #   rule[5] = "max" or "min"
                #   rule[6] = "value" | "documented" | "date" |
                #             ("time_documented", companion_de_uid) |
                #             ("value_if_unit", unit_companion_de_uid, expected_code) |
                #             <companion DE uid string>
                direction = rule[5]
                field = rule[6]
                want_max = (direction == "max")
                winner = event_with_extreme(ncf_evs, ncf_de, want_max)

                if field == "documented":
                    if winner:
                        upsert_dv(nid_evt, nid_de, known_value_for(nid_de))
                    else:
                        # Coded TEXT fields use "0" for No; genuine BOOLEAN
                        # fields use "false". known_value_for only covers
                        # the "yes" side, so handle "no" explicitly here.
                        upsert_dv(nid_evt, nid_de,
                                  "false" if nid_de in TIME_KNOWN_BOOLEAN_DES else "0")
                elif isinstance(field, tuple) and field[0] == "time_documented":
                    # "Is the TIME of the highest/lowest value recorded?" —
                    # depends on whether the companion time field has a
                    # value on the winning event, not just whether a
                    # winning event exists at all.
                    companion_de = field[1]
                    has_time = bool(winner) and any(
                        dv["dataElement"] == companion_de and dv.get("value") not in (None, "")
                        for dv in winner.get("dataValues", [])
                    )
                    upsert_dv(nid_evt, nid_de, known_value_for(nid_de) if has_time
                              else ("false" if nid_de in TIME_KNOWN_BOOLEAN_DES else "0"))
                elif winner is None:
                    pass  # no events with a usable value — nothing else to write
                elif field == "value":
                    val = next((dv["value"] for dv in winner.get("dataValues", [])
                                if dv["dataElement"] == ncf_de), None)
                    if val is not None:
                        upsert_dv(nid_evt, nid_de, val)
                elif field == "date":
                    if winner.get("eventDate"):
                        upsert_dv(nid_evt, nid_de, winner["eventDate"])
                elif isinstance(field, tuple) and field[0] == "value_if_unit":
                    # NCF stores one value + a unit flag; NID has separate
                    # fields per unit (e.g. temp °C field vs temp °F field).
                    # Only write nid_de if the winning event's unit matches
                    # the code this rule is responsible for.
                    unit_de, expected_code = field[1], field[2]
                    unit_val = next((dv["value"] for dv in winner.get("dataValues", [])
                                      if dv["dataElement"] == unit_de), None)
                    if str(unit_val) == str(expected_code):
                        val = next((dv["value"] for dv in winner.get("dataValues", [])
                                    if dv["dataElement"] == ncf_de), None)
                        if val is not None:
                            upsert_dv(nid_evt, nid_de, val)
                else:
                    # field is a companion data element UID — read it from
                    # the winning event's own dataValues
                    companion_val = next(
                        (dv["value"] for dv in winner.get("dataValues", [])
                         if dv["dataElement"] == field), None)
                    if companion_val is not None:
                        upsert_dv(nid_evt, nid_de, companion_val)

            elif transform == "COUNT_YES":
                match_val = rule[5]
                count = count_matching(ncf_evs, ncf_de, match_val)
                log.debug(f"COUNT_YES for {nid_de} (source {ncf_de}, match={match_val}): "
                         f"{len(ncf_evs)} events, count={count}")
                # Only write when count > 0: all target fields are
                # INTEGER_POSITIVE which rejects 0. The corresponding
                # "administered?" flag already records the No case.
                if count > 0:
                    upsert_dv(nid_evt, nid_de, str(count))

            elif transform == "COUNT_YES_CODED":
                # Same as COUNT_YES but maps the raw count to a coded
                # 1=Once/2=Twice/3=Three times/4=More than three scheme,
                # used by fields like "How many times did the patient
                # receive mechanical ventilation?" instead of a raw
                # INTEGER_POSITIVE value.
                match_val = rule[5]
                count = count_matching(ncf_evs, ncf_de, match_val)
                log.debug(f"COUNT_YES_CODED for {nid_de} (source {ncf_de}, match={match_val}): "
                         f"{len(ncf_evs)} events, count={count}")
                if count > 0:
                    code = str(min(count, 4))
                    upsert_dv(nid_evt, nid_de, code)

            elif transform == "REPEATABLE_SLOT":
                slot_index = rule[5]
                if slot_index is None:
                    # TIME_KNOWN variant for repeatable stage — same
                    # value-type-aware "known" value as the TIME_KNOWN
                    # transform above (see known_value_for).
                    any_val = get_de_value_across_events(ncf_evs, ncf_de)
                    if any_val:
                        upsert_dv(nid_evt, nid_de, known_value_for(nid_de))
                else:
                    # rule[6], if present, is an "anchor" data element —
                    # typically the intervention's own "administered/given
                    # = Yes" flag (e.g. Hwe1gdn1UZ4 for phototherapy,
                    # xEyz81PI8Qt for transfusion, WoGgKeuaq2K for oxygen).
                    # Slot N means "the Nth event where the anchor field
                    # equals Yes (code '1')" — matching how COUNT_YES
                    # already counts these events — and the value for
                    # nid_de is read from THAT SAME event, not from
                    # wherever ncf_de itself happens to be filled. This
                    # matters because a data collector may mark
                    # "Administered? = Yes" on one event without
                    # necessarily filling every companion field (date,
                    # time) on that exact same event versus a different
                    # one, so anchoring slot membership on the field being
                    # read (the old behavior) could pick the wrong episode
                    # or silently miss one entirely.
                    #
                    # If no anchor is given, fall back to anchoring on
                    # ncf_de itself (prior behavior), for any rule that
                    # hasn't been given an explicit anchor.
                    anchor_de = rule[6] if len(rule) > 6 else ncf_de
                    if anchor_de == ncf_de:
                        matching_events = [
                            ev for ev in ncf_all if ev.get(ncf_de) is not None
                        ]
                    else:
                        anchor_filtered = [
                            ev for ev in ncf_all if ev.get(anchor_de) == "1"
                        ]
                        # Safety net: if filtering by the anchor flag finds
                        # FEWER events with this slot's value present than
                        # filtering by the value field's own presence would,
                        # the anchor flag isn't being reliably re-marked on
                        # every event that actually carries this data (e.g.
                        # a follow-up reading recorded without re-selecting
                        # "Administered? = Yes" on that same event). In that
                        # case prefer self-anchoring instead, so a real
                        # value already in NCF is never silently dropped —
                        # which would otherwise blank out a field that had
                        # a value in a previous sync.
                        anchor_with_value = [ev for ev in anchor_filtered if ev.get(ncf_de) is not None]
                        self_filtered = [ev for ev in ncf_all if ev.get(ncf_de) is not None]
                        matching_events = anchor_filtered if len(anchor_with_value) >= len(self_filtered) else self_filtered
                    if slot_index < len(matching_events):
                        val = matching_events[slot_index].get(ncf_de)
                        if val is not None:
                            upsert_dv(nid_evt, nid_de, val)

            elif transform == "TRUE_ONLY_SLOT":
                # Set nid_de (a TRUE_ONLY field) to "true" only if ncf_de
                # has a value at this specific repeatable-stage slot index.
                # Used for "is the start/end time documented?" TRUE_ONLY
                # choice pairs, where start-time and end-time must each be
                # checked against their OWN source field independently —
                # not both keyed off whichever field happened to be
                # checked first.
                slot_index = rule[5]
                if slot_index < len(ncf_all):
                    val = ncf_all[slot_index].get(ncf_de)
                    if val is not None and val != "":
                        upsert_dv(nid_evt, nid_de, "true")

        except Exception as e:
            log.error(f"Error processing rule ({nid_stage_key}, {nid_de}, {transform}): {e}")

    # ── 5b. KMC section & Apnea section ──
    sync_nicu_days(ncf_events, nid_events["INTERVENTIONS"])
    sync_breast_milk_start_fallback(ncf_events, nid_events["OBS_NURSING_2"])
    sync_kmc(ncf_events, nid_events["INTERVENTIONS"])
    sync_apnea(ncf_events, nid_events["INTERVENTIONS"])

    # ── 5c. Residence geography (NID ADMISSION, derived from NCF) ──
    sync_geographic(ncf_events, nid_events["ADMISSION"])

    # ── 5d. Per-multiplicity birth order (NID MATERNAL, derived from NCF) ──
    sync_birth_order(ncf_events, nid_events["MATERNAL"])


    # ── 6. Update NID TEI attributes ──
    # For newly created TEIs the attributes were already set correctly
    # during creation — skip the redundant PUT to avoid DHIS2 server-side
    # validation side effects (e.g. spurious 409 "Non-unique" errors when
    # enrollment data is echoed back).
    if not is_new_tei:
        nid_tei_data = client.get(
            f"trackedEntityInstances/{nid_tei_uid}.json",
            {"fields": "trackedEntityInstance,attributes[attribute,value],orgUnit"}
        )
        updated_attrs = {a["attribute"]: a["value"] for a in nid_tei_data.get("attributes", [])}
        changed = False
        for ncf_attr_uid, nid_attr_uid in TEA_MAPPING:
            val = ncf_attrs.get(ncf_attr_uid)
            if val is not None and updated_attrs.get(nid_attr_uid) != val:
                updated_attrs[nid_attr_uid] = val
                changed = True

        # Date of Birth: NCF source is a data element on the NICU Admission
        # Careform event (vKsjdwDyJhC), not a TEI attribute — read it from the
        # already-fetched ncf_events rather than ncf_attrs.
        dob_first = events_to_de_map(ncf_events.get(NCF_DOB_STAGE, []))
        dob_val = dob_first.get(NCF_DOB_DE)
        if dob_val is not None and updated_attrs.get(NID_DOB_TEA) != dob_val:
            updated_attrs[NID_DOB_TEA] = dob_val
            changed = True

        if changed:
            tei_payload = dict(nid_tei_data)
            tei_payload["attributes"] = [{"attribute": k, "value": v} for k, v in updated_attrs.items()]
            result = client.update_tei(tei_payload, dry_run=dry_run)
            log.info(f"TEI attributes updated: {result.get('status', result)}")
    else:
        log.debug("Skipping TEI attribute update for newly created TEI")

    # ── 7. Save NID events ──
    for stage_key, evt in nid_events.items():
        if not evt.get("dataValues"):
            log.debug(f"No data values for NID stage {stage_key}, skipping")
            continue
        if evt.get("event"):
            # Update existing event — make sure the payload is structurally
            # complete (some DHIS2 versions reject a PUT that's missing
            # program/programStage/enrollment/status even though those
            # don't change) before sending it.
            evt.setdefault("program", NID_PROGRAM)
            evt.setdefault("programStage", NID_STAGE[stage_key])
            evt.setdefault("trackedEntityInstance", nid_tei_uid)
            evt.setdefault("enrollment", nid_enroll["enrollment"])
            ncf_source_key = NID_TO_NCF_PRIMARY.get(stage_key)
            ncf_evs = ncf_events.get(ncf_source_key, []) if ncf_source_key else []
            ncf_status = ncf_evs[0].get("status", "ACTIVE") if ncf_evs else "ACTIVE"
            evt["status"] = ncf_status
            result = client.update_event(evt, dry_run=dry_run)
            log.info(f"Updated NID {stage_key} event {evt['event']}: {result.get('status','ok')}")
        else:
            # Create new event
            result = client.create_event(evt, dry_run=dry_run)
            log.info(f"Created NID {stage_key} event: {result.get('status','ok')}")


def sync_all(client: DHIS2Client, ou: Optional[str] = None,
             tei_uid: Optional[str] = None,
             start_date: Optional[str] = None,
             end_date: Optional[str] = None,
             dry_run: bool = False,
             progress_callback: Optional[Any] = None,
             stop_check: Optional[Any] = None) -> dict:
    """
    Sync NCF record(s) into NID by Record ID:
        Record ID exists in NID  → update that NID record
        Record ID not in NID     → create a new NID record, then fill it in

    Record ID is NCF: Xam97lYmJB7 ↔ NID: UGwDTPoObkT, the unique identifier
    confirmed in both data dictionaries. (Registration Number, XwBOaM9MNlo,
    is a different, unrelated field that happens to share the same UID in
    both programs' metadata and must never be used here.)
    """
    log = logging.getLogger(__name__)
    log.info(f"Fetching NCF enrolled TEIs (OU={ou or 'ALL'}, {start_date or 'no start'}→{end_date or 'no end'})…")
    ncf_teis = client.get_teis(NCF_PROGRAM, ou=ou, tei_uid=tei_uid,
                               start_date=start_date, end_date=end_date)
    log.info(f"Found {len(ncf_teis)} NCF TEIs")

    log.info("Fetching NID enrolled TEIs…")
    nid_teis = client.get_teis(NID_PROGRAM, ou=ou)
    log.info(f"Found {len(nid_teis)} NID TEIs")

    # Build NID lookup: Record ID → tei_uid
    nid_lookup: dict[str, str] = {}
    nid_missing_key = 0
    for tei in nid_teis:
        attrs = {a["attribute"]: a["value"] for a in tei.get("attributes", [])}
        key = attrs.get("UGwDTPoObkT")
        if key:
            nid_lookup[key] = tei["trackedEntityInstance"]
        else:
            nid_missing_key += 1
    if nid_missing_key:
        log.warning(f"{nid_missing_key} NID TEI(s) have no Record ID (UGwDTPoObkT) value set")

    total = len(ncf_teis)
    updated = 0
    created = 0
    skipped = 0
    errors = 0

    for i, tei in enumerate(ncf_teis, 1):
        if stop_check and stop_check():
            log.info("Sync stopped by user.")
            break

        ncf_uid = tei["trackedEntityInstance"]
        pct = int(i / total * 100) if total else 100
        if progress_callback:
            progress_callback(pct, f"Processing {i}/{total} TEIs…", {
                "updated": updated, "created": created, "skipped": skipped, "errors": errors
            })

        nid_uid, outcome = get_or_create_nid_tei(client, nid_lookup, tei, dry_run=dry_run)

        if outcome == "no_record_id":
            skipped += 1
            if progress_callback:
                progress_callback(pct, f"Skipped (no record ID) {i}/{total}", {
                    "updated": updated, "created": created, "skipped": skipped, "errors": errors
                })
            continue

        if outcome == "create_failed":
            log.error(f"Failed to create NID TEI for {ncf_uid}")
            errors += 1
            if progress_callback:
                progress_callback(pct, f"Failed create {i}/{total}", {
                    "updated": updated, "created": created, "skipped": skipped, "errors": errors
                })
            continue

        if outcome == "created_new" and nid_uid is None:
            # dry-run: nothing was actually created, so there's no real
            # NID TEI to sync data into yet
            log.info(f"[DRY RUN] Skipping data sync for {ncf_uid} (new NID TEI not actually created)")
            created += 1
            if progress_callback:
                progress_callback(pct, f"Dry-run created {i}/{total}", {
                    "updated": updated, "created": created, "skipped": skipped, "errors": errors
                })
            continue

        try:
            sync_tei(client, ncf_uid, nid_uid, dry_run=dry_run,
                     is_new_tei=(outcome == "created_new"))
            if outcome == "updated_existing":
                updated += 1
            else:
                created += 1
            if progress_callback:
                progress_callback(pct, f"Processed {i}/{total}", {
                    "updated": updated, "created": created, "skipped": skipped, "errors": errors
                })
        except Exception as e:
            log.error(f"Failed syncing NCF {ncf_uid} → NID {nid_uid}: {e}", exc_info=False)
            errors += 1
            if progress_callback:
                progress_callback(pct, f"Error on {i}/{total}", {
                    "updated": updated, "created": created, "skipped": skipped, "errors": errors
                })

    log.info(
        f"Sync complete. Updated: {updated}, Created: {created}, "
        f"Skipped (no Record ID): {skipped}, Errors: {errors}"
    )

    return {
        "status": "completed",
        "total": total,
        "updated": updated,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }



