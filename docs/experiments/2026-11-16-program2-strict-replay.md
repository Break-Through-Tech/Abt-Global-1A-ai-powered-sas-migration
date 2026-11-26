# Program 2 STRICT replay

The November 10 Luna candidate produced two incorrect star assignments. We tested two
changes independently on copies of that candidate. Applying `STRICT=1` during the
second pass removed both differences. Correcting the percentile formula alone left
the outputs byte-identical to the original. [Original experiment](2026-11-10-program2-luna-baseline.md)

The candidate's percentile function used `(n+1)*p` interpolation, the formula for
definition 4. The percentile variant substituted the definition 5 calculation from
PR #74. The STRICT variant excluded observations more than one unit from their nearest
center when recomputing second-pass means. It kept one-based signed assignments for the
final join. The macro takes `ABS(cluster)`, so a rejected observation still maps to the
star for its nearest center. [UNIVARIATE percentiles](https://support.sas.com/documentation/cdl/en/procstat/63104/HTML/default/procstat_univariate_sect028.htm)
[FASTCLUS options](https://support.sas.com/documentation/cdl/en/statug/63033/HTML/default/statug_fastclus_sect005.htm)

| Candidate | STAR mismatches, Python chain input | STAR mismatches, supplied SAS intermediates |
|---|---:|---:|
| November 10 candidate | 2 | 2 |
| Definition 5 percentile only | 2 | 2 |
| STRICT correction only | 0 | 0 |
| Definition 5 percentile and STRICT correction | 0 | 0 |

All eight cases executed in Docker. National averages, exact copied domain scores and
missingness passed in every case. The unchanged controls reproduced the saved output
bytes. Input, candidate and policy hashes were recorded. All 29 protected files passed
the integrity check. The experiment used no additional model calls.

## Fresh chain replay

A new Docker run started from the protected July 2025 hospital input and passed all ten
artifact comparisons. Program 0 reused the saved model candidate after two automatic
repairs and passed 3/3. Program 1 used the human reference, consumed the newly produced
standardized CSV and passed 5/5. Program 2 used the model candidate with the manual
STRICT correction, consumed the new Python intermediates and passed 2/2. The exact
input-copy checks passed for Programs 1 and 2. All July 2025 star assignments matched.

Run from the repository root with the project Python environment and Docker. Supply the
saved Program 0 `attempt-2/candidate.py` and the Program 2 `attempt-2/source/main.py`
from the November 10 runs. The script verifies both candidates by hash and applies
the STRICT correction to a new copy. The recorded replay used the runner built from
`Dockerfile.runner` with image ID
`sha256:50903cf590be0dc3a6b3cc08ae3772d34d3d1ab555daada0fdff7c029796b5df`.

```text
docker build -f Dockerfile.runner -t sasguard-runner:local .
python scripts/replay_program2_strict.py PATH_TO_PROGRAM0_CANDIDATE PATH_TO_PROGRAM2_CANDIDATE
```

The command writes fresh records under `reports/runs/`. The `summary.json` in the
`program2-strict-replay-*` directory links the Program 0 and Program 1 reports and
records the Program 2 source, input and policy hashes. Keep the saved source artifacts
locally to reproduce the replay.

The replay also writes `abt-validation.md` and `cms-summary.md` beside the summary.
The Abt draft shows the Docker and validation results for each stage. The CMS draft
includes aggregate rating counts only after all ten comparisons and the integrity
checks pass. Review both drafts before sharing them outside Abt.

This result covers the supplied July 2025 release and a manually corrected hybrid
chain. The original source-only baseline retains its FAILED verdict. The narrow replay
still uses the original percentile formula and leaves broader FASTCLUS seed selection,
ties, and iteration behavior to be checked with SAS runtime evidence. A prospective
model repair and validation on another release are separate open tasks.
