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

Never push directly to `main`.

For every implementation task:

1. update local `main`
2. create a dedicated branch
3. inspect existing implementation
4. implement the smallest coherent change
5. run relevant verification
6. inspect `git diff`
7. commit
8. push the branch
9. create a Pull Request

Do not merge automatically unless explicitly authorized.

Do not commit:

- `.env`
- credentials
- `.venv`
- caches
- test reports
- build artifacts

---

# 7. Completion Report

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

# 8. Source of Truth

When documentation conflicts with implementation:

Do not silently choose one.

Identify the conflict and determine which represents the intended
current behavior before making high-risk changes.

Architecture decisions should be recorded under:

`docs/adr/`

Project architecture documentation should live under:

`docs/architecture/`