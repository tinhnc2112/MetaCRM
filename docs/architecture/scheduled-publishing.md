# M11 scheduled Facebook publishing

## Sheet contract

The configured worksheet must start with `ID | Page | Caption | Image | Publish Date | Publish Time | Status`. Add columns to an older `Caption | Image | Status` sheet without deleting existing rows. Assign a stable unique ID to every new schedule. `Page` is an exact Page ID, name, or username with exactly one active match. Caption text is preserved. Image is blank, a direct public URL, or a literal `=IMAGE("https://...")`. Dates accept ISO `YYYY-MM-DD` or `DD/MM/YYYY`; times accept `HH:MM` or ISO time. The configured IANA timezone is applied before storing UTC.

Blank and `Chưa đăng` may create a schedule. A new row already marked `Đã lên lịch`, `Đang đăng`, `Đã đăng`, `Không chắc chắn`, `Đã hủy`, or `Lỗi` is recorded as `INVALID` for review and cannot be claimed. Unknown statuses are also invalid. An existing scheduled row may be edited and re-synced with `Đã lên lịch`; a row previously rejected for invalid content may be corrected while retaining the app-written `Lỗi`. A conflicting Sheet status on a still-pending DB schedule quarantines it as `INVALID` for review, without overwriting the Sheet's status. Terminal DB execution states are authoritative and Sheet edits cannot reopen them. Correct a previously failed image/content/other mutable payload in the Sheet while leaving its status `Lỗi`, sync, then explicitly Retry only if the failure code is safe to retry.

## Data and transitions

`scheduled_posts` is authoritative. Sync updates `INVALID`, `READY`, and `SCHEDULED` payloads when Sheet status permits. A `FAILED` record may receive corrected caption, image, Page, and schedule while retaining `FAILED`, attempt count, and execution evidence. Only an explicit safe Retry makes it `SCHEDULED` again. Sync leaves `PUBLISHING`, `PUBLISHED`, `UNCERTAIN`, and `CANCELLED` unchanged. A missing Sheet row does not delete the DB row. The source identity has a unique digest index; due jobs and Page/time queries have indexes. MySQL stores UTC as naive `DATETIME`; the API returns an explicit UTC offset.

The worker claims and commits a due schedule before making the Graph request. It never holds an InnoDB lock during media validation or Graph I/O. Explicit Graph rejection becomes `FAILED`; explicit rate limiting schedules up to three attempts with exponential backoff. Network timeout, 5xx, malformed success response, or a stale claim becomes `UNCERTAIN`. A successful Graph response records the Page post ID and becomes terminal `PUBLISHED`. The status write-back is a separate operation and cannot change `PUBLISHED` into a retryable state.

Write-back checks the source row ID before updating column G. If the row moved or Sheets is unavailable, `writeback_pending` remains set. The worker retries status only. An admin can re-sync to relocate a mutable row. For a terminal row whose source row moved, manual Sheet correction may be needed; no automatic remapping can risk writing another row's status.

## Operational setup

1. Apply Alembic revision `0030_scheduled_publishing` on MySQL. Keep one Alembic head.
2. Enable Google Sheets API in the service account project. Supply its JSON key via backend-only `GOOGLE_SERVICE_ACCOUNT_FILE`, preferably a secret-mounted file outside the repository. Share only the target spreadsheet with the service-account email. The adapter requests the `https://www.googleapis.com/auth/spreadsheets` scope. No Drive scope or user Google OAuth is used.
3. In Desktop, an admin configures spreadsheet ID, worksheet, and IANA timezone, then triggers sync. Use public `raw.githubusercontent.com` image URLs for repository images in `assets/content-gia-vi-km/`.
4. Reconnect each Facebook Page through the existing Meta app so Page tokens receive publishing consent. The app must have appropriate Meta access/review for `pages_manage_posts`; the Page operator needs the `CREATE_CONTENT` task. Confirm the effective app permissions and Page tasks before enabling the worker.
5. Run `python -m scripts.publishing_worker` from `backend` as a supervised dedicated process. Do not run it inside each FastAPI worker. Monitor backlog, oldest due time, `UNCERTAIN`, `FAILED`, and pending write-backs. Restarting the process does not resend `UNCERTAIN` rows.

## Provider contract checked 2026-09-29

Meta's [Page posts guide](https://developers.facebook.com/docs/pages-api/posts/) documents `POST /{page_id}/feed` with `message`, and `POST /{page_id}/photos` with a public `url`; the photo response includes `id` and `post_id`. The [Page Feed reference](https://developers.facebook.com/docs/graph-api/reference/page/feed/) and [Page Photos reference](https://developers.facebook.com/docs/graph-api/reference/page/photos/) show Page access token, `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`, and a Page operator with `CREATE_CONTENT`. The guide lists additional permissions/tasks for broader Pages operations; confirm app review status for the actual app. The repository's configured Graph default remains `v25.0`, which is shown in the posts guide; the live reference examples currently show `v26.0`.

Meta's photo reference lists a 4 MB image limit and warns that PNG above 1 MB may degrade; the M11 fetch guard enforces 4 MB, so the existing roughly 2 MB PNG assets remain usable. Only JPEG, PNG, and GIF are accepted by the M11 validator. The same reference supports multipart `source`, which M11 uses after a bounded DNS-pinned download, avoiding a second URL fetch by Graph.

## Failure response and rollback

- Google outage: imported schedules continue; sync and write-back fail independently.
- Facebook timeout or worker crash: inspect the Page and resolve `UNCERTAIN` manually. Never use Retry until a post is verified absent.
- Invalid/revoked token (`INVALID_TOKEN`) or missing publishing permission (`MISSING_PERMISSION`): reconnect/re-consent the Page; these failures do not offer Retry. Reconcile the configuration and publishing access before any new schedule.
- Rollback: stop the dedicated worker first, roll back API/Desktop deployment, and preserve M11 tables and evidence. Dropping tables is destructive and requires backup/review.

Do not start the worker in production before a disposable MySQL migration/concurrency check and a controlled Meta app/Page publish test have passed.
