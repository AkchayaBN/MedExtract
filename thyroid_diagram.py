"""
thyroid_diagram.py
===================
Builds a clean, professional, color-coded SVG diagram of the thyroid
gland (right lobe, left lobe, isthmus) with each extracted nodule
plotted at its approximate anatomical position, sized and colored by
TI-RADS category.

The diagram is anterior-view, so the patient's *right* lobe appears
on the viewer's *left* side of the image (standard medical convention).
"""

import re

TIRADS_COLORS = {
    "TR1": "#2ecc71",   # green   - benign
    "TR2": "#27ae60",   # dark green - not suspicious
    "TR3": "#f1c40f",   # yellow  - mildly suspicious
    "TR4": "#e67e22",   # orange  - moderately suspicious
    "TR5": "#e74c3c",   # red     - highly suspicious
    "": "#95a5a6",       # gray    - unspecified
}

TIRADS_LABELS = {
    "TR1": "TR1 - Benign",
    "TR2": "TR2 - Not suspicious",
    "TR3": "TR3 - Mildly suspicious",
    "TR4": "TR4 - Moderately suspicious",
    "TR5": "TR5 - Highly suspicious",
    "": "Unspecified risk",
}


def _max_dimension_cm(size_str):
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


def _locate_nodule(location_text, index, total_in_zone):
    """
    Parses free-text location (e.g. 'Left lower pole', 'Right lobe')
    into an (x, y, zone_label) anchor point on a 700x460 canvas.
    Falls back to the isthmus/center if side can't be determined.
    """
    text = (location_text or "").lower()

    is_right = "right" in text
    is_left = "left" in text

    is_upper = "upper" in text or "superior" in text
    is_lower = "lower" in text or "inferior" in text

    # Anterior view: patient's right = image left, patient's left = image right
    if is_right:
        base_x = 250
        zone = "Right lobe"
    elif is_left:
        base_x = 450
        zone = "Left lobe"
    else:
        base_x = 350
        zone = "Isthmus / unspecified"

    if is_upper:
        base_y = 160
    elif is_lower:
        base_y = 320
    else:
        base_y = 240

    # Small deterministic offset so multiple nodules in the same
    # zone don't render exactly on top of each other.
    offset = (index % 3) * 22 - 22
    return base_x + offset, base_y + (index // 3) * 20, zone


def build_thyroid_svg(nodules, patient_name=None):
    """Returns a full standalone SVG string (700x520) for the diagram."""

    width, height = 700, 520

    svg_parts = []
    svg_parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {} {}" width="100%" height="auto" '
        'font-family="Arial, Helvetica, sans-serif">'.format(width, height)
    )

    # --- Background ---
    svg_parts.append(
        '<rect x="0" y="0" width="{}" height="{}" fill="#f4f9fc" rx="14"/>'.format(width, height)
    )

    # --- Title ---
    svg_parts.append(
        '<text x="{}" y="34" text-anchor="middle" font-size="20" font-weight="700" '
        'fill="#173f73">Thyroid Nodule Map</text>'.format(width // 2)
    )
    if patient_name:
        svg_parts.append(
            '<text x="{}" y="54" text-anchor="middle" font-size="12" fill="#5a6b84">'
            '{}</text>'.format(width // 2, patient_name.replace("&", "and"))
        )

    # --- Gradient defs for a soft tissue-like fill ---
    svg_parts.append("""
    <defs>
        <linearGradient id="lobeGradient" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#ffd9d0"/>
            <stop offset="100%" stop-color="#f3a58f"/>
        </linearGradient>
        <linearGradient id="isthmusGradient" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#ffcfc3"/>
            <stop offset="100%" stop-color="#f0967f"/>
        </linearGradient>
        <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="0.15"/>
        </filter>
    </defs>
    """)

    # --- Thyroid butterfly shape: right lobe, left lobe, isthmus ---
    # Right lobe (image-left, patient's right)
    svg_parts.append(
        '<ellipse cx="250" cy="240" rx="95" ry="140" fill="url(#lobeGradient)" '
        'stroke="#c0503a" stroke-width="2.5" filter="url(#softShadow)"/>'
    )
    # Left lobe (image-right, patient's left)
    svg_parts.append(
        '<ellipse cx="450" cy="240" rx="95" ry="140" fill="url(#lobeGradient)" '
        'stroke="#c0503a" stroke-width="2.5" filter="url(#softShadow)"/>'
    )
    # Isthmus connecting the two lobes
    svg_parts.append(
        '<rect x="270" y="215" width="160" height="50" rx="20" '
        'fill="url(#isthmusGradient)" stroke="#c0503a" stroke-width="2.5" filter="url(#softShadow)"/>'
    )

    # --- Anatomical labels ---
    svg_parts.append(
        '<text x="250" y="392" text-anchor="middle" font-size="14" font-weight="600" '
        'fill="#173f73">Right Lobe</text>'
    )
    svg_parts.append(
        '<text x="450" y="392" text-anchor="middle" font-size="14" font-weight="600" '
        'fill="#173f73">Left Lobe</text>'
    )
    svg_parts.append(
        '<text x="350" y="205" text-anchor="middle" font-size="11" font-weight="600" '
        'fill="#7a3b2c">Isthmus</text>'
    )
    svg_parts.append(
        '<text x="250" y="105" text-anchor="middle" font-size="10" fill="#5a6b84">Upper pole</text>'
    )
    svg_parts.append(
        '<text x="250" y="378" text-anchor="middle" font-size="10" fill="#5a6b84"></text>'
    )

    # --- Plot nodules ---
    zone_counters = {}

    for nodule in nodules:
        location = nodule.get("location", "")
        size_cm = _max_dimension_cm(nodule.get("size", ""))
        tirads = (nodule.get("tirads") or "").upper()
        color = TIRADS_COLORS.get(tirads, TIRADS_COLORS[""])

        zone_key = location.lower() or "center"
        idx = zone_counters.get(zone_key, 0)
        zone_counters[zone_key] = idx + 1

        x, y, _zone = _locate_nodule(location, idx, zone_counters[zone_key])

        # Radius scales with size, clamped for readability
        radius = max(10, min(34, 8 + size_cm * 9))

        svg_parts.append(
            '<circle cx="{}" cy="{}" r="{}" fill="{}" fill-opacity="0.85" '
            'stroke="#ffffff" stroke-width="2.5" filter="url(#softShadow)">'
            '<title>{} nodule, {} at {}</title></circle>'.format(
                x, y, radius, color,
                tirads or "Unspecified", nodule.get("size", "size unknown"),
                location or "unspecified location"
            )
        )

        label = nodule.get("size", "")
        svg_parts.append(
            '<text x="{}" y="{}" text-anchor="middle" font-size="10" font-weight="700" '
            'fill="#ffffff">{}</text>'.format(x, y + 4, tirads or "?")
        )
        svg_parts.append(
            '<text x="{}" y="{}" text-anchor="middle" font-size="9" '
            'fill="#26364a">{}</text>'.format(x, y + radius + 13, label)
        )

    # --- Legend ---
    legend_x = 30
    legend_y = 430
    svg_parts.append(
        '<text x="{}" y="{}" font-size="12" font-weight="700" fill="#173f73">'
        'TI-RADS Legend</text>'.format(legend_x, legend_y)
    )

    for i, key in enumerate(["TR1", "TR2", "TR3", "TR4", "TR5", ""]):
        cx = legend_x + 10 + (i % 3) * 220
        cy = legend_y + 20 + (i // 3) * 24
        svg_parts.append(
            '<circle cx="{}" cy="{}" r="7" fill="{}"/>'.format(cx, cy, TIRADS_COLORS[key])
        )
        svg_parts.append(
            '<text x="{}" y="{}" font-size="11" fill="#26364a">{}</text>'.format(
                cx + 14, cy + 4, TIRADS_LABELS[key]
            )
        )

    if not nodules:
        svg_parts.append(
            '<text x="{}" y="{}" text-anchor="middle" font-size="13" fill="#7a8aa0" '
            'font-style="italic">No nodules were extracted for this report.</text>'.format(
                width // 2, height - 20
            )
        )

    svg_parts.append("</svg>")
    return "".join(svg_parts)
