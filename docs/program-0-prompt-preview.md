# Preview the Program 0 baseline prompt

This command prepares a local payload for review under #46 and #48. It does not call a
model, contact Ollama or an API, download anything, execute candidate code, or compare outputs.
It is not Attempt 0, and it does not approve a payload or choose a model.

## Prepare and inspect

From the repository root with the host environment active, use the same command in Windows
PowerShell and macOS zsh:

```text
python -m sasguard.cli preview-program0-prompt
```

Choose the same source input as the planned execution. The default `--input-format csv`
uses the supplied CSV header and records that CSV's hash. For the integration's full-precision
SAS-input mode, use:

```text
python -m sasguard.cli preview-program0-prompt --input-format sas7bdat
```

SAS mode reads column names with `metadataonly=True` and hashes the source input binary.
It does not export or include hospital rows. Column names are uppercased to match the runner's
canonical CSV staging. The execution contract still names `alldata_2025jul.csv` because the
runner supplies a CSV to candidate code in either mode. The preview record names the selected
original input and its hash; the runner separately records its staged CSV hash after export.
Neither mode reads trusted SAS output files.

Without activation, use `.\.venv\Scripts\python.exe` on Windows or `./.venv/bin/python` on macOS.
Docker and Ollama do not need to be running. A successful command exits with code 0 and prints
the new local directory. Invalid inputs or an unsafe destination produce exit code 2.

The command creates an ignored `reports/runs/program0-prompt-<UUID>/` directory with:

| File | Contents |
|---|---|
| `messages.json` | The proposed system and user messages. No model-specific request settings. |
| `prompt.txt` | A readable copy of those messages. |
| `contract.json` | The shared candidate execution contract. |
| `preview.json` | Prompt version, selected source/input hashes, exact payload-file hashes, byte count, and pending/not-run states. |

The frozen template is `program0-direct-preview-v1`. Source files use the repository's portable
LF hash convention. Payload-file hashes cover the exact saved UTF-8 bytes. The model messages
use the selected input's column names. The legacy `input_hashes_lf` field follows the shared
hashing convention: portable LF for CSV, raw bytes for a SAS binary.
Messages are deterministic for the same source and input header; preview timestamps and directory names
are not. Byte counts are not token counts and do not establish that a selected model's context
is large enough. That check belongs to the later model decision and generation workflow.

You can choose `--output-directory reports/runs/my-prompt-review`. The directory must be new
and directly under `reports/runs/`. Previous previews are not overwritten. A redirected run
store, including a Windows junction, is rejected.

## What enters the payload

The payload contains exactly the original Program 0 SAS source, the original `Star_Macros.sas`
dependency, and the runtime contract with CSV column names. The entire supplied macro file is
included because Program 0 includes it. The preview does not expand arbitrary includes or
collect files mentioned in SAS comments. The contract is built by the same function used to
stage Program 0 candidates, so filenames and runtime paths agree with #55.

The builder reads only those two SAS files, the selected source input, and the protected manifest.
It checks their selected hashes against that local baseline. It hashes the input locally
but puts only its column names into the model messages. No hospital rows, trusted SAS output values,
Python reference translation, tested compatibility helpers, comparison policies, or prior
diagnostics enter the payload. It does not read the gold output files. This selected-file check
does not replace `sasguard verify-integrity` for all 29 protected files.

The SAS files retain original comments and paths. Column names and source comments can also
contain information that needs review. This is a fixed-input builder, not a general secret
scanner or a permission check. Keep the preview local until the team approves its contents.

## What remains blocked

`payload_approval` and `model_selection` are `pending`. Generation, execution, and validation
are `not_run`; human review is `not_recorded`. The CLI has no option to send the payload or
start a model. The team still needs to record the model, settings, hardware/context limits,
payload rules, and attempt limits in #46 before running the baseline in #48.

A later generation controller must preserve the approved messages, exact model identity and
settings, raw response, untouched Attempt 0 code, usage/cost metadata, and their hashes. It must
execute candidate code only through the isolated runner and use #44's validator on the host.
This preview does not create those records or imply that the baseline is complete.

## Check a saved preview

Before reviewing or using a preview, check the directory printed by the preparation command:

```text
python -m sasguard.cli check-program0-prompt reports/runs/program0-prompt-<UUID>
```

The checker is read-only and offline. It uses the input format recorded in the preview;
older previews without that field retain CSV mode. It checks saved payload hashes and byte count,
then rebuilds the expected messages from the current fixed template, shared contract, selected
SAS sources, and input column names. Changing the payload and replacing its recorded hash is not enough
to pass. Extra files, inconsistent snapshot records, and altered approval or execution claims
are rejected or flagged. An edited timestamp is not independently authenticated.

Exit code 0 means the payload matches those local inputs. Exit code 1 means the saved payload
or its record differs. Exit code 2 means the directory or record could not be checked safely,
or the current selected inputs no longer match the local protected baseline. A matching result
does not record human review, approve transmission, or establish SAS parity. This is not a
signed attestation and cannot detect coordinated changes to the trusted builder and baseline.

## Review checklist for #46

Record these decisions in #46 without marking the preview itself as an approved experiment:

* Identify the reviewed `messages.json` SHA-256 and prompt version. If the payload changes,
  review the new digest rather than silently editing an existing attempt.
* Record the selected input format and source hash. The preview's source must agree with the
  later runner invocation. A matching payload hash alone does not identify the execution input.
* Confirm that the two supplied SAS files and the input column names may enter the selected
  model runtime. Inspect original source comments and paths before any external transfer.
* Name the exact model, local model digest or hosted provider, machine requirements, context
  budget, and output limit. Measure tokens with the chosen tokenizer rather than using bytes.
* Record generation settings, attempt limits, who will run the experiment, and any paid-use cap.
  A local-only decision should explicitly prohibit remote fallback and downloads during a run.
* Keep trusted output values, human reference Python, helpers, and prior diagnostic feedback out
  of the direct baseline. Preserve Attempt 0 unchanged and record later retries separately.
* Confirm who will review the run and what evidence may be published. A PR approval does not
  automatically approve the payload or a specific generated result.

The checker deliberately has no approval switch. Team decisions remain separate from software
integrity checks. The real validator and baseline generation controller are still required.
