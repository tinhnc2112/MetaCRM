# Facebook Messenger Webhook Debug Guide

## 1. Flow hien tai

1. User hoan tat Facebook OAuth voi cac scope Page/Messenger.
2. Backend doc Page Access Token tu `GET /me/accounts`, ma hoa va luu token vao DB.
3. Sau khi sync Page, backend goi:

   ```text
   POST /{page-id}/subscribed_apps
   subscribed_fields=messages,messaging_postbacks,messaging_optins,message_deliveries,message_reads,messaging_referrals
   access_token={PAGE_ACCESS_TOKEN}
   ```

4. Meta App Dashboard phai cau hinh Webhooks product voi object `page`, Callback URL
   `/api/v1/facebook/webhook`, va toi thieu field `messages`.
5. Khi co tin nhan Messenger, Meta gui HTTPS POST qua Cloudflare Tunnel den:

   ```text
   POST /api/v1/facebook/webhook
   ```

6. Backend log request ngay khi request cham FastAPI, doc raw body, verify
   `X-Hub-Signature-256`, parse payload co `object=page`, roi moi persist/broadcast.

Neu khong co log `facebook webhook POST received`, request chua cham FastAPI. Khi do
khong nen debug parser, DB, conversation, message hay WebSocket.

## 2. Cac diem da kiem tra

- Webhook router co prefix `/facebook/webhook`.
- Top-level API router co prefix `/api/v1` va da include webhook router.
- Route cuoi cung la `GET|POST /api/v1/facebook/webhook`.
- `app.main:app` include top-level API router.
- Middleware duy nhat co lien quan HTTP la CORS. CORS khong chan server-to-server POST
  tu Meta; POST webhook khong yeu cau browser preflight.
- POST webhook khong yeu cau JWT. No chi verify chu ky Meta bang App Secret.
- Signature duoc tinh tren raw body bang HMAC-SHA256 va constant-time compare.
- Messenger payload duoc chap nhan khi `object=page`.
- Page subscription dung edge `/{page-id}/subscribed_apps` va Page Access Token.
- OAuth da xin them `pages_manage_metadata` va `pages_messaging`, ben canh cac scope
  Page dang co. User cu can OAuth lai de token moi thuc su co cac quyen moi.
- Khong co thay doi DB schema hay logic persist Messenger.

Theo tai lieu Messenger Platform cua Meta, can dong thoi co hai lop subscription:

1. App-level Webhooks configuration: object `page`, Callback URL hop le va field
   `messages` trong Meta App Dashboard.
2. Page-level installation: app xuat hien trong `GET /{page-id}/subscribed_apps`, voi
   `subscribed_fields` chua `messages`.

Page subscription thanh cong khong tu dong chung minh app-level Callback URL/object
configuration dang dung.

Tai lieu tham chieu:

- [Meta Messenger Platform - Webhooks](https://developers.facebook.com/docs/messenger-platform/webhooks)
- [Meta Messenger Platform - Get Started](https://developers.facebook.com/docs/messenger-platform/get-started)
- [Meta Messenger Platform API official Postman collection](https://www.postman.com/meta/messenger-platform-api/folder/22794852-b5d97624-14d8-4e67-a2e4-529add49ca58)

## 3. Cac endpoint debug

Tat ca endpoint debug deu yeu cau JWT cua MetaCRM:

```text
Authorization: Bearer {METACRM_ACCESS_TOKEN}
```

### Kiem tra app da cai tren Page

```http
GET /api/v1/facebook/debug/subscribed-apps/{page_id}
```

Backend goi Graph `GET /{page-id}/subscribed_apps` bang Page Access Token trong DB.

Response:

```json
{
  "page_id": "123456789",
  "app_id": "987654321",
  "subscribed_fields": ["messages", "messaging_postbacks"],
  "graph_response": {
    "data": [
      {
        "id": "987654321",
        "name": "MetaCRM",
        "subscribed_fields": ["messages", "messaging_postbacks"]
      }
    ]
  }
}
```

Can xac nhan:

- `graph_response.data` khong rong.
- `app_id` cau hinh nam trong `graph_response.data`.
- `subscribed_fields` cua dung app co `messages`.

### Kiem tra Page Access Token dang dung

```http
GET /api/v1/facebook/debug/page-token/{page_id}
```

Response chi co metadata:

```json
{
  "page_id": "123456789",
  "token_prefix": "EAAB...30-characters-only...",
  "token_length": 220,
  "expires_at": "2026-10-01T00:00:00Z"
}
```

Endpoint khong tra token day du. Doi chieu prefix, length va Page ID voi token dang
duoc test trong Graph API Explorer.

### Ep resubscribe, bo qua DB cache

```http
POST /api/v1/facebook/debug/resubscribe/{page_id}
```

Endpoint luon goi Graph `POST /{page-id}/subscribed_apps`, ke ca khi DB da co status
`subscribed`. Endpoint khong ghi status, attempt count hay timestamp vao DB.

Log mong doi:

```text
facebook_debug_resubscribe_request path=/123456789/subscribed_apps params={'subscribed_fields': '...', 'access_token': '<redacted>'}
facebook_debug_resubscribe_response page_id=123456789 graph_response={'success': True}
```

Neu Graph loi:

```text
facebook_debug_resubscribe_error page_id=123456789 error_type=FacebookPermissionError graph_error=...
```

### Kiem tra webhook health

```http
GET /api/v1/facebook/debug/webhook-health
```

Response:

```json
{
  "callback_url": "https://example.trycloudflare.com/api/v1/facebook/webhook",
  "verify_token_configured": true,
  "app_secret_configured": true,
  "cloudflare_reachable": "unknown"
}
```

`cloudflare_reachable=true` chi khi health request hien tai di qua Cloudflare va co
header `CF-Ray`. Neu goi endpoint qua localhost thi ket qua la `unknown`; dieu nay
khong co nghia tunnel dang hong.

Dat URL public hien tai vao:

```text
FACEBOOK_WEBHOOK_CALLBACK_URL=https://<current-tunnel-host>/api/v1/facebook/webhook
```

Neu bien nay chua duoc dat, health endpoint tam suy ra callback tu public origin cua
`FACEBOOK_REDIRECT_URI` va ghep `/api/v1/facebook/webhook`. Day la fallback chan doan;
gia tri van phai duoc doi chieu truc tiep voi Callback URL trong Meta App Dashboard.

Cloudflare Quick Tunnel co the doi hostname sau khi restart. URL trong Meta App
Dashboard va bien moi truong phai duoc cap nhat cung luc.

## 4. Ket qua mong doi

### Request da cham backend

Dong log dau tien:

```text
facebook webhook POST received request_id=... client_ip=... content_length=... signature_present=True headers=...
```

Sau khi doc body:

```text
facebook webhook body read request_id=... body_length=...
facebook webhook signature verified request_id=...
facebook webhook payload parsed request_id=... object_type=page entry_count=1
```

Header `Authorization`, `Cookie`, `Proxy-Authorization`, `Set-Cookie` va
`X-Hub-Signature-256` bi thay bang `<redacted>` trong log.

### Signature khong hop le

```text
facebook webhook signature verification failed request_id=... reason=Missing or malformed X-Hub-Signature-256 header
```

hoac:

```text
facebook webhook signature verification failed request_id=... reason=X-Hub-Signature-256 does not match payload
```

Neu thay dong nay, request da qua tunnel va router; can kiem tra request co den tu dung
Meta App va backend co dung App Secret cua app do hay khong.

### Khong co bat ky log POST nao

Request chua den FastAPI. Kiem tra theo thu tu:

1. Meta App Dashboard co dung app ID hay khong.
2. Webhooks product co object `page`, Callback URL hien tai va field `messages` hay khong.
3. `GET debug/subscribed-apps` co dung app ID va field `messages` hay khong.
4. Thu nut `Test` cho field `messages` trong Meta App Dashboard.
5. Xem Cloudflare request logs de biet Meta co cham tunnel hay khong.
6. Xac nhan Quick Tunnel hostname chua thay doi.
7. Xac nhan Cloudflare Access/WAF/Bot protection khong chan callback truoc origin.
8. Xac nhan app mode, app roles va Advanced Access.

## 5. Neu Facebook van khong gui POST

### App-level field subscription bi thieu

`POST /{page-id}/subscribed_apps` chi cai app vao Page. Meta App Dashboard van phai
cau hinh Webhooks product, object `page`, dung Callback URL va field `messages`.

### App dang Development mode hoac chi co Standard Access

Theo huong dan Messenger Platform cua Meta, Standard Access chi phu hop voi nguoi co
role tren app/Page trong qua trinh test. Tin nhan tu customer/account ngoai role can
Advanced Access cho cac quyen can thiet va app phai o trang thai phu hop de nhan du
lieu production.

Test tach doi:

- Gui bang account co role Admin/Developer/Tester cua app.
- Gui bang account hoan toan ngoai app role.

Neu account co role tao webhook nhung account ngoai role khong tao webhook, tunnel va
backend da dung; van de nam o app mode/access level/app review.

### Token cu chua co scope Messenger

Code OAuth moi xin `pages_manage_metadata` va `pages_messaging`, nhung token da luu
truoc thay doi khong tu co them scope. Disconnect/reconnect Facebook OAuth, dong y cac
permission moi, sync lai Page, sau do kiem tra lai `subscribed_apps`.

### Sai app, sai Page hoac sai Page token

- App ID trong `graph_response.data` phai trung `FACEBOOK_APP_ID`.
- Page ID trong endpoint debug phai trung Page nhan tin nhan.
- Prefix/length token phai trung token Page dang kiem tra trong Graph API Explorer.
- Page token phai duoc cap tu user co Page task phu hop va quyen
  `pages_manage_metadata`; Messenger can `pages_messaging`.

### Callback URL hoac Cloudflare route cu

GET verify thanh cong tai mot thoi diem khong chung minh hostname Quick Tunnel van con
hieu luc sau khi tunnel restart. Kiem tra lai URL trong Meta App Dashboard, health
endpoint qua public URL va Cloudflare request log.

Neu Cloudflare Access, WAF rule, Bot protection hoac authentication policy bao phu
callback path, Meta co the nhan 401/403 tai edge va request se khong tao log trong
FastAPI. Callback webhook phai duoc phep di qua edge ma khong can interactive login.

### Meta test event den, tin nhan that khong den

Day la dau hieu manh cua app mode/access level/app role, khong phai FastAPI route.
Kiem tra App Review, Advanced Access, Business Verification neu Meta yeu cau, va dung
Page/account da duoc gan vao app/business.

### Nhieu messaging app hoac Handover Protocol

Kiem tra Page co nhieu app Messenger, Business Integration cu, Primary Receiver hoac
Handover Protocol hay khong. Doi chieu toan bo `graph_response.data`, khong chi app dau
tien.

### Meta da tam dung delivery

Kiem tra Webhooks activity/delivery logs va alerts trong Meta App Dashboard. Nhieu lan
callback timeout, TLS fail, 4xx hoac 5xx co the tao retry/delivery issue. Backend hien
tra 200 cho payload `object=page` hop le va cac event khong ho tro, nen log dau request
se phan biet ro delivery issue voi processing issue.
