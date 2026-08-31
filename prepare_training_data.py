import pandas as pd
import shutil
from pathlib import Path


BASE = Path(
    "datasets/handwriting/Doctor’s Handwritten Prescription BD dataset"
)

SETS = {
    "Training": {
        "csv": "training_labels.csv",
        "images": "training_words",
        "output": "tesstrain/data/medical-ground-truth",
    },
    "Validation": {
        "csv": "validation_labels.csv",
        "images": "validation_words",
        "output": "tesstrain/data/medical-validation",
    },
    "Testing": {
        "csv": "testing_labels.csv",
        "images": "testing_words",
        "output": "tesstrain/data/medical-test",
    },
}


def prepare_dataset(set_name, config):
    print(f"\nProcessing {set_name}...")

    csv_path = BASE / set_name / config["csv"]
    images_dir = BASE / set_name / config["images"]
    output_dir = Path(config["output"])

    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path)

    print("Columns:", df.columns.tolist())
    print("Rows:", len(df))

    count = 0
    missing = 0

    for _, row in df.iterrows():

        image_name = str(row["IMAGE"]).strip()
        medicine_name = str(row["MEDICINE_NAME"]).strip()

        # Skip empty or invalid labels
        if not medicine_name or medicine_name.lower() == "nan":
            continue

        src_image = images_dir / image_name

        if not src_image.exists():
            missing += 1
            continue

        base_name = Path(image_name).stem

        # Add dataset prefix to avoid filename collisions
        output_base = f"{set_name.lower()}_{base_name}"

        dst_image = output_dir / f"{output_base}.png"
        dst_gt = output_dir / f"{output_base}.gt.txt"

        shutil.copy2(src_image, dst_image)

        with open(dst_gt, "w", encoding="utf-8") as f:
            f.write(medicine_name)

        count += 1

    print(f"Prepared: {count}")
    print(f"Missing images: {missing}")
    print(f"Output: {output_dir}")


for set_name, config in SETS.items():
    prepare_dataset(set_name, config)

print("\nDone!")
