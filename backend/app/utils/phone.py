"""Carrier-neutral phone normalization helpers."""

from __future__ import annotations

import re

_PHONE_CHARACTERS = re.compile(r"^[+\d\s().-]+$")


def normalize_phone(value: str, *, country_code: str = "VN") -> str:
    """Return a practical normalized phone value for validation and future matching."""
    display_value = value.strip()
    if not display_value or not _PHONE_CHARACTERS.fullmatch(display_value):
        raise ValueError("recipient_phone has an invalid format")

    digits = re.sub(r"\D", "", display_value)
    if not 8 <= len(digits) <= 15:
        raise ValueError("recipient_phone must contain between 8 and 15 digits")

    if display_value.startswith("+"):
        return f"+{digits}"
    if country_code.upper() == "VN":
        if digits.startswith("0"):
            return f"+84{digits[1:]}"
        if digits.startswith("84"):
            return f"+{digits}"
    return digits
