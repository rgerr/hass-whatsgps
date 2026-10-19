"""Tests voor scripts/har_inspect.py op een synthetische opname met nepwaarden."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "har_inspect.py"
_spec = importlib.util.spec_from_file_location("har_inspect", SCRIPT)
assert _spec and _spec.loader
har_inspect = importlib.util.module_from_spec(_spec)
sys.modules["har_inspect"] = har_inspect
_spec.loader.exec_module(har_inspect)

# Alle waarden zijn verzonnen.
ACCOUNT = "demo_account"
PASSWORD_MD5 = hashlib.md5(b"geen-echt-wachtwoord").hexdigest()
TOKEN = "FAKETOKEN1234567890abcdef"
SESSION = "FAKESESSIONABC123"
USER_ID = 987654
CAR_ID = 555001
IMEI = "356789012345678"
HOME = (54.0, 3.0)  # Noordzee, verzonnen
CAR_LAT, CAR_LON = 54.0001, 3.0001
SECRETS = [ACCOUNT, PASSWORD_MD5, TOKEN, SESSION, str(USER_ID), str(CAR_ID), IMEI, "Testnaam", "Testauto"]
COORD_TEXTS = ["54.0", "3.0001", "54.0001"]


def _entry(
    method: str,
    url: str,
    started: str,
    response_body: Any = None,
    mime: str = "application/json",
    post: dict[str, Any] | None = None,
    request_headers: list[dict[str, str]] | None = None,
    response_headers: list[dict[str, str]] | None = None,
    cookies: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    text = response_body if isinstance(response_body, str) else json.dumps(response_body)
    request: dict[str, Any] = {
        "method": method,
        "url": url,
        "headers": request_headers or [],
        "cookies": cookies or [],
    }
    if post:
        request["postData"] = post
    return {
        "startedDateTime": started,
        "request": request,
        "response": {
            "status": 200,
            "headers": [{"name": "Content-Type", "value": mime}, *(response_headers or [])],
            "cookies": [],
            "content": {"mimeType": mime, "text": text},
        },
    }


def _car(t_ms: int) -> dict[str, Any]:
    return {
        "ret": 1,
        "data": [
            {
                "carId": CAR_ID,
                "imei": IMEI,
                "machineName": "Testauto",
                "lat": CAR_LAT,
                "lng": CAR_LON,
                "speed": 0,
                "status": "1",
                "valid": 1,
                "gpsTime": "2026-10-18 22:00:00",
                "heartTime": t_ms,
                "battery": 80,
                "pointType": 1,
                "runStatus": 0,
                "exData": "gpsMileage=1234567;t=9;terminalChargingStatus=0;v=0;humidity=55;power=100",
            }
        ],
    }


def _har() -> dict[str, Any]:
    cookie = [{"name": "JSESSIONID", "value": SESSION}]
    token_header = [
        {"name": "X-Token", "value": TOKEN},
        {"name": "clienttype", "value": "pc"},
        {"name": "appversion", "value": "1.2.3"},
    ]
    entries = [
        _entry("GET", "https://www.example.test/", "2026-10-18T20:00:00.000Z", "<html></html>", "text/html"),
        _entry("GET", "https://www.example.test/statics/js/app.js", "2026-10-18T20:00:01.000Z", "var a=1;", "text/js"),
        _entry(
            "POST",
            "https://www.example.test/user/login.do",
            "2026-10-18T20:00:02.000Z",
            {"ret": 1, "msg": "ok", "data": {"token": TOKEN, "userId": USER_ID, "name": "Testnaam"}},
            post={
                "mimeType": "application/x-www-form-urlencoded",
                "text": f"name={ACCOUNT}&password={PASSWORD_MD5}&lang=nl",
            },
            response_headers=[{"name": "Set-Cookie", "value": f"JSESSIONID={SESSION}; Path=/; HttpOnly"}],
        ),
        _entry(
            "GET",
            f"https://www.example.test/car/list.do?token={TOKEN}&userId={USER_ID}&t=1792353603000",
            "2026-10-18T20:00:03.000Z",
            _car(1792353600000),
            request_headers=token_header,
            cookies=cookie,
        ),
        _entry(
            "GET",
            f"https://www.example.test/car/list.do?token={TOKEN}&userId={USER_ID}&t=1792353613000",
            "2026-10-18T20:00:13.000Z",
            _car(1792353610000),
            request_headers=token_header,
            cookies=cookie,
        ),
        _entry(
            "GET",
            f"https://www.example.test/device/{IMEI}/info",
            "2026-10-18T20:00:14.000Z",
            {IMEI: {"lat": CAR_LAT, "lng": CAR_LON}},
            mime="application/javascript",
        ),
    ]
    return {"log": {"entries": entries}}


@pytest.fixture
def report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    har = tmp_path / "opname.har"
    har.write_text(json.dumps(_har()), encoding="utf-8")
    monkeypatch.setenv("WHATSGPS_HOME_LAT", str(HOME[0]))
    monkeypatch.setenv("WHATSGPS_HOME_LON", str(HOME[1]))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert har_inspect.main([str(har)]) == 0
    return buffer.getvalue()


def test_no_secrets_or_coordinates_in_output(report: str) -> None:
    for secret in SECRETS:
        assert secret not in report, secret
    for coord in COORD_TEXTS:
        assert coord not in report, coord


def test_placeholders_link_values_across_requests(report: str) -> None:
    assert "token: <TOKEN_1: str len=25 alfanumeriek>" in report
    assert "x-token=<TOKEN_1>" in report
    assert "JSESSIONID=<COOKIE_1>" in report
    assert "set-cookie: JSESSIONID=<COOKIE_1> Path=/; HttpOnly" in report
    assert "userId: <USER_1: int>" in report
    assert "userId: <USER_1: str len=6 cijfers>" in report
    assert "/device/<IMEI_1>/info" in report
    assert "<IMEI_1>: {" in report


def test_password_shows_only_length_and_charset(report: str) -> None:
    assert "password: <PASSWORD_1: wachtwoord len=32 hex-klein (MD5?)>" in report


def test_literal_values_only_for_harmless_fields(report: str) -> None:
    assert "ret: 1" in report
    assert 'msg: "ok"' in report
    assert 'status: "1"' in report
    assert "valid: 1" in report
    assert "battery: 80" in report
    assert 'lang: "nl"' in report
    assert "pointType: 1" in report
    assert "runStatus: 0" in report


def test_exdata_pairs_show_names_and_harmless_values(report: str) -> None:
    assert (
        "exData: <sleutel=waarde: gpsMileage=<int>; t=9; terminalChargingStatus=0; v=0; humidity=55; power=100>"
        in report
    )
    assert "1234567" not in report


def test_harmless_header_values_are_shown(report: str) -> None:
    assert 'clienttype="pc"' in report
    assert 'appversion="1.2.3"' in report


def test_times_shown_as_offsets(report: str) -> None:
    assert "gpsTime: <datetime zonder zone, als UTC t.o.v. verzoek +2.0h>" in report
    assert "heartTime: <epoch-ms? t.o.v. verzoek -3s>" in report


def test_repeats_and_signature_summary(report: str) -> None:
    assert "GET www.example.test/car/list.do -> 200: 2 keer (#4), mediaan interval 10 s" in report
    assert "t: 2 keer, 2 verschillende waarden, wisselt per verzoek: ja" in report
    assert "Statische bestanden overgeslagen: 1" in report


def test_javascript_typed_api_response_is_parsed(report: str) -> None:
    assert "antwoord (application/javascript): {" in report


def test_coordinate_distances(report: str) -> None:
    line = next(x for x in report.splitlines() if "coordinatenpaar lat/lng" in x)
    assert "gelezen als WGS-84 13 m" in line


def test_gcj02_roundtrip_and_offset() -> None:
    wgs = (39.9087, 116.3975)  # Beijing, waar GCJ-02 een bekende verschuiving van honderden meters geeft
    gcj = har_inspect.wgs84_to_gcj02(*wgs)
    assert 300 < har_inspect.distance_m(*wgs, *gcj) < 800
    back = har_inspect.gcj02_to_wgs84(*gcj)
    assert har_inspect.distance_m(*wgs, *back) < 0.5


def test_gcj02_has_no_china_exception() -> None:
    gcj = har_inspect.wgs84_to_gcj02(*HOME)
    assert har_inspect.distance_m(*HOME, *gcj) > 10


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("password", ("password", "PASSWORD")),
        ("userPwd", ("password", "PASSWORD")),
        ("token", ("secret", "TOKEN")),
        ("imei", ("secret", "IMEI")),
        ("carId", ("secret", "CAR")),
        ("lat", ("coord", "COORD")),
        ("platenumber", ("secret", "PLATE")),
        ("modelName", ("literal", "")),
        ("valid", ("literal", "")),
        ("machineName", ("secret", "NAME")),
        ("gpsTime", ("plain", "")),
    ],
)
def test_classify(key: str, expected: tuple[str, str]) -> None:
    assert har_inspect.classify(key) == expected


def test_gcj02_position_is_recognised() -> None:
    inspector = har_inspect.Inspector(HOME)
    lat, lon = har_inspect.wgs84_to_gcj02(*HOME)
    line = inspector.coord_line({"lat": lat, "lng": lon}, "lat", "lng", "#1 antwoord")
    assert "als GCJ-02 0 m" in line
    assert "als WGS-84 0 m" not in line


def test_extract_js_skips_api_responses_typed_as_javascript(tmp_path: Path) -> None:
    target = tmp_path / "js"
    assert har_inspect.extract_js(_har()["log"]["entries"], target) == 1
    assert [p.name for p in target.iterdir()] == ["app.js"]


def test_extract_js_refuses_target_inside_repository() -> None:
    with pytest.raises(SystemExit):
        har_inspect.extract_js([], SCRIPT.parent / "js")
