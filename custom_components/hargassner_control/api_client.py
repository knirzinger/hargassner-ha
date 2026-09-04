"""
Hargassner Connect — async API client for Home Assistant.

Reverse-engineered from web.hargassner.at network traffic.

Authentication
--------------
JSON login against ``/api/auth/login`` with the user's email + password plus the
*public* application ``client_id`` / ``client_secret`` that ship inside the
Connect web client. Those two are not user secrets; they are hardcoded in
``const.py`` (see the note there). If a hardcoded value is ever rejected, the
client falls back to re-extracting the values from the live JS bundle, which is
a hashed Vite build discovered via ``/build/manifest.json``.

Until September 2026 the portal used an OAuth 2.0 ROPC grant at
``/oauth/token``. That endpoint has been removed and answers HTTP 404; it is
still tried as a fallback, but only after the current endpoint 404s.

The user only ever provides email + password.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    API_URL,
    APP_BRANDING,
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIENT_SECRET,
    LEGACY_TOKEN_URL,
    LOGIN_URL,
    MANIFEST_URL,
    PORTAL_URL,
    REFRESH_URL,
    USER_AGENT,
    WIDGET_HEATER,
)

_LOGGER = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 1800.0  # fallback when the API reports no expires_in
TOKEN_RENEW_MARGIN = 300.0  # renew this many seconds before the server expiry
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=25)

# Fallback only. Extracts the OAuth client_id/secret from the minified JS bundle
# by anchoring on the call site (``client_id:<var>,client_secret:<var>``) and
# then resolving each variable's string assignment — robust against the minified
# variable names changing between deploys.
_ANCHOR_RE = re.compile(r"client_id:(\w+),client_secret:(\w+)")
_LEGACY_APP_JS = f"{PORTAL_URL}/js/app.js"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class HargassnerError(Exception):
    """Base exception for all Hargassner API errors."""


class HargassnerAuthError(HargassnerError):
    """Raised when authentication fails (bad email/password or revoked token)."""


class HargassnerConnectionError(HargassnerError):
    """Raised on network-level failures."""


class HargassnerApiError(HargassnerError):
    """Raised when the API returns an unexpected status code."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(f"API returned {status}: {message}")


class HargassnerSecretError(HargassnerError):
    """Raised when client credentials cannot be extracted from the JS bundle."""


# ---------------------------------------------------------------------------
# Parsed data model (generic — mirrors the live /widgets payload)
# ---------------------------------------------------------------------------

@dataclass
class ParamInfo:
    """A single writable parameter from a widget's ``parameters`` block."""

    key: str
    resource: str | None = None
    value: Any = None
    options: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Widget:
    """One widget from the /widgets payload."""

    type: str
    number: str | None
    name: str
    values: dict[str, Any]
    parameters: dict[str, ParamInfo]
    actions: dict[str, str]  # action key -> resource URL


@dataclass
class HargassnerData:
    """Complete parsed state returned by GET /widgets."""

    widgets: list[Widget] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def widget(self, prefix: str) -> Widget | None:
        for w in self.widgets:
            if w.type.startswith(prefix):
                return w
        return None

    def param(self, prefix: str, key: str) -> ParamInfo | None:
        w = self.widget(prefix)
        return w.parameters.get(key) if w else None

    def action(self, prefix: str, key: str) -> str | None:
        w = self.widget(prefix)
        return w.actions.get(key) if w else None

    def value(self, prefix: str, key: str, default: Any = None) -> Any:
        w = self.widget(prefix)
        if w and isinstance(w.values, dict):
            return w.values.get(key, default)
        return default

    @property
    def online(self) -> bool:
        return bool(self.meta.get("online_state", True))

    @property
    def device_name(self) -> str:
        w = self.widget(WIDGET_HEATER)
        if w and w.values.get("name"):
            return str(w.values["name"])
        return "Hargassner"

    @property
    def device_model(self) -> str:
        w = self.widget(WIDGET_HEATER)
        if w and w.values.get("device_type"):
            return str(w.values["device_type"])
        return "Pellematic"


# ---------------------------------------------------------------------------
# In-memory token cache
# ---------------------------------------------------------------------------

@dataclass
class _TokenCache:
    access_token: str = ""
    refresh_token: str = ""
    fetched_at: float = 0.0
    ttl: float = TOKEN_TTL_SECONDS

    def is_valid(self) -> bool:
        return bool(self.access_token) and (
            time.monotonic() - self.fetched_at < self.ttl
        )

    def store(
        self,
        token: str,
        refresh: str | None = None,
        expires_in: Any = None,
    ) -> None:
        self.access_token = token
        if refresh:
            self.refresh_token = refresh
        try:
            if expires_in:
                self.ttl = max(60.0, float(expires_in) - TOKEN_RENEW_MARGIN)
        except (TypeError, ValueError):
            self.ttl = TOKEN_TTL_SECONDS
        self.fetched_at = time.monotonic()

    def invalidate(self) -> None:
        self.access_token = ""
        self.fetched_at = 0.0

    def clear(self) -> None:
        self.invalidate()
        self.refresh_token = ""


# ---------------------------------------------------------------------------
# Main API client
# ---------------------------------------------------------------------------

class HargassnerApiClient:
    """Async client for the Hargassner Connect REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        installation_id: str | int | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._installation_id: str | None = (
            str(installation_id) if installation_id else None
        )
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._scraped = False
        self._token = _TokenCache()
        self._token_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def installation_id(self) -> str | None:
        return self._installation_id

    @installation_id.setter
    def installation_id(self, value: str | int) -> None:
        self._installation_id = str(value)

    def _headers(self, auth: bool = True) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Branding": APP_BRANDING}
        if auth and self._token.access_token:
            headers["Authorization"] = f"Bearer {self._token.access_token}"
        return headers

    # ------------------------------------------------------------------
    # Credential handling
    # ------------------------------------------------------------------

    async def _async_scrape_credentials(self) -> tuple[str, str]:
        """
        Fallback: extract client_id/secret from the live JS bundle.

        Discovers the current hashed entry bundle via the Vite manifest (with an
        HTML and legacy fallback), then extracts by call-site anchor.
        """
        js = ""
        # 1) Vite manifest -> entry bundle
        try:
            async with self._session.get(
                MANIFEST_URL, headers=self._headers(auth=False), timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 200:
                    manifest = await resp.json(content_type=None)
                    entry = next(
                        (v["file"] for v in manifest.values()
                         if isinstance(v, dict) and v.get("isEntry")
                         and str(v.get("file", "")).endswith(".js")),
                        None,
                    )
                    if entry:
                        js = await self._async_fetch_text(f"{PORTAL_URL}/build/{entry}")
        except (aiohttp.ClientError, ValueError) as exc:
            _LOGGER.debug("Manifest discovery failed: %s", exc)

        # 2) HTML fallback — find build/assets/app-*.js
        if not js:
            html = await self._async_fetch_text(PORTAL_URL)
            m = re.search(r"build/assets/app-[\w-]+\.js", html or "")
            if m:
                js = await self._async_fetch_text(f"{PORTAL_URL}/{m.group(0)}")

        # 3) Legacy fallback — old static bundle
        if not js:
            js = await self._async_fetch_text(_LEGACY_APP_JS)

        if not js:
            raise HargassnerSecretError(
                "Could not fetch the Hargassner Connect JS bundle to extract "
                "the application client credentials."
            )

        anchor = _ANCHOR_RE.search(js)
        if anchor:
            id_var, sec_var = anchor.group(1), anchor.group(2)
            cid_m = re.search(rf'\b{id_var}="([^"]+)"', js)
            sec_m = re.search(rf'\b{sec_var}="([^"]+)"', js)
            if cid_m and sec_m:
                _LOGGER.info("Re-extracted client credentials from portal bundle")
                return cid_m.group(1), sec_m.group(1)

        # Legacy direct-object pattern
        legacy = re.search(r'o="(\d+)",n="([^"]+)"', js)
        if legacy:
            return legacy.group(1), legacy.group(2)

        raise HargassnerSecretError(
            "Could not locate the application client credentials in the portal "
            "JS bundle. The structure may have changed — please open a GitHub "
            "issue."
        )

    async def _async_fetch_text(self, url: str) -> str:
        try:
            async with self._session.get(
                url, headers=self._headers(auth=False), timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("GET %s -> HTTP %s", url, resp.status)
                    return ""
                return await resp.text()
        except aiohttp.ClientError as exc:
            _LOGGER.debug("GET %s failed: %s", url, exc)
            return ""

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap(body: Any) -> dict[str, Any]:
        """Return the token object, whether or not it is wrapped in ``data``."""
        if not isinstance(body, dict):
            return {}
        inner = body.get("data")
        if isinstance(inner, dict) and "access_token" in inner:
            return inner
        return body

    async def _post_json(
        self, url: str, payload: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        try:
            async with self._session.post(
                url,
                json=payload,
                headers=self._headers(auth=False),
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 200:
                    return resp.status, await resp.json(content_type=None)
                body = await resp.text()
                _LOGGER.debug("POST %s -> HTTP %s: %s", url, resp.status, body[:200])
                return resp.status, {}
        except aiohttp.ClientError as exc:
            raise HargassnerConnectionError(
                f"Network error during POST {url}: {exc}"
            ) from exc

    async def _post_legacy_token(
        self, cid: str, csec: str
    ) -> tuple[int, dict[str, Any]]:
        """Pre-September-2026 OAuth password grant. Kept as a fallback only."""
        payload = {
            "grant_type": "password",
            "client_id": cid,
            "client_secret": csec,
            "username": self._username,
            "password": self._password,
        }
        try:
            async with self._session.post(
                LEGACY_TOKEN_URL,
                data=payload,
                headers=self._headers(auth=False),
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 200:
                    return resp.status, await resp.json(content_type=None)
                body = await resp.text()
                _LOGGER.debug(
                    "Legacy token endpoint HTTP %s: %s", resp.status, body[:200]
                )
                return resp.status, {}
        except aiohttp.ClientError as exc:
            raise HargassnerConnectionError(
                f"Network error during legacy token fetch: {exc}"
            ) from exc

    async def _async_login(self, cid: str, csec: str) -> tuple[int, dict[str, Any]]:
        """Log in against the current endpoint, falling back to the old one."""
        status, body = await self._post_json(
            LOGIN_URL,
            {
                "email": self._username,
                "password": self._password,
                "client_id": cid,
                "client_secret": csec,
            },
        )
        if status == 404:
            _LOGGER.debug(
                "%s returned 404 — trying the legacy OAuth token endpoint",
                LOGIN_URL,
            )
            status, body = await self._post_legacy_token(cid, csec)
        return status, body

    async def _async_try_refresh(self) -> str:
        """Exchange the refresh token for a new access token. '' on failure."""
        cid = self._client_id or DEFAULT_CLIENT_ID
        csec = self._client_secret or DEFAULT_CLIENT_SECRET
        status, body = await self._post_json(
            REFRESH_URL,
            {
                "refresh_token": self._token.refresh_token,
                "client_id": cid,
                "client_secret": csec,
            },
        )
        if status != 200:
            _LOGGER.debug(
                "Refresh failed (HTTP %s) — falling back to a full login", status
            )
            self._token.clear()
            return ""

        data = self._unwrap(body)
        token = data.get("access_token", "")
        if token:
            self._token.store(
                token, data.get("refresh_token"), data.get("expires_in")
            )
        else:
            self._token.clear()
        return token

    async def _async_fetch_token(self) -> str:
        """Obtain a valid Bearer token, refreshing/re-authenticating as needed."""
        async with self._token_lock:
            if self._token.is_valid():
                return self._token.access_token

            if self._token.refresh_token:
                refreshed = await self._async_try_refresh()
                if refreshed:
                    return refreshed

            cid = self._client_id or DEFAULT_CLIENT_ID
            csec = self._client_secret or DEFAULT_CLIENT_SECRET

            status, body = await self._async_login(cid, csec)

            # Built-in client credentials rejected — try re-extracting once.
            if status in (400, 401) and not self._scraped:
                _LOGGER.warning(
                    "Login rejected with the built-in client credentials; "
                    "re-extracting them from the portal bundle"
                )
                cid, csec = await self._async_scrape_credentials()
                self._scraped = True
                status, body = await self._async_login(cid, csec)

            if status in (401, 403, 422):
                raise HargassnerAuthError(
                    "Authentication failed — please check your Hargassner "
                    "Connect email and password."
                )
            if status != 200:
                raise HargassnerApiError(status, f"Login endpoint error ({LOGIN_URL})")

            data = self._unwrap(body)
            token = data.get("access_token", "")
            if not token:
                raise HargassnerAuthError(
                    "Login succeeded but returned no access_token."
                )

            self._client_id, self._client_secret = cid, csec
            self._token.store(
                token, data.get("refresh_token"), data.get("expires_in")
            )
            _LOGGER.debug(
                "Bearer token cached for %.0fs (refresh_token %s)",
                self._token.ttl,
                "present" if self._token.refresh_token else "absent",
            )
            return token

    async def async_validate_credentials(self) -> str:
        """Validate email/password by performing a fresh login."""
        self._token.clear()
        return await self._async_fetch_token()

    # ------------------------------------------------------------------
    # HTTP helpers (authenticated, with 401 retry)
    # ------------------------------------------------------------------

    async def _async_request(
        self, method: str, url: str, *, json: Any = None, _retry: bool = True
    ) -> aiohttp.ClientResponse:
        await self._async_fetch_token()
        try:
            resp = await self._session.request(
                method, url, headers=self._headers(), json=json, timeout=REQUEST_TIMEOUT
            )
        except aiohttp.ClientError as exc:
            raise HargassnerConnectionError(f"Request failed [{method} {url}]: {exc}") from exc

        if resp.status == 401 and _retry:
            _LOGGER.debug("401 received — re-authenticating and retrying")
            self._token.clear()
            await self._async_fetch_token()
            return await self._async_request(method, url, json=json, _retry=False)

        return resp

    async def _async_get(self, url: str) -> Any:
        resp = await self._async_request("GET", url)
        if resp.status != 200:
            raise HargassnerApiError(resp.status, f"GET {url}")
        return await resp.json(content_type=None)

    # ------------------------------------------------------------------
    # Installation discovery
    # ------------------------------------------------------------------

    async def async_discover_installation_id(self) -> list[dict[str, Any]]:
        """Return a list of installations accessible to this account."""
        for endpoint in (
            f"{API_URL}/installations",
            f"{API_URL}/user/installations",
        ):
            try:
                raw = await self._async_get(endpoint)
            except HargassnerApiError as exc:
                if exc.status == 404:
                    _LOGGER.debug("Endpoint %s returned 404, trying next", endpoint)
                    continue
                raise
            installations = self._parse_installations(raw)
            if installations:
                _LOGGER.debug("Discovered %d installation(s) via %s",
                              len(installations), endpoint)
                return installations

        raise HargassnerError(
            "Could not auto-discover any Hargassner installations for this account."
        )

    @staticmethod
    def _parse_installations(raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, dict):
            raw = raw.get("data", raw.get("installations", []))
        if isinstance(raw, list):
            return [
                {
                    "id": str(item.get("id", "")),
                    "name": item.get("name", f"Installation {item.get('id', '?')}"),
                }
                for item in raw
                if isinstance(item, dict) and item.get("id")
            ]
        return []

    # ------------------------------------------------------------------
    # Read — GET /widgets
    # ------------------------------------------------------------------

    async def async_get_data(self) -> HargassnerData:
        """Fetch and parse the complete installation state."""
        if not self._installation_id:
            raise HargassnerError("Installation ID not set.")
        raw = await self._async_get(
            f"{API_URL}/installations/{self._installation_id}/widgets"
        )
        return self._parse(raw)

    @staticmethod
    def _parse(raw: dict) -> HargassnerData:
        widgets: list[Widget] = []
        for w in raw.get("data", []):
            wtype = w.get("widget", "")
            vals = w.get("values", {})
            values = vals if isinstance(vals, dict) else {}

            params: dict[str, ParamInfo] = {}
            for key, entry in (w.get("parameters") or {}).items():
                if not isinstance(entry, dict):
                    continue
                if "resource" not in entry and "value" not in entry:
                    continue
                params[key] = ParamInfo(
                    key=key,
                    resource=entry.get("resource"),
                    value=entry.get("value"),
                    options=entry.get("options"),
                    minimum=entry.get("min"),
                    maximum=entry.get("max"),
                    step=entry.get("step"),
                    unit=entry.get("unit"),
                    raw=entry,
                )

            actions: dict[str, str] = {}
            for key, entry in (w.get("actions") or {}).items():
                if isinstance(entry, dict) and entry.get("resource"):
                    actions[key] = entry["resource"]

            widgets.append(
                Widget(
                    type=wtype,
                    number=w.get("number"),
                    name=str(values.get("name") or wtype.replace("_", " ").title()),
                    values=values,
                    parameters=params,
                    actions=actions,
                )
            )

        return HargassnerData(widgets=widgets, meta=raw.get("meta", {}))

    # ------------------------------------------------------------------
    # Write — generic, resource-based
    # ------------------------------------------------------------------

    async def async_patch_resource(self, resource: str, value: Any) -> None:
        """PATCH a parameter's resource URL with a new value."""
        url = f"{API_URL}{resource}"
        resp = await self._async_request("PATCH", url, json={"value": value})
        if resp.status not in (200, 204):
            raise HargassnerApiError(resp.status, f"PATCH {resource}")
        _LOGGER.debug("PATCH %s = %r [%s]", resource, value, resp.status)

    async def async_post_action(self, resource: str) -> None:
        """POST to an action resource URL."""
        url = f"{API_URL}{resource}"
        resp = await self._async_request("POST", url)
        if resp.status not in (200, 204):
            raise HargassnerApiError(resp.status, f"POST {resource}")
        _LOGGER.debug("POST %s [%s]", resource, resp.status)
