"""Tests voor de WhatsGPS-client op geanonimiseerde fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.whatsgps.api import (
    WhatsGPSAuthError,
    WhatsGPSClient,
    WhatsGPSConnectionError,
    WhatsGPSResponseError,
    parse_alarm,
    parse_ex_data,
    parse_tracker,
)
from custom_components.whatsgps.coords import gcj02_to_wgs84, wgs84_to_gcj02

from .common import (
    ACCOUNT,
    ALARMS_URL,
    LOGIN_URL,
    MILEAGE_URL,
    MONITOR_URL,
    PASSWORD,
    TOKEN,
    calls_to,
    fixture,
    mock_api,
)


def _client(hass: HomeAssistant) -> WhatsGPSClient:
    return WhatsGPSClient(async_get_clientsession(hass), ACCOUNT, PASSWORD, timezone_seconds=7200)


async def test_login_sends_form_and_portal_headers(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_api(aioclient_mock)
    result = await _client(hass).async_login()
    assert result.user_id == "1000001"
    assert result.token == TOKEN
    _, _, data, headers = calls_to(aioclient_mock, LOGIN_URL)[0]
    assert data == {"name": ACCOUNT, "password": PASSWORD, "timeZoneSecond": "7200", "lang": "nl"}
    assert headers["appId"] == "ABROAD_WHATSGPS"
    assert headers["appKey"] == "ljdw-abroad"
    assert "token" not in headers


async def test_trackers_with_one_login_and_token_header(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_api(aioclient_mock)
    client = _client(hass)
    first = await client.async_get_trackers()
    await client.async_get_trackers()
    assert len(calls_to(aioclient_mock, LOGIN_URL)) == 1
    monitor_calls = calls_to(aioclient_mock, MONITOR_URL)
    assert len(monitor_calls) == 2
    assert monitor_calls[0][3]["token"] == TOKEN
    assert monitor_calls[0][2]["mapType"] == 2
    assert [t.car_id for t in first] == ["1000001"]


async def test_expired_token_logs_in_once_more(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    # Eerste ronde goed; daarna is het token verlopen (401) en volgt een keer opnieuw inloggen.
    answers = [200, 401, 200]

    async def monitor(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        status = answers.pop(0)
        body = fixture("monitor.json") if status == 200 else {"ret": 0, "code": "10006", "msg": "No permission"}
        return AiohttpClientMockResponse(method, url, status=status, json=body)

    aioclient_mock.post(MONITOR_URL, side_effect=monitor)
    client = _client(hass)
    await client.async_get_trackers()
    trackers = await client.async_get_trackers()
    assert len(trackers) == 1
    assert len(calls_to(aioclient_mock, LOGIN_URL)) == 2


async def test_token_refused_after_fresh_login_is_no_password_problem(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Login lukt, maar het token wordt toch geweigerd: geen reauth (dat zou een lus geven)."""
    mock_api(aioclient_mock, monitor={"ret": 0, "code": "10006"}, monitor_status=401)
    with pytest.raises(WhatsGPSResponseError, match="appId/appKey"):
        await _client(hass).async_get_trackers()
    # Het token was net nieuw: niet nog een keer inloggen.
    assert len(calls_to(aioclient_mock, LOGIN_URL)) == 1


async def test_wrong_password_is_not_retried(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(LOGIN_URL, json={"ret": 0, "code": "500", "msg": "Onjuist wachtwoord"})
    with pytest.raises(WhatsGPSAuthError):
        await _client(hass).async_get_trackers()
    assert len(calls_to(aioclient_mock, LOGIN_URL)) == 1


async def test_blocked_login_is_no_password_verdict(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(LOGIN_URL, status=403, json={"message": "Your request is not allowed! 003"})
    with pytest.raises(WhatsGPSResponseError):
        await _client(hass).async_login()


@pytest.mark.parametrize("exc", [aiohttp.ClientConnectionError(), TimeoutError()])
async def test_connection_problems(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, exc: Exception) -> None:
    aioclient_mock.post(LOGIN_URL, exc=exc)
    with pytest.raises(WhatsGPSConnectionError):
        await _client(hass).async_login()


async def test_server_error_on_status(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_api(aioclient_mock, monitor={"error": "x"}, monitor_status=502)
    with pytest.raises(WhatsGPSConnectionError):
        await _client(hass).async_get_trackers()


async def test_unexpected_status_body(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_api(aioclient_mock, monitor={"ret": 0, "code": "500", "msg": "fout"})
    with pytest.raises(WhatsGPSResponseError):
        await _client(hass).async_get_trackers()


def test_parse_tracker_fields() -> None:
    car = fixture("monitor.json")["data"][0]["monitorCarsVoList"][0]
    tracker = parse_tracker(car)
    assert (tracker.car_id, tracker.imei, tracker.name, tracker.model_code) == ("1000001", ACCOUNT, "Demo", 208)
    assert (tracker.latitude, tracker.longitude) == (54.0, 3.0)
    assert tracker.position_source == "satellite"
    assert tracker.status == "stationary"
    assert tracker.moving is False
    assert tracker.acc is None
    assert tracker.battery == 87
    assert tracker.speed == 0
    assert tracker.direction == 90
    assert tracker.last_fix == datetime.fromtimestamp(1799980000, tz=UTC)
    assert tracker.last_communication == datetime.fromtimestamp(1799999640, tz=UTC)
    # Uit exData: temperatuur, luchtvochtigheid, spanning en laden.
    assert tracker.temperature == 9
    assert tracker.humidity == 57
    assert tracker.voltage == 0
    assert tracker.charging is False
    # gpsMileage in exData is niet de kilometerstand van het portaal; die komt uit mileageSta.
    assert tracker.total_km is None
    assert tracker.stationary_since == datetime.fromtimestamp(1799945000, tz=UTC)


def test_extra_values_absent_or_garbled_give_none() -> None:
    car = fixture("monitor.json")["data"][0]["monitorCarsVoList"][0]
    car["carStatus"]["exData"] = "power=abc;terminalChargingStatus=7"
    car["carStatus"]["staticTime"] = 0
    tracker = parse_tracker(car)
    assert tracker.battery is None
    assert tracker.temperature is None
    assert tracker.humidity is None
    assert tracker.voltage is None
    assert tracker.charging is None
    assert tracker.stationary_since is None


def test_moving_tracker_has_no_stationary_since() -> None:
    car = fixture("monitor.json")["data"][0]["monitorCarsVoList"][0]
    car["carStatus"].update({"runStatus": 2, "speed": 48})
    tracker = parse_tracker(car)
    assert tracker.stationary_since is None
    assert tracker.charging is False


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"online": 0}, "offline"),
        ({"runStatus": 2}, "moving"),
        ({"runStatus": 3}, "speeding"),
        ({"runStatus": 4}, "idling"),
        ({"runStatus": 0}, "not_located"),
    ],
)
def test_status_mapping(changes: dict[str, int], expected: str) -> None:
    car = fixture("monitor.json")["data"][0]["monitorCarsVoList"][0]
    car["carStatus"].update(changes)
    assert parse_tracker(car).status == expected


def test_inactive_device_is_offline_and_acc_known_when_reported() -> None:
    car = fixture("monitor.json")["data"][0]["monitorCarsVoList"][0]
    car["active"] = 0
    car["carStatus"]["accStatus"] = 1
    tracker = parse_tracker(car)
    assert tracker.status == "offline"
    assert tracker.acc is True


def test_missing_position_gives_none() -> None:
    car = fixture("monitor.json")["data"][0]["monitorCarsVoList"][0]
    car["carStatus"].update({"lat": 0, "lon": 0})
    assert parse_tracker(car).latitude is None


def test_parse_ex_data() -> None:
    assert parse_ex_data("power=87;t=9;v=0") == {"power": "87", "t": "9", "v": "0"}
    assert parse_ex_data(None) == {}


def test_gcj02_roundtrip_inside_china() -> None:
    lat, lon = 39.9087, 116.3975  # Beijing
    g_lat, g_lon = wgs84_to_gcj02(lat, lon)
    assert abs(g_lat - lat) > 0.001  # GCJ-02 verschuift binnen China honderden meters
    back = gcj02_to_wgs84(g_lat, g_lon)
    assert abs(back[0] - lat) < 1e-6
    assert abs(back[1] - lon) < 1e-6


def test_gcj02_outside_china_unchanged() -> None:
    assert gcj02_to_wgs84(52.0, 6.0) == (52.0, 6.0)


async def test_mileage_in_km_with_token(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_api(aioclient_mock)
    mileage = await _client(hass).async_get_mileage("1000001")
    # Het portaal geeft meters: 1234560 m wordt 1.234,56 km.
    assert (mileage.today_km, mileage.total_km) == (1.5, 1234.56)
    call = calls_to(aioclient_mock, MILEAGE_URL + "?carId=1000001")[0]
    assert call[3]["token"] == TOKEN


async def test_alarms_parsed_from_list(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    item = {"alarmId": "A1", "alarmType": 10, "alarmTime": "2026-10-19 09:30:00", "speed": 0, "carId": "1000001"}
    aioclient_mock.post(ALARMS_URL, json={"ret": 1, "code": "200", "total": 1, "data": [item]})
    alarms = await _client(hass).async_get_alarms("1000001")
    assert len(alarms) == 1
    alarm = alarms[0]
    assert (alarm.alarm_id, alarm.code, alarm.speed) == ("A1", 10, 0)
    # alarmTime is tekst in UTC (het portaal zet die om naar lokale tijd).
    assert alarm.time == datetime(2026, 10, 19, 9, 30, tzinfo=UTC)
    body = calls_to(aioclient_mock, ALARMS_URL)[0][2]
    assert body == {"pageNum": 1, "pageSize": 20, "carId": "1000001"}


def test_alarm_without_id_uses_code_and_time() -> None:
    alarm = parse_alarm({"alarmType": 25, "alarmTime": 1800000000000})
    assert alarm.alarm_id == "25-" + datetime.fromtimestamp(1800000000, tz=UTC).isoformat()
    assert parse_alarm({"alarmType": "x"}).code is None


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (429, {"ret": 0, "code": "429", "msg": "Too many requests"}),
        (403, {"message": "Your request is not allowed! 003"}),
        (200, {"ret": 0, "code": "10006", "msg": "No permission, cannot call"}),
    ],
)
async def test_login_refusal_without_password_verdict_is_temporary(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int, body: dict[str, Any]
) -> None:
    """Alleen een weigering met HTTP 200 zegt iets over het wachtwoord; de rest is tijdelijk."""
    aioclient_mock.post(LOGIN_URL, status=status, json=body)
    with pytest.raises(WhatsGPSResponseError):
        await _client(hass).async_login()


async def test_refused_login_is_remembered_without_network(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(LOGIN_URL, json={"ret": 0, "code": "500", "msg": "Onjuist wachtwoord"})
    client = _client(hass)
    for _ in range(3):
        with pytest.raises(WhatsGPSAuthError):
            await client.async_get_trackers()
    # Account-blokkade voorkomen: maar een keer bij de server aangeklopt.
    assert len(calls_to(aioclient_mock, LOGIN_URL)) == 1


async def test_timezone_is_evaluated_at_each_login(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    offsets = iter([7200, 3600])
    client = WhatsGPSClient(async_get_clientsession(hass), ACCOUNT, PASSWORD, timezone_seconds=lambda: next(offsets))
    await client.async_login()
    await client.async_login()
    sent = [call[2]["timeZoneSecond"] for call in calls_to(aioclient_mock, LOGIN_URL)]
    assert sent == ["7200", "3600"]


async def test_garbled_status_is_a_response_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    monitor = fixture("monitor.json")
    monitor["data"][0]["monitorCarsVoList"][0]["carStatus"] = "geen dict"
    monitor["data"][0]["monitorCarsVoList"][0]["machineType"] = {"x": 1}
    mock_api(aioclient_mock, monitor=monitor)
    trackers = await _client(hass).async_get_trackers()
    # Een carStatus zonder structuur geeft lege waarden, geen crash.
    assert trackers[0].latitude is None
    assert trackers[0].status is not None


def test_absurd_epoch_gives_none() -> None:
    car = fixture("monitor.json")["data"][0]["monitorCarsVoList"][0]
    car["carStatus"]["pointTime"] = 10**20
    assert parse_tracker(car).last_fix is None


@pytest.mark.parametrize("key", ["list", "rows", "records"])
async def test_alarm_list_in_other_shapes(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, key: str) -> None:
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    item = {"alarmId": "A1", "alarmType": 1, "alarmTime": "2026-10-19 09:30:00"}
    aioclient_mock.post(ALARMS_URL, json={"ret": 1, "code": "200", "data": {key: [item], "total": 1}})
    alarms = await _client(hass).async_get_alarms("1000001")
    assert [a.alarm_id for a in alarms] == ["A1"]


async def test_unexpected_alarm_shape_warns_once(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, caplog: pytest.LogCaptureFixture
) -> None:
    aioclient_mock.post(LOGIN_URL, json=fixture("login.json"))
    aioclient_mock.post(ALARMS_URL, json={"ret": 1, "code": "200", "data": "onverwacht"})
    client = _client(hass)
    assert await client.async_get_alarms("1000001") == []
    assert await client.async_get_alarms("1000001") == []
    assert caplog.text.count("onverwachte vorm") == 1
