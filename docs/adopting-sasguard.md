# Adopting SASGuard at Abt

This guide is for engineers and analysts at Abt Global who are deciding whether to adopt
SASGuard and, after that, using it without the student team present. It says what the system
guarantees, how to see that for yourself in fifteen minutes, how to point it at new work, and
where it stops. Every command below exists in the installed CLI; every path exists in the
repository.

SASGuard was built and validated on one case: the CMS July 2025 Overall Hospital Quality Star
Rating pipeline (three SAS programs, ten SAS output artifacts). Anything beyond that case is
described here as untested.

## 1. What SASGuard is and what it guarantees

SASGuard checks that Python produces the same outputs as SAS. It treats the SAS output files
you already have as the answer key and decides pass or fail with ordinary code. It can also
drive a model to write the Python, but the model is optional and never part of the decision.

| Guarantee | How it is enforced | Where |
|---|---|---|
| A deterministic validator decides | Row alignment by `PROVIDER_ID` (text, so leading zeros count), missing values must match missing values, exact comparison for flags, counts, categories and stars, `1e-12` absolute and relative for calculated values. Policies are fixed before any run. | `src/sasguard/verification/`, [Comparison policy](comparison-policy.md) |
| The model never grades itself | The validator runs on the host and reads the SAS outputs; the model only ever sees SAS source and column names. Repair feedback is built by the host from aggregate diagnostics. | [Program 0 model workflow](program-0-model-workflow.md) |
| Generated code runs isolated | Network-disabled container, read-only root, three mounts (source, input, output), no trusted outputs mounted, no API key in the container. | `Dockerfile.runner`, `src/sasguard/execution/`, [Isolated runner](isolated-runner.md) |
| Supplied materials cannot be altered to pass | 29 protected files (SAS programs, input, SAS outputs) are hashed against a committed manifest before and after every run. | `configs/protected-artifacts.json`, [Data integrity](data-integrity.md) |
| Handoffs are real | Program 1's copied measures must equal the actual Program 0 output file, and Program 2's copied domain scores must equal the actual Program 1 scores, exactly. A stage that did not consume its upstream output fails even if its numbers are within tolerance. | `src/sasguard/verification/pipeline.py`, [Full-pipeline validation](full-pipeline-validation.md) |
| Tolerances cannot be quietly loosened | Before comparing, every tolerance in the three policy files is audited; any nonzero value other than exactly `1e-12` fails the run. | `src/sasguard/verification/pipeline.py` |
| Evidence is re-checked | Every run records source, input, output and policy hashes, the environment and the git commit. `report-run` re-hashes the recorded outputs and only then prints VERIFIED; a missing or altered stage gives NOT VERIFIED or FAILED. | `pipeline-validation.json`, `src/sasguard/reporting/` |
| Code origin is labeled honestly | Each stage is `human_reference`, `direct_model_output`, `helper_assisted_model_output` or `manually_corrected_model_output`. Review is recorded separately (`reviewed_by`) and never changes the origin. | [Full-pipeline validation](full-pipeline-validation.md) |
| Privacy | Model prompts contain SAS source, column names and a runtime contract, never hospital rows, trusted values or human Python. The CMS summary contains no provider IDs and no column that is not in the SAS reference schema; the first differing key and unexpected headers stay in the technical record. | [Model workflows](program-0-model-workflow.md), `src/sasguard/reporting/render.py` |

### What a PASS means

`PASS` means: all ten artifact comparisons matched the supplied SAS artifacts under the fixed
policy, both handoffs were exact, the policy audit passed, and all protected files were
unchanged before and after. Pipeline status is `PASS`, `PARTIAL` (some comparisons pass; never
parity) or `FAIL`. Only `PASS` exits 0.

### What a PASS does not mean

* It is not Abt or CMS approval. Human review and client approval are not recorded by the
  validator.
* It does not cover any release other than the one the run was configured for.
* It does not prove the SAS itself is right. SAS is the reference by definition.
* If a stage's code origin is not `human_reference`, the PASS says nothing about who wrote or
  reviewed that code.

## 2. Fifteen-minute evaluation

No API key, no SAS license and no model calls are needed.

**Prerequisites:** Git, Docker Desktop (the Linux engine must be running; `docker version`
should show a Server section), Python 3.11 or 3.12 (3.13 is rejected), about 6 GB of disk and
network access for setup. The host Python is needed because evidence records capture the host
OS and git commit.

**Setup, Windows PowerShell:**

```powershell
git clone https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration.git
Set-Location .\Abt-Global-1A-ai-powered-sas-migration
$env:PYTHONUTF8 = "1"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python -m pip install --no-deps --no-build-isolation -e .
docker compose build
```

**Setup, macOS zsh:**

```zsh
git clone https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration.git
cd Abt-Global-1A-ai-powered-sas-migration
export PYTHONUTF8=1
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
python -m pip install --no-deps --no-build-isolation -e .
docker compose build
```

Check out the commit the team gave you (the [runbook](demo-runbook.md) uses branch
`integration/issue-71-full-pipeline`). Setup takes 5 to 10 minutes.

**Run it:**

```text
sasguard demo
```

`sasguard demo` runs the integrity check, then the full Program 0, 1 and 2 pipeline using the
human-written Program 0 and 1 references and the bundled Program 2 reference, then writes the
reports. It exits 0 only on PASS and prints the evidence directory and the report directory.
It makes no model calls and needs no API key.

The same steps by hand, if you want to see each one:

```text
sasguard verify-integrity
sasguard validate-pipeline --run-human-references --run-reference-program2
sasguard report-run reports/runs/pipeline-<UUID>
```

Expected: `Integrity check passed: 29 protected files verified.`, then
`Status: PASS. 10 of 10 artifact comparisons passed.` and `STAR mismatches: 0.`

**Reading the outputs** (all under `reports/runs/`, which is ignored by Git):

| File | Read it for |
|---|---|
| `pipeline-*/summary.md` | The verdict: status, per-stage source and result, artifact counts, STAR mismatches, integrity before and after, and the earliest divergence on a failure. |
| `pipeline-*/pipeline-validation.json` | The full evidence record: per-stage source flags and notes, every artifact comparison, handoff results, `source_hashes`, input, policy and reference hashes, environment (Python, OS, packages, git commit) and output hashes. |
| `handoff-*/report.html` | A self-contained visual report written by `report-run` (and therefore `demo`): status, stage table, and the star distribution only when the run is VERIFIED. It is CMS-safe, so it has no provider IDs. |
| `handoff-*/handoff.md` | The short CMS-facing summary, marked internal draft. States code origin per stage and "Human review: not recorded. Abt approval: not recorded.". |
| `handoff-*/technical.md` | The Abt-facing record: policies, hashes, per-stage notes and the Program 2 pending-review caveat. |
| `handoff-*/report.json` | The same report as machine-readable data. |

Check that `summary.md` says Program 2 is `helper_assisted_model_output` with the note
"Program 2 reference implementation pending teammate review". That label is deliberate; see
section 7.

**See it fail.** A correct-looking but wrong result must not pass. Step 5 of the
[demo runbook](demo-runbook.md#5-executable-but-wrong-result-fails-validation-about-15-s)
changes one Program 0 value and re-runs validation: the code runs fine, status becomes
`PARTIAL`, the earliest divergence is named (Program 0, `STD_DATA_2025JUL_ANALYSIS`, column
`STD_MORT_30_AMI`, key `010001`) and later stages are marked `upstream_failure`. Step 4 shows
a missing Program 2 output also giving `PARTIAL`, not a pass. Run `report-run` on the failing
evidence and you get NOT VERIFIED with no hospital totals.

## 3. Using it on a new CMS star-rating release

`validate-pipeline` and `demo` take `--config PATH`, so a new release needs files, not code
edits. Only July 2025 has been run on real data. The second release below is a synthetic one:
the July 2025 data with every release-tagged file renamed to `2026jan`
(`tests/test_release_config.py`). It shows that no July name is hardcoded on the pipeline path;
it says nothing about how a real new release behaves.

**Steps for a new release (tag `2026jan` as the example):**

1. Put the supplied materials under a new protected root, for instance a copy of the
   `data/Project_1` layout, with every release-tagged file named with the lowercase tag:
   `alldata_2026jan.csv`, `std_data_2026jan_analysis.sas7bdat`, `star_2026jan.sas7bdat`, and
   so on. The CSV copies use the upper-case form (`STAR_2026JAN.csv`).
   The project root also needs `reference_python/`, and `configs/program0-comparison-policies.json`,
   `program1-...` and `program2-...` copied unchanged (the run reads them from there and stops
   with a missing-file error otherwise). The SAS program files may keep their July names; list
   them as they are in the configuration.
2. Write a new configuration beside `configs/cms_2025jul.yaml`, for example
   `configs/cms_2026jan.yaml`, following [Project configuration](project-configuration.md).
   List the ten artifacts with their `2026JAN` names and add the release section:

   ```yaml
   release:
     tag: 2026jan                                     # lowercase letters and digits
     integrity_manifest: configs/protected-artifacts-2026jan.json
   ```

   Both fields are optional. Without a `release` section the tag is `2025jul` and the manifest
   is `configs/protected-artifacts.json`, which is why the July 2025 configuration did not
   change.
3. Build the new manifest for the new files (see the regeneration policy below) and save it at
   the path named in the configuration.
4. Run `sasguard validate-pipeline --config configs/cms_2026jan.yaml ...` or
   `sasguard demo --config configs/cms_2026jan.yaml`, then `sasguard report-run`. The record
   stores the release tag and the SHA-256 of the configuration and manifest that were used, and
   the report shows them.

The tag decides every release-dependent name: `STAR_2026JAN`, `NATIONAL_AVERAGE_2026JAN`,
`MEASURE_AVERAGE_STDDEV_2026JAN`, `STD_DATA_2026JAN_ANALYSIS`, their lowercase CSV filenames,
and the input file `alldata_2026jan.csv`. The other six artifacts keep their names. The names
are derived in one place, `src/sasguard/release.py`.

**Files that carry the release:**

| What | Location | Release-specific? |
|---|---|---|
| Project configuration: programs, macro, input paths, ten artifact names and files, key, release tag and manifest | `configs/cms_2025jul.yaml` ([Project configuration](project-configuration.md)) | Yes. Create a separate YAML for a new release rather than overwriting July 2025. |
| Supplied SAS programs, macro, input dataset, SAS outputs | `data/Project_1/` | Yes. |
| Protected-artifact manifest | `configs/protected-artifacts.json`, or the path in `release.integrity_manifest` | Yes. Built for the new files (below). |
| Comparison policies (keys, exact columns, tolerances) | `configs/program0-comparison-policies.json`, `program1-...`, `program2-...` | Shared. They are written once, keyed by the July 2025 names, and applied to a new release by role: `STAR_2026JAN` uses the `STAR_2025JUL` entry. No tolerance changes. If the new SAS output schema differs, the comparison fails on the schema instead of adapting. |
| Artifact lineage | `configs/cms-artifact-lineage.json` | Yes, if the dataset graph changes. |
| Human references | `reference_python/domain_scoring.py`, `reference_python/program2.py`, `src/sasguard/program0.py` | Yes. They implement the July 2025 SAS programs; a changed SAS program needs a changed reference. |

**Still July 2025 only:** the model workflows (`model-program0`, `model-program2`,
`run-program0-candidate`, `run-program01-chain`), the mortality prototype, the Program 0 scoped
reports, and the Program 0 Docker execution path in `src/sasguard/execution/program0.py` still
read `configs/cms_2025jul.yaml` and the `2025JUL` names. `--config` applies to the full
pipeline (`validate-pipeline`, `demo`, and `report-run` on their records) only.

**Regenerating the protected-artifact manifest.** The manifest is a hash list of every file
under the protected root `data/Project_1`. Do not regenerate it to make a failure disappear.
For officially supplied new materials, follow the update policy in
[Data integrity](data-integrity.md): a dedicated issue naming the source and reason, an
independent teammate verification of the new files, one focused change containing the files and
the manifest, old and new hashes in the review evidence, and approval from someone other than
the author. There is no CLI command that writes the manifest. The function that builds it is
`build_integrity_manifest` in `src/sasguard/verification/integrity.py`; a reviewer runs it and
inspects the diff. For example, from the project root with the environment activated
(replace the output path with the `release.integrity_manifest` in your config):

```text
python -c "from pathlib import Path; from sasguard.verification.integrity import build_integrity_manifest; m = build_integrity_manifest(Path('.'), ['data/Project_1']); Path('configs/protected-artifacts-2026jan.json').write_text(m.model_dump_json(indent=2) + '\n')"
```

List every directory that holds the release's input, SAS programs and trusted outputs. A
manifest that covers fewer files protects fewer files, and the run records which manifest
was used. After the change, `sasguard verify-integrity` should report the new file
count (not 29).

**Reusable as is:** the comparator and policy engine, the integrity checker, the isolated
runner, the handoff checks, the earliest-divergence logic, the evidence and report writers, and
the SAS-semantics helpers.

**Release-specific:** tolerances you choose per column, key and schema lists, the artifact
names and the three human reference programs.

**Not tested:** any real release other than July 2025 (the `2026jan` run is renamed July data); any change to measure counts, schema
additions or renamed columns; behavior when a FASTCLUS tie, empty cluster or MAXITER stop
occurs on real data (the helpers raise `UnresolvedSASBehavior` rather than guess; none
occurred in July 2025). A second release is the single most valuable test Abt can run.

## 4. Verifying a translation from any source

`validate-pipeline` checks Python output files, not code, and does not care who wrote the code.
Point it at directories of CSVs named like the SAS artifacts (`less100_measure.csv`,
`outcome_mortality.csv`, `star_2025jul.csv`, and so on; Program 1 names match ignoring case).

```text
sasguard validate-pipeline \
  --program0-output D:\work\p0 --program0-source human_reference \
  --program1-output D:\work\p1 --program1-source human_reference \
  --program2-output D:\work\p2 --program2-source direct_model_output \
  --program2-code D:\work\program2.py
```

(PowerShell uses a backtick for line continuation; zsh uses a backslash.)

| Option | Meaning |
|---|---|
| `--programN-output DIR` | Directory with that stage's actual output CSVs (N = 0, 1, 2). |
| `--programN-source LABEL` | Where that output came from. Required whenever the output is supplied. |
| `--programN-code FILE` | Optional. Records the SHA-256 of the candidate source file. |
| `--program2-note TEXT` | Free-text provenance note. |
| `--program2-reviewed-by NAME` | Records a reviewer separately from the origin. |
| `--run-human-references` | Produce Programs 0 and 1 from the human references instead of supplying them. |
| `--run-human-program1` | Run the human Program 1 on the supplied `--program0-output`. |
| `--run-reference-program2` | Run the bundled Program 2 reference on the Program 0 and 1 outputs. Its origin is fixed; `--program2-source` and `--program2-code` are rejected with it. |
| `--output-directory`, `--project-root` | Where to write the record (a new directory under `reports/runs`), and the repository root. |

**Stage source labels:**

| Label | Use when |
|---|---|
| `human_reference` | A person wrote and owns the code. |
| `direct_model_output` | A model wrote it and nobody edited it or added helpers. |
| `helper_assisted_model_output` | A model wrote it with SASGuard's tested SAS helpers (for example FASTCLUS). |
| `manually_corrected_model_output` | A model wrote it and a person edited it afterward. This cannot keep a model-only attribution. |

Use the label that is true. An Abt engineer's translation is `human_reference`; output from
another migration tool is closest to `direct_model_output`; anything fixed by hand afterwards is
`manually_corrected_model_output`. The label is recorded and shown in every report. The command
validates files on the host and never runs your code. If you also want isolation, run the code
yourself through [the isolated runner](isolated-runner.md) first and pass the produced
directory.

All three stages need an output directory and a source label; omitting one is a setup error
(exit 2). A stage whose directory is empty or whose files are missing is reported as the
earliest divergence (status `PARTIAL`, never a pass).

## 5. Adding a different SAS program or pipeline

The generic pieces below exist and are importable. The wiring from them to a CMS-style
pipeline is CMS-specific today, so a different pipeline needs new glue code, not only new
configuration.

| Extension point | Where | State |
|---|---|---|
| Artifact loading (SAS7BDAT and CSV, keyed, case-insensitive columns) | `src/sasguard/data/loading.py`, `src/sasguard/loaders.py`, [Artifact loading](artifact-loading.md) | Generic. |
| Comparison policy (keys, exact versus numeric columns, tolerances, missing-value mode, structural actions) | `src/sasguard/verification/policy.py`, `src/sasguard/verification/comparator.py`, [Comparison policy](comparison-policy.md) | Generic. A policy is plain JSON. |
| Artifact definitions and lineage | `configs/cms_2025jul.yaml`, `configs/cms-artifact-lineage.json`, `src/sasguard/config.py`, `src/sasguard/verification/lineage.py` | Config loader is strict and reusable; the artifact list is CMS data. |
| Per-program validators | `src/sasguard/verification/program0.py`, `program1.py`, `program2.py`, orchestrated by `pipeline.py` | CMS-specific: filenames, keys, handoff column maps and statistic comparisons. Use them as the pattern. |
| Protected-file integrity | `src/sasguard/verification/integrity.py` | Generic over any `protected_roots`. |
| SAS semantics helpers | `src/sasguard/semantics/fastclus.py` (percentile definition 5, STRICT identifiers, cluster-to-star order), `fastclus_iteration.py`, `src/sasguard/group_scoring.py` | Behaviors models get wrong; add new ones with tests under `tests/`. FASTCLUS is not generic to other procedures. |
| Isolated runner contract | `src/sasguard/execution/runner.py`, `worker.py`, `result.py`, `Dockerfile.runner` | Generic: source, input and output mounts, `SASGUARD_INPUT_DIR` and `SASGUARD_OUTPUT_DIR`, status and policy-violation result. |
| Model workflows | `src/sasguard/prototypes/program0_prompt.py`, `program0_model.py`, `program2_model.py` | CMS-specific prompts and contracts; the request, hashing and repair shape is reusable. |
| Evidence and reports | `src/sasguard/reporting/pipeline.py`, `reader.py`, `render.py`, `models.py` | Reports read the evidence record; the CMS fields (hospital counts, star distribution) are July 2025 specific. |

To add a pipeline: write a project YAML and policy JSON files for its artifacts, a validator
module like `verification/program2.py`, handoff checks like `check_domain_passthrough`, a
reference or candidate producing CSVs, then tests that include a wrong-but-executable case for
each stage. The existing tests under `tests/verification/` show the pattern. Expect to touch
Python, not only configuration.

## 6. Using models

Models are optional. The pipeline passes and fails the same way with or without them.

| | Program 0 | Program 2 |
|---|---|---|
| Command | `sasguard preview-program0-prompt`, then `sasguard model-program0 PREVIEW_DIR --image ...` | `sasguard model-program2 --image ... --upstream-chain DIR` (or `--reference-inputs`) |
| Workflow doc | [Program 0 model workflow](program-0-model-workflow.md) | [Program 2 model workflow](program-2-model-workflow.md) |
| Default model and limits | `gpt-6-luna`, medium reasoning, 8,192 output tokens, `--repair-attempts` 0 to 2 (default 0) | Same model, 16,384 output tokens, `--repair-attempts` 0 to 2 (default 2) |

There is no Program 1 model command; Program 1 is human reference only.

**What the prompt contains:** the SAS programs and macro file, input column names and a
runtime contract. **What it never contains:** hospital rows, trusted output values, expected
counts or human Python. The preview command lets you read the exact `prompt.txt` and
`contract.json` before anything is sent, and invoking `model-program0` is the authorization to
send that reviewed payload (see [Prompt preview](program-0-prompt-preview.md)). Repair feedback
is aggregate only: counts, column names and structural errors, with no provider IDs, values,
stdout, stderr or exception text.

**API key handling:** the host reads `SASGUARD_API_KEY` from the environment. Enter it without
putting it in a command or file, and unset it afterward. The key is never forwarded to the
container. The Program 0 workflow doc has the PowerShell (`Read-Host -AsSecureString`) and zsh
(`read -s`) forms. Do not set it for the demo.

**Budget.** The controllers record token usage returned by the provider; they do not estimate
price or enforce a dollar cap. The model, payload and spending decision
([Model budget decision](model-budget-decision.md), issue #46) is still a draft, with owners,
prices and caps marked TBD. No paid use should be approved against it until it is completed.

**Recorded results** (one model, `gpt-6-luna`; results from single runs, not statistics):

* Program 0 with automatic repair: attempt 0 produced a malformed statistics table, attempt 1
  still had 15 statistics cells wrong, attempt 2 passed all three artifacts, driven only by
  automatically built diagnostics ([experiment](experiments/2026-11-10-program0-automatic-repair-v2.md)).
  Repair passed 3 of 3 artifacts after two repairs.
* Program 2 baseline: the best candidate matched every score, weight and peer group but got 2
  of 2,891 stars wrong, and was reported FAILED
  ([baseline](experiments/2026-11-10-program2-luna-baseline.md)). A manual correction for SAS
  FASTCLUS `STRICT` handling brought it to 0 mismatches; the percentile fix alone did not
  change the result ([STRICT replay](experiments/2026-11-16-program2-strict-replay.md)). That
  corrected result is a manually corrected, retrospective one, not a prospective model pass.
* Local small models on synthetic cases: [Helper comparison](local-model-helper-comparison.md).

## 7. Known limits and open items

* **One real release.** Only July 2025 has been validated on real data. A second release runs
  through `--config` (section 3), proven only on renamed July data; model workflows and the
  mortality prototype remain July 2025 only.
* **Program 2 reference is pending teammate review.** `reference_python/program2.py` was not
  written by a team member. It is recorded as `helper_assisted_model_output` with a fixed
  note, its hash is recorded, and its origin cannot be relabeled. Its output is not approved
  CMS ratings.
* **FASTCLUS helpers are from documentation.** They follow SAS documentation and agree with the
  supplied outputs on July 2025, but have not been probed on licensed SAS
  ([FASTCLUS findings](issue-51-fastclus-findings.md)). Exact ties, empty clusters and MAXITER
  stops raise `UnresolvedSASBehavior` instead of picking a rule.
* **No model-generated Program 1.** It has not been attempted.
* **Model budget is a draft** (issue #46).
* **Isolation is not a security proof.** The runner reduces risk; it is not a hardened sandbox
  and should not be exposed as a multi-tenant service. Only trusted people should choose
  images and mount paths ([Isolated runner](isolated-runner.md)).
* **Reproducibility is bounded.** Pinned dependencies do not make a rebuild byte-identical;
  the base image tag is mutable. Keep the recorded image ID ([Reproducibility](reproducibility.md)).
* **Reports are local records,** not signed attestations. Check any report for credentials and
  unapproved data before sharing it.
* **License not yet selected.** The README says so; do not assume terms.
* **PASS is not approval** by Abt or CMS.

## 8. Adoption checklist for Abt

1. Confirm the license with the Challenge Advisor before copying or redistributing the code.
2. Run `sasguard demo` on an Abt machine and keep the evidence directory. Confirm PASS, 29/29
   protected files and the recorded commit.
3. Review `reference_python/program2.py` against the Program 2 SAS. When a reviewer signs off,
   record it with `--program2-reviewed-by "<name>"`; the origin label stays
   `helper_assisted_model_output`. Optionally replace it with an Abt-owned implementation and
   validate it through section 4.
4. Probe the FASTCLUS helpers on licensed SAS if the clustering step will be relied on.
5. Run the pipeline on a second CMS release, following section 3 and the manifest policy in
   [Data integrity](data-integrity.md).
6. Decide whether to use models at all, and if so complete the [budget decision](model-budget-decision.md)
   (provider, model, caps, key holder) first.
7. Put `sasguard verify-integrity` and `sasguard demo` in CI. Docker-gated tests need a built
   runner image (`docker build --file Dockerfile.runner --tag sasguard-runner:test .`).
8. Agree who signs off a result before it is shared with CMS. SASGuard does not record that.

## 9. Where to look in the code

| Area | Path |
|---|---|
| Commands (`demo`, `verify-integrity`, `validate-pipeline`, `report-run`, `run-program0`, `model-program0`, `model-program2`, `preview-program0-prompt`, `check-program0-prompt`, `run-program01-chain`, `mortality-prototype`, local-model commands) | `src/sasguard/cli.py` |
| Comparison engine and policy schema | `src/sasguard/verification/comparator.py`, `policy.py`, `artifact.py` |
| Per-stage validators and full-pipeline orchestration | `src/sasguard/verification/program0.py`, `program1.py`, `program2.py`, `pipeline.py` |
| Protected-file integrity | `src/sasguard/verification/integrity.py`, `configs/protected-artifacts.json` |
| Project configuration | `src/sasguard/config.py`, `configs/cms_2025jul.yaml` |
| Human references and Program 2 reference | `src/sasguard/program0.py`, `reference_python/` |
| Reference runners | `src/sasguard/prototypes/pipeline_reference.py`, `program01.py` |
| SAS semantics | `src/sasguard/semantics/` ([Program 2 semantics](program-2-sas-semantics.md), [FASTCLUS iteration](fastclus-iteration.md)) |
| Isolated runner | `src/sasguard/execution/`, `Dockerfile.runner`, `scripts/run-isolated.ps1`, `scripts/run-isolated.sh` |
| Model workflows | `src/sasguard/prototypes/program0_prompt.py`, `program0_model.py`, `program2_model.py` |
| Reports | `src/sasguard/reporting/` |
| Tests | `tests/verification/`, `tests/integration/`, `tests/regression/` |
| Experiments and runbooks | `docs/experiments/`, [Demo runbook](demo-runbook.md), [Reproducibility](reproducibility.md) |
