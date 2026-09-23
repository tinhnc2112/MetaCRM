# Skill: DevOps & Reliability

## Delivery pipeline

- Build reproducible; pin dependency bằng manifest/lockfile phù hợp.
- CI chạy lint/static analysis/test/security scan theo risk.
- Artifact immutable, có provenance/version; promotion giữa môi trường thay vì rebuild.
- Secret từ secret manager; least privilege cho CI/CD và workload identity.
- Infrastructure/config được review, test và audit; drift được phát hiện.
- Deployment có health/readiness, feature flag và automated verification.

## Reliability design

1. Xác định critical user journey.
2. Định nghĩa SLI/SLO và error budget.
3. Đặt timeout budget xuyên chuỗi dependency.
4. Retry chỉ lỗi transient, có exponential backoff+jitter, giới hạn và idempotency.
5. Dùng backpressure, queue limit, circuit breaker/bulkhead khi phù hợp.
6. Thiết kế graceful degradation và load shedding.
7. Capacity plan có peak/headroom và trigger scale.

## Observability

- Metric: traffic, error, latency, saturation và business outcome.
- Log có cấu trúc, correlation ID, redaction, sampling/retention.
- Trace tại service/dependency boundary; kiểm soát cardinality/cost.
- Dashboard theo user journey; alert actionable theo SLO/symptom.
- Runbook gồm impact, diagnosis, mitigation, escalation và recovery verification.

## Rollout/Rollback

- Chọn rolling/canary/blue-green theo risk và hạ tầng.
- Định nghĩa pre-check, canary cohort, promote/abort metric và observation window.
- Rollback code/config nhanh; schema/data dùng compatibility và roll-forward nếu không đảo ngược an toàn.
- Sau rollback: kiểm tra health, data integrity, queue/backlog và user impact.

## DR

Định nghĩa RPO/RTO, backup scope/encryption/retention, restore drill, dependency và communication. Backup chưa restore-test không được coi là chiến lược recovery hoàn chỉnh.
