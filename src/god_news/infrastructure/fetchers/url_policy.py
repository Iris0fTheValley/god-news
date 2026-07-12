from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from god_news.errors import FetchPolicyError


def normalize_allowed_ports(values: Iterable[int | str]) -> tuple[int, ...]:
    return tuple(int(value) for value in values)


@dataclass(frozen=True, slots=True)
class UrlPolicy:
    allow_private: bool = False
    allowed_ports: tuple[int, ...] = (80, 443)

    async def validate(self, url: str) -> str:
        return await asyncio.to_thread(self.validate_sync, url)

    def validate_sync(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise FetchPolicyError("Only http and https source URLs are allowed.")
        if parsed.username is not None or parsed.password is not None:
            raise FetchPolicyError("Source URLs cannot contain credentials.")
        hostname = parsed.hostname
        if not hostname:
            raise FetchPolicyError("Source URL must include a hostname.")
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        if port not in self.allowed_ports:
            raise FetchPolicyError("Source URL uses a disallowed port.")
        if self.allow_private:
            return url

        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None
        addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        if literal is not None:
            addresses.add(literal)
        else:
            try:
                records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise FetchPolicyError("Source hostname could not be resolved.") from exc
            for record in records:
                addresses.add(ipaddress.ip_address(record[4][0]))
        if not addresses or any(not address.is_global for address in addresses):
            raise FetchPolicyError("Source URL resolves to a non-public network address.")
        return url
