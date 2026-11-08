# -*- coding: utf-8 -*-
"""Unit tests for bahmni_concept_importer.py (standard library only).

Run:  python -m unittest -v test_bahmni_concept_importer
"""
import csv
import os
import tempfile
import unittest

try:
    import backend.modules.concepts.bahmni_concept_importer as B
except ImportError:
    import bahmni_concept_importer as B

U = "00000000-0000-4000-8000-%012d"          # helper to build readable UUIDs


def uid(n):
    return U % n


# ---------------------------------------------------------------- fixtures
def export_of(rows):
    """rows: (name, datatype, answers_string, uuid)"""
    return B.ServerExport.from_rows([
        {"EMR Concept Fully Specified Name": n, "EMR concept Data Type": d,
         "EMR Options (Answers)": a, "EMR Concept UUID": u} for (n, d, a, u) in rows])


def write_file(root, rel, kind, rows):
    """rows: dicts with uuid,name,datatype,(answers|children list), class ..."""
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = max([len(r.get("refs", [])) for r in rows] + [1])
    if kind == "concept":
        head = ["uuid", "name", "description", "class", "shortname", "datatype", "units",
                "High Normal", "Low Normal", "Allow Decimal", "locale", "synonym.1"]
        head += ["answer.%d" % i for i in range(1, n + 1)]
    else:
        head = ["uuid", "name", "description", "class", "shortname"]
        head += ["child.%d" % i for i in range(1, n + 1)]
    head += ["reference-term-source", "reference-term-code", "reference-term-relationship"]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for r in rows:
            line = []
            for h in head:
                if h.startswith(("answer.", "child.")):
                    i = int(h.split(".")[1]) - 1
                    refs = r.get("refs", [])
                    line.append(refs[i] if i < len(refs) else "")
                else:
                    line.append(r.get({"High Normal": "high", "Low Normal": "low",
                                       "Allow Decimal": "allow"}.get(h, h), ""))
            w.writerow(line)
    return path


def C(n, name, dt="Text", refs=(), **kw):
    d = {"uuid": uid(n), "name": name, "datatype": dt, "class": "Misc", "refs": list(refs)}
    d.update(kw)
    return d


def S(n, name, refs=(), **kw):
    d = {"uuid": uid(n), "name": name, "class": "Misc", "refs": list(refs)}
    d.update(kw)
    return d


class Live:
    """Fake live-read backend."""

    def __init__(self, data=None):
        self.data = data or {}
        self.calls = []

    def __call__(self, uuid):
        self.calls.append(uuid)
        return self.data.get(uuid)


def plan_for(tree, export_rows, live=None, cap=200, strict=False):
    with tempfile.TemporaryDirectory() as td:
        for rel, (kind, rows) in tree.items():
            write_file(td, rel, kind, rows)
        rows = B.scan_folder(td)
    lv = B.LiveReads(live, cap)
    return B.Plan(rows, export_of(export_rows), lv, strict), lv


def by_name(plan, name):
    return next(r for r in plan.recs if r.name == name)


# ---------------------------------------------------------------- tests
class NameHelpers(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(B.norm("  Cafe\u0301   Latte "), B.norm("CAFÉ LATTE"))
        self.assertEqual(B.clean("a \t b\u00a0c"), "a b c")


class Scanning(unittest.TestCase):
    def test_walk_order_case_insensitive_and_dynamic_columns(self):
        with tempfile.TemporaryDirectory() as td:
            write_file(td, "b/Concepts.CSV", "concept", [C(1, "B1")])
            write_file(td, "a/concept_sets.csv", "set", [S(2, "A set", ["x"])])
            write_file(td, "a/concepts.csv", "concept", [C(3, "A1", "Coded", ["p", "q", "r"])])
            write_file(td, "a/sub/concepts.csv", "concept", [C(4, "A-sub")])
            write_file(td, "concepts.csv", "concept", [C(5, "Root")])
            write_file(td, "a/other.csv", "concept", [C(6, "Ignored")])
            rows = B.scan_folder(td)
        # root files first, then a (concepts, sets, then sub), then b
        self.assertEqual([r.name for r in rows], ["Root", "A1", "A set", "A-sub", "B1"])
        self.assertEqual(rows[1].refs, ["p", "q", "r"])

    def test_malformed_rows_are_errors_and_blank_rows_skipped(self):
        tree = {"f/concepts.csv": ("concept", [
            C(1, "Ok"), dict(C(2, ""), name=""), dict(C(3, "NoUuid"), uuid=""),
            C(4, "BadType", "Weird"), {"uuid": "", "name": "", "datatype": ""}])}
        plan, _ = plan_for(tree, [])
        self.assertEqual(plan.counts()["ERROR"], 3)
        self.assertEqual(by_name(plan, "Ok").action, "CREATE")


class ConceptRules(unittest.TestCase):
    def test_reuse_same_name_and_datatype_even_if_uuid_differs(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "Pulse", "Numeric")])}
        plan, lv = plan_for(tree, [("pulse", "Numeric", "", uid(900))])
        r = by_name(plan, "Pulse")
        self.assertEqual((r.action, r.final_uuid, r.final_name), ("REUSE", uid(900), "pulse"))
        self.assertEqual(lv.count, 0)

    def test_datatype_differs_gets_question_mark(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "Pulse", "Numeric")])}
        plan, _ = plan_for(tree, [("Pulse", "Text", "", uid(900))])
        r = by_name(plan, "Pulse")
        self.assertEqual((r.action, r.final_name), ("CREATE_RENAMED", "Pulse?"))
        self.assertEqual(r.final_uuid, uid(1))             # keeps its file UUID

    def test_answer_role_na_gets_dot(self):
        tree = {"f/concepts.csv": ("concept", [
            C(1, "Yes", "N/A"), C(2, "Smoker", "Coded", ["Yes"])])}
        plan, _ = plan_for(tree, [("Yes", "Text", "", uid(900))])
        self.assertEqual(by_name(plan, "Yes").final_name, "Yes.")
        smoker = by_name(plan, "Smoker")
        self.assertEqual([f.name for f in smoker.final_refs], ["Yes."])

    def test_repeat_until_free_or_equivalent(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "X", "Numeric")])}
        ex = [("X", "Text", "", uid(900)), ("X?", "Text", "", uid(901)),
              ("X??", "Numeric", "", uid(902))]
        plan, _ = plan_for(tree, ex)
        r = by_name(plan, "X")
        self.assertEqual((r.action, r.final_uuid), ("REUSE", uid(902)))     # X?? is equivalent
        plan, _ = plan_for(tree, ex[:2])
        self.assertEqual(by_name(plan, "X").final_name, "X??")

    def test_uuid_taken_by_other_name_gets_deterministic_new_uuid(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "Fresh", "Text")])}
        plan, _ = plan_for(tree, [("Other", "Text", "", uid(1))])
        r = by_name(plan, "Fresh")
        self.assertEqual(r.action, "CREATE")
        self.assertNotEqual(r.final_uuid, uid(1))
        plan2, _ = plan_for(tree, [("Other", "Text", "", uid(1))])
        self.assertEqual(by_name(plan2, "Fresh").final_uuid, r.final_uuid)
        self.assertTrue(any(l["code"] == "NEW_UUID_ASSIGNED" for l in plan.logs))

    def test_coded_equal_answers_reuse_regardless_of_order(self):
        ex = [("Colour", "Coded", "Red; Blue", uid(900)), ("Red", "N/A", "", uid(901)),
              ("Blue", "N/A", "", uid(902))]
        tree = {"f/concepts.csv": ("concept", [
            C(1, "Blue", "N/A"), C(2, "Red", "N/A"), C(3, "Colour", "Coded", ["Blue", "Red"])])}
        plan, lv = plan_for(tree, ex)
        self.assertEqual(by_name(plan, "Colour").action, "REUSE")
        self.assertEqual(lv.count, 0)

    def test_coded_different_answers_renamed_and_cascade(self):
        ex = [("Colour", "Coded", "Red; Blue", uid(900)), ("Red", "N/A", "", uid(901)),
              ("Blue", "N/A", "", uid(902)), ("Form", "N/A", "", uid(903))]
        tree = {"f/concepts.csv": ("concept", [
            C(2, "Red", "N/A"), C(3, "Colour", "Coded", ["Red"]),
            C(4, "Q", "Coded", ["Colour"])])}
        plan, _ = plan_for(tree, ex)
        self.assertEqual(by_name(plan, "Colour").final_name, "Colour?")
        # Q does not exist on the server, but it now points at the renamed concept
        q = by_name(plan, "Q")
        self.assertEqual(q.action, "CREATE")
        self.assertEqual([f.name for f in q.final_refs], ["Colour?"])

    def test_cascade_makes_existing_parent_differ(self):
        ex = [("Yes", "Text", "", uid(900)), ("Smoker", "Coded", "Yes", uid(901))]
        tree = {"f/concepts.csv": ("concept", [
            C(1, "Yes", "N/A"), C(2, "Smoker", "Coded", ["Yes"])])}
        plan, _ = plan_for(tree, ex)
        self.assertEqual(by_name(plan, "Smoker").final_name, "Smoker?")

    def test_semicolon_names_fall_back_to_live_read(self):
        ex = [("Pace; fast", "N/A", "", uid(901)), ("Pace", "N/A", "", uid(902)),
              ("fast", "N/A", "", uid(903)),
              ("Speech", "Coded", "Pace; fast", uid(900))]
        tree = {"f/concepts.csv": ("concept", [
            C(1, "Pace", "N/A"), C(2, "fast", "N/A"), C(3, "Speech", "Coded", ["Pace", "fast"])])}
        live = Live({uid(900): {"datatype": {"name": "Coded"},
                                "answers": [{"uuid": uid(901)}]}})
        plan, lv = plan_for(tree, ex, live)
        self.assertEqual(lv.count, 1)                         # ambiguity -> one live read
        self.assertEqual(by_name(plan, "Speech").final_name, "Speech?")   # live answers differ
        live = Live({uid(900): {"datatype": {"name": "Coded"},
                                "answers": [{"uuid": uid(902)}, {"uuid": uid(903)}]}})
        plan, lv = plan_for(tree, ex, live)
        self.assertEqual(by_name(plan, "Speech").action, "REUSE")

    def test_live_read_cap_and_offline_are_conservative(self):
        ex = [("S", "N/A", "", uid(900)), ("a", "N/A", "", uid(901))]
        tree = {"f/concepts.csv": ("concept", [C(1, "a", "N/A")]),
                "f/concept_sets.csv": ("set", [S(2, "S", ["a"])])}
        live = Live({uid(900): {"set": True, "setMembers": [{"uuid": uid(901)}]}})
        plan, lv = plan_for(tree, ex, live)
        self.assertEqual(by_name(plan, "S").action, "REUSE")
        self.assertEqual(lv.count, 1)
        plan, lv = plan_for(tree, ex, live, cap=0)
        self.assertEqual(by_name(plan, "S").final_name, "S?")
        self.assertEqual(lv.capped, 1)
        plan, lv = plan_for(tree, ex, None)
        self.assertEqual(by_name(plan, "S").final_name, "S?")
        self.assertEqual(lv.unavailable, 1)

    def test_strict_set_check_reads_plain_na_concepts(self):
        ex = [("a", "N/A", "", uid(900))]
        tree = {"f/concepts.csv": ("concept", [C(1, "a", "N/A")])}
        plan, lv = plan_for(tree, ex, Live({uid(900): {"set": False}}))
        self.assertEqual((by_name(plan, "a").action, lv.count), ("REUSE", 0))
        plan, lv = plan_for(tree, ex, Live({uid(900): {"set": False}}), strict=True)
        self.assertEqual((by_name(plan, "a").action, lv.count), ("REUSE", 1))
        plan, lv = plan_for(tree, ex, Live({uid(900): {"set": True}}), strict=True)
        self.assertEqual(by_name(plan, "a").final_name, "a?")


class SetRules(unittest.TestCase):
    def test_set_and_concept_same_name_set_renamed_and_new_uuid_if_equal(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "Pain", "Text")]),
                "f/concept_sets.csv": ("set", [dict(S(1, "Pain", ["Pain"]))])}
        plan, _ = plan_for(tree, [])
        s = next(r for r in plan.recs if r.kind == "set")
        self.assertEqual(s.final_name, "Pain set")
        self.assertNotEqual(s.final_uuid, uid(1))
        # inside its own member list, the same name refers to the CONCEPT
        self.assertEqual([f.name for f in s.final_refs], ["Pain"])
        self.assertEqual(s.final_refs[0].rec.kind, "concept")

    def test_child_prefers_set_over_concept(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "Vitals", "Text"), C(2, "T", "Text")]),
                "f/concept_sets.csv": ("set", [S(3, "Vitals", ["T"]), S(4, "Top", ["Vitals"])])}
        plan, _ = plan_for(tree, [])
        top = next(r for r in plan.recs if r.name == "Top")
        self.assertEqual([f.name for f in top.final_refs], ["Vitals set"])

    def test_set_name_free_on_server_creates_in_file_order(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "a"), C(2, "b")]),
                "f/concept_sets.csv": ("set", [S(3, "G", ["b", "a"])])}
        plan, _ = plan_for(tree, [])
        g = by_name(plan, "G")
        self.assertEqual([f.name for f in g.final_refs], ["b", "a"])
        self.assertEqual(g.action, "CREATE")

    def test_set_name_on_server_as_non_set_datatype_renamed_without_read(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "a")]),
                "f/concept_sets.csv": ("set", [S(3, "G", ["a"])])}
        plan, lv = plan_for(tree, [("G", "Text", "", uid(900))])
        self.assertEqual(by_name(plan, "G").final_name, "G?")
        self.assertEqual(lv.count, 0)


class InImportAnalysis(unittest.TestCase):
    def test_identical_rows_same_uuid_are_one_record(self):
        tree = {"a/concepts.csv": ("concept", [C(1, "X")]),
                "b/concepts.csv": ("concept", [C(1, "X")])}
        plan, _ = plan_for(tree, [])
        self.assertEqual(len(plan.recs), 1)
        self.assertEqual(len(plan.recs[0].dup_rows), 1)
        self.assertEqual(len(B.plan_rows(plan)), 2)               # nothing silently dropped

    def test_identical_rows_different_uuid_merge_and_alias(self):
        tree = {"a/concepts.csv": ("concept", [C(1, "X")]),
                "b/concepts.csv": ("concept", [C(2, "x")])}
        plan, _ = plan_for(tree, [])
        self.assertEqual(plan.counts()["CREATE"], 1)
        rows = B.uuid_map_rows(plan)
        self.assertEqual({r[0] for r in rows}, {uid(1), uid(2)})
        self.assertEqual({r[2] for r in rows}, {uid(1)})

    def test_same_uuid_different_identity_later_gets_new_uuid(self):
        tree = {"a/concepts.csv": ("concept", [C(1, "X", "Text")]),
                "b/concepts.csv": ("concept", [C(1, "Y", "Text")])}
        plan, _ = plan_for(tree, [])
        self.assertEqual(by_name(plan, "X").final_uuid, uid(1))
        self.assertNotEqual(by_name(plan, "Y").final_uuid, uid(1))

    def test_question_type_keeps_name_na_nonanswer_gets_question_mark(self):
        tree = {"a/concepts.csv": ("concept", [C(1, "Z", "N/A")]),
                "b/concepts.csv": ("concept", [C(2, "Z", "Numeric")])}
        plan, _ = plan_for(tree, [])
        self.assertEqual([r.final_name for r in plan.recs], ["Z?", "Z"])

    def test_two_types_later_gets_suffix(self):
        tree = {"a/concepts.csv": ("concept", [C(1, "Z", "Text")]),
                "b/concepts.csv": ("concept", [C(2, "Z", "Numeric")])}
        plan, _ = plan_for(tree, [])
        self.assertEqual([r.final_name for r in plan.recs], ["Z", "Z?"])

    def test_sets_same_name_identical_members_merge_else_question_mark(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "a"), C(2, "b")]),
                "f/concept_sets.csv": ("set", [S(3, "G", ["a"]), S(4, "G", ["a"]),
                                               S(5, "G", ["b"])])}
        plan, _ = plan_for(tree, [])
        names = sorted(r.final_name for r in plan.primaries() if r.kind == "set")
        self.assertEqual(names, ["G", "G?"])

    def test_unresolved_reference_skipped_parent_continues(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "a"), C(2, "P", "Coded", ["a", "ghost"])])}
        plan, _ = plan_for(tree, [])
        p = by_name(plan, "P")
        self.assertEqual(p.action, "CREATE")
        self.assertEqual([f.name for f in p.final_refs], ["a"])
        self.assertTrue(any(l["code"] == "UNRESOLVED_REFERENCE" for l in plan.logs))

    def test_reference_found_on_server_is_used_read_only(self):
        tree = {"f/concepts.csv": ("concept", [C(2, "P", "Coded", ["Existing"])])}
        plan, _ = plan_for(tree, [("existing", "Text", "", uid(900))])
        self.assertEqual(by_name(plan, "P").final_refs[0].uuid, uid(900))

    def test_cycle_is_error_dependents_continue(self):
        tree = {"f/concepts.csv": ("concept", [
            C(1, "A", "Coded", ["B"]), C(2, "B", "Coded", ["A"]),
            C(3, "D", "Coded", ["A", "E"]), C(4, "E")])}
        plan, _ = plan_for(tree, [])
        self.assertEqual(by_name(plan, "A").action, "ERROR")
        self.assertEqual(by_name(plan, "B").action, "ERROR")
        d = by_name(plan, "D")
        self.assertEqual(d.action, "CREATE")
        self.assertEqual([f.name for f in d.final_refs], ["E"])

    def test_name_too_long_is_error(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "x" * 256), C(2, "y" * 255, "Numeric")])}
        plan, _ = plan_for(tree, [("y" * 255, "Text", "", uid(900))])
        self.assertEqual(by_name(plan, "x" * 256).action, "ERROR")
        self.assertEqual(by_name(plan, "y" * 255).action, "ERROR")   # '?' would make it 256


class Ordering(unittest.TestCase):
    def test_dependency_from_later_folder_created_right_before_dependent(self):
        tree = {"a/concepts.csv": ("concept", [C(1, "Parent", "Coded", ["Late"]), C(2, "Other")]),
                "z/concepts.csv": ("concept", [C(3, "Late", "N/A")])}
        plan, _ = plan_for(tree, [])
        self.assertEqual([r.final_name for r in plan.execution_order()],
                         ["Late", "Parent", "Other"])


class Determinism(unittest.TestCase):
    def test_plan_is_identical_on_rerun(self):
        tree = {"a/concepts.csv": ("concept", [C(1, "Yes", "N/A"), C(2, "Q", "Coded", ["Yes"]),
                                               C(3, "Z", "Text")]),
                "a/concept_sets.csv": ("set", [S(4, "Z", ["Q"])])}
        ex = [("Yes", "Text", "", uid(900)), ("Z", "Text", "", uid(1))]
        p1, _ = plan_for(tree, ex)
        p2, _ = plan_for(tree, ex)
        self.assertEqual(B.plan_rows(p1), B.plan_rows(p2))
        self.assertEqual(B.uuid_map_rows(p1), B.uuid_map_rows(p2))


class CsvMode(unittest.TestCase):
    def test_upload_files_only_new_records_ordered_and_chunked(self):
        tree = {"a/concepts.csv": ("concept", [
            C(1, "Old", "Text"), C(2, "A", "N/A"), C(3, "B", "N/A"),
            C(4, "P", "Coded", ["A", "B", "Old"])]),
            "a/concept_sets.csv": ("set", [S(5, "G", ["P"])])}
        plan, _ = plan_for(tree, [("Old", "Text", "", uid(900))])
        with tempfile.TemporaryDirectory() as out:
            files = B.write_upload_files(plan, out, chunk_size=2)
            self.assertEqual(files, ["001_concepts.csv", "002_concepts.csv", "003_concept_sets.csv"])
            with open(os.path.join(out, "001_concepts.csv"), encoding="utf-8") as fh:
                first = list(csv.DictReader(fh))
            with open(os.path.join(out, "002_concepts.csv"), encoding="utf-8") as fh:
                second = list(csv.DictReader(fh))
            with open(os.path.join(out, "003_concept_sets.csv"), encoding="utf-8") as fh:
                sets = list(csv.DictReader(fh))
            self.assertEqual([r["name"] for r in first], ["A", "B"])
            self.assertEqual([r["name"] for r in second], ["P"])
            self.assertEqual(second[0]["answer.3"], "Old")            # server concept referenced by name
            self.assertNotIn("Old", [r["name"] for r in first + second])   # never re-created
            self.assertEqual(sets[0]["child.1"], "P")
            with open(os.path.join(out, "upload_order.txt"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertLess(text.index("001_"), text.index("003_"))
            self.assertTrue(os.path.exists(os.path.join(out, "consolidated_review_not_for_upload.csv")))


class FakeApi:
    """Stands in for ApiClient.  Honours client-supplied UUIDs unless told not to."""

    def __init__(self, honour_uuid=True, taken_names=(), fail_names=()):
        self.store = {}
        self.posts = []
        self.honour = honour_uuid
        self.taken = {B.norm(n) for n in taken_names}
        self.fail = {B.norm(n) for n in fail_names}

    def get(self, path):
        uuid = path.split("/concept/")[1].split("?")[0]
        if uuid in self.store:
            return B.Resp(200, {"uuid": uuid})
        return B.Resp(404)

    def post(self, path, body):
        self.posts.append((path, body))
        if path != "/concept":
            return B.Resp(200, {})
        name = body["names"][0]["name"]
        if B.norm(name) in self.fail:
            return B.Resp(500 if False else 400, None, "some other validation error")
        if B.norm(name) in self.taken:
            return B.Resp(400, None, "Duplicate concept name '%s'" % name)
        uuid = body["uuid"] if self.honour else "ffffffff-0000-4000-8000-000000000001"
        self.store[uuid] = body
        return B.Resp(201, {"uuid": uuid})


class ApiExecution(unittest.TestCase):
    def setUp(self):
        self.tree = {"f/concepts.csv": ("concept", [
            C(1, "A", "N/A"), C(2, "P", "Coded", ["A"]), C(3, "N", "Numeric",
                                                          units="mmHg", high="140", low="90",
                                                          allow="true")]),
            "f/concept_sets.csv": ("set", [S(4, "G", ["P", "N"])])}
        self.maps = {"datatypes": {"coded": "dt-coded"}, "classes": {}}

    def run_exec(self, api, state_path):
        plan, _ = plan_for(self.tree, [])
        return plan, B.execute_api(plan, api, B.State(state_path), self.maps, 25, 0,
                                   sleep=lambda s: None)

    def test_creates_in_order_with_final_uuids_and_resumes_without_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            sp = os.path.join(td, "state.jsonl")
            api = FakeApi()
            plan, res = self.run_exec(api, sp)
            self.assertEqual(res.created, 4)
            self.assertEqual([p[1]["names"][0]["name"] for p in api.posts if p[0] == "/concept"],
                             ["A", "P", "N", "G"])
            g = api.posts[-1][1]
            self.assertTrue(g["set"])
            self.assertEqual(g["setMembers"], [uid(2), uid(3)])
            self.assertEqual(api.posts[1][1]["answers"], [uid(1)])
            self.assertEqual(api.posts[2][1]["units"], "mmHg")
            # second run: same plan, nothing created again
            api2 = FakeApi()
            plan2, res2 = self.run_exec(api2, sp)
            self.assertEqual((res2.created, res2.already, len(api2.posts)), (0, 4, 0))
            self.assertEqual(B.plan_rows(plan), B.plan_rows(plan2))

    def test_uuid_not_honoured_stops(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(B.StopRun) as cm:
                self.run_exec(FakeApi(honour_uuid=False), os.path.join(td, "s.jsonl"))
            self.assertIn("csv", str(cm.exception).lower())

    def test_duplicate_name_requests_replan_and_replan_renames(self):
        with tempfile.TemporaryDirectory() as td:
            api = FakeApi(taken_names=["P"])
            plan, res = self.run_exec(api, os.path.join(td, "s.jsonl"))
            self.assertEqual(res.replan_name, "p")
            rows, _ = None, None
            with tempfile.TemporaryDirectory() as t2:
                for rel, (kind, rws) in self.tree.items():
                    write_file(t2, rel, kind, rws)
                rows = B.scan_folder(t2)
            plan2 = B.Plan(rows, export_of([]), B.LiveReads(None), False, {"p"})
            self.assertEqual(by_name(plan2, "P").final_name, "P?")
            self.assertEqual(by_name(plan2, "G").final_refs[0].name, "P?")

    def test_failed_dependency_skips_dependents_and_continues(self):
        with tempfile.TemporaryDirectory() as td:
            api = FakeApi(fail_names=["A"])
            plan, res = self.run_exec(api, os.path.join(td, "s.jsonl"))
            self.assertEqual([r.name for r, _ in res.failed], ["A"])
            self.assertEqual({r.name for r in res.skipped}, {"P", "G"})
            self.assertEqual(res.created, 1)                     # N is independent


class CheckOnly(unittest.TestCase):
    def test_check_only_reports_matches_and_missing(self):
        tree = {"f/concepts.csv": ("concept", [C(1, "A", "Text"), C(2, "B", "Numeric")])}
        plan, _ = plan_for(tree, [])
        with tempfile.TemporaryDirectory() as out:
            B.write_reports(plan, out)
            fresh = os.path.join(out, "fresh.csv")
            with open(fresh, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["EMR Concept Fully Specified Name", "EMR Concept UUID",
                            "EMR concept Data Type", "EMR Options (Answers)"])
                w.writerow(["A", uid(1), "Text", ""])
            args = B.build_parser().parse_args(["--check-only", "--export", fresh, "--out-dir", out])
            self.assertEqual(B.run_check_only(args), 1)           # B is missing
            with open(fresh, "a", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh).writerow(["B", uid(2), "Numeric", ""])
            self.assertEqual(B.run_check_only(args), 0)


class Misc(unittest.TestCase):
    def test_base_url_normalisation(self):
        for u in ("https://h", "https://h/", "https://h/openmrs", "https://h/openmrs/ws/rest/v1"):
            self.assertEqual(B.normalize_base_url(u), "https://h/openmrs/ws/rest/v1")

    def test_run_window(self):
        import datetime
        w = B.parse_window("22:00-06:00")
        self.assertTrue(B.in_window(w, datetime.datetime(2026, 1, 1, 23, 0)))
        self.assertTrue(B.in_window(w, datetime.datetime(2026, 1, 1, 5, 59)))
        self.assertFalse(B.in_window(w, datetime.datetime(2026, 1, 1, 12, 0)))

    def test_answer_segmentation_ambiguity(self):
        ex = export_of([("A; B", "N/A", "", uid(1)), ("A", "N/A", "", uid(2)),
                        ("B", "N/A", "", uid(3)), ("C", "Coded", "A; B", uid(4)),
                        ("D", "Coded", "A; Z", uid(5))])
        self.assertIsNone(ex.answer_uuids(ex.by_uuid[uid(4)]))        # 2 segmentations
        self.assertIsNone(ex.answer_uuids(ex.by_uuid[uid(5)]))        # unknown name
        ex2 = export_of([("A", "N/A", "", uid(2)), ("B", "N/A", "", uid(3)),
                         ("C", "Coded", "B; A", uid(4))])
        self.assertEqual(ex2.answer_uuids(ex2.by_uuid[uid(4)]), [uid(3), uid(2)])


if __name__ == "__main__":
    unittest.main()
