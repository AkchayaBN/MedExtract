import os
import re
import json
import uuid

import fitz
from flask import Flask, render_template, request, send_file, jsonify, Response
from werkzeug.utils import secure_filename

import database
import risk_analyzer
import export_utils
import chatbot
import recommendation_engine
import thyroid_diagram
import followup_scheduler
import global_chatbot
import key_points
import ocr_engine


app = Flask(__name__)
database.init_db()

UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"pdf"}


# ============================================================
# FILE VALIDATION
# ============================================================

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

def extract_pdf_text(pdf_path):
    """
    Extract text directly from a PDF.
    Fast for digitally generated PDFs.
    """

    doc = fitz.open(pdf_path)
    pages = []

    try:
        for page in doc:
            text = page.get_text("text")

            if text.strip():
                pages.append(text)

    finally:
        doc.close()

    return "\n".join(pages).strip()


# ============================================================
# OCR FALLBACK - see ocr_engine.py for the actual pytesseract-based
# implementation (with preprocessing, PSM fallback, and confidence
# scoring). This project now uses that instead of shelling out to
# the tesseract CLI directly.
# ============================================================

# ============================================================
# TEXT NORMALIZATION
# ============================================================


# Word/Office-generated PDFs often store bullet-list markers as Wingdings /
# Symbol-font code points sitting in the Unicode Private Use Area. PyMuPDF's
# text extraction returns those raw code points, and since no normal font
# maps them to anything, browsers render them as a tofu/empty square ("")
# instead of a bullet. Map the common ones to a real bullet character.
_BULLET_GLYPH_MAP = {
    "\uf0b7": "•", "\uf0a7": "•", "\uf06c": "•", "\uf076": "•",
    "\uf0d8": "•", "\uf0a8": "•", "\uf0fc": "•", "\uf0ac": "•",
    "\u25aa": "•", "\u25cf": "•", "\u25e6": "•", "\u2043": "•",
    "\u2219": "•", "\u25a0": "•", "\u25cb": "•",
}

# Catch-all for any other Private Use Area code point (U+E000-U+F8FF) that
# slips through unmapped above - these never render as anything but a
# square, so fold them to a bullet rather than leave a stray box on screen.
_PUA_RE = re.compile("[\ue000-\uf8ff]")


def _fix_bullet_glyphs(text):
    for glyph, bullet in _BULLET_GLYPH_MAP.items():
        text = text.replace(glyph, bullet)
    return _PUA_RE.sub("•", text)


def normalize_text(text):

    if not text:
        return ""

    text = text.replace("\r", "\n")
    text = text.replace("\x0c", "\n")

    text = _fix_bullet_glyphs(text)

    # Normalize multiplication signs
    text = text.replace("×", "x")

    # Normalize common OCR variations
    text = re.sub(
        r"\bTIRADS\b",
        "TI-RADS",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\bTI\s*[- ]?\s*RAD\b",
        "TI-RADS",
        text,
        flags=re.IGNORECASE
    )

    cleaned = []

    for line in text.split("\n"):

        line = line.strip()

        if not line:
            continue

        line = re.sub(r"[ \t]+", " ", line)

        cleaned.append(line)

    return "\n".join(cleaned)


# ============================================================
# VALUE CLEANING
# ============================================================

def clean_value(value):

    if not value:
        return ""

    value = value.strip()

    value = re.sub(r"\s+", " ", value)

    value = value.strip(" :|-")

    return value


# ============================================================
# LABEL/VALUE EXTRACTION
# ============================================================

def get_label_value(lines, labels):

    if isinstance(labels, str):
        labels = [labels]

    for i, line in enumerate(lines):

        for label in labels:

            # Example:
            # Patient Name : John
            # Age / Gender | 40Y / Female

            pattern = (
                r"^\s*"
                + re.escape(label)
                + r"\s*(?::|\||-)?\s*(.*)$"
            )

            match = re.match(
                pattern,
                line,
                re.IGNORECASE
            )

            if match:

                value = clean_value(match.group(1))

                if value:
                    return value

                if i + 1 < len(lines):
                    return clean_value(
                        lines[i + 1]
                    )

    return ""


# ============================================================
# METADATA
# ============================================================

def extract_metadata(text):

    lines = text.split("\n")

    metadata = {}

    metadata["patient_name"] = get_label_value(
        lines,
        ["Patient Name", "Patient"]
    )

    metadata["mrn"] = get_label_value(
        lines,
        ["MRN", "Patient ID"]
    )

    metadata["age_gender"] = get_label_value(
        lines,
        [
            "Age/Sex",
            "Age / Sex",
            "Age/Gender",
            "Age / Gender"
        ]
    )

    metadata["requested_by"] = get_label_value(
        lines,
        [
            "Requested By",
            "Referring Physician",
            "Referring Doctor"
        ]
    )

    metadata["procedure_date"] = get_label_value(
        lines,
        [
            "Procedure Date",
            "Study Date"
        ]
    )

    metadata["study_datetime"] = get_label_value(
        lines,
        [
            "Study Time",
            "Study DateTime"
        ]
    )

    metadata["reported_datetime"] = get_label_value(
        lines,
        [
            "Reported DateTime",
            "Report DateTime"
        ]
    )

    metadata["facility"] = get_label_value(
        lines,
        [
            "Facility",
            "Hospital",
            "Medical Centre",
            "Medical Center"
        ]
    )

    return metadata


# ============================================================
# EXAMINATION
# ============================================================

def extract_examination(text):

    patterns = [
        r"ULTRASOUND\s+OF\s+THYROID",
        r"ULTRASOUND\s+THYROID",
        r"THYROID\s+ULTRASOUND",
        r"ULTRASONOGRAPHIC\s+EXAMINATION\s+OF\s+THE\s+THYROID",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return "Ultrasound Thyroid"

    return ""


# ============================================================
# SECTION EXTRACTION
# ============================================================

SECTION_HEADINGS = [
    "FINDINGS",
    "IMPRESSION",
    "CONCLUSION",
    "OPINION",
    "RECOMMENDATIONS",
    "RECOMMENDATION",
    "FOLLOW UP",
    "FOLLOW-UP",
    "DISCLAIMER",
    "TECHNIQUE",
    "COMPARISON",
]


def find_section(text, heading):

    pattern = (
        r"(?:^|\n)\s*"
        + re.escape(heading)
        + r"\s*:?\s*\n?"
        + r"(.*?)"
        + r"(?=\n\s*(?:"
        + "|".join(
            re.escape(h)
            for h in SECTION_HEADINGS
            if h.upper() != heading.upper()
        )
        + r")\s*:|\Z)"
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        return clean_value(match.group(1))

    return ""


# ============================================================
# REMOVE FOOTER / SIGNATURE NOISE
# ============================================================

def remove_footer(text):

    if not text:
        return ""

    stop_patterns = [
        r"\*\*\*End of Report\*\*\*",
        r"\* This is a digitally signed",
        r"Digitally validated",
        r"Transcribed By",
        r"Transcribed by",
        r"Page \d+ of \d+",
        r"Disclaimer:",
    ]

    lines = text.split("\n")
    result = []

    for line in lines:

        should_stop = False

        for pattern in stop_patterns:

            if re.search(
                pattern,
                line,
                re.IGNORECASE
            ):
                should_stop = True
                break

        if should_stop:
            break

        result.append(line)

    return "\n".join(result)


# ============================================================
# FINDINGS
# ============================================================

def clean_finding_line(line):

    line = line.strip()

    # Remove bullets
    line = re.sub(
        r"^[•●▪◦*-]\s*",
        "",
        line
    )

    line = re.sub(
        r"^\d+[\.\)]\s*",
        "",
        line
    )

    return clean_value(line)


def split_findings(text):

    if not text:
        return []

    text = remove_footer(text)

    lines = text.split("\n")

    findings = []

    current = ""

    for line in lines:

        line = clean_finding_line(line)

        if not line:
            continue

        # Ignore obvious footer garbage
        if re.search(
            r"digitally validated|transcribed by|end of report|radiologist",
            line,
            re.IGNORECASE
        ):
            continue

        # Ignore hospital/footer-like lines
        if "©" in line:
            continue

        if current:

            # Continue wrapped sentence
            current += " " + line

        else:

            current = line

        # Finish at sentence boundary
        if re.search(r"[.!?]$", line):

            findings.append(
                clean_value(current)
            )

            current = ""

    if current:
        findings.append(
            clean_value(current)
        )

    return findings


def extract_findings(text):

    findings_text = find_section(
        text,
        "FINDINGS"
    )

    if not findings_text:

        # Some reports use US Neck / body text
        # without a FINDINGS heading.
        findings_text = find_section(
            text,
            "US Neck"
        )

    return split_findings(
        findings_text
    )


# ============================================================
# IMPRESSION / CONCLUSION / OPINION
# ============================================================

def extract_impression(text):

    for heading in [
        "IMPRESSION",
        "CONCLUSION",
        "OPINION"
    ]:

        value = find_section(
            text,
            heading
        )

        if value:

            return split_findings(value)

    return []


# ============================================================
# RECOMMENDATIONS
# ============================================================

def extract_recommendations(text):

    for heading in [
        "RECOMMENDATIONS",
        "RECOMMENDATION",
        "FOLLOW UP",
        "FOLLOW-UP"
    ]:

        value = find_section(
            text,
            heading
        )

        if value:

            return split_findings(value)

    return []


# ============================================================
# MEASUREMENTS
# ============================================================

def extract_measurements(text):

    measurements = []

    # --------------------------------------------------------
    # Right lobe
    # --------------------------------------------------------

    right_patterns = [
        r"Right\s+lobe.*?measures?\s*"
        r"([0-9.]+\s*x\s*[0-9.]+\s*x\s*[0-9.]+\s*cm)"
        r".*?volume\s*[:=]\s*([0-9.]+)\s*ml",

        r"Right\s+lobe.*?measures?\s*"
        r"([0-9.]+\s*x\s*[0-9.]+\s*x\s*[0-9.]+\s*cm)",
    ]

    right_size = ""
    right_volume = ""

    for pattern in right_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            right_size = clean_value(
                match.group(1)
            )

            if match.lastindex and match.lastindex >= 2:
                right_volume = clean_value(
                    match.group(2)
                )

            break

    if right_size:

        measurements.append({
            "name": "Right thyroid lobe",
            "size": right_size,
            "volume": (
                right_volume + " ml"
                if right_volume
                else ""
            )
        })

    # --------------------------------------------------------
    # Left lobe
    # --------------------------------------------------------

    left_patterns = [
        r"Left\s+lobe.*?measures?\s*"
        r"([0-9.]+\s*x\s*[0-9.]+\s*x\s*[0-9.]+\s*cm)"
        r".*?volume\s*[:=]\s*([0-9.]+)\s*ml",

        r"Left\s+lobe.*?measures?\s*"
        r"([0-9.]+\s*x\s*[0-9.]+\s*x\s*[0-9.]+\s*cm)",
    ]

    left_size = ""
    left_volume = ""

    for pattern in left_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            left_size = clean_value(
                match.group(1)
            )

            if match.lastindex and match.lastindex >= 2:
                left_volume = clean_value(
                    match.group(2)
                )

            break

    if left_size:

        measurements.append({
            "name": "Left thyroid lobe",
            "size": left_size,
            "volume": (
                left_volume + " ml"
                if left_volume
                else ""
            )
        })

    # --------------------------------------------------------
    # Isthmus
    # --------------------------------------------------------

    isthmus_match = re.search(
        r"Isthmus(?:\s+measures?)?\s*"
        r"([0-9.]+\s*(?:mm|cm))",
        text,
        re.IGNORECASE
    )

    if isthmus_match:

        measurements.append({
            "name": "Isthmus",
            "size": clean_value(
                isthmus_match.group(1)
            ),
            "volume": ""
        })

    return measurements


# ============================================================
# NODULE EXTRACTION
# ============================================================

def extract_nodules(text):

    nodules = []

    # Normalize line wrapping
    searchable = re.sub(
        r"\s+",
        " ",
        text
    )

    # --------------------------------------------------------
    # Explicit nodule descriptions
    # --------------------------------------------------------

    patterns = [

        # Right/left + size + nodule + TI-RADS
        (
            r"(Right|Left)\s+lobe.*?"
            r"nodule.*?"
            r"measur(?:ing|es?)?\s*"
            r"([0-9.]+\s*x\s*[0-9.]+\s*(?:x\s*[0-9.]+\s*)?cm|"
            r"[0-9.]+\s*x\s*[0-9.]+\s*(?:mm))"
            r".{0,300}?"
            r"(?:TI[- ]?RADS?|TI[- ]?RAD)\s*"
            r"([1-5])"
        ),

        # Generic nodule with TI-RADS
        (
            r"(?:nodule|lesion).*?"
            r"([0-9.]+\s*x\s*[0-9.]+\s*(?:x\s*[0-9.]+\s*)?cm|"
            r"[0-9.]+\s*x\s*[0-9.]+\s*(?:mm))"
            r".{0,300}?"
            r"(?:TI[- ]?RADS?|TI[- ]?RAD)\s*"
            r"([1-5])"
        ),
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            searchable,
            re.IGNORECASE
        ):

            location = clean_value(
                match.group(1)
            ) if match.lastindex >= 3 else ""

            size = clean_value(
                match.group(2)
                if match.lastindex >= 3
                else match.group(1)
            )

            tirads_number = (
                match.group(3)
                if match.lastindex >= 3
                else match.group(2)
            )

            tirads = "TR" + tirads_number

            # Avoid duplicates
            duplicate = any(
                n["size"] == size
                and n["tirads"] == tirads
                for n in nodules
            )

            if not duplicate:

                nodules.append({
                    "location": location,
                    "size": size,
                    "description": "Nodule",
                    "tirads": tirads
                })

    # --------------------------------------------------------
    # Detect nodules even when no TI-RADS is given
    # --------------------------------------------------------

    generic_pattern = (
        r"(right|left)\s+lobe.{0,250}?"
        r"(?:a\s+)?(?:well-defined\s+|ill-defined\s+|"
        r"spongiform\s+|cystic\s+)?"
        r"(?:nodule|lesion).{0,150}?"
        r"(?:size|measuring|measures?)\s*"
        r"([0-9.]+\s*x\s*[0-9.]+\s*(?:x\s*[0-9.]+\s*)?"
        r"(?:cm|mm))"
    )

    for match in re.finditer(
        generic_pattern,
        searchable,
        re.IGNORECASE
    ):

        location = match.group(1).title()
        size = clean_value(match.group(2))

        duplicate = any(
            n["location"].lower() == location.lower()
            and n["size"] == size
            for n in nodules
        )

        if not duplicate:

            nodules.append({
                "location": location,
                "size": size,
                "description": "Nodule / lesion",
                "tirads": ""
            })

    return nodules


# ============================================================
# INDICATION
# ============================================================

def extract_indication(text):

    lines = text.split("\n")

    return get_label_value(
        lines,
        [
            "Indication",
            "Clinical Indication",
            "Clinical indication"
        ]
    )


# ============================================================
# MAIN STRUCTURED EXTRACTION
# ============================================================

def extract_report_information(text):

    text = normalize_text(text)

    metadata = extract_metadata(text)

    report = {

        "metadata": metadata,

        "examination": extract_examination(
            text
        ),

        "indication": extract_indication(
            text
        ),

        "measurements": extract_measurements(
            text
        ),

        "findings": extract_findings(
            text
        ),

        "nodules": extract_nodules(
            text
        ),

        "impression": extract_impression(
            text
        ),

        "recommendations": extract_recommendations(
            text
        ),
    }

    # If the source report has no explicit Recommendations/Follow-up
    # section, derive recommendations from the extracted nodule data
    # using ACR TI-RADS guidelines instead of leaving it empty.
    if not report["recommendations"]:
        report["recommendations"] = recommendation_engine.generate_recommendations(report)

    return report


# ============================================================
# ROUTE
# ============================================================

@app.route("/", methods=["GET", "POST"])
def index():

    message = None
    error = None

    extracted_text = None
    report_data = None

    extraction_method = None
    ocr_confidence = None

    if request.method == "POST":

        if "report" not in request.files:

            error = "Please select a medical report PDF."

        else:

            file = request.files["report"]

            if file.filename == "":

                error = "Please select a medical report PDF."

            elif not allowed_file(file.filename):

                error = "Only PDF files are supported."

            else:

                try:

                    original_name = secure_filename(
                        file.filename
                    )

                    unique_name = (
                        str(uuid.uuid4())
                        + "_"
                        + original_name
                    )

                    save_path = os.path.join(
                        app.config["UPLOAD_FOLDER"],
                        unique_name
                    )

                    file.save(save_path)

                    # ------------------------------------------
                    # First try direct text extraction
                    # ------------------------------------------

                    extracted_text = extract_pdf_text(
                        save_path
                    )

                    if extracted_text.strip():

                        extraction_method = (
                            "PDF text extraction"
                        )

                        ocr_confidence = None

                        message = (
                            "Report analyzed successfully."
                        )

                    else:

                        # --------------------------------------
                        # OCR fallback (pytesseract, with image
                        # preprocessing + PSM fallback + confidence)
                        # --------------------------------------

                        extracted_text, ocr_confidence, page_count = (
                            ocr_engine.run_ocr_on_pdf(save_path)
                        )

                        extraction_method = (
                            "Tesseract OCR"
                        )

                        if extracted_text.strip():
                            message = (
                                "Scanned PDF detected. Tesseract OCR was "
                                "used across {} page(s) (avg. confidence "
                                "{}%).".format(page_count, ocr_confidence)
                            )
                        else:
                            message = (
                                "Scanned PDF detected. Tesseract OCR was "
                                "attempted but returned no readable text."
                            )

                    # ------------------------------------------
                    # Structure the report
                    # ------------------------------------------

                    if extracted_text.strip():

                        report_data = (
                            extract_report_information(
                                extracted_text
                            )
                        )

                        # --------------------------------------
                        # Risk analysis + save
                        # --------------------------------------

                        content_hash = database.compute_content_hash(
                            extracted_text
                        )

                        risk_level, risk_flags = (
                            risk_analyzer.analyze_risk(report_data)
                        )

                        if ocr_confidence is not None and ocr_confidence < ocr_engine.LOW_CONFIDENCE_THRESHOLD:
                            risk_flags.append(
                                "Low OCR confidence ({}%) - please verify extracted "
                                "text against the original scanned document.".format(ocr_confidence)
                            )
                            if risk_level == "LOW":
                                risk_level = "MEDIUM"

                        database.save_report(
                            original_name,
                            report_data,
                            extracted_text,
                            extraction_method,
                            content_hash,
                            risk_level,
                            risk_flags,
                            ocr_confidence,
                        )

                    else:

                        error = (
                            "No readable text was found "
                            "in this report, even after OCR."
                        )

                except Exception as exc:

                    error = str(exc)

    return render_template(
        "index.html",

        message=message,
        error=error,

        extracted_text=extracted_text,

        report_data=report_data,

        extraction_method=extraction_method,
        ocr_confidence=ocr_confidence,
    )


# ============================================================
# SHARED BATCH-UPLOAD PROCESSING
# ============================================================

def process_single_pdf(save_path, original_filename):
    """
    Runs the same extraction pipeline as the single-upload route,
    but returns a result dict instead of rendering a page.
    Used by /batch-upload for multi-file uploads.
    """

    extracted_text = extract_pdf_text(save_path)
    extraction_method = "PDF text extraction"
    ocr_confidence = None

    if not extracted_text.strip():
        extracted_text, ocr_confidence, _page_count = ocr_engine.run_ocr_on_pdf(save_path)
        extraction_method = "Tesseract OCR"

    if not extracted_text.strip():
        raise ValueError("No readable text was found in this report, even after OCR.")

    report_data = extract_report_information(extracted_text)
    content_hash = database.compute_content_hash(extracted_text)

    risk_level, risk_flags = risk_analyzer.analyze_risk(report_data)

    if ocr_confidence is not None and ocr_confidence < ocr_engine.LOW_CONFIDENCE_THRESHOLD:
        risk_flags.append(
            "Low OCR confidence ({}%) - please verify extracted "
            "text against the original scanned document.".format(ocr_confidence)
        )
        if risk_level == "LOW":
            risk_level = "MEDIUM"

    report_id = database.save_report(
        original_filename,
        report_data,
        extracted_text,
        extraction_method,
        content_hash,
        risk_level,
        risk_flags,
        ocr_confidence,
    )

    return {
        "status": "ok",
        "report_id": report_id,
        "filename": original_filename,
        "risk_level": risk_level,
        "ocr_confidence": ocr_confidence,
    }


# ============================================================
# BATCH UPLOAD ROUTE
# ============================================================

@app.route("/batch-upload", methods=["POST"])
def batch_upload():

    files = request.files.getlist("reports")
    results = []

    for file in files:

        if file.filename == "" or not allowed_file(file.filename):
            results.append({
                "status": "error",
                "filename": file.filename,
                "error": "Invalid file",
            })
            continue

        try:
            original_name = secure_filename(file.filename)
            unique_name = str(uuid.uuid4()) + "_" + original_name
            save_path = os.path.join(
                app.config["UPLOAD_FOLDER"], unique_name
            )
            file.save(save_path)

            results.append(
                process_single_pdf(save_path, original_name)
            )

        except Exception as exc:
            results.append({
                "status": "error",
                "filename": file.filename,
                "error": str(exc),
            })

    return render_template("batch_results.html", results=results)


# ============================================================
# DASHBOARD / HISTORY / SEARCH
# ============================================================

@app.route("/dashboard")
def dashboard():

    query = request.args.get("q", "").strip()

    reports = (
        database.search_reports(query)
        if query
        else database.get_all_reports()
    )

    return render_template(
        "dashboard.html", reports=reports, query=query
    )


# ============================================================
# RECOMMENDATION CLASSIFICATION (FOR COLORED DISPLAY)
# ============================================================

def classify_recommendations(recommendation_list):
    """
    Takes the plain recommendation strings (either extracted from the
    report text or auto-generated from ACR TI-RADS guidelines) and
    tags each with an urgency level so the UI can show a colored
    badge instead of a flat bullet list.
    """
    classified = []

    for text in recommendation_list:
        lower = text.lower()

        if "fna" in lower or "biopsy" in lower:
            level = "urgent"
            label = "Biopsy advised"
        elif "follow-up ultrasound recommended" in lower or "follow up" in lower or "follow-up" in lower:
            level = "watch"
            label = "Follow-up advised"
        elif "no biopsy" in lower or "no immediate action" in lower or "no nodules" in lower or "not required" in lower:
            level = "clear"
            label = "No action needed"
        else:
            level = "info"
            label = "Note"

        # Strip the bracketed auto-generated tag for cleaner display;
        # we show that provenance separately via the badge instead.
        clean_text = text.replace("[auto-generated from ACR TI-RADS guidelines]", "").strip()

        classified.append({
            "text": clean_text,
            "level": level,
            "label": label,
        })

    return classified


# ============================================================
# REPORT DETAIL
# ============================================================

@app.route("/report/<int:report_id>")
def report_detail(report_id):

    row = database.get_report_by_id(report_id)

    if not row:
        return "Report not found", 404

    report_data = json.loads(row["report_json"])
    risk_flags = json.loads(row["risk_flags"] or "[]")

    points = key_points.generate_key_points(
        report_data, row["risk_level"], risk_flags
    )

    # Render the diagram SVG inline (more reliable than a separate
    # <img src="..."> request, which can fail behind some proxies).
    diagram_svg = thyroid_diagram.build_thyroid_svg(
        report_data.get("nodules", []),
        patient_name=row["patient_name"],
    )

    recommendations = classify_recommendations(
        report_data.get("recommendations", [])
    )

    return render_template(
        "report_detail.html",
        report=row,
        report_data=report_data,
        metadata=report_data.get("metadata", {}),
        risk_flags=risk_flags,
        key_points=points,
        diagram_svg=diagram_svg,
        recommendations=recommendations,
    )


# ============================================================
# EXPORT
# ============================================================

@app.route("/export/<int:report_id>/<fmt>")
def export_report(report_id, fmt):

    row = database.get_report_by_id(report_id)

    if not row:
        return "Report not found", 404

    filename_base = "report_{}".format(report_id)

    if fmt == "json":
        buf = export_utils.export_json(row)
        return send_file(
            buf,
            mimetype="application/json",
            as_attachment=True,
            download_name=filename_base + ".json",
        )

    if fmt == "csv":
        buf = export_utils.export_csv(row)
        return send_file(
            buf,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename_base + ".csv",
        )

    if fmt == "pdf":
        buf = export_utils.export_pdf(row)
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename_base + ".pdf",
        )

    return "Unsupported format", 400


# ============================================================
# TREND ANALYSIS (PER PATIENT / MRN)
# ============================================================

@app.route("/trend/<mrn>")
def trend(mrn):

    reports = database.get_reports_by_mrn(mrn)
    trend_rows = []
    previous_largest = None

    for row in reports:

        report_data = json.loads(row["report_json"])
        nodules = report_data.get("nodules", [])

        sizes = [
            risk_analyzer._max_dimension_cm(n.get("size", ""))
            for n in nodules
        ]

        largest = max(sizes) if sizes else 0

        change = None

        if previous_largest is not None:
            if largest > previous_largest:
                change = "up"
            elif largest < previous_largest:
                change = "down"
            else:
                change = "same"

        trend_rows.append({
            "id": row["id"],
            "procedure_date": row["procedure_date"],
            "risk_level": row["risk_level"],
            "nodule_count": len(nodules),
            "largest_nodule_size": (
                "{} cm".format(largest) if largest else None
            ),
            "change": change,
        })

        previous_largest = largest

    patient_name = reports[0]["patient_name"] if reports else None

    return render_template(
        "trend.html",
        mrn=mrn,
        patient_name=patient_name,
        reports=reports,
        trend_rows=trend_rows,
    )


# ============================================================
# CHATBOT (PER REPORT)
# ============================================================

@app.route("/chatbot/<int:report_id>", methods=["POST"])
def chatbot_query(report_id):

    row = database.get_report_by_id(report_id)

    if not row:
        return jsonify({"answer": "Report not found."}), 404

    question = request.json.get("question", "") if request.json else ""

    report_data = json.loads(row["report_json"])
    risk_flags = json.loads(row["risk_flags"] or "[]")

    answer = chatbot.answer_question(
        question, report_data, row["risk_level"], risk_flags
    )

    return jsonify({"answer": answer})


# ============================================================
# THYROID DIAGRAM (SVG)
# ============================================================

@app.route("/diagram/<int:report_id>.svg")
def diagram_svg(report_id):

    row = database.get_report_by_id(report_id)

    if not row:
        return "Report not found", 404

    report_data = json.loads(row["report_json"])
    svg = thyroid_diagram.build_thyroid_svg(
        report_data.get("nodules", []),
        patient_name=row["patient_name"],
    )

    return Response(svg, mimetype="image/svg+xml")


# ============================================================
# FOLLOW-UP SCHEDULER (.ics EXPORT)
# ============================================================

@app.route("/followup/<int:report_id>")
def followup_info(report_id):

    row = database.get_report_by_id(report_id)

    if not row:
        return jsonify({"error": "Report not found"}), 404

    plan = followup_scheduler.get_followup_plan(row)

    return jsonify({
        "needed": plan["needed"],
        "reason": plan["reason"],
        "months": plan["months"],
        "due_date": plan["due_date"].strftime("%Y-%m-%d") if plan["due_date"] else None,
    })


@app.route("/followup/<int:report_id>/ics")
def followup_ics(report_id):

    row = database.get_report_by_id(report_id)

    if not row:
        return "Report not found", 404

    ics_bytes = followup_scheduler.generate_ics(row)

    return Response(
        ics_bytes,
        mimetype="text/calendar",
        headers={
            "Content-Disposition": "attachment; filename=followup_report_{}.ics".format(report_id)
        },
    )


# ============================================================
# GLOBAL CHATBOT (ACROSS ALL REPORTS)
# ============================================================

@app.route("/chat")
def global_chat_page():
    return render_template("global_chat.html")


@app.route("/diagnostics")
def diagnostics():
    """
    Quick health check for the two most common setup problems:
    Tesseract OCR not installed, and the Gemini API key missing.
    Visit /diagnostics in the browser after starting the app.
    """
    import ai_client

    return jsonify({
        "tesseract_ready": ocr_engine.TESSERACT_READY,
        "tesseract_error": ocr_engine.TESSERACT_ERROR,
        "tesseract_cmd": pytesseract_cmd_or_none(),
        "gemini_api_key_set": bool(ai_client.GEMINI_API_KEY),
        "gemini_model": ai_client.GEMINI_MODEL,
    })


def pytesseract_cmd_or_none():
    try:
        import pytesseract
        return pytesseract.pytesseract.tesseract_cmd
    except Exception:
        return None


@app.route("/global-chatbot", methods=["POST"])
def global_chatbot_query():

    question = request.json.get("question", "") if request.json else ""
    reports = database.get_all_reports()

    answer = global_chatbot.answer_question(question, reports)

    return jsonify({"answer": answer})


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
