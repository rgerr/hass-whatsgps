"""Tests voor scripts/probe.py met een nep-transport: geen netwerk, alleen verzonnen waarden."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("probe", SCRIPTS / "probe.py")
assert _spec and _spec.loader
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

ACCOUNT = "356789012345678"
PASSWORD = "geenEchtWw12"
TOKEN = "NEPTOKEN" + "x" * 40
CAR_ID = 5550011
LAT, LON = 54.0002, 3.0002
SECRETS = [ACCOUNT, PASSWORD, TOKEN, str(CAR_ID), "54.0002", "3.0002", "Testauto", "XX-000-X"]


def _ok(data: Any) -> tuple[int, Any]:
    return 200, {"ret": 1, "dialog": False, "code": "200", "data": data, "time": 1800000000000}


class FakeServer:
    def __init__(self, login_ok: bool = True) -> None:
        self.login_ok = login_ok
        self.calls: list[tuple[str, str, dict[str, str], Any]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, Any]:
        parts = urlsplit(url)
        path = parts.path.removeprefix("/web/api/")
        parsed: Any = None
        if body and headers.get("Content-Type") == "application/json":
            parsed = json.loads(body)
        elif body:
            parsed = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        self.calls.append((method, path, headers, parsed))
        if path == "user-service/user/login":
            if not self.login_ok:
                return 200, {"ret": 0, "code": "500", "msg": "Onjuist wachtwoord"}
            return _ok({"token": TOKEN, "userId": 1000001, "userName": ACCOUNT, "timeZone": 7200})
        if headers.get("token") != TOKEN:
            return 401, {"ret": 0, "msg": "No permission, cannot call", "code": "10006"}
        if path == "device-service/structure/v2/getMonitorCars":
            car = {
                "carId": str(CAR_ID),
                "imei": ACCOUNT,
                "machineName": "Testauto",
                "carNO": "XX-000-X",
                "carStatus": {"lat": LAT, "lon": LON, "pointType": 1, "runStatus": 1, "online": 1},
            }
            return _ok([{"carGroupId": "1", "monitorCarsVoList": [car]}])
        if path == "user-service/user/logout":
            return _ok(None)
        return _ok({"signal": 25, "workMode": "SMART"})


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSGPS_HOME_LAT", "54.0")
    monkeypatch.setenv("WHATSGPS_HOME_LON", "3.0")


def _run(server: FakeServer) -> tuple[int, str]:
    lines: list[str] = []
    result = probe.Probe(server, probe.har_inspect.read_home(), lines.append).run(ACCOUNT, PASSWORD)
    return result, "\n".join(lines)


def test_output_contains_no_secrets(home: None) -> None:
    server = FakeServer()
    result, output = _run(server)
    assert result == 0
    for secret in SECRETS:
        assert secret not in output, secret


def test_login_uses_form_and_portal_headers(home: None) -> None:
    server = FakeServer()
    _run(server)
    method, path, headers, body = server.calls[0]
    assert (method, path) == ("POST", "user-service/user/login")
    assert body["name"] == ACCOUNT
    assert body["password"] == PASSWORD
    assert body["lang"] == "nl"
    assert headers["appId"] == "ABROAD_WHATSGPS"
    assert headers["appKey"] == "ljdw-abroad"


def test_checks_then_always_logs_out(home: None) -> None:
    server = FakeServer()
    _, output = _run(server)
    paths = [call[1] for call in server.calls]
    assert paths[-1] == "user-service/user/logout"
    assert "device-service/car/deviceDetail" in paths
    assert "alarm-service/carAlarm/getAllByPage" in paths
    # Het verzoek zonder appId/appKey stuurt die headers echt niet mee.
    info = next(call for call in server.calls if call[1] == "user-service/user/info")
    assert "appId" not in info[2]
    assert "signal: 25" in output
    assert "afstand tot huis gelezen als WGS-84" in output


def test_failed_login_stops_without_retry(home: None) -> None:
    server = FakeServer(login_ok=False)
    result, output = _run(server)
    assert result == 1
    assert len(server.calls) == 1
    assert "Inloggen mislukt" in output
    assert PASSWORD not in output
