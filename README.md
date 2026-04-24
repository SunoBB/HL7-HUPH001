# HL7 FHIR Bulk Import With HAPI FHIR

This repository contains a simple local setup for loading a large Synthea-style FHIR dataset into HAPI FHIR using Docker and a Python bulk uploader.

The project has three main parts:

- `HL7_FHIR/`: Docker Compose stack for HAPI FHIR JPA Server + PostgreSQL
- `scripts/main.py`: Python uploader for bulk-importing JSON Bundle files into `http://localhost:8081/fhir`
- `scripts/translate_vi_med_to_en.py`: Python client for translating Vietnamese clinical text to medical English through a backend API

## Use Case

This setup is intended for:

- local FHIR sandbox environments
- importing large synthetic healthcare datasets
- testing HAPI FHIR with heavy `transaction` bundles
- preparing sample data for API, frontend, or analytics work

## Project Structure

```text
HL7/
├── HL7_FHIR/
│   ├── docker-compose.yml
│   ├── hapi.application.yaml
│   └── readme.md
├── scripts/
│   ├── main.py
│   ├── README.md
│   ├── translate_vi_med_to_en.py
│   └── translate_vi_med_to_en.md
├── Patient.fhir.json
├── synthea-transaction.json
└── README.md
```

## Requirements

- Docker
- Docker Compose
- Python 3.10+
- Python package: `requests`

Install the Python dependency if needed:

```bash
pip3 install requests
```

## HAPI FHIR Stack

The Docker stack runs:

- HAPI FHIR JPA Server
- PostgreSQL

Current local endpoint:

```text
http://localhost:8081/fhir
```

Main Docker files:

- [`docker-compose.yml`](/home/suno/Downloads/HL7/HL7_FHIR/docker-compose.yml)
- [`hapi.application.yaml`](/home/suno/Downloads/HL7/HL7_FHIR/hapi.application.yaml)

## Start The Stack

```bash
cd /home/suno/Downloads/HL7/HL7_FHIR
docker compose up -d
```

Check that HAPI is available:

```bash
curl -s http://localhost:8081/fhir/metadata
```

If you want a clean database before importing:

```bash
cd /home/suno/Downloads/HL7/HL7_FHIR
docker compose down -v
docker compose up -d --force-recreate
```

## Uploader Script

The uploader is implemented in:

- [`main.py`](/home/suno/Downloads/HL7/scripts/main.py)
- [`scripts/README.md`](/home/suno/Downloads/HL7/scripts/README.md)

It scans a folder of `.json` files, validates that each file is a FHIR `Bundle`, classifies heavy bundles, and uploads them to HAPI FHIR.

### What The Script Does

- scans all JSON files in `DATA_DIR`
- reads metadata first before uploading
- separates light bundles from heavy `transaction` bundles
- adjusts read timeout based on entry count
- retries transient request failures
- writes a timestamped upload log

### Default Target

By default the script posts to:

```text
http://localhost:8081/fhir
```

### Run The Import

From the project root:

```bash
cd /home/suno/Downloads/HL7
python3 scripts/main.py
```

For large imports, a conservative run is recommended:

```bash
cd /home/suno/Downloads/HL7
MAX_WORKERS=1 MAX_WORKERS_HEAVY=1 READ_TIMEOUT_MAX=7200 python3 scripts/main.py
```

## Environment Variables

The uploader can be tuned with environment variables:

- `FHIR_URL`: target FHIR base URL
- `MAX_WORKERS`: worker count for lighter files
- `MAX_WORKERS_HEAVY`: worker count for heavy transaction bundles
- `BIG_FILE_MB`: file size threshold for heavy classification
- `HEAVY_ENTRY_COUNT`: entry count threshold for heavy classification
- `SERVER_MAX_BUNDLE_SIZE`: optional client-side hard limit; `0` disables the check
- `MAX_RETRIES`: retry count per file
- `CONNECT_TIMEOUT`: HTTP connect timeout in seconds
- `READ_TIMEOUT_BASE`: base read timeout in seconds
- `READ_TIMEOUT_PER_ENTRY`: extra timeout per bundle entry
- `READ_TIMEOUT_MAX`: maximum read timeout in seconds

Example:

```bash
FHIR_URL=http://localhost:8081/fhir \
MAX_WORKERS=1 \
MAX_WORKERS_HEAVY=1 \
READ_TIMEOUT_MAX=7200 \
python3 scripts/main.py
```

## Translation Script

The repository also includes a small Python client for translating Vietnamese medical text to English through your backend.

File:

- [`translate_vi_med_to_en.py`](/home/suno/Downloads/HL7/scripts/translate_vi_med_to_en.py)
- [`translate_vi_med_to_en.md`](/home/suno/Downloads/HL7/scripts/translate_vi_med_to_en.md)

Quick run:

```bash
cd /home/suno/Downloads/HL7
python3 scripts/translate_vi_med_to_en.py --text "Bệnh nhân đau ngực, khó thở và sốt."
```

Configure backend URL:

```bash
TRANSLATE_BACKEND_URL=http://localhost:9000/api/translate \
python3 scripts/translate_vi_med_to_en.py --text "Bệnh nhân có tiền sử COPD."
```

## Notes About Large Bundles

This dataset contains many heavy FHIR `transaction` bundles. Some bundles can contain thousands of entries, so import time can be long.

Key points:

- heavy bundles are uploaded sequentially by default
- very large bundles can take many minutes each
- rerunning the same dataset against a non-empty database can cause `409` conflicts
- for a fresh import, reset PostgreSQL volume first

## Verified Result

A successful full import was recorded on March 27, 2026:

- total files: `564`
- success: `564`
- failed: `0`
- skipped: `0`
- total runtime: about `77 minutes`

Example success log:

- [`fhir_upload_20260327_190353.log`](/home/suno/Downloads/HL7/fhir_upload_20260327_190353.log)

## Useful Verification Commands

Count key resources after import:

```bash
curl -s "http://localhost:8081/fhir/Patient?_summary=count"
curl -s "http://localhost:8081/fhir/Encounter?_summary=count"
curl -s "http://localhost:8081/fhir/Observation?_summary=count"
```

Fetch sample patients:

```bash
curl -s "http://localhost:8081/fhir/Patient?_count=5"
```

## GitHub Notes

Before pushing to GitHub, consider:

- ignoring `__pycache__/`
- ignoring generated upload logs if they are not meant to be versioned
- avoiding hardcoded local paths if the repo will be reused on other machines

The current uploader uses this local dataset path by default:

```text
/home/suno/Downloads/_archives/Data_Sample
```

If you plan to share the repository, you may want to make `DATA_DIR` configurable through an environment variable.
