# Issues and project board

The team uses GitHub issues to define work and the
[Abt-Global-1A Project Board](https://github.com/orgs/Break-Through-Tech/projects/58) to track its
progress. Issues explain what must be delivered. The project board shows when it will be done, who
owns it, and its current state.

## What is a GitHub issue?

A GitHub issue is a small, reviewable unit of work. It may describe a feature, analysis task, bug,
test, documentation change, or technical question. An issue is not complete merely because code
was written. Its acceptance criteria must be satisfied and reviewed.

Each project issue should contain:

- a specific title with a workstream prefix;
- an objective that explains the desired outcome;
- a task checklist or bounded scope;
- measurable acceptance criteria;
- one or more assignees;
- a milestone, priority, size, and relevant labels;
- dependencies or blockers when applicable.

Example title:

```text
[Data] Implement canonical input and reference-data loaders
```

## Workstream prefixes and labels

| Workstream | Typical work |
|---|---|
| Foundation | Docker, packaging, tooling, and CI |
| Data | Loading, identifiers, schemas, and artifact inventory |
| SAS Analysis | Program interpretation and SAS semantics |
| Validation | Artifact comparison and discrepancy reporting |
| Testing | Unit, regression, and golden tests |
| Documentation | Setup, workflow, architecture, and reports |

Priority labels mean:

| Label | Meaning |
|---|---|
| `priority-p0` | Critical work that blocks other milestone tasks |
| `priority-p1` | High-priority milestone work |
| `priority-p2` | Normal-priority work |
| `priority-p3` | Optional stretch work |

Size estimates are relative planning aids:

| Size | Meaning |
|---|---|
| XS | Very small and isolated |
| S | Contained task |
| M | Moderate implementation or analysis |
| L | Large task with several components or uncertainty |
| XL | Too large unless there is a clear reason not to split it |

## Project board statuses

### Backlog

The team has accepted the task, but it is not ready to begin. It may depend on another issue or
need further definition.

### Ready

The issue has a clear owner, sufficient context, and no unresolved dependency. The assignee may
start it.

### In progress

The assignee is actively working on the issue. The issue should contain a recent status comment.
Avoid keeping several issues in progress without completing or pausing one.

### In review

A pull request or reviewable document is available. At least one teammate other than the author
must review it.

### Done

The acceptance criteria are satisfied, required checks pass, the work has been approved and
merged, and the issue is closed.

If work is blocked and the board does not have a `Blocked` status, add a clear issue comment and a
`blocked` label. Include what is blocked, why, and the person or decision needed to continue.

## Starting an issue

1. Select an issue assigned to you from `Ready`.
2. Confirm that its dependencies and acceptance criteria are clear.
3. Move it to `In progress`.
4. Add a starting comment.
5. Create a branch from the latest `main` using the issue number.

Example starting comment:

```text
Starting this issue today. I will first implement CSV and SAS binary loading, then add tests for
provider identifiers and missing values. I will post any schema questions here.
```

Example branch:

```bash
git switch main
git pull --ff-only
git switch -c feat/issue-5-data-loaders
```

## Updating an issue

Add a comment when:

- work begins;
- an important technical decision is made;
- the scope or acceptance criteria need clarification;
- a blocker appears;
- a pull request is opened;
- verification is complete.

Useful progress comment:

```text
Progress update: CSV loading and provider-ID preservation are implemented. SAS binary loading is
next. The current tests cover leading zeros and missing numeric values.
```

Useful blocker comment:

```text
Blocked: the CSV and SAS binary artifacts use different column casing. I need confirmation that
uppercase canonical names should be used internally before completing the schema tests.
```

Do not use vague comments such as "working on it" when a concrete update is available.

## Opening and reviewing a pull request

Before opening a pull request:

1. Review the issue acceptance criteria.
2. Run the required checks in Docker.
3. Review your own diff for accidental data or unrelated changes.
4. Push the issue branch and open a pull request.
5. Link the issue with `Closes #N` or `Refs #N`.
6. Move the board item to `In review`.

At least one teammate other than the author must approve the pull request. Reviewers should check
correctness, tests, readability, data integrity, and whether the acceptance criteria are actually
met. Authors should respond to every comment and request another review after meaningful changes.

## Closing an issue

An issue may be closed after:

- the linked pull request is approved and merged;
- CI passes;
- all acceptance criteria are checked;
- documentation is updated where necessary;
- no unresolved review conversation remains.

Move the item to `Done` after confirming these conditions. Do not close an issue solely because a
draft implementation exists.

## Weekly board routine

At the beginning of each team meeting:

1. Review milestone progress and the due date.
2. Confirm that every `In progress` item has an owner and recent update.
3. Review blockers and assign a next action.
4. Move dependency-free work from `Backlog` to `Ready`.
5. Confirm who will review each item in `In review`.
6. Check whether any large issue should be split.
7. Verify that completed work is linked to an issue and pull request.

At the end of the meeting, every active teammate should know their current issue, next action, and
review responsibility.

## Relationship between issues, branches, and pull requests

```text
Issue defines the outcome
    -> project board tracks its state
    -> branch contains the implementation
    -> pull request presents the change for review
    -> CI checks the change
    -> teammate approves the change
    -> merge closes the issue
    -> board item moves to Done
```

See [Contributing](../CONTRIBUTING.md) for branch naming, code standards, review rules, and required
verification commands.
