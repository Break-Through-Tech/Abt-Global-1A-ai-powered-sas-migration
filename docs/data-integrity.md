# Protected Artifact Integrity

SASGuard treats the supplied SAS programs, input datasets, logs, documentation, and SAS output
artifacts as authoritative project materials. These files must not be changed to make a Python
implementation pass validation.

## Protected scope

The protected root is:

```text
data/Project_1
```

The version-controlled manifest at `configs/protected-artifacts.json` records every file expected
under that root and its SHA-256 digest. Known text formats are normalized to LF while hashing so
the same content produces the same digest on Windows, macOS, Linux, and GitHub Actions. Binary
files are hashed byte for byte. The manifest currently covers the supplied SAS programs, CSV and
SAS input files, CSV and SAS output files, execution log, HTML output, and source PDF.

Any unlisted file added under the protected root is also reported. Exploratory outputs and
generated Python results belong outside `data/Project_1`.

## Run the check

Run the check before opening a pull request and whenever work reads supplied data:

```bash
docker compose run --rm sasguard sasguard verify-integrity
```

A successful check reports the number of protected files verified and exits with status `0`.
The command exits with status `1` when a file is missing, modified, or unexpected. It exits with
status `2` when the manifest cannot be loaded or the check cannot run.

Diagnostics contain paths only. They do not print raw golden-output values.

## Trust boundary

Access to a file and permission to use it are separate concerns:

| Component | SAS source | Input data | Golden output | May modify protected files |
|---|---:|---:|---:|---:|
| Translation code | Yes | Yes | No | No |
| Generated Python | As needed | Yes | No | No |
| Deterministic validator | No | No | Yes | No |
| Integrity checker | No | No | Hashes only | No |
| Repair worker | Relevant source span | Diagnostic only | No | No |

The repository mount keeps `data/` read-only inside the Docker development environment. The
integrity manifest provides an additional deterministic check for changes made outside Docker.

## Updating supplied materials

Do not regenerate the manifest to make an unexpected integrity failure disappear. If Abt Global
officially supplies a corrected or additional artifact:

1. Create a dedicated issue describing the source and reason for the change.
2. Have a teammate verify the new files independently.
3. Update the protected files and manifest in one focused pull request.
4. Include the old and new hashes in the review evidence.
5. Require approval from someone other than the author.

Ordinary translation, validation, and repair pull requests must not update the integrity manifest.
