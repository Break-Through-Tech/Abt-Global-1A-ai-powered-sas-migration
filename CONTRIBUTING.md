# Contributing to SASGuard

This guide defines how the team creates branches, writes code, opens pull requests, reviews work,
and protects the supplied SAS reference artifacts.

## Core rules

1. Start work from a GitHub issue.
2. Do not commit directly to `main`.
3. Keep each branch and pull request focused on one issue or one closely related group of issues.
4. Require at least one approval from a teammate other than the author before merging.
5. Require all continuous-integration checks to pass before merging.
6. Never modify supplied SAS source, input data, or trusted outputs to make a comparison pass.
7. Add a regression test for every discovered SAS and Python semantic difference.

Documentation communicates the review requirement. A repository administrator should also enable
a GitHub ruleset or branch-protection rule that requires one approval and passing status checks.

## Before starting work

1. Confirm that the issue is assigned to you.
2. Read the issue objective, tasks, dependencies, and acceptance criteria.
3. Move the project-board item to `In progress`.
4. Leave a short comment stating what you are beginning.
5. Create a branch from the latest `main`.

```bash
git switch main
git pull --ff-only
git switch -c feat/issue-5-data-loaders
```

## Branch names

Use lowercase words separated by hyphens. Include the issue number.

```text
feat/issue-5-data-loaders
fix/issue-9-provider-alignment
docs/issue-13-contributor-guide
test/issue-10-regression-facts
chore/issue-12-ci-configuration
```

Use these prefixes:

| Prefix | Use |
|---|---|
| `feat/` | New behavior or capability |
| `fix/` | Defect correction |
| `docs/` | Documentation-only work |
| `test/` | Test-only work |
| `chore/` | Tooling, dependency, or repository maintenance |

## Commits

Write short, imperative commit subjects that describe the outcome.

```text
feat: preserve provider identifiers during CSV loading
test: cover missing domain weight redistribution
docs: explain project board workflow
```

Do not include unrelated formatting or generated files in a functional commit. Never commit API
keys, tokens, passwords, `.env` files, notebook checkpoints, or local output artifacts.

## Pull requests

Open a pull request when the issue's acceptance criteria are implemented and the local checks pass.
The description should include:

```markdown
## Summary
- What changed
- Why it changed

## Verification
- `docker compose run --rm sasguard ruff check .`
- `docker compose run --rm sasguard ruff format --check .`
- `docker compose run --rm sasguard mypy`
- `docker compose run --rm sasguard sasguard verify-integrity`
- `docker compose run --rm sasguard pytest`

## Data integrity
- Supplied SAS source and trusted artifacts were not modified.
- Any numerical tolerance is documented and tested.

Closes #5
```

Use `Closes #N` when merging the pull request should close the issue. Use `Refs #N` when the pull
request contributes to an issue but does not complete it.

After opening the pull request:

1. Move the board item to `In review`.
2. Request a review from at least one teammate who did not author the changes.
3. Respond to every review comment.
4. Resolve conversations only after the concern has been addressed or the reviewer agrees.
5. Re-run checks after significant revisions.

The author must not approve their own pull request. A pull request is ready to merge only when one
teammate has approved it, all required checks pass, and all review conversations are resolved.

## Closing an issue

An issue is ready to close when:

1. All acceptance criteria are satisfied.
2. The implementation or documentation has been reviewed.
3. Required CI checks pass.
4. Any related review conversations are resolved.
5. The project-board item is moved to `Done`.

Issues should not be closed solely because work has started or a pull request has been opened.

## Python names and casing

Follow these conventions:

| Construct | Convention | Example |
|---|---|---|
| Modules and files | `snake_case` | `artifact_loader.py` |
| Functions and variables | `snake_case` | `load_reference_data` |
| Classes | `PascalCase` | `ArtifactComparison` |
| Constants | `UPPER_SNAKE_CASE` | `PROVIDER_ID_COLUMN` |
| Private helpers | Leading underscore | `_canonicalize_name` |

SAS identifiers are case-insensitive. At ingestion and comparison boundaries, canonicalize SAS
identifiers to uppercase. Preserve authoritative external names such as `PROVIDER_ID` in schemas
and exported artifacts. Do not create several columns that differ only by letter case.

## Types and data semantics

- Add type hints to public functions, methods, and nontrivial helpers.
- Avoid `Any` unless the reason is documented.
- Use Pydantic models or dataclasses for structured results and configuration where appropriate.
- Preserve provider identifiers as strings. Never convert them to integers.
- Preserve leading zeros in identifiers.
- Preserve numeric missing values as `NaN`. Never silently convert missing values to zero.
- Align hospital-level artifacts by `PROVIDER_ID`, not row position.
- Make joins and merge cardinality explicit and test them.
- Treat SAS comments as documentation, not authority when they contradict executable behavior.

## Comments and docstrings

Comments should explain why code exists, especially when reproducing a non-obvious SAS behavior.
They should not restate a straightforward line of Python.

Good comment:

```python
# SAS PROC STANDARD uses the sample standard deviation for this pipeline.
standard_deviation = values.std(ddof=1)
```

Unhelpful comment:

```python
# Calculate the standard deviation.
standard_deviation = values.std(ddof=1)
```

Add docstrings to public modules, classes, and functions. A useful docstring explains inputs,
outputs, important missing-value behavior, and raised exceptions. Remove commented-out code rather
than keeping it in the repository. Git history already preserves previous implementations.

## Generated and manually written Code

Keep generated code separated from manually written application code: 

- Generated Python entry points belong in `generated/`.
- Manually written application code belongs in `src/sasguard/`.
- Manually written tests belong in `tests/`.

Generated code must not read or modify supplied SAS source, input datasets, or trusted output artifacts. Validation software may compare generated results with trusted outputs, but must not modify either source.

When adding or changing generated code:

1. Document how the code was generated.
2. Keep generated code separate from manually written application code.
3. Verify the generated results using the project's validation commands.
4. Do not modify trusted artifacts to make generated results pass validation.

## Validation and testing

Run all checks before requesting review:

```bash
docker compose run --rm sasguard ruff check .
docker compose run --rm sasguard ruff format --check .
docker compose run --rm sasguard mypy
docker compose run --rm sasguard sasguard verify-integrity
docker compose run --rm sasguard pytest
```

Tests must cover important boundary behavior, including:

- leading-zero provider identifiers;
- case-insensitive SAS names;
- missing values;
- keyed artifact alignment;
- eligibility thresholds;
- numerical tolerance boundaries;
- SAS-specific behavior discovered during implementation.

Use exact comparisons for identifiers, schemas, counts, indicators, peer groups, stars, and
missingness masks where appropriate. Numerical tolerances must be specific, justified, and covered
by tests. Never weaken validation simply to make an implementation pass.

## Protected project materials

The following materials are authoritative and must not be edited during translation or repair:

- supplied SAS programs and macros;
- supplied input datasets;
- supplied SAS output CSV files;
- supplied SAS binary output datasets;
- validation policies used to evaluate generated code.

Generated code must not read trusted output files. Validation code may read generated and trusted
outputs, but it must not modify either source.

The protected-file paths and SHA-256 digests are recorded in
`configs/protected-artifacts.json`. See [Protected artifact integrity](docs/data-integrity.md) for
the checker, trust boundary, and controlled update process. Do not regenerate the manifest during
ordinary translation, validation, or repair work.

## Definition of done

An issue is done only when:

- its acceptance criteria are satisfied;
- appropriate tests and documentation are included;
- local and CI checks pass;
- at least one teammate approves the pull request;
- review conversations are resolved;
- the pull request is merged;
- the issue is closed and the board item is in `Done`.
