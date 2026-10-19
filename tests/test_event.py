"""Alarmen als events, nieuwe trackers zonder herladen en verwijderen van oude apparaten."""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.whatsgps import async_remove_config_entry_device
from custom_components.whatsgps.const import DOMAIN

from .common import ACCOUNT, ALARMS_URL, LOGIN_URL, MILEAGE, MILEAGE_URL, MONITOR_URL, PASSWORD, fixture

USER_INPUT = {CONF_USERNAME: ACCOUNT, CONF_PASSWORD: PASSWORD}


def _alarm(alarm_id: str, code: int, minute: int) -> dict[str, Any]:
    return {"alarmId": alarm_id, "alarmType": code, "alarmTime": f"2026-10-19 09:{minute:02d}:00", "speed": 0}


class Cloud:
    """Nepcloud met een instelbare alarmlijst en trackerlijst."""

    def __init__(self, aioclient_mock: AiohttpClientMocker) -> None:
        self.alarms: list[dict[str, Any]] = []
        self.monitor = fixture("monitor.json")
        aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
        aioclient_mock.get(MILEAGE_URL, json=MILEAGE)
        aioclient_mock.post(MONITOR_URL, side_effect=self._monitor)
        aioclient_mock.post(ALARMS_URL, side_effect=self._alarms)

    async def _monitor(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, json=copy.deepcopy(self.monitor))

    async def _alarms(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        body = {"ret": 1, "code": "200", "total": len(self.alarms), "data": list(self.alarms)}
        return AiohttpClientMockResponse(method, url, json=body)


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1000001", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _event_entity(hass: HomeAssistant, car_id: str = "1000001") -> str:
    entity_id = er.async_get(hass).async_get_entity_id("event", DOMAIN, f"{car_id}_alarm")
    assert entity_id
    return entity_id


async def _next_alarm_round(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=120))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_old_alarms_not_replayed_new_alarm_once(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    cloud = Cloud(aioclient_mock)
    cloud.alarms = [_alarm("OLD", 25, 1)]
    await _setup(hass)
    entity_id = _event_entity(hass)
    fired: list[Event] = []
    hass.bus.async_listen("state_changed", lambda e: fired.append(e) if e.data["entity_id"] == entity_id else None)
    assert hass.states.get(entity_id).state == "unknown"  # type: ignore[union-attr]

    cloud.alarms = [_alarm("NEW", 10, 5), *cloud.alarms]
    await _next_alarm_round(hass, freezer)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["event_type"] == "tamper"
    assert state.attributes["code"] == 10
    assert state.attributes["description"] == "Sabotage-alarm"
    assert len(fired) == 1

    # Dezelfde lijst nog eens: geen nieuw event.
    await _next_alarm_round(hass, freezer)
    assert len(fired) == 1


async def test_each_alarm_once_after_restart(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    cloud = Cloud(aioclient_mock)
    entry = await _setup(hass)
    cloud.alarms = [_alarm("A1", 6, 2)]
    await _next_alarm_round(hass, freezer)
    entity_id = _event_entity(hass)
    assert hass.states.get(entity_id).attributes["event_type"] == "geofence_exit"  # type: ignore[union-attr]

    # Herladen (zoals na een herstart): A1 niet opnieuw, A2 wel.
    freezer.tick(timedelta(seconds=5))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    fired: list[Event] = []
    hass.bus.async_listen("state_changed", lambda e: fired.append(e) if e.data["entity_id"] == entity_id else None)
    await _next_alarm_round(hass, freezer)
    assert fired == []
    cloud.alarms = [_alarm("A2", 3, 7), *cloud.alarms]
    await _next_alarm_round(hass, freezer)
    assert len(fired) == 1
    assert hass.states.get(entity_id).attributes["event_type"] == "low_battery"  # type: ignore[union-attr]


async def test_unknown_alarm_code_is_other(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    cloud = Cloud(aioclient_mock)
    await _setup(hass)
    cloud.alarms = [_alarm("X", 999, 3)]
    await _next_alarm_round(hass, freezer)
    state = hass.states.get(_event_entity(hass))
    assert state is not None
    assert state.attributes["event_type"] == "other"
    assert state.attributes["description"] == "Onbekend alarm"


async def test_new_tracker_gets_entities_without_reload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    cloud = Cloud(aioclient_mock)
    await _setup(hass)
    second = copy.deepcopy(cloud.monitor["data"][0]["monitorCarsVoList"][0])
    second.update({"carId": "1000002", "imei": "356789012345679", "machineName": "Tweede"})
    cloud.monitor["data"][0]["monitorCarsVoList"].append(second)
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for domain, key in [
        ("device_tracker", "location"),
        ("sensor", "speed"),
        ("binary_sensor", "online"),
        ("event", "alarm"),
    ]:
        assert registry.async_get_entity_id(domain, DOMAIN, f"1000002_{key}"), (domain, key)


async def test_only_trackers_gone_from_account_can_be_removed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    Cloud(aioclient_mock)
    entry = await _setup(hass)
    registry = dr.async_get(hass)
    current = registry.async_get_device_by_identifier((DOMAIN, "1000001"), entry.entry_id)
    assert current is not None
    assert await async_remove_config_entry_device(hass, entry, current) is False
    stale = registry.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, "9999999")})
    assert await async_remove_config_entry_device(hass, entry, stale) is True
