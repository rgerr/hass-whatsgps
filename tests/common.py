"""Gedeelde hulpmiddelen voor de integratietests. Alle waarden zijn verzonnen."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.whatsgps.api import ALARMS_PATH, LOGIN_PATH, MILEAGE_PATH, MONITOR_PATH
from custom_components.whatsgps.const import BASE_URL

FIXTURES = Path(__file__).parent / "fixtures"
LOGIN_URL = f"{BASE_URL}/{LOGIN_PATH}"
MONITOR_URL = f"{BASE_URL}/{MONITOR_PATH}"
MILEAGE_URL = f"{BASE_URL}/{MILEAGE_PATH}"
ALARMS_URL = f"{BASE_URL}/{ALARMS_PATH}"
NO_ALARMS = {"ret": 1, "code": "200", "total": 0, "data": [], "pageSize": 20}
MILEAGE = {"ret": 1, "code": "200", "data": {"todayMileages": 1500, "totalMileages": 1234560, "totalRuntimes": 0}}
ACCOUNT = "356789012345678"
PASSWORD = "geenEchtWw12"
TOKEN = "VOORBEELDTOKEN-NIET-ECHT"
CAR_ID = "1000001"


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def mock_api(
    aioclient_mock: AiohttpClientMocker,
    *,
    login: dict[str, Any] | None = None,
    monitor: dict[str, Any] | None = None,
    monitor_status: int = 200,
) -> None:
    aioclient_mock.post(LOGIN_URL, json=login or fixture("login.json"))
    aioclient_mock.post(MONITOR_URL, json=monitor or fixture("monitor.json"), status=monitor_status)
    aioclient_mock.get(MILEAGE_URL, json=MILEAGE)
    aioclient_mock.post(ALARMS_URL, json=NO_ALARMS)


def calls_to(aioclient_mock: AiohttpClientMocker, url: str) -> list[tuple[Any, ...]]:
    return [call for call in aioclient_mock.mock_calls if str(call[1]) == url]
