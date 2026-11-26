# Model, payload and budget decision record (issue #46)

**Status: DRAFT, not approved.**

This is a template for the team to fill in and approve. It records what the code does today
so the decision can be made against facts. It does not approve any paid call, data upload,
model, price or spending cap. Blank fields marked `TBD` must be completed by the decision
owners. No price appears here because none was checked.

Drafted against branch `integration/issue-71-full-pipeline` (draft PR #77). Code facts below
were read from the source on that branch; statements that could not be confirmed are marked
"unverified".

## 1. Owners and approvers

Issue #46 has no assignees on GitHub. The issue text only suggests an owner and a reviewer
and asks the team to confirm at sprint planning.

| Role | Suggested in #46 | Confirmed |
|---|---|---|
| Decision owner | Amiri | TBD |
| Reviewer | Tony | TBD |
| Person who pays / holds the budget | not named in #46 | TBD |
| Person who holds the credential | not named in #46 | TBD |

Related assignees on the dependent issues (for information): #48 Loaardi (suggested owner
Amiri, reviewer Vasco); #67 theocsav, AmiriHayes; #68 AmiriHayes, keiraw777; #70 theocsav,
keiraw777.

## 2. Provider and model

Values currently hard-coded or defaulted in the repository:

| Item | Current value | Source |
|---|---|---|
| API host and endpoint | `api.openai.com`, `POST /v1/responses` | `src/sasguard/prototypes/program0_model.py` (`_submit_request`) |
| Default model ID | `gpt-6-luna` | `ModelSettings.model` default, same file; reused by `program2_model.py` |
| Reasoning effort | `medium` (allowed: low, medium, high) | `ModelSettings.reasoning_effort` |
| Output token cap per request | Program 0: 8,192 (allowed 128 to 32,768); Program 2: 16,384 | `ModelSettings`; `program2_model.py` default settings |
| Provider-side storage | request sets `"store": false`, `"service_tier": "default"` | `_request()` in `program0_model.py` |
| Structured output | JSON schema `generated_python`, strict | `_request()` |
| Response size cap | 2 MiB | `MAX_RESPONSE_BYTES` |
| API timeout | Program 0 default 180 s (max 300); Program 2 default 300 s | `ModelSettings`, `program2_model.py` |
| Transport retries | none | `docs/program-0-model-workflow.md` |

`--model` can override the model ID on both `model-program0` and `model-program2`. The
controller accepts any string up to 128 characters; it does not check the ID against the
provider. Whether `gpt-6-luna` is the intended October model is for the team to confirm.
The recorded experiments in `docs/experiments/` report using this ID, but they do not record
a pricing check, and the saved run directories (ignored by Git) were not inspected here
(unverified).

Decision (fill in):

- Provider: TBD
- Exact model ID: TBD
- Reasoning effort and any other settings: TBD
- Input price per 1M tokens: TBD. Output price per 1M tokens: TBD.
- Pricing checked on `<date>` at `<source URL>`: TBD (must be filled by whoever checks it)
- Are tokens for reasoning billed as output? TBD (confirm on the provider's pricing page)

## 3. Spending and attempt limits

The controllers record token usage as returned by the provider. They do not estimate price
and do not enforce a dollar budget (`docs/program-0-model-workflow.md`,
`docs/program-2-model-workflow.md`). Any dollar cap therefore has to be applied by a person
before the run or by the provider's own billing limit.

| Limit | Decision | Current technical limit in code |
|---|---|---|
| Per-run cap (USD) | TBD | None enforced in code. |
| Total cap for the experiment series (USD) | TBD | None enforced in code. |
| Maximum attempts, Program 0 | TBD | `repair_attempts` default 0, maximum 2, so at most 3 requests. The documented example uses 1 (2 requests). |
| Maximum attempts, Program 2 | TBD | Default 2 repairs (3 requests); `--repair-attempts 0` records only the direct baseline. |
| Maximum attempts, Program 1 | TBD | No Program 1 model controller exists on this branch (no `model-program1` command found). See section 9. |
| Output tokens per request | TBD | 8,192 (Program 0), 16,384 (Program 2), upper bound 32,768. |
| Who pays | TBD | Not recorded anywhere in the repository. |

Note: `configs/cms_2025jul.yaml` has `repair.max_attempts: 3`, and `config.py` allows 0 to 3.
I did not find code that passes this value to the model controllers; they use their own limit
of 2. The team should decide which is authoritative (unverified that the config value is
unused elsewhere).

A rough worst case can be computed once prices are filled in: requests per run times
(input tokens x input price + output cap x output price). Input token counts are not
recorded in this draft; the preview reports byte counts only, which are not token counts.

## 4. Credential handling

- The key is read only from the environment variable `SASGUARD_API_KEY` on the host
  (`program0_model.py`, `program2_model.py`). Both controllers refuse to start without it,
  and both reject keys shorter than 16 characters.
- Enter it interactively, never on a command line and never in a file. The documented
  commands use `Read-Host -AsSecureString` (PowerShell) and `read -s` (zsh), then remove the
  variable after the run.
- Never commit a key. The key is not mounted into the Docker candidate container. Program 2
  additionally checks that the key string does not appear in the request body.
- Who obtains and rotates the key: TBD. Whether a key may be shared between teammates: TBD.
  Whether the key is revoked or rotated after the experiments: TBD.
- Do not paste the key into issues, PRs, run notes or chat.

## 5. Payload allowed to leave the machine

These lists come from the prompt builders. Nothing here is permission to send; the team must
approve each row.

### Program 0 (`program0_prompt.py`, preview docs)

Sent in the initial request (`messages.json`):

- The system prompt (fixed text, template `program0-direct-preview-v1`).
- The full text of `0 - Data and Measure Standardization_2025Jul.sas`, including its
  original comments and paths.
- The full text of `Star_Macros.sas`, including comments and paths.
- The runtime contract: input filename `alldata_2025jul.csv`, the input column names (from
  the CSV header or the SAS dataset metadata), the identifier column and type note, the
  missing-value convention, the three output filenames, and the two environment variable
  paths.

Not sent: hospital rows, trusted SAS output values, human reference Python, helpers,
comparison policies, prior diagnostics. The preview checks only the two SAS files, the
selected input and the protected manifest; it is not a secret scanner.

Sent in a repair request (attempt 1 or 2), in addition to the above:

- The preceding candidate code (model-generated).
- The aggregate diagnostic `program0-aggregate-v2`: per-artifact pass flag, expected and
  actual row counts, expected column names from SAS metadata, missing and mismatched column
  names, counts of missing and extra keys, mismatched-cell and missingness-mismatch counts,
  names of missing or malformed output files, and the fixed comparison policies. Candidate
  column names outside the trusted schema are sent as a count only.

Not sent in repair: provider IDs, reference values, stdout, stderr, exception text.

Open point for approval: expected row counts and column names of the trusted outputs are
derived from SAS reference metadata. The team should confirm these may leave the machine.

### Program 2 (`program2_model.py`, `program2_messages`)

Sent in the initial request:

- The system prompt and the full text of all three SAS programs and `Star_Macros.sas`
  (the programs and macros listed in `configs/cms_2025jul.yaml`).
- A contract with the column names of the six staged input CSVs (five domain outputs and
  `std_data_2025jul_analysis`), role descriptions, the two output filenames, the environment
  paths and the runtime library list.

Not sent: hospital rows, trusted Program 2 outputs, expected hospital counts, human Python.

Repair requests carry aggregate schemas, mismatch counts, missingness counts, affected column
names and fixed policies. Raw row keys, reference values, logs and exception messages are
excluded; an execution failure can expose an allowlisted exception class name only.

### Must never be sent (any program, any mode)

- Trusted SAS output values or rows (any of the ten reference artifacts).
- Reference Python (`reference_python/`, the human Program 0 and Program 1 code).
- Row-level answers, row keys, provider IDs, or row-level diffs.
- Compatibility helper code or manually selected documentation, in a direct baseline.
- API keys, tokens, local paths, earlier validation reports.
- Input hospital rows (not needed by any current prompt).

## 6. Direct-baseline isolation rules

The direct baseline (#48) is a source-only translation measured before any helper or repair.

- Prompt contains only approved SAS source, schema (column names), runtime contract and
  expected output names.
- Attempt 0 is saved exactly as generated; later retries and any human edit are separate,
  labelled records.
- The candidate runs only in the isolated Docker runner. The runner mounts `source/`,
  `input/` and `output/` only, with no network (`docs/program-0-candidate-execution.md`;
  defaults in `execution/runner.py`: 60 s timeout, 512 MB memory, 1 CPU, 64 processes; the
  model controllers pass a 120 s limit for Program 2, per its doc).
- Comparison with trusted SAS outputs happens on the host with the fixed policies. The model
  never decides pass or fail.
- Helper-assisted runs (#69 helpers, #70) are labelled separately and are not the direct
  baseline.
- A failed run is a valid baseline result. If approval is not given, the baseline stays
  blocked; do not substitute a hand translation.

## 7. Required run-record fields

For each experiment, the record must contain (the controllers already write most of these;
the "Gap" column is my reading of the code and is unverified against a real run):

| Field | Where it is recorded today | Gap |
|---|---|---|
| Prompt version and `messages.json` hash | `workflow.json`, `program2-workflow.json` | none found |
| Source and input hashes | `workflow.json` (`project_hashes_lf`, `input_hashes`) | none found |
| Generated-code hash | `attempt.json` `hashes_bytes["candidate.py"]` (Program 0); source hash in Program 2 attempt | none found |
| Request and response hashes | `attempt.json` `hashes_bytes` | none found |
| Model ID and settings (reasoning, max output tokens, repair limit, timeout) | `workflow.json` `settings` | none found |
| Token usage as returned | `attempt.usage` | none found |
| Timestamp | `attempt.timestamp` | none found |
| Cost estimate | not recorded; code states it does not estimate dollars | A person must compute it from usage and the checked prices and add it to the run note. |
| Provider request ID or billing reference | not found in the code | Decide whether to record. |
| Who ran it and who reviewed it | `human_review` is `not_recorded` | Add to the run note. |
| Docker image ID, platform | Program 2 records `image`; exact ID depends on how it is passed | Use the image ID, not the tag. |

## 8. Local no-spend alternative

Ollama models run on the host with no API spend (`docs/local-model-smoke.md`,
`local-model-comparison.md`, `local-model-numeric-reassessment.md`):

- Commands: `local-model-smoke` and `local-model-suite` call `127.0.0.1:11434`; the Docker
  runner still has no network.
- Tried so far: `qwen3:4b` and `qwen3.5:9b-q4_K_M` on one Windows machine (RTX 4070 Laptop,
  8 GiB VRAM, about 32 GiB RAM), context 4,096, max output 1,200 tokens, temperature 0.
  Qwen3.5 9B passed one of four synthetic cases; Qwen3 4B passed none (October 18 comparison).
- Limits: the cases are small synthetic SAS fragments, not Program 0, 1 or 2. A 4,096 token
  context is far smaller than the Program 0 payload would need (byte counts only are
  available; token fit is unverified). No local model has been run on the real Program 0
  payload in the docs I read. Results cannot be compared with the hosted model without
  fixing the same prompt and settings.
- If the team chooses local-only, the decision record should name the model digest, forbid
  remote fallback and downloads during a run, and state machine requirements
  (`program-0-prompt-preview.md` checklist).

## 9. What this decision unblocks

- #48 Program 0 direct baseline (blocked on #46, #47, #44 per its text).
- #68 Program 1 model translation. Note: I found no Program 1 model-generation controller on
  the PR #77 branch, so a code change is also needed (unverified that none exists elsewhere).
- #70 final recorded Program 2 results (new prospective helper-assisted run, fixed settings
  and repair limit before generation).
- #67 asks that the actual model, reasoning setting, payload boundary, usage and budget be
  recorded in #46.
- Downstream: #71 final recorded result and #52, #72 reports use these records.

## 10. Reviewed payload checklist

Before the first paid call, record:

- [ ] `messages.json` SHA-256 reviewed: `TBD`; prompt version `program0-direct-preview-v1`
- [ ] Input format (`csv` or `sas7bdat`) and source hash: `TBD`
- [ ] SAS files, comments and paths inspected for sensitive content: `TBD`
- [ ] Token count measured with the chosen tokenizer: `TBD`
- [ ] Review of Program 2 payload (three SAS programs, macro file, six column lists): `TBD`
- [ ] Evidence that may be published (the repository ignores `reports/runs/`): `TBD`

## 11. Sign-off

| Decision item | Value | Approver | Date | Link to evidence |
|---|---|---|---|---|
| Provider and exact model ID | TBD | | | |
| Pricing source and date | TBD | | | |
| Per-run cap | TBD | | | |
| Total cap | TBD | | | |
| Max attempts per program | TBD | | | |
| Payer | TBD | | | |
| Credential holder | TBD | | | |
| Approved payload, Program 0 | TBD | | | |
| Approved payload, Program 2 | TBD | | | |
| Local-only alternative acceptable? | TBD | | | |
| Decision owner sign-off | | | | |
| Reviewer sign-off | | | | |

Until every row above is filled, no paid call or data upload is authorized.
