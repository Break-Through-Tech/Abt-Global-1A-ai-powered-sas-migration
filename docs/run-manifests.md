# Reproducible Run Manifests

Every meaningful SASGuard execution should produce a versioned run manifest. The manifest records
how the run was created and evaluated without storing source contents, input records, golden
values, prompts, credentials, or other secrets.

The implementation lives in `src/sasguard/execution/manifest.py`.

## Recorded provenance

Each manifest records:

- schema version, run UUID, and timezone-aware UTC timestamp;
- SHA-256 hashes for SAS source, input files, and generated Python files;
- model name, temperature, and prompt version when translation is used;
- optional token usage and estimated cost;
- repair-attempt count and runtime;
- the reference source used for each compared artifact;
- structured `ArtifactComparison` results.

File paths are repository-relative and stored with forward slashes so manifests remain portable
between Windows, macOS, Linux, and Docker. Known text formats use LF-normalized SHA-256 hashes;
binary files are hashed byte for byte.

## Example

```json
{
  "artifact_results": {},
  "generated_code_hashes": {},
  "input_hashes": {
    "data/Project_1/Starrating/alldata_2025jul.csv": "<sha256>"
  },
  "reference_sources": {},
  "repair_attempts": 0,
  "run_id": "12345678-1234-5678-1234-567812345678",
  "runtime_seconds": 0.0,
  "schema_version": 1,
  "source_hashes": {
    "data/Project_1/SAS Programs/0 - Data and Measure Standardization_2025Jul.sas": "<sha256>"
  },
  "timestamp": "2026-09-09T12:00:00Z"
}
```

The placeholders above illustrate the schema. A real manifest must contain complete 64-character
SHA-256 values.

## Creating a manifest in Python

```python
from pathlib import Path

from sasguard.execution.manifest import RunManifest
from sasguard.provenance.hashing import hash_files

project_root = Path(".")

manifest = RunManifest.create(
    source_hashes=hash_files(
        project_root,
        ["data/Project_1/SAS Programs/0 - Data and Measure Standardization_2025Jul.sas"],
    ),
    input_hashes=hash_files(
        project_root,
        ["data/Project_1/Starrating/alldata_2025jul.csv"],
    ),
)

print(manifest.to_json())
```

`RunManifest.to_json()` sorts JSON object keys and normalizes hash mappings. Serializing the same
manifest object repeatedly therefore produces the same text.

## Storage and versioning

Local run records belong under `reports/runs/`, which is ignored by Git. Reports intended for a
pull request or final evaluation should be reviewed for sensitive information before they are
committed.

The current schema version is `1`. A breaking field or meaning change requires a new schema
version and migration notes. Existing run records must remain readable.
