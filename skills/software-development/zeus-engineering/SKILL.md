---
name: zeus-engineering
description: Deliver code with baseline-aware verification.
version: 1.0.0
author: Ahmet (@loteiron), ZeusAgent
license: MIT
platforms: [linux, macos, windows]
metadata:
  zeus:
    tags: [coding, verification, regression, delivery]
    category: software-development
    related_skills: [systematic-debugging, requesting-code-review]
---

# Zeus Engineering Skill

Implement a coding task and connect its delivery claims to observed checks on
the actual workspace. Preserve a baseline of existing failures so later results
can distinguish repairs, persistent failures, and regressions.

## When to Use

Use for substantive coding, repairs, refactoring, or a requested end-to-end
engineering pass. Load this skill once for the task; keep the conversation's
system prompt and tool definitions stable while working.

## Prerequisites

Use a local Git workspace, the configured project runtime, and the `terminal`,
`read_file`, `search_files`, and `patch` tools. Follow workspace instructions and
the existing approval policy. Source receipts exclude ignored dependencies,
remote services, and runtime environment changes; verify those separately.

## How to Run

Invoke `/zeus-engineering <task>` or load this skill with `skill_view`.
Use `terminal` with the session's workspace as `workdir` for every check.
Evidence commands inherit the active session identifier; outside an agent
session, consistently pass `--session <name>`.

## Quick Reference

Use these commands through `terminal`, with the intended workspace selected:

```sh
zeus verify --detect-only --json
zeus verify --status --json
zeus verify --capture-baseline --json
```

Detection and status never execute a project recipe. `--status` exits 0 only
when the observed checks are current and passing; exit 1 means incomplete,
failed, stale, or unavailable evidence. Exit 2 indicates invalid arguments.
Baseline capture stores observed outcomes, including failures, without running
checks. It refuses stale, running, and unverified results.

## Procedure

1. Read the task and project instructions. Identify the concrete behavior to
   change, the session workspace, and the checks that can disprove success.
2. Inspect the existing recipe with `zeus verify --detect-only --json`. Read
   its commands before execution. Respect the project's prescribed test runner.
3. Run the relevant existing checks through `terminal`. Record unavailable
   dependencies or services as unavailable; never replace them with a mock and
   call the resulting evidence a production check.
4. Capture the baseline before editing. Keep this baseline through the repair;
   replacing it after introducing a failure would conceal the regression.
5. For a bug, reproduce the reported failure at its real boundary. Add a test
   that fails for that behavior, implement the fix, and rerun that test and the
   relevant neighboring checks. For independent work, use `delegate_task`
   with disjoint file ownership and review its changes before integration.
6. Challenge the implementation with a credible failure case: cancellation,
   a changed workspace, duplicate delivery, malformed input, or loss of an
   external service. Choose cases that follow from the changed behavior.
7. Read `zeus verify --status --json`. Each exact command/cwd/scope has a
   separate result. A targeted pass cannot erase a failed broad suite. Rerun
   every required stale check after the final source edit.
8. Compare outcomes with the baseline: `fixed`, `regression`,
   `persistent_failure`, `unchanged`, `new`, or `incomparable`. Investigate
   regressions. Explain inherited failures without counting them as passes.
9. If the session has a goal, preserve its acceptance contract and required
   quality gates. Completion requires current passing gate receipts. Do not
   edit goal databases or drop a gate to bypass a failing check.
10. Deliver the changed behavior, the checks actually run and their scope,
    and any remaining concrete limitation. Desktop users can inspect the same
    results and baseline in the composer's **Evidence** view.

## Pitfalls

- A successful command only proves what that command tested.
- A check still running has no final verdict. A lost completion stays unknown.
- An external editor can invalidate results without an agent file-tool event.
- Source changes during a check invalidate its freshness even when exit is 0.
- Non-Git, remote, or unsupported workspaces cannot receive local source proof.
- Do not initialize Git, delete user data, install dependencies, or change
  approval settings merely to obtain a passing evidence indicator.

## Verification

The final report must retain failing and unavailable checks, show the correct
workspace and scope, and explain material baseline changes. Never claim a
benchmark ranking, exhaustive correctness, or successful live integration
without an actual measurement of that claim.
