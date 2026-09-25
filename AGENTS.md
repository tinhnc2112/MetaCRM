# MetaCRM — AI Engineering Guide

This repository is developed with AI coding agents under human supervision.

## 1. Mandatory Instructions

Before modifying code, read:

- `.ai/instructions.md`

Then load the relevant skills from:

- `.ai/skills/`

Do not start implementation before understanding the existing code,
requirements, architecture, and affected boundaries.

---

## 2. Skill Selection

### Requirements / new features

Read:

- `.ai/skills/requirements-analysis.md`

Clarify requirements and acceptance criteria before implementation when
ambiguity could materially affect correctness or architecture.

### Architecture

Read:

- `.ai/skills/system-design.md`
- `.ai/templates/adr.md`

Architecture changes must consider:

- domain boundaries
- data ownership
- consistency
- transaction boundaries
- failure modes
- security
- observability
- migration
- rollback

Do not introduce microservices or distributed components without evidence
that the current modular monolith cannot satisfy requirements.

### API changes

Read:

- `.ai/skills/api-design.md`
- `.ai/templates/api-spec-checklist.md`

Preserve backward compatibility unless an approved breaking change exists.

### Database / persistence

Read:

- `.ai/skills/data-modeling.md`

Database changes must include:

- invariants
- transaction boundaries
- indexes based on access patterns
- migration strategy
- compatibility
- rollback or roll-forward strategy

Alembic migrations are the source of truth for database schema evolution.

Do not use runtime `create_all()` as a replacement for migrations.

### Security-sensitive changes

Read:

- `.ai/skills/security-review.md`
- `.ai/templates/threat-model.md`

Never expose or commit:

- passwords
- access tokens
- refresh tokens
- API secrets
- private keys
- production PII

Authorization must be enforced server-side.

### Testing

Read:

- `.ai/skills/testing-strategy.md`

Run the relevant tests for changed behavior.

Never claim a test passed unless it was actually executed.

### Deployment / reliability

Read:

- `.ai/skills/devops-reliability.md`

Consider:

- timeout
- retry
- idempotency
- observability
- rollout
- rollback
- recovery

### Code review

Read:

- `.ai/skills/code-review.md`
- `.ai/templates/code-review-report.md`

Prioritize:

1. correctness / data loss / security
2. reliability / concurrency
3. API and schema compatibility
4. performance with evidence
5. maintainability
6. style

---

# 3. MetaCRM Architecture Principles

MetaCRM should remain a modular monolith unless measurable requirements
justify another architecture.

Primary runtime boundaries:

Clients:

- Electron Desktop
- Browser Extension

Server:

- FastAPI backend

Persistence:

- MySQL

External systems are integrations, not owners of core business domains.

Examples:

- Facebook
- shipping carriers
- future sales channels

Core domains should remain channel-independent where practical.

Examples:

- Customers
- Orders
- Products
- Inventory
- Shipping

Facebook-specific concepts belong in the Facebook integration boundary.

Do not duplicate core business logic between:

- backend
- desktop
- browser extension

The backend owns authoritative business rules and persistence.

The database is the durable source of truth.

WebSocket messages are notifications/invalidation signals and must not
be treated as the authoritative state.

---

# 4. Transaction Rules

Business operations spanning multiple aggregates must have an explicit
transaction boundary.

Example:

Confirm Order
  -> validate order
  -> consume inventory
  -> create/update shipment state
  -> append order event

Avoid hidden commits inside lower-level helpers when the caller must
coordinate an atomic business operation.

External events must be designed for duplicate delivery.

Use idempotency where required.

---

# 5. Change Policy

Prefer:

small
-> reviewable
-> testable
-> reversible

changes.

Do not:

- rewrite working modules without evidence
- perform unrelated refactoring
- introduce dependencies without justification
- change architecture merely for stylistic consistency
- silently introduce breaking API/schema changes

---

# 6. Git Workflow

Never push directly to `main`, force-push a shared branch, merge to `main`,
deploy to production, or delete production data without explicit authorization.

For every implementation task:

1. update local `main`
2. create a dedicated branch
3. inspect existing implementation
4. implement the smallest coherent change
5. run relevant verification
6. inspect `git diff`
7. commit
8. push the branch when credentials are already available
9. create a Pull Request when the branch is available remotely

If pushing is unavailable, follow the Work Sandbox Delivery Protocol below.

Do not merge automatically unless explicitly authorized.

Do not commit:

- `.env`
- credentials
- `.venv`
- caches
- test reports
- build artifacts

---

# 7. Autonomous Execution Policy

Autonomous execution is the default. For an authorized task, independently
investigate, implement, run relevant verification, diagnose and fix failures,
review the final diff, update directly affected documentation, commit, and
deliver a feature branch and Pull Request or a patch as described below.

Do not interrupt the user for routine implementation decisions, naming or
internal design details, normal refactoring required by the task, lint/type/test
failures, fixing failures caused by the implementation, adding or updating
tests, directly affected documentation, safe development commands, or
intermediate progress updates.

When something fails: investigate -> determine the root cause -> fix -> verify
again -> continue.

For an assigned roadmap milestone or bounded batch, use the Autonomous
Milestone Runner in `.ai/instructions.md`. Complete focused and regression
verification, security/reliability review, and a separate commit per milestone;
continue through the assigned batch without routine approval. Stop before an
unresolved product decision gate or beyond the assigned batch. Never weaken a
valid failing test to make verification green.

Request human confirmation only when:

- product requirements are materially ambiguous
- destructive or difficult-to-reverse operations are required
- a breaking API, schema, or compatibility change requires approval
- a major architecture decision conflicts with an existing ADR
- credentials or external permissions are required
- a production deployment or action requires approval
- a genuine blocker cannot be safely resolved

An unavailable Docker/MySQL sandbox or GitHub push does not by itself block
other local work. Report verification as PASS, FAIL, SKIPPED, or NOT RUN with
the environment reason; do not claim a check passed unless it ran.

# 8. Work Sandbox Delivery Protocol

Work may run in an isolated repository under `/workspace`. Identify the actual
working tree and do not imply that changes were made to another local checkout.

If GitHub push is unavailable:

1. Do not repeatedly retry authentication or request GitHub passwords, PATs,
   tokens, or other secrets.
2. Continue the task locally in the sandbox and complete the implementation.
3. Run all relevant verification; investigate and fix failures when safely
   possible.
4. Review the final diff and commit the completed work to the task branch.
5. Verify that `origin/main` is the intended patch base.
6. Export commits not present in `origin/main` with
   `git format-patch origin/main..HEAD --stdout` to a downloadable `.patch` file.
   Confirm the patch contains exactly the task commits in order.
7. Report the patch artifact, source branch, source commit(s), verification
   results, and any genuine human decision gates.

Push unavailability alone does not block completion. Do not copy the repository
to another workspace to work around authentication.

---

# 9. Completion Report

Before declaring a task complete, report:

## Changed

Files and behavior changed.

## Architecture

Any architecture/domain/API/data-model changes.

## Verification

Commands/tests actually executed and their results.

## Not Verified

Anything that could not be executed or validated.

## Risks

Known limitations or remaining risks.

## Migration

Required migration or compatibility considerations.

## Rollback

How the change can be safely reverted.

---

# 10. Source of Truth

When documentation conflicts with implementation:

Do not silently choose one.

Identify the conflict and determine which represents the intended
current behavior before making high-risk changes.

Architecture decisions should be recorded under:

`docs/adr/`

Project architecture documentation should live under:

`docs/architecture/`
