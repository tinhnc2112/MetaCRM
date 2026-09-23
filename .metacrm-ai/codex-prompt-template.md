# MetaCRM Codex Prompt Template

Use this template for every Codex implementation task.

---

## TASK

[Milestone ID] — [Task Name]

Example:

M24 — Product / Inventory Foundation Audit

---

## CONTEXT

You are working on the MetaCRM project.

MetaCRM is a CRM and sales operations system connected to Facebook comment/inbox workflows, customer management, order management, product/inventory foundation, and reporting.

Development follows the MetaCRM AI Development Protocol.

Important workflow rule:

- Codex writes and modifies code.
- Human runs build, tests, migrations, git diff, and UI verification.
- Codex must not claim verification passed unless logs are provided by the human.
- Do not perform unrelated refactors.
- Do not make silent database schema changes.

Current milestone status:

[Paste current status from milestone-log.md]

---

## GOAL

[Describe the exact goal of this task.]

Example:

Audit the existing product and inventory foundation in MetaCRM and identify what already exists, what is missing, and what must be implemented next.

---

## FILES TO INSPECT FIRST

Inspect relevant files before editing.

Start with:

- [file/path/1]
- [file/path/2]
- [file/path/3]

If the exact files are unknown, search the repository for:

- product
- inventory
- stock
- sku
- order item
- customer
- pricing
- migration
- schema
- API route
- service

---

## REQUIRED CHANGES

Implement only the required changes below:

1. [Required change 1]
2. [Required change 2]
3. [Required change 3]

If this is an audit-only task, do not modify code unless necessary. Instead, produce a structured audit report.

---

## DO NOT CHANGE

Do not:

- Refactor unrelated modules.
- Rename existing public APIs.
- Change database schema unless explicitly required.
- Add dependencies unless absolutely necessary.
- Modify unrelated tests.
- Change formatting across unrelated files.
- Delete existing functionality.
- Claim tests passed without human-provided logs.

---

## ACCEPTANCE CRITERIA

This task is complete when:

1. [Criterion 1]
2. [Criterion 2]
3. [Criterion 3]

For code tasks, include:

- No obvious TypeScript/Python import errors.
- Existing behavior is preserved.
- New behavior is covered by tests where practical.
- Risky changes are documented.

For audit tasks, include:

- Existing implementation is mapped.
- Missing pieces are identified.
- Recommended next tasks are listed.
- No code changes unless explicitly requested.

---

## HUMAN VERIFICATION REQUIRED

After Codex finishes, the human operator must run the relevant commands.

General:

```bash
git status
git diff --stat
git diff