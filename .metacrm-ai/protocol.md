# MetaCRM AI Development Protocol

## Purpose

This protocol defines how MetaCRM is developed with ChatGPT, Codex, and the human operator.

MetaCRM development must be controlled, milestone-based, and verifiable.

## Roles

### Human Operator

The human operator is responsible for:

- Running the app locally.
- Running backend tests.
- Running frontend or extension builds.
- Running database migrations manually.
- Running git status and git diff.
- Verifying the UI manually.
- Sending logs, screenshots, errors, and diffs back to ChatGPT.

The human operator is the only source of truth for whether something actually runs successfully.

### ChatGPT / Planner

ChatGPT is responsible for:

- Designing milestones.
- Breaking milestones into Codex tasks.
- Writing precise Codex prompts.
- Reviewing Codex summaries.
- Reviewing terminal logs.
- Reviewing git diff and git status output.
- Deciding PASS, FAIL, or NEEDS FIX based on evidence.
- Creating the next Codex task.

ChatGPT must not assume tests passed unless the human operator provides logs.

### Codex

Codex is responsible for:

- Reading project code.
- Editing code.
- Creating or modifying files.
- Proposing implementation details.
- Reporting changed files.
- Reporting risks and commands the human should run.

Codex must not claim that build, tests, migrations, or UI verification passed unless the human operator provides logs.

## Core Rules

1. Codex may write or modify code.
2. Codex may inspect project files.
3. Codex may propose implementation design.
4. Codex must not perform final verification.
5. The human operator must run build, tests, migrations, git diff, and UI checks.
6. ChatGPT reviews the human-provided verification result.
7. Every task must have clear acceptance criteria.
8. Every task must include a human verification checklist.
9. No unrelated refactors.
10. No silent schema changes.
11. No database migration unless explicitly required.
12. No destructive changes without clear rollback notes.
13. No feature is marked PASS without evidence.
14. If UI is not manually verified, status must say: Live UI NOT VERIFIED.
15. If tests are not run, status must say: Tests NOT RUN.
16. If build is not run, status must say: Build NOT RUN.

## Standard Task Flow

### Step 1 — Planner creates task

ChatGPT creates a Codex prompt with:

- Task name
- Context
- Goal
- Files to inspect first
- Required changes
- Do not change
- Acceptance criteria
- Human verification commands
- Expected Codex output

### Step 2 — Codex implements

Codex reads files and edits code.

Codex must return:

- Summary
- Files changed
- Important implementation notes
- Migration required or not
- Suggested commands for human verification
- Known risks

### Step 3 — Human verifies

Human runs:

- Backend test command
- Frontend or extension build command
- Migration command, if needed
- Git status
- Git diff --stat
- Git diff
- Manual UI verification, if applicable

### Step 4 — ChatGPT reviews

ChatGPT reviews the evidence and returns one of:

- PASS
- FAIL
- NEEDS FIX
- NEEDS MANUAL UI VERIFICATION
- NEEDS MORE LOGS

### Step 5 — Milestone log updated

The result is added to:

.metacrm-ai/milestone-log.md

## Status Definitions

### PASS

A task can be marked PASS only if:

- Required implementation is complete.
- Required tests or builds passed, or missing verification is explicitly stated.
- No obvious unrelated changes are present.
- Acceptance criteria are satisfied.
- Risks are documented.

### FAIL

A task is FAIL if:

- Build fails.
- Tests fail.
- Required behavior is missing.
- Migration fails.
- App cannot start.
- Feature creates serious regression.

### NEEDS FIX

A task is NEEDS FIX if:

- Most implementation is present.
- One or more issues remain.
- A follow-up Codex fix prompt is needed.

### NEEDS MANUAL UI VERIFICATION

Use this when code/build looks acceptable but the UI has not been checked by the human operator.

### NEEDS MORE LOGS

Use this when the human operator has not provided enough information to judge.

## Verification Commands

Use the commands appropriate to the actual MetaCRM project structure.

Common commands:

```bash
git status
git diff --stat
git diff