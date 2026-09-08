# Linux Training Handoff

This repository intentionally excludes the handwriting dataset, generated
`.lstmf` files, `tesstrain/`, virtual environments, and model artifacts. Copy
or mount those resources separately on the Linux machine; do not add them to
Git.

## 1. Verify The Linux Environment

From the repository root, create the Python environment and install the
application dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Verify the existing OCR and training executables before changing anything:

```bash
command -v tesseract lstmtraining combine_tessdata
tesseract --version
lstmtraining --version
```

The known training environment used Tesseract and `lstmtraining` 4.1.1. Record
the output above so any version mismatch is visible before investigating the
segmentation fault.

## 2. Restore And Validate Data

Set the dataset path to the root that contains `Training`, `Validation`, and
`Testing` directories:

```bash
export DATASET_DIR="/path/to/Doctor's Handwritten Prescription BD dataset"
find "$DATASET_DIR" -maxdepth 3 -type f | head -n 30
```

Prepare the ground-truth directories with the checked-in script:

```bash
python prepare_training_data.py \
  --dataset-dir "$DATASET_DIR" \
  --output-root "$PWD/tesstrain/data"
```

This creates the following directories when the dataset layout is valid:

- `tesstrain/data/medical-ground-truth`
- `tesstrain/data/medical-validation`
- `tesstrain/data/medical-test`

The script stops early if a label CSV, image directory, or either required CSV
column (`IMAGE`, `MEDICINE_NAME`) is missing. Capture its output before
generating `.lstmf` files.

## 3. Restore Application Services

Set database configuration through the shell or an untracked `.env` file:

```bash
export DB_NAME="prescriptrx"
export DB_USER="your_postgres_user"
export DB_PASSWORD="your_postgres_password"
export DB_HOST="localhost"
export DB_PORT="5432"
```

Initialize the schema with a PostgreSQL user that can create tables:

```bash
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f schema.sql
```

If the database does not yet contain the local cleaned NDC catalogue, import
the four CSV fields without committing any database credentials:

```bash
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "\\copy drugs(drug_name, generic_name, dosage_form, ndc_code) FROM 'datasets/ndc/drugs_clean.csv' WITH (FORMAT csv, HEADER true)"
```

Confirm that the catalogue is present before starting Flask:

```bash
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT COUNT(*) FROM drugs;"
python -c "import app; print('Flask import: OK')"
```

## 4. Investigate The Existing LSTM Crash

Do not replace the training command yet. The prior failure continued from
`data/eng/medical.lstm`, loaded `.lstmf` files, then terminated with exit code
139. First capture the exact invocation and state that produced it.

```bash
mkdir -p logs
ls -lh data/eng/medical.lstm
find tesstrain -name '*.lstmf' -type f | wc -l
find tesstrain -maxdepth 3 -type f \( -name '*.traineddata' -o -name '*.lstm' \) -ls
```

Enable core dumps before rerunning the exact previous command. Redirect both
output streams to a timestamped log and record its exit status:

```bash
ulimit -c unlimited
date -Is | tee "logs/training-started.txt"
# Run the exact previously used lstmtraining command here.
```

After a crash, collect the following diagnostic evidence before modifying
models, `.lstmf` files, or command arguments:

```bash
find . -maxdepth 3 -type f -name 'core*' -ls
dmesg --ctime | tail -n 100
```

`dmesg` may require elevated permissions on some Linux distributions. Preserve
the exact command, full output, executable versions, count of `.lstmf` files,
and any core-dump metadata. Those facts are needed to determine whether the
fault comes from a corrupted base model, incompatible training files, or a
Tesseract 4.1.1 training-tool issue.

## 5. Keep Git Clean

Before pushing source changes from Windows or Linux, verify that large data and
training artifacts are still ignored:

```bash
git status --short
git check-ignore -v tesstrain datasets/handwriting venv
```

Commit source, tests, documentation, and dependency declarations only. Do not
commit `.env`, database passwords, datasets, `.lstmf` files, trained models,
or core dumps.
