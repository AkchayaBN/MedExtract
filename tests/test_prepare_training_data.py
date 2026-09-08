import tempfile
import unittest
from pathlib import Path

import pandas as pd

import prepare_training_data


class PrepareTrainingDataTests(unittest.TestCase):
    def test_prepare_dataset_copies_image_and_writes_ground_truth(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_dir = root / "dataset"
            images_dir = dataset_dir / "Training" / "training_words"
            images_dir.mkdir(parents=True)
            (images_dir / "word_001.png").write_bytes(b"image data")

            labels = pd.DataFrame([
                {"IMAGE": "word_001.png", "MEDICINE_NAME": "Aspirin"},
                {"IMAGE": "missing.png", "MEDICINE_NAME": "Ibuprofen"},
                {"IMAGE": "blank.png", "MEDICINE_NAME": ""},
            ])
            labels.to_csv(dataset_dir / "Training" / "training_labels.csv", index=False)

            summary = prepare_training_data.prepare_dataset(
                dataset_dir,
                root / "output",
                "Training",
                prepare_training_data.SETS["Training"],
            )

            output_dir = root / "output" / "medical-ground-truth"
            self.assertEqual(summary["prepared"], 1)
            self.assertEqual(summary["missing_images"], 1)
            self.assertEqual(
                (output_dir / "training_word_001.gt.txt").read_text(encoding="utf-8"),
                "Aspirin",
            )
            self.assertTrue((output_dir / "training_word_001.png").is_file())

    def test_prepare_dataset_requires_expected_label_columns(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_dir = root / "dataset"
            images_dir = dataset_dir / "Training" / "training_words"
            images_dir.mkdir(parents=True)
            pd.DataFrame([{"IMAGE": "word_001.png"}]).to_csv(
                dataset_dir / "Training" / "training_labels.csv",
                index=False,
            )

            with self.assertRaisesRegex(ValueError, "MEDICINE_NAME"):
                prepare_training_data.prepare_dataset(
                    dataset_dir,
                    root / "output",
                    "Training",
                    prepare_training_data.SETS["Training"],
                )


if __name__ == "__main__":
    unittest.main()
