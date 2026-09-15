# Project Experience

Project Experience connects Zeus's verification ledger to durable, project-specific
learning. It records observations from actual tool execution; it does not train
model weights or certify a model-generated explanation.

## A complete learning cycle

1. A classified check fails. Zeus stores the command identity, diagnostic excerpt,
   session, scope, timestamp, source revision and content fingerprint.
2. The agent makes a change and runs the same check. A recovery requires stable
   source during both checks, changed source between them, and a passing run that
   started after the failure completed. Different commands, targets or sessions
   cannot supply the initial recovery evidence.
3. The existing background memory/skill reviewer can attach a proposed cause,
   repair, failed approach and applicability conditions automatically. Its annotations
   are hypotheses; they cannot change check results. Late reviews cannot overwrite
   newer verification evidence or a manually revised explanation.
4. Before a relevant request, Zeus recalls up to three project experiences in the
   current user message's API context. A local `read_file` and repeated failed check
   can also recall related evidence. Historical messages and the cached system prompt
   remain unchanged. Retrieval itself makes no model call.
5. Changed source invalidates the previous result's freshness. A later session may
   re-run a previously repaired check to refresh the observed source identity.
   This does not count as another recovery unless another failure/repair pair was
   actually observed.

## Quiet learning during normal use

No learning command is required. After three meaningful completed turns in a
conversation, Zeus requests its existing background memory/skill review. Explicit
corrections such as "from now on" or "bundan sonra" request it after that response.
This is turn-based, not a fixed number of minutes. Short greetings and acknowledgements
do not advance this new trigger. Existing memory/skill triggers remain available;
local-model idle scheduling, cancellation and review cost controls still apply.

The reviewer can save explicit durable preferences, consolidate memory and create or
improve eligible managed skills. It is instructed to merge duplicates, preserve scope,
replace superseded preferences and record procedure prerequisites and verification
steps. Protected skills and SOUL are not rewritten by this review. No change is the
correct outcome when there is no useful new lesson. Review summaries stay out of chat
by default; operational failures remain in logs.

Memory, skills and verification experiences persist in the active profile. Later
sessions can load those memories and skills; project experiences are recalled only
inside the same resolved Git project. This improves the context and procedures
available to the model, rather than retraining its weights. Selecting a skill and
interpreting a lesson still depend on the model. A successful test is evidence for
that test, not proof that a proposed solution is universally correct.

## Outcome states

| State | Meaning |
| --- | --- |
| `unresolved` | A failure has been observed without a corresponding recovery. |
| `recovered` | The same check passed after an observed failure on different, stable source. |
| `unstable` | Failure and success occurred on identical source; runtime changes or flakiness may explain it. |
| `unverified` | Missing source identity, changed source during execution, or overlapping execution prevents a recovery claim. |
| `contradicted` | The check failed again on the source fingerprint associated with a previous recovery. |

Source freshness is separate from outcome: `current`, `stale`, or `unknown`.
Recovery counts describe distinct observed pairs, not a probability of correctness.
A revalidation does not inflate them. Diagnostic grouping ignores ordinary progress
and duration noise when an error identity is available; it does not assert that two
errors have the same cause.

## Inspect and control

`zeus experience list`, `status`, `recall <words>`, and `show <id>` inspect the
current project. Add `--root <directory>` and `--json` for another local project
or structured output. IDs are scoped to the current profile and resolved project.

`zeus experience explain <id> --cause <hypothesis> --resolution <repair>` adds
an explanation. Optional `--avoid` and `--conditions` preserve failed approaches
and applicability constraints. `zeus experience forget <id>` deletes the case
and its copied observations; the original verification history remains separate.
An independently observed future failure may create a new case.

`/experience` shares the read-only command implementation across classic CLI,
Desktop/TUI chat and Telegram. Desktop/TUI takes its workspace and profile from the
live session. Telegram inspection is limited to explicitly authorized owners in
private chats and the selected profile's `terminal.cwd`. Group chats and allow-all
access do not grant access to project experience. Chat commands cannot change the
root, edit explanations or delete records.

## Configuration and storage

```yaml
experience:
  enabled: true
  recall_enabled: true
  automatic_review: true
  quiet: true
  review_interval: 3
  max_cases: 500
  observations_per_case: 24
```

Automatic capture, recall and experience consolidation can be disabled independently.
`automatic_review: false` disables the new conversational trigger and pre-turn
experience recall/consolidation; the existing memory/skill review settings still apply.
`quiet: false` restores existing review notifications. Existing records remain
inspectable. File-read recall respects the agent's `skip_memory` setting. At most
32 distinct experiences are recalled through file reads per agent conversation;
each reminder is bounded and a case is not repeatedly injected. Background check
completion records experience durably; use `/experience` to inspect it.

The profile's `experience.db` uses short-lived SQLite transactions, the existing
safe journal-mode policy, and private file permissions where supported. Replayed
receipts are ignored while retained. The oldest cases are pruned at the configured
bound; each retained case keeps its original failure and recent observations.
Default limits can be adjusted within bounded ranges. Full backups include the
database, and the normal pre-update snapshot includes it alongside verification.

Stored excerpts and explanations use forced credential redaction and remove hidden
control characters. They remain **untrusted historical data**, not executable
instructions. Redaction is heuristic; avoid putting credentials in explanations.
Experience does not upload observations to another service. A recalled excerpt
becomes part of the next request to the model provider configured for that session,
like other tool output.

## Practical limits

- The automatic evidence path covers classified coding checks and `zeus verify`.
  It does not automatically learn from every chat message, external action or
  provider failure, and does not invent lessons from old conversation transcripts.
- Source identity describes local Git contents. Installed dependencies, ignored
  files, secrets, runtime configuration and remote services are outside it.
  Remote terminal backends do not receive a claim about local source verification.
- Passing a check proves that observed command's exit outcome and scope. It does
  not prove full test coverage, absence of flaky behavior, or a causal explanation.
- Recovery may include test changes; the system does not certify that a test was
  not weakened. Keep independent acceptance checks for important deliveries.
- Matching uses project boundaries, diagnostic identities, file names and lexical
  relevance. It can miss paraphrases; inspect with `recall` or `show` when needed.
- A failed experience write does not turn a completed check into a failed command.
  The original verification receipt remains available and a warning is logged.
