"""Setup, entiteitswaarden, coordinator (backoff, drie mislukte rondes, reauth) en diagnose."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.whatsgps.const import DOMAIN

from .common import (
    ACCOUNT,
    ALARMS_URL,
    LOGIN_URL,
    MILEAGE,
    MILEAGE_URL,
    MONITOR_URL,
    NO_ALARMS,
    PASSWORD,
    TOKEN,
    calls_to,
    fixture,
    mock_api,
)

USER_INPUT = {CONF_USERNAME: ACCOUNT, CONF_PASSWORD: PASSWORD}


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1000001", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity(hass: HomeAssistant, domain: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"1000001_{key}")
    assert entity_id, key
    return entity_id


async def test_entities_and_device(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_api(aioclient_mock)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    tracker = hass.states.get(_entity(hass, "device_tracker", "location"))
    assert tracker is not None
    assert tracker.attributes["latitude"] == 54.0
    assert tracker.attributes["longitude"] == 3.0
    assert tracker.attributes["gps_accuracy"] == 20
    assert tracker.attributes["source_type"] == "gps"

    values = {
        "speed": "0.0",
        "direction": "90",
        "battery": "87",
        "position_source": "satellite",
        "status": "stationary",
        "last_fix": datetime.fromtimestamp(1799980000, tz=UTC).isoformat(),
        "last_communication": datetime.fromtimestamp(1799999640, tz=UTC).isoformat(),
        "temperature": "9.0",
        "humidity": "57",
        "voltage": "0.0",
        "today_distance": "1.5",
        "total_distance": "1234.56",
        "stationary_since": datetime.fromtimestamp(1799945000, tz=UTC).isoformat(),
    }
    for key, expected in values.items():
        state = hass.states.get(_entity(hass, "sensor", key))
        assert state is not None and state.state == expected, (key, state)
    battery = hass.states.get(_entity(hass, "sensor", "battery"))
    assert battery is not None
    assert battery.attributes["friendly_name"] == "Demo Tracker battery"

    assert hass.states.get(_entity(hass, "binary_sensor", "online")).state == "on"  # type: ignore[union-attr]
    assert hass.states.get(_entity(hass, "binary_sensor", "moving")).state == "off"  # type: ignore[union-attr]
    assert hass.states.get(_entity(hass, "binary_sensor", "charging")).state == "off"  # type: ignore[union-attr]
    # accStatus -1: deze tracker meldt geen contact, dus geen contactsensor.
    assert er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, "1000001_ignition") is None

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "1000001"), entry.entry_id)
    assert device is not None
    assert device.manufacturer == "Protectly/WhatsGPS"
    assert device.serial_number == ACCOUNT
    assert ACCOUNT not in (device.name or "")
    for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        assert ACCOUNT not in entity.entity_id


async def test_cell_tower_position_has_wide_accuracy(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    monitor = fixture("monitor.json")
    monitor["data"][0]["monitorCarsVoList"][0]["carStatus"]["pointType"] = 3
    mock_api(aioclient_mock, monitor=monitor)
    await _setup(hass)
    state = hass.states.get(_entity(hass, "device_tracker", "location"))
    assert state is not None
    assert state.attributes["gps_accuracy"] == 500


async def test_unavailable_after_three_failures_and_recovers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    plan = ["ok", "fail", "fail", "fail", "ok"]

    async def monitor(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        if plan.pop(0) == "fail":
            raise aiohttp.ClientConnectionError
        return AiohttpClientMockResponse(method, url, json=fixture("monitor.json"))

    aioclient_mock.post(MONITOR_URL, side_effect=monitor)
    aioclient_mock.get(MILEAGE_URL, json=MILEAGE)
    aioclient_mock.post(ALARMS_URL, json=NO_ALARMS)
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    speed = _entity(hass, "sensor", "speed")

    intervals = []
    for expected_state in ["0.0", "0.0", STATE_UNAVAILABLE]:
        freezer.tick(coordinator.update_interval)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        intervals.append(coordinator.update_interval.total_seconds())
        assert hass.states.get(speed).state == expected_state  # type: ignore[union-attr]

    # Exponentiele backoff vanaf 60 s, nooit meer dan 15 minuten.
    assert intervals == [120, 240, 480]

    freezer.tick(coordinator.update_interval)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(speed).state == "0.0"  # type: ignore[union-attr]
    assert coordinator.update_interval.total_seconds() == 60
    assert coordinator.failures == 0


async def test_backoff_is_capped_at_fifteen_minutes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    calls = {"n": 0}

    async def monitor(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        calls["n"] += 1
        if calls["n"] > 1:
            raise aiohttp.ClientConnectionError
        return AiohttpClientMockResponse(method, url, json=fixture("monitor.json"))

    aioclient_mock.post(MONITOR_URL, side_effect=monitor)
    aioclient_mock.get(MILEAGE_URL, json=MILEAGE)
    aioclient_mock.post(ALARMS_URL, json=NO_ALARMS)
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    for _ in range(6):
        freezer.tick(coordinator.update_interval)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert coordinator.update_interval == timedelta(minutes=15)


async def test_rejected_login_starts_reauth_without_retrying(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    logins = [fixture("login.json"), {"ret": 0, "code": "500", "msg": "Onjuist wachtwoord"}]

    async def login(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, json=logins.pop(0) if len(logins) > 1 else logins[0])

    statuses = [200, 401]

    async def monitor(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        status = statuses.pop(0) if statuses else 401
        body = fixture("monitor.json") if status == 200 else {"ret": 0, "code": "10006"}
        return AiohttpClientMockResponse(method, url, status=status, json=body)

    aioclient_mock.post(LOGIN_URL, side_effect=login)
    aioclient_mock.post(MONITOR_URL, side_effect=monitor)
    aioclient_mock.get(MILEAGE_URL, json=MILEAGE)
    aioclient_mock.post(ALARMS_URL, json=NO_ALARMS)
    entry = await _setup(hass)
    coordinator = entry.runtime_data

    freezer.tick(coordinator.update_interval)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    flows = [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == SOURCE_REAUTH]
    assert len(flows) == 1
    logins_after_reauth = len(calls_to(aioclient_mock, LOGIN_URL))

    # Volgende rondes loggen niet steeds opnieuw in: de coordinator staat stil tot de reauth.
    for _ in range(3):
        freezer.tick(timedelta(minutes=15))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert len(calls_to(aioclient_mock, LOGIN_URL)) == logins_after_reauth


async def test_setup_retries_when_cloud_unreachable(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(LOGIN_URL, exc=aiohttp.ClientConnectionError())
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1000001", data=USER_INPUT)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_api(aioclient_mock)
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_hide_secrets(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, hass_client: ClientSessionGenerator
) -> None:
    mock_api(aioclient_mock)
    entry = await _setup(hass)
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = str(diagnostics)
    for secret in [ACCOUNT, PASSWORD, TOKEN, "1000001", "54.0", "XX-000-X", "31600000000000", "89310000000000000000"]:
        assert secret not in text, secret
    assert diagnostics["trackers"][0]["carStatus"]["pointType"] == 1


def _mileage_calls(aioclient_mock: AiohttpClientMocker) -> int:
    return sum(1 for call in aioclient_mock.mock_calls if str(call[1]).startswith(MILEAGE_URL))


async def test_mileage_at_most_every_ten_minutes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    mock_api(aioclient_mock)
    entry = await _setup(hass)
    assert _mileage_calls(aioclient_mock) == 1
    for _ in range(9):
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert _mileage_calls(aioclient_mock) == 1
    assert len(calls_to(aioclient_mock, MONITOR_URL)) == 10
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _mileage_calls(aioclient_mock) == 2
    assert entry.state is ConfigEntryState.LOADED


async def test_mileage_failure_keeps_entities_available(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    aioclient_mock.post(MONITOR_URL, json=fixture("monitor.json"))
    aioclient_mock.get(MILEAGE_URL, status=502, json={"error": "x"})
    aioclient_mock.post(ALARMS_URL, json=NO_ALARMS)
    await _setup(hass)
    assert hass.states.get(_entity(hass, "sensor", "speed")).state == "0.0"  # type: ignore[union-attr]
    assert hass.states.get(_entity(hass, "sensor", "total_distance")).state == "unknown"  # type: ignore[union-attr]


async def test_device_removal_refused_when_not_loaded(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    from custom_components.whatsgps import async_remove_config_entry_device

    mock_api(aioclient_mock)
    entry = await _setup(hass)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "1000001"), entry.entry_id)
    assert device is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    # Niet geladen: niet bekend welke trackers er zijn, dus niets laten verwijderen (en geen crash).
    assert await async_remove_config_entry_device(hass, entry, device) is False


async def test_diagnostics_only_known_fields(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, hass_client: ClientSessionGenerator
) -> None:
    monitor = fixture("monitor.json")
    car = monitor["data"][0]["monitorCarsVoList"][0]
    car["driverTel"] = "0612345678"
    car["carStatus"]["address"] = "Voorbeeldstraat 1"
    mock_api(aioclient_mock, monitor=monitor)
    entry = await _setup(hass)
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = str(diagnostics)
    assert "0612345678" not in text
    assert "Voorbeeldstraat" not in text
    # Wel de namen, zodat een nieuw veld opvalt.
    assert "driverTel" in diagnostics["trackers"][0]["other_fields"]
    assert "address" in diagnostics["trackers"][0]["other_status_fields"]
    assert diagnostics["alarm_codes"] == [[]]


async def test_diagnostics_when_not_loaded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, hass_client: ClientSessionGenerator
) -> None:
    from custom_components.whatsgps.diagnostics import async_get_config_entry_diagnostics

    aioclient_mock.post(LOGIN_URL, exc=aiohttp.ClientConnectionError())
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1000001", data=USER_INPUT)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["loaded"] is False
    assert PASSWORD not in str(diagnostics)
