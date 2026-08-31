import json
import glob
import pandas as pd


JSON_FILES = glob.glob(
    "datasets/ndc/**/*.json",
    recursive=True
)

print("JSON files found:")

for f in JSON_FILES:
    print(" ", f)


if not JSON_FILES:
    raise FileNotFoundError(
        "No JSON files found in datasets/ndc/"
    )


records = []


for json_file in JSON_FILES:

    print(
        f"\nProcessing: {json_file}"
    )

    with open(
        json_file,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)


    # openFDA download files normally
    # contain a 'results' list
    if isinstance(data, dict):
        items = data.get(
            "results",
            []
        )

    elif isinstance(data, list):
        items = data

    else:
        items = []


    print(
        f"Records found: {len(items)}"
    )


    for item in items:

        brand_name = (
            item.get(
                "brand_name",
                ""
            )
            or ""
        ).strip()


        generic_name = (
            item.get(
                "generic_name",
                ""
            )
            or ""
        ).strip()


        dosage_form = (
            item.get(
                "dosage_form",
                ""
            )
            or ""
        ).strip()


        product_ndc = (
            item.get(
                "product_ndc",
                ""
            )
            or ""
        ).strip()


        # Skip records without any usable name
        if not brand_name and not generic_name:
            continue


        # Prefer brand name
        # If no brand name exists, use generic name
        drug_name = (
            brand_name
            if brand_name
            else generic_name
        )


        records.append(
            {
                "drug_name": drug_name,
                "generic_name": generic_name,
                "dosage_form": dosage_form,
                "ndc_code": product_ndc
            }
        )


df = pd.DataFrame(
    records
)


# Remove exact duplicate rows
df = df.drop_duplicates()


print("\nFinal records:")

print(len(df))


df.to_csv(
    "datasets/ndc/drugs_clean.csv",
    index=False
)


print(
    "\nSaved:"
)

print(
    "datasets/ndc/drugs_clean.csv"
)


print("\nPreview:")

print(
    df.head(10)
)
