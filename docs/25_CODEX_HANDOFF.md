# Codex / Claude Code Handoff

## Instruction

You are implementing MetaCRM according to this design pack.

Before changing code:
1. Read every numbered design document in this folder.
2. Inspect the repository and current implementation.
3. Inspect git history and current tests.
4. Compare current code against the acceptance criteria.
5. Produce an internal implementation plan based on the prescribed DEVELOPMENT_ORDER.

## Important
Do not assume the current repository matches this design.
Do not blindly rewrite existing code.
Preserve working features.
Use migrations for schema changes.
Use tests to prove behavior.

## Execution
Implement one milestone at a time in the exact order in `17_DEVELOPMENT_ORDER.md`.

For each milestone:
- inspect current code
- implement smallest coherent change
- write migration
- write tests
- run regression suite
- run backend checks
- run frontend build/tests
- report changed files and verification

Do not proceed around a failed gate.

## Provider constraints
Facebook and J&T are adapters.
J&T real API must wait for official documentation/credentials.
Use MockJTAdapter for development.

## Final release condition
All acceptance criteria in `22_ACCEPTANCE_CRITERIA.md` must pass.
