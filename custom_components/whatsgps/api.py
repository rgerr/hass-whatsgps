"""Asynchrone client voor de WhatsGPS-API (alleen lezen). Zie docs/api.md."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import aiohttp

from .const import (
    APP_ID,
    APP_KEY,
    APP_VERSION,
    BASE_URL,
    CLIENT_TYPE,
    COORDINATE_SYSTEM,
    LANGUAGE,
    LOGGER,
    POSITION_SOURCES,
    REQUEST_TIMEOUT,
    RUN_STATUSES,
)
from .coords import gcj02_to_wgs84

LOGIN_PATH = "user-service/user/login"
MONITOR_PATH = "device-service/structure/v2/getMonitorCars"
MILEAGE_PATH = "location-service/position/mileageSta"
ALARMS_PATH = "alarm-service/carAlarm/getAllByPage"
# Code in het antwoord als het token ontbreekt of ongeldig is (gezien met HTTP 401).
TOKEN_INVALID_CODES = {"10006"}


class WhatsGPSError(Exception):
    """Basisfout van de WhatsGPS-client."""


class WhatsGPSAuthError(WhatsGPSError):
    """Inloggen geweigerd: verkeerd account of wachtwoord."""


class WhatsGPSConnectionError(WhatsGPSError):
    """Geen verbinding, time-out of serverfout."""


class WhatsGPSResponseError(WhatsGPSError):
    """Antwoord dat niet past bij wat de API normaal geeft."""


@dataclass(frozen=True)
class LoginResult:
    user_id: str
    token: str


@dataclass(frozen=True)
class TrackerStatus:
    """Status van een tracker, omgezet uit carStatus van getMonitorCars."""

    car_id: str
    imei: str
    name: str
    model_code: int | None
    active: bool
    online: bool
    latitude: float | None
    longitude: float | None
    position_source: str | None
    run_status: str | None
    speed: float | None
    direction: int | None
    acc: bool | None
    battery: int | None
    last_fix: datetime | None
    last_communication: datetime | None
    raw: dict[str, Any] = field(repr=False, compare=False)
    # Uit exData; vergeleken met het portaal op 19 oktober 2026 (docs/api.md).
    temperature: float | None = None
    humidity: int | None = None
    voltage: float | None = None
    charging: bool | None = None
    stationary_since: datetime | None = None
    # Uit mileageSta, apart en minder vaak opgehaald (zie de coordinator).
    today_km: float | None = None
    total_km: float | None = None

    @property
    def status(self) -> str | None:
        if not self.active or not self.online:
            return "offline"
        return self.run_status

    @property
    def moving(self) -> bool | None:
        if self.run_status is None:
            return None
        return self.run_status in {"moving", "speeding"}


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _epoch_ms(value: Any) -> datetime | None:
    millis = _int(value)
    if not millis or millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=UTC)


def parse_ex_data(text: Any) -> dict[str, str]:
    """exData is tekst met sleutel=waarde-paren, gescheiden door ';'."""
    if not isinstance(text, str):
        return {}
    pairs: dict[str, str] = {}
    for part in text.replace(",", ";").split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            pairs[key.strip()] = value.strip()
    return pairs


def parse_tracker(car: dict[str, Any]) -> TrackerStatus:
    status = car.get("carStatus") or {}
    lat, lon = _float(status.get("lat")), _float(status.get("lon"))
    if lat is None or lon is None or (lat == 0 and lon == 0) or abs(lat) > 90 or abs(lon) > 180:
        lat = lon = None
    elif COORDINATE_SYSTEM == "gcj02":
        lat, lon = gcj02_to_wgs84(lat, lon)
    point_type = _int(status.get("pointType"))
    run_status = _int(status.get("runStatus"))
    acc = _int(status.get("accStatus"))
    ex_data = parse_ex_data(status.get("exData"))
    battery = _int(ex_data.get("power"))
    humidity = _int(ex_data.get("humidity"))
    charging = _int(ex_data.get("terminalChargingStatus"))
    stationary = RUN_STATUSES.get(run_status) == "stationary" if run_status is not None else False
    return TrackerStatus(
        car_id=str(car.get("carId", "")),
        imei=str(car.get("imei") or ""),
        name=str(car.get("machineName") or "WhatsGPS"),
        model_code=_int(car.get("machineType")),
        active=_int(car.get("active")) != 0,
        online=_int(status.get("online")) == 1,
        latitude=lat,
        longitude=lon,
        position_source=POSITION_SOURCES.get(point_type) if point_type is not None else None,
        run_status=RUN_STATUSES.get(run_status) if run_status is not None else None,
        speed=_float(status.get("speed")),
        direction=_int(status.get("dir")),
        acc=None if acc is None or acc < 0 else acc == 1,
        battery=battery if battery is not None and 0 <= battery <= 100 else None,
        last_fix=_epoch_ms(status.get("pointTime")),
        last_communication=_epoch_ms(status.get("heartTime")),
        raw=car,
        temperature=_float(ex_data.get("t")),
        humidity=humidity if humidity is not None and 0 <= humidity <= 100 else None,
        voltage=_float(ex_data.get("v")),
        charging=charging == 1 if charging in (0, 1) else None,
        # gpsMileage in exData is NIET de kilometerstand van het portaal (bij vergelijking ruim
        # 30 procent hoger); die komt uit mileageSta.
        stationary_since=_epoch_ms(status.get("staticTime")) if stationary else None,
    )


@dataclass(frozen=True)
class Mileage:
    """Afstand vandaag en in totaal, in km (het portaal geeft meters)."""

    today_km: float | None
    total_km: float | None


@dataclass(frozen=True)
class Alarm:
    """Een alarm uit carAlarm/getAllByPage (velden volgens de JavaScript van het portaal)."""

    alarm_id: str
    code: int | None
    time: datetime | None
    speed: float | None
    raw: dict[str, Any] = field(repr=False, compare=False)


def _utc_text_or_epoch(value: Any) -> datetime | None:
    """alarmTime: tekst in UTC (het portaal zet die om naar lokale tijd) of epoch-ms."""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return _epoch_ms(value)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("/", "-").replace(" ", "T"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def parse_alarm(item: dict[str, Any]) -> Alarm:
    code = _int(item.get("alarmType"))
    time = _utc_text_or_epoch(item.get("alarmTime")) or _epoch_ms(item.get("createTime"))
    alarm_id = item.get("alarmId") or item.get("id")
    if alarm_id is None:
        # Zonder ID: code plus tijd maakt een alarm herkenbaar.
        alarm_id = f"{code}-{time.isoformat() if time else ''}"
    return Alarm(alarm_id=str(alarm_id), code=code, time=time, speed=_float(item.get("speed")), raw=item)


def _km(meters: Any) -> float | None:
    value = _float(meters)
    return round(value / 1000, 2) if value is not None and value >= 0 else None


class WhatsGPSClient:
    """Een sessie per account. Logt alleen in als er geen geldig token is."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        account: str,
        password: str,
        *,
        timezone_seconds: int = 0,
    ) -> None:
        self._session = session
        self._account = account
        self._password = password
        self._timezone_seconds = timezone_seconds
        self._token: str | None = None
        self._login_lock = asyncio.Lock()

    async def async_login(self) -> LoginResult:
        """Inloggen; een geweigerde login wordt nooit herhaald."""
        form = {
            "name": self._account,
            "password": self._password,
            "timeZoneSecond": str(self._timezone_seconds),
            "lang": LANGUAGE,
        }
        status, body = await self._send("POST", LOGIN_PATH, data=form)
        if status >= 500:
            raise WhatsGPSConnectionError(f"Inloggen: HTTP {status}")
        if not isinstance(body, dict) or "ret" not in body:
            # Bijvoorbeeld de blokkade 003 ({"message": ...}): geen oordeel over het wachtwoord.
            raise WhatsGPSResponseError(f"Inloggen: onverwacht antwoord, HTTP {status}")
        data = body.get("data")
        if body.get("ret") != 1 or not isinstance(data, dict) or not data.get("token"):
            # De melding van de server bevat geen gevoelige gegevens; het account wel.
            raise WhatsGPSAuthError(str(body.get("msg") or "Inloggen geweigerd"))
        self._token = str(data["token"])
        LOGGER.debug("Ingelogd bij WhatsGPS")
        return LoginResult(user_id=str(data.get("userId", "")), token=self._token)

    async def async_get_trackers(self) -> list[TrackerStatus]:
        """Status van alle trackers van het account in een verzoek."""
        # Zonder carId en carGroupIds geeft de API alle trackers (probe, 19 oktober 2026).
        body = {
            "subFlag": 0,
            "targetEntId": "",
            "carGroupIds": "",
            "orderType": "0",
            "carId": "",
            "mapType": 2,
            "isQueryDeviceImage": 0,
        }
        data = await self._request("POST", MONITOR_PATH, json=body)
        if not isinstance(data, list):
            raise WhatsGPSResponseError("Statusantwoord zonder lijst")
        return [
            parse_tracker(car)
            for group in data
            if isinstance(group, dict)
            for car in group.get("monitorCarsVoList") or []
            if isinstance(car, dict) and car.get("carId") is not None
        ]

    async def async_get_mileage(self, car_id: str) -> Mileage:
        """Kilometers vandaag en totaal van een tracker, zoals het portaal ze toont."""
        data = await self._request("GET", MILEAGE_PATH, params={"carId": car_id})
        if not isinstance(data, dict):
            raise WhatsGPSResponseError("Kilometerantwoord zonder gegevens")
        return Mileage(today_km=_km(data.get("todayMileages")), total_km=_km(data.get("totalMileages")))

    async def async_get_alarms(self, car_id: str) -> list[Alarm]:
        """De meest recente alarmen van een tracker (eerste pagina)."""
        data = await self._request("POST", ALARMS_PATH, json={"pageNum": 1, "pageSize": 20, "carId": car_id})
        items = data.get("list") if isinstance(data, dict) else data
        if items is None:
            return []
        if not isinstance(items, list):
            raise WhatsGPSResponseError("Alarmantwoord zonder lijst")
        return [parse_alarm(item) for item in items if isinstance(item, dict)]

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Verzoek met token; bij een verlopen token een keer opnieuw inloggen."""
        for attempt in range(2):
            async with self._login_lock:
                if self._token is None:
                    await self.async_login()
            status, body = await self._send(method, path, token=self._token, **kwargs)
            code = str(body.get("code")) if isinstance(body, dict) else ""
            if status == 401 or code in TOKEN_INVALID_CODES:
                self._token = None
                if attempt == 0:
                    LOGGER.debug("Token verlopen; opnieuw inloggen")
                    continue
                # Een token dat direct na een geslaagde login wordt geweigerd, zegt niets over
                # het wachtwoord. Waarschijnlijker is een gewijzigde appId/appKey van het
                # portaal; een reauth zou dan alleen een lus van wachtwoordvragen geven.
                raise WhatsGPSResponseError(
                    f"{path}: token direct na inloggen geweigerd; mogelijk gewijzigde appId/appKey"
                )
            if status >= 400:
                raise WhatsGPSConnectionError(f"{path}: HTTP {status}")
            if not isinstance(body, dict) or body.get("ret") != 1:
                raise WhatsGPSResponseError(f"{path}: onverwacht antwoord")
            return body.get("data")
        raise WhatsGPSResponseError(f"{path}: geen antwoord")  # pragma: no cover

    async def _send(self, method: str, path: str, *, token: str | None = None, **kwargs: Any) -> tuple[int, Any]:
        headers = {
            "appId": APP_ID,
            "appKey": APP_KEY,
            "appVersion": APP_VERSION,
            "clientType": CLIENT_TYPE,
            "Accept": "application/json",
        }
        if token:
            headers["token"] = token
        try:
            async with self._session.request(
                method,
                f"{BASE_URL}/{path}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                **kwargs,
            ) as response:
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    body = None
                return response.status, body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WhatsGPSConnectionError(f"{path}: {type(err).__name__}") from err
