"""RFC4180 CSV import/export helpers.

This module provides small helpers for importing questionnaire definitions from
CSV and exporting a stable snapshot. Export ordering is deterministic by
`screen_key`, `question_order`, `question_id`.
"""

from __future__ import annotations

import csv
import io
from typing import Dict, Iterable, List, Tuple
from uuid import uuid4

from sqlalchemy import text as sql_text

from app.db.base import get_engine


HEADER = [
    "external_qid",
    "screen_key",
    "question_order",
    "question_text",
    "answer_kind",
    "mandatory",
    "placeholder_code",
    "options",
]


def build_export_csv(questionnaire_id: str, rows: Iterable[Dict[str, object]] | None = None) -> bytes:
    rows = list(rows or [])
    # If no rows are provided, load from DB
    if not rows:
        eng = get_engine()
        with eng.connect() as conn:
            qrows = conn.execute(
                sql_text(
                    """
                    SELECT q.question_id, q.external_qid, q.screen_key, q.question_order, q.question_text,
                           q.answer_type AS answer_kind, q.mandatory, q.placeholder_code
                    FROM questionnaire_question q
                    JOIN screens s ON s.screen_key = q.screen_key
                    WHERE s.questionnaire_id = :qid
                    ORDER BY q.screen_key ASC, q.question_order ASC, q.question_id ASC
                    """
                ),
                {"qid": questionnaire_id},
            ).mappings().all()
            # Fetch options per question for enum_single
            def _options_for(qid: str) -> str:
                opt_rows = conn.execute(
                    sql_text(
                        "SELECT value, COALESCE(label, value) AS label FROM answer_option WHERE question_id = :qid ORDER BY sort_index ASC"
                    ),
                    {"qid": qid},
                ).fetchall()
                return "|".join(f"{r[0]}:{r[1]}" for r in opt_rows)
        rows = [
            {
                "question_id": str(r["question_id"]),
                "external_qid": r["external_qid"],
                "screen_key": r["screen_key"],
                "question_order": int(r["question_order"]),
                "question_text": r["question_text"],
                "answer_kind": r["answer_kind"],
                "mandatory": bool(r["mandatory"]),
                "placeholder_code": r["placeholder_code"] or "",
                "options": _options_for(str(r["question_id"])) if r["answer_kind"] == "enum_single" else "",
            }
            for r in qrows
        ]
    rows.sort(key=lambda r: (str(r.get("screen_key")), int(r.get("question_order", 0)), str(r.get("question_id", ""))))
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=HEADER)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in HEADER})
    return buf.getvalue().encode("utf-8")


def parse_import_csv(b: bytes) -> Dict[str, object]:
    text = (b or b"").decode("utf-8")
    # Normalize escaped underscores in headers/body just in case
    text = text.replace("\\_", "_")
    buf = io.StringIO(text)
    reader = csv.DictReader(buf)
    created = 0
    updated = 0
    errors: List[Dict[str, object]] = []
    rows: List[Dict[str, str]] = []
    seen_ext: Dict[str, int] = {}
    ext_lines: Dict[str, List[int]] = {}
    for i, row in enumerate(reader, start=2):  # header is line 1
        ext = (row.get("external_qid") or "").strip()
        if not ext:
            errors.append({"line": i, "message": "missing external_qid"})
        rows.append(row)  # preserve original row order for options sort_index
        if ext:
            seen_ext[ext] = seen_ext.get(ext, 0) + 1
            ext_lines.setdefault(ext, []).append(i)
    # Reject duplicate external_qid within the same file
    dup_exts = [ext for ext, cnt in seen_ext.items() if cnt > 1]
    if dup_exts:
        for ext in dup_exts:
            for ln in ext_lines.get(ext, []):
                errors.append({"line": ln, "message": f"duplicate external_qid in file: {ext}"})
        return {"created": 0, "updated": 0, "errors": errors}

    eng = get_engine()
    with eng.begin() as conn:
        for row in rows:
            external_qid = (row.get("external_qid") or "").strip()
            screen_key = (row.get("screen_key") or "").strip()
            question_text = (row.get("question_text") or "").strip()
            answer_kind = (row.get("answer_kind") or "").strip()
            mandatory = str(row.get("mandatory") or "").strip().lower() in {"true", "1", "yes"}
            order = int(str(row.get("question_order") or 0) or 0)
            placeholder = (row.get("placeholder_code") or "").strip() or None
            # Basic row validation: must have external_qid, question_text, answer_kind
            if not (external_qid and question_text and answer_kind):
                # Compute the original CSV line number for this row
                # Note: rows list preserves order with header at line 1
                idx = rows.index(row)
                line_no = idx + 2  # offset for header
                errors.append({"line": line_no, "message": f"invalid row for external_qid={external_qid or '?'}"})
                continue
            # Determine if question exists
            existing = conn.execute(
                sql_text("SELECT question_id FROM questionnaire_question WHERE external_qid = :ext"),
                {"ext": external_qid},
            ).fetchone()
            if existing:
                question_id = str(existing[0])
                conn.execute(
                    sql_text(
                        """
                        UPDATE questionnaire_question
                        SET screen_key=:skey, question_order=:ord, question_text=:qtext, answer_type=:akind, mandatory=:mand, placeholder_code=:ph
                        WHERE external_qid = :ext
                        """
                    ),
                    {
                        "skey": screen_key,
                        "ord": order,
                        "qtext": question_text,
                        "akind": answer_kind,
                        "mand": mandatory,
                        "ph": placeholder,
                        "ext": external_qid,
                    },
                )
                updated += 1
                # Clear and repopulate options when enum_single
                if answer_kind == "enum_single":
                    conn.execute(
                        sql_text("DELETE FROM answer_option WHERE question_id = :qid"),
                        {"qid": question_id},
                    )
            else:
                question_id = str(uuid4())
                conn.execute(
                    sql_text(
                        """
                        INSERT INTO questionnaire_question (question_id, screen_key, external_qid, question_order, question_text, answer_type, mandatory, placeholder_code)
                        VALUES (:qid, :skey, :ext, :ord, :qtext, :akind, :mand, :ph)
                        """
                    ),
                    {
                        "qid": question_id,
                        "skey": screen_key,
                        "ext": external_qid,
                        "ord": order,
                        "qtext": question_text,
                        "akind": answer_kind,
                        "mand": mandatory,
                        "ph": placeholder,
                    },
                )
                created += 1
            # Insert options when enum_single
            if answer_kind == "enum_single":
                raw_options = (row.get("options") or "").strip()
                if raw_options:
                    parts = [part for part in raw_options.split("|") if part]
                    sort_index = 1
                    for part in parts:
                        # Unescape escaped colon (\:) used in feature literals
                        part = part.replace("\\:", ":")
                        if ":" in part:
                            value, label = part.split(":", 1)
                        else:
                            value, label = part, part
                        conn.execute(
                            sql_text(
                                """
                                INSERT INTO answer_option (option_id, question_id, value, label, sort_index)
                                VALUES (:oid, :qid, :val, :lbl, :idx)
                                ON CONFLICT (question_id, value) DO UPDATE SET label=EXCLUDED.label, sort_index=EXCLUDED.sort_index
                                """
                            ),
                            {
                                "oid": str(uuid4()),
                                "qid": question_id,
                                "val": value,
                                "lbl": label,
                                "idx": sort_index,
                            },
                        )
                        sort_index += 1

    return {"created": created, "updated": updated, "errors": errors}
