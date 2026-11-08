#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bahmni_concept_importer.py
==========================

Import concepts and concept sets from a folder tree of CSV files into the
legacy OpenMRS that Bahmni 0.93 runs on, WITHOUT ever touching existing
server data.

What it does, in one paragraph
------------------------------
1. Reads a *server concept export* (one CSV per hospital) - this is the only
   source used to decide what already exists on the server.
2. Walks the import folder (any depth) and reads every ``concepts.csv`` and
   ``concept_sets.csv``.
3. Plans each record as exactly one of CREATE / REUSE / CREATE_RENAMED / ERROR
   (see the "Algorithm" section of the README).
4. Writes the plan, UUID map, conflict report and summary (always, even in a
   dry run), and then either
     * ``--mode api``  : creates the new concepts through the REST API
                         (only with ``--apply``), gently and resumably, or
     * ``--mode csv``  : writes Bahmni Admin CSV-upload files for the new
                         concepts only (with ``--apply``).
5. ``--check-only`` compares a fresh export (taken after the run) against the
   plan written by the run.

Safety rules baked in
---------------------
* Existing concepts are only ever *read* (REUSE).  Nothing is updated,
  renamed, retired, deleted, or extended.  In API mode the only concepts that
  may be edited are those created by this very run (Numeric attributes).
* Existence decisions come from the export, not from per-concept lookups.
  Live reads (``GET /concept/{uuid}?v=custom:(...)``) happen only when the
  export cannot answer (see ``LiveReads``) and are capped.
* ``?q=`` concept search, ``v=full`` and dictionary listings are never used.
* Single thread, one keep-alive session, fixed delay between requests,
  batch pauses, adaptive back-off when the server slows down, optional
  run-window, clean stop after 5 consecutive failures.

Only the standard library plus ``requests`` (imported lazily, so planning and
the unit tests work without it).  Python 3.9+.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import getpass
import json
import os
import re
import sys
import time
import unicodedata
import uuid as uuidlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

VERSION = "1.0.0"

# Fixed namespace so that generated UUIDs are deterministic across runs and
# machines.  NEVER change this value once a production run has happened.
NAMESPACE = uuidlib.UUID("b7f3c8a2-5e1d-4f6a-9c3b-2d8e7a1f4c60")

NAME_MAX = 255

# canonical spelling of every datatype we accept (key = lower case)
DATATYPES = {
    "n/a": "N/A", "coded": "Coded", "text": "Text", "numeric": "Numeric",
    "boolean": "Boolean", "date": "Date", "datetime": "Datetime",
    "time": "Time", "complex": "Complex",
}

CREATES = ("CREATE", "CREATE_RENAMED")

LIVE_CUSTOM = ("custom:(uuid,name:(name),datatype:(name),set,"
               "setMembers:(uuid,name:(name)),answers:(uuid,name:(name)))")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
SAY_HOOK: Optional[Callable[[str], None]] = None
CANCEL_HOOK: Optional[Callable[[], bool]] = None


def clean(s: Optional[str]) -> str:
    """Display form of a name: NFC, trimmed, internal whitespace collapsed."""
    return " ".join(unicodedata.normalize("NFC", s or "").split())


def norm(s: Optional[str]) -> str:
    """Normalized name used for ALL comparisons (case-insensitive)."""
    return clean(s).casefold()


def say(msg: str = "") -> None:
    print(msg, flush=True)
    if SAY_HOOK is not None:
        try:
            SAY_HOOK(msg)
        except Exception:
            pass


def _default_sleep(duration: float) -> None:
    if CANCEL_HOOK and CANCEL_HOOK():
        raise StopRun("Job canceled by user.")
    step = 0.25
    remaining = duration
    while remaining > 0:
        if CANCEL_HOOK and CANCEL_HOOK():
            raise StopRun("Job canceled by user.")
        time.sleep(min(remaining, step))
        remaining -= step


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding=encoding, newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_csv(path: str, header: List[str], rows: Iterable[List[Any]],
              bom: bool = True, quote_all: bool = False) -> None:
    """Atomic CSV writer.  Reports use a BOM (Excel friendly); Bahmni upload
    files do not (a BOM would corrupt the first header name)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL,
                       lineterminator="\r\n")
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    os.replace(tmp, path)


class StopRun(Exception):
    """Raised to stop the whole run cleanly (state is saved by the caller)."""


# --------------------------------------------------------------------------
# Phase 0 - the server export
# --------------------------------------------------------------------------
class ServerEntry:
    __slots__ = ("uuid", "name", "short", "cid", "datatype", "answers_raw", "order")

    def __init__(self, uuid, name, short, cid, datatype, answers_raw, order):
        self.uuid = uuid
        self.name = name
        self.short = short
        self.cid = cid
        self.datatype = datatype
        self.answers_raw = answers_raw
        self.order = order


class ServerExport:
    """Indexes of the server concept export (by UUID and by normalized name)."""

    MAX_SEMICOLONS_IN_NAME = 8

    def __init__(self) -> None:
        self.entries: List[ServerEntry] = []
        self.by_uuid: Dict[str, ServerEntry] = {}
        self.by_name: Dict[str, List[ServerEntry]] = {}
        self.skipped_rows = 0
        self.duplicate_uuid_rows = 0
        self.path = ""
        self.file_date: Optional[datetime.date] = None
        self._answer_cache: Dict[str, Optional[List[str]]] = {}

    def add(self, uuid: str, name: str, short: str, cid: str, datatype: str,
            answers_raw: str) -> None:
        uuid = (uuid or "").strip()
        name = clean(name)
        if not uuid or not name:
            self.skipped_rows += 1
            return
        if uuid.lower() in self.by_uuid:      # same concept listed twice (e.g. one row per form)
            self.duplicate_uuid_rows += 1
            return
        dt = DATATYPES.get((datatype or "").strip().lower(), (datatype or "").strip())
        e = ServerEntry(uuid, name, clean(short), (cid or "").strip(), dt,
                        answers_raw or "", len(self.entries))
        self.entries.append(e)
        self.by_uuid[uuid.lower()] = e
        self.by_name.setdefault(norm(name), []).append(e)

    @classmethod
    def from_rows(cls, rows: Iterable[Dict[str, str]]) -> "ServerExport":
        """Build from dicts using the canonical column names (used by tests)."""
        ex = cls()
        for r in rows:
            ex.add(r.get("EMR Concept UUID", ""), r.get("EMR Concept Fully Specified Name", ""),
                   r.get("EMR Concept short name", ""), r.get("EMR Concept ID", ""),
                   r.get("EMR concept Data Type", ""), r.get("EMR Options (Answers)", ""))
        return ex

    @classmethod
    def load(cls, path: str) -> "ServerExport":
        ex = cls()
        ex.path = path
        try:
            ex.file_date = datetime.date.fromtimestamp(os.path.getmtime(path))
        except OSError:
            pass
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            header = next(reader, None) or []
            col: Dict[str, int] = {}
            for i, h in enumerate(header):
                col.setdefault((h or "").strip().lower(), i)

            def idx(*names: str) -> Optional[int]:
                for n in names:
                    if n in col:
                        return col[n]
                return None

            i_name = idx("emr concept fully specified name")
            i_short = idx("emr concept short name")
            i_uuid = idx("emr concept uuid")
            i_id = idx("emr concept id")
            i_dt = idx("emr concept data type")
            i_ans = idx("emr options (answers)")
            if i_name is None or i_uuid is None or i_dt is None:
                raise SystemExit("ERROR: export file is missing one of the columns "
                                 "'EMR Concept Fully Specified Name', 'EMR Concept UUID', "
                                 "'EMR concept Data Type'.")

            def cell(cells: List[str], i: Optional[int]) -> str:
                return cells[i] if i is not None and i < len(cells) else ""

            for cells in reader:
                if not any((c or "").strip() for c in cells):
                    continue
                ex.add(cell(cells, i_uuid), cell(cells, i_name), cell(cells, i_short),
                       cell(cells, i_id), cell(cells, i_dt), cell(cells, i_ans))
        return ex

    # ------------------------------------------------------------------
    def answer_uuids(self, e: ServerEntry) -> Optional[List[str]]:
        """Server answer UUIDs of a coded export entry, or None if ambiguous.

        The export joins answer names with '; ' but names may contain ';'.
        We try every way of re-assembling the pieces into KNOWN server names.
        Exactly one valid segmentation, with every name mapping to exactly one
        server concept, gives a trustworthy answer.  Zero or several
        segmentations (or a duplicated name) -> None -> caller does a live read.
        """
        key = e.uuid.lower()
        if key in self._answer_cache:
            return self._answer_cache[key]
        result = self._segment(e.answers_raw)
        self._answer_cache[key] = result
        return result

    def _segment(self, raw: str) -> Optional[List[str]]:
        if not raw.strip():
            return []
        parts = raw.split("; ")
        n = len(parts)
        # ways[i] = up to 2 segmentations (lists of normalized tokens) of parts[i:]
        ways: List[List[Tuple[str, ...]]] = [[] for _ in range(n + 1)]
        ways[n] = [()]
        for i in range(n - 1, -1, -1):
            found: List[Tuple[str, ...]] = []
            for j in range(i + 1, min(n, i + self.MAX_SEMICOLONS_IN_NAME) + 1):
                tok = norm("; ".join(parts[i:j]))
                if tok not in self.by_name:
                    continue
                for rest in ways[j]:
                    found.append((tok,) + rest)
                    if len(found) >= 2:
                        break
                if len(found) >= 2:
                    break
            ways[i] = found
        if len(ways[0]) != 1:
            return None
        out = []
        for tok in ways[0][0]:
            ents = self.by_name[tok]
            if len(ents) != 1:
                return None
            out.append(ents[0].uuid)
        return out


# --------------------------------------------------------------------------
# Phase 1 - scanning the import folder
# --------------------------------------------------------------------------
@dataclass
class Row:
    """One data row of one source file."""
    kind: str                # 'concept' | 'set'
    folder: str
    file: str
    rownum: int              # spreadsheet row number (header = 1)
    order: int               # global processing order
    uuid: str = ""
    name: str = ""
    description: str = ""
    cls: str = ""
    short: str = ""
    dtype: str = ""
    units: str = ""
    high: str = ""
    low: str = ""
    allow_decimal: str = ""
    locale: str = ""
    synonyms: List[str] = field(default_factory=list)
    refs: List[str] = field(default_factory=list)      # answers (concept) or children (set)
    ignored_refs: int = 0
    term_source: str = ""
    term_code: str = ""
    term_rel: str = ""
    error: str = ""

    @property
    def where(self) -> str:
        return "%s:%d" % (self.file, self.rownum)


_MULTI = re.compile(r"^(answer|child|synonym)[\s._-]*(\d+)$")


def _raise_csv_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def parse_import_file(path: str, kind: str, root: str, order_start: int,
                      notes: List[Dict[str, str]]) -> List[Row]:
    """Parse one concepts.csv / concept_sets.csv into Row objects."""
    _raise_csv_limit()
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    folder = os.path.dirname(rel)
    rows: List[Row] = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header is None:
                return rows
            hdr = [(h or "").strip().lower() for h in header]
            col: Dict[str, int] = {}
            for i, h in enumerate(hdr):
                col.setdefault(h, i)
            multi: Dict[str, List[Tuple[int, int]]] = {"answer": [], "child": [], "synonym": []}
            for i, h in enumerate(hdr):
                m = _MULTI.match(h)
                if m:
                    multi[m.group(1)].append((int(m.group(2)), i))
            for v in multi.values():
                v.sort()

            def get(cells: List[str], *names: str) -> str:
                for nme in names:
                    i = col.get(nme)
                    if i is not None and i < len(cells):
                        return (cells[i] or "").strip()
                return ""

            def get_multi(cells: List[str], which: str) -> List[str]:
                out, seen = [], set()
                for _, i in multi[which]:
                    v = clean(cells[i]) if i < len(cells) else ""
                    if v and norm(v) not in seen:
                        seen.add(norm(v))
                        out.append(v)
                return out

            order = order_start
            for rownum, cells in enumerate(reader, start=2):
                if not any((c or "").strip() for c in cells):
                    notes.append({"kind": "blank_row", "file": rel})
                    continue
                row = Row(kind=kind, folder=folder, file=rel, rownum=rownum, order=order)
                order += 1
                row.uuid = get(cells, "uuid")
                row.name = clean(get(cells, "name"))
                row.description = get(cells, "description")
                row.cls = get(cells, "class")
                row.short = clean(get(cells, "shortname", "short name"))
                row.locale = get(cells, "locale")
                row.term_source = get(cells, "reference-term-source")
                row.term_code = get(cells, "reference-term-code")
                row.term_rel = get(cells, "reference-term-relationship")
                row.refs = get_multi(cells, "answer" if kind == "concept" else "child")
                if kind == "concept":
                    row.units = get(cells, "units")
                    row.high = get(cells, "high normal")
                    row.low = get(cells, "low normal")
                    row.allow_decimal = get(cells, "allow decimal")
                    row.synonyms = get_multi(cells, "synonym")
                    raw_dt = get(cells, "datatype")
                    row.dtype = DATATYPES.get(raw_dt.lower(), "")
                    if not row.dtype:
                        row.error = ("missing datatype" if not raw_dt
                                     else "unknown datatype '%s'" % raw_dt)
                else:
                    row.dtype = "N/A"
                    row.synonyms = get_multi(cells, "synonym")
                if not row.name:
                    row.error = "missing name"
                elif not row.uuid:
                    row.error = "missing uuid"
                if kind == "concept" and row.dtype and row.dtype != "Coded" and row.refs:
                    row.ignored_refs = len(row.refs)     # answers only make sense for Coded
                    row.refs = []
                rows.append(row)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        notes.append({"kind": "file_unreadable", "file": rel, "detail": str(exc)})
    return rows


def scan_folder(root: str, notes: Optional[List[Dict[str, str]]] = None) -> List[Row]:
    """Depth-first, folders sorted alphabetically; in each folder
    concepts.csv first, then concept_sets.csv, then the sub-folders."""
    notes = notes if notes is not None else []
    rows: List[Row] = []

    def sort_key(e: "os.DirEntry[str]") -> Tuple[str, str]:
        return (e.name.casefold(), e.name)

    def walk(dirpath: str) -> None:
        try:
            entries = list(os.scandir(dirpath))
        except OSError as exc:
            notes.append({"kind": "folder_unreadable", "file": dirpath, "detail": str(exc)})
            return
        files = sorted([e for e in entries if e.is_file()], key=sort_key)
        dirs = sorted([e for e in entries if e.is_dir(follow_symlinks=False)], key=sort_key)
        for wanted, kind in (("concepts.csv", "concept"), ("concept_sets.csv", "set")):
            for e in files:
                if e.name.casefold() == wanted:
                    rows.extend(parse_import_file(e.path, kind, root, len(rows), notes))
        for d in dirs:
            walk(d.path)

    walk(root)
    # order = position in the final list (parse_import_file used len(rows) as a base,
    # which is already globally increasing, but make it airtight)
    for i, r in enumerate(rows):
        r.order = i
    return rows


# --------------------------------------------------------------------------
# Planning (Phases 1-3)
# --------------------------------------------------------------------------
class Ref:
    """A reference (answer / child) of a record, resolved by name."""
    __slots__ = ("kind", "rec", "entry", "name")

    def __init__(self, kind: str, rec: "Optional[Rec]", entry: Optional[ServerEntry], name: str):
        self.kind = kind       # 'rec' | 'srv' | 'unres'
        self.rec = rec
        self.entry = entry
        self.name = name


class FinalRef:
    """A reference after resolution: final UUID + final name."""
    __slots__ = ("uuid", "name", "new", "rec")

    def __init__(self, uuid: str, name: str, new: bool, rec: "Optional[Rec]"):
        self.uuid = uuid
        self.name = name
        self.new = new         # True when it points to a concept this import creates
        self.rec = rec


class Rec:
    """An import record = one unique concept row or set row."""

    def __init__(self, rid: int, row: Row) -> None:
        self.rid = rid
        self.row = row
        self.rows: List[Row] = [row]
        self.dup_rows: List[Row] = []          # identical rows with the same UUID
        self.kind = row.kind
        self.name = row.name
        self.nname = norm(row.name)
        self.uuid = row.uuid
        self.dtype = row.dtype
        self.refnames = list(row.refs)
        self.refset = frozenset(norm(x) for x in row.refs)
        self.ident = (self.kind, self.nname, self.dtype, self.refset)
        # Phase 2
        self.alias_of: Optional[Rec] = None
        self.alias_why = ""
        self.p2name: Optional[str] = None
        self.causes: List[str] = []
        self.is_na_answer = False
        self.uuid_owner = True
        self.force_new_uuid = False
        # linking / resolution
        self.refs: List[Ref] = []
        self.state = "new"
        self.in_cycle = False
        self.cycle_desc = ""
        # outcome
        self.action = ""
        self.final_name = ""
        self.final_uuid = ""
        self.matched = ""
        self.reason = ""
        self.final_refs: List[FinalRef] = []
        self.created_uuid = ""                 # set during API execution
        self.exec_status = ""


class LiveReads:
    """Capped, cached, read-only access to individual concepts on the server.

    ``fetch`` is a callable ``uuid -> dict | None``; None means "no server
    configured".  ``get`` returns None whenever the data cannot be obtained
    (offline, cap reached, error) - callers then take the SAFE path (treat the
    server concept as *different*, i.e. create a renamed concept)."""

    def __init__(self, fetch: Optional[Callable[[str], Optional[dict]]], cap: int = 200) -> None:
        self.fetch = fetch
        self.cap = cap
        self.count = 0
        self.cache: Dict[str, Optional[dict]] = {}
        self.needed: Set[str] = set()
        self.unavailable = 0
        self.capped = 0

    def get(self, uuid: str) -> Optional[dict]:
        k = uuid.lower()
        self.needed.add(k)
        if k in self.cache:
            return self.cache[k]
        if self.fetch is None:
            self.unavailable += 1
            return None
        if 0 <= self.cap <= self.count:
            self.capped += 1
            return None
        self.count += 1
        try:
            data = self.fetch(uuid)
        except StopRun:
            raise
        except Exception:                       # noqa: BLE001 - any failure -> safe path
            data = None
        self.cache[k] = data
        return data


class Plan:
    """Runs Phases 1-3 on construction.  Pure computation (plus live reads)."""

    def __init__(self, rows: List[Row], export: ServerExport, live: LiveReads,
                 strict_set_check: bool = False, extra_taken: Iterable[str] = ()) -> None:
        self.rows = rows
        self.export = export
        self.live = live
        self.strict = strict_set_check
        self.extra_taken: Set[str] = set(extra_taken)
        self.logs: List[Dict[str, str]] = []
        self.recs: List[Rec] = []
        self.err_recs: List[Rec] = []
        self.created: Dict[str, Rec] = {}                  # normalized final name -> rec
        self.generated: Set[str] = set()                   # UUIDs minted by us (lower)
        self.stack: List[Rec] = []
        self._warned_names: Set[str] = set()
        self.import_uuids: Set[str] = {r.uuid.lower() for r in rows if r.uuid}
        self.phase1()
        self.phase2()
        self.link()
        self.resolve_all()

    # ---- logging ------------------------------------------------------
    def log(self, severity: str, code: str, who: Any, detail: str) -> None:
        row = who.row if isinstance(who, Rec) else who
        self.logs.append({
            "severity": severity, "code": code,
            "kind": getattr(row, "kind", ""), "file": getattr(row, "file", ""),
            "row": str(getattr(row, "rownum", "")), "name": getattr(row, "name", ""),
            "uuid": getattr(row, "uuid", ""), "detail": detail})

    def canon(self, r: Rec) -> Rec:
        while r.alias_of is not None:
            r = r.alias_of
        return r

    # ---- Phase 1 --------------------------------------------------------
    def phase1(self) -> None:
        by_uuid: Dict[str, List[Rec]] = {}
        rid = 0
        for row in self.rows:
            if row.error:
                r = Rec(rid, row)
                rid += 1
                r.action = "ERROR"
                r.reason = "malformed row: " + row.error
                self.err_recs.append(r)
                self.log("ERROR", "MALFORMED_ROW", row, row.error)
                continue
            probe = (row.kind, norm(row.name), row.dtype, frozenset(norm(x) for x in row.refs))
            found = None
            for r in by_uuid.get(row.uuid.lower(), []):
                if r.ident == probe:
                    found = r
                    break
            if found is not None:                         # same UUID, same identity -> one record
                found.rows.append(row)
                found.dup_rows.append(row)
                continue
            r = Rec(rid, row)
            rid += 1
            self.recs.append(r)
            by_uuid.setdefault(row.uuid.lower(), []).append(r)
            if row.ignored_refs:
                self.log("WARNING", "ANSWERS_IGNORED", row,
                         "%d answer(s) ignored: datatype %s is not Coded" % (row.ignored_refs, row.dtype))
        # who owns each file UUID (concept beats set; otherwise first in order)
        for u, rs in by_uuid.items():
            owner = next((x for x in rs if x.kind == "concept"), rs[0])
            for x in rs:
                x.uuid_owner = x is owner
                if x is not owner:
                    self.log("WARNING", "UUID_DUPLICATE_DIFFERENT_IDENTITY", x,
                             "UUID already used by '%s' (%s); a new UUID will be generated"
                             % (owner.name, owner.row.where))

    # ---- Phase 2 --------------------------------------------------------
    def phase2(self) -> None:
        self.answer_names = {norm(a) for r in self.recs
                             if r.kind == "concept" and r.dtype == "Coded" for a in r.refnames}
        groups: Dict[str, List[Rec]] = collections.OrderedDict()
        for r in self.recs:
            groups.setdefault(r.nname, []).append(r)
            r.is_na_answer = (r.kind == "concept" and r.dtype == "N/A"
                              and r.nname in self.answer_names)
        self.groups = groups
        for g in groups.values():
            concepts = [r for r in g if r.kind == "concept"]
            sets = [r for r in g if r.kind == "set"]
            # (a) identical concept rows with different UUIDs merge into the first
            distinct: List[Rec] = []
            seen: Dict[Tuple[str, frozenset], Rec] = {}
            for r in concepts:
                k = (r.dtype, r.refset)
                if k in seen:
                    r.alias_of = seen[k]
                    r.alias_why = "identical concept row with a different UUID"
                    self.log("INFO", "MERGED_ALIAS", r,
                             "merged into %s; UUID becomes an alias" % seen[k].row.where)
                else:
                    seen[k] = r
                    distinct.append(r)
            # (b) concepts with the same name but different identity
            if len(distinct) > 1:
                keeper = next((r for r in distinct if r.dtype != "N/A"), distinct[0])
                for r in distinct:
                    if r is keeper:
                        continue
                    if r.dtype == "N/A" and r.is_na_answer:
                        r.p2name = r.name + "."
                        r.causes.append("IN_IMPORT_ANSWER_ROLE_CLASH")
                    else:
                        r.p2name = r.name + "?"
                        r.causes.append("IN_IMPORT_CONFLICT")
                    self.log("WARNING", "NAME_CONFLICT_IN_IMPORT", r,
                             "same name as %s but different %s; renamed '%s'"
                             % (keeper.row.where,
                                "datatype" if r.dtype != keeper.dtype else "answers", r.p2name))
            # (c) sets with the same name: identical members merge, later ones get '?'
            dsets: List[Rec] = []
            sseen: Dict[frozenset, Rec] = {}
            for r in sets:
                if r.refset in sseen:
                    r.alias_of = sseen[r.refset]
                    r.alias_why = "identical set with a different UUID"
                    self.log("INFO", "MERGED_ALIAS", r,
                             "merged into %s; UUID becomes an alias" % sseen[r.refset].row.where)
                else:
                    sseen[r.refset] = r
                    dsets.append(r)
            for r in dsets[1:]:
                r.p2name = r.name + "?"
                r.causes.append("IN_IMPORT_SET_CONFLICT")
                self.log("WARNING", "SET_CONFLICT_IN_IMPORT", r,
                         "same name as set %s with different members; renamed '%s'"
                         % (dsets[0].row.where, r.p2name))
            # (d) concept row and set row with the same name: the (first) set is renamed
            if concepts and dsets:
                s0 = dsets[0]
                s0.p2name = s0.name + " set"
                s0.causes.append("SET_CONCEPT_CLASH")
                if any(c.uuid.lower() == s0.uuid.lower() for c in concepts):
                    s0.force_new_uuid = True
                self.log("WARNING", "SET_CONCEPT_NAME_CLASH", s0,
                         "a concept row has the same name; set renamed '%s'%s"
                         % (s0.p2name, " and gets a new UUID" if s0.force_new_uuid else ""))

    # ---- reference linking ----------------------------------------------
    def link(self) -> None:
        idx_na: Dict[str, List[Rec]] = {}
        idx_other: Dict[str, List[Rec]] = {}
        idx_set: Dict[str, List[Rec]] = {}
        for r in self.recs:
            if r.alias_of is not None:
                continue
            tgt = idx_set if r.kind == "set" else (idx_na if r.dtype == "N/A" else idx_other)
            tgt.setdefault(r.nname, []).append(r)

        def first(lst: Optional[List[Rec]]) -> Optional[Rec]:
            return lst[0] if lst else None

        for r in self.recs:
            if r.alias_of is not None:
                continue
            for name in r.refnames:
                n = norm(name)
                if r.kind == "concept":
                    cand = first(idx_na.get(n)) or first(idx_other.get(n))
                else:
                    cand = None
                    if n != r.nname:                       # own name inside own list -> the concept
                        cand = first(idx_set.get(n))
                    cand = cand or first(idx_other.get(n)) or first(idx_na.get(n))
                if cand is not None:
                    r.refs.append(Ref("rec", cand, None, name))
                    continue
                ents = self.export.by_name.get(n)
                if ents:
                    if len(ents) > 1 and n not in self._warned_names:
                        self._warned_names.add(n)
                        self.log("WARNING", "AMBIGUOUS_SERVER_NAME", r,
                                 "'%s' matches %d server concepts; the first one is referenced"
                                 % (name, len(ents)))
                    r.refs.append(Ref("srv", None, ents[0], name))
                else:
                    r.refs.append(Ref("unres", None, None, name))
                    self.log("ERROR", "UNRESOLVED_REFERENCE", r,
                             "%s '%s' is neither in the import nor on the server; skipped"
                             % ("answer" if r.kind == "concept" else "child", name))

    # ---- Phase 3 ----------------------------------------------------------
    def resolve_all(self) -> None:
        for r in self.recs:
            if r.alias_of is None:
                self.visit(r)

    def visit(self, r: Rec) -> None:
        if r.alias_of is not None:
            self.visit(self.canon(r))
            return
        if r.state == "done":
            return
        if r.state == "visiting":                          # back-edge: cycle
            i = self.stack.index(r)
            members = self.stack[i:]
            desc = " -> ".join(m.name for m in members) + " -> " + r.name
            for m in members:
                m.in_cycle = True
                m.cycle_desc = desc
            return
        r.state = "visiting"
        self.stack.append(r)
        for ref in r.refs:
            if ref.kind == "rec":
                self.visit(self.canon(ref.rec))
        self.stack.pop()
        if r.in_cycle:
            self.fail(r, "CYCLE", "dependency cycle: " + r.cycle_desc)
        else:
            self.decide(r)
        r.state = "done"

    def fail(self, r: Rec, code: str, detail: str) -> None:
        r.action = "ERROR"
        r.reason = detail
        self.log("ERROR", code, r, detail)

    def collect_refs(self, r: Rec) -> List[FinalRef]:
        out: List[FinalRef] = []
        seen: Set[str] = set()
        for ref in r.refs:
            if ref.kind == "rec":
                c = self.canon(ref.rec)
                if c.action == "ERROR" or not c.action:
                    self.log("WARNING", "REFERENCE_OMITTED", r,
                             "'%s' omitted because that record is an ERROR" % ref.name)
                    continue
                fr = FinalRef(c.final_uuid, c.final_name, c.action in CREATES, c)
            elif ref.kind == "srv":
                fr = FinalRef(ref.entry.uuid, ref.entry.name, False, None)
            else:
                continue
            if fr.uuid.lower() in seen:
                continue
            seen.add(fr.uuid.lower())
            out.append(fr)
        return out

    # -- equivalence checks --------------------------------------------------
    def coded_equal(self, r: Rec, e: ServerEntry) -> Tuple[bool, str]:
        refs = r.final_refs
        if any(f.new for f in refs):
            return False, "answers differ (an answer is new)"
        if bool(refs) != bool(e.answers_raw.strip()):
            return False, "answers differ (one side has none)"
        srv = self.export.answer_uuids(e)
        mine = {f.uuid.lower() for f in refs}
        if srv is not None:
            if {u.lower() for u in srv} == mine:
                return True, "answers equal"
            return False, "answers differ"
        data = self.live.get(e.uuid)                       # ambiguous -> live read
        if data is None:
            self.log("WARNING", "LIVE_READ_UNAVAILABLE", r,
                     "answers of server concept %s are ambiguous in the export and could not "
                     "be read live; treated as different" % e.uuid)
            return False, "answers could not be verified (treated as different)"
        if (data.get("datatype") or {}).get("name") != "Coded":
            return False, "server concept is not Coded"
        theirs = {a.get("uuid", "").lower() for a in (data.get("answers") or [])}
        return (theirs == mine), ("answers equal (live read)" if theirs == mine
                                  else "answers differ (live read)")

    def set_equal(self, r: Rec, e: ServerEntry) -> Tuple[bool, str]:
        if any(f.new for f in r.final_refs):
            return False, "members differ (a member is new)"
        data = self.live.get(e.uuid)
        if data is None:
            self.log("WARNING", "LIVE_READ_UNAVAILABLE", r,
                     "server concept %s has the same name; could not check whether it is "
                     "an equal set; treated as different" % e.uuid)
            return False, "server concept could not be read (treated as different)"
        if not data.get("set"):
            return False, "server concept with this name is not a set"
        theirs = {m.get("uuid", "").lower() for m in (data.get("setMembers") or [])}
        mine = {f.uuid.lower() for f in r.final_refs}
        return (theirs == mine), ("set members equal (live read)" if theirs == mine
                                  else "set members differ (live read)")

    def not_a_set(self, e: ServerEntry) -> bool:
        data = self.live.get(e.uuid)
        return data is not None and not data.get("set")

    def check_name(self, r: Rec, name: str) -> Tuple[str, Any, str]:
        """-> ('REUSE', entry, why) | ('MERGE', rec, why) | ('FREE', None, '') |
        ('TAKEN', None, why)"""
        n = norm(name)
        cands = self.export.by_name.get(n, [])
        whys: List[str] = []
        for e in cands:
            if r.kind == "concept":
                if e.datatype != r.dtype:
                    whys.append("server concept %s has datatype %s" % (e.uuid, e.datatype))
                    continue
                if r.dtype == "Coded":
                    ok, why = self.coded_equal(r, e)
                elif r.dtype == "N/A" and self.strict:
                    ok = self.not_a_set(e)
                    why = "plain N/A concept" if ok else "server N/A concept is a set or unverifiable"
                else:
                    ok, why = True, "same name and datatype"
                if ok:
                    return "REUSE", e, why
                whys.append("server concept %s: %s" % (e.uuid, why))
            else:
                if e.datatype != "N/A":
                    whys.append("server concept %s has datatype %s (not a set)" % (e.uuid, e.datatype))
                    continue
                ok, why = self.set_equal(r, e)
                if ok:
                    return "REUSE", e, why
                whys.append("server concept %s: %s" % (e.uuid, why))
        if cands:
            return "TAKEN", None, "; ".join(whys)
        if n in self.extra_taken:
            return "TAKEN", None, "server reported this name as already in use"
        o = self.created.get(n)
        if o is not None:
            same = o.kind == r.kind and o.dtype == r.dtype
            if same and (r.kind == "set" or r.dtype == "Coded"):
                same = ({f.uuid.lower() for f in o.final_refs}
                        == {f.uuid.lower() for f in r.final_refs})
            if same:
                return "MERGE", o, "equivalent to import record %s" % o.row.where
            return "TAKEN", None, "name already used by import record %s" % o.row.where
        return "FREE", None, ""

    def pick_uuid(self, r: Rec, final_name: str) -> Tuple[str, str]:
        fu = r.uuid
        keep = (r.uuid_owner and not r.force_new_uuid
                and fu.lower() not in self.export.by_uuid
                and fu.lower() not in self.generated)
        if keep:
            return fu, ""
        why = ("UUID already used by a server concept" if fu.lower() in self.export.by_uuid
               else "UUID belongs to another import record" if not r.uuid_owner
               else "UUID shared with a concept of the same name" if r.force_new_uuid
               else "UUID already minted for another record")
        reserved = set(self.export.by_uuid) | self.import_uuids | self.generated
        nu = str(uuidlib.uuid5(NAMESPACE, fu + "|" + final_name))
        while nu.lower() in reserved:
            nu = str(uuidlib.uuid4())
        self.generated.add(nu.lower())
        return nu, why

    def decide(self, r: Rec) -> None:
        r.final_refs = self.collect_refs(r)
        suffix = "." if r.is_na_answer else "?"
        name = r.p2name or r.name
        server_clash = False
        first_why = ""
        for _ in range(60):
            if len(name) > NAME_MAX:
                self.fail(r, "NAME_TOO_LONG",
                          "name would be %d characters (limit %d)" % (len(name), NAME_MAX))
                return
            verdict, obj, why = self.check_name(r, name)
            if verdict == "REUSE":
                r.action = "REUSE"
                r.final_name, r.final_uuid, r.matched = obj.name, obj.uuid, obj.uuid
                r.reason = why
                if r.row.term_code or r.row.term_source:
                    self.log("INFO", "REFERENCE_TERM_IGNORED", r,
                             "reused concept is read-only; reference term not applied")
                return
            if verdict == "MERGE":
                r.alias_of = obj
                r.alias_why = why
                self.log("INFO", "MERGED_ALIAS", r, why)
                return
            if verdict == "FREE":
                break
            if not first_why:
                first_why = why
            server_clash = True
            name = name + suffix
        else:
            self.fail(r, "NAME_UNRESOLVABLE", "no free name found after 60 suffix attempts")
            return
        final_uuid, uwhy = self.pick_uuid(r, name)
        r.final_name, r.final_uuid = name, final_uuid
        if server_clash:
            r.causes.append("SERVER_CLASH")
        renamed = norm(name) != norm(r.name) or name != r.name
        r.action = "CREATE_RENAMED" if renamed else "CREATE"
        parts = []
        if r.causes:
            parts.append("; ".join(r.causes))
        if first_why:
            parts.append(first_why)
        if not parts:
            parts.append("name not on server")
        r.reason = " | ".join(parts)
        if uwhy:
            r.reason += " | new UUID (%s)" % uwhy
            self.log("WARNING", "NEW_UUID_ASSIGNED", r, uwhy)
        if server_clash:
            self.log("INFO", "RENAMED_SERVER_CLASH", r, "'%s' -> '%s': %s" % (r.name, name, first_why))
        self.created[norm(name)] = r

    # ---- views for the writers ----------------------------------------------
    def primaries(self) -> List[Rec]:
        return [r for r in self.recs if r.alias_of is None]

    def execution_order(self) -> List[Rec]:
        """Folder order; a dependency not yet emitted goes right before its
        first dependent, even if it comes from a later folder."""
        order: List[Rec] = []
        seen: Set[int] = set()

        def emit(r: Rec) -> None:
            r = self.canon(r)
            if r.rid in seen or r.action not in CREATES:
                return
            seen.add(r.rid)
            for f in r.final_refs:
                if f.rec is not None:
                    emit(f.rec)
            order.append(r)

        for r in self.recs:
            emit(r)
        return order

    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = collections.Counter()
        for r in self.primaries():
            c[r.action] += 1
        for r in self.err_recs:
            c["ERROR"] += 1
        return dict(c)


# --------------------------------------------------------------------------
# Output files
# --------------------------------------------------------------------------
def plan_rows(plan: Plan) -> List[List[Any]]:
    items: List[Tuple[int, Row, Rec, str]] = []
    for r in plan.recs:
        items.append((r.row.order, r.row, r, ""))
        for d in r.dup_rows:
            items.append((d.order, d, r, "duplicate row (same UUID and content) of %s" % r.row.where))
    for r in plan.err_recs:
        items.append((r.row.order, r.row, r, ""))
    items.sort(key=lambda t: t[0])
    out: List[List[Any]] = []
    for _, row, rec, note in items:
        c = plan.canon(rec)
        merged = note
        if not merged and rec.alias_of is not None:
            merged = "merged into %s (%s)" % (c.row.where, rec.alias_why)
        out.append([
            rec.rid, row.kind, row.folder, os.path.basename(row.file), row.rownum,
            row.name, row.uuid, rec.dtype or "", c.action, c.final_name, c.final_uuid,
            c.matched, merged, "; ".join(c.causes), c.reason])
    return out


PLAN_HEADER = ["record_id", "kind", "source_folder", "source_file", "source_row",
               "original_name", "original_uuid", "datatype", "action", "final_name",
               "final_uuid", "matched_server_uuid", "merged_into", "rename_cause", "reason"]


def uuid_map_rows(plan: Plan) -> List[List[Any]]:
    out = []
    for r in plan.recs + plan.err_recs:
        c = plan.canon(r)
        note = ""
        if r.alias_of is not None:
            note = "alias: " + r.alias_why
        elif not r.uuid_owner:
            note = "original UUID shared with another record"
        out.append([r.row.uuid, r.row.name, c.final_uuid, c.final_name, c.action, r.kind, note])
    return out


UUID_MAP_HEADER = ["original_uuid", "original_name", "final_uuid", "final_name",
                   "action", "kind", "note"]
LOG_HEADER = ["severity", "code", "kind", "file", "row", "name", "uuid", "detail"]


def write_reports(plan: Plan, out_dir: str, extra_logs: Optional[List[Dict[str, str]]] = None) -> None:
    write_csv(os.path.join(out_dir, "import_plan.csv"), PLAN_HEADER, plan_rows(plan))
    write_csv(os.path.join(out_dir, "uuid_map.csv"), UUID_MAP_HEADER, uuid_map_rows(plan))
    logs = plan.logs + (extra_logs or [])
    write_csv(os.path.join(out_dir, "conflicts_and_errors.csv"), LOG_HEADER,
              [[l.get(h, "") for h in LOG_HEADER] for l in logs])


def build_summary(plan: Plan, args_info: Dict[str, Any], extra: List[str]) -> str:
    c = plan.counts()
    lines = ["Bahmni concept importer %s - summary" % VERSION,
             "Generated: %s" % datetime.datetime.now().isoformat(timespec="seconds"), ""]
    for k, v in args_info.items():
        lines.append("%s: %s" % (k, v))
    lines.append("")
    n_rows = len(plan.rows)
    lines.append("Source rows read: %d  (concept rows %d, set rows %d)" % (
        n_rows, sum(1 for r in plan.rows if r.kind == "concept"),
        sum(1 for r in plan.rows if r.kind == "set")))
    lines.append("Unique import records: %d  (+ %d identical duplicate rows, + %d merged aliases)" % (
        len(plan.recs) + len(plan.err_recs), sum(len(r.dup_rows) for r in plan.recs),
        sum(1 for r in plan.recs if r.alias_of is not None)))
    lines.append("")
    lines.append("Actions (unique records, aliases counted with their target):")
    for a in ("CREATE", "REUSE", "CREATE_RENAMED", "ERROR"):
        lines.append("  %-15s %d" % (a, c.get(a, 0)))
    for kind in ("concept", "set"):
        kc: Dict[str, int] = collections.Counter(
            r.action for r in plan.primaries() if r.kind == kind)
        lines.append("  %-8s CREATE=%d  CREATE_RENAMED=%d  REUSE=%d  ERROR=%d" % (
            kind + "s:", kc.get("CREATE", 0), kc.get("CREATE_RENAMED", 0), kc.get("REUSE", 0),
            kc.get("ERROR", 0)))
    sev = collections.Counter(l["severity"] for l in plan.logs)
    codes = collections.Counter(l["code"] for l in plan.logs)
    lines.append("")
    lines.append("Report entries: %s" % ", ".join("%s=%d" % kv for kv in sorted(sev.items())))
    for code, n in sorted(codes.items()):
        lines.append("  %-38s %d" % (code, n))
    lr = plan.live
    lines.append("")
    lines.append("Live reads used: %d (cap %s); needed but not possible: offline=%d, over cap=%d" % (
        lr.count, "unlimited" if lr.cap < 0 else lr.cap, lr.unavailable, lr.capped))
    lines.extend(extra)
    return "\n".join(lines) + "\n"


# ---- CSV mode ----------------------------------------------------------------
def _concept_cells(r: Rec) -> Dict[str, Any]:
    w = r.row
    return {"uuid": r.final_uuid, "name": r.final_name, "description": w.description,
            "class": w.cls or "Misc", "shortname": w.short, "datatype": r.dtype,
            "units": w.units, "High Normal": w.high, "Low Normal": w.low,
            "Allow Decimal": w.allow_decimal, "locale": w.locale or "en",
            "reference-term-source": w.term_source, "reference-term-code": w.term_code,
            "reference-term-relationship": w.term_rel}


def write_upload_files(plan: Plan, out_dir: str, chunk_size: int) -> List[str]:
    """Bahmni Admin -> CSV upload files for CREATE / CREATE_RENAMED only."""
    order = plan.execution_order()
    concepts = [r for r in order if r.kind == "concept"]
    sets = [r for r in order if r.kind == "set"]
    chunk_size = max(1, chunk_size)
    written: List[str] = []
    upload_lines: List[str] = []
    seq = 0

    def build(recs: List[Rec], kind: str) -> Tuple[List[str], List[List[Any]]]:
        n_syn = max([len(r.row.synonyms) for r in recs] + [0]) if kind == "concept" else 0
        n_ref = max([len(r.final_refs) for r in recs] + [0])
        if kind == "concept":
            head = ["uuid", "name", "description", "class", "shortname", "datatype", "units",
                    "High Normal", "Low Normal", "Allow Decimal", "locale"]
            head += ["synonym.%d" % i for i in range(1, n_syn + 1)]
            head += ["answer.%d" % i for i in range(1, n_ref + 1)]
        else:
            head = ["uuid", "name", "description", "class", "shortname"]
            head += ["child.%d" % i for i in range(1, n_ref + 1)]
        head += ["reference-term-source", "reference-term-code", "reference-term-relationship"]
        body = []
        for r in recs:
            cells = _concept_cells(r)
            row = []
            for h in head:
                if h.startswith("synonym."):
                    i = int(h.split(".")[1]) - 1
                    row.append(r.row.synonyms[i] if i < len(r.row.synonyms) else "")
                elif h.startswith(("answer.", "child.")):
                    i = int(h.split(".")[1]) - 1
                    row.append(r.final_refs[i].name if i < len(r.final_refs) else "")
                else:
                    row.append(cells.get(h, ""))
            body.append(row)
        return head, body

    for kind, recs, label in (("concept", concepts, "concepts"), ("set", sets, "concept_sets")):
        for start in range(0, len(recs), chunk_size):
            seq += 1
            part = recs[start:start + chunk_size]
            head, body = build(part, kind)
            fname = "%03d_%s.csv" % (seq, label)
            write_csv(os.path.join(out_dir, fname), head, body, bom=False, quote_all=True)
            written.append(fname)
            target = "Concepts" if kind == "concept" else "Concept Set"
            upload_lines.append("%03d. %-28s %5d rows   Bahmni Admin > CSV Upload > %s"
                                % (seq, fname, len(part), target))
    # consolidated, ordered review file (NOT for upload)
    n_ref = max([len(r.final_refs) for r in order] + [0])
    n_syn = max([len(r.row.synonyms) for r in order] + [0])
    head = ["record_type", "uuid", "name", "description", "class", "shortname", "datatype",
            "units", "High Normal", "Low Normal", "Allow Decimal", "locale", "action"]
    head += ["synonym.%d" % i for i in range(1, n_syn + 1)]
    head += ["ref.%d" % i for i in range(1, n_ref + 1)]
    head += ["reference-term-source", "reference-term-code", "reference-term-relationship"]
    body = []
    for r in order:
        c = _concept_cells(r)
        row = [r.kind, c["uuid"], c["name"], c["description"], c["class"], c["shortname"],
               r.dtype, c["units"], c["High Normal"], c["Low Normal"], c["Allow Decimal"],
               c["locale"], r.action]
        row += [r.row.synonyms[i] if i < len(r.row.synonyms) else "" for i in range(n_syn)]
        row += [r.final_refs[i].name if i < len(r.final_refs) else "" for i in range(n_ref)]
        row += [c["reference-term-source"], c["reference-term-code"], c["reference-term-relationship"]]
        body.append(row)
    write_csv(os.path.join(out_dir, "consolidated_review_not_for_upload.csv"), head, body)
    header = ["Upload these files in exactly this order (dependencies come first).",
              "Do NOT upload consolidated_review_not_for_upload.csv - it is for review only.", ""]
    if not upload_lines:
        upload_lines = ["Nothing to upload: no CREATE / CREATE_RENAMED records."]
    atomic_write_text(os.path.join(out_dir, "upload_order.txt"),
                      "\n".join(header + upload_lines) + "\n")
    return written


# --------------------------------------------------------------------------
# REST client (API mode and live reads)
# --------------------------------------------------------------------------
class Resp:
    def __init__(self, status: int, data: Any = None, text: str = "") -> None:
        self.status = status
        self.data = data
        self.text = text


class PostUncertain(Exception):
    """A POST ended without a clear answer - it may or may not have been applied."""


class RequestFailed(Exception):
    """A GET failed after its retries."""


def normalize_base_url(url: str) -> str:
    u = url.strip().rstrip("/")
    if u.endswith("/ws/rest/v1"):
        return u
    if u.endswith("/openmrs"):
        return u + "/ws/rest/v1"
    return u + "/openmrs/ws/rest/v1"


def parse_window(s: str) -> Tuple[int, int]:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", s or "")
    if not m:
        raise SystemExit("ERROR: --run-window must look like HH:MM-HH:MM")
    a, b, c, d = (int(x) for x in m.groups())
    if not (0 <= a < 24 and 0 <= c < 24 and 0 <= b < 60 and 0 <= d < 60):
        raise SystemExit("ERROR: --run-window has an invalid time")
    return a * 60 + b, c * 60 + d


def in_window(window: Optional[Tuple[int, int]], now: datetime.datetime) -> bool:
    if window is None:
        return True
    start, end = window
    m = now.hour * 60 + now.minute
    if start == end:
        return True
    return (start <= m < end) if start < end else (m >= start or m < end)


class ApiClient:
    """One keep-alive session, polite pacing, adaptive back-off."""

    def __init__(self, base: str, user: str, password: str, delay_ms: int = 200,
                 max_latency_ms: int = 1500, insecure: bool = False,
                 run_window: Optional[Tuple[int, int]] = None,
                 sleep: Callable[[float], None] = _default_sleep, session: Any = None) -> None:
        try:
            import requests                      # lazy: planning/tests do not need it
        except ImportError:
            raise SystemExit("ERROR: the 'requests' package is required for server access "
                             "(pip install requests).")
        self.requests = requests
        self.s = session or requests.Session()
        self.s.auth = (user, password)
        self.s.headers.update({"Accept": "application/json"})
        if insecure:
            self.s.verify = False
            try:
                import urllib3
                urllib3.disable_warnings()
            except Exception:                    # noqa: BLE001
                pass
        self.base = normalize_base_url(base)
        self.base_delay = max(0.0, delay_ms / 1000.0)
        self.delay = self.base_delay
        self.max_latency = max_latency_ms / 1000.0
        self.window = run_window
        self.sleep = sleep
        self.latencies: collections.deque = collections.deque(maxlen=20)
        self.fail_streak = 0
        self.requests_made: Dict[str, int] = collections.Counter()
        self.throttle_events = 0
        self._window_notice = False

    # -- pacing ---------------------------------------------------------------
    def _wait_window(self) -> None:
        while not in_window(self.window, datetime.datetime.now()):
            if not self._window_notice:
                say("Outside the run window - pausing until it opens ...")
                self._window_notice = True
            self.sleep(30)
        self._window_notice = False

    def _slow_down(self, why: str, retry_after: float = 0.0) -> None:
        self.delay = min(10.0, max(self.delay * 2, 0.05))
        self.throttle_events += 1
        say("  server is struggling (%s): delay is now %.2fs, pausing" % (why, self.delay))
        self.sleep(max(self.delay, retry_after))
        self.latencies.clear()

    def _note(self, method: str, status: Optional[int], latency: float, failed: bool,
              retry_after: float = 0.0) -> None:
        self.requests_made[method] += 1
        if failed or status in (429, 500, 502, 503, 504):
            self.fail_streak += 1
            if failed or status in (429, 502, 503, 504):
                self._slow_down("network error" if failed else "HTTP %s" % status, retry_after)
        else:
            self.fail_streak = 0
            self.latencies.append(latency)
            if len(self.latencies) >= 5:
                avg = sum(self.latencies) / len(self.latencies)
                if avg > self.max_latency:
                    self._slow_down("average latency %.0f ms" % (avg * 1000))
                elif avg < self.max_latency / 2 and self.delay > self.base_delay:
                    self.delay = max(self.base_delay, self.delay / 2)
                    self.latencies.clear()
        if self.fail_streak >= 5:
            raise StopRun("5 consecutive failures - stopping cleanly.")
        self.sleep(self.delay)

    # -- requests -------------------------------------------------------------
    def _request(self, method: str, path: str, body: Any = None, retries: int = 0) -> Resp:
        url = self.base + path
        attempt = 0
        while True:
            self._wait_window()
            t0 = time.monotonic()
            try:
                r = self.s.request(method, url, json=body, timeout=(5, 60))
            except (self.requests.Timeout, self.requests.ConnectionError) as exc:
                self._note(method, None, time.monotonic() - t0, True)
                if method == "POST":
                    raise PostUncertain(str(exc))
                if attempt < retries:
                    attempt += 1
                    continue
                raise RequestFailed(str(exc))
            lat = time.monotonic() - t0
            try:
                data = r.json()
            except ValueError:
                data = None
            try:
                ra = float(r.headers.get("Retry-After", "0"))
            except (TypeError, ValueError):
                ra = 0.0
            self._note(method, r.status_code, lat, False, ra)
            if r.status_code in (401, 403):
                raise StopRun("Server refused the credentials / permission (HTTP %d)." % r.status_code)
            if method == "GET" and r.status_code in (429, 502, 503, 504) and attempt < retries:
                attempt += 1
                continue
            return Resp(r.status_code, data, r.text[:2000])

    def get(self, path: str) -> Resp:
        return self._request("GET", path, retries=3)

    def post(self, path: str, body: Any) -> Resp:
        return self._request("POST", path, body=body, retries=0)       # never retried

    # -- pre-flight -------------------------------------------------------------
    def preflight(self) -> Dict[str, Dict[str, str]]:
        r = self.get("/session")
        if r.status != 200:
            raise StopRun("Pre-flight failed: GET /session returned HTTP %s" % r.status)
        if isinstance(r.data, dict) and r.data.get("authenticated") is False:
            raise StopRun("Pre-flight failed: the server did not accept the credentials.")
        maps: Dict[str, Dict[str, str]] = {}
        for key, res in (("datatypes", "conceptdatatype"), ("classes", "conceptclass")):
            rr = self.get("/%s?v=custom:(uuid,name)&limit=100" % res)
            if rr.status != 200 or not isinstance(rr.data, dict):
                rr = self.get("/%s?v=custom:(uuid,name)" % res)
            if rr.status != 200 or not isinstance(rr.data, dict):
                raise StopRun("Pre-flight failed: GET /%s returned HTTP %s" % (res, rr.status))
            maps[key] = {x["name"].lower(): x["uuid"] for x in rr.data.get("results", [])}
        return maps

    def fetch_concept(self, uuid: str) -> Optional[dict]:
        r = self.get("/concept/%s?v=%s" % (uuid, LIVE_CUSTOM))
        if r.status == 200 and isinstance(r.data, dict):
            return r.data
        return None


# --------------------------------------------------------------------------
# State file + API execution
# --------------------------------------------------------------------------
class State:
    """JSON-lines record of every concept this tool created."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.by_name: Dict[str, dict] = {}
        self.by_uuid: Dict[str, dict] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    self.by_name[norm(e.get("final_name", ""))] = e
                    self.by_uuid[e.get("final_uuid", "").lower()] = e

    def add(self, entry: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        entry = dict(entry, ts=datetime.datetime.now().isoformat(timespec="seconds"))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        self.by_name[norm(entry["final_name"])] = entry
        self.by_uuid[entry["final_uuid"].lower()] = entry


def _num(s: str) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _truthy(s: str) -> Optional[bool]:
    v = (s or "").strip().lower()
    if v in ("true", "yes", "1", "y"):
        return True
    if v in ("false", "no", "0", "n"):
        return False
    return None


def numeric_fields(r: Rec) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    w = r.row
    if r.dtype != "Numeric":
        return out
    if w.units:
        out["units"] = w.units
    if _num(w.high) is not None:
        out["hiNormal"] = _num(w.high)
    if _num(w.low) is not None:
        out["lowNormal"] = _num(w.low)
    ad = _truthy(w.allow_decimal)
    if ad is not None:
        out["allowDecimal"] = ad
    return out


def build_payload(r: Rec, maps: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    w = r.row
    loc = w.locale or "en"
    names = [{"name": r.final_name, "locale": loc, "localePreferred": True,
              "conceptNameType": "FULLY_SPECIFIED"}]
    used = {norm(r.final_name)}
    if w.short and norm(w.short) not in used:
        names.append({"name": w.short, "locale": loc, "conceptNameType": "SHORT"})
        used.add(norm(w.short))
    for s in w.synonyms:
        if norm(s) not in used:
            names.append({"name": s, "locale": loc})
            used.add(norm(s))
    dt_key = "N/A" if r.kind == "set" else r.dtype
    payload: Dict[str, Any] = {
        "uuid": r.final_uuid,
        "names": names,
        "datatype": maps.get("datatypes", {}).get(dt_key.lower(), dt_key),
        "conceptClass": maps.get("classes", {}).get((w.cls or "Misc").lower(), w.cls or "Misc"),
    }
    if w.description:
        payload["descriptions"] = [{"description": w.description, "locale": loc}]

    def ref_uuid(f: FinalRef) -> str:
        return (f.rec.created_uuid or f.uuid) if f.rec is not None else f.uuid

    if r.kind == "set":
        payload["set"] = True
        payload["setMembers"] = [ref_uuid(f) for f in r.final_refs]
    elif r.dtype == "Coded":
        payload["answers"] = [ref_uuid(f) for f in r.final_refs]
    payload.update(numeric_fields(r))
    if w.term_code and w.term_source:
        payload["mappings"] = [{"conceptReferenceTerm": {"code": w.term_code,
                                                         "conceptSource": w.term_source},
                                "conceptMapType": w.term_rel or "SAME-AS"}]
    return payload


class ExecResult:
    def __init__(self) -> None:
        self.created = 0
        self.already = 0
        self.failed: List[Tuple[Rec, str]] = []
        self.skipped: List[Rec] = []
        self.replan_name: Optional[str] = None
        self.logs: List[Dict[str, str]] = []


def _xlog(res: ExecResult, sev: str, code: str, r: Rec, detail: str) -> None:
    res.logs.append({"severity": sev, "code": code, "kind": r.kind, "file": r.row.file,
                     "row": str(r.row.rownum), "name": r.final_name or r.name,
                     "uuid": r.final_uuid, "detail": detail})


def execute_api(plan: Plan, api: ApiClient, state: State, maps: Dict[str, Dict[str, str]],
                batch_size: int, batch_pause_s: float,
                sleep: Callable[[float], None] = _default_sleep) -> ExecResult:
    order = plan.execution_order()
    res = ExecResult()
    since_pause = 0
    for i, r in enumerate(order, 1):
        if CANCEL_HOOK and CANCEL_HOOK():
            raise StopRun("Job canceled by user.")
        deps = [f.rec for f in r.final_refs if f.rec is not None]
        if any(d.exec_status in ("FAILED", "SKIPPED") for d in deps):
            r.exec_status = "SKIPPED"
            res.skipped.append(r)
            _xlog(res, "ERROR", "SKIPPED_DEPENDENCY_FAILED", r,
                  "a dependency could not be created; rerun to resume")
            continue
        existing = state.by_name.get(norm(r.final_name))
        if existing:
            r.created_uuid = existing.get("final_uuid", "")
            r.exec_status = "ALREADY"
            res.already += 1
            if r.created_uuid.lower() != r.final_uuid.lower():
                _xlog(res, "WARNING", "STATE_UUID_DIFFERS", r,
                      "state file has UUID %s for this name; dependents use it" % r.created_uuid)
            continue
        payload = build_payload(r, maps)
        uncertain = False
        try:
            resp = api.post("/concept", payload)
            if resp.status in (500, 502, 503, 504):
                uncertain = True
        except PostUncertain:
            uncertain = True
            resp = Resp(0)
        if uncertain:                                   # never blind-retry: look first
            chk = api.get("/concept/%s?v=custom:(uuid,name:(name))" % r.final_uuid)
            if chk.status == 200:
                resp = Resp(201, chk.data)
                _xlog(res, "WARNING", "POST_VERIFIED_AFTER_ERROR", r,
                      "POST ended unclearly but the concept exists")
            elif chk.status == 404:
                resp = Resp(0, None, "POST failed; concept not created")
            else:
                raise StopRun("Cannot tell whether '%s' was created (GET returned HTTP %s). "
                              "Check the server before rerunning." % (r.final_name, chk.status))
        if resp.status in (200, 201):
            got = (resp.data or {}).get("uuid", "") if isinstance(resp.data, dict) else ""
            if got and got.lower() != r.final_uuid.lower():
                state.add({"record": r.rid, "kind": r.kind, "orig_uuid": r.row.uuid,
                           "orig_name": r.row.name, "final_uuid": got, "final_name": r.final_name,
                           "note": "server ignored the requested UUID %s" % r.final_uuid})
                raise StopRun(
                    "The REST endpoint did NOT honour the client-supplied uuid (asked %s, got %s "
                    "for '%s'). Stopping. Use --mode csv instead. That one concept exists on the "
                    "server with the wrong UUID; it is listed in the state file." %
                    (r.final_uuid, got, r.final_name))
            r.created_uuid = r.final_uuid
            r.exec_status = "CREATED"
            res.created += 1
            state.add({"record": r.rid, "kind": r.kind, "orig_uuid": r.row.uuid,
                       "orig_name": r.row.name, "final_uuid": r.final_uuid,
                       "final_name": r.final_name, "datatype": r.dtype, "action": r.action})
            _post_create_numeric(r, api, res)
            since_pause += 1
            if i % 25 == 0 or i == len(order):
                say("  created %d / %d" % (res.created, len(order)))
            if since_pause >= batch_size:
                since_pause = 0
                sleep(batch_pause_s)
            continue
        text = (resp.text or "").lower()
        if resp.status == 400 and ("duplicate" in text or "already in use" in text):
            res.replan_name = norm(r.final_name)
            _xlog(res, "WARNING", "DUPLICATE_NAME_REPLAN", r,
                  "server says the name exists (stale export); re-planning with this name taken")
            return res
        r.exec_status = "FAILED"
        res.failed.append((r, "HTTP %s %s" % (resp.status, (resp.text or "")[:300])))
        _xlog(res, "ERROR", "POST_FAILED", r, "HTTP %s %s" % (resp.status, (resp.text or "")[:300]))
    return res


def _post_create_numeric(r: Rec, api: ApiClient, res: ExecResult) -> None:
    """Numeric attributes: verify, and edit the concept we just created if needed."""
    want = numeric_fields(r)
    if not want:
        return
    chk = api.get("/concept/%s?v=custom:(uuid,units,hiNormal,lowNormal,allowDecimal)" % r.created_uuid)
    have = chk.data if chk.status == 200 and isinstance(chk.data, dict) else {}
    missing = {k: v for k, v in want.items() if have.get(k) != v}
    if not missing:
        return
    upd = api.post("/concept/%s" % r.created_uuid, missing)      # allowed: our own new concept
    if upd.status not in (200, 201):
        _xlog(res, "WARNING", "NUMERIC_ATTRS_NOT_SET", r,
              "could not set %s (HTTP %s)" % (sorted(missing), upd.status))


# --------------------------------------------------------------------------
# --check-only
# --------------------------------------------------------------------------
def run_check_only(args: argparse.Namespace) -> int:
    plan_path = os.path.join(args.out_dir, "import_plan.csv")
    if not os.path.exists(plan_path):
        say("ERROR: %s not found. Run the import (or a dry run) with the same --out-dir first." % plan_path)
        return 2
    export = ServerExport.load(args.export)
    say("Fresh export: %s (%d concepts)" % (args.export, len(export.entries)))
    expected: "collections.OrderedDict[Tuple[str, str], Dict[str, str]]" = collections.OrderedDict()
    with open(plan_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["action"] not in ("CREATE", "CREATE_RENAMED", "REUSE") or not row["final_name"]:
                continue
            dtype = row["datatype"] or "N/A"
            key = (norm(row["final_name"]), dtype)
            expected.setdefault(key, {"name": row["final_name"], "dtype": dtype,
                                      "uuid": row["final_uuid"], "kind": row["kind"],
                                      "action": row["action"]})
    out_rows, counts = [], collections.Counter()
    for (n, dtype), e in expected.items():
        ents = export.by_name.get(n, [])
        if not ents:
            status = "MISSING"
        elif any(x.datatype == dtype for x in ents):
            status = "MATCH"
        else:
            status = "DATATYPE_MISMATCH"
        uuid_ok = ""
        if status == "MATCH":
            uuid_ok = "yes" if any(x.uuid.lower() == e["uuid"].lower() for x in ents) else "no"
        counts[status] += 1
        out_rows.append([status, e["kind"], e["action"], e["name"], dtype, e["uuid"], uuid_ok,
                         ", ".join("%s(%s)" % (x.uuid, x.datatype) for x in ents)])
    write_csv(os.path.join(args.out_dir, "check_report.csv"),
              ["status", "kind", "action", "final_name", "expected_datatype", "expected_uuid",
               "uuid_matches", "server_entries"], out_rows)
    uuid_diff = sum(1 for r in out_rows if r[6] == "no")
    summary = ["Check-only result (no server calls were made)",
               "Checked: %d unique final names" % len(expected),
               "MATCH: %d" % counts["MATCH"],
               "MISSING: %d" % counts["MISSING"],
               "DATATYPE_MISMATCH: %d" % counts["DATATYPE_MISMATCH"],
               "Matches whose UUID differs from the plan (informational, e.g. reused concepts): %d" % uuid_diff,
               "Note: the export has no set flag or members, so sets are checked by name and "
               "datatype N/A only."]
    atomic_write_text(os.path.join(args.out_dir, "check_summary.txt"), "\n".join(summary) + "\n")
    say("\n".join(summary))
    clean_run = counts["MISSING"] == 0 and counts["DATATYPE_MISMATCH"] == 0
    say("CLEAN" if clean_run else "NOT CLEAN - see %s" % os.path.join(args.out_dir, "check_report.csv"))
    return 0 if clean_run else 1


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bahmni_concept_importer.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=("Import concepts / concept sets from a folder tree of CSV files into Bahmni 0.93 "
                     "(legacy OpenMRS) without changing anything that already exists.\n"
                     "Without --apply the run is a DRY RUN: nothing is written to the server."),
        epilog=("examples:\n"
                "  dry run:   %(prog)s --export Hospital_Concepts.csv --folder ./bahmni_concepts "
                "--url https://bahmni.example.org --user superman --out-dir out\n"
                "  apply:     add --apply  (password from env OPENMRS_PASSWORD or prompt)\n"
                "  CSV mode:  %(prog)s --export E.csv --folder F --mode csv --apply --out-dir out\n"
                "  verify:    %(prog)s --check-only --export fresh_export.csv --out-dir out\n"))
    p.add_argument("--export", required=True, help="server concept export CSV (the snapshot of what exists)")
    p.add_argument("--folder", help="import folder (searched recursively for concepts.csv / concept_sets.csv)")
    p.add_argument("--url", help="server URL, e.g. https://host or https://host/openmrs "
                                 "(needed for live reads and for API mode; omit for a fully offline plan)")
    p.add_argument("--user", help="OpenMRS user name")
    p.add_argument("--password", help="password (or set env OPENMRS_PASSWORD; otherwise you are asked)")
    p.add_argument("--mode", choices=("api", "csv"), default="api",
                   help="api: create through REST; csv: write Bahmni Admin upload files (default: api)")
    p.add_argument("--apply", action="store_true", help="really write (API calls or CSV upload files)")
    p.add_argument("--out-dir", default="bahmni_import_out", help="where reports and files go")
    p.add_argument("--state-file", help="JSON-lines state file (default: <out-dir>/import_state.jsonl)")
    p.add_argument("--delay-ms", type=int, default=200, help="pause between requests (default 200)")
    p.add_argument("--batch-size", type=int, default=25, help="writes per batch (default 25)")
    p.add_argument("--batch-pause-s", type=float, default=5, help="pause after each batch (default 5)")
    p.add_argument("--max-latency-ms", type=int, default=1500,
                   help="rolling average latency above which the delay doubles (default 1500)")
    p.add_argument("--max-live-reads", type=int, default=200,
                   help="cap on single-concept reads from the live server; -1 = unlimited (default 200)")
    p.add_argument("--run-window", help="only send requests between HH:MM-HH:MM (local time)")
    p.add_argument("--export-max-age-days", type=int, default=3,
                   help="warn when the export file is older than this (default 3)")
    p.add_argument("--strict-set-check", action="store_true",
                   help="also read plain N/A concepts that exist on the server, to be sure they are not sets")
    p.add_argument("--insecure", action="store_true", help="do not verify TLS certificates")
    p.add_argument("--check-only", action="store_true",
                   help="compare a fresh export against the plan in --out-dir; makes no server calls")
    p.add_argument("--csv-chunk-size", type=int, default=200, help="rows per CSV upload file (default 200)")
    return p


MAX_REPLANS = 25


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")      # type: ignore[attr-defined]
        except Exception:                             # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    if args.check_only:
        return run_check_only(args)
    if not args.folder:
        raise SystemExit("ERROR: --folder is required (except with --check-only).")
    if not os.path.isdir(args.folder):
        raise SystemExit("ERROR: folder not found: %s" % args.folder)
    if args.apply and args.mode == "api" and not (args.url and args.user):
        raise SystemExit("ERROR: --apply in API mode needs --url and --user.")
    window = parse_window(args.run_window) if args.run_window else None
    os.makedirs(args.out_dir, exist_ok=True)
    state_path = args.state_file or os.path.join(args.out_dir, "import_state.jsonl")

    # ---- Phase 0
    say("Reading export %s ..." % args.export)
    export = ServerExport.load(args.export)
    say("  %d server concepts (%d duplicate-UUID rows ignored, %d unusable rows skipped)"
        % (len(export.entries), export.duplicate_uuid_rows, export.skipped_rows))
    extra_summary: List[str] = []
    if export.file_date:
        age = (datetime.date.today() - export.file_date).days
        say("  export file date: %s (%d day(s) old)" % (export.file_date.isoformat(), age))
        if age > args.export_max_age_days:
            say("  WARNING: the export is older than %d day(s); results may be stale." % args.export_max_age_days)
            extra_summary.append("WARNING: export is %d days old" % age)

    # ---- Phase 1 scan
    say("Scanning %s ..." % args.folder)
    notes: List[Dict[str, str]] = []
    rows = scan_folder(args.folder, notes)
    say("  %d rows in %d file(s)" % (len(rows), len({r.file for r in rows})))
    for n in notes:
        if n["kind"] != "blank_row":
            say("  WARNING: %s: %s %s" % (n["kind"], n["file"], n.get("detail", "")))

    # ---- server access (reads only unless --apply in API mode)
    api: Optional[ApiClient] = None
    maps: Dict[str, Dict[str, str]] = {}
    if args.url:
        password = args.password or os.environ.get("OPENMRS_PASSWORD")
        if not password:
            password = getpass.getpass("OpenMRS password for %s: " % (args.user or "user"))
        api = ApiClient(args.url, args.user or "", password, args.delay_ms,
                        args.max_latency_ms, args.insecure, window)
        try:
            say("Pre-flight check ...")
            maps = api.preflight()
            say("  server reachable; %d datatypes, %d classes cached"
                % (len(maps["datatypes"]), len(maps["classes"])))
        except (StopRun, RequestFailed) as exc:
            say("ERROR: %s" % exc)
            say("       (omit --url to build an offline plan)")
            return 2
    live = LiveReads(api.fetch_concept if api else None, args.max_live_reads)

    # ---- Phases 2-3 (+ execution, with re-plan if the server says a name exists)
    extra_taken: Set[str] = set()
    state = State(state_path)
    exec_res: Optional[ExecResult] = None
    exec_logs: List[Dict[str, str]] = []
    stop_msg = ""
    plan = None
    for attempt in range(MAX_REPLANS):
        if CANCEL_HOOK and CANCEL_HOOK():
            raise StopRun("Job canceled by user.")
        say("Planning ...")
        plan = Plan(rows, export, live, args.strict_set_check, extra_taken)
        used_classes = {(r.row.cls or "Misc") for r in plan.execution_order()}
        for cname in sorted(used_classes):
            if maps and cname.lower() not in maps["classes"]:
                plan.log("WARNING", "CLASS_NOT_ON_SERVER", rows[0] if rows else Row("", "", "", 0, 0),
                         "concept class '%s' not found on the server; creating such concepts will fail" % cname)
        write_reports(plan, args.out_dir, exec_logs)
        if not (args.apply and args.mode == "api"):
            break
        assert api is not None
        say("Creating %d concept(s) through the API ..." % len(plan.execution_order()))
        try:
            exec_res = execute_api(plan, api, state, maps, args.batch_size, args.batch_pause_s)
        except StopRun as exc:
            stop_msg = str(exc)
            say("STOPPED: %s" % stop_msg)
            break
        exec_logs.extend(exec_res.logs)
        if exec_res.replan_name:
            extra_taken.add(exec_res.replan_name)
            continue
        break
    assert plan is not None

    if args.apply and args.mode == "csv":
        files = write_upload_files(plan, args.out_dir, args.csv_chunk_size)
        say("Wrote %d upload file(s) + upload_order.txt in %s" % (len(files), args.out_dir))

    # ---- reports
    write_reports(plan, args.out_dir, exec_logs)
    info = collections.OrderedDict([
        ("Mode", "%s (%s)" % (args.mode, "APPLY" if args.apply else "DRY RUN - no writes")),
        ("Export", "%s (%d concepts)" % (args.export, len(export.entries))),
        ("Folder", args.folder),
        ("Server", normalize_base_url(args.url) if args.url else "(none - offline plan)"),
    ])
    if export.file_date:
        info["Export file date"] = export.file_date.isoformat()
    extra = list(extra_summary)
    reqs = api.requests_made if api else {}
    extra.append("Requests made: %s (throttle events: %d)" % (
        ", ".join("%s=%d" % kv for kv in sorted(reqs.items())) or "none",
        api.throttle_events if api else 0))
    extra.append("State file: %s (%d record(s) created in total)" % (state_path, len(state.by_name)))
    if not args.apply:
        extra.append("DRY RUN: nothing was created. Add --apply to proceed.")
    if exec_res is not None:
        extra.append("Execution: created=%d, already created earlier=%d, failed=%d, skipped (dependency failed)=%d"
                     % (exec_res.created, exec_res.already, len(exec_res.failed), len(exec_res.skipped)))
    if stop_msg:
        extra.append("STOPPED EARLY: " + stop_msg)
    atomic_write_text(os.path.join(args.out_dir, "summary.txt"), build_summary(plan, info, extra))
    say("")
    say(build_summary(plan, info, extra))
    if stop_msg:
        return 2
    c = plan.counts()
    bad = c.get("ERROR", 0) or (exec_res is not None and (exec_res.failed or exec_res.skipped))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
