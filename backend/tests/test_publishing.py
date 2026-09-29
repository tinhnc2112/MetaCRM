"""Focused schedule, recovery and input-boundary tests (provider calls are fake)."""

from datetime import UTC, datetime, timedelta

import pytest
from app.db.base import Base
from app.db.session import get_db_session
from app.dependencies.auth import get_current_user
from app.main import app
from app.models.auth import Role, User
from app.models.facebook import FacebookAccount, FacebookPage
from app.models.publishing import ScheduledPost, SheetPublishingConfig, source_identity_key
from app.services.facebook.client import FacebookGraphClient
from app.services.facebook.exceptions import (
    FacebookPermissionError,
    FacebookTokenError,
    FacebookTransportError,
)
from app.services.publishing.media import MediaError, inspect_image, validate_public_url
from app.services.publishing.parser import parse_image, parse_rows
from app.services.publishing.sheet import SheetError
from app.services.publishing.sync import flush_writebacks, sync_sheet
from app.services.publishing.worker import (
    claim_due,
    mark_stale_uncertain,
    publish_claimed,
    run_once,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

HEADERS = ["ID", "Page", "Caption", "Image", "Publish Date", "Publish Time", "Status"]


class FakeSheet:
    def __init__(self, rows):
        self.rows = rows
        self.writes = []
        self.fail_write = False

    def read(self, _spreadsheet, _worksheet):
        return self.rows

    def write_status(self, _spreadsheet, _worksheet, row, status):
        if self.fail_write:
            raise OSError("offline")
        self.writes.append((row, status))


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(username="publisher", email="publisher@example.com", password_hash="test")
        db.add(user)
        db.flush()
        account = FacebookAccount(
            user_id=user.id, facebook_user_id="fbuser", access_token_encrypted="encrypted"
        )
        db.add(account)
        db.flush()
        db.add(
            FacebookPage(
                facebook_account_id=account.id,
                page_id="page1",
                name="Demo",
                access_token_encrypted="encrypted",
            )
        )
        db.add(
            SheetPublishingConfig(
                id=1, spreadsheet_id="sheet", worksheet="Posts", timezone="Asia/Ho_Chi_Minh"
            )
        )
        db.commit()
        yield db
    engine.dispose()


def test_parser_preserves_unicode_and_rejects_duplicate_and_bad_image():
    rows = [
        HEADERS,
        [
            "one",
            "Demo",
            "Xin chào\nDòng hai",
            '=IMAGE("https://raw.githubusercontent.com/a/b.png")',
            "2026-10-01",
            "10:30",
            "",
        ],
        ["one", "Demo", "another", "", "2026-10-02", "10:30", ""],
        ["two", "Demo", "Text", "=IMAGE(A1)", "2026-10-02", "10:30", ""],
    ]
    valid, errors = parse_rows(rows, "Asia/Ho_Chi_Minh")
    assert len(valid) == 1
    assert valid[0].caption == "Xin chào\nDòng hai"
    assert valid[0].scheduled_for_utc.hour == 3
    assert [error[2] for error in errors] == ["Duplicate ID", "Invalid IMAGE formula"]
    assert parse_image("") is None
    assert parse_image("https://example.com/a.png") == "https://example.com/a.png"


def test_sync_is_idempotent_and_published_is_immutable(session):
    sheet = FakeSheet([HEADERS, ["one", "page1", "Caption", "", "2026-10-01", "10:30", ""]])
    assert sync_sheet(session, sheet)["created"] == 1
    assert sync_sheet(session, sheet)["unchanged"] == 1
    post = session.scalar(select(ScheduledPost).where(ScheduledPost.external_id == "one"))
    sheet.rows[1][2] = "Changed"
    assert sync_sheet(session, sheet)["updated"] == 1
    assert post.caption == "Changed"
    post.status = "PUBLISHED"
    session.commit()
    sheet.rows[1][2] = "Too late"
    sync_sheet(session, sheet)
    assert post.caption == "Changed"
    sheet.rows = [HEADERS]
    sync_sheet(session, sheet)
    assert (
        session.scalar(select(ScheduledPost).where(ScheduledPost.external_id == "one")) is not None
    )


@pytest.mark.parametrize(
    "status",
    ["Đã lên lịch", "Đang đăng", "Đã đăng", "Không chắc chắn", "Đã hủy", "Lỗi", "unknown"],
)
def test_preexisting_sheet_status_never_creates_a_due_job(session, status):
    sheet = FakeSheet(
        [HEADERS, ["old", "page1", "Already handled", "", "2025-01-01", "10:30", status]]
    )
    result = sync_sheet(session, sheet)
    post = session.scalar(select(ScheduledPost).where(ScheduledPost.external_id == "old"))
    assert result["invalid"] == 1
    assert post.status == "INVALID"
    assert claim_due(session) is None
    assert post.last_error_code == ("SHEET_ROW" if status == "unknown" else "SHEET_STATUS")


def test_published_db_record_stays_terminal_when_sheet_says_published(session):
    sheet = FakeSheet([HEADERS, ["done", "page1", "Original", "", "2025-01-01", "10:30", ""]])
    sync_sheet(session, sheet)
    post = session.scalar(select(ScheduledPost).where(ScheduledPost.external_id == "done"))
    post.status = "PUBLISHED"
    post.attempt_count = 1
    post.facebook_post_id = "page1_123"
    session.commit()
    sheet.rows[1][2] = "Changed after publication"
    sheet.rows[1][6] = "Đã đăng"
    sync_sheet(session, sheet)
    assert post.status == "PUBLISHED"
    assert post.caption == "Original"
    assert post.attempt_count == 1
    assert post.facebook_post_id == "page1_123"
    assert claim_due(session) is None


def test_existing_scheduled_row_can_be_updated_after_status_writeback(session):
    sheet = FakeSheet([HEADERS, ["update", "page1", "Initial", "", "2026-10-01", "10:30", ""]])
    sync_sheet(session, sheet)
    sheet.rows[1][6] = "Đã lên lịch"
    sheet.rows[1][2] = "Corrected before publish"
    assert sync_sheet(session, sheet)["updated"] == 1
    post = session.scalar(select(ScheduledPost).where(ScheduledPost.external_id == "update"))
    assert post.status == "SCHEDULED" and post.caption == "Corrected before publish"


def test_conflicting_published_sheet_status_quarantines_pending_schedule(session):
    sheet = FakeSheet([HEADERS, ["conflict", "page1", "Original", "", "2025-01-01", "10:30", ""]])
    sync_sheet(session, sheet)
    sheet.rows[1][6] = "Đã đăng"
    assert sync_sheet(session, sheet)["invalid"] == 1
    post = session.scalar(select(ScheduledPost).where(ScheduledPost.external_id == "conflict"))
    assert post.status == "INVALID"
    assert post.last_error_code == "SHEET_STATUS"
    assert claim_due(session) is None


def test_failed_image_can_be_corrected_but_requires_explicit_retry(session):
    from app.api.publishing import retry

    row = [
        "image-fix",
        "page1",
        "Caption",
        "https://example.com/bad.png",
        "2025-01-01",
        "10:30",
        "",
    ]
    sheet = FakeSheet([HEADERS, row])
    sync_sheet(session, sheet)
    post = session.scalar(select(ScheduledPost).where(ScheduledPost.external_id == "image-fix"))
    post.status = "FAILED"
    post.attempt_count = 1
    post.last_error_code = "INVALID_IMAGE"
    post.request_fingerprint = "original-attempt-fingerprint"
    session.commit()
    row[2] = "Corrected caption"
    row[3] = "https://example.com/good.png"
    row[4] = "2025-01-02"
    row[6] = "Lỗi"  # Status written back after a definite failure.
    assert sync_sheet(session, sheet)["updated"] == 1
    assert post.status == "FAILED"
    assert post.image_url == row[3] and post.caption == row[2]
    assert post.attempt_count == 1
    assert post.request_fingerprint == "original-attempt-fingerprint"
    assert post.last_error_code == "INVALID_IMAGE"
    assert claim_due(session) is None
    user = session.scalar(select(User).where(User.username == "publisher"))
    user.roles = [Role(name="admin")]
    session.commit()
    assert retry(post.uuid, session, user)["status"] == "SCHEDULED"
    assert post.image_url == row[3]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (FacebookTokenError("revoked"), "INVALID_TOKEN"),
        (FacebookPermissionError("permission"), "MISSING_PERMISSION"),
    ],
)
def test_provider_credential_failures_are_distinct_and_not_retryable(
    session, monkeypatch, failure, code
):
    from app.api.publishing import retry
    from fastapi import HTTPException

    page = session.scalar(select(FacebookPage))
    post = ScheduledPost(
        source="google_sheet",
        source_key=source_identity_key("google_sheet", "sheet", "Posts", code),
        spreadsheet_id="sheet",
        worksheet="Posts",
        external_id=code,
        source_timezone="UTC",
        status="SCHEDULED",
        caption="No unsafe retry",
        facebook_page_id=page.id,
        scheduled_for_utc=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
    )
    session.add(post)
    session.commit()
    monkeypatch.setattr(
        "app.services.publishing.worker.TokenCipher",
        lambda: type("Cipher", (), {"decrypt": lambda self, value: "fake-token"})(),
    )

    class Graph:
        def post(self, path, payload):
            raise failure

    assert publish_claimed(session, claim_due(session), Graph()) == "FAILED"
    assert post.last_error_code == code
    user = session.scalar(select(User).where(User.username == "publisher"))
    user.roles = [Role(name="admin")]
    session.commit()
    with pytest.raises(HTTPException) as exc:
        retry(post.uuid, session, user)
    assert exc.value.status_code == 409


def test_duplicate_sheet_id_never_schedules_a_post(session):
    sheet = FakeSheet(
        [
            HEADERS,
            ["dup", "page1", "First", "", "2026-10-01", "10:30", ""],
            ["dup", "page1", "Second", "", "2026-10-02", "10:30", ""],
        ]
    )
    result = sync_sheet(session, sheet)
    post = session.scalar(select(ScheduledPost).where(ScheduledPost.external_id == "dup"))
    assert result["invalid"] == 1
    assert post.status == "INVALID"
    assert post.last_error_message == "Duplicate ID"


def test_claim_stale_and_transport_uncertain(session, monkeypatch):
    page = session.scalar(select(FacebookPage))
    post = ScheduledPost(
        source="google_sheet",
        source_key=source_identity_key("google_sheet", "sheet", "Posts", "due"),
        spreadsheet_id="sheet",
        worksheet="Posts",
        external_id="due",
        source_timezone="Asia/Ho_Chi_Minh",
        status="SCHEDULED",
        caption="Hello",
        facebook_page_id=page.id,
        scheduled_for_utc=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
    )
    session.add(post)
    session.commit()
    assert claim_due(session) == post.id
    assert claim_due(session) is None
    monkeypatch.setattr(
        "app.services.publishing.worker.TokenCipher",
        lambda: type("Cipher", (), {"decrypt": lambda self, value: "fake-token"})(),
    )

    class Graph:
        def post(self, path, payload):
            assert path == "/page1/feed"
            raise FacebookTransportError("timeout")

    assert publish_claimed(session, post.id, Graph()) == "UNCERTAIN"
    assert claim_due(session) is None
    post.status = "PUBLISHING"
    post.claimed_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    session.commit()
    assert mark_stale_uncertain(session) == 1
    assert post.status == "UNCERTAIN"


def test_success_survives_sheet_write_failure(session, monkeypatch):
    page = session.scalar(select(FacebookPage))
    post = ScheduledPost(
        source="google_sheet",
        source_key=source_identity_key("google_sheet", "sheet", "Posts", "due"),
        spreadsheet_id="sheet",
        worksheet="Posts",
        external_id="due",
        source_row=2,
        source_timezone="Asia/Ho_Chi_Minh",
        status="SCHEDULED",
        caption="Hello",
        facebook_page_id=page.id,
        scheduled_for_utc=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
    )
    session.add(post)
    session.commit()
    monkeypatch.setattr(
        "app.services.publishing.worker.TokenCipher",
        lambda: type("Cipher", (), {"decrypt": lambda self, value: "fake-token"})(),
    )

    class Graph:
        calls = 0

        def post(self, path, payload):
            self.calls += 1
            return {"id": "page1_123"}

    graph = Graph()
    claim_due(session)
    assert publish_claimed(session, post.id, graph) == "PUBLISHED"
    sheet = FakeSheet([HEADERS, ["due", "page1", "Hello", "", "2026-10-01", "10:30", ""]])
    sheet.fail_write = True
    assert flush_writebacks(session, sheet) == 0
    assert post.status == "PUBLISHED"
    assert post.facebook_post_id == "page1_123"
    assert claim_due(session) is None
    assert graph.calls == 1


def test_single_image_uses_validated_bytes_and_persists_post_id(session, monkeypatch):
    page = session.scalar(select(FacebookPage))
    post = ScheduledPost(
        source="google_sheet",
        source_key=source_identity_key("google_sheet", "sheet", "Posts", "image"),
        spreadsheet_id="sheet",
        worksheet="Posts",
        external_id="image",
        source_timezone="UTC",
        status="SCHEDULED",
        caption="Image caption",
        image_url="https://raw.githubusercontent.com/example/a.png",
        facebook_page_id=page.id,
        scheduled_for_utc=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
    )
    session.add(post)
    session.commit()
    monkeypatch.setattr(
        "app.services.publishing.worker.TokenCipher",
        lambda: type("Cipher", (), {"decrypt": lambda self, value: "fake-token"})(),
    )
    monkeypatch.setattr(
        "app.services.publishing.worker.inspect_image",
        lambda url: (b"\x89PNG\r\n\x1a\n", "image/png"),
    )

    class Graph:
        def post_photo(self, path, token, caption, image, mime):
            assert (path, token, caption, mime) == (
                "/page1/photos",
                "fake-token",
                "Image caption",
                "image/png",
            )
            assert image.startswith(b"\x89PNG")
            return {"id": "photo123", "post_id": "page1_456"}

    assert publish_claimed(session, claim_due(session), Graph()) == "PUBLISHED"
    assert post.facebook_post_id == "page1_456"


def test_graph_photo_upload_uses_multipart_source(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"id":"photo123","post_id":"page1_456"}'

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["type"] = request.headers["Content-type"]
        seen["body"] = request.data
        return Response()

    monkeypatch.setattr("app.services.facebook.client.urlopen", fake_urlopen)
    result = FacebookGraphClient(api_version="v25.0").post_photo(
        "/page1/photos", "fake-token", "Xin chào", b"\x89PNGdata", "image/png"
    )
    assert result["post_id"] == "page1_456"
    assert seen["url"].endswith("/v25.0/page1/photos")
    assert seen["type"].startswith("multipart/form-data; boundary=")
    assert b'name="source"' in seen["body"]
    assert b"\x89PNGdata" in seen["body"]


def test_sheet_outage_does_not_block_due_facebook_publish(session, monkeypatch):
    page = session.scalar(select(FacebookPage))
    post = ScheduledPost(
        source="google_sheet",
        source_key=source_identity_key("google_sheet", "sheet", "Posts", "offline"),
        spreadsheet_id="sheet",
        worksheet="Posts",
        external_id="offline",
        source_timezone="UTC",
        status="SCHEDULED",
        caption="Still publish",
        facebook_page_id=page.id,
        scheduled_for_utc=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
    )
    session.add(post)
    session.commit()
    monkeypatch.setattr(
        "app.services.publishing.worker.TokenCipher",
        lambda: type("Cipher", (), {"decrypt": lambda self, value: "fake-token"})(),
    )
    monkeypatch.setattr(
        "app.services.publishing.worker.flush_writebacks",
        lambda *args, **kwargs: (_ for _ in ()).throw(SheetError("offline")),
    )

    class Graph:
        def post(self, path, payload):
            return {"id": "page1_789"}

    assert run_once(session, Graph()) == "PUBLISHED"
    assert post.facebook_post_id == "page1_789"


def test_disconnected_page_is_not_published(session):
    page = session.scalar(select(FacebookPage))
    account = session.get(FacebookAccount, page.facebook_account_id)
    account.is_active = False
    post = ScheduledPost(
        source="google_sheet",
        source_key=source_identity_key("google_sheet", "sheet", "Posts", "revoked"),
        spreadsheet_id="sheet",
        worksheet="Posts",
        external_id="revoked",
        source_timezone="UTC",
        status="SCHEDULED",
        caption="Should not publish",
        facebook_page_id=page.id,
        scheduled_for_utc=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
    )
    session.add(post)
    session.commit()

    class Graph:
        def post(self, *args):
            pytest.fail("Graph must not be called for a disconnected Page")

    assert publish_claimed(session, claim_due(session), Graph()) == "FAILED"
    assert post.last_error_code == "PAGE_UNAVAILABLE"


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "192.168.1.1", "169.254.169.254", "::1"])
def test_private_media_hosts_rejected(monkeypatch, ip):
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", (ip, 443))])
    with pytest.raises(MediaError):
        validate_public_url("https://example.com/image.png")
    with pytest.raises(MediaError):
        validate_public_url("http://localhost/image.png")


@pytest.mark.parametrize(
    ("content_type", "body_kind", "expected"),
    [
        ("text/html", "html", "supported image"),
        ("image/png", "spoof", "does not match"),
        ("image/png", "oversize", "size limit"),
    ],
)
def test_media_rejects_html_spoofing_and_oversize(monkeypatch, content_type, body_kind, expected):
    body = {
        "html": b"<html>not an image</html>",
        "spoof": b"<html>pretend image</html>",
        "oversize": b"\x89PNG\r\n\x1a\n",
    }[body_kind]
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 80))]
    )

    class Response:
        status = 200

        def __init__(self):
            self.offset = 0

        def getheader(self, name):
            size = 5 * 1024 * 1024 if body_kind == "oversize" else len(body)
            return {"Content-Type": content_type, "Content-Length": str(size)}.get(name)

        def read(self, size):
            chunk = body[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("app.services.publishing.media.http.client.HTTPConnection", Connection)
    with pytest.raises(MediaError, match=expected):
        inspect_image("http://example.com/image.png")


def test_media_rejects_private_redirect(monkeypatch):
    def resolve(host, port, **kwargs):
        address = "127.0.0.1" if host == "localhost" else "8.8.8.8"
        return [(2, 1, 6, "", (address, port))]

    monkeypatch.setattr("socket.getaddrinfo", resolve)

    class Response:
        status = 302

        def getheader(self, name):
            return "http://localhost/internal" if name == "Location" else None

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("app.services.publishing.media.http.client.HTTPConnection", Connection)
    with pytest.raises(MediaError, match="not public"):
        inspect_image("http://example.com/image.png")


def test_http_page_isolation_and_admin_boundary(session):
    staff_role = Role(name="staff")
    unknown_role = Role(name="unknown")
    staff = session.scalar(select(User).where(User.username == "publisher"))
    staff.roles = [staff_role]
    other = User(
        username="other", email="other@example.com", password_hash="test", roles=[staff_role]
    )
    revoked = User(
        username="revoked", email="revoked@example.com", password_hash="test", roles=[unknown_role]
    )
    session.add_all([other, revoked])
    session.flush()
    other_account = FacebookAccount(
        user_id=other.id, facebook_user_id="other-fb", access_token_encrypted="encrypted"
    )
    session.add(other_account)
    session.flush()
    other_page = FacebookPage(facebook_account_id=other_account.id, page_id="page2", name="Other")
    session.add(other_page)
    session.flush()
    post = ScheduledPost(
        source="google_sheet",
        source_key=source_identity_key("google_sheet", "sheet", "Posts", "private"),
        spreadsheet_id="sheet",
        worksheet="Posts",
        external_id="private",
        source_timezone="UTC",
        status="SCHEDULED",
        caption="Private",
        facebook_page_id=other_page.id,
        scheduled_for_utc=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(post)
    session.commit()
    active = [staff]
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: active[0]
    try:
        client = TestClient(app)
        try:
            assert client.get("/api/v1/publishing/posts").json()["items"] == []
            assert client.get(f"/api/v1/publishing/posts/{post.uuid}").status_code == 404
            assert (
                client.put(
                    "/api/v1/publishing/config",
                    json={"spreadsheet_id": "sheet", "worksheet": "Posts", "timezone": "UTC"},
                ).status_code
                == 403
            )
            active[0] = other
            assert len(client.get("/api/v1/publishing/posts").json()["items"]) == 1
            active[0] = revoked
            assert client.get("/api/v1/publishing/posts").status_code == 403
        finally:
            client.close()
    finally:
        app.dependency_overrides.clear()
