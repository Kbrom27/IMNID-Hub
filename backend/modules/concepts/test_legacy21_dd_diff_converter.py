"""Unit tests for legacy21_dd_diff_converter.py (CM-15) and CM-13 integration."""

import csv
import os
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from backend.modules.concepts import bahmni_concept_importer as bci
from backend.modules.concepts import legacy21_dd_diff_converter as conv


def _make_dd_xlsx(path: Path, rows: list, sheet_name: str = "Added (New Only)") -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append([
        "Stage Name", "Section Name", "Data Element ID",
        "Data Element Name", "Data Type", "Options",
    ])
    for r in rows:
        ws.append(r)
    wb.save(str(path))


def _make_existing_csv(path: Path, uuids: list, col_name: str = "EMR Concept UUID") -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow([col_name, "EMR Concept Fully Specified Name", "EMR concept Data Type", "EMR Options (Answers)"])
        for i, u in enumerate(uuids):
            w.writerow([u, f"Existing {i}", "Text", ""])


class TestDdDiffRules(unittest.TestCase):
    def test_parse_options_and_datatypes(self):
        self.assertEqual(conv.parse_options("1:Yes; 0:No; -1:Not recorded"), ["Yes", "No", "Not recorded"])
        self.assertEqual(conv.parse_options(None), [])
        self.assertEqual(conv.resolve_datatype("TEXT", []), "Text")
        self.assertEqual(conv.resolve_datatype("TIME", []), "Text")
        self.assertEqual(conv.resolve_datatype("DATE", []), "Date")
        self.assertEqual(conv.resolve_datatype("DATETIME", []), "Datetime")
        self.assertEqual(conv.resolve_datatype("INTEGER_POSITIVE", []), "Numeric")
        self.assertEqual(conv.resolve_datatype("TEXT", ["1", "2", "3"]), "Numeric")
        self.assertEqual(conv.resolve_datatype("TEXT", ["Yes", "No"]), "Boolean")
        self.assertEqual(
            conv.resolve_datatype("TEXT", ["Yes", "No", "Not recorded", "Not readable"]),
            "Boolean",
        )
        self.assertEqual(conv.resolve_datatype("TEXT", ["Yes", "No", "Maybe"]), "Coded")

    def test_conversion_structure_dedup_and_cm13_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            dd_xlsx = td_path / "dd.xlsx"
            existing_csv = td_path / "existing.csv"
            out_root = td_path / "out"

            existing_uid = "11111111-1111-4111-8111-111111111111"
            _make_existing_csv(existing_csv, [existing_uid])
            _make_dd_xlsx(dd_xlsx, [
                # Coded DE with shared answer 'Other'
                ["Stage A", "Sec 1", "DE1", "Symptom", "TEXT", "1:Fever; 2:Other"],
                # Boolean (Yes/No + admin)
                ["Stage A", "Sec 1", "DE2", "Admitted?", "TEXT", "1:Yes; 0:No; -1:Not recorded"],
                # All-numeric options -> Numeric
                ["Stage A", "Sec 1", "DE3", "Day of Month", "INTEGER", "1:1; 2:2; 3:3"],
                # Duplicate DE across sections + Coded sharing 'other' (case-insensitive)
                ["Stage A", "Sec 2", "DE4", "Cause", "TEXT", "1:Trauma; 2:other"],
                ["Stage A", "Sec 2", "DE1", "Symptom", "TEXT", "1:Fever; 2:Other"],
                # Whitespace-only section -> falls back to Stage B, no self-cycle
                ["Stage B", "   ", "DE5", "Notes", "TIME", None, "trailing_extra_col"],
            ])

            res = conv.convert_dd_differences_to_legacy21(
                dd_path=dd_xlsx,
                existing_concepts_path=existing_csv,
                output_root=out_root,
                parent_folder_name="NCF_Test",
            )

            base = out_root / "NCF_Test"
            # Stage A has stage-level concept_sets.csv + 2 sections
            self.assertTrue((base / "Stage A" / "concept_sets.csv").is_file())
            self.assertTrue((base / "Stage A" / "Sec 1" / "concepts.csv").is_file())
            self.assertTrue((base / "Stage A" / "Sec 1" / "concept_sets.csv").is_file())
            self.assertTrue((base / "Stage A" / "Sec 2" / "concepts.csv").is_file())
            self.assertTrue((base / "Stage A" / "Sec 2" / "concept_sets.csv").is_file())

            # Stage B fell back to section == stage, so no redundant self-referencing stage set
            self.assertFalse((base / "Stage B" / "concept_sets.csv").is_file())
            self.assertTrue((base / "Stage B" / "Stage B" / "concepts.csv").is_file())
            self.assertTrue((base / "Stage B" / "Stage B" / "concept_sets.csv").is_file())

            # Verify canonical answer casing ('Other' reused in Sec 2) and shared answer UUID
            with open(base / "Stage A" / "Sec 1" / "concepts.csv", encoding="utf-8") as f:
                sec1 = list(csv.DictReader(f))
            with open(base / "Stage A" / "Sec 2" / "concepts.csv", encoding="utf-8") as f:
                sec2 = list(csv.DictReader(f))

            other_s1 = next(r for r in sec1 if r["name"] == "Other")
            other_s2 = next(r for r in sec2 if r["name"] == "Other")
            self.assertEqual(other_s1["uuid"], other_s2["uuid"])
            self.assertEqual(other_s1["datatype"], "N/A")

            cause = next(r for r in sec2 if r["name"] == "Cause")
            self.assertEqual(cause["answer.2"], "Other")
            # Duplicate DE 'Symptom' only created in Sec 1, not repeated in Sec 2 concepts.csv
            self.assertFalse(any(r["name"] == "Symptom" for r in sec2))
            # Yet 'Symptom' IS included as a child in Sec 2 concept_sets.csv
            with open(base / "Stage A" / "Sec 2" / "concept_sets.csv", encoding="utf-8") as f:
                sec2_set = list(csv.DictReader(f))[0]
            self.assertIn("Symptom", [sec2_set["child.1"], sec2_set["child.2"]])

            # Feed directly into CM-13 Plan to prove 0 errors, 0 cycles, and full stage/section pickup
            scanned = bci.scan_folder(str(base))
            export = bci.ServerExport.load(str(existing_csv))
            plan = bci.Plan(scanned, export, bci.LiveReads(None))
            counts = plan.counts()
            self.assertEqual(counts.get("ERROR", 0), 0, f"Unexpected CM-13 errors: {plan.logs}")

            # Stage A set must be created AFTER its child sections Sec 1 and Sec 2
            exec_names = [r.final_name for r in plan.execution_order()]
            self.assertIn("Stage A", exec_names)
            self.assertLess(exec_names.index("Sec 1"), exec_names.index("Stage A"))
            self.assertLess(exec_names.index("Sec 2"), exec_names.index("Stage A"))
            self.assertEqual(res["stages_count"], 2)
            self.assertEqual(res["sections_count"], 3)


if __name__ == "__main__":
    unittest.main()
