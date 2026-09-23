# Facebook Messenger Webhook Root Cause

## Scope

Bao cao nay chi danh gia cac dieu kien co bang chung tu Graph API v26.0, tai lieu
chinh thuc cua Meta, source code MetaCRM, hoac ket qua runtime da duoc cung cap.

Khong thay doi OAuth, Verify Token, webhook signature, Page Access Token,
`subscribed_apps`, websocket hay DB schema.

## PASS

### Webhook verification

- `GET /api/v1/facebook/webhook` da duoc Meta verify thanh cong.
- `backend/app/api/router.py` include Facebook va webhook router voi prefix `/api/v1`.
- `backend/app/api/webhook.py` co ca GET va POST tai `/facebook/webhook`.

Bang chung nay xac nhan callback nhan duoc GET verification. No khong xac nhan Meta
da tao Messenger event hoac public ingress forward duoc POST.

### OAuth scopes

User token da duoc Graph xac nhan grant:

```text
pages_manage_metadata
pages_messaging
pages_read_engagement
pages_show_list
public_profile
```

Khong co declined scope. Source OAuth tai `backend/app/services/facebook/auth.py`
dung cung danh sach scope nay va lay OAuth `client_id` tu
`settings.facebook_app_id`.

### Page Access Token

- Token ton tai, length 218 va `expires_at` hop le theo ket qua runtime.
- Token duoc dung cho Page node va `/{page-id}/subscribed_apps`.

Token length/expiry tu DB khong tu no chung minh token thuoc cung App ID. Endpoint
`debug/webhook-subscriptions` dung `/debug_token` de xac minh them App ID cua token.

### App ID trong config va source

- `.env` va `.env.example` hien co cung `FACEBOOK_APP_ID` (so sanh noi bo, khong in
  gia tri ra report).
- OAuth URL, Facebook Login token exchange, App Access Token va app subscription
  request deu lay App ID tu `settings.facebook_app_id`.

App ID ben trong User/Page token van can Graph `/debug_token` de xac minh; muc nay
duoc liet ke trong `UNKNOWN` cho den khi chay endpoint tong hop.

### Page subscription

`GET /{page-id}/subscribed_apps` da tra app subscription voi:

```text
messages
messaging_postbacks
messaging_optins
message_deliveries
message_reads
messaging_referrals
```

Day la bang chung Page-level subscription co field `messages`. Tai lieu Meta mo ta
Page subscription qua `POST /{page-id}/subscribed_apps` va kiem tra qua
`GET /{page-id}/subscribed_apps`.

### Backend ingress route

- Source co `POST /api/v1/facebook/webhook`.
- Log ingress `facebook webhook POST received` nam truoc signature va nghiep vu.
- Khong co log ingress khi gui tin nhan that.

Bang chung nay loai tru webhook signature, JSON parsing, DB va websocket khoi diem
gay mat request hien tai: request chua vao toi handler.

## FAIL

### Messenger event delivery

Ket qua duy nhat da xac nhan fail la:

```text
MetaCRM chua tung quan sat duoc POST /api/v1/facebook/webhook cho tin nhan that.
```

Chua co bang chung Graph hoac Meta Dashboard de ket luan mot cau hinh cu the ben
Meta dang fail.

## UNKNOWN

### App Mode

`UNKNOWN`. Graph API khong expose mot field Application on dinh de xac minh App dang
Live hay Development. `GET /api/v1/facebook/debug/app-info` tra
`app_mode="UNKNOWN"` thay vi suy doan.

### Advanced Access

`UNKNOWN`. Granted scope tren token khong chung minh permission da co Advanced
Access cho nguoi gui khong co role. Tai lieu Messenger cua Meta neu Advanced Access
can thiet cho conversations voi nguoi khong co role tren app, Page hoac business.

### Messenger Product enabled

`UNKNOWN`. Graph API khong expose product-installation switch cua App Dashboard.
`debug/app-info` chi tra bang chung app-level subscription `object=page` co
`messages`; no khong chuyen bang chung nay thanh product enabled.

### Webhooks Product enabled

`UNKNOWN`. Graph API co the doc app subscriptions, nhung khong expose Webhooks
Product switch trong Dashboard. `debug/app-info` tra `webhook_product_enabled` la
`UNKNOWN`.

### App-level subscription va callback

`UNKNOWN` cho den khi chay:

```http
GET /api/v1/facebook/debug/webhook-subscriptions
```

Can thay `app_subscriptions.data` co `object=page`, field `messages`, va callback URL
dung neu Graph tra field callback. Neu Graph khong tra callback, response bat buoc la
`callback_url="UNKNOWN"`.

### App ID consistency

`UNKNOWN` cho den khi `debug/webhook-subscriptions` tra ket qua. Endpoint doi chieu:

- Runtime `.env` qua `settings.facebook_app_id`.
- OAuth va Facebook Login `client_id` trong source.
- App ID cua User token va Page token tu `/debug_token`.
- App IDs trong Page `subscribed_apps`.
- App ID dung de doc app subscriptions.

Messenger verification request va webhook payload khong co App ID de doi chieu truc
tiep, nen `webhook_payload_app_id` la `UNKNOWN`.

### POST forwarding qua public ingress

`UNKNOWN` neu chua goi public endpoint self-test bang POST. GET verification thanh
cong khong chung minh Cloudflare/WAF/Access policy forward POST.

## ROOT CAUSE

### Ket luan co bang chung

Chua du bang chung de xac dinh mot cau hinh Meta cu the la root cause.

Ranh gio loi da xac dinh la **truoc dong log dau tien cua FastAPI POST handler**.
Source code chung minh signature, parsing, DB va websocket chi chay sau dong log nay,
nen chung khong the la nguyen nhan cua viec khong co request/log.

Hai nhanh chua duoc phan tach bang bang chung la:

1. Meta khong tao/deliver event do App Mode, Advanced Access, Messenger/Webhooks
   product hoac app-level `page/messages` subscription.
2. Meta co gui POST nhung public ingress khong forward POST den FastAPI.

Khong duoc chon mot trong hai nhanh lam root cause cu the truoc khi hoan tat cac
`NEXT ACTION`. Gan App Mode hoac Advanced Access lam nguyen nhan luc nay se la suy
doan.

## NEXT ACTION

### 1. Xac minh public POST ingress

Goi endpoint self-test qua chinh public callback host:

```http
POST https://<public-host>/api/v1/facebook/debug/webhook-selftest
Content-Type: application/json
X-Request-ID: messenger-root-cause-selftest

{"probe":true}
```

- Neu khong co log: kiem tra Cloudflare Access, WAF, Bot rules, route/method policy
  va origin mapping. Root cause nam o public ingress.
- Neu co log: public POST path PASS; tiep tuc buoc 2.

### 2. Chay Page info v26.0

```http
GET /api/v1/facebook/debug/page-info/{page_id}
```

Xac nhan `id/name/category` cua dung Page va `tasks` co `MESSAGING`, `MODERATE` hoac
Profile Plus task tuong ung. Endpoint chi request field Page hop le
`id,name,category`; `tasks` lay dung nguon `/me/accounts` bang User token.

### 3. Chay App info v26.0

```http
GET /api/v1/facebook/debug/app-info
```

Ghi lai Application ID/name va `graph_evidence.app_subscriptions`. Khong chuyen cac
field `UNKNOWN` thanh PASS neu khong co bang chung Dashboard.

### 4. Chay webhook subscriptions va App ID consistency

```http
GET /api/v1/facebook/debug/webhook-subscriptions
```

- `app_id_consistency.status` phai la `PASS`.
- App subscription phai co `object=page` va field `messages`.
- Page subscription phai chua configured App ID va field `messages`.
- Callback phai khop public callback neu Graph tra callback.

Neu bat ky muc nao `FAIL`, day la root cause co bang chung. Neu `UNKNOWN`, tiep tuc
buoc 5.

### 5. Xac minh cac muc Dashboard ma Graph khong expose

Trong dung App ID da xac minh o buoc 4:

- App Mode: Live, hoac sender la app tester/developer khi App Development.
- `pages_messaging`: Advanced Access neu sender khong co role.
- Messenger product da duoc add/configure cho dung App.
- Webhooks product co object `page`, callback hien tai va field `messages`.
- Meta Webhooks delivery/activity logs co event, retry, HTTP status hay TLS error.

Neu sender co app/Page role nhan webhook nhung sender ngoai role khong nhan,
Advanced Access/App Mode la root cause co bang chung tu phep thu doi chung.

## Debug endpoints

```http
GET /api/v1/facebook/debug/page-info/{page_id}
GET /api/v1/facebook/debug/app-info
GET /api/v1/facebook/debug/webhook-subscriptions
```

Ca ba endpoint dung Graph API v26.0 va khong tra/log access token.

## Meta documentation evidence

- Messenger Platform requirements:
  https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api
- Subscribe a Page:
  https://www.postman.com/meta/messenger-platform-api/request/22794852-71c8141d-c26e-4936-82a8-c36921bbb1e1
- Fetch subscribed apps:
  https://www.postman.com/meta/messenger-platform-api/request/22794852-81886664-6443-4622-8846-5539056d0234
- Get Page tokens and Page tasks through `/me/accounts`:
  https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api
