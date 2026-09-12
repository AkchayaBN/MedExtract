"""
followup_scheduler.py
======================
Suggests a follow-up date for a report based on the most urgent
TI-RADS follow-up interval found among its nodules (via
recommendation_engine.suggest_followup_interval), and generates a
standard .ics calendar file the user can import into Google/Outlook/
Apple Calendar.
"""

import json
import uuid
from datetime import datetime, timedelta

import recommendation_engine


def _parse_procedure_date(date_str):
    """Report procedure_date looks like '20-06-2026 15:42:34'."""
    if not date_str:
        return datetime.utcnow()

    formats = ["%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def get_followup_plan(report_row):
    """
    report_row: a dict from database.get_report_by_id
    Returns a dict with due_date, months, reason, and whether
    follow-up is needed at all.
    """
    report_data = json.loads(report_row["report_json"])
    months, reason = recommendation_engine.suggest_followup_interval(report_data)

    procedure_date = _parse_procedure_date(report_row["procedure_date"])

    if months is None:
        return {
            "needed": False,
            "reason": reason,
            "due_date": None,
            "months": None,
        }

    due_date = procedure_date + timedelta(days=months * 30)

    return {
        "needed": True,
        "reason": reason,
        "due_date": due_date,
        "months": months,
    }


def _format_ics_datetime(dt):
    return dt.strftime("%Y%m%d")


def generate_ics(report_row):
    """Returns raw .ics file content (bytes) for the suggested follow-up."""
    plan = get_followup_plan(report_row)

    metadata_name = report_row["patient_name"] or "Patient"

    if plan["needed"]:
        due_date = plan["due_date"]
        summary = "Thyroid Follow-up Ultrasound - {}".format(metadata_name)
        description = "{} Suggested by MedExtract based on report #{}.".format(
            plan["reason"], report_row["id"]
        )
    else:
        # Even with no follow-up needed, offer a routine 12-month check
        due_date = _parse_procedure_date(report_row["procedure_date"]) + timedelta(days=365)
        summary = "Routine Thyroid Check-up - {}".format(metadata_name)
        description = "No urgent follow-up was flagged for report #{}. Routine annual check suggested.".format(
            report_row["id"]
        )

    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    date_str = _format_ics_datetime(due_date)
    uid = "{}@medextract".format(uuid.uuid4())

    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MedExtract//Follow-up Scheduler//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        "UID:{}".format(uid),
        "DTSTAMP:{}".format(dtstamp),
        "DTSTART;VALUE=DATE:{}".format(date_str),
        "DTEND;VALUE=DATE:{}".format(date_str),
        "SUMMARY:{}".format(summary),
        "DESCRIPTION:{}".format(description.replace("\n", "\\n")),
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:Reminder",
        "TRIGGER:-P7D",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    ics_content = "\r\n".join(ics_lines)
    return ics_content.encode("utf-8")
