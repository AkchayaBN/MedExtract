"""
database.py
============
SQLite persistence layer for MedExtract.

Stores every processed report so the app can offer:
- a report history / dashboard
- search & filter across findings/nodules
- duplicate detection (same patient + same procedure date + same content hash)
- trend analysis (multiple reports for the same patient/MRN over time)

No external DB server needed - uses a local medextract.db file.
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "medextract.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT,
                patient_name TEXT,
                mrn TEXT,
                age_gender TEXT,
                procedure_date TEXT,
                facility TEXT,
                extraction_method TEXT,
                ocr_confidence REAL,
                content_hash TEXT,
                report_json TEXT,
                extracted_text TEXT,
                risk_level TEXT,
                risk_flags TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def compute_content_hash(extracted_text):
    """Hash of normalized text - kept for record-keeping / future use."""
    if not extracted_text:
        return ""
    normalized = " ".join(extracted_text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def save_report(original_filename, report_data, extracted_text,
                 extraction_method, content_hash, risk_level, risk_flags,
                 ocr_confidence=None):
    metadata = report_data.get("metadata", {})

    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO reports (
                original_filename, patient_name, mrn, age_gender,
                procedure_date, facility, extraction_method, ocr_confidence,
                content_hash, report_json, extracted_text,
                risk_level, risk_flags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            original_filename,
            metadata.get("patient_name", ""),
            metadata.get("mrn", ""),
            metadata.get("age_gender", ""),
            metadata.get("procedure_date", ""),
            metadata.get("facility", ""),
            extraction_method,
            ocr_confidence,
            content_hash,
            json.dumps(report_data),
            extracted_text,
            risk_level,
            json.dumps(risk_flags),
            datetime.utcnow().isoformat()
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_all_reports(limit=200):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_report_by_id(report_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def search_reports(keyword):
    """
    Search patient name, MRN, extracted text, and the raw report JSON
    (covers findings/nodules/impression text) for a keyword.
    """
    if not keyword:
        return get_all_reports()

    like = "%{}%".format(keyword)

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT * FROM reports
            WHERE patient_name LIKE ?
               OR mrn LIKE ?
               OR extracted_text LIKE ?
               OR report_json LIKE ?
            ORDER BY id DESC
        """, (like, like, like, like)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_reports_by_mrn(mrn):
    """All reports for one patient, oldest first - used for trend analysis."""
    if not mrn:
        return []

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM reports WHERE mrn = ? ORDER BY id ASC", (mrn,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_distinct_mrns():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT mrn, patient_name FROM reports "
            "WHERE mrn IS NOT NULL AND mrn != '' ORDER BY patient_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
