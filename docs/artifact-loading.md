# Canonical Artifact Loading

SASGuard uses one loader contract for generated CSV files, supplied CSV files, and SAS7BDAT
artifacts. Loading does not compare values and never writes to the source file.

## Guarantees

- `.csv` and `.sas7bdat` files are supported.
- The configured comparison key resolves case-insensitively.
- The original spelling of every column remains unchanged.
- Comparison keys use pandas' nullable string type.
- Leading zeros in CSV identifiers remain significant.
- A missing identifier remains missing instead of becoming the text `"nan"` or `"<NA>"`.
- Numeric missing values remain missing and are never replaced with zero.
- Missing and ambiguous key columns produce explicit errors.
- Unsupported formats and missing files produce explicit errors.

The loader does not assert that keys are non-missing or unique. Those are comparison-time
requirements because diagnostics must distinguish a loading failure from an invalid comparison
key.

## Configured input

```python
from pathlib import Path

from sasguard.config import load_project_configuration
from sasguard.data import load_artifact

project_root = Path.cwd()
configuration = load_project_configuration(
    project_root / "configs" / "cms_2025jul.yaml",
    project_root=project_root,
)
paths = configuration.resolve_paths(project_root)

input_artifact = load_artifact(
    paths.input_sas7bdat,
    key=configuration.project.key,
)
```

## Trusted reference artifact

The validator, not the translator or generated-code runner, may load a trusted reference:

```python
mortality_reference = load_artifact(
    paths.reference_sas7bdat["OUTCOME_MORTALITY"],
    key=configuration.project.key,
)
```

The isolated generated-code runner does not mount the reference directories, so generated code
cannot call this loader on trusted outputs during execution.
