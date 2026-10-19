"""Eenmalige controle van de WhatsGPS-API met je eigen account, met geanonimiseerde uitvoer.

Gebruik (alleen de standaardbibliotheek, Python 3.11 of nieuwer):

    python scripts/probe.py

Account en wachtwoord komen uit WHATSGPS_ACCOUNT en WHATSGPS_PASSWORD. Zijn die niet
gezet, dan vraagt het script erom zonder ze op het scherm te tonen. Met
WHATSGPS_HOME_LAT en WHATSGPS_HOME_LON toont het per positie de afstand tot huis,
gelezen als WGS-84, GCJ-02 en BD-09.

Het script logt een keer in, doet alleen leesverzoeken en logt daarna uit. Het toont
de structuur van de antwoorden, nooit wachtwoord, token, IMEI, ID's of coordinaten
(zie har_inspect.py voor de redactie).
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import har_inspect

BASE_URL = "https://www.whatsgps.com/web/api"
# Vaste waarden van het internationale webportaal (openbare JavaScript), zie docs/api.md.
PORTAL_HEADERS = {
    "appId": "ABROAD_WHATSGPS",
    "appKey": "ljdw-abroad",
    "appVersion": "1.0.0",
    "clientType": "pc",
    "Accept": "application/json",
}
TIMEOUT = 15

Send = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]


def send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, Any]:
    """Een HTTP-verzoek; geeft (status, JSON of None). Gooit nooit bij een HTTP-fout."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as err:
        status, raw = err.code, err.read()
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None


class Probe:
    def __init__(self, transport: Send, home: har_inspect.Home | None, out: Callable[[str], None]) -> None:
        self.transport = transport
        self.inspector = har_inspect.Inspector(home)
        self.out = out
        self.token = ""
        self.step = 0

    def secret(self, kind: str, value: str) -> None:
        if value:
            self.inspector.registry.register(kind, value)

    def call(
        self,
        title: str,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
        portal_headers: bool = True,
        show: bool = True,
    ) -> Any:
        self.step += 1
        headers = dict(PORTAL_HEADERS) if portal_headers else {"Accept": "application/json"}
        if self.token:
            headers["token"] = self.token
        body: bytes | None = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(json_body).encode()
        elif form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = urllib.parse.urlencode(form).encode()
        url = f"{BASE_URL}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        self.inspector.now = datetime.now(UTC)
        try:
            status, data = self.transport(method, url, headers, body)
        except (OSError, TimeoutError) as err:
            self.out(f"#{self.step} {title}: {method} {path} -> verbindingsfout {type(err).__name__}")
            return None
        where = f"#{self.step}"
        self.inspector.entry_labels[self.step] = f"{method} {path}"
        lines: list[str] = []
        if isinstance(data, dict):
            ret, code, msg = data.get("ret"), data.get("code"), data.get("msg")
            summary = f"ret={ret!r} code={code!r}"
            if msg:
                summary += f" msg={self.inspector.describe('msg', msg, where)}"
        else:
            summary = "geen JSON"
        self.out(f"#{self.step} {title}: {method} {path} -> HTTP {status}, {summary}")
        if show and data is not None:
            self.inspector.render_field("  antwoord", data, f"{where} antwoord", 0, lines)
            for line in lines:
                self.out("  " + line)
        return data

    def run(self, account: str, password: str) -> int:
        self.secret("ACCOUNT", account)
        self.secret("PASSWORD", password)
        offset = datetime.now().astimezone().utcoffset()
        seconds = int(offset.total_seconds()) if offset else 0
        login = self.call(
            "inloggen",
            "POST",
            "user-service/user/login",
            form={"name": account, "password": password, "timeZoneSecond": seconds, "lang": "nl"},
        )
        data = login.get("data") if isinstance(login, dict) else None
        if not isinstance(data, dict) or not data.get("token"):
            self.out("Inloggen mislukt; het script stopt hier. Er wordt niet opnieuw geprobeerd.")
            return 1
        self.token = str(data["token"])
        self.secret("TOKEN", self.token)
        try:
            self.checks()
        finally:
            self.call("uitloggen", "GET", "user-service/user/logout", show=False)
            self.token = ""
        self.out("")
        skip = ("== ", "Hosts", "Statische", "Handtekening")
        for line in self.inspector.summary({}, {}, {}, 0, 0):
            if not line.startswith(skip):
                self.out(line)
        return 0

    def checks(self) -> None:
        monitor = {
            "subFlag": 0,
            "targetEntId": "",
            "carGroupIds": "",
            "orderType": "0",
            "carId": "",
            "mapType": 2,
            "isQueryDeviceImage": 0,
        }
        result = self.call(
            "status zonder carId en carGroupIds (open vraag 4)",
            "POST",
            "device-service/structure/v2/getMonitorCars",
            json_body=monitor,
        )
        car_id, group_id = first_device(result)
        if car_id is None:
            self.out("Geen apparaat in het antwoord; de overige controles hebben een carId nodig.")
            return
        self.call(
            "status met carId en carGroupIds zoals het portaal",
            "POST",
            "device-service/structure/v2/getMonitorCars",
            json_body={**monitor, "carId": car_id, "carGroupIds": group_id or ""},
            show=False,
        )
        self.call("apparaatdetails (signaal en modus?, open vraag 2)", "GET", "device-service/car/deviceDetail",
                  query={"carId": car_id})  # fmt: skip
        self.call("diagnose (signaal?)", "GET", "device-service/car/getCarDiagnosis", query={"carId": car_id})
        self.call(
            "alarmlijst (open vraag 3)",
            "POST",
            "alarm-service/carAlarm/getAllByPage",
            json_body={"pageNum": 1, "pageSize": 10, "carId": car_id},
        )
        self.call("gebruikersinfo zonder appId/appKey", "GET", "user-service/user/info", portal_headers=False,
                  show=False)  # fmt: skip


def first_device(result: Any) -> tuple[str | None, str | None]:
    if not isinstance(result, dict):
        return None, None
    for group in result.get("data") or []:
        for car in group.get("monitorCarsVoList") or []:
            if car.get("carId") is not None:
                return str(car["carId"]), str(group.get("carGroupId") or "")
    return None, None


def main(argv: list[str] | None = None, transport: Send = send) -> int:
    del argv
    account = os.environ.get("WHATSGPS_ACCOUNT") or getpass.getpass("Account of IMEI (wordt niet getoond): ")
    password = os.environ.get("WHATSGPS_PASSWORD") or getpass.getpass("Wachtwoord (wordt niet getoond): ")
    if not account or not password:
        print("Geen account of wachtwoord opgegeven.")
        return 2
    return Probe(transport, har_inspect.read_home(), print).run(account.strip(), password)


if __name__ == "__main__":
    sys.exit(main())
