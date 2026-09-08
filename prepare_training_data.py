import argparse
import shutil
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_DIR = (
    PROJECT_ROOT
    / "datasets"
    / "handwriting"
    / "Doctor's Handwritten Prescription BD dataset"
)
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "tesstrain" / "data"

SETS = {
    "Training": {
        "csv": "training_labels.csv",
        "images": "training_words",
        "output": "medical-ground-truth",
    },
    "Validation": {
        "csv": "validation_labels.csv",
        "images": "validation_words",
        "output": "medical-validation",
    },
    "Testing": {
        "csv": "testing_labels.csv",
        "images": "testing_words",
        "output": "medical-test",
    },
}

REQUIRED_COLUMNS = {"IMAGE", "MEDICINE_NAME"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Prepare handwritten prescription images for Tesseract LSTM training."
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="Dataset root containing Training, Validation, and Testing directories.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where Tesseract ground-truth directories will be created.",
    )
    return parser.parse_args()


def prepare_dataset(dataset_dir, output_root, set_name, config):
    print(f"\nProcessing {set_name}...")

    csv_path = dataset_dir / set_name / config["csv"]
    images_dir = dataset_dir / set_name / config["images"]
    output_dir = output_root / config["output"]

    if not csv_path.is_file():
        raise FileNotFoundError(f"Label CSV not found: {csv_path}")

    if not images_dir.is_dir():
        raise FileNotFoundError(f"Image directory not found: {images_dir}")

    df = pd.read_csv(csv_path)
    missing_columns = REQUIRED_COLUMNS.difference(df.columns)
    if missing_columns:
        missing_list = ", ".join(sorted(missing_columns))
        raise ValueError(f"Label CSV is missing required columns: {missing_list}")

    output_dir.mkdir(parents=True, exist_ok=True)

    print("Columns:", df.columns.tolist())
    print("Rows:", len(df))

    count = 0
    missing = 0

    for _, row in df.iterrows():
        image_name = str(row["IMAGE"]).strip()
        medicine_name = str(row["MEDICINE_NAME"]).strip()

        if not medicine_name or medicine_name.lower() == "nan":
            continue

        src_image = images_dir / image_name
        if not src_image.exists():
            missing += 1
            continue

        base_name = Path(image_name).stem
        output_base = f"{set_name.lower()}_{base_name}"
        dst_image = output_dir / f"{output_base}.png"
        dst_gt = output_dir / f"{output_base}.gt.txt"

        shutil.copy2(src_image, dst_image)
        dst_gt.write_text(medicine_name, encoding="utf-8")
        count += 1

    print(f"Prepared: {count}")
    print(f"Missing images: {missing}")
    print(f"Output: {output_dir}")

    return {"prepared": count, "missing_images": missing, "output_dir": output_dir}


def prepare_all_datasets(dataset_dir, output_root):
    dataset_dir = Path(dataset_dir)
    output_root = Path(output_root)

    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    summaries = {}
    for set_name, config in SETS.items():
        summaries[set_name] = prepare_dataset(
            dataset_dir,
            output_root,
            set_name,
            config,
        )

    print("\nDone!")
    return summaries


def main():
    args = parse_args()
    prepare_all_datasets(args.dataset_dir, args.output_root)


if __name__ == "__main__":
    main()
