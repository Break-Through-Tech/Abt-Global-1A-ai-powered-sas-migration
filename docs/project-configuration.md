# Project Configuration

SASGuard keeps case-study paths and bounded policy values in a versioned YAML configuration rather
than scattering them through loaders, validators, runners, and translated code.

The CMS July 2025 configuration is `configs/cms_2025jul.yaml`. It records:

- the logical project name and `PROVIDER_ID` comparison key;
- the three SAS programs in execution order;
- the supporting macro file;
- equivalent CSV and SAS7BDAT inputs;
- trusted CSV and SAS7BDAT reference directories;
- one logical entry for each of the 10 supplied golden artifacts;
- SAS7BDAT as the preferred numeric reference source;
- the future repair loop's maximum attempt count.

It contains paths and policy metadata only. It must not contain credentials, prompts, provider
records, expected row-level values, or copied golden-output data.

## Loading the configuration

Use the strict loader from the repository root:

```python
from pathlib import Path

from sasguard.config import load_project_configuration

project_root = Path(".")
configuration = load_project_configuration(
    project_root / "configs" / "cms_2025jul.yaml",
    project_root=project_root,
)
paths = configuration.resolve_paths(project_root)
```

The returned `ProjectConfiguration` contains normalized, repository-relative values. The resolved
paths object provides absolute paths for consumers:

```python
for program_path in paths.programs:
    print(program_path)

star_csv = paths.reference_csv["STAR_2025JUL"]
star_sas = paths.reference_sas7bdat["STAR_2025JUL"]
```

Program order is significant. Consumers must iterate over `paths.programs` without sorting it.
Artifact names are canonicalized to uppercase because SAS identifiers are case-insensitive.

## Validation rules

The loader:

- rejects undocumented YAML fields;
- rejects absolute paths and parent-directory traversal;
- normalizes Windows separators to portable forward slashes;
- validates required filename extensions;
- rejects duplicate programs, macros, artifacts, and reference filenames ignoring case;
- resolves every path beneath the explicit repository root;
- reports all missing configured directories and files together.

Path existence is checked by default. Planning and schema-only tools may pass
`require_existing=False`, but execution and validation code must keep the default.

## Updating the configuration

Configuration changes affect every downstream result and require normal pull-request review.
When adding another case study or quarter, create a separate YAML file instead of overwriting the
July 2025 definition. Do not add quarter-specific constants to Python modules when they belong in
configuration.
