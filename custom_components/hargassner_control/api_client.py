"""
Hargassner Connect – async API client for Home Assistant.

Reverse-engineered from web.hargassner.at network traffic.

Authentication
--------------
OAuth 2.0 ROPC flow.  Both ``client_id`` and ``client_secret`` are extracted
at runtime from a single, stable JS file:

    https://web.hargassner.at/js/app.js

The file has no cache-busting hash, making it a reliable fetch target.
The regex  o=\"(\d+)\",n=\"([^\"]+)\"  reliably captures both values.

No credentials are hardcoded.  No user input beyond email + password.
Self-heals automatically if Hargassner rotate the values.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORTAL_URL  = "https://web.hargassner.at"
TOKEN_URL   = f"{PORTAL_URL}/oauth/token"
API_BASE    = f"{PORTAL_URL}/api/installations"
APP_JS_URL  = f"{PORTAL_URL}/js/app.js"

TOKEN_TTL_SECONDS = 1800   # 30 min safety margin (real TTL ~3600 s)
REQUEST_TIMEOUT   = aiohttp.ClientTimeout(total=20)

# Extracts client_id (group 1) and client_secret (group 2) from app.js.
# Pattern confirmed against the live bundle: o="1",n="aSYsAYj7..."
# NOTE: client_secret is a PUBLIC APPLICATION IDENTIFIER embedded in the
# Hargassner Connect web app — it is NOT a user credential or secret key.
# It is extracted dynamically at runtime so that rotations are handled
# automatically without any user action or integration update.
_OAUTH_CREDS_RE = re.compile(r'o=\"(\d+)\",n=\"([^\"]+)\"')


# ---------------------------------------------------------------------------
# Domain enums  (values are lowercase — used as HA translation keys)
# The API itself uses uppercase MODE_* strings; conversion happens in
# _parse_widgets (API → HA) and async_set_* (HA → API).
# ---------------------------------------------------------------------------

class HeatingMode(StrEnum):
    AUTOMATIC = "mode_automatic"
    HEATING   = "mode_heating"
    REDUCTION = "mode_reduction"
    OFF       = "mode_off"


class SolarMode(StrEnum):
    ON  = "mode_on"
    OFF = "mode_off"


class BathroomHeating(StrEnum):
    ON  = "mode_on"
    OFF = "mode_off"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class HargassnerError(Exception):
    """Base exception for all Hargassner API errors."""


class HargassnerAuthError(HargassnerError):
    """Raised when authentication fails (bad credentials or revoked token)."""


class HargassnerConnectionError(HargassnerError):
    """Raised on network-level failures."""


class HargassnerApiError(HargassnerError):
    """Raised when the API returns an unexpected status code."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(f"API returned {status}: {message}")


class HargassnerSecretError(HargassnerError):
    """
    Raised when client_id/client_secret cannot be extracted from app.js.

    This means the JS structure has changed.  Open a GitHub issue so the
    regex pattern can be updated.
    """


# ---------------------------------------------------------------------------
# Data classes (parsed from GET /widgets)
# ---------------------------------------------------------------------------

@dataclass
class HeatingCircuitData:
    mode: str                                   = "unknown"
    room_temp_correction: float                 = 0.0
    room_temp_heating: float                    = 20.0
    room_temp_reduction: float                  = 18.0
    steepness: float                            = 1.5
    deactivation_limit_heating: float           = 15.0
    deactivation_limit_reduction_day: float     = 15.0
    deactivation_limit_reduction_night: float   = 15.0
    bathroom_heating: str                       = "mode_off"


@dataclass
class BoilerData:
    temperature: float | None  = None
    state: str                 = "unknown"
    setpoint: float | None     = None


@dataclass
class BufferData:
    solar_mode_active: str    = "mode_off"
    temperature: float | None = None


@dataclass
class HotWaterData:
    temperature: float | None = None
    setpoint: float | None    = None


@dataclass
class WidgetSnapshot:
    """Complete parsed state returned by GET /widgets."""
    heating_circuit: HeatingCircuitData = field(default_factory=HeatingCircuitData)
    boiler: BoilerData                  = field(default_factory=BoilerData)
    buffer: BufferData                  = field(default_factory=BufferData)
    hot_water: HotWaterData             = field(default_factory=HotWaterData)
    pellet_stock_kg: float | None       = None
    raw: dict[str, Any]                 = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# In-memory token cache
# ---------------------------------------------------------------------------

@dataclass
class _TokenCache:
    access_token: str = ""
    fetched_at: float = 0.0

    def is_valid(self) -> bool:
        return bool(self.access_token) and (
            time.monotonic() - self.fetched_at < TOKEN_TTL_SECONDS
        )

    def store(self, token: str) -> None:
        self.access_token = token
        self.fetched_at = time.monotonic()
        _LOGGER.debug("Bearer token cached (TTL %s s)", TOKEN_TTL_SECONDS)

    def invalidate(self) -> None:
        self.access_token = ""
        self.fetched_at = 0.0


# ---------------------------------------------------------------------------
# Main API client
# ---------------------------------------------------------------------------

class HargassnerApiClient:
    """
    Async client for the Hargassner Connect REST API.

    Lifecycle
    ---------
    1.  Instantiate with ``session``, ``username``, ``password`` only.
    2.  Call ``async_validate_credentials()`` — fetches app.js, extracts
        client_id + client_secret, then performs the ROPC token grant.
    3.  Call ``async_discover_installation_id()`` — returns available
        installations for auto-selection.
    4.  The coordinator calls ``async_get_widgets()`` on every poll.
    5.  Control entities call the ``async_set_*`` methods on user interaction.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        installation_id: str | int | None = None,
    ) -> None:
        self._session          = session
        self._username         = username
        self._password         = password
        self._installation_id: str | None = str(installation_id) if installation_id else None
        self._client_id: str | None       = None
        self._client_secret: str | None   = None
        self._token            = _TokenCache()
        self._token_lock       = asyncio.Lock()
        self._creds_lock       = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def installation_id(self) -> str | None:
        return self._installation_id

    @installation_id.setter
    def installation_id(self, value: str | int) -> None:
        self._installation_id = str(value)

    @property
    def _api_base(self) -> str:
        if not self._installation_id:
            raise HargassnerError(
                "Installation ID not set — call async_discover_installation_id() first."
            )
        return f"{API_BASE}/{self._installation_id}"

    # ------------------------------------------------------------------
    # Step 1 — Extract client_id + client_secret from app.js
    # ------------------------------------------------------------------

    async def async_discover_oauth_credentials(self) -> tuple[str, str]:
        """
        Fetch ``/js/app.js`` and extract the OAuth client_id and client_secret.

        The file is served without a cache-busting hash, making it a stable
        fetch target.  The regex  o=\"(\d+)\",n=\"([^\"]+)\"  captures both values.

        Returns ``(client_id, client_secret)`` on success.
        Raises ``HargassnerSecretError`` if the pattern is not found.
        Raises ``HargassnerConnectionError`` on network failure.
        Result is cached for the lifetime of this client instance.
        """
        async with self._creds_lock:
            if self._client_id and self._client_secret:
                return self._client_id, self._client_secret

            _LOGGER.debug("Fetching OAuth credentials from %s", APP_JS_URL)
            try:
                async with self._session.get(
                    APP_JS_URL, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        raise HargassnerConnectionError(
                            f"HTTP {resp.status} fetching app.js"
                        )
                    js = await resp.text()
            except aiohttp.ClientError as exc:
                raise HargassnerConnectionError(
                    f"Network error fetching app.js: {exc}"
                ) from exc

            m = _OAUTH_CREDS_RE.search(js)
            if not m:
                raise HargassnerSecretError(
                    "Could not locate OAuth credentials in /js/app.js. "
                    "The JS pattern may have changed — please open a GitHub issue."
                )

            self._client_id     = m.group(1)
            self._client_secret = m.group(2)
            _LOGGER.debug(
                "OAuth credentials extracted — client_id=%s, secret_len=%d",
                self._client_id, len(self._client_secret),
            )
            return self._client_id, self._client_secret

    # ------------------------------------------------------------------
    # Step 2 — Authentication (token)
    # ------------------------------------------------------------------

    async def async_validate_credentials(self) -> str:
        """
        Validate email/password by fetching a fresh token.

        Internally calls ``async_discover_oauth_credentials()`` first.
        Returns the raw access_token on success.
        """
        await self.async_discover_oauth_credentials()
        async with self._token_lock:
            self._token.invalidate()
            return await self._async_fetch_token()

    async def _async_get_token(self) -> str:
        """Return a valid Bearer token, refreshing transparently when stale."""
        if not (self._client_id and self._client_secret):
            await self.async_discover_oauth_credentials()
        async with self._token_lock:
            if self._token.is_valid():
                return self._token.access_token
            return await self._async_fetch_token()

    async def _async_fetch_token(self) -> str:
        """
        POST /oauth/token — ROPC grant.
        Must be called with ``_token_lock`` held.
        """
        assert self._client_id and self._client_secret, (
            "OAuth credentials must be populated before token fetch"
        )

        payload = {
            "grant_type":    "password",
            "client_id":     self._client_id,
            "client_secret": self._client_secret,
            "username":      self._username,
            "password":      self._password,
        }
        try:
            async with self._session.post(
                TOKEN_URL, data=payload, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise HargassnerAuthError(
                        "Authentication failed — please check your Hargassner "
                        "Connect email and password."
                    )
                if resp.status != 200:
                    raise HargassnerApiError(resp.status, "Token endpoint error")

                body = await resp.json(content_type=None)
                token: str = body.get("access_token", "")
                if not token:
                    raise HargassnerAuthError(
                        "Token endpoint returned an empty access_token."
                    )
                self._token.store(token)
                return token

        except aiohttp.ClientError as exc:
            raise HargassnerConnectionError(
                f"Network error during token fetch: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Step 3 — Installation ID auto-discovery
    # ------------------------------------------------------------------

    async def async_discover_installation_id(self) -> list[dict[str, Any]]:
        """
        Return a list of installations accessible to this account.

        Each entry is ``{"id": str, "name": str}``.
        Raises ``HargassnerError`` if no installations are found.
        """
        for endpoint in (
            f"{PORTAL_URL}/api/user/installations",
            f"{PORTAL_URL}/api/installations",
        ):
            try:
                raw = await self._async_get(endpoint)
                installations = self._parse_installations(raw)
                if installations:
                    _LOGGER.debug(
                        "Discovered %d installation(s) via %s",
                        len(installations), endpoint,
                    )
                    return installations
            except HargassnerApiError as exc:
                if exc.status == 404:
                    _LOGGER.debug("Endpoint %s returned 404, trying next", endpoint)
                    continue
                raise

        raise HargassnerError(
            "Could not auto-discover any Hargassner installations for this account."
        )

    @staticmethod
    def _parse_installations(raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, list):
            return [
                {
                    "id":   str(item.get("id", "")),
                    "name": item.get("name", f"Installation {item.get('id', '?')}"),
                }
                for item in raw if item.get("id")
            ]
        if isinstance(raw, dict):
            items = raw.get("data", raw.get("installations", []))
            return HargassnerApiClient._parse_installations(items)
        return []

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _async_request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        _retry: bool = True,
    ) -> aiohttp.ClientResponse:
        """
        Authenticated request with automatic 401 → credential re-extraction
        → token refresh → single retry.
        """
        token = await self._async_get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = await self._session.request(
                method, url, headers=headers, json=json, timeout=REQUEST_TIMEOUT
            )
        except aiohttp.ClientError as exc:
            raise HargassnerConnectionError(
                f"Request failed [{method} {url}]: {exc}"
            ) from exc

        if resp.status == 401 and _retry:
            _LOGGER.debug("401 received — re-extracting credentials and retrying")
            async with self._creds_lock:
                self._client_id = None
                self._client_secret = None
            await self.async_discover_oauth_credentials()
            async with self._token_lock:
                self._token.invalidate()
                await self._async_fetch_token()
            return await self._async_request(method, url, json=json, _retry=False)

        return resp

    async def _async_get(self, url: str) -> Any:
        resp = await self._async_request("GET", url)
        if resp.status != 200:
            raise HargassnerApiError(resp.status, f"GET {url}")
        return await resp.json(content_type=None)

    async def _async_patch(self, endpoint: str, value: Any) -> None:
        url = f"{self._api_base}/{endpoint}"
        resp = await self._async_request("PATCH", url, json={"value": value})
        if resp.status not in (200, 204):
            raise HargassnerApiError(resp.status, f"PATCH {endpoint}")
        _LOGGER.debug("PATCH %s = %r [%s]", endpoint, value, resp.status)

    async def _async_post_action(self, endpoint: str) -> None:
        url = f"{self._api_base}/{endpoint}"
        resp = await self._async_request("POST", url)
        if resp.status not in (200, 204):
            raise HargassnerApiError(resp.status, f"POST {endpoint}")
        _LOGGER.debug("POST %s [%s]", endpoint, resp.status)

    # ------------------------------------------------------------------
    # Read — GET /widgets
    # ------------------------------------------------------------------

    async def async_get_widgets(self) -> WidgetSnapshot:
        """Fetch the complete installation state in one API call."""
        raw = await self._async_get(f"{self._api_base}/widgets")
        return self._parse_widgets(raw)

    # ------------------------------------------------------------------
    # Widget parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _pv(params: dict, key: str, default: Any = None) -> Any:
        entry = params.get(key)
        if isinstance(entry, dict):
            return entry.get("value", default)
        return default

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _api_to_ha_mode(value: Any) -> str:
        """Convert API uppercase MODE_* string to lowercase HA translation key."""
        if isinstance(value, str):
            return value.lower()
        return "unknown"

    def _parse_widgets(self, raw: dict) -> WidgetSnapshot:
        snap = WidgetSnapshot(raw=raw)
        for w in raw.get("data", []):
            wtype: str   = w.get("widget", "")
            params: dict = w.get("parameters", {})

            if wtype == "HEATING_CIRCUIT_RADIATOR":
                snap.heating_circuit = HeatingCircuitData(
                    mode=self._api_to_ha_mode(self._pv(params, "mode", "unknown")),
                    room_temp_correction=float(
                        self._pv(params, "room_temperature_correction", 0.0)
                    ),
                    room_temp_heating=float(
                        self._pv(params, "room_temperature_heating", 20.0)
                    ),
                    room_temp_reduction=float(
                        self._pv(params, "room_temperature_reduction", 18.0)
                    ),
                    steepness=float(self._pv(params, "steepness", 1.5)),
                    deactivation_limit_heating=float(
                        self._pv(params, "deactivation_limit_heating", 15.0)
                    ),
                    deactivation_limit_reduction_day=float(
                        self._pv(params, "deactivation_limit_reduction_day", 15.0)
                    ),
                    deactivation_limit_reduction_night=float(
                        self._pv(params, "deactivation_limit_reduction_night", 15.0)
                    ),
                    bathroom_heating=self._api_to_ha_mode(
                        self._pv(params, "bathroom_heating", "MODE_OFF")
                    ),
                )
            elif wtype == "BOILER":
                snap.boiler = BoilerData(
                    temperature=self._safe_float(self._pv(params, "boiler_temperature")),
                    setpoint=self._safe_float(self._pv(params, "boiler_setpoint")),
                    state=self._pv(params, "boiler_state", "unknown"),
                )
                pellets = self._pv(params, "fuel_stock")
                if pellets is not None:
                    snap.pellet_stock_kg = self._safe_float(pellets)
            elif wtype == "BUFFER":
                snap.buffer = BufferData(
                    solar_mode_active=self._api_to_ha_mode(
                        self._pv(params, "solar_mode_active", "MODE_OFF")
                    ),
                    temperature=self._safe_float(self._pv(params, "buffer_temperature")),
                )
            elif wtype == "HOT_WATER":
                snap.hot_water = HotWaterData(
                    temperature=self._safe_float(self._pv(params, "water_temperature")),
                    setpoint=self._safe_float(self._pv(params, "water_setpoint")),
                )

        return snap

    # ------------------------------------------------------------------
    # Write — Heating Circuit
    # (HA uses lowercase mode keys; API expects uppercase MODE_* strings)
    # ------------------------------------------------------------------

    async def async_set_heating_mode(self, mode: HeatingMode | str) -> None:
        await self._async_patch(
            "widgets/heating-circuits/1/parameters/mode", str(mode).upper()
        )

    async def async_set_room_temp_correction(self, value: float) -> None:
        await self._async_patch(
            "widgets/heating-circuits/1/parameters/room-temperature-correction",
            round(value, 1),
        )

    async def async_set_room_temp_heating(self, value: float) -> None:
        await self._async_patch(
            "widgets/heating-circuits/1/parameters/room-temperature-heating",
            round(value, 1),
        )

    async def async_set_room_temp_reduction(self, value: float) -> None:
        await self._async_patch(
            "widgets/heating-circuits/1/parameters/room-temperature-reduction",
            round(value, 1),
        )

    async def async_set_steepness(self, value: float) -> None:
        await self._async_patch(
            "widgets/heating-circuits/1/parameters/steepness",
            round(value, 2),
        )

    async def async_set_bathroom_heating(self, mode: BathroomHeating | str) -> None:
        await self._async_patch(
            "widgets/heating-circuits/1/parameters/bathroom-heating", str(mode).upper()
        )

    async def async_set_deactivation_limit_heating(self, value: float) -> None:
        await self._async_patch(
            "widgets/heating-circuits/all/parameters/deactivation-limit-heating",
            round(value, 1),
        )

    async def async_set_deactivation_limit_reduction_day(self, value: float) -> None:
        await self._async_patch(
            "widgets/heating-circuits/all/parameters/deactivation-limit-reduction-day",
            round(value, 1),
        )

    async def async_set_deactivation_limit_reduction_night(self, value: float) -> None:
        await self._async_patch(
            "widgets/heating-circuits/all/parameters/deactivation-limit-reduction-night",
            round(value, 1),
        )

    # ------------------------------------------------------------------
    # Write — Boiler
    # ------------------------------------------------------------------

    async def async_force_charge(self) -> None:
        await self._async_post_action("widgets/boilers/1/actions/force-charging")

    async def async_set_pellet_stock(self, kg: float) -> None:
        await self._async_patch(
            "widgets/heater/parameters/fuel-stock", round(kg, 0)
        )

    # ------------------------------------------------------------------
    # Write — Buffer / Solar
    # ------------------------------------------------------------------

    async def async_set_solar_mode(self, mode: SolarMode | str) -> None:
        await self._async_patch(
            "widgets/buffer/default/parameters/solar-mode-active", str(mode).upper()
        )
