# Program 2 Luna baseline

## Setup

Translated Program 2 using `gpt-6-luna`, medium reasoning, a maximum of 16,384 output
tokens per request, and two permitted automatic repairs. The initial prompt contained
the original SAS programs and macro dependency, input headers, and the runtime contract.
It contained no hospital rows, target values, expected hospital counts, human Python
implementations, or manually written clustering helpers.

The six execution inputs came from the verified Python chain: the automatically repaired
Program 0 candidate followed by the human Program 1 reference. Target SAS references
remained on the host. Policies were fixed before generation; categorical decisions,
counts, and stars require exact matches.

## Recorded results

| Attempt | Execution | Star artifact | National averages |
|---|---|---|---|
| 0 | Succeeded | Failed: 35,055 cell mismatches | Failed: four missing-value mismatches |
| 1 | Succeeded | Failed: two STAR cells mismatched | Passed |
| 2 | Succeeded | Failed: two STAR cells mismatched | Passed |

The best candidate matches schemas, provider keys, missingness, domain scores, fixed
and redistributed weights, summary scores, measure counts, eligibility, and peer groups
under the fixed policies. Its copied domain scores exactly match the actual input.
Two star assignments remain incorrect. The overall verdict is FAILED.

There are 4,566 hospital rows, including 2,891 rated hospitals in the reference. Matching
most ratings does not establish a verified star-rating migration. Both remaining
assignments must pass without relaxing the exact star comparison.

Every generation, failed candidate, request, response, diagnostic, source/input hash,
Docker result, and artifact comparison remains saved locally. No generated candidate
was manually edited.

## Replay with SAS intermediates

Executed the final candidate unchanged with full-precision CSV exports of the supplied
SAS intermediate datasets. This required no model calls. National averages still passed,
and the same two STAR mismatches remained. Exact copied-input checks also passed.
The observed difference therefore persists independently of upstream Python rounding.

## Documentation-assisted follow-up

After the three-request automatic experiment ended, made one separate request using
human-selected generic official SAS documentation. The notes concern percentile
definition 5 and the distance restriction and signed output identifiers associated with
STRICT. Sources are recorded in [SAS semantics references](../program-2-sas-semantics.md).
No hospital-specific values or expected star assignments were supplied.

This follow-up executed successfully and kept national averages and copied values
matching, but regressed to 2,661 STAR mismatches. Inspection found inconsistent zero-
and one-based cluster identifiers in the generated helper. It is a separate failed
documentation-assisted experiment, not an automatic repair success or a replacement
for the best source-only candidate.

## Remaining work

Develop isolated synthetic probes for FASTCLUS seed selection, percentile definitions,
STRICT distance handling, and signed cluster identifier conversion. Resolve those
semantics from authoritative documentation and, when available, SAS runtime evidence
before repeating a prospective translation experiment. Do not hardcode the two hospital
outcomes, select a tolerance for stars, or treat a generic KMeans implementation as SAS.

The Program 2 runner, fixed validator, aggregate feedback, and regression controls are
implemented. They demonstrate rejection of executable but incorrect translations.
Full-pipeline behavioral parity and client release approval remain unverified.
