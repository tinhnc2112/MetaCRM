# AI CODING RULES — Codex / Claude Code

## Mandatory reading
Read all numbered design files before coding and inspect the current repository at baseline commit.

## Preserve
Do not migrate FastAPI, SQLAlchemy, Alembic, PostgreSQL, React/Vite, Electron, React Query, Zustand or WebSocket without explicit approval.

## Architecture
- Incremental refactor, not rewrite.
- No Facebook-specific core domain.
- No J&T-specific core domain.
- No FacebookOrder/PosOrder.
- One OrderService.
- Provider DTOs stay inside adapters.

## Database
- Every schema change has Alembic migration.
- Money = Decimal/Numeric.
- Foreign keys and unique constraints are explicit.
- Never silently destroy existing data.
- Backfills are repeatable/idempotent.

## Business integrity
- Stock mutations use transactions and row locks.
- Order transitions are explicit and validated.
- Historical price/cost snapshots are immutable.
- Webhooks are idempotent.

## API
- Pydantic schemas are explicit.
- Core endpoints are provider-neutral.
- Never expose secrets.

## Frontend
- React Query for server state.
- Zustand only for appropriate local/global UI state.
- Do not duplicate server state unnecessarily.
- UI permission checks never replace backend authorization.

## Testing
Every milestone needs unit/integration tests and regression tests.
Do not mark a task complete with TODO placeholders for required business logic.

## Git
Use small logical commits.
Commit messages should reference milestone/task IDs.
Do not mix unrelated refactors with feature work.

## TASK EXECUTION SAFETY / CONTEXT BUDGET PROTOCOL

Before starting any task, the AI coding agent MUST:

1. Read the relevant Source of Truth documents and inspect the current repository state.
2. Break the task into explicit subtasks.
3. Estimate whether the available context/tool budget is sufficient to:
   - inspect the required files,
   - implement the task,
   - run verification,
   - and provide a completion report.
4. If the agent believes the remaining context/tool budget may be insufficient to safely finish the entire task, DO NOT start implementation.
5. Instead, stop and report:
   - what has been inspected,
   - what has been completed,
   - what remains,
   - the recommended safe stopping point,
   - and exactly what should be continued in the next session.

### During execution

The agent MUST NOT start a large implementation if it is already close to its context/tool limit.

The agent should work in small, independently verifiable checkpoints.

After each major checkpoint, the agent should be able to leave the repository in a coherent state.

Preferred checkpoint order:

1. Analysis / repository inspection
2. Backend models/schema
3. Migration
4. Backend services/API
5. Tests
6. Desktop/UI
7. Verification
8. Final report

If context/tool budget becomes constrained during execution:

- STOP at the nearest completed checkpoint.
- Do NOT begin another major subsystem.
- Do NOT leave half-written files if avoidable.
- Do NOT claim the task is complete.
- Report exactly which checkpoint was completed.
- Report all remaining subtasks.
- Report files changed/created.
- Report tests/builds already executed.
- Provide a concise continuation instruction for the next session.

### Commit policy

The AI agent MUST NOT commit or push unless explicitly instructed by the user.

The user performs commits manually.

### Completion requirement

A task is considered COMPLETE only when:

- implementation is complete,
- required migrations are complete,
- tests pass,
- required builds pass,
- git diff --check passes,
- and the final verification report has been produced.

If any of these are incomplete, report the task as PARTIAL rather than COMPLETE.