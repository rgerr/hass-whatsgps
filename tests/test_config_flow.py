"""Config flow: goed, foute inlog, geen verbinding, dubbel account, reauth en opties."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.whatsgps.const import CONF_SCAN_INTERVAL, DOMAIN

from .common import ACCOUNT, LOGIN_URL, PASSWORD, calls_to, fixture, mock_api

USER_INPUT = {CONF_USERNAME: ACCOUNT, CONF_PASSWORD: PASSWORD}


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Geen echte setup na een flow.

    Een nieuwe entry of een geslaagde reauth laadt de integratie op de achtergrond. Eindigt
    de test terwijl dat nog loopt, dan blijft een timer van device_tracker hangen (op
    GitHub Actions gezien als "Lingering timer after test").
    """
    with patch("custom_components.whatsgps.async_setup_entry", AsyncMock(return_value=True)) as mock:
        yield mock


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    # De portaalnaam komt als plaatshouder, niet als URL in de vertaling.
    assert result["description_placeholders"] == {"portal": "www.whatsgps.com"}
    return str(result["flow_id"])


async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    mock_api(aioclient_mock)
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "WhatsGPS"
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == "1000001"
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("mock", "error"),
    [
        ({"json": {"ret": 0, "code": "500", "msg": "Onjuist wachtwoord"}}, "invalid_auth"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
        ({"status": 403, "json": {"message": "Your request is not allowed! 003"}}, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock: dict[str, object], error: str
) -> None:
    aioclient_mock.post(LOGIN_URL, **mock)
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    # Een geweigerde login wordt niet herhaald.
    assert len(calls_to(aioclient_mock, LOGIN_URL)) == 1


async def test_same_account_twice_aborts(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="1000001", data=USER_INPUT).add_to_hass(hass)
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1000001", data={**USER_INPUT, CONF_PASSWORD: "oud"})
    entry.add_to_hass(hass)
    mock_api(aioclient_mock)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: PASSWORD})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == PASSWORD
    # Na de reauth wordt de integratie opnieuw geladen.
    assert len(mock_setup_entry.mock_calls) == 1


async def test_reauth_with_other_account_aborts(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="9999999", data=USER_INPUT)
    entry.add_to_hass(hass)
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


async def test_reauth_wrong_password_shows_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1000001", data=USER_INPUT)
    entry.add_to_hass(hass)
    aioclient_mock.post(LOGIN_URL, json={"ret": 0, "code": "500", "msg": "Onjuist wachtwoord"})
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "fout"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_flow_sets_interval(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_api(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1000001", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: 120})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {CONF_SCAN_INTERVAL: 120}
    assert entry.runtime_data.update_interval.total_seconds() == 120


async def test_options_flow_rejects_out_of_range(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_api(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1000001", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData, match="scan_interval"):
        await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: 10})
