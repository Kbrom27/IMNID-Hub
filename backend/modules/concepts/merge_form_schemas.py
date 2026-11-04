"""Merge Form Schemas from Two Directories.

Source A (with rules): used as base, keeps rules (hide, validators, calculate).
Source B (manually fixed): provides missing questions and answer options.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Callable, Optional


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def extract_leaf_questions(schema: dict) -> list[dict]:
    questions: list[dict] = []
    for page in schema.get("pages", []):
        for section in page.get("sections", []):
            for q in section.get("questions", []):
                if q.get("type") == "obsGroup":
                    questions.extend(q.get("questions", []))
                else:
                    questions.append(q)
    return questions


def find_match(
    fix_q: dict,
    gen_by_id: dict[str, dict],
    gen_by_concept: dict[str, dict],
    gen_by_label: dict[str, dict],
) -> tuple[dict | None, str]:
    qid = fix_q["id"]
    concept = fix_q.get("questionOptions", {}).get("concept", "")
    label = normalize(fix_q.get("label", ""))

    if qid in gen_by_id:
        return gen_by_id[qid], "id"
    nid = normalize(qid)
    for gid, gq in gen_by_id.items():
        if normalize(gid) == nid:
            return gq, "norm_id"
    if concept and concept in gen_by_concept:
        return gen_by_concept[concept], "concept"
    if label and label in gen_by_label:
        return gen_by_label[label], "label"
    return None, ""


def merge_answers(gen_q: dict, fix_q: dict) -> int:
    gen_answers = gen_q.get("questionOptions", {}).get("answers", [])
    fix_answers = fix_q.get("questionOptions", {}).get("answers", [])
    if not fix_answers:
        return 0
    gen_by_concept: dict[str, int] = {}
    gen_by_label: dict[str, int] = {}
    for i, a in enumerate(gen_answers):
        c = a.get("concept", "")
        if c:
            gen_by_concept[c] = i
        l = normalize(a.get("label", ""))
        if l:
            gen_by_label[l] = i

    changed = 0
    for fa in fix_answers:
        fc = fa.get("concept", "")
        fl = normalize(fa.get("label", ""))
        if fc and fc in gen_by_concept:
            continue
        if fl and fl in gen_by_label:
            idx = gen_by_label[fl]
            old_concept = gen_answers[idx].get("concept", "")
            if old_concept != fc:
                gen_answers[idx]["concept"] = fc
                gen_by_concept[fc] = idx
                gen_by_concept.pop(old_concept, None)
                changed += 1
            continue
        gen_answers.append(fa)
        if fc:
            gen_by_concept[fc] = len(gen_answers) - 1
        if fl:
            gen_by_label[fl] = len(gen_answers) - 1
        changed += 1

    if changed:
        gen_q.setdefault("questionOptions", {})["answers"] = gen_answers
    return changed


def merge_forms(
    gen_schema: dict, fix_schema: dict
) -> tuple[dict, int, int, int]:
    gen_questions = extract_leaf_questions(gen_schema)
    gen_by_id: dict[str, dict] = {}
    gen_by_concept: dict[str, dict] = {}
    gen_by_label: dict[str, dict] = {}
    for q in gen_questions:
        qid = q["id"]
        gen_by_id[qid] = q
        concept = q.get("questionOptions", {}).get("concept", "")
        if concept:
            gen_by_concept[concept] = q
        label = normalize(q.get("label", ""))
        if label:
            gen_by_label[label] = q

    fix_questions = extract_leaf_questions(fix_schema)
    matched_gen_objects: set[int] = set()
    questions_to_add: list[dict] = []
    matched_count = 0
    added_answers_total = 0

    for fix_q in fix_questions:
        match, match_type = find_match(
            fix_q, gen_by_id, gen_by_concept, gen_by_label
        )
        if match:
            matched_gen_objects.add(id(match))
            matched_count += 1
            added_answers_total += merge_answers(match, fix_q)
        else:
            questions_to_add.append(fix_q)

    if questions_to_add:
        for page in gen_schema.get("pages", []):
            for section in page.get("sections", []):
                for q in section.get("questions", []):
                    if q.get("type") == "obsGroup":
                        q.setdefault("questions", []).extend(questions_to_add)
                        questions_to_add = []
                        break
                if not questions_to_add:
                    break
            if not questions_to_add:
                break
        if questions_to_add and gen_schema.get("pages"):
            first_section = gen_schema["pages"][0]["sections"][0]
            first_section.setdefault("questions", []).extend(questions_to_add)

    return gen_schema, matched_count, added_answers_total, len(questions_to_add)


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run_merge_forms(
    base_dir: str | Path,
    fix_dir: str | Path,
    out_dir: str | Path,
    log_fn: Optional[Callable[[str], None]] = None,
) -> dict:
    log = log_fn or (lambda msg: None)
    base_path = Path(base_dir)
    fix_path = Path(fix_dir)
    out_path = Path(out_dir)

    if not base_path.is_dir():
        raise FileNotFoundError(f"Source A directory not found: {base_path}")
    if not fix_path.is_dir():
        raise FileNotFoundError(f"Source B directory not found: {fix_path}")

    out_path.mkdir(parents=True, exist_ok=True)

    fix_by_name: dict[str, Path] = {}
    fix_by_stem: dict[str, list[Path]] = {}
    for fpath in sorted(fix_path.rglob("*")):
        if fpath.suffix not in (".json",):
            continue
        fix_by_stem.setdefault(normalize(fpath.stem), []).append(fpath)
        schema = load_json(fpath)
        if schema:
            iname = normalize(schema.get("name", ""))
            if iname:
                fix_by_name.setdefault(iname, fpath)

    base_files = []
    for fpath in sorted(base_path.rglob("*.json")):
        schema = load_json(fpath)
        if isinstance(schema, dict) and (
            "pages" in schema
            or schema.get("processor") == "EncounterFormProcessor"
            or "name" in schema
        ):
            base_files.append(fpath)

    total_base = 0
    total_matched_forms = 0
    total_added_questions = 0
    total_added_answers = 0
    processed_forms = []

    for fpath in base_files:
        rel = fpath.relative_to(base_path)
        out_fpath = out_path / rel

        gen = load_json(fpath)
        if gen is None:
            continue

        total_base += 1
        gen_name_raw = gen.get("name", "")
        gen_name_key = normalize(gen_name_raw)
        gen_stem = fpath.stem.replace(".form", "")

        fix_fpath = fix_by_name.get(gen_name_key)
        if fix_fpath is None:
            key = normalize(gen_stem)
            candidates = fix_by_stem.get(key, [])
            if candidates:
                fix_fpath = candidates[0]

        if fix_fpath is None:
            log(f"  {gen_name_raw or fpath.name}: NO MATCH -> copied as-is")
            out_fpath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fpath, out_fpath)
            processed_forms.append(
                {"name": gen_name_raw, "status": "copied_as_is"}
            )
            continue

        fix = load_json(fix_fpath)
        if fix is None:
            log(
                f"  {gen_name_raw or fpath.name}: fix file found but unreadable -> copied as-is"
            )
            out_fpath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fpath, out_fpath)
            processed_forms.append(
                {"name": gen_name_raw, "status": "unreadable_copied"}
            )
            continue

        merged, q_matched, a_added, q_added = merge_forms(gen, fix)
        total_matched_forms += 1
        total_added_questions += q_added
        total_added_answers += a_added

        out_fpath.parent.mkdir(parents=True, exist_ok=True)
        out_fpath.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        log(
            f"  {gen_name_raw or fpath.name}: {q_matched} questions matched, {a_added} answers added, {q_added} new questions added"
        )
        processed_forms.append(
            {
                "name": gen_name_raw,
                "status": "merged",
                "matched_questions": q_matched,
                "added_answers": a_added,
                "added_questions": q_added,
            }
        )

    log(
        f"\nDone. {total_base} base forms processed, {total_matched_forms} matched with fix version."
    )
    return {
        "status": "completed",
        "total_base_forms": total_base,
        "matched_forms": total_matched_forms,
        "added_questions": total_added_questions,
        "added_answers": total_added_answers,
        "output_directory": str(out_path),
        "forms": processed_forms,
    }
