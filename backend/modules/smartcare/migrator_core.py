"""
SmartCare to OpenMRS 3.x Migration Engine
Handles data transformations, MRN generation with Luhn check-digit,
UUID normalization, birthdate parsing, and OpenMRS REST API integration.
"""

import csv
import json
import re
import datetime
import requests
from typing import Dict, Any, List, Optional, Tuple

class SmartcareOpenmrsMigrator:
    # OpenMRS Identifier Type UUID for MRN
    DEFAULT_MRN_TYPE_UUID = "e0de71c6-9836-4414-bf87-7569e6945d02"
    DEFAULT_LEGACY_ID_TYPE_UUID = "22348099-3873-459e-a32e-d93b17eda533"
    
    # OpenMRS Person Attribute Type UUID for Telephone Number
    DEFAULT_PHONE_ATTR_UUID = "14d4f066-15f5-102d-96e4-000c29c2a5d7"

    def __init__(self, base_url: str = "http://localhost/openmrs", username: str = "admin", password: str = ""):
        self.base_url = base_url.rstrip("/")
        self.rest_url = f"{self.base_url}/ws/rest/v1"
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.auth = (self.username, self.password)
        self.cached_locations: List[Dict[str, Any]] = []
        self.cached_id_types: List[Dict[str, Any]] = []
        self.cached_attr_types: List[Dict[str, Any]] = []

    def set_credentials(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.rest_url = f"{self.base_url}/ws/rest/v1"
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.auth = (self.username, self.password)

    @staticmethod
    def calculate_luhn_check_digit(number_str: str) -> int:
        """
        Calculates standard Luhn (mod 10) check digit matching
        OpenMRS org.openmrs.patient.impl.LuhnIdentifierValidator.
        """
        digits = [int(d) for d in str(number_str) if d.isdigit()]
        if not digits:
            return 0
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 0:
                doubled = d * 2
                total += (doubled // 10) + (doubled % 10)
            else:
                total += d
        mod = total % 10
        return (10 - mod) % 10

    @staticmethod
    def format_mrn(patient_id: str) -> str:
        """
        Pads patient_id to 6 digits and appends hyphen + Luhn check digit.
        Format: \\d{6}-\\d (e.g., 162989 -> 162989-8)
        """
        clean_id = re.sub(r'[^0-9]', '', str(patient_id or ''))
        padded = clean_id.zfill(6)
        check_digit = SmartcareOpenmrsMigrator.calculate_luhn_check_digit(padded)
        return f"{padded}-{check_digit}"

    @staticmethod
    def normalize_uuid(guid_str: str) -> str:
        """
        Converts 32-char hex string to standard 36-char canonical UUID format:
        8-4-4-4-12 (e.g., 00014d63beb7447d83507dff24a2dfcd -> 00014d63-beb7-447d-8350-7dff24a2dfcd).
        Ensures both UUIDs have the exact same character representation.
        """
        clean = re.sub(r'[^0-9a-fA-F]', '', str(guid_str or '')).lower()
        if len(clean) == 32:
            return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"
        return guid_str

    @staticmethod
    def parse_birthdate(year_str: str, month_str: str, day_str: str, age_enrollment: Optional[str] = None) -> Tuple[Optional[str], bool]:
        """
        Extracts ISO format YYYY-MM-DD.
        Returns (birthdate_iso, is_estimated).
        OpenMRS automatically computes the patient's age dynamically from this birthdate.
        """
        try:
            y = int(year_str) if year_str and str(year_str).isdigit() else None
            m = int(month_str) if month_str and str(month_str).isdigit() else 1
            d = int(day_str) if day_str and str(day_str).isdigit() else 1

            if y and 1900 <= y <= datetime.datetime.now().year:
                m = max(1, min(12, m))
                d = max(1, min(31, d))
                for test_day in range(d, 0, -1):
                    try:
                        dt = datetime.date(y, m, test_day)
                        return dt.strftime("%Y-%m-%d"), False
                    except ValueError:
                        continue
        except Exception:
            pass

        if age_enrollment and str(age_enrollment).strip().isdigit():
            age = int(age_enrollment)
            curr_year = datetime.datetime.now().year
            est_year = max(1900, curr_year - age)
            return f"{est_year}-01-01", True

        return None, False

    @staticmethod
    def parse_single_date(val: object) -> Tuple[Optional[str], bool]:
        """
        Parses all-in-one birthdate string (e.g. YYYY-MM-DD, DD/MM/YYYY, or ISO timestamp).
        Returns (birthdate_iso, is_estimated).
        """
        if not val:
            return None, False
        clean = str(val).strip().split("T")[0].split(" ")[0]
        m1 = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", clean)
        if m1:
            try:
                y, m, d = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
                if 1900 <= y <= datetime.datetime.now().year and 1 <= m <= 12 and 1 <= d <= 31:
                    return datetime.date(y, m, d).strftime("%Y-%m-%d"), False
            except ValueError:
                pass
        m2 = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", clean)
        if m2:
            try:
                d, m, y = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
                if 1900 <= y <= datetime.datetime.now().year and 1 <= m <= 12 and 1 <= d <= 31:
                    return datetime.date(y, m, d).strftime("%Y-%m-%d"), False
            except ValueError:
                pass
        return None, False

    def test_connection(self) -> Dict[str, Any]:
        """Tests connection to OpenMRS backend and fetches system metadata."""
        try:
            s_resp = self.session.get(f"{self.rest_url}/session", timeout=10)
            if s_resp.status_code != 200:
                return {"success": False, "error": f"HTTP {s_resp.status_code}: {s_resp.text}"}
            
            s_data = s_resp.json()
            if not s_data.get("authenticated"):
                return {"success": False, "error": "Authentication failed. Check username and password."}

            user_display = s_data.get("user", {}).get("display", "Admin")

            # Fetch locations
            loc_resp = self.session.get(f"{self.rest_url}/location?v=full", timeout=10)
            locations = []
            if loc_resp.status_code == 200:
                for l in loc_resp.json().get("results", []):
                    locations.append({
                        "uuid": l.get("uuid"),
                        "name": l.get("name"),
                        "display": l.get("display")
                    })
            self.cached_locations = locations

            # Fetch identifier types
            id_resp = self.session.get(f"{self.rest_url}/patientidentifiertype?v=full", timeout=10)
            id_types = []
            if id_resp.status_code == 200:
                for it in id_resp.json().get("results", []):
                    id_types.append({
                        "uuid": it.get("uuid"),
                        "name": it.get("name"),
                        "required": it.get("required"),
                        "format": it.get("format")
                    })
            self.cached_id_types = id_types

            # Fetch person attributes
            at_resp = self.session.get(f"{self.rest_url}/personattributetype?v=full", timeout=10)
            attr_types = []
            if at_resp.status_code == 200:
                for at in at_resp.json().get("results", []):
                    attr_types.append({
                        "uuid": at.get("uuid"),
                        "name": at.get("name"),
                        "format": at.get("format")
                    })
            self.cached_attr_types = attr_types

            return {
                "success": True,
                "user": user_display,
                "locations": locations,
                "identifier_types": id_types,
                "attribute_types": attr_types
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def transform_row(self, row: Dict[str, str], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Converts a single SmartCare CSV row into an OpenMRS 3.x patient registration payload.
        Supports dynamic column mappings via config['field_mappings'].
        """
        config = config or {}
        mrn_type_uuid = config.get("mrn_type_uuid") or self.DEFAULT_MRN_TYPE_UUID
        include_legacy_id = config.get("include_legacy_id", True)
        legacy_id_type_uuid = config.get("legacy_id_type_uuid") or self.DEFAULT_LEGACY_ID_TYPE_UUID
        location_uuid = config.get("location_uuid")  # Optional location override
        field_map = config.get("field_mappings") or {}

        # 1. Identifiers & UUID
        pid_col = field_map.get("patient_id") or "PatientID"
        guid_col = field_map.get("patient_guid") or "PatientGUID"
        pid_raw = row.get(pid_col, "").strip()
        guid_raw = row.get(guid_col, "").strip()
        formatted_mrn = self.format_mrn(pid_raw) if pid_raw else None
        canonical_uuid = self.normalize_uuid(guid_raw) if guid_raw else None

        identifiers = []
        if formatted_mrn:
            id_obj = {
                "identifier": formatted_mrn,
                "identifierType": mrn_type_uuid,
                "preferred": True
            }
            if location_uuid:
                id_obj["location"] = location_uuid
            identifiers.append(id_obj)

        if include_legacy_id and guid_raw:
            leg_obj = {
                "identifier": canonical_uuid,
                "identifierType": legacy_id_type_uuid,
                "preferred": False
            }
            if location_uuid:
                leg_obj["location"] = location_uuid
            identifiers.append(leg_obj)

        # 2. Names
        first_col = field_map.get("given_name") or "FirstName"
        middle_col = field_map.get("middle_name") or "MiddleName"
        family_col = field_map.get("family_name") or "SurName"
        first_name = row.get(first_col, "").strip() or "Unknown"
        middle_name = row.get(middle_col, "").strip() or ""
        family_name = row.get(family_col, "").strip() or "Unknown"

        # 3. Demographics
        gender_col = field_map.get("gender") or "Sex"
        raw_sex = row.get(gender_col, "").strip().upper()
        gender = "M" if (raw_sex.startswith("M") or raw_sex == "1") else ("F" if (raw_sex.startswith("F") or raw_sex == "2") else "O")

        # 4. Birthdate & Age (All in one vs separate Day, Month, Year)
        dob_mode = field_map.get("birthdate_mode") or "separate"
        birthdate = None
        birthdate_est = False

        if dob_mode == "all_in_one":
            dob_col = field_map.get("birthdate") or "Birthdate"
            raw_dob = row.get(dob_col, "").strip()
            birthdate, birthdate_est = self.parse_single_date(raw_dob)
            if not birthdate:
                age_col = field_map.get("age_enrollment") or "AgeAtDateOfEnrollment"
                age_val = row.get(age_col, "").strip()
                if age_val and str(age_val).isdigit():
                    curr_year = datetime.datetime.now().year
                    est_year = max(1900, curr_year - int(age_val))
                    birthdate, birthdate_est = f"{est_year}-01-01", True
        else:
            by_col = field_map.get("birth_year") or "BirthYear"
            bm_col = field_map.get("birth_month") or "BirthMonth"
            bd_col = field_map.get("birth_day") or "BirthDay"
            age_col = field_map.get("age_enrollment") or "AgeAtDateOfEnrollment"
            by = row.get(by_col, "").strip()
            bm = row.get(bm_col, "").strip()
            bd = row.get(bd_col, "").strip()
            age_enrollment = row.get(age_col, "").strip()
            birthdate, birthdate_est = self.parse_birthdate(by, bm, bd, age_enrollment)

        if not birthdate:
            birthdate = "2000-01-01"
            birthdate_est = True

        # 5. Attributes (Phone Number & Person Attributes)
        # 5. Attributes (Phone Number)
        attributes = []
        phone_col = field_map.get("phone")
        phone_val = None
        if phone_col:
            raw_phone = row.get(phone_col, "").strip()
            if raw_phone and raw_phone != "NULL":
                phone_val = raw_phone
                attributes.append({
                    "attributeType": self.DEFAULT_PHONE_ATTR_UUID,  # Telephone Number
                    "value": phone_val
                })

        # 6. Address (OpenMRS 3 Address Hierarchy)
        woreda_col = field_map.get("woreda") or field_map.get("city_village") or field_map.get("district")
        zone_col = field_map.get("zone") or field_map.get("county_district")
        region_col = field_map.get("region") or field_map.get("state_province")
        kebele_col = field_map.get("kebele") or field_map.get("address3")
        house_col = field_map.get("house_number") or field_map.get("address1")

        addr = {}
        if woreda_col:
            w_val = row.get(woreda_col, "").strip()
            if w_val and w_val != "NULL":
                addr["cityVillage"] = w_val
        if zone_col:
            z_val = row.get(zone_col, "").strip()
            if z_val and z_val != "NULL":
                addr["countyDistrict"] = z_val
        if region_col:
            r_val = row.get(region_col, "").strip()
            if r_val and r_val != "NULL":
                addr["stateProvince"] = r_val
        if kebele_col:
            k_val = row.get(kebele_col, "").strip()
            if k_val and k_val != "NULL":
                addr["address3"] = k_val
        if house_col:
            h_val = row.get(house_col, "").strip()
            if h_val and h_val != "NULL":
                addr["address1"] = h_val

        addresses = []
        if addr:
            addr["country"] = "Ethiopia"
            addr["preferred"] = True
            addresses.append(addr)

        addr_parts = [addr.get(k) for k in ["cityVillage", "countyDistrict", "stateProvince", "address3", "address1"] if addr.get(k)]
        formatted_address = ", ".join(addr_parts) if addr_parts else None

        person_obj = {
            "names": [
                {
                    "givenName": first_name,
                    "middleName": middle_name,
                    "familyName": family_name,
                    "preferred": True
                }
            ],
            "gender": gender,
            "birthdate": birthdate,
            "birthdateEstimated": birthdate_est
        }

        if canonical_uuid:
            person_obj["uuid"] = canonical_uuid

        if attributes:
            person_obj["attributes"] = attributes
        if addresses:
            person_obj["addresses"] = addresses

        payload = {
            "person": person_obj,
            "identifiers": identifiers
        }

        if canonical_uuid:
            payload["uuid"] = canonical_uuid

        return {
            "payload": payload,
            "meta": {
                "raw_patient_id": pid_raw,
                "raw_guid": guid_raw,
                "formatted_mrn": formatted_mrn,
                "canonical_uuid": canonical_uuid,
                "full_name": f"{first_name} {middle_name} {family_name}".strip(),
                "birthdate": birthdate,
                "birthdate_estimated": birthdate_est,
                "gender": gender,
                "phone": phone_val,
                "address": formatted_address
            }
        }

    def dry_run(self, csv_filepath: str, limit: Optional[int] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a thorough dry run:
        - Validates CSV structure
        - Checks MRN uniqueness and Luhn formatting
        - Checks UUID normalization and character counts
        - Validates birthdate & age computation
        - Generates sample payload preview
        - Returns full audit summary without modifying OpenMRS.
        """
        stats = {
            "total_rows": 0,
            "valid_records": 0,
            "warnings": 0,
            "errors": 0,
            "duplicate_mrns": 0,
            "duplicate_uuids": 0,
            "estimated_birthdates": 0,
            "with_contact": 0
        }

        seen_mrns = set()
        seen_uuids = set()
        issues = []
        samples = []

        with open(csv_filepath, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=1):
                stats["total_rows"] += 1
                row_issues = []

                transformed = self.transform_row(row, config)
                meta = transformed["meta"]

                # Validate MRN
                mrn = meta["formatted_mrn"]
                if not mrn or not re.match(r"^\d{6}-\d$", mrn):
                    row_issues.append(f"Row {i}: Invalid MRN format '{mrn}' (expected 6 digits + hyphen + Luhn check digit)")
                    stats["errors"] += 1
                elif mrn in seen_mrns:
                    row_issues.append(f"Row {i}: Duplicate MRN '{mrn}' found in CSV")
                    stats["duplicate_mrns"] += 1
                else:
                    seen_mrns.add(mrn)

                # Validate UUID
                u = meta["canonical_uuid"]
                if not u or len(u) != 36:
                    row_issues.append(f"Row {i}: UUID length mismatch ({len(u) if u else 0} chars, expected 36 chars)")
                    stats["warnings"] += 1
                elif u in seen_uuids:
                    row_issues.append(f"Row {i}: Duplicate UUID '{u}' found in CSV")
                    stats["duplicate_uuids"] += 1
                else:
                    seen_uuids.add(u)

                # Check birthdate
                if meta["birthdate_estimated"]:
                    stats["estimated_birthdates"] += 1

                # Check contact details (phone / address)
                if meta["phone"] or meta["address"]:
                    stats["with_contact"] += 1

                if not row_issues:
                    stats["valid_records"] += 1
                else:
                    issues.extend(row_issues)

                if len(samples) < 10:
                    samples.append({
                        "row_num": i,
                        "meta": meta,
                        "openmrs_payload": transformed["payload"]
                    })

                if limit and stats["total_rows"] >= limit:
                    break

        return {
            "summary": stats,
            "sample_records": samples,
            "issues": issues[:100],
            "total_issues_count": len(issues)
        }

    def import_patient(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends a single patient payload to OpenMRS via REST POST /ws/rest/v1/patient.
        """
        url = f"{self.rest_url}/patient"
        headers = {"Content-Type": "application/json"}
        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code in (200, 201):
                return {"success": True, "data": resp.json(), "action": "created"}
            else:
                return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def normalize_name_tokens(name_str: str) -> List[str]:
        if not name_str:
            return []
        cleaned = re.sub(r"[^\w\s]", " ", str(name_str).lower())
        return [w for w in cleaned.split() if w]

    @classmethod
    def is_same_patient_name(cls, existing_name: str, uploaded_name: str) -> bool:
        """
        Compares two patient names to determine if they belong to the same person.
        Returns True if matching, False if different.
        """
        tokens_exist = cls.normalize_name_tokens(existing_name)
        tokens_upload = cls.normalize_name_tokens(uploaded_name)
        if not tokens_exist or not tokens_upload:
            return False

        # 1. Exact normalized match
        if " ".join(tokens_exist) == " ".join(tokens_upload):
            return True

        # 2. Exact token set match (e.g. order difference)
        if set(tokens_exist) == set(tokens_upload):
            return True

        # 3. Given name (first token) and family name (last token) match
        if tokens_exist[0] == tokens_upload[0]:
            if tokens_exist[-1] == tokens_upload[-1]:
                return True
            if len(tokens_exist) >= 2 and len(tokens_upload) >= 2 and tokens_exist[1] == tokens_upload[1]:
                return True

        return False

    @staticmethod
    def extract_patient_name(patient: Dict[str, Any]) -> str:
        """
        Extracts preferred or full name from an OpenMRS patient dictionary.
        """
        if not patient:
            return ""
        person = patient.get("person") or {}
        preferred = person.get("preferredName") or {}
        g = (preferred.get("givenName") or "").strip()
        m = (preferred.get("middleName") or "").strip()
        f = (preferred.get("familyName") or "").strip()

        if not (g or f) and person.get("names"):
            for n in person.get("names", []):
                if not n.get("voided"):
                    g = (n.get("givenName") or "").strip()
                    m = (n.get("middleName") or "").strip()
                    f = (n.get("familyName") or "").strip()
                    break

        parts = [p for p in [g, m, f] if p]
        if parts:
            return " ".join(parts)
        return (person.get("display") or patient.get("display") or "").strip()

    def find_patient_by_mrn(self, mrn: str) -> Optional[Dict[str, Any]]:
        """
        Looks up patient in OpenMRS by MRN / identifier.
        Matches exact identifier or identifier with/without Luhn check-digit.
        Returns the full patient dict if found, else None.
        """
        if not mrn:
            return None
        import urllib.parse
        clean_mrn = str(mrn).strip()
        try:
            url = f"{self.rest_url}/patient?q={urllib.parse.quote(clean_mrn)}&v=full"
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                base_target = clean_mrn.split("-")[0].lower()
                for p in results:
                    for ident in p.get("identifiers", []):
                        id_val = str(ident.get("identifier", "")).strip().lower()
                        if id_val == clean_mrn.lower():
                            return p
                        # Check base before hyphen
                        base_id = id_val.split("-")[0]
                        if base_id and base_target and base_id == base_target:
                            return p
            return None
        except Exception:
            return None

    def update_patient(self, existing_patient: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates demographics, addresses, and attributes for an existing patient via POST /person/{person_uuid}.
        """
        person = existing_patient.get("person") or {}
        person_uuid = person.get("uuid") or existing_patient.get("uuid")
        if not person_uuid:
            return {"success": False, "error": "Existing patient has no person UUID"}

        new_person = payload.get("person") or {}
        update_body = {}

        if new_person.get("gender"):
            update_body["gender"] = new_person["gender"]
        if new_person.get("birthdate"):
            update_body["birthdate"] = new_person["birthdate"]
            update_body["birthdateEstimated"] = new_person.get("birthdateEstimated", False)
        if new_person.get("names"):
            update_body["names"] = new_person["names"]
        if new_person.get("addresses"):
            update_body["addresses"] = new_person["addresses"]
        if new_person.get("attributes"):
            update_body["attributes"] = new_person["attributes"]

        url = f"{self.rest_url}/person/{person_uuid}"
        headers = {"Content-Type": "application/json"}
        try:
            resp = self.session.post(url, json=update_body, headers=headers, timeout=15)
            if resp.status_code in (200, 201):
                return {"success": True, "data": resp.json(), "action": "updated"}
            else:
                return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

