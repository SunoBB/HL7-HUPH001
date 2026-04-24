# `scripts/main.py` Explained

This document explains how [`main.py`](/home/suno/Downloads/HL7/scripts/main.py) works and what each part of the uploader is responsible for.

## Purpose

The script bulk-imports FHIR `Bundle` JSON files from a local folder into a HAPI FHIR server.

Default behavior:

- read all `.json` files from a dataset folder
- keep only files whose top-level `resourceType` is `Bundle`
- classify large `transaction` bundles as "heavy"
- upload light bundles first, then heavy bundles
- retry transient failures
- write a timestamped log file

## High-Level Flow

The runtime flow is:

1. Read configuration from constants and environment variables.
2. Scan the dataset directory for `.json` files.
3. Load each file just enough to extract bundle metadata.
4. Skip invalid JSON or non-`Bundle` resources.
5. Split valid bundles into `light` and `heavy`.
6. Upload `light` bundles with `MAX_WORKERS`.
7. Upload `heavy` bundles with `MAX_WORKERS_HEAVY`.
8. Print a final summary and save the log filename.

## Configuration Block

At the top of the file, the script defines runtime settings:

- `DATA_DIR`: where the input JSON files live
- `FHIR_URL`: target FHIR endpoint, default `http://localhost:8081/fhir`
- `MAX_WORKERS`: concurrency for lighter files
- `MAX_WORKERS_HEAVY`: concurrency for heavier `transaction` bundles
- `BIG_FILE_MB`: file-size threshold used in heavy classification
- `HEAVY_ENTRY_COUNT`: entry-count threshold used in heavy classification
- `SERVER_MAX_BUNDLE_SIZE`: optional client-side guard against very large bundles
- `MAX_RETRIES`: upload retry attempts per file
- `CONNECT_TIMEOUT`: HTTP connect timeout
- `READ_TIMEOUT_BASE`: minimum read timeout
- `READ_TIMEOUT_PER_ENTRY`: extra read timeout added per bundle entry
- `READ_TIMEOUT_MAX`: cap on calculated read timeout
- `LOG_FILE`: timestamped output log file

This design makes the script easy to tune without editing the code every time.

## Data Structures

The script uses two dataclasses.

### `Summary`

`Summary` stores the final upload result lists:

- `ok`: successfully uploaded files
- `failed`: failed uploads
- `skipped`: ignored files

The global `summary` object is updated as work completes.

### `BundleInfo`

`BundleInfo` is metadata for a single file:

- `file_path`: absolute path to the JSON file
- `filename`: basename used in logs
- `size_mb`: file size in MB
- `bundle_type`: FHIR bundle type such as `transaction`
- `entry_count`: number of `entry` elements
- `is_heavy`: whether the script should treat the file as heavy

The uploader computes this once before upload so later steps do not need to recalculate it.

## Core Functions

### `load_bundle_info(file_path)`

This function validates and classifies one file.

What it does:

- opens the JSON file
- rejects invalid JSON
- rejects resources whose `resourceType` is not `Bundle`
- calculates file size
- reads bundle `type`
- counts `entry`
- marks the bundle as heavy when:
  - `bundle_type == 'transaction'`
  - and file size is at least `BIG_FILE_MB`
  - or entry count is at least `HEAVY_ENTRY_COUNT`

Return value:

- a `BundleInfo` object for valid bundles
- `None` for invalid or skipped files

This is the scan phase. It does not upload anything yet.

### `build_session(pool_size)`

This creates one reusable `requests.Session` with a matching connection pool.

Why it exists:

- reduces connection setup overhead
- lets worker threads reuse HTTP connections
- keeps transport settings in one place

### `compute_read_timeout(info)`

This computes a read timeout based on bundle size in entries.

Formula:

```text
READ_TIMEOUT_BASE + (entry_count * READ_TIMEOUT_PER_ENTRY)
```

The result is then clamped between:

- minimum: `READ_TIMEOUT_BASE`
- maximum: `READ_TIMEOUT_MAX`

This is important because large transaction bundles can take much longer to process on the server.

### `upload_bundle(session, info)`

This is the main upload function for one bundle.

What it does:

1. Builds a timeout tuple `(connect_timeout, read_timeout)`.
2. Logs extra detail for heavy bundles.
3. Optionally skips bundles larger than `SERVER_MAX_BUNDLE_SIZE`.
4. Retries up to `MAX_RETRIES`.
5. Reads the JSON body from disk.
6. Sends `POST` to `FHIR_URL`.
7. Interprets the result:
   - `200` or `201`: success
   - `4xx`: permanent failure, no retry
   - other responses: retry
8. Handles request exceptions:
   - connection errors
   - connection reset / aborted
   - timeout
   - other request exceptions
9. Uses exponential backoff before retrying.

Return values:

- `'ok'`
- `'failed'`

This return value is used by the thread-pool caller to update `summary`.

## Main Workflow

### `main()`

`main()` orchestrates the whole job.

It performs these steps:

### 1. List input files

It reads all `.json` files under `DATA_DIR`.

If none are found, it logs a warning and exits.

### 2. Scan metadata

It loops over every JSON file and calls `load_bundle_info()`.

During this stage it:

- fills `bundle_infos` with valid bundles
- records skipped files in `summary.skipped`
- logs scan progress every 10 files

### 3. Split work by type

It partitions valid files into:

- `light_files`: everything not marked heavy
- `heavy_files`: large `transaction` bundles
- `oversized_files`: files over `SERVER_MAX_BUNDLE_SIZE`

`oversized_files` is only for reporting; actual skipping still happens in `upload_bundle()`.

### 4. Upload in two phases

The nested helper `process_batch(infos, workers)`:

- creates one shared HTTP session
- starts a `ThreadPoolExecutor`
- submits one future per bundle
- waits for completion with `as_completed`
- appends the filename into `summary.ok` or `summary.failed`
- logs progress every 10 completed uploads

The script runs:

- light files first with `MAX_WORKERS`
- heavy files second with `MAX_WORKERS_HEAVY`

This ordering reduces the chance that many expensive transaction bundles overload the server at once.

### 5. Print summary

At the end, the script logs:

- total runtime
- success count
- failure count
- skipped count
- failed filenames
- generated log filename

## Why Heavy Bundles Are Special

The script treats a bundle as heavy only when it is a `transaction` bundle and it crosses either the file-size or entry-count threshold.

That matters because transaction bundles often:

- create many resources in one request
- trigger more database work
- take longer server-side
- are more likely to hit timeouts or connection resets

So the script gives them:

- separate scheduling
- lower concurrency
- clearer logging
- longer dynamic read timeouts

## Logging Behavior

The script logs to both:

- terminal output
- a timestamped file like `fhir_upload_20260402_134500.log`

Typical log events include:

- invalid JSON
- skipped non-Bundle files
- heavy bundle notices
- retries
- timeouts
- 4xx failures
- final totals

This is useful for long-running imports where you need to review failures after the run finishes.

## Important Limitations

Some current constraints in the code are worth knowing:

- `DATA_DIR` is hardcoded, not environment-driven
- the same JSON file is opened once during scan and again during upload
- `summary` is global state
- `oversized_files` is counted in `main()` but enforced later in `upload_bundle()`
- retries are generic and do not distinguish all HTTP server failure modes

None of these are necessarily wrong for a local import script, but they are useful to understand before extending it.

## Safe Extension Points

If you want to improve the script later, the safest places are:

- make `DATA_DIR` configurable with an env var
- add CLI arguments
- write a CSV or JSON summary output
- support resume mode for failed files only
- add per-resource statistics from server responses
- split scanning and upload into separate modules

## Run Example

```bash
cd /home/suno/Downloads/HL7
MAX_WORKERS=1 MAX_WORKERS_HEAVY=1 READ_TIMEOUT_MAX=7200 python3 scripts/main.py
```
