# ADR-0001: Database-backed scheduled Page publishing

- **Status:** Accepted for M11
- **Date:** 2026-09-29
- **Decision owners:** MetaCRM maintainers

## Context

Google Sheets is the content planning surface. A due-time read from Sheets would lose schedules during a Sheets outage and could publish changed content without review. A Graph publish request has no application idempotency key, so a timeout can leave its outcome unknown.

## Decision Drivers

- Survive Sheets outages after import.
- Avoid duplicate Page posts across worker restarts and concurrent workers.
- Keep the backend and MySQL authoritative for execution state.
- Avoid new distributed infrastructure.

## Considered Options

1. Read Sheets when each row is due.
2. Import to MySQL, then claim with InnoDB row locks in a dedicated worker.
3. Add a separate queue/broker.

## Decision

Choose option 2. Admin-triggered sync imports the seven-column Sheet into `scheduled_posts`, keyed by a SHA-256 digest of source, spreadsheet, worksheet, and external ID. A dedicated process claims due rows using `FOR UPDATE SKIP LOCKED`, commits `PUBLISHING`, then calls Graph outside the DB transaction. The worker stores provider outcome before attempting Sheet write-back. Stale claims and ambiguous transport outcomes become `UNCERTAIN` and require manual verification; they never auto-resend.

## Trade-off Matrix

| Option | Benefit | Risk | Operations | Reversibility |
|---|---|---|---|---|
| Due-time Sheets read | Few tables | Sheets outage loses due posts; mutable payload | Simple | Easy |
| MySQL claim | Durable snapshot; no new service | Separate worker and recovery flow | Moderate | Stop worker and retain data |
| Broker | Higher throughput | More moving parts and duplicate handling | High | Harder |

## Consequences

- MySQL is the source of truth for schedule and outcome. Sheet status is eventually consistent.
- At-most-one claim is expected on InnoDB; exactly-once external publication cannot be promised after network ambiguity.
- Admin must review `UNCERTAIN` against the Page before marking published or verified absent.
- A Sheet row deleted after import does not cancel its schedule.
- The worker must be deployed as a single logical service; multiple processes are safe through row locks.

## Validation

Focused unit tests cover import, immutable published payload, stale claims, uncertain outcomes, and write-back independence. A guarded disposable MySQL concurrency test is required before rollout.

## Rollback / Revisit Triggers

Stop the worker first, then roll back API/Desktop code. Retain the additive tables for audit and potential roll-forward. Reconsider a broker only when measured job volume or latency exceeds MySQL polling capacity.

## References

- [Meta Page posts guide](https://developers.facebook.com/docs/pages-api/posts/)
- [Meta Page Feed reference](https://developers.facebook.com/docs/graph-api/reference/page/feed/)
- [Meta Page Photos reference](https://developers.facebook.com/docs/graph-api/reference/page/photos/)
- [Google Sheets values guide](https://developers.google.com/workspace/sheets/api/guides/values)
