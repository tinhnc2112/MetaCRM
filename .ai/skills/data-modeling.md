# Skill: Data Modeling

## Quy trình

1. Xác định entity, lifecycle, ownership và source of truth.
2. Ghi business invariant và transaction boundary trước schema.
3. Chọn mô hình lưu trữ theo access pattern, consistency, volume, retention và vận hành; không chọn theo xu hướng.
4. Định nghĩa key, relationship, cardinality, nullability và constraint.
5. Thiết kế index từ query thực tế; đánh giá write amplification và storage.
6. Xử lý concurrency: isolation, optimistic/pessimistic locking, uniqueness và idempotency.
7. Phân loại PII/secret; encryption, masking, retention, deletion và audit.
8. Thiết kế migration, backfill, validation, cutover và rollback/roll-forward.
9. Thiết kế backup, restore test, RPO/RTO và archival.

## Consistency

Nêu rõ nơi cần strong consistency và nơi chấp nhận eventual consistency; mô tả stale-read window, conflict resolution và trải nghiệm người dùng. Với distributed workflow, cân nhắc outbox/inbox, saga hoặc reconciliation; không tuyên bố exactly-once nếu không chứng minh được.

## Migration an toàn

Ưu tiên expand–migrate–contract:

1. Thêm schema backward-compatible.
2. Deploy code đọc/ghi tương thích.
3. Backfill có checkpoint, throttle và metric.
4. Validate count/checksum/invariant.
5. Chuyển traffic bằng flag/canary.
6. Chỉ contract sau khi không còn consumer cũ.

## Checklist

- [ ] Invariant được enforce đúng tầng
- [ ] Query/access pattern và index khớp
- [ ] Tenant isolation và authorization không dựa vào client
- [ ] Retention/deletion/audit rõ
- [ ] Hot key, growth, partition và archival được xét
- [ ] Migration có dry-run, observability và abort criteria
- [ ] Restore đã được kiểm thử
