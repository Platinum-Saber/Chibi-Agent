"""What the Google tools (calendar, gmail) share: read every signed-in account at
once over one pooled client, and turn one account's failure into a line instead
of failing the whole answer."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from ..google_auth import NotConnected, short
from . import CTX

T = TypeVar("T")


def not_connected(service: str) -> str:
    return (f"Google {service} is not connected. Kryo can choose 'Google accounts', "
            "then 'Add Google account' in the tray.")


def reason(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 403:
            return "Google refused access (an admin may block this app)"
        if code == 401:
            return "Google rejected the sign-in"
        return f"Google answered {code}"
    if isinstance(e, NotConnected):
        return str(e)
    return f"Google could not be reached ({type(e).__name__})"


def accounts() -> list[str]:
    return CTX.google.accounts() if CTX.google is not None else []


async def each_account(base_url: str, transport: httpx.AsyncBaseTransport | None,
                       fn: Callable[[httpx.AsyncClient, dict, str], Awaitable[T]],
                       emails: list[str]) -> tuple[list[tuple[str, T]], list[str]]:
    """Run fn(client, auth_headers, email) for every account at the same time.
    Returns ([(email, result)], [problem lines]); other errors propagate."""
    async with httpx.AsyncClient(base_url=base_url, transport=transport, timeout=15,
                                 limits=httpx.Limits(max_connections=12)) as c:
        async def one(email: str) -> T:
            token = await CTX.google.token(email)
            return await fn(c, {"Authorization": f"Bearer {token}"}, email)
        results = await asyncio.gather(*(one(e) for e in emails), return_exceptions=True)
    done, problems = [], []
    for email, res in zip(emails, results):
        if isinstance(res, (NotConnected, httpx.HTTPError)):
            problems.append(f"Could not read {short(email)}: {reason(res)}. Kryo can sign in again from the tray.")
        elif isinstance(res, BaseException):
            raise res
        else:
            done.append((email, res))
    return done, problems
