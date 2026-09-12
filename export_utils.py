"""
export_utils.py
================
Export a single extracted report to JSON, CSV, or a simple PDF summary.

PDF export uses fpdf2 (lightweight, no external system deps beyond pip).
"""

import io
import csv
import json


def export_json(report_row):
    """report_row: a dict from database.get_report_by_id (report_json is a JSON string)."""
    report_data = json.loads(report_row["report_json"])
    payload = {
        "id": report_row["id"],
        "original_filename": report_row["original_filename"],
        "created_at": report_row["created_at"],
        "risk_level": report_row["risk_level"],
        "risk_flags": json.loads(report_row["risk_flags"] or "[]"),
        "report": report_data,
    }
    buffer = io.BytesIO(json.dumps(payload, indent=2).encode("utf-8"))
    buffer.seek(0)
    return buffer


def export_csv(report_row):
    report_data = json.loads(report_row["report_json"])
    metadata = report_data.get("metadata", {})

    output = io.StringIO()
    writer = csv.writer(output)

    import key_points as _key_points
    points = _key_points.generate_key_points(
        report_data, report_row["risk_level"],
        json.loads(report_row["risk_flags"] or "[]")
    )
    writer.writerow(["Key Points"])
    for p in points:
        writer.writerow([p])
    writer.writerow([])

    writer.writerow(["Field", "Value"])
    for key, value in metadata.items():
        writer.writerow([key, value])

    writer.writerow([])
    writer.writerow(["Examination", report_data.get("examination", "")])
    writer.writerow(["Indication", report_data.get("indication", "")])

    writer.writerow([])
    writer.writerow(["Measurements"])
    writer.writerow(["Name", "Size", "Volume"])
    for m in report_data.get("measurements", []):
        writer.writerow([m.get("name", ""), m.get("size", ""), m.get("volume", "")])

    writer.writerow([])
    writer.writerow(["Nodules"])
    writer.writerow(["Location", "Size", "TI-RADS", "Description"])
    for n in report_data.get("nodules", []):
        writer.writerow([n.get("location", ""), n.get("size", ""),
                          n.get("tirads", ""), n.get("description", "")])

    writer.writerow([])
    writer.writerow(["Findings"])
    for f in report_data.get("findings", []):
        writer.writerow([f])

    writer.writerow([])
    writer.writerow(["Impression"])
    for i in report_data.get("impression", []):
        writer.writerow([i])

    writer.writerow([])
    writer.writerow(["Recommendations"])
    for r in report_data.get("recommendations", []):
        writer.writerow([r])

    buffer = io.BytesIO(output.getvalue().encode("utf-8"))
    buffer.seek(0)
    return buffer


def _sanitize_for_pdf(text):
    """
    Core PDF fonts (Helvetica) only support latin-1. Replace characters
    outside that range (e.g. '×', smart quotes, bullets) with safe
    ASCII equivalents so fpdf2 doesn't raise on layout/encoding.
    """
    if text is None:
        return ""

    text = str(text)

    replacements = {
        "\u00d7": "x", "\u2013": "-", "\u2014": "-",
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2022": "-", "\u25cf": "-", "\u25aa": "-", "\u25e6": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Drop anything still outside latin-1 rather than crashing.
    text = text.encode("latin-1", "replace").decode("latin-1")

    # fpdf2's multi_cell can't break a single "word" that has no
    # spaces and is wider than the page - insert soft break points
    # into any very long unspaced token so it always wraps.
    def break_long_token(word, chunk_size=40):
        if len(word) <= chunk_size:
            return word
        return " ".join(
            word[i:i + chunk_size] for i in range(0, len(word), chunk_size)
        )

    text = " ".join(break_long_token(w) for w in text.split(" "))

    return text


def export_pdf(report_row):
    from fpdf import FPDF

    report_data = json.loads(report_row["report_json"])
    metadata = report_data.get("metadata", {})

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "MedExtract Report Summary", ln=True)

    pdf.set_font("Helvetica", "", 11)

    def section_title(title):
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, _sanitize_for_pdf(title), ln=True)
        pdf.set_font("Helvetica", "", 11)

    def line(text):
        text = _sanitize_for_pdf(text)
        if not text.strip():
            text = "-"
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6, text)

    import key_points as _key_points
    points = _key_points.generate_key_points(
        report_data, report_row["risk_level"],
        json.loads(report_row["risk_flags"] or "[]")
    )
    section_title("Key Points")
    for p in points:
        line("- " + p)

    section_title("Patient Information")
    for key, value in metadata.items():
        line("{}: {}".format(key.replace("_", " ").title(), value or "-"))

    section_title("Examination")
    line(report_data.get("examination", "") or "-")

    section_title("Indication")
    line(report_data.get("indication", "") or "-")

    section_title("Measurements")
    for m in report_data.get("measurements", []):
        line("{}: {} {}".format(m.get("name", ""), m.get("size", ""), m.get("volume", "")))

    section_title("Nodules")
    for n in report_data.get("nodules", []):
        line("{} - {} - {} - {}".format(
            n.get("location", ""), n.get("size", ""),
            n.get("tirads", ""), n.get("description", "")
        ))

    section_title("Findings")
    for f in report_data.get("findings", []):
        line("- " + f)

    section_title("Impression")
    for i in report_data.get("impression", []):
        line("- " + i)

    section_title("Recommendations")
    for r in report_data.get("recommendations", []):
        line("- " + r)

    risk_flags = json.loads(report_row["risk_flags"] or "[]")
    if risk_flags:
        section_title("Risk Flags ({})".format(report_row["risk_level"]))
        for flag in risk_flags:
            line("- " + flag)

    buffer = io.BytesIO(pdf.output(dest="S"))
    buffer.seek(0)
    return buffer
