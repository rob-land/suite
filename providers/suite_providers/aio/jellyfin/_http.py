"""HttpMixin — shared HTTP plumbing for the Jellyfin provider."""

from typing import Any

import httpx

from ..base import ProviderAuthError, ProviderUnreachableError
from ._helpers import emby_auth_header


class HttpMixin:
    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.server_url,
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(
                    max_connections=8,
                    max_keepalive_connections=4,
                ),
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self, credentials: dict[str, Any] | None) -> dict[str, str]:
        token = (credentials or {}).get("access_token")
        return {
            "X-Emby-Authorization": emby_auth_header(token),
            "Accept": "application/json",
        }

    def _user_id(self, credentials: dict[str, Any] | None) -> str:
        creds = credentials or {}
        uid = creds.get("user_id")
        if not uid:
            raise ProviderAuthError("not signed in to Jellyfin")
        return uid

    async def _get(
        self, path: str, credentials: dict[str, Any] | None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        client = await self._http()
        try:
            r = await client.get(path, params=params,
                                 headers=self._headers(credentials))
        except httpx.HTTPError as exc:
            raise ProviderUnreachableError(str(exc)) from exc
        if r.status_code == 401:
            raise ProviderAuthError("Jellyfin rejected the access token")
        r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    async def _post(
        self, path: str, credentials: dict[str, Any] | None,
        json: Any = None, params: dict[str, Any] | None = None,
    ) -> Any:
        client = await self._http()
        try:
            r = await client.post(path, json=json, params=params,
                                  headers=self._headers(credentials))
        except httpx.HTTPError as exc:
            raise ProviderUnreachableError(str(exc)) from exc
        if r.status_code == 401:
            raise ProviderAuthError("Jellyfin rejected the access token")
        r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    async def _delete(
        self, path: str, credentials: dict[str, Any] | None,
    ) -> Any:
        client = await self._http()
        try:
            r = await client.delete(path,
                                    headers=self._headers(credentials))
        except httpx.HTTPError as exc:
            raise ProviderUnreachableError(str(exc)) from exc
        if r.status_code == 401:
            raise ProviderAuthError("Jellyfin rejected the access token")
        r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return None
        return r.json()
