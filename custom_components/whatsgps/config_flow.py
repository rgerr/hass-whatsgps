"""Configuratie via de UI: account, reauth en het poll-interval."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import probatio as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import timezone_seconds
from .api import (
    LoginResult,
    WhatsGPSAuthError,
    WhatsGPSClient,
    WhatsGPSConnectionError,
    WhatsGPSError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import WhatsGPSConfigEntry

USER_SCHEMA = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def _login(hass: HomeAssistant, account: str, password: str) -> tuple[LoginResult | None, str | None]:
    """Een echte login als controle; geeft (resultaat, foutcode voor het formulier)."""
    client = WhatsGPSClient(async_get_clientsession(hass), account, password, timezone_seconds=timezone_seconds())
    try:
        return await client.async_login(), None
    except WhatsGPSAuthError:
        return None, "invalid_auth"
    except WhatsGPSConnectionError:
        return None, "cannot_connect"
    except WhatsGPSError:
        LOGGER.exception("Onverwacht antwoord van WhatsGPS bij inloggen")
        return None, "unknown"


class WhatsGPSConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            account = user_input[CONF_USERNAME].strip()
            result, error = await _login(self.hass, account, user_input[CONF_PASSWORD])
            if result is not None:
                await self.async_set_unique_id(result.user_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="WhatsGPS", data={CONF_USERNAME: account, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
            # Geen URL in de vertaling zelf (hassfest); de portaalnaam als plaatshouder.
            description_placeholders={"portal": "www.whatsgps.com"},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            result, error = await _login(self.hass, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if result is not None:
                await self.async_set_unique_id(result.user_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(step_id="reauth_confirm", data_schema=REAUTH_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: WhatsGPSConfigEntry) -> WhatsGPSOptionsFlow:
        return WhatsGPSOptionsFlow()


class WhatsGPSOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
