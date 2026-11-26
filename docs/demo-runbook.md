# November pipeline demo runbook

Runbook for the Nov 27 rehearsal (issue #72, which builds on the October walkthrough in #49).
It runs the full Program 0, 1 and 2 pipeline on the supplied CMS July 2025 data, shows an
executable but wrong result failing validation, shows how a bounded repair attempt is
recorded, and renders the Abt and CMS reports. It needs no model call and no API key. Do not
set `SASGUARD_API_KEY` for the demo.

Read this first. What the demo does and does not show:

* Programs 0 and 1 are human-written reference code. Program 2 comes from
  `reference_python/program2.py`, which was not written by a team member and is **pending
  teammate review**. The pipeline records it as `helper_assisted_model_output` with the note
  "Program 2 reference implementation pending teammate review". Never describe it as a human
  Program 2, and never describe the output as approved CMS ratings.
* A `PASS` means: ten artifact comparisons, two handoffs and 29 protected files all matched
  the supplied July 2025 SAS artifacts. It is not human review or Abt/CMS approval.
* The repair record is a saved, scripted replay (a fake provider with human-written
  responses), not a measurement of any model.

Linked docs, not repeated here: [README](../README.md), [Development setup](development-setup.md),
[Full-pipeline validation](full-pipeline-validation.md), [Scoped run reports](scoped-run-reports.md),
[Program 0 model workflow](program-0-model-workflow.md),
[Model and budget decision (draft)](model-budget-decision.md), [Issue close-out](issue-closeout.md).

## Prerequisites

* Git, Docker Desktop (Linux engine running; `docker version` must show a Server section) and
  about 6 GB of free disk.
* Python 3.11 or 3.12 on the host (3.13 is rejected by `pyproject.toml`). The host Python is
  needed for the commands that write the evidence records (`validate-pipeline`, `report-run`),
  because those records capture the host OS and git commit. Inside Docker the OS is Linux and
  the commit is `unknown`.
* Network access to pull images and Python packages during setup. The demo itself is offline.
* No API key, no licensed SAS.

## Setup from a clean checkout

Replace the clone URL with the team's remote and check out the demo branch or the merged
commit the team agreed on. Record `git rev-parse HEAD` in the table at the end.

### Windows PowerShell

```powershell
git clone https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration.git
Set-Location .\Abt-Global-1A-ai-powered-sas-migration
git checkout integration/issue-71-full-pipeline
git rev-parse HEAD
$env:PYTHONUTF8 = "1"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python -m pip install --no-deps --no-build-isolation -e .
sasguard version
docker compose build
```

If PowerShell blocks `Activate.ps1`, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once in that window.

### macOS zsh

```zsh
git clone https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration.git
cd Abt-Global-1A-ai-powered-sas-migration
git checkout integration/issue-71-full-pipeline
git rev-parse HEAD
export PYTHONUTF8=1
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
python -m pip install --no-deps --no-build-isolation -e .
sasguard version
docker compose build
```

Expected: `sasguard version` prints `0.1.0`. Setup takes roughly 5 to 10 minutes (the locked
install dominates). Open every later step in the same activated terminal, from the repository
root. Commands below are identical in both shells unless a block is labeled.

## Demo script

Times are from the dry run on one Windows machine (see [Dry run](#dry-run-on-2026-11-26-windows-11-commit-e3ce14c));
Docker cold builds and slow networks take longer. Paste the `Evidence:` path that
`validate-pipeline` prints into a variable where a step says so.

### 1. Environment and protected data (about 10 s)

```text
docker compose run --rm sasguard sasguard verify-integrity
sasguard verify-integrity
```

Say: the supplied SAS programs, input data and trusted outputs are checksummed against a
committed manifest. Nothing we run may change them, and the validator re-checks them before
and after every run.
Expect: `Integrity check passed: 29 protected files verified.` from both.

### 2. Automated test suite (about 4.5 min; run before the session, show the result)

```text
docker compose run --rm sasguard pytest -q
```

Say: this is the regression suite, including the synthetic wrong-value cases for each stage.
Expect: `812 passed, 29 skipped`. The 29 skips are the Docker-gated tests (they need the host
Docker daemon, which is not available inside the container); step 9 runs two of them. For a
quicker live subset, run the pipeline validator tests on the host:
`python -m pytest tests/verification/test_pipeline.py -q` (37 tests, about 2 min).

### 3. Full pipeline, all ten artifacts (about 7 s)

```text
sasguard validate-pipeline --run-human-references --run-reference-program2
```

Say: Program 0 and Program 1 run from the human-written references; Program 2 runs from the
reference implementation, which is **pending teammate review**, so its origin is recorded as
helper-assisted model output, not human. Every output is a real Python-produced file compared
with the supplied SAS binaries at fixed 1e-12 tolerances, and each handoff between programs
is checked exactly.
Expect: exit code 0 and these lines:

```text
Status: PASS. 10 of 10 artifact comparisons passed.
| Program 0 | human_reference | passed | 3/3 | n/a |
| Program 1 | human_reference | passed | 5/5 | passed |
| Program 2 | helper_assisted_model_output | passed | 2/2 | passed |
STAR mismatches: 0.
Protected-file integrity before / after: 29/29 (passed) / 29/29 (passed).
Evidence: <path>\reports\runs\pipeline-<UUID>
```

Copy the `Evidence:` path. Open `summary.md` in that directory and `pipeline-validation.json`
(see `stages[*].note` for the Program 2 caveat, and `source_hashes`).

PowerShell: `$pass = "reports/runs/pipeline-<UUID>"`. zsh: `pass=reports/runs/pipeline-<UUID>`.

### 4. No Program 2 output gives PARTIAL, not a pass (about 6 s)

`--run-human-references` on its own is refused with exit 2 (it requires a Program 2 source).
To show "Programs 0 and 1 pass, Program 2 missing", point Program 2 at an empty directory.
The source flag is required by the command and is recorded as `direct_model_output`; no
model produced anything here.

```powershell
New-Item -ItemType Directory -Force reports/runs/demo-empty-program2
```

```zsh
mkdir -p reports/runs/demo-empty-program2
```

```text
sasguard validate-pipeline --run-human-references --program2-output reports/runs/demo-empty-program2 --program2-source direct_model_output
```

Say: missing output is a clear failure, and 8 of 10 is never presented as parity.
Expect: exit code 1 and

```text
Status: PARTIAL. 8 of 10 artifact comparisons passed.
Full-pipeline parity: NOT established.
Earliest divergence: Program 2, artifact STAR_2025JUL, missing_output; column n/a, key n/a. file is missing
```

### 5. Executable but wrong result fails validation (about 15 s)

This step starts from a correct Program 0 output, changes one value, and validates. No model
is involved. The `direct_model_output` label stands in for "candidate code produced this";
say aloud that the file is the human reference with one deliberate edit. Use a new directory
name on every rehearsal; `run-program0` refuses an existing directory.

```text
sasguard run-program0 --output-directory reports/runs/demo-wrong-program0
python -c "import pandas as pd; p='reports/runs/demo-wrong-program0/std_data_2025jul_analysis.csv'; d=pd.read_csv(p,dtype=str,keep_default_na=False); print('before', d.loc[0,'PROVIDER_ID'], d.loc[0,'std_MORT_30_AMI']); d.loc[0,'std_MORT_30_AMI']='9.5'; d.to_csv(p,index=False)"
sasguard validate-pipeline --program0-output reports/runs/demo-wrong-program0 --program0-source direct_model_output --run-human-program1 --run-reference-program2
```

Expect: the `python` line prints `before 010001 1.4059231766117712`. Then `run-program0`
wrote `4566 hospitals`; validation exits 1 with

```text
Status: PARTIAL. 6 of 10 artifact comparisons passed.
| Program 0 | direct_model_output | failed | 2/3 | n/a |
| Program 1 | human_reference | upstream_failure | 4/5 | passed |
| Program 2 | helper_assisted_model_output | upstream_failure | 0/2 | passed |
STAR mismatches: 6.
Earliest divergence: Program 0, artifact STD_DATA_2025JUL_ANALYSIS, value; column STD_MORT_30_AMI, key 010001. 1 mismatched cells, 0 missingness mismatches
```

Say: the code ran fine and produced plausible files; only deterministic comparison caught the
error. The earliest divergence is named (stage, artifact, column, hospital), and later stages
are marked `upstream_failure` because they consumed bad input, not because they are wrong.
Copy this run's `Evidence:` path too: PowerShell `$bad = "reports/runs/pipeline-<UUID>"`,
zsh `bad=reports/runs/pipeline-<UUID>`.

Optional (about 12 s): the same idea as automated tests, with three realistic mistakes
(direction reversal skipped, missing values to zero, leading-zero IDs lost), all rejected.
These run on the host without Docker and also inside `docker compose ... pytest`:

```text
python -m pytest tests/integration/test_program0_wrong_candidates.py -v
```

Expect `3 passed`. Details: [Program 0 wrong candidates](program0-wrong-candidates.md).
Pipeline-level wrong-value cases are in `tests/verification/test_pipeline.py`.

### 6. Reports for CMS and Abt (about 2 s each)

```text
sasguard report-run $pass
sasguard report-run $bad
```

Each prints `Internal draft generated: <path>\reports\runs\handoff-<UUID>`. Open `handoff.md`
(short CMS summary), `technical.md` (Abt record) and `report.json`.
Expect for the passing run: `Validation status: VERIFIED`, 10 of 10, 4,566 hospitals processed,
2,891 rated, a star distribution (1: 233, 2: 661, 3: 939, 4: 767, 5: 291, unrated 1,675),
code origin per stage, "Human review and Abt approval: not recorded". For the wrong run:
`Validation status: NOT VERIFIED`, 6 of 10, no hospital counts, and the earliest divergence.
Say: the report only reads the saved record, reruns nothing, and a tampered record renders as
`FAILED`. Point out that `technical.md` carries the Program 2 "pending teammate review" note;
the short CMS `handoff.md` shows "helper-assisted model output" but not that note, so say it
aloud. Abt has not confirmed the final field list. Check both files for credentials and
unapproved data before sharing anything (none were found in the dry run; the check is not a
general secret scanner).

### 7. How a bounded repair attempt is recorded (about 25 s, no API call)

The controller allows at most two repairs, always keeps the first candidate as Attempt 0, and
gives a repair only aggregate diagnostics. This test replays it with a fake provider, no
network and no key: Attempt 0 is a candidate with one column sign-flipped (executes, fails
SAS comparison), Attempt 1 is the corrected candidate. Both run in the network-disabled Docker
runner and are validated on the host.

First build the runner image the test uses (about 1 to 6 min, once and after every pull):

```text
docker build --file Dockerfile.runner --tag sasguard-runner:test .
```

PowerShell:

```powershell
$env:SASGUARD_RUN_DOCKER_TESTS = "1"
python -m pytest tests/integration/test_program0_model_workflow.py -q
Remove-Item Env:SASGUARD_RUN_DOCKER_TESTS
```

zsh:

```zsh
SASGUARD_RUN_DOCKER_TESTS=1 python -m pytest tests/integration/test_program0_model_workflow.py -q
```

Expect `1 passed`. The test writes `reports/runs/program0-model-<UUID>/`; open its `summary.md`
(Attempt 0 `direct` execution succeeded, SAS comparison failed; Attempt 1
`repair_with_automatic_aggregate_diagnostics` passed), then `attempt-0/attempt.json`,
`attempt-0/repair-diagnostics.json`, `attempt-1/attempt.json`, and the request, response and
candidate files per attempt. Then `sasguard report-run reports/runs/program0-model-<UUID>`.
The replay's model name is `test-provider-replay`: it is a control for the plumbing, not
model-quality evidence.

Saved real-model repair records are in the experiment write-ups, which need no API call to
read: [automatic repair v2](experiments/2026-11-10-program0-automatic-repair-v2.md) (Attempt 0
malformed, Attempt 1 15 cells off, Attempt 2 passed) and
[repair and chain](experiments/2026-11-10-program0-repair-and-chain.md). The Program 2
[STRICT replay](experiments/2026-11-16-program2-strict-replay.md) needs candidate files from
the restricted team Drive that are not in the repository, so it cannot be replayed from a
clean checkout. Workflow details: [Program 0 model workflow](program-0-model-workflow.md).

### 8. Close with statuses and limits (about 3 min, talk only)

Use the vocabulary and limits sections below.

## Status vocabulary

The tools report four different things and the reports keep them separate. A green value in
one column never implies another.

| Question | Where it appears | Values |
|---|---|---|
| Who wrote the code (code origin)? | stage `Source` | `human_reference`, `direct_model_output`, `helper_assisted_model_output`, `manually_corrected_model_output`; `not_recorded` when unknown |
| Did it run (execution)? | execution reports, attempt records | succeeded or failed, separate from collection of outputs |
| Does it match SAS (validation)? | `validate-pipeline` | `PASS`, `PARTIAL`, `FAIL`; per artifact passed, failed, missing, malformed, `upstream_failure`; report labels `VERIFIED`, `NOT VERIFIED`, `FAILED` |
| Has a person reviewed it (human review)? | reports | always `not_recorded` today; Abt approval is separate |

`VERIFIED` means all recorded comparisons agreed with themselves and the files, within the
supplied July 2025 SAS artifacts. It is not a human review and not CMS approval.

## Limits to state

* FASTCLUS: clustering behavior is not fully resolved. Exact ties, empty clusters and
  MAXITER raise `UnresolvedSASBehavior` rather than guessing. None occurred on the July 2025
  data, but seed replacement, equidistant assignment and tied final centers still lack SAS
  evidence. See [FASTCLUS iteration](fastclus-iteration.md).
* One release only: results cover the July 2025 inputs and SAS artifacts. No other release,
  no SAS runtime comparison.
* Program 2 reference is pending teammate review and was not written by a team member; its
  `PASS` is not a human Program 2 result.
* No paid model runs are planned: the model, budget and payer decision (#46) is a draft in
  [Model and budget decision](model-budget-decision.md). The repair demonstration is a replay,
  and a prospective model-generated Program 1 or helper-assisted Program 2 run has not happened.
* The licensed-SAS FASTCLUS probes (`tests/sas/fastclus_synthetic_probes.sas`) have not been
  run.
* Reports are internal drafts: Abt has not confirmed the field list, human review is not
  recorded, and the run command and date are not stored in the record.

## Troubleshooting

* Stale runner image: Docker tests fail on missing helpers or old behavior after a pull.
  Rebuild: `docker build --file Dockerfile.runner --tag sasguard-runner:test .` (the CLI
  default tag is `sasguard-runner:local`; build that tag when running
  `run-program0-candidate` or `model-program0` without `--image`). Rebuild the dev image with
  `docker compose build`. Record the image ID with `docker image inspect sasguard-runner:test --format "{{.Id}}"`.
* Garbled box characters, `?` marks or `UnicodeEncodeError` on a Windows console (cp1252):
  set `PYTHONUTF8=1` (`$env:PYTHONUTF8 = "1"` in PowerShell, `export PYTHONUTF8=1` in zsh) and rerun.
* Python version: the project needs 3.11 or 3.12. `python --version` inside the venv must show
  one of them; recreate the venv if not.
* Docker daemon: `docker version` showing a client but no server means Docker Desktop is not
  ready. Start it and wait. Docker-gated tests skip silently without the
  `SASGUARD_RUN_DOCKER_TESTS=1` variable, and show `1 skipped` instead of `1 passed`.
* `Program 0 output already exists; choose a new output directory.` Pick a new directory name.
* `Program 2 needs --program2-output and --program2-source`: pass one of those, or use
  `--run-reference-program2`.
* `sasguard` not found: activate the venv, or call `.\.venv\Scripts\sasguard.exe` (Windows) or
  `./.venv/bin/sasguard` (macOS).
* Output paths must sit under `reports/runs/` (git-ignored). Never write into `data/`.

## Record your rehearsal

Fill one row per machine, and paste it into issue #72. Take OS and commit from
`environment.operating_system` and `environment.git_commit` in
`pipeline-validation.json` of a host run, not a Docker run.

| Field | Value |
|---|---|
| Date and person | |
| OS and version | |
| Docker Desktop version | |
| Commit (`git rev-parse HEAD`) | |
| Dev image ID (`docker compose images`) | |
| Runner image ID | |
| Step 1 integrity (29/29 host and Docker) | |
| Step 2 pytest result and time | |
| Step 3 status, passed by program, STAR mismatches, integrity before/after | |
| Step 4 PARTIAL result | |
| Step 5 earliest divergence reported | |
| Step 6 report labels, secrets check done by | |
| Step 7 repair replay result | |
| Timings per step | |
| Issues and platform notes | |

## Dry run on 2026-11-26, Windows 11, commit e3ce14c

Run by one person on one Windows 11 machine (Python 3.11.9, Docker Desktop with the Linux
engine) from the existing working checkout of branch `integration/issue-71-full-pipeline` at
commit `e3ce14c`, using that checkout's existing virtual environment. This is **not** the
second-machine, clean-checkout rehearsal that issue #72 requires, and macOS zsh was not run.
PowerShell was exercised for the host commands (activation, `sasguard`, `python -c`) and Git
Bash for the rest. Outputs are under `reports/runs/` (git-ignored). The record reports the OS
as "Windows 10 10.0.26300" for this Windows 11 machine, which is how Python reports it.

| Step | Result | Time |
|---|---|---|
| Fresh venv and locked install (`pip install --require-hashes`, editable install, version, integrity) in a scratch venv | passed, `0.1.0`, 29 files | 6 min 13 s (ran alongside a test run) |
| `docker compose build` | passed (image cache warm) | 1 min 3 s |
| `docker compose run --rm sasguard sasguard verify-integrity` | passed, 29 files | 5 s |
| Host `sasguard verify-integrity` | passed, 29 files | 2 s |
| `docker compose run --rm sasguard pytest -q` | 812 passed, 29 skipped | 4 min 35 s |
| `validate-pipeline --run-human-references --run-reference-program2` (host) | PASS 10/10, 0 STAR mismatches, 29/29 and 29/29 | 7 s |
| Same command inside the Docker service | PASS 10/10; record shows OS Linux and commit `unknown` | 16 s |
| `validate-pipeline --run-human-references` alone | exit 2, needs a Program 2 source (not PARTIAL) | 3 s |
| Empty Program 2 directory (step 4) | PARTIAL 8/10, earliest divergence Program 2 `STAR_2025JUL` missing | 6 s |
| Wrong result (step 5) | PARTIAL 6/10, 6 STAR mismatches, earliest divergence Program 0 `STD_DATA_2025JUL_ANALYSIS`, `STD_MORT_30_AMI`, key `010001`; PowerShell variant identical | 11 s (`run-program0` 2 s) |
| `report-run` on the PASS run | VERIFIED, 4,566 hospitals, 2,891 rated | 2 s |
| `report-run` on the wrong run | NOT VERIFIED, 6 of 10, no hospital counts | 2 s |
| Runner image build, `sasguard-runner:test` | passed, image ID `sha256:1f2fc94c5bf30bae873e6f9db9355305a4eb5c315da568e128895182fd287ed5` | 1 min 7 s |
| Repair replay with Docker (step 7), then `report-run` on its record | 1 passed; Attempt 0 failed SAS comparison, Attempt 1 passed; report generated | 22 s, 2 s |
| `tests/integration/test_program0_wrong_candidates.py` (host) | 3 passed | 12 s |
| `tests/verification/test_pipeline.py` (host) | 37 passed | 2 min |

Dev image `btt-sasguard:latest` ID `824a99b96c1f` (the name follows the checkout folder). The
replacement of the previous runner image `0a566c94b9ee` by `1f2fc94c5bf3` shows that images go
stale after a rebuild; rebuild after every pull.

What was not run: a clean clone, macOS zsh, a second computer, the Docker-gated suite beyond
steps 7, any model call, licensed SAS. Findings during the dry run: the pipeline documentation
claimed `--run-human-references` alone yields PARTIAL (it exits 2; corrected), and the short
CMS `handoff.md` omits the Program 2 "pending teammate review" note that `technical.md` and
`report.json` carry.
