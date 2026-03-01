"""
Config flow for the Hargassner Connect Home Assistant integration.

User-facing inputs:  email address + password only.
Auto-discovered:     OAuth client_id + client_secret (from /js/app.js),
                     installation ID.

Flow steps
----------
user                 → email + password form
select_installation  → only shown when account has >1 installation
(entry created)

Options flow
------------
Allows re-entering credentials after setup (e.g. password change).
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import (
    HargassnerApiClient,
    HargassnerAuthError,
    HargassnerConnectionError,
    HargassnerSecretError,
)
from .const import CONF_INSTALLATION_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class HargassnerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup config flow for Hargassner Connect."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._username: str = ""
        self._password: str = ""
        self._installations: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the email/password form and validate on submit."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            client = HargassnerApiClient(
                session=async_get_clientsession(self.hass),
                username=username,
                password=password,
            )

            try:
                await client.async_validate_credentials()
                installations = await client.async_discover_installation_id()
            except HargassnerSecretError:
                _LOGGER.exception("Failed to extract OAuth credentials from app.js")
                errors["base"] = "secret_extraction_failed"
            except HargassnerAuthError:
                errors["base"] = "invalid_auth"
            except HargassnerConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Hargassner setup")
                errors["base"] = "unknown"
            else:
                self._username = username
                self._password = password
                self._installations = installations

                if len(installations) == 1:
                    return self._create_entry(
                        installations[0]["id"], installations[0]["name"]
                    )
                return await self.async_step_select_installation()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_select_installation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick which installation to integrate."""
        if user_input is not None:
            install_id = user_input[CONF_INSTALLATION_ID]
            install_name = next(
                (i["name"] for i in self._installations if i["id"] == install_id),
                install_id,
            )
            return self._create_entry(install_id, install_name)

        return self.async_show_form(
            step_id="select_installation",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INSTALLATION_ID): vol.In(
                        {i["id"]: i["name"] for i in self._installations}
                    ),
                }
            ),
            description_placeholders={"count": str(len(self._installations))},
        )

    def _create_entry(self, installation_id: str, installation_name: str) -> ConfigFlowResult:
        """
        Create the config entry.

        Stored:      username, password, installation_id.
        NOT stored:  client_id, client_secret — re-extracted from /js/app.js
                     on every HA startup.  Self-heals on rotation.
        """
        return self.async_create_entry(
            title=f"Hargassner — {installation_name}",
            data={
                CONF_USERNAME:        self._username,
                CONF_PASSWORD:        self._password,
                CONF_INSTALLATION_ID: installation_id,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HargassnerOptionsFlow:
        return HargassnerOptionsFlow(config_entry)


class HargassnerOptionsFlow(OptionsFlow):
    """Allow the user to update credentials after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self._config_entry.data

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            client = HargassnerApiClient(
                session=async_get_clientsession(self.hass),
                username=username,
                password=password,
                installation_id=current[CONF_INSTALLATION_ID],
            )

            try:
                await client.async_validate_credentials()
            except HargassnerSecretError:
                errors["base"] = "secret_extraction_failed"
            except HargassnerAuthError:
                errors["base"] = "invalid_auth"
            except HargassnerConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Hargassner options update")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data={**current, CONF_USERNAME: username, CONF_PASSWORD: password},
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=current.get(CONF_USERNAME, "")
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
