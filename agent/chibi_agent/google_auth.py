"""Google sign-in for Calendar and Gmail, read-only (docs/scope.md -> M5).

Kryo makes the Desktop OAuth client in the Google Cloud console, saves its JSON
as %APPDATA%\\ChibiAgent\\google_client.json and signs in from the tray: the
browser opens Google's own page and Kryo completes it there (never automated).
Several accounts can be signed in; each one's refresh token is kept in Windows
Credential Manager (keyring, user "google:<email>"), with the list of accounts
under "google:accounts" since keyring can't enumerate. Access tokens live in memory.

The OAuth app is in Testing mode, so Google expires a sign-in after 7 days: that
account is dropped and Kryo is told to sign in again.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time

import httpx
import keyring
from chibi_shared import paths

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly",
          "https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_FILE = paths.DATA / "google_client.json"
SERVICE, INDEX = "ChibiAgent", "google:accounts"
PRIMARY = "https://www.googleapis.com/calendar/v3/calendars/primary"


class NotConnected(Exception):
    """No usable sign-in for an account: Kryo has to sign in from the tray."""


def short(email: str) -> str:
    """What she says aloud for an account: the part before the @."""
    return email.split("@", 1)[0]


class GoogleAuth:
    def __init__(self, client_file=CLIENT_FILE, store=keyring, transport: httpx.AsyncBaseTransport | None = None):
        self.client_file, self.store, self.transport = client_file, store, transport
        self._cache: dict[str, tuple[str, float]] = {}  # email -> (access token, expires)
        self._locks: dict[str, asyncio.Lock] = {}  # one per account: refreshes run side by side

    # --- the account list ----------------------------------------------------------
    def _get(self, user: str) -> str | None:
        try:
            return self.store.get_password(SERVICE, user)
        except Exception as e:  # no credential backend
            log.warning("keyring unavailable: %s", e)
            return None

    def _save_index(self, emails: list[str]) -> None:
        if emails:
            self.store.set_password(SERVICE, INDEX, json.dumps(emails))
        else:
            self._delete(INDEX)

    def _delete(self, user: str) -> None:
        try:
            self.store.delete_password(SERVICE, user)
        except Exception:  # already gone
            pass

    def accounts(self) -> list[str]:
        """Signed-in accounts, in sign-in order."""
        try:
            emails = json.loads(self._get(INDEX) or "[]")
        except ValueError:
            emails = []
        return [e for e in emails if self._get(f"google:{e}")]

    @property
    def connected(self) -> bool:
        return bool(self.accounts())

    # --- signing in and out ------------------------------------------------------------
    def _client(self) -> dict:
        if not self.client_file.exists():
            raise NotConnected(f"The Google client file is missing. Save it as {self.client_file}.")
        data = json.loads(self.client_file.read_text(encoding="utf-8"))
        return data.get("installed") or data.get("web") or data

    def _run_flow(self):
        """Google's own page in Kryo's browser, with the account chooser every time."""
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(self.client_file), SCOPES)
        return flow.run_local_server(port=0, open_browser=True, prompt="select_account consent",
                                     timeout_seconds=300,
                                     success_message="Raphael is connected. You may close this tab.")

    async def _whoami(self, token: str) -> str:
        """The account's email: the id of its primary calendar."""
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as c:
            r = await c.get(PRIMARY, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return r.json()["id"]

    async def sign_in(self) -> str:
        """Add (or renew) one account; returns its email."""
        self._client()  # fail early, with the path, if the file is missing
        creds = await asyncio.to_thread(self._run_flow)
        if not creds.refresh_token:
            raise NotConnected("Google returned no refresh token. Sign in again.")
        email = (await self._whoami(creds.token)).lower()
        self.store.set_password(SERVICE, f"google:{email}", creds.refresh_token)
        emails = self.accounts()
        self._save_index(emails if email in emails else [*emails, email])
        self._cache[email] = (creds.token, time.time() + 3000)
        log.info("google connected: %s", email)
        return email

    def sign_out(self, email: str | None = None) -> None:
        """Sign out one account, or all of them."""
        emails = self.accounts()
        gone = [email.lower()] if email else emails
        for e in gone:
            self._delete(f"google:{e}")
            self._cache.pop(e, None)
        self._save_index([e for e in emails if e not in gone])
        log.info("google signed out: %s", ", ".join(gone) or "nothing")

    # --- tokens --------------------------------------------------------------------
    async def token(self, email: str) -> str:
        """A valid access token for this account, refreshed when needed. Raises NotConnected."""
        async with self._locks.setdefault(email, asyncio.Lock()):
            tok, exp = self._cache.get(email, ("", 0.0))
            if tok and time.time() < exp - 60:
                return tok
            refresh = self._get(f"google:{email}")
            if not refresh:
                raise NotConnected(f"{short(email)} is not signed in.")
            c = self._client()
            from google.auth.exceptions import RefreshError
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            creds = Credentials(None, refresh_token=refresh, client_id=c["client_id"],
                                client_secret=c.get("client_secret"),
                                token_uri=c.get("token_uri", "https://oauth2.googleapis.com/token"),
                                scopes=SCOPES)
            try:
                await asyncio.to_thread(creds.refresh, Request())
            except RefreshError as e:
                if "invalid_grant" in str(e):  # expired (Testing: 7 days), revoked, or password changed
                    self.sign_out(email)
                    raise NotConnected(f"the sign-in for {short(email)} has expired") from e
                raise
            exp = creds.expiry.replace(tzinfo=dt.timezone.utc).timestamp() if creds.expiry else time.time() + 3000
            self._cache[email] = (creds.token, exp)
            return creds.token
