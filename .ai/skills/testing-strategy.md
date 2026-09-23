# Skill: Testing Strategy

## Nguyên tắc

Thiết kế test theo risk, invariant và acceptance criteria; coverage là tín hiệu, không phải mục tiêu duy nhất.

## Ma trận test

- **Unit**: logic thuần, boundary, property/invariant.
- **Integration**: database, queue, cache, filesystem, external adapter.
- **Contract**: producer/consumer, API schema, backward compatibility.
- **E2E**: user journey quan trọng; số lượng nhỏ, ổn định.
- **Performance**: load, stress, soak, spike; workload và pass/fail rõ.
- **Security**: authorization matrix, injection, abuse, secret/PII leakage.
- **Resilience**: timeout, dependency outage, retry storm, partial failure, recovery.
- **Migration/DR**: forward/backward compatibility, backfill, restore và rollback.

## Quy trình

1. Liệt kê risk và invariant.
2. Map mỗi risk tới tầng test rẻ nhất có đủ confidence.
3. Định nghĩa fixture, clock, randomness, network và cleanup.
4. Định nghĩa môi trường, dữ liệu đại diện và isolation.
5. Đặt quality gate theo severity; quản lý flaky test có owner/SLA.
6. Thu thập test result, latency/error metric và artifact để điều tra.

## Checklist

- [ ] Happy, negative, boundary và malformed input
- [ ] Authorization theo role/resource/tenant
- [ ] Duplicate, ordering, concurrency và idempotency
- [ ] Timeout/retry/cancellation/cleanup
- [ ] Compatibility và migration
- [ ] Không dùng production secret/PII
- [ ] Test deterministic và chạy lặp lại được
- [ ] Pass/fail gắn với requirement/SLO

Không tuyên bố “đã test” nếu chưa thực thi; thay bằng “test đề xuất” hoặc “cần chạy”.
