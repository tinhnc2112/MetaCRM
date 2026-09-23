# Skill: Security Review

## Phạm vi

Review theo risk và trust boundary; tham chiếu OWASP phù hợp nhưng không biến checklist thành bằng chứng an toàn.

## Quy trình

1. Inventory asset, actor, entry point, dependency và dữ liệu nhạy cảm.
2. Vẽ data flow/trust boundary.
3. Xác định threat actor, capability và abuse case.
4. Phân tích spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege khi phù hợp.
5. Đánh giá likelihood × impact; ghi assumption và evidence.
6. Đề xuất control phòng ngừa, phát hiện, phản ứng và recovery.
7. Xác định residual risk, owner và verification test.

## Checklist trọng yếu

- Authentication: session/token lifecycle, MFA khi cần, replay và revocation.
- Authorization: deny by default, server-side, object/action/tenant level.
- Input/output: allowlist, canonicalization, injection, XSS, SSRF, path traversal, file upload.
- Secret/key: secret manager, rotation, scope, không log/commit.
- Data: classification, encryption, retention, deletion, backup access.
- Network: TLS, egress control, service identity, admin surface.
- Supply chain: lockfile, provenance, vulnerability triage, CI permission, artifact signing khi cần.
- Abuse: rate limit, quota, bot/fraud, expensive query, enumeration.
- Logging/audit: tamper resistance, redaction, access và retention.
- Operations: patching, incident response, break-glass và recovery.

## Báo cáo finding

Mỗi finding: ID, severity, asset/flow, evidence, exploit scenario, impact, recommendation, verification và residual risk. Không khẳng định exploitability nếu chưa có bằng chứng; ghi “cần xác minh”. Không đưa secret thật vào báo cáo.
