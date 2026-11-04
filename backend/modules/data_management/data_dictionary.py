import os
import requests
import pandas as pd

class _Var:
    def __init__(self, val=""):
        self.val = str(val) if val is not None else ""
    def get(self):
        return self.val
    def set(self, val):
        self.val = str(val) if val is not None else ""
    def strip(self, *args):
        return self.val.strip(*args)
    def __str__(self):
        return self.val

class DataDictionaryExportPage:
    def __init__(self, url: str, username: str, password: str, program_name: str, filename: str, directory: str, log_callback=None):
        if not url or not str(url).strip():
            raise ValueError("DHIS2 URL is required.")
        if not username or not str(username).strip():
            raise ValueError("DHIS2 username is required.")
        if not password or not str(password).strip():
            raise ValueError("DHIS2 password is required.")
        if not program_name or not str(program_name).strip():
            raise ValueError("Program name is required.")
        if not filename or not str(filename).strip():
            raise ValueError("Filename is required.")
        if not directory or not str(directory).strip():
            raise ValueError("Directory is required.")

        self.log_callback = log_callback
        self.url_var = _Var(url)
        self.username_var = _Var(username)
        self.password_var = _Var(password)
        self.program_var = _Var(program_name)
        self.filename_var = _Var(filename)
        self.dir_var = _Var(directory)
        self.session = None
        self.headers = None

    def log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    # ====== API FUNCTIONS ======
    def get_program_stages(self, program_id):
        fields = (
            "programStages[id,name,sortOrder,"
            "programStageDataElements[compulsory,sortOrder,"
            "dataElement[id,name,formName,valueType,minValue,maxValue,pattern,optionSet[id,name]]],"
            "programStageSections[id,name,dataElements[id]]]"
        )
        url = f"{self.url_var.get().strip('/')}/api/programs/{program_id}?fields={fields}"
        response = self.session.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_option_set_options(self, option_set_id):
        url = f"{self.url_var.get().strip('/')}/api/optionSets/{option_set_id}?fields=options[code,name]"
        response = self.session.get(url, headers=self.headers)
        response.raise_for_status()
        return [(opt["code"], opt["name"]) for opt in response.json().get("options", [])]

    def get_program_rules(self, program_id):
        url = f"{self.url_var.get().strip('/')}/api/programRules?filter=program.id:eq:{program_id}&fields=id,name,condition,programRuleActions[programRuleActionType,dataElement[id,name]]"
        response = self.session.get(url, headers=self.headers)
        response.raise_for_status()
        rules = {}
        for pr in response.json().get("programRules", []):
            for action in pr.get("programRuleActions", []):
                de = action.get("dataElement")
                if de:
                    rules.setdefault(de["id"], []).append(
                        f"{action['programRuleActionType']} (if {pr['condition']})"
                    )
        return rules

    def get_tracked_entity_attributes(self, program_id):
        """Get Tracked Entity Attributes (TEA) with their order"""
        fields = "programTrackedEntityAttributes[sortOrder,trackedEntityAttribute[id,name,valueType,optionSet[id,name]]]"
        url = f"{self.url_var.get().strip('/')}/api/programs/{program_id}?fields={fields}"
        response = self.session.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def extract_data_elements(self, program_id):
        result = []
        program_data = self.get_program_stages(program_id)
        program_rules = self.get_program_rules(program_id)
        
        # First, extract and order Tracked Entity Attributes (TEA)
        tea_data = self.get_tracked_entity_attributes(program_id)
        
        # Extract TEAs in correct order
        teas = tea_data.get("programTrackedEntityAttributes", [])
        # Sort TEAs by sortOrder
        teas_sorted = sorted(teas, key=lambda x: x.get("sortOrder", 0))
        
        for tea in teas_sorted:
            att = tea.get("trackedEntityAttribute", {})
            if att:
                att_id = att.get("id", "")
                att_name = att.get("name", "")
                options = ""
                if "optionSet" in att and att["optionSet"]:
                    opts = self.get_option_set_options(att["optionSet"]["id"])
                    options = "; ".join([f"{code}:{name}" for code, name in opts])
                
                result.append({
                    "Stage Name": "Tracked Entity Attributes",
                    "Section Name": "",
                    "Data Element ID": att_id,
                    "Data Element Name": att_name,
                    "Form Name": "",
                    "Data Type": att.get("valueType", ""),
                    "Compulsory": False,  # TEAs don't have compulsory field in this context
                    "Min Value": "",
                    "Max Value": "",
                    "Pattern": "",
                    "Options": options,
                    "Program Rule": ""
                })

        # Now extract program stages and data elements in correct order
        # Sort program stages by sortOrder
        program_stages_sorted = sorted(
            program_data.get("programStages", []), 
            key=lambda x: x.get("sortOrder", 0)
        )

        # Build a lookup: data element ID → section name within each stage
        def build_section_lookup(stage):
            lookup = {}
            sections = stage.get("programStageSections") or stage.get("sections") or []
            for sec in sections:
                sec_name = sec.get("name", "")
                for de in sec.get("dataElements", []):
                    lookup[de["id"]] = sec_name
            return lookup

        for stage in program_stages_sorted:
            stage_name = stage["name"]
            section_lookup = build_section_lookup(stage)
            
            # Sort programStageDataElements by sortOrder within each stage
            psdes = sorted(
                stage.get("programStageDataElements", []), 
                key=lambda x: x.get("sortOrder", 0)
            )
            
            for psde in psdes:
                de = psde["dataElement"]
                de_id = de["id"]
                options = ""
                if "optionSet" in de and de["optionSet"]:
                    opts = self.get_option_set_options(de["optionSet"]["id"])
                    options = "; ".join([f"{code}:{name}" for code, name in opts])

                result.append({
                    "Stage Name": stage_name,
                    "Section Name": section_lookup.get(de_id, ""),
                    "Data Element ID": de_id,
                    "Data Element Name": de["name"],
                    "Form Name": de.get("formName", ""),
                    "Data Type": de["valueType"],
                    "Compulsory": psde.get("compulsory", False),
                    "Min Value": de.get("minValue", ""),
                    "Max Value": de.get("maxValue", ""),
                    "Pattern": de.get("pattern", ""),
                    "Options": options,
                    "Program Rule": "; ".join(program_rules.get(de_id, []))
                })
        return result

    # ====== EXPORT FUNCTION ======
    def export_data(self):
        try:
            url = (self.url_var.get() if hasattr(self.url_var, "get") else self.url_var).strip()
            username = (self.username_var.get() if hasattr(self.username_var, "get") else self.username_var).strip()
            password = (self.password_var.get() if hasattr(self.password_var, "get") else self.password_var).strip()
            program_name = (self.program_var.get() if hasattr(self.program_var, "get") else self.program_var).strip()
            filename = (self.filename_var.get() if hasattr(self.filename_var, "get") else self.filename_var).strip()
            directory = (self.dir_var.get() if hasattr(self.dir_var, "get") else self.dir_var).strip()

            if not all([url, username, password]):
                raise ValueError("Please provide DHIS2 URL, username and password")
            if not program_name:
                raise ValueError("Please select a program")
            if not filename:
                raise ValueError("Please provide a file name.")
            if not directory:
                raise ValueError("Please select an export directory.")

            # Map program names to IDs
            program_ids = {
                "Maternal inpatient data": "aLoraiFNkng",
                "Newborn inpatient data": "pLk3Ht2XMKl",
                "Neonatal Care Form": "QYJKpoUeg9F"
            }

            program_id = program_ids.get(program_name)
            if not program_id:
                raise ValueError(f"Invalid program selected: {program_name}")

            # Setup session
            self.session = requests.Session()
            self.session.auth = (username, password)
            self.headers = {"Accept": "application/json"}

            # Extract data
            self.log(f"Extracting data elements for program: {program_name} ({program_id})")
            elements = self.extract_data_elements(program_id)
            
            if not elements:
                self.log(f"Warning: No data elements found for program: {program_name}")
                return {"status": "no_data", "message": f"No data elements found for program: {program_name}"}
            
            df = pd.DataFrame(elements)

            # Ensure filename has .xlsx
            if not filename.lower().endswith('.xlsx'):
                filename += '.xlsx'
            output_path = os.path.join(directory, filename)
            os.makedirs(directory, exist_ok=True)

            df.to_excel(output_path, index=False)
            self.log(f"Success: Exported {program_name} data dictionary to: {output_path} (Total elements: {len(elements)})")
            return {"status": "success", "output_path": output_path, "total_elements": len(elements)}
        except requests.exceptions.RequestException as e:
            self.log(f"Connection Error: {str(e)}")
            raise RuntimeError(f"Connection Error: {str(e)}")
        except Exception as e:
            import traceback
            self.log(f"Export Error: {str(e)}\n{traceback.format_exc()}")
            raise RuntimeError(f"Export Error: {str(e)}")
