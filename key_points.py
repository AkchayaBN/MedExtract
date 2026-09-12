"""
key_points.py
==============
Generates a short, scannable "Key Points" summary for a report -
the handful of facts a clinician would want at a glance, pulled
from the already-extracted structured data (no extra parsing).
"""

from risk_analyzer import _max_dimension_cm


def generate_key_points(report_data, risk_level=None, risk_flags=None):
    points = []

    metadata = report_data.get("metadata", {})
    nodules = report_data.get("nodules", [])
    measurements = report_data.get("measurements", [])
    impression = report_data.get("impression", [])

    # --- Who / what / when ---
    patient = metadata.get("patient_name")
    age_gender = metadata.get("age_gender")
    exam = report_data.get("examination")
    date = metadata.get("procedure_date")

    if patient:
        who = patient
        if age_gender:
            who += " ({})".format(age_gender)
        points.append("Patient: {}".format(who))

    if exam:
        line = "Examination: {}".format(exam)
        if date:
            line += " on {}".format(date)
        points.append(line)

    # --- Gland size, if present ---
    for m in measurements:
        name = (m.get("name") or "").lower()
        if "right" in name or "left" in name:
            points.append("{}: {}{}".format(
                m.get("name"), m.get("size"),
                " (volume {})".format(m["volume"]) if m.get("volume") else ""
            ))

    # --- Nodule summary ---
    if nodules:
        highest_tirads = None
        highest_rank = -1
        rank_order = {"TR5": 5, "TR4": 4, "TR3": 3, "TR2": 2, "TR1": 1}

        for n in nodules:
            tirads = (n.get("tirads") or "").upper()
            rank = rank_order.get(tirads, 0)
            if rank > highest_rank:
                highest_rank = rank
                highest_tirads = tirads

        largest = max(
            (_max_dimension_cm(n.get("size", "")) for n in nodules),
            default=0
        )

        summary = "{} nodule(s) detected".format(len(nodules))
        if highest_tirads:
            summary += ", highest category {}".format(highest_tirads)
        if largest:
            summary += ", largest {} cm".format(largest)
        points.append(summary)
    else:
        points.append("No nodules were detected in this report.")

    # --- Impression headline (first line only, kept short) ---
    if impression:
        first = impression[0]
        if len(first) > 140:
            first = first[:137] + "..."
        points.append("Impression: {}".format(first))

    # --- Risk flag summary ---
    if risk_level:
        if risk_flags:
            points.append("Risk level: {} ({} flag(s) raised)".format(risk_level, len(risk_flags)))
        else:
            points.append("Risk level: {}".format(risk_level))

    return points
