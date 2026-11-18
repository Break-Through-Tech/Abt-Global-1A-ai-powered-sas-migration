# Program 0 to Program 1 chain

`run-program01-chain` runs Keira's human-written Program 1 reference on a verified
Python-generated Program 0 CSV. It compares all five domain outputs against the supplied
SAS binary outputs on the host. No model calls occur in this command.

This connects two stages for the supplied July 2025 release. Program 2, eligibility,
clustering, star assignment, and the complete pipeline remain unverified.

## Run the chain

Use the host Python environment described in [Development setup](development-setup.md)
and start Docker. Build the isolated runner if needed:

```text
docker build -f Dockerfile.runner -t sasguard-runner:local .
python -m sasguard.cli run-program01-chain reports/runs/PROGRAM0-RUN --image sasguard-runner:local
```

The command is identical in PowerShell and zsh. Replace `PROGRAM0-RUN` with either a
verified `program0-candidate-*` directory or a verified `program0-model-*` directory.
Use an image ID instead of the tag when reproducing an experiment with an exact image.

The existing report reader must confirm all three Program 0 outputs and their saved
evidence before Program 1 starts. A failed, incomplete, changed, or unconfirmed run is
rejected. An arbitrary CSV file is not an accepted input.

## Execution and validation

The controller copies `output/std_data_2025jul_analysis.csv` from that Python run into a
new input directory without rewriting it. The container receives only that CSV, the
unchanged `reference_python/domain_scoring.py`, and a CSV entry point. It does not receive
the supplied SAS intermediate, domain reference outputs, API credentials, or the validator.

The reference's existing SAS7BDAT entry point is unchanged. The chain's CSV entry point
preserves text provider identifiers and uses round-trip floating-point parsing. Both
stages therefore consume the same numerical intermediate recorded in the handoff.

Host verification compares `OUTCOME_MORTALITY`, `OUTCOME_SAFETY`, `OUTCOME_READMISSION`,
`PTEXP`, and `PROCESS` using the committed Program 1 policies. Each output also receives
an exact check of its copied standardized measures against the actual Python input.
This additional check catches a change smaller than the SAS comparison tolerance.
Existing comparison tolerances and protected reference artifacts are unchanged.

Source, policy, input, reference, and controller hashes are checked around execution
and comparison. Missing, malformed, or undeclared outputs prevent a pass.

## Evidence

Each invocation creates an ignored `reports/runs/program01-chain-*` directory with:

* `chain.json`, containing the upstream report, snapshot hashes, Docker result, five SAS
  comparisons, five exact input-copy comparisons, output hashes, and comparison policies;
* `summary.md`, containing aggregate outcomes and explicit scope limits;
* `manifest.json`, `source/`, `input/`, and `output/` for reproducing the execution.

The summary records Program 1 as a human-written reference. It retains Program 0's
recorded origin; a candidate execution alone cannot establish model generation or the
kind of repair that produced the code. If separate experiment metadata establishes a
human-guided repair, retain that metadata alongside this run rather than calling the
chain an unassisted model translation.

Exit status zero requires a verified upstream run and all five SAS and input-copy
comparisons to pass. Status 1 means the saved chain failed. Status 2 means it could not
start. Human review and approval for a client release remain unrecorded.
