# -*- coding: utf-8 -*-
"""Unit tests for concept_drug_importer.py."""

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.modules.concepts.concept_drug_importer import (
    resolve_drug_input_files,
    scan_drug_files,
    run_concept_drug_import,
)


class TestConceptDrugImporter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_csv(self, filename: str, rows: list[dict], fieldnames: list[str]) -> str:
        filepath = os.path.join(self.dir_path, filename)
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return filepath

    def create_json(self, filename: str, data: list[dict]) -> str:
        filepath = os.path.join(self.dir_path, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return filepath

    def test_resolve_input_files_single_and_dir(self):
        csv1 = self.create_csv("drugs1.csv", [{"Name": "A", "Concept Drug": "Amox"}], ["Name", "Concept Drug"])
        json1 = self.create_json("drugs2.json", [{"name": "B", "concept": "Para"}])

        # Single file
        res = resolve_drug_input_files(csv1, file_format="csv")
        self.assertEqual(len(res), 1)
        self.assertEqual(str(res[0]), csv1)

        # Single JSON file
        res_json = resolve_drug_input_files(json1, file_format="json")
        self.assertEqual(len(res_json), 1)
        self.assertEqual(str(res_json[0]), json1)

        # Directory with format filter
        res_csv_only = resolve_drug_input_files(self.dir_path, file_format="csv")
        self.assertEqual(len(res_csv_only), 1)

        res_json_only = resolve_drug_input_files(self.dir_path, file_format="json")
        self.assertEqual(len(res_json_only), 1)

    def test_scan_drug_files(self):
        csv1 = self.create_csv("drugs.csv", [
            {"Name": "Drug A", "Concept Drug": "UUID-1"},
            {"Name": "Drug B", "Concept Drug": "UUID-2"},
        ], ["Name", "Concept Drug"])
        json1 = self.create_json("drugs.json", [
            {"name": "Drug C", "concept": "@Drug|C"},
        ])
        csv2 = self.create_csv("not_drug.csv", [
            {"Name": "Concept X", "Datatype": "Numeric"}
        ], ["Name", "Datatype"])

        files = resolve_drug_input_files(self.dir_path, file_format="auto")
        scan = scan_drug_files(files)
        self.assertEqual(scan["valid_files_count"], 2)
        self.assertEqual(scan["total_drug_rows"], 3)

    def test_drug_import_csv(self):
        csv_file = self.create_csv("formulations.csv", [
            {
                "Uuid": "",
                "Name": "Amoxicillin 500mg Capsule",
                "Concept Drug": "Amoxicillin",
                "Concept Dosage Form": "Capsule",
                "Strength": "500mg",
                "Description": "Oral antibiotic capsule",
                "Maximum daily dose": "1500",
                "Minimum daily dose": "500",
                "Void/Retire": "",
            },
            {
                "Uuid": "",
                "Name": "Retired Drug",
                "Concept Drug": "Amoxicillin",
                "Concept Dosage Form": "",
                "Strength": "250mg",
                "Description": "",
                "Maximum daily dose": "",
                "Minimum daily dose": "",
                "Void/Retire": "true",
            },
            {
                "Uuid": "",
                "Name": "Existing Drug",
                "Concept Drug": "Paracetamol",
                "Concept Dosage Form": "",
                "Strength": "500mg",
                "Description": "",
                "Maximum daily dose": "",
                "Minimum daily dose": "",
                "Void/Retire": "false",
            },
        ], [
            "Uuid",
            "Name",
            "Concept Drug",
            "Concept Dosage Form",
            "Strength",
            "Description",
            "Maximum daily dose",
            "Minimum daily dose",
            "Void/Retire",
        ])

        mock_client = MagicMock()
        mock_client._url.side_effect = lambda path: f"http://openmrs{path}"

        posted_payloads = []

        def mock_request(method, url, json=None, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"status": "ok"}'

            if "/ws/rest/v1/concept" in url and "q=" in url:
                if "Amoxicillin" in url:
                    mock_resp.json.return_value = {
                        "results": [
                            {"uuid": "amox-concept-uuid", "name": {"name": "Amoxicillin"}, "conceptClass": {"name": "Drug"}}
                        ]
                    }
                elif "Capsule" in url:
                    mock_resp.json.return_value = {
                        "results": [
                            {"uuid": "capsule-concept-uuid", "name": {"name": "Capsule"}, "conceptClass": {"name": "Drug form"}}
                        ]
                    }
                else:
                    mock_resp.json.return_value = {"results": []}
                return mock_resp

            if "/ws/rest/v1/drug" in url and method == "GET":
                if "Existing+Drug" in url or "Existing%20Drug" in url:
                    mock_resp.json.return_value = {
                        "results": [{"uuid": "existing-uuid", "name": "Existing Drug"}]
                    }
                else:
                    mock_resp.json.return_value = {"results": []}
                return mock_resp

            if "/ws/rest/v1/drug" in url and method == "POST":
                posted_payloads.append(json)
                mock_resp.json.return_value = {"uuid": "new-drug-uuid", "name": json.get("name")}
                return mock_resp

            mock_resp.json.return_value = {}
            return mock_resp

        mock_client.session.request.side_effect = mock_request

        report_path = os.path.join(self.dir_path, "report.csv")

        # Dry Run
        res_dry = run_concept_drug_import(
            client=mock_client,
            path=csv_file,
            file_format="csv",
            dry_run=True,
            out_report_path=Path(report_path),
        )

        self.assertEqual(res_dry["dry_run_ok"], 1)
        self.assertEqual(res_dry["skipped"], 2)
        self.assertEqual(res_dry["created"], 0)

        # Live Run
        res_live = run_concept_drug_import(
            client=mock_client,
            path=csv_file,
            file_format="csv",
            dry_run=False,
            out_report_path=Path(report_path),
        )

        self.assertEqual(res_live["created"], 1)
        self.assertEqual(res_live["skipped"], 2)
        self.assertEqual(len(posted_payloads), 1)

    def test_drug_import_json(self):
        json_file = self.create_json("formulations.json", [
            {
                "name": "Oxytocin 10 IU/mL injection",
                "concept": "@Drug|Oxytocin",
                "dosageForm": "@Drug form|Solution for injection",
                "strength": "10 IU/mL",
                "combination": False
            }
        ])

        mock_client = MagicMock()
        mock_client._url.side_effect = lambda path: f"http://openmrs{path}"

        posted_payloads = []

        def mock_request(method, url, json=None, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"status": "ok"}'

            if "/ws/rest/v1/concept" in url and "q=" in url:
                if "Oxytocin" in url:
                    mock_resp.json.return_value = {
                        "results": [
                            {"uuid": "oxytocin-uuid", "name": {"name": "Oxytocin"}, "conceptClass": {"name": "Drug"}}
                        ]
                    }
                elif "Solution%20for%20injection" in url or "Solution+for+injection" in url:
                    mock_resp.json.return_value = {
                        "results": [
                            {"uuid": "sol-inj-uuid", "name": {"name": "Solution for injection"}, "conceptClass": {"name": "Drug form"}}
                        ]
                    }
                else:
                    mock_resp.json.return_value = {"results": []}
                return mock_resp

            if "/ws/rest/v1/drug" in url and method == "GET":
                mock_resp.json.return_value = {"results": []}
                return mock_resp

            if "/ws/rest/v1/drug" in url and method == "POST":
                posted_payloads.append(json)
                mock_resp.json.return_value = {"uuid": "oxytocin-drug-uuid", "name": json.get("name")}
                return mock_resp

            mock_resp.json.return_value = {}
            return mock_resp

        mock_client.session.request.side_effect = mock_request

        res = run_concept_drug_import(
            client=mock_client,
            path=json_file,
            file_format="json",
            dry_run=False,
        )

        self.assertEqual(res["created"], 1)
        self.assertEqual(res["failed"], 0)
        self.assertEqual(len(posted_payloads), 1)
        self.assertEqual(posted_payloads[0]["concept"], "oxytocin-uuid")
        self.assertEqual(posted_payloads[0]["dosageForm"], "sol-inj-uuid")


if __name__ == "__main__":
    unittest.main()
