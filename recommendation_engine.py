"""
recommendation_engine.py
=========================
Many source reports never include an explicit "Recommendations" or
"Follow-up" section - the referring radiologist just states TI-RADS
categories and expects the reader to know the ACR TI-RADS management
thresholds. This module fills that gap by deriving recommendations
directly from the extracted nodule data, using the standard ACR
TI-RADS (2017) FNA / follow-up size thresholds:

    TR1 (benign)              - no FNA, no routine follow-up
    TR2 (not suspicious)      - no FNA, no routine follow-up
    TR3 (mildly suspicious)   - FNA >= 2.5 cm, follow-up >= 1.5 cm
    TR4 (moderately suspicious) - FNA >= 1.5 cm, follow-up >= 1.0 cm
    TR5 (highly suspicious)   - FNA >= 1.0 cm, follow-up >= 0.5 cm

This is the same table already printed at the bottom of the sample
reports - we're just applying it programmatically to each nodule.

Also exposes suggest_followup_interval(), used by followup_scheduler.py
to pick a concrete follow-up date.
"""

from risk_analyzer import _max_dimension_cm

# (fna_threshold_cm, followup_threshold_cm, followup_months)
TIRADS_TABLE = {
    "TR1": (None, None, None),
    "TR2": (None, None, None),
    "TR3": (2.5, 1.5, 24),
    "TR4": (1.5, 1.0, 12),
    "TR5": (1.0, 0.5, 6),
}


def _nodule_recommendation(nodule):
    tirads = (nodule.get("tirads") or "").upper()
    location = nodule.get("location") or "the identified location"
    size_cm = _max_dimension_cm(nodule.get("size", ""))

    if tirads not in TIRADS_TABLE or not size_cm:
        return None

    fna_threshold, followup_threshold, months = TIRADS_TABLE[tirads]

    if fna_threshold is None:
        return "{} nodule at {} ({}): no biopsy or routine follow-up required per ACR TI-RADS.".format(
            tirads, location, nodule.get("size", "")
        )

    if size_cm >= fna_threshold:
        return "{} nodule at {} ({}): FNA biopsy recommended (>= {} cm threshold for {}).".format(
            tirads, location, nodule.get("size", ""), fna_threshold, tirads
        )

    if size_cm >= followup_threshold:
        return "{} nodule at {} ({}): follow-up ultrasound recommended in {} months (>= {} cm threshold for {}).".format(
            tirads, location, nodule.get("size", ""), months, followup_threshold, tirads
        )

    return "{} nodule at {} ({}): below follow-up threshold, no immediate action required; reassess if it grows.".format(
        tirads, location, nodule.get("size", "")
    )


def generate_recommendations(report_data):
    """
    Returns a list of recommendation strings derived from nodule
    TI-RADS categories and sizes. Each is clearly labeled as
    auto-generated so it's never confused with a radiologist's
    own written recommendation.
    """
    nodules = report_data.get("nodules", [])
    recommendations = []

    for nodule in nodules:
        rec = _nodule_recommendation(nodule)
        if rec:
            recommendations.append(rec)

    if not recommendations:
        if nodules:
            recommendations.append(
                "Nodules were detected but lack a clear size or TI-RADS "
                "category, so an automatic recommendation could not be "
                "generated. Clinical correlation is advised."
            )
        else:
            recommendations.append(
                "No nodules requiring follow-up were identified in this report."
            )

    return [r + " [auto-generated from ACR TI-RADS guidelines]" for r in recommendations]


def suggest_followup_interval(report_data):
    """
    Looks at all nodules and returns the most urgent (shortest)
    follow-up interval required, along with the reason.
    Returns (months, reason) or (None, reason) if no follow-up needed.
    """
    nodules = report_data.get("nodules", [])
    best_months = None
    best_reason = "No nodules requiring follow-up were identified."

    for nodule in nodules:
        tirads = (nodule.get("tirads") or "").upper()
        size_cm = _max_dimension_cm(nodule.get("size", ""))

        if tirads not in TIRADS_TABLE or not size_cm:
            continue

        fna_threshold, followup_threshold, months = TIRADS_TABLE[tirads]

        if months is None or followup_threshold is None:
            continue

        if size_cm >= followup_threshold:
            if best_months is None or months < best_months:
                best_months = months
                best_reason = "{} nodule at {} ({}) meets the follow-up threshold.".format(
                    tirads, nodule.get("location") or "unspecified location", nodule.get("size", "")
                )

    return best_months, best_reason
