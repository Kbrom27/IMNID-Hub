import requests
import json
import os
import zipfile
import tempfile
import shutil
from datetime import datetime
import threading
import time
import re

def get_metadata_json_path(file_path: str):
    """If file_path is a zip archive, extracts the metadata JSON file into a temporary directory."""
    if zipfile.is_zipfile(file_path):
        with zipfile.ZipFile(file_path, "r") as zf:
            json_files = [f for f in zf.namelist() if f.lower().endswith(".json")]
            if not json_files:
                raise ValueError("Zip archive does not contain any JSON metadata file.")
            target = "metadata.json" if "metadata.json" in json_files else json_files[0]
            temp_dir = tempfile.mkdtemp(prefix="imnid_meta_")
            extracted = zf.extract(target, temp_dir)
            return extracted, temp_dir
    return file_path, None

def get_metadata_file_info(file_path: str) -> dict:
    """Reads metadata file and extracts summary counts of each object type, matching the desktop app."""
    real_path, tmp_dir = get_metadata_json_path(file_path)
    try:
        with open(real_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        contents = {}
        total = 0
        for key, value in metadata.items():
            if isinstance(value, list):
                count = len(value)
                contents[key] = count
                total += count
            elif isinstance(value, dict):
                contents[key] = 1
                total += 1

        return {
            "filename": os.path.basename(file_path),
            "size": os.path.getsize(file_path),
            "modified": datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S"),
            "total_objects": total,
            "contents": contents,
        }
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)

class DHIS2MetadataImporter:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.session = None

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def build_api_url(self, base_url, api_version):
        """Build the correct API URL based on DHIS2 version"""
        base_url = base_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
            
        if api_version and api_version != 'auto-detect':
            return f"{base_url}/api/{api_version}/metadata"
        else:
            return f"{base_url}/api/metadata"
    
    def import_metadata(self, dhis2_base_url, api_version, username, password, json_file_path,
                        import_mode="COMMIT", import_strategy="CREATE_AND_UPDATE",
                        identifier="UID", merge_mode="MERGE", exec_mode="Direct (Synchronous)",
                        atomic_mode=False):
        if not all([dhis2_base_url, username, password, json_file_path]):
            raise ValueError("All fields are required!")
        if not os.path.exists(json_file_path):
            raise FileNotFoundError("Metadata file does not exist!")
        return self._run_import(
            dhis2_base_url, api_version, username, password, json_file_path,
            import_mode, import_strategy, identifier, merge_mode, exec_mode, atomic_mode
        )

    def _run_import(self, dhis2_base_url, api_version, username, password, json_file_path,
                    import_mode, import_strategy, identifier, merge_mode,
                    exec_mode="Direct (Synchronous)", atomic_mode=False):
        real_json_path, tmp_dir = None, None
        try:
            real_json_path, tmp_dir = get_metadata_json_path(json_file_path)
            url = self.build_api_url(dhis2_base_url, api_version)
            base_url = dhis2_base_url.rstrip('/')
            if base_url.endswith('/api'):
                base_url = base_url[:-4]
            
            is_async = (exec_mode == 'Background (Async)')
            
            # Request Parameters
            params = {
                "importMode": import_mode,
                "importStrategy": import_strategy,
                "identifier": identifier,
                "mergeMode": merge_mode,
                "atomicMode": "ALL" if atomic_mode else "NONE",
                "flushMode": "AUTO",
                "skipValidation": "false",
                "skipSharing": "false",
                "skipTranslation": "false",
                "async": "true" if is_async else "false",
                "reportMode": "FULL"
            }
            
            # Load Metadata JSON for analysis only
            try:
                with open(real_json_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception as e:
                self.log(f"Failed to load metadata file: {str(e)}")
                raise RuntimeError(f"Failed to load metadata file: {str(e)}")
            
            file_size = os.path.getsize(real_json_path)
            
            self.log("=" * 70)
            self.log("🚀 DHIS2 Metadata Import Tool")
            self.log("=" * 70)
            self.log(f"📡 Target Server: {dhis2_base_url}")
            self.log(f"🔗 API Endpoint: {url}")
            self.log(f"👤 Username: {username}")
            self.log(f"📄 Metadata file: {os.path.basename(json_file_path)}")
            self.log(f"📊 File size: {file_size:,} bytes")
            self.log(f"⚙️  Import Mode: {import_mode}")
            self.log(f"⚙️  Import Strategy: {import_strategy}")
            self.log(f"⚙️  Identifier: {identifier}")
            self.log(f"⚙️  Merge Mode: {merge_mode}")
            self.log(f"⚙️  Atomic Mode: {'ALL' if atomic_mode else 'NONE'}")
            self.log(f"⚙️  Execution: {exec_mode}")
            
            # Analyze metadata structure
            self.log("\n" + "=" * 70)
            self.log("📋 METADATA ANALYSIS")
            self.log("=" * 70)
            
            total_objects = 0
            for key, value in metadata.items():
                if isinstance(value, list):
                    count = len(value)
                    total_objects += count
                    self.log(f"  • {key:30} {count:5} object(s)")
                elif isinstance(value, dict):
                    total_objects += 1
                    self.log(f"  • {key:30} {1:5} object(s)")
            
            self.log("-" * 70)
            self.log(f"  {'TOTAL':30} {total_objects:5} object(s)")
            self.log("=" * 70)
            
            # Free the in-memory metadata dict (no longer needed for the POST)
            del metadata
            
            if is_async and total_objects > 1000:
                self.log("⚠️  Large metadata payload detected! Running via DHIS2 asynchronous task...")
            
            self.log("\n📤 Submitting metadata payload to DHIS2...")
            self.log(f"📤 URL: {url}")
            
            session = requests.Session()
            session.auth = (username, password)
            
            with open(real_json_path, "rb") as f:
                raw_data = f.read()
            
            # Send Direct uncompressed JSON.
            # Avoid Content-Encoding: gzip because Apache Tomcat does not decompress
            # incoming request bodies by default, which causes DHIS2 to reject the stream.
            self.log(f"📦 Upload method: Direct JSON ({file_size:,} bytes)")
            response = session.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                params=params,
                data=raw_data,
                timeout=600
            )
            
            # Check for DHIS2 E6102 "File content could not be stored" error on async import.
            # If the server file storage is not configured, automatically retry with synchronous import.
            if response.status_code == 409 and ("E6102" in response.text or "File content could not be stored" in response.text):
                if params.get("async") == "true":
                    self.log("\n⚠️ Server rejected async file storage (E6102: File content could not be stored).")
                    self.log("🔄 Automatically falling back to Synchronous Import (direct execution)...")
                    params["async"] = "false"
                    response = session.post(
                        url,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json"
                        },
                        params=params,
                        data=raw_data,
                        timeout=600
                    )
                    self.log(f"📥 Fallback Response Status: {response.status_code}")
            
            self.log(f"📥 Initial Response Status: {response.status_code}")
            
            # Check specific HTTP status codes
            if response.status_code == 401:
                self.log("❌ ERROR: Authentication failed (401 Unauthorized)")
                raise RuntimeError("HTTP 401: Invalid username or password.")
            elif response.status_code == 403:
                self.log("❌ ERROR: Access forbidden (403 Forbidden). User lacks metadata import authorities.")
                raise RuntimeError("HTTP 403: User lacks permissions to import metadata.")
            elif response.status_code == 404:
                self.log(f"❌ ERROR: API endpoint not found (404): {url}")
                raise RuntimeError(f"Endpoint not found (404): {url}\nPlease verify Server URL and API version.")
            elif response.status_code == 413:
                self.log("❌ ERROR: Payload too large (413 Request Entity Too Large)")
                self.log("The web server / reverse proxy rejected the payload because it exceeds the body size limit.")
                raise RuntimeError("HTTP 413: The metadata file is too large for the web server/reverse proxy limit.")
            elif response.status_code >= 500:
                self.log(f"❌ ERROR: Server error (HTTP {response.status_code})")
                self.log(f"Response (first 300 chars): {response.text[:300]}")
                raise RuntimeError(f"DHIS2 server error (HTTP {response.status_code}). Check DHIS2 / Tomcat logs.")
            
            # Parse JSON
            try:
                response_data = response.json()
            except ValueError:
                self.log("❌ ERROR: Server returned non-JSON response.")
                if "<html" in response.text.lower():
                    title_match = re.search(r'<title>(.*?)</title>', response.text, re.IGNORECASE)
                    title = title_match.group(1).strip() if title_match else "HTML Error Page"
                    self.log(f"Server HTML Page: {title}")
                    raise RuntimeError(f"Server returned an HTML page instead of JSON:\n{title}")
                else:
                    self.log(f"Response: {response.text[:500]}")
                    raise RuntimeError("Server returned invalid response (not JSON)")
            
            # Check if this is an async job
            resp_obj = response_data.get("response", {})
            job_id = resp_obj.get("id") if isinstance(resp_obj, dict) else None
            
            summary_data = None
            if job_id:
                self.log(f"\n⏳ DHIS2 task initiated (Job ID: {job_id})")
                self.log("📡 Tracking progress in real-time...")
                
                tasks_endpoint = f"{base_url}/api/system/tasks/METADATA_IMPORT/{job_id}"
                summary_endpoint = f"{base_url}/api/system/taskSummaries/METADATA_IMPORT/{job_id}"
                
                seen_messages = set()
                completed = False
                max_polls = 600  # up to 20 minutes (600 * 2s)
                
                for _ in range(max_polls):
                    time.sleep(2)
                    try:
                        t_resp = session.get(tasks_endpoint, timeout=15)
                        if t_resp.status_code == 200:
                            task_items = t_resp.json()
                            if isinstance(task_items, list):
                                for item in task_items:
                                    msg = item.get("message")
                                    item_id = item.get("uid") or item.get("id") or msg
                                    if item_id and item_id not in seen_messages:
                                        seen_messages.add(item_id)
                                        if msg:
                                            self.log(f"  • {msg}")
                                    if item.get("completed"):
                                        completed = True
                        if completed:
                            break
                    except Exception:
                        continue
                
                # Fetch final summary report
                self.log("\n📊 Fetching final import summary...")
                time.sleep(1)
                try:
                    s_resp = session.get(summary_endpoint, timeout=30)
                    if s_resp.status_code == 200:
                        summary_data = s_resp.json()
                except Exception as sum_e:
                    self.log(f"⚠️ Failed to retrieve task summary: {sum_e}")
            
            if not summary_data:
                summary_data = response_data
            
            self._process_import_summary(summary_data, total_objects)
            
        except requests.exceptions.ConnectionError as e:
            self.log(f"\n❌ CONNECTION ERROR: {str(e)}")
            raise RuntimeError(f"Cannot connect to server: {str(e)}")
        except requests.exceptions.Timeout as e:
            self.log(f"\n⏱️ TIMEOUT ERROR: Request timed out")
            raise e
        except Exception as e:
            import traceback
            self.log(f"\n❌ UNEXPECTED ERROR: {str(e)}")
            self.log(traceback.format_exc())
            raise e
        finally:
            if tmp_dir and os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
            self.log("\n" + "=" * 70)
            self.log("🏁 Import process completed")
            self.log("=" * 70)

    def _process_import_summary(self, response_data, total_objects):
        response_info = response_data.get("response", response_data)
        
        # Determine status
        status = response_info.get("status")
        if not status:
            for key in ['Status', 'import', 'Import']:
                if key in response_data:
                    status = response_data[key]
                    break
        status = status or "UNKNOWN"
        description = response_info.get("description", "")
        
        self.log(f"\n📊 Import Status: {status}")
        if description and description != "No description":
            self.log(f"📝 Description: {description}")
            
        type_reports = response_info.get("typeReports", [])
        
        if status in ["OK", "WARNING", "SUCCESS", "SUCCESSFUL"]:
            self.log("\n✅ SUCCESS: Import completed!")
            self.log("\n" + "=" * 70)
            self.log("📈 IMPORT SUMMARY")
            self.log("=" * 70)
            
            total_stats = {"created": 0, "updated": 0, "ignored": 0, "deleted": 0, "errors": 0}
            
            # Prime from root stats if available
            root_stats = response_info.get("stats")
            if isinstance(root_stats, dict) and "created" in root_stats:
                total_stats["created"] = root_stats.get("created", 0)
                total_stats["updated"] = root_stats.get("updated", 0)
                total_stats["ignored"] = root_stats.get("ignored", 0)
                total_stats["deleted"] = root_stats.get("deleted", 0)
                total_stats["errors"] = root_stats.get("errors", 0)
            
            calc_totals = (total_stats["created"] == 0 and total_stats["updated"] == 0 and 
                           total_stats["ignored"] == 0 and total_stats["deleted"] == 0)

            all_warning_error_items = []
            all_ignored_items = []
            
            for report in type_reports:
                klass = report.get("klass", "Unknown").split(".")[-1]
                stats = report.get("stats", {})
                
                created = stats.get("created", 0)
                updated = stats.get("updated", 0)
                ignored = stats.get("ignored", 0)
                deleted = stats.get("deleted", 0)
                
                if calc_totals:
                    total_stats["created"] += created
                    total_stats["updated"] += updated
                    total_stats["ignored"] += ignored
                    total_stats["deleted"] += deleted

                type_warning_errors = []
                type_ignored_objects = []

                for obj_report in report.get("objectReports", []):
                    uid = obj_report.get("uid")
                    display_name = obj_report.get("displayName")
                    index = obj_report.get("index")
                    
                    id_label = uid or display_name or (f"index {index}" if index is not None else "Unknown ID")
                    if display_name and uid and display_name != uid:
                        id_label = f"{uid} ({display_name})"

                    err_reports = obj_report.get("errorReports", [])
                    warn_reports = obj_report.get("warningReports", [])

                    obj_first_err_msg = None
                    if err_reports:
                        for err in err_reports:
                            msg = err.get("message", "Unknown error")
                            code = err.get("errorCode")
                            prop = err.get("errorProperty") or (", ".join(err.get("errorProperties", [])) if err.get("errorProperties") else None)
                            parts = [f"[{klass} - {id_label}]"]
                            if code:
                                parts.append(f"[{code}]")
                            parts.append(msg)
                            if prop:
                                parts.append(f"(property: {prop})")
                            formatted_err = " ".join(parts)
                            type_warning_errors.append(formatted_err)
                            if not obj_first_err_msg:
                                obj_first_err_msg = msg

                    if warn_reports:
                        for warn in warn_reports:
                            msg = warn.get("message", "Unknown warning")
                            code = warn.get("warningCode")
                            parts = [f"[{klass} - {id_label}] (Warning)"]
                            if code:
                                parts.append(f"[{code}]")
                            parts.append(msg)
                            formatted_warn = " ".join(parts)
                            type_warning_errors.append(formatted_warn)

                    # An object report with errors or ignored status
                    reason = obj_first_err_msg or ("Ignored by server" if not warn_reports else "Warning reported")
                    type_ignored_objects.append(f"{klass} [{id_label}] - Reason: {reason}")

                # Check type-level errors
                for err in report.get("errorReports", []):
                    msg = err.get("message", "Unknown error")
                    code = err.get("errorCode")
                    code_str = f"[{code}] " if code else ""
                    type_warning_errors.append(f"[{klass}] {code_str}{msg}")

                err_count = len(type_warning_errors)
                if err_count > 0:
                    total_stats["errors"] += err_count
                    all_warning_error_items.extend(type_warning_errors)

                if type_ignored_objects:
                    all_ignored_items.extend(type_ignored_objects)
                    if ignored > len(type_ignored_objects):
                        diff = ignored - len(type_ignored_objects)
                        all_ignored_items.append(f"{klass} - {diff} additional object(s) ignored")
                elif ignored > 0:
                    all_ignored_items.append(f"{klass} - {ignored} object(s) ignored")
                
                if created + updated + deleted + ignored > 0:
                    self.log(f"\n📁 {klass}:")
                    if created > 0:
                        self.log(f"    ✅ Created: {created}")
                    if updated > 0:
                        self.log(f"    🔄 Updated: {updated}")
                    if ignored > 0:
                        self.log(f"    ⏭️  Ignored: {ignored}")
                    if deleted > 0:
                        self.log(f"    🗑️  Deleted: {deleted}")
                    if err_count > 0:
                        self.log(f"    ⚠️  Warnings/Errors: {err_count}")
                    
                    if type_warning_errors:
                        for item in type_warning_errors:
                            self.log(f"       • ⚠️  {item}")
                    if type_ignored_objects and not type_warning_errors:
                        for item in type_ignored_objects:
                            self.log(f"       • ⏭️  {item}")

            # Top-level error reports and conflicts
            for err in response_info.get("errorReports", []):
                msg = err.get("message", "Unknown error")
                code = err.get("errorCode")
                code_str = f"[{code}] " if code else ""
                formatted = f"[General] {code_str}{msg}"
                all_warning_error_items.append(formatted)
                total_stats["errors"] += 1

            for conf in response_info.get("conflicts", []):
                obj = conf.get("object", "")
                val = conf.get("value", "")
                formatted = f"[Conflict on {obj}]: {val}"
                all_warning_error_items.append(formatted)
                total_stats["errors"] += 1

            if len(all_warning_error_items) > total_stats["errors"]:
                total_stats["errors"] = len(all_warning_error_items)
            
            self.log("\n" + "=" * 70)
            self.log("📊 FINAL TOTALS")
            self.log("=" * 70)
            self.log(f"    ✅ Created: {total_stats['created']}")
            self.log(f"    🔄 Updated: {total_stats['updated']}")
            self.log(f"    ⏭️  Ignored: {total_stats['ignored']}")
            if total_stats['deleted'] > 0:
                self.log(f"    🗑️  Deleted: {total_stats['deleted']}")
            if total_stats['errors'] > 0:
                self.log(f"    ⚠️  Warnings/Errors: {total_stats['errors']}")
            self.log("-" * 70)
            self.log(f"    📋 Processed: {total_objects} object(s)")
            self.log("=" * 70)

            # Detailed breakdown section
            if all_warning_error_items or all_ignored_items:
                self.log("\n" + "=" * 70)
                self.log("🔍 DETAILED REPORT: WARNINGS, ERRORS & IGNORED OBJECTS")
                self.log("=" * 70)
                
                if all_warning_error_items:
                    self.log(f"\n⚠️  WARNINGS & ERRORS ({len(all_warning_error_items)}):")
                    for item in all_warning_error_items:
                        self.log(f"   • {item}")
                
                if all_ignored_items:
                    self.log(f"\n⏭️  IGNORED OBJECTS ({len(all_ignored_items)}):")
                    for item in all_ignored_items:
                        self.log(f"   • {item}")
                
                self.log("=" * 70)
            
            success_msg = f"Metadata import completed with status: {status}\n\n"
            success_msg += f"Created: {total_stats['created']}\n"
            success_msg += f"Updated: {total_stats['updated']}\n"
            success_msg += f"Ignored: {total_stats['ignored']}\n"
            if total_stats['deleted'] > 0:
                success_msg += f"Deleted: {total_stats['deleted']}\n"
            if total_stats['errors'] > 0 or total_stats['ignored'] > 0:
                success_msg += f"\n⚠️ {total_stats['errors']} warning(s)/error(s), {total_stats['ignored']} ignored.\nSee the detailed breakdown above in the log."
        else:
            # Error case
            self.log(f"\n❌ ERROR: Import failed with status: {status}")
            self.log("\n" + "=" * 70)
            self.log("🔍 ERROR DETAILS")
            self.log("=" * 70)
            
            error_messages = []
            for report in type_reports:
                klass = report.get("klass", "Unknown").split(".")[-1]
                for obj_report in report.get("objectReports", []):
                    uid = obj_report.get("uid") or obj_report.get("displayName") or f"index {obj_report.get('index', '?')}"
                    for error in obj_report.get("errorReports", []):
                        msg = error.get('message', 'Unknown error')
                        code = error.get('errorCode')
                        prop = error.get('errorProperty') or (", ".join(error.get("errorProperties", [])) if error.get("errorProperties") else None)
                        parts = [f"{klass}[{uid}]"]
                        if code:
                            parts.append(f"[{code}]")
                        parts.append(msg)
                        if prop:
                            parts.append(f"(property: {prop})")
                        formatted = " ".join(parts)
                        error_messages.append(formatted)
                        self.log(f"  • {formatted}")
                for error in report.get("errorReports", []):
                    msg = error.get('message', 'Unknown error')
                    code = error.get('errorCode')
                    code_str = f"[{code}] " if code else ""
                    formatted = f"{klass}: {code_str}{msg}"
                    error_messages.append(formatted)
                    self.log(f"  • {formatted}")
            
            for conf in response_info.get("conflicts", []):
                obj = conf.get("object", "")
                val = conf.get("value", "")
                formatted = f"Conflict on {obj}: {val}"
                error_messages.append(formatted)
                self.log(f"  • {formatted}")

            if not error_messages:
                self.log("  No detailed error messages available.")
                self.log(f"  Full response: {json.dumps(response_data, indent=2)[:1000]}")
            
            err_box_msg = f"Import failed with status: {status}\n\n"
            if description:
                err_box_msg += f"Description: {description}\n\n"
            if error_messages:
                err_box_msg += f"First error: {error_messages[0]}\n\n"
            err_box_msg += "Check the Import Log for complete details."
            raise RuntimeError(err_box_msg)

# Function to match main.py's expected interface
