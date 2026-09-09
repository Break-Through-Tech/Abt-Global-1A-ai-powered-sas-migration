## Summary

- Describe what changed.
- Explain why the change is needed.

## Linked issue

Closes #

## Verification

- [ ] `docker compose run --rm sasguard ruff check .`
- [ ] `docker compose run --rm sasguard ruff format --check .`
- [ ] `docker compose run --rm sasguard mypy`
- [ ] `docker compose run --rm sasguard pytest`
- [ ] New or changed behavior has appropriate tests.

## Data integrity

- [ ] Supplied SAS programs, input data, and trusted outputs were not modified.
- [ ] Provider identifiers remain strings and preserve leading zeros.
- [ ] Missing values are preserved where applicable.
- [ ] Numerical tolerances are documented and tested where applicable.

## Review readiness

- [ ] The pull request is focused on the linked issue.
- [ ] Documentation is updated where needed.
- [ ] At least one teammate other than the author has been requested as a reviewer.
