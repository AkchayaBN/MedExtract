import os
import re
import uuid
import subprocess

import fitz
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename


app = Flask(__name__)

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
# OCR FALLBACK
# ============================================================

def run_ocr_on_pdf(pdf_path):
    """
    Render PDF pages to images and run Tesseract.
    Used only when the PDF has no usable text layer.
    """

    doc = fitz.open(pdf_path)
    pages = []

    try:
        for page_number, page in enumerate(doc):

            pix = page.get_pixmap(
                matrix=fitz.Matrix(2, 2),
                alpha=False
            )

            image_path = os.path.join(
                "/tmp",
                "medextract_{}.png".format(uuid.uuid4())
            )

            pix.save(image_path)

            try:
                command = [
                    "tesseract",
                    image_path,
                    "stdout",
                    "-l",
                    "eng",
                    "--psm",
                    "6",
                ]

                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=60,
                )

                if result.returncode != 0:
                    raise RuntimeError(
                        "Tesseract OCR failed: " + result.stderr
                    )

                if result.stdout.strip():

                    pages.append(
                        "PAGE {}\n{}".format(
                            page_number + 1,
                            result.stdout.strip()
                        )
                    )

            finally:

                if os.path.exists(image_path):
                    os.remove(image_path)

    finally:
        doc.close()

    return "\n\n".join(pages).strip()


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = text.replace("\r", "\n")
    text = text.replace("\x0c", "\n")

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

                        message = (
                            "Report analyzed successfully."
                        )

                    else:

                        # --------------------------------------
                        # OCR fallback
                        # --------------------------------------

                        extracted_text = run_ocr_on_pdf(
                            save_path
                        )

                        extraction_method = (
                            "Tesseract OCR"
                        )

                        message = (
                            "Scanned PDF detected. "
                            "Tesseract OCR was used."
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

                    else:

                        error = (
                            "No readable text was found "
                            "in this report."
                        )

                except subprocess.TimeoutExpired:

                    error = (
                        "OCR took too long. "
                        "Please try another PDF."
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
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
