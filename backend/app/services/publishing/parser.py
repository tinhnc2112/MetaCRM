"""Pure parsing of the seven-column Sheet contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

HEADERS = ("ID", "Page", "Caption", "Image", "Publish Date", "Publish Time", "Status")
IMAGE_FORMULA = re.compile(r'^=IMAGE\("(https?://[^"\s]+)"\)$', re.IGNORECASE)
SHEET_STATUSES = {
    "",
    "Chưa đăng",
    "Đã lên lịch",
    "Đang đăng",
    "Đã đăng",
    "Không chắc chắn",
    "Đã hủy",
    "Lỗi",
}
IMPORTABLE_STATUSES = {"", "Chưa đăng"}


@dataclass(frozen=True)
class ParsedRow:
    external_id: str
    page: str
    caption: str
    image_url: str | None
    scheduled_for_utc: datetime
    row_number: int
    sheet_status: str


def parse_image(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value.startswith("="):
        match = IMAGE_FORMULA.fullmatch(value)
        if not match:
            raise ValueError("Invalid IMAGE formula")
        value = match.group(1)
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Image must be a public HTTP(S) URL")
    if len(value) > 2048:
        raise ValueError("Image URL is too long")
    return value


def parse_rows(
    values: list[list[str]], timezone: str
) -> tuple[list[ParsedRow], list[tuple[int, str, str]]]:
    if not values or tuple(values[0][:7]) != HEADERS:
        raise ValueError(
            "Sheet requires ID, Page, Caption, Image, Publish Date, Publish Time, Status headers"
        )
    zone = ZoneInfo(timezone)
    result: list[ParsedRow] = []
    errors: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for row_number, raw in enumerate(values[1:], 2):
        cells = (raw + [""] * 7)[:7]
        external_id, page, caption, image, date_value, time_value, status = [
            str(item) for item in cells
        ]
        external_id, page = external_id.strip(), page.strip()
        if not any(cells):
            continue
        try:
            if not external_id or len(external_id) > 255:
                raise ValueError("Missing or invalid ID")
            if external_id in seen:
                raise ValueError("Duplicate ID")
            seen.add(external_id)
            status = status.strip()
            if status not in SHEET_STATUSES:
                raise ValueError("Unknown Sheet Status")
            if not page:
                raise ValueError("Missing Page")
            if not caption.strip() and not image.strip():
                raise ValueError("Caption or Image is required")
            image_url = parse_image(image)
            date_text, time_text = date_value.strip(), time_value.strip()
            try:
                local = datetime.fromisoformat(f"{date_text}T{time_text}")
            except ValueError:
                local = datetime.strptime(f"{date_text} {time_text}", "%d/%m/%Y %H:%M")
            if local.tzinfo is not None:
                raise ValueError("Use local date and time without an offset")
            aware = local.replace(tzinfo=zone)
            if aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local:
                raise ValueError("Publish time does not exist in timezone")
            if aware.replace(fold=1).utcoffset() != aware.utcoffset():
                raise ValueError("Publish time is ambiguous in timezone")
            result.append(
                ParsedRow(
                    external_id,
                    page,
                    caption,
                    image_url,
                    aware.astimezone(UTC),
                    row_number,
                    status,
                )
            )
        except ValueError as exc:
            errors.append((row_number, external_id, str(exc)))
    return result, errors
