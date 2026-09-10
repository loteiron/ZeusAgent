## Problem and change

<!-- Explain the observable defect or requested behavior. Link an issue in this repository. -->

## Verification

<!-- TDD is a work method, not an application feature. Include actual results; do not claim unrun checks. -->

- Red reproduction (command + exit status):
- Green regression (same test + exit status):
- Neighboring/broader checks:
- Failed, skipped or unrun checks and why:
- Actual OS / Python / Node versions:

## Compatibility and risk

<!-- Mention data persistence, approvals, provider contracts, platform impact and safe rollback when relevant. -->

## Review checklist

- [ ] I read this repository's CONTRIBUTING.md, SECURITY.md and relevant AGENTS.md.
- [ ] The change is scoped; unrelated user edits are preserved.
- [ ] Python tests use `bash scripts/run_tests.sh` and results disclose retries.
- [ ] A bug fix includes a behavioral regression, not a source-text change detector.
- [ ] I did not weaken security checks or fake the host OS to obtain a green result.
- [ ] Dependency changes retain bounds/pins and update the corresponding lockfile.
- [ ] Logs/screenshots are reviewed and redacted; no credentials or conversations are included.
- [ ] I have stated which integrations/platforms were actually exercised.
- [ ] Public source and private handoff evidence remain separate.

## Evidence

<!-- Only minimal redacted excerpts or screenshots. Do not require an external diagnostic upload. -->
