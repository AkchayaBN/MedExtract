"""
risk_analyzer.py
=================
Rule-based anomaly / risk highlighting for an extracted report.

Flags:
  - TI-RADS 4 or 5 nodules (higher malignancy risk category)
  - Unusually large nodules (>= 2 cm on any measured dimension)
  - Missing critical fields (patient name, MRN, impression, findings)

Returns a risk_level of "HIGH", "MEDIUM", or "LOW" plus a list of
human-readable flag messages, so the UI can badge a report accordingly.
"""

import re

LARGE_NODULE_CM_THRESHOLD = 2.0


def _max_dimension_cm(size_str):
    """Parse a size string like '2.3 x 1.1 x 0.9 cm' or '15 mm' -> max dimension in cm."""
    if not size_str:
        return 0.0

    numbers = re.findall(r"[0-9]+\.?[0-9]*", size_str)
    if not numbers:
        return 0.0

    values = [float(n) for n in numbers]
    max_value = max(values)

    if "mm" in size_str.lower():
        return max_value / 10.0

    return max_value


def analyze_risk(report_data):
    flags = []

    metadata = report_data.get("metadata", {})
    nodules = report_data.get("nodules", [])
    findings = report_data.get("findings", [])
    impression = report_data.get("impression", [])

    # --- TI-RADS based risk ---
    for nodule in nodules:
        tirads = (nodule.get("tirads") or "").upper()
        if tirads in ("TR4", "TR5"):
            flags.append(
                "High-risk nodule detected ({}) at {} - size {}".format(
                    tirads,
                    nodule.get("location") or "unspecified location",
                    nodule.get("size") or "size not recorded"
                )
            )

    # --- Large nodule size, regardless of TI-RADS ---
    for nodule in nodules:
        dimension = _max_dimension_cm(nodule.get("size", ""))
        if dimension >= LARGE_NODULE_CM_THRESHOLD:
            flags.append(
                "Large nodule ({} cm+) at {}".format(
                    dimension,
                    nodule.get("location") or "unspecified location"
                )
            )

    # --- Missing critical fields ---
    if not metadata.get("patient_name"):
        flags.append("Missing patient name")

    if not metadata.get("mrn"):
        flags.append("Missing MRN / Patient ID")

    if not findings:
        flags.append("No findings section could be extracted")

    if not impression:
        flags.append("No impression/conclusion section could be extracted")

    # --- Determine overall level ---
    has_tirads_45 = any(
        (n.get("tirads") or "").upper() in ("TR4", "TR5") for n in nodules
    )
    has_large_nodule = any(
        _max_dimension_cm(n.get("size", "")) >= LARGE_NODULE_CM_THRESHOLD
        for n in nodules
    )

    if has_tirads_45 or has_large_nodule:
        level = "HIGH"
    elif flags:
        level = "MEDIUM"
    else:
        level = "LOW"

    return level, flags
