"""
O3 Form Schema Generator — fixed version.

This is your original script with three real bugs fixed. See the
accompanying notes for the full explanation; short version:

1. SKIP PATTERNS / VALIDATION (HIDEFIELD, SETMANDATORYFIELD, SHOWERROR, SHOWWARNING)
   Your DHIS2 rule conditions compare against option CODES, e.g.
       #{Number_of_Newborns}=='2'
   but O3 form fields store the ANSWER'S CONCEPT UUID as their value, not
   the DHIS2 code. So the translated expression ended up as
       numberOfNewborns!=='2'
   which can never match anything (the runtime value is a UUID like
   '354b8360-...', never the string '2'), so the hide/validator/required
   rule silently never fires in the browser.

   Your script *tried* to fix this with `build_code_concept_uuid_map`,
   but that function reads a CSV column called "Answers" that doesn't
   exist after your column-remapping step (it's "EMR Options (Answers)"),
   AND even if you fixed that key, your concepts CSV doesn't store
   "code|uuid" pairs in that column at all — it just has semicolon
   separated answer labels with no codes. So the map was always empty
   and every coded comparison was left un-translated.

   Fix: for every data element that has a DHIS2 optionSet, this script
   looks up each option's CODE and NAME, matches the NAME to your
   concepts CSV (same fuzzy matching you already use for answers), and
   builds a real {code: concept_uuid} map per data element. Rule
   conditions are then translated per-rule using only the maps for the
   data elements they actually reference.

2. CONDITIONAL REQUIRED (SETMANDATORYFIELD)
   Your script did `question["required"] = "<raw js expression>"`.
   O3's `required` property only accepts `true`/`false` or a
   `{"type": "conditionalRequired", "referenceQuestionId": ...,
   "referenceQuestionAnswers": [...]}` object — a raw expression string
   is not a recognized shape, so O3 just ignores it and treats the
   field as not-required.

   Fix: conditional "required" is now expressed as a validator instead
   (the pattern used in real AMPATH/O3 forms):
       {"type": "js_expression",
        "failsWhenExpression": "<condition-is-true> && isEmpty(myValue)",
        "message": "This field is required"}
   This works for arbitrary conditions (not just "one reference
   question equals one answer"), which your DHIS2 rules often are
   (compound conditions with && / ||).

3. FORM REPEATABILITY (programStage.repeatable)
   Writing a bare top-level `"repeatable": true` and calling it done
   isn't enough — O3's React Form Engine actually makes a group of
   fields repeat by nesting them inside a `type: "obsGroup"` question
   whose `questionOptions.rendering` is `"repeating"`, with a real
   grouping concept (a ConvSet-class concept in the dictionary) and a
   `repeatOptions` object. That's the pattern in your working
   nurse-followup-sheet_form.json sample.

   Fix: for every repeatable stage, this script now nests all of the
   stage's questions inside one such obsGroup (keeping the top-level
   `"repeatable": true` too, matching your sample) and generates a
   `PLACEHOLDER-CONCEPT-UUID-<STAGE-NAME>` grouping concept, exactly
   like your sample does. You still need to create a real ConvSet
   concept for each repeatable stage in the dictionary and swap the
   placeholder for its UUID before the form will load — there's no way
   to auto-generate a legitimate new concept from this script. The
   `_summary.json` and run log list exactly which stages need that.

   Also fixed: once fields live inside a repeating group, any
   hideWhenExpression/failsWhenExpression that references ANOTHER
   field must call `useFieldValue('otherFieldId')` instead of using
   the bare field id — bare ids don't reliably resolve per-repeat-
   instance. This script now rewrites those references automatically
   for anything moved into a repeating group.
"""

import csv
import json
import queue
import re
import threading
import uuid as uuid_mod
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional




YES_NO_ANSWERS = [
    {"concept": "1065AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "label": "Yes"},
    {"concept": "1066AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "label": "No"},
]

COLUMN_MAP_NEW_TO_OLD = {
    "Fully Specified Name": "EMR Concept Fully Specified Name",
    "name": "EMR Concept Fully Specified Name",
    "Name": "EMR Concept Fully Specified Name",
    "Short Name": "EMR Concept short name",
    "shortname": "EMR Concept short name",
    "UUID": "EMR Concept UUID",
    "uuid": "EMR Concept UUID",
    "Datatype": "EMR concept Data Type",
    "datatype": "EMR concept Data Type",
    "Answers": "EMR Options (Answers)",
    "answers": "EMR Options (Answers)",
}
OLD_COLUMNS = {"EMR Concept Fully Specified Name", "EMR Concept UUID", "EMR concept Data Type", "EMR Options (Answers)"}


def normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def camel_case(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value or "")
    if not words:
        return "question"
    return words[0].lower() + "".join(word[:1].upper() + word[1:] for word in words[1:])


def read_concepts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return rows
    if OLD_COLUMNS.issubset(rows[0].keys()):
        return rows
    mapped = []
    for row in rows:
        new_row = {}
        for key, value in row.items():
            if key is None:
                continue
            new_key = COLUMN_MAP_NEW_TO_OLD.get(key, key)
            new_row[new_key] = value
        if "EMR Concept Fully Specified Name" not in new_row:
            for k in ("name", "Name", "concept_name", "Fully Specified Name"):
                if row.get(k):
                    new_row["EMR Concept Fully Specified Name"] = row[k]
                    break
            else:
                new_row["EMR Concept Fully Specified Name"] = ""
        mapped.append(new_row)
    return mapped


def build_concept_map(concepts: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    name_map = {}
    for row in concepts:
        name = row.get("EMR Concept Fully Specified Name", "").strip()
        short = row.get("EMR Concept short name", "").strip()
        uuid = row.get("EMR Concept UUID", "").strip()
        if name:
            name_map[name.casefold()] = row
        if short and short.casefold() != name.casefold():
            name_map.setdefault(short.casefold(), row)
        normal = normalise(name)
        if normal and normal not in name_map:
            name_map[normal] = row
        if uuid:
            name_map[uuid] = row
    return name_map


def find_concept(name: str, concept_map: dict[str, dict[str, str]], concepts: list[dict[str, str]]) -> dict[str, str] | None:
    key = (name or "").strip()
    if not key:
        return None
    row = concept_map.get(key.casefold())
    if row:
        return row
    row = concept_map.get(normalise(key))
    if row:
        return row
    import difflib
    candidates = [v["EMR Concept Fully Specified Name"] for v in concepts if v.get("EMR Concept Fully Specified Name")]
    closest = difflib.get_close_matches(key, candidates, n=1, cutoff=0.85)
    if closest:
        return concept_map.get(closest[0].casefold())
    return None


def resolve_datatype(raw_value_type: str, has_options: bool) -> str:
    if has_options:
        return "Coded"
    dt_map = {
        "TEXT": "Text", "LONG_TEXT": "Text", "EMAIL": "Text", "PHONE_NUMBER": "Text",
        "URL": "Text", "USERNAME": "Text", "ORGANISATION_UNIT": "Text",
        "TRACKER_ASSOCIATE": "Text", "MULTI_TEXT": "Text", "FILE_RESOURCE": "Text",
        "IMAGE": "Text", "COORDINATE": "Text",
        "INTEGER": "Numeric", "INTEGER_POSITIVE": "Numeric", "INTEGER_NEGATIVE": "Numeric",
        "INTEGER_ZERO_OR_POSITIVE": "Numeric", "NUMBER": "Numeric", "PERCENTAGE": "Numeric",
        "UNIT_INTERVAL": "Numeric",
        "DATE": "Date", "AGE": "Date",
        "DATETIME": "Datetime",
        "TIME": "Time",
        "BOOLEAN": "Boolean", "TRUE_ONLY": "Boolean",
    }
    return dt_map.get((raw_value_type or "").strip().upper(), "Text")


def rendering_from_datatype(concept_datatype: str, dhis_value_type: str) -> str:
    dt = (concept_datatype or dhis_value_type or "").casefold()
    if "date" in dt:
        return "date"
    if any(w in dt for w in ("numeric", "integer", "decimal", "float")):
        return "number"
    return "text"


def determine_rendering(answer_names: list[str], concept_datatype: str, dhis_value_type: str) -> str:
    if {n.casefold() for n in answer_names} == {"yes", "no"}:
        return "radio"
    if not answer_names:
        return rendering_from_datatype(concept_datatype, dhis_value_type)
    if dhis_value_type == "MULTI_TEXT":
        return "checkbox" if len(answer_names) <= 5 else "checkbox-searchable"
    if len(answer_names) <= 4:
        return "radio"
    return "select"


def unique_uuid(occupied: set[str]) -> str:
    while True:
        value = str(uuid_mod.uuid4())
        if value not in occupied:
            occupied.add(value)
            return value


def parse_option_string(options_str: str) -> list[str]:
    labels = []
    for part in (options_str or "").split(";"):
        part = re.sub(r"^\s*[^:]+:\s*", "", part).strip()
        if part:
            labels.append(part)
    return labels


def generate_question_id(form_name: str, used_ids: defaultdict[str, int]) -> str:
    base_id = camel_case(form_name)
    used_ids[base_id] += 1
    return base_id if used_ids[base_id] == 1 else f"{base_id}{used_ids[base_id]}"


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    import zipfile
    from xml.etree import ElementTree as ET
    NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            shared_root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = ["".join(item.itertext()) for item in shared_root.findall("x:si", NS)]
        sheet_root = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))

    raw_rows: list[dict[str, str]] = []
    for row in sheet_root.findall(".//x:sheetData/x:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("x:c", NS):
            raw = cell.findtext("x:v", default="", namespaces=NS)
            if cell.get("t") == "s":
                raw = shared[int(raw)]
            elif cell.get("t") == "inlineStr":
                inline = cell.find("x:is", NS)
                raw = "".join(inline.itertext()) if inline is not None else ""
            col = re.match(r"[A-Z]+", cell.get("r", "")).group(0)
            values[col] = raw
        raw_rows.append(values)
    if not raw_rows:
        raise ValueError("Excel has no rows")
    headers = raw_rows[0]
    return [{headers[c]: v for c, v in raw.items() if c in headers} for raw in raw_rows[1:]]


class DhisConditionTranslator:
    DATA_ELEMENT_REF = re.compile(r"#\{([^}]+)\}")

    FUNC_MAP = {
        "d2:hasValue": lambda args, qid_map: f"!isEmpty({qid_map.get(args[0], args[0])})",
        "d2:validatePattern": lambda args, qid_map: f"new RegExp({args[1]}).test({qid_map.get(args[0], args[0])})",
        "d2:count": lambda args, qid_map: f"count_{args[0]}",
        "d2:daysBetween": lambda args, qid_map: f"daysBetween({qid_map.get(args[0], args[0])}, {qid_map.get(args[1], args[1])})",
        "d2:zing": lambda args, qid_map: f"Zing({','.join(qid_map.get(a, a) for a in args)})",
        "VALUE": lambda args, qid_map: qid_map.get(args[0], args[0]),
    }

    @classmethod
    def translate(cls, condition: str, qid_map: dict[str, str],
                  var_qid_map: dict[str, str] | None = None,
                  code_uuid_map: dict[str, str] | None = None) -> str:
        if not condition:
            return ""
        expr = condition.strip()
        merged = dict(qid_map)
        if var_qid_map:
            merged.update(var_qid_map)

        for func_name, handler in cls.FUNC_MAP.items():
            pattern = re.compile(re.escape(func_name) + r"\(([^)]*)\)")
            def replacer(m, fn=func_name, h=handler):
                raw_args = m.group(1)
                args = cls._split_args(raw_args)
                return h(args, merged)
            expr = pattern.sub(replacer, expr)
        expr = cls.DATA_ELEMENT_REF.sub(lambda m: merged.get(m.group(1), m.group(1)), expr)
        expr = cls._translate_operators(expr)
        if code_uuid_map:
            # Replace quoted DHIS2 option codes ('1', '2', ...) with the
            # matching EMR answer concept UUID, so the runtime comparison
            # is against the same value the form engine actually stores.
            expr = re.sub(
                r"(===|!==)(\s*)'([^']+)'",
                lambda m: f"{m.group(1)}{m.group(2)}'{code_uuid_map.get(m.group(3), m.group(3))}'",
                expr,
            )
        return expr

    @classmethod
    def _split_args(cls, raw: str) -> list[str]:
        args: list[str] = []
        current = ""
        depth = 0
        in_str = False
        for ch in raw:
            if ch == "'" and not in_str:
                in_str = True
                current += ch
            elif ch == "'" and in_str:
                in_str = False
                current += ch
            elif ch in ("(", "[") and not in_str:
                depth += 1
                current += ch
            elif ch in (")", "]") and not in_str:
                depth -= 1
                current += ch
            elif ch == "," and depth == 0 and not in_str:
                args.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            args.append(current.strip())
        return args

    @classmethod
    def _translate_operators(cls, expr: str) -> str:
        expr = re.sub(r"!=", "__NEQ__", expr)
        expr = re.sub(r"==", "__EQ__", expr)
        expr = re.sub(r"(?<![<>!_])=", "===", expr)
        expr = expr.replace("__EQ__", "===")
        expr = expr.replace("__NEQ__", "!==")
        expr = re.sub(r"!===+", "!==", expr)
        expr = re.sub(r"====+", "===", expr)
        return expr


def build_element_map(stage: dict, metadata: dict, excel_rows_by_stage: dict[str, list[dict[str, str]]] | None) -> dict[str, dict]:
    """Build a map of DHIS2 data element ID -> {question_id, form_name, concept, answer_names, ...}"""
    stage_id = stage["id"]
    sections_raw = [s for s in metadata.get("programStageSections", []) if s.get("programStage", {}).get("id") == stage_id]
    if not sections_raw:
        psdes = sorted(stage.get("programStageDataElements", []), key=lambda d: d.get("sortOrder", 999999))
        if psdes:
            sections_raw = [{"name": stage.get("name", ""), "sortOrder": 0,
                            "dataElements": [{"id": p["dataElement"]["id"]} for p in psdes]}]
        else:
            return {}
    sections_raw.sort(key=lambda s: (s.get("sortOrder", 999999), s.get("name", "")))

    metadata_des_by_id = {de["id"]: de for de in metadata.get("dataElements", [])}
    stage_rows = (excel_rows_by_stage or {}).get(stage.get("name", ""), [])
    by_dhis_id = {r.get("Data Element ID", "").strip(): r for r in stage_rows}

    element_map: dict[str, dict] = {}
    used_ids: defaultdict[str, int] = defaultdict(int)

    for sec in sections_raw:
        for element_ref in sec.get("dataElements", []):
            dhis_id = element_ref.get("id", "")
            source = by_dhis_id.get(dhis_id)
            dhis_value_type = ""
            if not source:
                meta_de = metadata_des_by_id.get(dhis_id)
                if not meta_de:
                    continue
                dhis_value_type = meta_de.get("valueType", "")
                source = {
                    "Data Element ID": meta_de.get("id", ""),
                    "Data Element Name": meta_de.get("name", ""),
                    "Form Name": meta_de.get("formName", "") or meta_de.get("name", ""),
                    "Data Type": dhis_value_type,
                    "Options": "",
                }
            else:
                meta_de = metadata_des_by_id.get(dhis_id)
                if meta_de:
                    dhis_value_type = meta_de.get("valueType", "")
            form_name = source.get("Form Name", "").strip() or source.get("Data Element Name", "").strip()
            options_str = source.get("Options", "")
            element_map[dhis_id] = {
                "dhis_id": dhis_id,
                "question_id": generate_question_id(form_name, used_ids),
                "form_name": form_name,
                "data_element_name": source.get("Data Element Name", ""),
                "raw_datatype": source.get("Data Type", ""),
                "dhis_value_type": dhis_value_type,
                "options_str": options_str,
            }
    return element_map


def enrich_element_with_concept(element: dict, concept_map: dict, concepts: list[dict[str, str]]) -> None:
    elem_name = element["data_element_name"]
    override_map = {"KczDjcq8Cdd": "ANC, Parity", "WVUda4sIj1J": "ayh, abortion"}
    override = override_map.get(element["dhis_id"])
    concept = find_concept(override, concept_map, concepts) if override else None
    if concept is None:
        concept = find_concept(elem_name, concept_map, concepts)
    answer_names = parse_option_string(element.get("options_str", ""))
    if concept is None:
        element["review_required"] = True
        element["answer_names"] = answer_names
        return
    element["concept"] = concept
    concept_answers = concept.get("EMR Options (Answers)", "").strip()
    if not answer_names:
        answer_names = [p.strip() for p in concept_answers.split(";") if p.strip()]
    element["answer_names"] = answer_names


def build_section_questions(sec: dict, element_map: dict[str, dict], metadata: dict,
                            concept_map: dict, concepts: list[dict[str, str]]) -> list[dict]:
    questions: list[dict] = []
    for element_ref in sec.get("dataElements", []):
        dhis_id = element_ref.get("id", "")
        el = element_map.get(dhis_id)
        if el is None:
            continue
        answer_names = el.get("answer_names", [])
        has_options = bool(answer_names)
        concept = el.get("concept")
        if concept:
            datatype = concept.get("EMR concept Data Type", "").strip()
            concept_uuid = concept["EMR Concept UUID"]
        else:
            datatype = ""
            concept_uuid = f"no-concept-{el['question_id']}"
        if not datatype:
            datatype = resolve_datatype(el.get("raw_datatype", ""), has_options)
        rendering = determine_rendering(answer_names, datatype, el.get("dhis_value_type", ""))
        q_opts: dict = {"rendering": rendering, "concept": concept_uuid}

        if rendering in ("radio", "select", "checkbox", "checkbox-searchable") and answer_names:
            if {n.casefold() for n in answer_names} == {"yes", "no"}:
                q_opts["answers"] = YES_NO_ANSWERS
            else:
                answers_list = []
                for an in answer_names:
                    ans = find_concept(an, concept_map, concepts)
                    if ans:
                        answers_list.append({"concept": ans["EMR Concept UUID"], "label": an})
                if not answers_list:
                    for an in answer_names:
                        answers_list.append({"concept": f"no-concept-{normalise(an)}", "label": an})
                if answers_list:
                    q_opts["answers"] = answers_list

        question: dict = {
            "label": el.get("form_name", ""),
            "id": el["question_id"],
            "type": "obs",
            "questionOptions": q_opts,
            "validators": [],
        }
        if el.get("review_required"):
            question["_review_required"] = True
        el["question_obj"] = question
        questions.append(question)
    return questions


# ---------------------------------------------------------------------------
# FIX #1: real DHIS2-option-code -> EMR-concept-UUID mapping.
#
# The old build_code_concept_uuid_map() read a CSV column ("Answers") that
# doesn't exist post-remap and expected "code|uuid" values that your CSV
# never contains, so it always returned {} and every coded comparison in a
# rule condition ('1', '2', '3'...) was left untranslated -- which is why
# hide/validate/require rules involving a coded field never actually fired
# in the browser (form values are concept UUIDs, not DHIS2 codes).
#
# This builds it correctly: for every data element that has a DHIS2
# optionSet, match each option's NAME to a row in your concepts CSV (the
# same matching already used for building question answers) and record
# {code: concept_uuid}.
# ---------------------------------------------------------------------------

def build_de_code_uuid_map(metadata: dict, concept_map: dict, concepts: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    all_options = metadata.get("options", [])
    optionset_code_uuid: dict[str, dict[str, str]] = {}
    for opt_set in metadata.get("optionSets", []):
        os_id = opt_set.get("id")
        if not os_id:
            continue
        opts = [o for o in all_options if o.get("optionSet", {}).get("id") == os_id]
        code_map: dict[str, str] = {}
        is_yes_no = {(o.get("name") or "").strip().casefold() for o in opts} == {"yes", "no"}
        for o in opts:
            code = (o.get("code") or "").strip()
            name = (o.get("name") or "").strip()
            if not code or not name:
                continue
            if is_yes_no:
                # build_section_questions renders Yes/No option sets using
                # the hardcoded YES_NO_ANSWERS concepts, not whatever a
                # name-lookup would find in the concepts CSV -- match that
                # so hide/validator expressions compare against the same
                # UUID the question will actually use.
                code_map[code] = YES_NO_ANSWERS[0]["concept"] if name.casefold() == "yes" else YES_NO_ANSWERS[1]["concept"]
                continue
            concept = find_concept(name, concept_map, concepts)
            if concept:
                code_map[code] = concept["EMR Concept UUID"]
        optionset_code_uuid[os_id] = code_map

    de_code_uuid: dict[str, dict[str, str]] = {}
    for de in metadata.get("dataElements", []):
        opt_set = de.get("optionSet")
        os_id = opt_set.get("id") if isinstance(opt_set, dict) else opt_set
        if os_id and os_id in optionset_code_uuid:
            de_code_uuid[de["id"]] = optionset_code_uuid[os_id]
        elif de.get("valueType") == "BOOLEAN":
            # DHIS2 booleans compare against 'true'/'1' style literals in
            # rules; map both common encodings onto the Yes/No answers
            # already used for boolean questions in build_section_questions.
            de_code_uuid[de["id"]] = {
                "true": YES_NO_ANSWERS[0]["concept"], "1": YES_NO_ANSWERS[0]["concept"],
                "false": YES_NO_ANSWERS[1]["concept"], "0": YES_NO_ANSWERS[1]["concept"],
            }
    return de_code_uuid


def build_var_to_de_map(metadata: dict) -> dict[str, str]:
    var_to_de: dict[str, str] = {}
    for prv in metadata.get("programRuleVariables", []):
        de = prv.get("dataElement")
        de_id = de.get("id") if isinstance(de, dict) else de
        if de_id:
            var_to_de[prv["name"]] = de_id
    return var_to_de


def build_condition_code_uuid_map(condition: str, var_to_de: dict[str, str],
                                   de_code_uuid_map: dict[str, dict[str, str]]) -> dict[str, str]:
    """For one rule condition, merge the code->uuid maps of every data
    element it actually references (via program rule variable names)."""
    merged: dict[str, str] = {}
    for var_name in re.findall(r"#\{([^}]+)\}", condition):
        de_id = var_to_de.get(var_name)
        if de_id and de_id in de_code_uuid_map:
            merged.update(de_code_uuid_map[de_id])
    return merged


def parse_rule_condition_to_hide(rule: dict, element_map: dict[str, dict],
                                 var_qid_map: dict[str, str] | None = None,
                                 code_uuid_map: dict[str, str] | None = None) -> str | None:
    condition = rule.get("condition", "").strip()
    if not condition:
        return None
    qid_map = {did: info["question_id"] for did, info in element_map.items()}
    try:
        return DhisConditionTranslator.translate(condition, qid_map, var_qid_map, code_uuid_map)
    except Exception:
        return None


def build_validator_for_rule(rule: dict, action: dict, element_map: dict[str, dict], rule_type: str,
                              var_qid_map: dict[str, str] | None = None,
                              code_uuid_map: dict[str, str] | None = None) -> dict | None:
    condition = rule.get("condition", "").strip()
    if not condition:
        return None
    qid_map = {did: info["question_id"] for did, info in element_map.items()}
    try:
        translated = DhisConditionTranslator.translate(condition, qid_map, var_qid_map, code_uuid_map)
    except Exception:
        return None
    if rule_type == "SHOWERROR":
        return {"type": "js_expression", "failsWhenExpression": translated, "message": action.get("content", "") or "Invalid value"}
    if rule_type == "SHOWWARNING":
        return {"type": "warning", "failsWhenExpression": translated, "message": action.get("content", "") or "Warning"}
    return None


# ---------------------------------------------------------------------------
# FIX #3 (real fix, not a no-op removal): O3 repeatable forms.
#
# Your nurse-followup-sheet_form.json sample shows the actual working
# pattern: all the stage's fields get nested INSIDE one obsGroup question
# with questionOptions.rendering = "repeating" and a grouping concept
# (a real ConvSet concept in the dictionary -- the sample uses a
# PLACEHOLDER-CONCEPT-UUID-... token because that concept still has to be
# created manually). The top-level schema "repeatable": true key from your
# sample is also kept, in case the O3 version you're on still reads it.
#
# One more thing the sample makes clear: once fields live inside a
# repeating group, a hideWhenExpression/failsWhenExpression that
# references ANOTHER field must use useFieldValue('otherFieldId') instead
# of the bare field id -- e.g. useFieldValue('weightChange')!=='1' rather
# than weightChange!=='1'. Bare ids do not reliably resolve across the
# repeat's per-instance scope. myValue (the field's own value) is left
# untouched.
# ---------------------------------------------------------------------------

def wrap_cross_field_refs(expr: str, valid_qids: set[str]) -> str:
    if not expr or not valid_qids:
        return expr
    ordered = sorted(valid_qids, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(q) for q in ordered) + r")\b")

    def replacer(m):
        token = m.group(1)
        if token == "myValue":
            return token
        # don't double-wrap something already inside useFieldValue('...')
        start = m.start()
        preceding = expr[max(0, start - 14):start]
        if "useFieldValue(" in preceding and preceding.rstrip().endswith("'"):
            return token
        return f"useFieldValue('{token}')"

    return pattern.sub(replacer, expr)


def make_repeating_obsgroup_section(stage_name: str, json_sections: list[dict], occupied_qids: set[str]) -> dict:
    """Collapse every section's questions for a repeatable stage into a
    single obsGroup question with rendering 'repeating', matching the
    known-working nurse-followup-sheet pattern."""
    all_questions: list[dict] = []
    valid_qids: set[str] = set()
    for sec in json_sections:
        for q in sec.get("questions", []):
            valid_qids.add(q["id"])
    for sec in json_sections:
        for q in sec.get("questions", []):
            if "hide" in q and "hideWhenExpression" in q["hide"]:
                q["hide"]["hideWhenExpression"] = wrap_cross_field_refs(q["hide"]["hideWhenExpression"], valid_qids)
            for v in q.get("validators", []) or []:
                if "failsWhenExpression" in v:
                    v["failsWhenExpression"] = wrap_cross_field_refs(v["failsWhenExpression"], valid_qids)
            if "calculate" in q:
                q["calculate"] = wrap_cross_field_refs(q["calculate"], valid_qids)
            all_questions.append(q)

    used_ids: defaultdict[str, int] = defaultdict(int)
    group_id = generate_question_id(f"{stage_name} Entry", used_ids)
    while group_id in occupied_qids:
        used_ids[group_id] += 1
        group_id = f"{group_id}{used_ids[group_id]}"
    occupied_qids.add(group_id)

    placeholder_concept = "PLACEHOLDER-CONCEPT-UUID-" + re.sub(r"[^A-Za-z0-9]+", "-", stage_name).strip("-").upper()

    obs_group = {
        "label": f"{stage_name} Entry",
        "id": group_id,
        "type": "obsGroup",
        "questionOptions": {
            "rendering": "repeating",
            "concept": placeholder_concept,
            "repeatOptions": {},
        },
        "questions": all_questions,
    }
    return {"label": stage_name, "isExpanded": "true", "questions": [obs_group]}


def build_var_to_qid(element_map: dict[str, dict], metadata: dict) -> dict[str, str]:
    var_to_qid: dict[str, str] = {}
    for prv in metadata.get("programRuleVariables", []):
        de = prv.get("dataElement")
        if isinstance(de, dict):
            de_id = de.get("id")
        else:
            de_id = de
        if de_id and de_id in element_map:
            var_to_qid[prv.get("name", "")] = element_map[de_id]["question_id"]
    return var_to_qid


def apply_rules_to_schema(schema_data: dict, stage: dict, metadata: dict, element_map: dict[str, dict],
                           concept_map: dict, concepts: list[dict[str, str]] | None = None) -> None:
    stage_id = stage["id"]
    rules = [r for r in metadata.get("programRules", []) if r.get("programStage", {}).get("id") == stage_id]
    actions = metadata.get("programRuleActions", [])
    var_qid_map = build_var_to_qid(element_map, metadata)
    var_to_de = build_var_to_de_map(metadata)
    de_code_uuid_map = build_de_code_uuid_map(metadata, concept_map, concepts or [])

    question_by_id: dict[str, dict] = {}
    for sec in schema_data.get("sections", []):
        for q in sec.get("questions", []):
            question_by_id[q["id"]] = q

    de_question_map: dict[str, str] = {did: info["question_id"] for did, info in element_map.items()}

    for rule in rules:
        condition = rule.get("condition", "").strip()
        # Build the code->uuid map scoped to exactly the fields THIS
        # condition references, rather than one giant global (and
        # previously always-empty) map.
        code_uuid_map = build_condition_code_uuid_map(condition, var_to_de, de_code_uuid_map) if condition else None
        rule_actions = [a for a in actions if a.get("programRule", {}).get("id") == rule["id"]]
        for action in rule_actions:
            a_type = action.get("programRuleActionType", "")
            de_id = action.get("dataElement", {}).get("id") if isinstance(action.get("dataElement"), dict) else action.get("dataElement")
            q_id = de_question_map.get(de_id) if de_id else None
            q = question_by_id.get(q_id) if q_id else None

            if a_type == "HIDEFIELD" and q is not None:
                hide_expr = parse_rule_condition_to_hide(rule, element_map, var_qid_map, code_uuid_map)
                if hide_expr:
                    q["hide"] = {"hideWhenExpression": hide_expr}

            elif a_type == "HIDESECTION":
                sec_label = action.get("content", "").strip() or action.get("location", "").strip()
                if sec_label:
                    for sec in schema_data.get("sections", []):
                        if normalise(sec.get("label", "")) == normalise(sec_label):
                            hide_expr = parse_rule_condition_to_hide(rule, element_map, var_qid_map, code_uuid_map)
                            if hide_expr:
                                sec["hide"] = {"hideWhenExpression": hide_expr}

            elif a_type == "HIDEOPTION" and q is not None:
                option_val = (action.get("content") or "").strip()
                if option_val and "answers" in q.get("questionOptions", {}):
                    hide_expr = parse_rule_condition_to_hide(rule, element_map, var_qid_map, code_uuid_map)
                    if hide_expr:
                        hidden_opts = q.get("_hiddenOptions", [])
                        hidden_opts.append({"value": option_val, "hide": {"hideWhenExpression": hide_expr}})
                        q["_hiddenOptions"] = hidden_opts

            elif a_type == "SETMANDATORYFIELD" and q is not None:
                # FIX #2: O3's `required` only accepts true/false or a
                # {"type": "conditionalRequired", "referenceQuestionId":
                # ..., "referenceQuestionAnswers": [...]} object -- a raw
                # JS expression string (what the old script wrote) is
                # silently ignored. Conditions here are often compound
                # (&&/||), so instead of trying to force the single
                # reference-question shape we express "required when
                # condition holds" as a validator, the same pattern O3
                # form authors use for this exact situation:
                #     failsWhenExpression: "<condition> && isEmpty(myValue)"
                if condition:
                    qid_map = {did: info["question_id"] for did, info in element_map.items()}
                    try:
                        cond_expr = DhisConditionTranslator.translate(condition, qid_map, var_qid_map, code_uuid_map)
                        validators = q.setdefault("validators", [])
                        validators.append({
                            "type": "js_expression",
                            "failsWhenExpression": f"({cond_expr}) && isEmpty(myValue)",
                            "message": "This field is required",
                        })
                    except Exception:
                        pass

            elif a_type == "SHOWERROR":
                de_id_for_err = de_id
                q_for_err = question_by_id.get(de_question_map.get(de_id_for_err)) if de_id_for_err else None
                if q_for_err is not None:
                    v = build_validator_for_rule(rule, action, element_map, "SHOWERROR", var_qid_map, code_uuid_map)
                    if v:
                        if "validators" not in q_for_err:
                            q_for_err["validators"] = []
                        q_for_err["validators"].append(v)

            elif a_type == "SHOWWARNING":
                de_id_for_warn = de_id
                q_for_warn = question_by_id.get(de_question_map.get(de_id_for_warn)) if de_id_for_warn else None
                if q_for_warn is not None:
                    v = build_validator_for_rule(rule, action, element_map, "SHOWWARNING", var_qid_map, code_uuid_map)
                    if v:
                        if "validators" not in q_for_warn:
                            q_for_warn["validators"] = []
                        q_for_warn["validators"].append(v)

            elif a_type == "ASSIGN" and q is not None:
                content = action.get("content", "").strip()
                if content:
                    try:
                        qid_map = {did: info["question_id"] for did, info in element_map.items()}
                        calc = DhisConditionTranslator.translate(content, qid_map, var_qid_map, code_uuid_map)
                        q["calculate"] = calc
                    except Exception:
                        pass

            elif a_type == "DISPLAYTEXT" and q is not None:
                msg = (action.get("content") or "").strip()
                if msg:
                    existing = q.get("_displayTexts", [])
                    existing.append(msg)
                    q["_displayTexts"] = existing

    for sec in schema_data.get("sections", []):
        for q in sec.get("questions", []):
            validators = q.get("validators", [])
            if validators:
                q["validators"] = validators
            else:
                q.pop("validators", None)
            hidden_opts = q.pop("_hiddenOptions", None)
            if hidden_opts and "answers" in q.get("questionOptions", {}):
                if q["questionOptions"]["answers"]:
                    for ho in hidden_opts:
                        ho_val_lower = normalise(ho["value"])
                        for ans in q["questionOptions"]["answers"]:
                            if normalise(ans.get("label", "")) == ho_val_lower:
                                if "hide" not in ans:
                                    ans["hide"] = ho["hide"]
                                break
            display_texts = q.pop("_displayTexts", None)
            if display_texts:
                if "questionOptions" not in q:
                    q["questionOptions"] = {}
                q["questionOptions"]["infoText"] = "\n".join(display_texts)


def generate_enhanced_schema(
    program_name: str,
    metadata: dict,
    concepts: list[dict[str, str]],
    encounter_type: str = "",
    data_dictionary_path: Path | None = None,
) -> list[dict]:
    program = next((p for p in metadata.get("programs", []) if p.get("name") == program_name), None)
    if not program:
        raise ValueError(f"Program not found: {program_name}")

    program_id = program["id"]
    stages = [s for s in metadata.get("programStages", []) if s.get("program", {}).get("id") == program_id]
    if not stages:
        raise ValueError(f"No stages found for program: {program_name}")
    stages.sort(key=lambda s: s.get("sortOrder", 999999))

    concept_map = build_concept_map(concepts)
    occupied = {row.get("EMR Concept UUID", "").strip().lower() for row in concepts}

    excel_rows_by_stage: dict[str, list[dict[str, str]]] | None = None
    if data_dictionary_path and data_dictionary_path.exists():
        excel_rows = read_xlsx_rows(data_dictionary_path)
        excel_rows_by_stage = {}
        current_stage = ""
        for row in excel_rows:
            current_stage = row.get("Stage Name", "").strip() or current_stage
            if current_stage:
                excel_rows_by_stage.setdefault(current_stage, []).append(row)

    results: list[dict] = []
    for stage in stages:
        stage_name = stage.get("name", "")
        element_map = build_element_map(stage, metadata, excel_rows_by_stage)
        for did, el in element_map.items():
            enrich_element_with_concept(el, concept_map, concepts)

        sections_raw = [s for s in metadata.get("programStageSections", [])
                        if s.get("programStage", {}).get("id") == stage["id"]]
        if not sections_raw:
            psdes = sorted(stage.get("programStageDataElements", []), key=lambda d: d.get("sortOrder", 999999))
            if psdes:
                sections_raw = [{"name": stage_name, "sortOrder": 0,
                                "dataElements": [{"id": p["dataElement"]["id"]} for p in psdes]}]
        sections_raw.sort(key=lambda s: (s.get("sortOrder", 999999), s.get("name", "")))

        json_sections: list[dict] = []
        placed_qids: set[str] = set()
        for sec in sections_raw:
            label = sec.get("name", "").strip() or stage_name
            questions = build_section_questions(
                sec, element_map, metadata, concept_map, concepts
            )
            for q in questions:
                if q["id"] in placed_qids:
                    continue
                placed_qids.add(q["id"])
            json_sections.append({"label": label, "isExpanded": "true", "questions": questions})

        schema_data = {"sections": json_sections}
        apply_rules_to_schema(schema_data, stage, metadata, element_map, concept_map, concepts)

        for sec in schema_data.get("sections", []):
            for q in sec.get("questions", []):
                validators = q.get("validators", [])
                if not validators:
                    q.pop("validators", None)

        question_count = sum(len(s["questions"]) for s in json_sections)
        safe_name = re.sub(r"[^a-zA-Z0-9]+", "-", stage_name).strip("-").lower()
        form_uuid = unique_uuid(occupied)
        is_repeatable = stage.get("repeatable", False)

        occupied_qids = {info["question_id"] for info in element_map.values()}
        if is_repeatable:
            # Collapse into one repeating obsGroup -- see
            # make_repeating_obsgroup_section for why (matches your
            # working nurse-followup-sheet sample).
            json_sections = [make_repeating_obsgroup_section(stage_name, json_sections, occupied_qids)]

        schema = {
            "name": stage_name,
            "pages": [{"label": stage_name, "sections": json_sections}],
            "processor": "EncounterFormProcessor",
            "encounterType": encounter_type,
            "referencedForms": [],
            "uuid": form_uuid,
            "description": stage_name,
            "version": "1.0",
        }
        if is_repeatable:
            schema["repeatable"] = True

        results.append({
            "schema": schema,
            "form_uuid": form_uuid,
            "stage_name": stage_name,
            "safe_name": safe_name,
            "questions_count": question_count,
            "is_repeatable": is_repeatable,
            "rules_applied": len([r for r in metadata.get("programRules", [])
                                  if r.get("programStage", {}).get("id") == stage["id"]]),
        })
    return results




def run_enhanced_form_generation(
    metadata_path: str | Path,
    concepts_path: str | Path,
    output_dir: str | Path,
    program_name: str,
    encounter_type: str = "",
    data_dictionary_path: str | Path | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    log(f"Loading metadata from: {metadata_path}")
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    log(f"Loading concepts from: {concepts_path}")
    concepts = read_concepts(Path(concepts_path))

    dd_path = Path(data_dictionary_path) if data_dictionary_path else None
    log(f"Generating enhanced schemas for program: {program_name}")
    results = generate_enhanced_schema(
        program_name=program_name,
        metadata=metadata,
        concepts=concepts,
        encounter_type=encounter_type,
        data_dictionary_path=dd_path,
    )

    out_base = Path(output_dir)
    prog_safe = re.sub(r"[^a-zA-Z0-9]+", "-", program_name).strip("-").lower()
    stage_dir = out_base / prog_safe
    stage_dir.mkdir(parents=True, exist_ok=True)

    repeatable_stages = []
    for r in results:
        path = stage_dir / f"{r['safe_name']}.form.json"
        path.write_text(json.dumps(r["schema"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if r.get("is_repeatable"):
            repeatable_stages.append(r["stage_name"])
        log(f"  {r['stage_name']}: {r['questions_count']} questions, {r['rules_applied']} rules")

    summary = {
        "program": program_name,
        "stages": len(results),
        "total_questions": sum(r["questions_count"] for r in results),
        "total_rules": sum(r["rules_applied"] for r in results),
        "repeatable_stages": repeatable_stages,
    }
    (stage_dir / "_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"Done. {len(results)} schemas written to {stage_dir}")

    return {
        "status": "success",
        "output_dir": str(stage_dir),
        "summary": summary,
        "results": results,
    }
