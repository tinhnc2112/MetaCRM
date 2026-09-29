"""Narrow Sheets REST adapter using a server-side service account."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.core.config import get_settings
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class SheetError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class SheetsClient:
    def __init__(self) -> None:
        path = get_settings().google_service_account_file
        if not path:
            raise SheetError("Google service account is not configured")
        try:
            credentials = json.loads(Path(path).read_text(encoding="utf-8"))
            if credentials.get("type") != "service_account":
                raise ValueError("Invalid service account")
            self.email = credentials["client_email"]
            private_key = serialization.load_pem_private_key(
                credentials["private_key"].encode(), password=None
            )
            now = int(time.time())
            header = _b64(b'{"alg":"RS256","typ":"JWT"}')
            claims = _b64(
                json.dumps(
                    {
                        "iss": self.email,
                        "scope": SCOPE,
                        "aud": "https://oauth2.googleapis.com/token",
                        "iat": now,
                        "exp": now + 3600,
                    },
                    separators=(",", ":"),
                ).encode()
            )
            signed = f"{header}.{claims}".encode()
            signature = _b64(private_key.sign(signed, padding.PKCS1v15(), hashes.SHA256()))
            body = urlencode(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": f"{header}.{claims}.{signature}",
                }
            ).encode()
            request = Request("https://oauth2.googleapis.com/token", data=body, method="POST")
            with urlopen(request, timeout=10) as response:
                self.token = json.load(response)["access_token"]
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise SheetError("Google service account authentication failed") from exc

    def _request(self, method: str, url: str, payload: dict | None = None) -> dict:
        request = Request(
            url,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except (OSError, ValueError) as exc:
            raise SheetError("Google Sheets request failed") from exc

    @staticmethod
    def _base(spreadsheet_id: str) -> str:
        return f"https://sheets.googleapis.com/v4/spreadsheets/{quote(spreadsheet_id, safe='')}"

    def read(self, spreadsheet_id: str, worksheet: str) -> list[list[str]]:
        sheet_range = quote(f"'{worksheet.replace(chr(39), chr(39) * 2)}'!A:G", safe="")
        url = f"{self._base(spreadsheet_id)}/values/{sheet_range}"
        values = self._request("GET", f"{url}?valueRenderOption=FORMATTED_VALUE").get("values", [])
        formulas = self._request("GET", f"{url}?valueRenderOption=FORMULA").get("values", [])
        for index, row in enumerate(formulas):
            if len(row) > 3 and str(row[3]).startswith("=") and index < len(values):
                values[index] += [""] * max(0, 4 - len(values[index]))
                values[index][3] = row[3]
        return values

    def write_status(self, spreadsheet_id: str, worksheet: str, row: int, status: str) -> None:
        escaped = worksheet.replace("'", "''")
        sheet_range = quote(f"'{escaped}'!G{row}", safe="")
        url = f"{self._base(spreadsheet_id)}/values/{sheet_range}?valueInputOption=RAW"
        self._request(
            "PUT",
            url,
            {"range": f"'{escaped}'!G{row}", "majorDimension": "ROWS", "values": [[status]]},
        )
