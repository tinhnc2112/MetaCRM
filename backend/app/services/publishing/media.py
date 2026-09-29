"""Fetch a public image through a DNS-pinned connection with bounded redirects."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 3


class MediaError(ValueError):
    pass


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, port: int) -> None:
        super().__init__(host, port, timeout=10, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _resolve(url: str) -> tuple[str, str, int, str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise MediaError("Image URL must be HTTP(S)")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in {80, 443}:
            raise MediaError("Image URL port is not allowed")
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise MediaError("Image host is not public")
    except MediaError:
        raise
    except (OSError, ValueError) as exc:
        raise MediaError("Image host could not be validated") from exc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.hostname, addresses[0][4][0], port, path


def validate_public_url(url: str) -> None:
    _resolve(url)


def inspect_image(url: str) -> tuple[bytes, str]:
    for redirect_count in range(MAX_REDIRECTS + 1):
        host, ip, port, path = _resolve(url)
        parsed = urlsplit(url)
        connection = (
            _PinnedHTTPS(host, ip, port)
            if parsed.scheme == "https"
            else http.client.HTTPConnection(ip, port, timeout=10)
        )
        try:
            connection.request("GET", path, headers={"Host": host, "User-Agent": "MetaCRM/1.0"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirect_count == MAX_REDIRECTS:
                    raise MediaError("Invalid image redirect")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise MediaError("Image URL did not return success")
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
            if content_type not in {"image/jpeg", "image/png", "image/gif"}:
                raise MediaError("URL does not return a supported image")
            max_size = MAX_IMAGE_BYTES
            length = response.getheader("Content-Length")
            if length and int(length) > max_size:
                raise MediaError("Image exceeds provider size limit")
            size = 0
            signature = b""
            chunks: list[bytes] = []
            while chunk := response.read(64 * 1024):
                chunks.append(chunk)
                if len(signature) < 8:
                    signature += chunk[:8]
                size += len(chunk)
                if size > max_size:
                    raise MediaError("Image exceeds provider size limit")
            if size == 0:
                raise MediaError("Image is empty")
            if not (
                (content_type == "image/png" and signature.startswith(b"\x89PNG\r\n\x1a\n"))
                or (content_type == "image/jpeg" and signature.startswith(b"\xff\xd8\xff"))
                or (content_type == "image/gif" and signature.startswith((b"GIF87a", b"GIF89a")))
            ):
                raise MediaError("Image body does not match its MIME type")
            return b"".join(chunks), content_type
        except (OSError, ValueError) as exc:
            if isinstance(exc, MediaError):
                raise
            raise MediaError("Image could not be inspected") from exc
        finally:
            connection.close()
