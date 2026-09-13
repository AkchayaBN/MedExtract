import logging
import os
import platform
import shutil
import tempfile
import uuid

import fitz
import pytesseract
from PIL import Image, ImageOps, ImageEnhance

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

# OCR confidence below this value will be flagged by app.py
LOW_CONFIDENCE_THRESHOLD = 70.0

# Set to True once configure_tesseract() has confirmed a working
# Tesseract install. If this is False, run_ocr_on_pdf() will raise
# a clear, actionable error instead of silently returning empty text.
TESSERACT_READY = False
TESSERACT_ERROR = None


# ============================================================
# FIND TESSERACT (WINDOWS / MACOS / LINUX)
# ============================================================

def configure_tesseract():
    """
    Configure the Tesseract executable across platforms.

    1. Try the system PATH (works out of the box on Linux/macOS if the
       `tesseract-ocr` / `tesseract` system package is installed, and on
       Windows if it was added to PATH during install).
    2. Fall back to common known install locations per OS.

    IMPORTANT: pip installing `pytesseract` only installs a thin Python
    wrapper - it does NOT install the actual Tesseract OCR engine. The
    engine has to be installed separately:
        - Windows: https://github.com/UB-Mannheim/tesseract/wiki
        - macOS:   brew install tesseract
        - Linux:   sudo apt-get install tesseract-ocr  (Debian/Ubuntu)
                   sudo dnf install tesseract           (Fedora)
    """
    global TESSERACT_READY, TESSERACT_ERROR

    system = platform.system()

    possible_paths = []
    if system == "Windows":
        possible_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(
                r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"
            ),
        ]
    elif system == "Darwin":
        possible_paths = [
            "/opt/homebrew/bin/tesseract",   # Apple Silicon Homebrew
            "/usr/local/bin/tesseract",      # Intel Homebrew
            "/opt/local/bin/tesseract",      # MacPorts
        ]
    else:  # Linux and others
        possible_paths = [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]

    # 1. Already resolvable via PATH?
    which_path = shutil.which(pytesseract.pytesseract.tesseract_cmd or "tesseract")
    if which_path:
        try:
            pytesseract.get_tesseract_version()
            TESSERACT_READY = True
            TESSERACT_ERROR = None
            logger.info("Tesseract found on PATH: %s", which_path)
            return
        except Exception as exc:
            TESSERACT_ERROR = str(exc)

    # 2. Check common install locations for this OS.
    for path in possible_paths:
        if path and os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            try:
                pytesseract.get_tesseract_version()
                TESSERACT_READY = True
                TESSERACT_ERROR = None
                logger.info("Tesseract found at: %s", path)
                return
            except Exception as exc:
                TESSERACT_ERROR = str(exc)

    # 3. Nothing worked - record a clear, actionable error instead of
    #    silently letting every OCR call fail later with an empty result.
    TESSERACT_READY = False
    if TESSERACT_ERROR is None:
        TESSERACT_ERROR = (
            "Tesseract executable was not found on PATH or in any common "
            "install location for {}.".format(system)
        )
    logger.warning("Tesseract is not configured correctly: %s", TESSERACT_ERROR)


configure_tesseract()


# ============================================================
# IMAGE PREPROCESSING
# ============================================================

def preprocess_image(pil_image):
    """
    Improve scanned medical-report image quality before OCR.
    """

    # Convert to grayscale
    image = ImageOps.grayscale(pil_image)

    # Increase contrast
    image = ImageEnhance.Contrast(image).enhance(2.0)

    # Increase sharpness
    image = ImageEnhance.Sharpness(image).enhance(1.5)

    return image


# ============================================================
# OCR ONE PAGE
# ============================================================

def ocr_page(image):
    """
    Run OCR on a single PDF page.

    Multiple PSM modes are attempted and the result
    with the highest confidence is returned.
    """

    processed_image = preprocess_image(image)

    psm_modes = [6, 3, 11]

    best_text = ""
    best_confidence = 0.0

    for psm in psm_modes:

        try:
            data = pytesseract.image_to_data(
                processed_image,
                lang="eng",
                config="--psm {}".format(psm),
                output_type=pytesseract.Output.DICT
            )
        except pytesseract.pytesseract.TesseractNotFoundError:
            # Don't swallow this - a missing/misconfigured Tesseract
            # install should surface as a clear error, not as "0 pages
            # of text found".
            raise
        except pytesseract.pytesseract.TesseractError as exc:
            # A specific PSM mode failing (e.g. unsupported language
            # data) is fine to skip and try the next mode.
            logger.warning("Tesseract PSM %s failed: %s", psm, exc)
            continue

        try:

            words = []
            confidences = []

            for text, confidence in zip(
                data.get("text", []),
                data.get("conf", [])
            ):

                text = text.strip()

                if not text:
                    continue

                try:
                    confidence = float(confidence)
                except (ValueError, TypeError):
                    continue

                if confidence >= 0:
                    words.append(text)
                    confidences.append(confidence)

            text = " ".join(words).strip()

            if confidences:
                average_confidence = (
                    sum(confidences) / len(confidences)
                )
            else:
                average_confidence = 0.0

            if (
                average_confidence > best_confidence
                or (
                    average_confidence == best_confidence
                    and len(text) > len(best_text)
                )
            ):
                best_text = text
                best_confidence = average_confidence

        except Exception:
            continue

    return best_text, best_confidence


# ============================================================
# OCR PDF
# ============================================================

def run_ocr_on_pdf(pdf_path):
    """
    Convert every page of a scanned PDF to an image
    and run Tesseract OCR.

    Returns:
        extracted_text
        average_confidence
        page_count
    """

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            "PDF file not found: {}".format(pdf_path)
        )

    if not TESSERACT_READY:
        raise RuntimeError(
            "Tesseract OCR engine is not available: {} "
            "The pytesseract PIP package only wraps the engine, it does "
            "not install it. Install the actual Tesseract binary "
            "(Windows: https://github.com/UB-Mannheim/tesseract/wiki, "
            "macOS: 'brew install tesseract', "
            "Linux: 'sudo apt-get install tesseract-ocr'), then restart "
            "the app.".format(TESSERACT_ERROR)
        )

    doc = fitz.open(pdf_path)

    page_texts = []
    page_confidences = []

    try:

        page_count = len(doc)

        for page_number, page in enumerate(doc):

            # Render PDF page as a high-resolution image.
            # 2.0 gives approximately 144 DPI.
            matrix = fitz.Matrix(2.0, 2.0)

            pix = page.get_pixmap(
                matrix=matrix,
                alpha=False
            )

            # Convert PyMuPDF image bytes directly into PIL.
            # No /tmp path is required.
            image = Image.frombytes(
                "RGB",
                [pix.width, pix.height],
                pix.samples
            )

            text, confidence = ocr_page(image)

            if text.strip():
                page_texts.append(
                    "Page {}:\n{}".format(
                        page_number + 1,
                        text
                    )
                )

                page_confidences.append(confidence)

    finally:
        doc.close()

    # Combine all pages
    extracted_text = "\n\n".join(page_texts).strip()

    if page_confidences:
        average_confidence = (
            sum(page_confidences)
            / len(page_confidences)
        )
    else:
        average_confidence = 0.0

    return (
        extracted_text,
        round(average_confidence, 2),
        page_count
    )