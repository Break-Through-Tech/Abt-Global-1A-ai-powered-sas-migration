# Issue close-out checklist

Prepared against branch `integration/issue-71-full-pipeline` (draft PR #77). For each open
issue: its acceptance criteria in short, what PR #77 provides, what still needs a person, a
paid run, licensed SAS or Abt, and a recommended action.

How to read the evidence column: file paths and commands were checked to exist on the branch
by reading the source and docs. Test counts and pass results copied from the PR #77
description and the repository docs are marked "unverified" unless a re-run is named. On
2026-11-26 one person re-ran, on one Windows 11 machine at commit `e3ce14c` (see the
[dry run in the demo runbook](demo-runbook.md#dry-run-on-2026-11-26-windows-11-commit-e3ce14c)):
`docker compose run --rm sasguard pytest -q` (812 passed, 29 Docker-gated tests skipped),
`sasguard verify-integrity` (29 files, host and Docker), the validation commands below, the
wrong-candidate tests (3 passed) and the repair replay with Docker (1 passed). That is not an
independent second-machine replay, so nothing below is closed on its strength alone. The team
should still run the Docker-gated suite (`SASGUARD_RUN_DOCKER_TESTS=1`) and CI before closing
anything.

Two pieces of work are now on this branch and were verified in that run:

* A Program 2 reference implementation, `reference_python/program2.py`. It was not written
  by a team member and is pending teammate review, so `validate-pipeline` records its stage as
  `helper_assisted_model_output` with the note "Program 2 reference implementation pending
  teammate review". Command: `sasguard validate-pipeline --run-human-references
  --run-reference-program2`. Result: PASS, 10 of 10 artifacts (Program 0 3/3, Program 1 5/5,
  Program 2 2/2), both handoffs exact, 0 STAR mismatches, 29/29 protected files before and
  after (7 s on the host). This is not a human Program 2 or approved CMS ratings, and it is
  one July 2025 result against the supplied SAS artifacts.
* Pipeline reports: `sasguard report-run <validate-pipeline run dir>` writes `handoff.md`
  (CMS summary), `technical.md` (Abt record) and `report.json`. The PASS run rendered
  `VERIFIED`; a deliberately wrong run (one Program 0 value changed) rendered `NOT VERIFIED`
  with the earliest divergence. Abt has not confirmed the field list. The short CMS
  `handoff.md` shows the Program 2 origin but not the "pending teammate review" note, which
  only `technical.md` and `report.json` carry.

Recommended actions use three labels: **close after PR 77 merges**, **keep open**,
**close as superseded**. "Close" always means after a teammate has checked the evidence.

## Summary table

| Issue | Recommended action |
|---|---|
| #13 Contributor guide | Keep open until a clean-checkout walkthrough is recorded |
| #43 Program 0 in Python | Close after PR 77 merges |
| #44 Program 0 validator | Close after PR 77 merges |
| #45 Wrong Program 0 behavior | Close after PR 77 merges |
| #46 Model and budget decision | Keep open (needs the team) |
| #47 Isolated execution | Close after PR 77 merges |
| #48 Direct baseline | Keep open (blocked on #46) |
| #49 October demo | Keep open |
| #52 Abt report | Keep open |
| #67 Integration | Close after PR 77 merges, once #46 record is linked |
| #68 Program 1 with a model | Keep open |
| #69 FASTCLUS helpers | Keep open |
| #70 Program 2 repair | Keep open |
| #71 Ten-artifact validation | Keep open until independent replay |
| #72 November demo | Keep open |

## Per-issue detail

### #13 Contributor setup and workflow guide (haileybella)

- Acceptance: a teammate can clone, build, test and open a notebook from the guide; rules
  forbid editing golden outputs; PRs must cite an issue with verification evidence; guide says
  where generated and manual code go.
- PR 77 provides: `CONTRIBUTING.md` exists with sections for branches, commits, pull requests,
  data integrity, protected project materials and definition of done; `docs/development-setup.md`
  covers Docker and local Python; `.github/pull_request_template.md` exists. PR 77 itself
  changes README.md and adds many docs but is not the source of the contributor guide (the
  guide appears to predate it; not confirmed which PR added it).
- Still needs: a person following the guide from a clean clone through build, tests and
  notebook; confirmation that the generated-versus-manual code location is stated (the
  `generated/` directory is empty on this branch; I did not confirm the guide mentions it).
- Action: keep open until a second person records a clean-checkout run (this overlaps #72).

### #43 Reproduce Program 0 standardization in Python (theocsav)

- Acceptance: deterministic Python for Program 0 compared with the three supplied SAS
  outputs; Docker tests on synthetic edge cases and all three outputs; integrity, lint, mypy
  and CI pass; docs state parity scope and tolerance.
- PR 77 provides: `src/sasguard/program0.py`; tests `tests/test_program0.py`,
  `tests/integration/test_program0_reference.py`; docs `docs/program-0-python.md`. The PR
  description states Program 0 passed 3 of 3 artifacts with human references; the 2026-11-26
  dry run reproduced 3/3 in the pipeline command. Command: `sasguard validate-pipeline
  --run-human-references --run-reference-program2`.
- Still needs: a human re-run of the tests and CI on the merged branch.
- Action: close after PR 77 merges (PR 53, the original #43 PR, is also still open and
  should be closed as superseded).

### #44 Verify all three Program 0 outputs with the shared pipeline (TonyMapeke)

- Acceptance: one documented command checks all three artifacts with per-shape policies;
  structured outcomes for missing, malformed, schema, missingness and numeric differences;
  human reference passes; a deliberate semantic error fails usefully; trusted outputs stay
  outside candidate execution.
- PR 77 provides: `src/sasguard/verification/program0.py`,
  `configs/program0-comparison-policies.json`, tests
  `tests/test_program0_validation_adapter.py` and
  `tests/integration/test_program0_validation.py`, doc `docs/program-0-validation.md`.
- Still needs: re-run of the tests; a teammate's review.
- Action: close after PR 77 merges.

### #45 Catch executable but wrong Program 0 behavior (Loaardi)

- Acceptance: at least three wrong candidates run and are rejected; results name the artifact
  and mismatch kind; supplied files never modified; command and outcome documented.
- PR 77 provides: `tests/integration/test_program0_wrong_candidates.py` (3 tests: direction
  reversal skipped, missing values to zero, leading-zero IDs lost) and
  `docs/program0-wrong-candidates.md` with the Docker command. The 2026-11-26 dry run got
  "3 passed" on the host (they are not Docker-gated) and the same tests passed inside the
  Docker `pytest -q` run. Population versus sample standard deviation is covered by
  the Mortality test from PR 40. Pipeline-level wrong-value cases are in
  `tests/verification/test_pipeline.py`.
- Still needs: a Docker run of the three tests by someone other than the author.
- Action: close after PR 77 merges.

### #46 Agree on October model, payload rules and budget (no assignee)

- Acceptance: provider and exact model ID with checked pricing, caps, attempts and payer,
  credential holder, approved payload, baseline isolation, run-record fields, all recorded
  and approved. No paid call is authorized until then.
- PR 77 provides: a draft record at `docs/model-budget-decision.md` listing the code's
  current model ID, limits, payload and record fields. The prompt preview and checker
  (`preview-program0-prompt`, `check-program0-prompt`) exist. Nothing is approved.
- Still needs: team decision, pricing check, budget and payer, sign-offs.
- Action: keep open. It cannot be closed by a merge.

### #47 Run generated Program 0 code with an isolated output contract (theocsav)

- Acceptance: a candidate is staged and its three outputs collected; missing or escaped
  output fails clearly; a test shows the candidate cannot read the trusted reference
  directory; Docker integration tests pass.
- PR 77 provides: `src/sasguard/execution/program0.py` (`run-program0-candidate`), docs
  `docs/program-0-candidate-execution.md` (states only `source/`, `input/`, `output/` are
  mounted), tests `tests/test_program0_execution.py`,
  `tests/integration/test_program0_candidate_docker.py`. The PR description reports 29 Docker
  integration tests passed (unverified here).
- Still needs: Docker test run by a second person.
- Action: close after PR 77 merges.

### #48 Record a direct model baseline for Program 0 (Loaardi)

- Acceptance: one reproducible Attempt 0 with prompt and model metadata, code hash, execution
  report, validation of all three artifacts, plain account of results. Blocked on #46.
- PR 77 provides: the controller `model-program0`
  (`src/sasguard/prototypes/program0_model.py`), `docs/program-0-model-workflow.md`, tests
  `tests/test_program0_model.py`, `tests/integration/test_program0_model_workflow.py`, and
  recorded experiments under `docs/experiments/2026-11-10-*`. Those experiments used bounded
  automatic repair, so they are not the direct Attempt 0 baseline alone. Whether a saved
  direct-only result exists is unverified; run directories are ignored by Git.
- Still needs: #46 approval, then a paid run (or a documented local alternative), with
  Attempt 0 kept separate from repairs.
- Action: keep open.

### #49 Rehearse the October Program 0 walkthrough (haileybella)

- Acceptance: documented commands and expected outputs; another teammate runs it from a clean
  checkout; records what passed, failed and is unverified; no new API spending required.
- PR 77 provides the ingredients (human reference run, wrong-candidate tests, `report-run`,
  replay of recorded experiments) and now `docs/demo-runbook.md`, which was dry-run
  end to end on the author's Windows machine. The runbook covers the November pipeline; its
  Program 0 pieces (human reference, wrong result, recorded repair, report) cover #49's
  walkthrough.
- Still needs: a written walkthrough, a clean-checkout run by a teammate, and the model
  segment (depends on #48 or a statement that it is blocked).
- Action: keep open.

### #52 Generate Abt validation report and CMS handoff summary (theocsav, haileybella)

- Acceptance: readable report plus machine-readable results; Abt technical section and short
  CMS summary; VERIFIED / FAILED / NOT VERIFIED labels; failure and partial reports; no
  secrets; separate claims for generated, executed, compared, reviewed. Fields to be
  confirmed with Abt.
- PR 77 provides: `src/sasguard/reporting/` (`report-run`, Program 0, Program 0 model, and
  July 2025 replay reports), `docs/scoped-run-reports.md`, tests `tests/test_reporting.py`,
  `tests/test_program0_reporting.py`, `tests/test_july_2025_reporting.py`, and the pipeline
  `report-run` extension (verified 2026-11-26: VERIFIED for a PASS run, NOT VERIFIED with the
  earliest divergence for a wrong run, `handoff.md`, `technical.md` and `report.json`
  written, no credentials found by a text search of the output).
- Still needs: Abt confirmation of fields and delivery format; independent replay (#71);
  human review of a real report for leaked data.
- Action: keep open.

### #67 Review and merge the verified Program 0 baseline (theocsav, AmiriHayes)

- Acceptance: PRs reviewed and merged in dependency order with CI; three Program 0
  comparisons reproduced in Docker on the integrated branch; model, reasoning, payload
  boundary, usage and budget recorded in #46; baseline commits recorded.
- PR 77 provides: one integrated branch from main containing the listed stacked PRs (per its
  description), which replaces merging them one by one.
- Still needs: teammate review and green CI on PR 77; the #46 record; a note of the integrated
  baseline commit.
- Action: close after PR 77 merges and the #46 record is linked. If #46 stays open, keep this
  open or note the exception.

### #68 Generate and verify Program 1 with Luna (AmiriHayes, keiraw777)

- Acceptance: model-generated Program 1 from SAS source and macro only; all five domain
  outputs pass against SAS; reproducible command; recorded prompt, settings, usage and
  candidates.
- PR 77 provides: a human-reference Program 1 (`reference_python/domain_scoring.py`), a
  Program 1 validator (`src/sasguard/verification/program1.py`), the chain runner
  (`run-program01-chain`). I found no Program 1 model-generation controller on the branch
  (no `model-program1` command), unverified that none exists elsewhere.
- Still needs: a controller, #46 approval, a paid or local model run.
- Action: keep open.

### #69 Implement and test FASTCLUS compatibility helpers (haileybella, keiraw777)

- Acceptance: synthetic probes for percentile definition 5, seed order, STRICT, outliers and
  signed identifiers; consistent cluster numbering; limits recorded where SAS evidence is
  missing; reusable tested helper; no hardcoded hospitals.
- PR 77 provides: `src/sasguard/semantics/fastclus.py`, `fastclus_iteration.py`, tests
  `tests/test_fastclus_semantics.py` and `tests/test_fastclus_iteration.py`, a SAS probe
  script `tests/sas/fastclus_synthetic_probes.sas`, docs `docs/fastclus-synthetic-probes.md`,
  `docs/fastclus-iteration.md`, `docs/program-2-sas-semantics.md`.
- Still needs: a run of the probe script in licensed SAS (the issue says it has not been run);
  unresolved behaviors named in the issue (seed replacement, equidistant assignment, tied
  final centers) need evidence.
- Action: keep open.

### #70 Repair and integrate the Program 2 model workflow (theocsav, keiraw777)

- Acceptance: reviewable runner and policies without secrets; new helper-assisted experiment
  with fixed model and repair limit; both Program 2 artifacts pass with exact categorical
  matches; actual upstream Python artifacts fed to Program 2.
- PR 77 provides: `model-program2` (`src/sasguard/prototypes/program2_model.py`),
  `src/sasguard/verification/program2.py`, `configs/program2-comparison-policies.json`,
  `docs/program-2-model-workflow.md`, recorded experiments
  (`docs/experiments/2026-11-10-program2-luna-baseline.md`: best candidate had two STAR
  mismatches, FAILED; `2026-11-16-program2-strict-replay.md`: a manual-correction replay
  reported as passing all ten comparisons, which depends on a candidate package held on
  restricted Drive and is unverified here). The Program 2 reference implementation passes
  2/2 Program 2 artifacts with 0 STAR mismatches in the chain (dry run 2026-11-26), but it
  is not a model-translation result and does not close this issue.
- Still needs: #46 approval and a paid or local prospective helper-assisted run; helper
  integration into the generation prompt; #69 resolved questions.
- Action: keep open.

### #71 Verify all ten artifacts across the complete pipeline (Loaardi, TonyMapeke)

- Acceptance: chain Programs 0, 1, 2 with stage origins recorded; all ten artifacts checked
  at the fixed 1e-12 tolerances; 29 protected files verified; wrong, missing and malformed
  cases rejected with earliest divergence; independent teammate replay.
- PR 77 provides: `sasguard validate-pipeline`, `src/sasguard/verification/pipeline.py`,
  `program1.py`, tests `tests/verification/test_pipeline.py` (37 passed on the host in the
  2026-11-26 dry run) and `test_program1.py`, doc `docs/full-pipeline-validation.md`.
  Verified result (`--run-human-references --run-reference-program2`): PASS, 10 of 10, 0 STAR
  mismatches, 29/29 integrity before and after, Program 2 labeled
  `helper_assisted_model_output` (reference implementation pending teammate review). The
  human references with no Program 2 output give PARTIAL 8 of 10 (earliest divergence
  Program 2 `STAR_2025JUL`, missing output); that needs an empty `--program2-output`
  directory because `--run-human-references` alone exits 2. A wrong Program 0 value is caught
  at Program 0 with Programs 1 and 2 marked `upstream_failure`.
- Still needs: teammate review of `reference_python/program2.py` (until then no
  `human_reference` label); Tony's independent replay recorded in the issue (OS, commit,
  image ID, pass counts, STAR mismatches, integrity result; use a host run so the commit and
  OS are recorded, a Docker run records commit `unknown`); model-candidate chains for #68 and
  #70.
- Action: keep open until the independent replay is recorded and the Program 2 review is done.

### #72 Reproduce and rehearse the November pipeline demo (Loaardi, haileybella)

- Acceptance: documented Docker workflow run on a second computer from a clean checkout;
  PowerShell and zsh instructions; full rehearsal including a wrong result and a bounded
  repair record; statuses explained separately; reports checked for secrets; team rehearsal.
- PR 77 provides `docs/demo-runbook.md` (PowerShell and zsh setup, ordered script, wrong
  result, repair record replay, `report-run`, status vocabulary, limits, troubleshooting, a
  record table) and a dry run of its commands on one Windows 11 machine on 2026-11-26. macOS
  zsh and a clean clone were not run. The rehearsals themselves are human tasks.
- Still needs: the second-computer clean-checkout run with the record table filled in,
  the team rehearsal, a person reading the generated reports for sensitive content,
  and the dependencies #67, #71, #52.
- Action: keep open; the second-computer run is the next step.

## Open PRs superseded by PR 77 once it merges

PR 77's description states these were merged into the integration branch with history
preserved. After PR 77 merges, close them as superseded (do not close before):

| PR | Branch | Title |
|---|---|---|
| 55 | `feat/issue-47-program0-execution` | execute Program 0 candidates with an isolated output contract |
| 57 | `feat/issue-52-scoped-reports` | generate scoped validation and handoff reports |
| 58 | `feat/issue-44-program0-validator` | validate Program 0 outputs against SAS artifacts |
| 61 | `feat/issue-52-program0-run-reports` | report Program 0 runs from saved validation evidence |
| 62 | `test/issue-45-wrong-program-0-behavior` | wrong Program 0 behavior tests |
| 65 | `fix/issue-48-structural-repair-feedback` | structural and numerical repair feedback |
| 73 | `feat/program2-model-baseline` | Program 2 model baselines with fixed SAS verification |
| 74 | `feat/issue-69-fastclus-semantics` | FASTCLUS semantic helpers and synthetic probes |
| 75 | `feat/july-2025-replay-report` | Abt and CMS reports from the July 2025 replay |
| 76 | `feat/issue-69-seed-iteration` | FASTCLUS seed selection and iteration helpers |

Also found open and not in the list given to me: PR 53 (`feat/program0-standardization`,
"reproduce Program 0 outputs in Python"). PR 77's description says it was merged with #58's
stack, so it likely also becomes superseded; confirm before closing.

Before closing any superseded PR, check that PR 77 really contains its commits
(`git merge-base --is-ancestor <PR head> integration/issue-71-full-pipeline`), because the
claim comes from the PR description. I did not run that check for each PR.

## Cannot be done from the repository alone

- #46 approval, pricing check, payer and credential holder.
- Paid or local model runs for #48, #68 and #70.
- A Program 1 model-generation controller (#68), if the team wants one.
- A licensed SAS run of the FASTCLUS probes (#69).
- Abt confirmation of report fields and delivery format (#52).
- Teammate clean-checkout and second-computer replays (#13, #49, #71, #72).
- Teammate review of the Program 2 reference implementation, so its stage may be labeled
  human (#71).
- The Program 2 candidate package (restricted Drive) for the STRICT replay (#70); a 10 of 10
  result on the branch already exists from the reference implementation.
