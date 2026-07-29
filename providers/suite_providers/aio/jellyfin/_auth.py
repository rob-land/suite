"""AuthMixin — username/password + Quick Connect flows."""

import logging
from typing import Any

from ...media import AuthStatus
from ..base import ProviderAuthError, ProviderError, ProviderUnreachableError

log = logging.getLogger(__name__)


class AuthMixin:
    async def authenticate(
        self, credentials: dict[str, Any] | None,
    ) -> AuthStatus:
        creds = credentials or {}
        # If we already have a token, validate it cheaply.
        if creds.get("access_token") and creds.get("user_id"):
            try:
                await self._get(f"/Users/{creds['user_id']}", credentials=creds)
                return AuthStatus(ok=True)
            except ProviderAuthError:
                pass  # fall through to re-auth
        username = creds.get("username")
        password = creds.get("password", "")
        if not username:
            return AuthStatus(ok=False,
                              message="No Jellyfin username on file")
        return await self.authenticate_password(username, password)

    async def authenticate_password(
        self, username: str, password: str,
    ) -> AuthStatus:
        try:
            data = await self._post(
                "/Users/AuthenticateByName", credentials=None,
                json={"Username": username, "Pw": password},
            )
        except ProviderAuthError:
            return AuthStatus(ok=False, message="Wrong username or password.")
        except ProviderUnreachableError as exc:
            return AuthStatus(ok=False, message=f"Couldn't reach the server: {exc}")
        if not data or not data.get("AccessToken"):
            return AuthStatus(ok=False, message="Sign-in failed.")
        new_creds = {
            "access_token": data["AccessToken"],
            "user_id": data["User"]["Id"],
            "username": data["User"]["Name"],
        }
        return AuthStatus(ok=True, credentials=new_creds)

    # ── Quick Connect ──
    #
    # Three steps:
    #   1. Initiate — server hands back a short Code + a long Secret.
    #   2. Poll Connect with the Secret until Authenticated == True.
    #   3. AuthenticateWithQuickConnect to swap the Secret for a token.
    async def quick_connect_enabled(self) -> bool:
        try:
            data = await self._get("/QuickConnect/Enabled", credentials=None)
        except ProviderError:
            return False
        if isinstance(data, bool):
            return data
        if isinstance(data, str):
            return data.strip().lower() == "true"
        return False

    async def quick_connect_initiate(self) -> dict[str, str] | None:
        try:
            data = await self._post(
                "/QuickConnect/Initiate", credentials=None,
            )
        except ProviderError:
            log.exception("quick connect initiate failed")
            return None
        if not data or not data.get("Secret") or not data.get("Code"):
            return None
        return {"code": data["Code"], "secret": data["Secret"]}

    async def quick_connect_poll(self, secret: str) -> bool:
        try:
            data = await self._get(
                "/QuickConnect/Connect", credentials=None,
                params={"Secret": secret},
            )
        except ProviderAuthError:
            # Server may treat an expired secret as 401 — surface as
            # "not yet" so the dialog re-initiates.
            return False
        except ProviderError:
            return False
        return bool(data and data.get("Authenticated"))

    async def quick_connect_complete(self, secret: str) -> AuthStatus:
        try:
            data = await self._post(
                "/Users/AuthenticateWithQuickConnect", credentials=None,
                json={"Secret": secret},
            )
        except ProviderAuthError:
            return AuthStatus(ok=False,
                              message="Quick Connect code expired. Try again.")
        except ProviderUnreachableError as exc:
            return AuthStatus(ok=False, message=f"Couldn't reach the server: {exc}")
        if not data or not data.get("AccessToken"):
            return AuthStatus(ok=False, message="Quick Connect didn't return a token.")
        new_creds = {
            "access_token": data["AccessToken"],
            "user_id": data["User"]["Id"],
            "username": data["User"]["Name"],
        }
        return AuthStatus(ok=True, credentials=new_creds)
