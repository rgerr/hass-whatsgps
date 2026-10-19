# WhatsGPS-API: verkenning fase 1 (variant B)

Datum: 19 oktober 2026.

## Bronnen en werkwijze

- **HAR-opname** van het webportaal, gemaakt door de auteur in Chrome,
  op 19 oktober 2026 van 09:42 tot 09:54 (lokale tijd). Inhoud: uitloggen, inloggen,
  ruim acht minuten de pagina Locatiemonitor, uitloggen. Geanalyseerd met
  `scripts/har_inspect.py`; geen ruwe waarden gelezen of opgeslagen.
- **JavaScript van het portaal** (`app.ca07087b.js` en de taalbestanden), uit de opname
  gehaald met `--extract-js` naar een map buiten de repository.
- **Twee verzoeken zonder login** met curl, vanaf de thuisverbinding (zie Blokkade 003).

Status per gegeven:

- **HAR**: gezien in de opname.
- **JS**: gezien in de JavaScript van het portaal.
- **Aangenomen**: afgeleid, nog niet bevestigd.

Alle voorbeeldwaarden in dit document zijn verzonnen.

## Conclusie

Geen van de stopcondities geldt:

| Stopconditie | Uitkomst |
|---|---|
| Portaal accepteert het account niet | Geldt niet. Inloggen werkt; de tracker staat in het portaal. |
| Door de leverancier uitgegeven appKey/secret of handtekening | Geldt niet. De headers `appid` en `appkey` hebben een vaste waarde die letterlijk in de openbare JavaScript staat (15 en 11 tekens), gelijk voor alle verzoeken. Er is geen handtekening, nonce of tijdstempel. |
| Alleen de mobiele app werkt | Geldt niet. Het webportaal gebruikt een JSON-API die ook een client zonder browser bedient. |

Een integratie is dus haalbaar met een gewone `aiohttp`-client. De open vragen staan
onderaan.

## Blokkade 003

- `statics/` (JavaScript, favicon) geeft voor elke client die geen browser is HTTP 403 met
  `{"message":"Your request is not allowed! 003"}`, ook vanaf het thuisadres. Dat raakt de
  integratie niet: die heeft `statics/` niet nodig.
- De API zelf blokkeert niet: `POST /web/api/device-service/carStatus/getByCarIds` zonder
  login geeft HTTP 401 met `{"ret":0,"msg":"No permission, cannot call","code":"10006","success":false}`,
  voor curl en voor een client met de User-Agent van Home Assistant. (HAR en curl)

## Basis-URL en vorm van de verzoeken

| Onderwerp | Gevonden | Status |
|---|---|---|
| Basis-URL | `https://www.whatsgps.com/web/api` | HAR, JS (`baseURL:"/web/api"`) |
| Regio | Eén host voor het portaal; geen regioserver gezien | HAR |
| Authenticatie | Header `token` met het token uit het loginantwoord | HAR |
| Vaste headers | `appid`, `appkey` (vaste waarden uit de JavaScript), `appversion: "1.0.0"`, `clienttype: "pc"` | HAR, JS |
| Cookies | Alleen analyse- en voorkeurcookies (`sensorsdata*`, `isCustomApp`, `site`, `domainUrl`). De sessie draait niet op een cookie. | HAR |
| Body | `application/x-www-form-urlencoded` (login) of `application/json` (status); GET met queryparameters | HAR |
| Antwoord | `{"ret": 1, "dialog": false, "code": "200", "data": ..., "time": <epoch-ms>}`; bij een fout `ret: 0` en `msg` | HAR, JS |
| Succes | `ret === 1` | JS (`SUCCESS:1`) |
| Token verlopen of ongeldig | HTTP 401. Het portaal toont dan "login verlopen", logt uit en laadt opnieuw. | JS (`TIMEOUT:401`), curl |

Of `appid` en `appkey` verplicht zijn, is niet getest: dat kan alleen met een geldig token.
`scripts/probe.py` moet dat vaststellen. (Aangenomen: verplicht.)

## Login

`POST /web/api/user-service/user/login`, `application/x-www-form-urlencoded`. (HAR, JS)

| Parameter | Inhoud | Status |
|---|---|---|
| `name` | Accountnaam of IMEI. Het testaccount logt in met het IMEI (15 cijfers). | HAR, loginpagina "account/IMEI" |
| `password` | Het wachtwoord zoals ingetypt, zonder hash (12 alfanumerieke tekens in de opname; geen MD5 of SHA-1). Alleen beschermd door HTTPS. | HAR, JS (`loginForm.password` gaat ongewijzigd mee) |
| `timeZoneSecond` | Verschil met UTC in seconden, bijvoorbeeld `7200` | HAR, JS |
| `lang` | Taalcode, bijvoorbeeld `nl` | HAR |

Antwoord (`data`), zie ook het voorbeeld onderaan:

| Veld | Inhoud | Status |
|---|---|---|
| `token` | Token van ongeveer 1.460 tekens | HAR |
| `userId`, `entId`, `userName`, `nickName` | Gebruiker en onderneming; `userName` is hier het IMEI | HAR |
| `timeZone` | `7200` (seconden) | HAR |
| `userType`, `clientType`, `objectType`, `buzType`, `mileageUnit`, `speedUnit`, `mapStatus`, `timeScale` | Instellingen | HAR |

- **Geldigheid van het token**: het antwoord noemt geen vervaltijd. Het token uit een
  eerdere sessie werkte nog bij het begin van de opname. Vernieuwen gebeurt in het portaal
  door opnieuw in te loggen na een 401. (Aangenomen: de integratie logt opnieuw in bij 401.)
- **Fout wachtwoord**: niet opgenomen. (Aangenomen: `ret: 0` met een `msg`, HTTP 200.)
  Of het account na herhaalde fouten wordt geblokkeerd, is onbekend.
- **Uitloggen**: `GET /web/api/user-service/user/logout` met de header `token`. (HAR)
- Gebruikersinfo: `GET /web/api/user-service/user/info` geeft dezelfde gegevens als de
  login, zonder token. (HAR)

## Apparaten en status in een verzoek

`POST /web/api/device-service/structure/v2/getMonitorCars`, `application/json`. Het
portaal vraagt dit elke 11 seconden op (mediaan in de opname). Het antwoord bevat per
groep alle apparaten met hun status, dus een verzoek per ronde volstaat. (HAR)

Body zoals het portaal die stuurt:

| Veld | Waarde | Status |
|---|---|---|
| `subFlag` | `0` | HAR |
| `targetEntId` | leeg | HAR |
| `carGroupIds` | ID van de groep (een cijfer in de opname) | HAR |
| `orderType` | `"0"` | HAR |
| `carId` | ID van het geselecteerde apparaat | HAR |
| `mapType` | `2` | HAR |
| `isQueryDeviceImage` | `0` of `1` | HAR |

Of het verzoek ook zonder `carId` en `carGroupIds` alle apparaten geeft, is niet getest.
Waar het portaal de groep-ID vandaan haalt, staat niet in de opname. (Open vraag 4.)

Antwoord: `data` is een lijst groepen (`carGroupId`, `carGroupName`, `monitorCarsVoList`).
Per apparaat:

| Veld | Betekenis | Status |
|---|---|---|
| `carId` | ID van het apparaat bij WhatsGPS (7 cijfers) | HAR |
| `imei` | IMEI (15 cijfers) | HAR |
| `machineName` | Naam van het apparaat | HAR |
| `carNO` | Kenteken | HAR |
| `machineType` | Modelnummer, `208` voor deze tracker | HAR |
| `simNO`, `iccid` | Simkaart | HAR |
| `active` | `1` actief; `0` toont het portaal als offline | HAR, JS |
| `activeTime`, `customExpireTime` | Datum zonder tijdzone | HAR |
| `carStatus` | Status, zie hieronder | HAR |

`carStatus`:

| Veld | Betekenis | Status |
|---|---|---|
| `lat`, `lon` | Positie | HAR; stelsel: zie Coördinaten |
| `latc`, `lonc` | "Gecorrigeerde" positie voor de kaart; in de opname gelijk aan `lat`/`lon` | HAR |
| `pointTime` | Tijd van de laatste fix, epoch-ms (UTC) | HAR; klopt met "Positioneringstijd" in het portaal |
| `heartTime` | Laatste communicatie, epoch-ms (UTC) | HAR; klopt met "signaal tijd" in het portaal |
| `staticTime` | Begin van de huidige stilstand, epoch-ms | HAR, JS |
| `speed` | Snelheid in km/h | HAR (`0`), JS (weergave als km/h) |
| `dir` | Richting in graden | HAR (`0`); eenheid aangenomen |
| `pointType` | Bron van de positie: `0` niet gelokaliseerd, `1` satelliet (GPS/BDS), `2` kompas, `3` basisstation (LBS), `4` wifi, `5` differentieel | HAR (`1`), JS (Nederlandse labels) |
| `runStatus` | `0` niet gelokaliseerd, `1` stilstand, `2` beweging, `3` snelheidsovertreding, `4` stationair (contact aan, stil) | HAR (`1`), JS |
| `online` | `1` online; `0` offline | HAR, JS |
| `accStatus` | Contact: `-1` geen gegevens, `1` aan, `0` uit | HAR (`-1`), JS |
| `alarm` | Tekst met het actieve alarm; leeg in de opname | HAR; betekenis aangenomen |
| `status` | Tekst; leeg in de opname. Het portaal kleurt rood als die `12` bevat. | HAR, JS; betekenis onbekend |
| `exData` | Tekst met `sleutel=waarde`-paren, gescheiden door `;`. Zie hieronder. | HAR |
| `wireless` | `true`: draadloze tracker (eigen accu) | HAR; betekenis aangenomen |
| `distance`, `show`, `snapshotStatus` | Onbekend | HAR |

`exData` (vergeleken met wat het portaal op hetzelfde moment toonde):

| Sleutel | Betekenis | Status |
|---|---|---|
| `power` | Accu in procent (`100`) | HAR; klopt met het portaal |
| `terminalChargingStatus` | Laden: `0` laadt niet ("niet in rekening gebracht") | HAR; aangenomen |
| `t` | Temperatuur in °C (`9`) | HAR; klopt met het portaal |
| `v` | Spanning in V (`0`) | HAR; klopt met het portaal (0,0 V) |
| `humidity` | Luchtvochtigheid in procent (`57`) | HAR; klopt met het portaal |
| `gpsMileage`, `totalMileage` | Onbekend. `gpsMileage` is NIET de kilometerstand van het portaal: bij vergelijking op 19 oktober ruim 30 procent hoger dan de stand in het portaal. | HAR, vergelijking met het portaal |
| `idleTime` | Begin van stationair draaien, bij `runStatus` 4 | JS |

**Niet in het statusantwoord gevonden:** signaalsterkte (GSM) en de actieve modus (Real
Time, Smart, Power Saving, Alarm). Zie open vraag 2.

## Kilometers

`GET /web/api/location-service/position/mileageSta?carId=<carId>`. Het portaal vraagt dit
op samen met de status. (HAR) De integratie vraagt het hooguit eens per 10 minuten op, een
verzoek per tracker; mislukt het, dan blijven de vorige waarden staan.

| Veld | Betekenis | Status |
|---|---|---|
| `todayMileages` | Afstand vandaag in meters | HAR; eenheid JS (zelfde opmaak als snelheid × 1000) |
| `totalMileages` | Totale afstand in meters | HAR, JS; in HA gelijk aan het portaal (19 oktober, op 0,01 km) |
| `totalRuntimes` | Totale looptijd | HAR; eenheid onbekend |

## Alarmen

- In de status: het veld `carStatus.alarm` (leeg in de opname). (HAR)
- Eigen endpoints, alleen gezien in de JavaScript; niet in de opname en het account had geen
  alarmen: `alarm-service/carAlarm/getAllByPage`, `getNotReadByUser`, `getById`,
  `updateReadByIds`; `alarm-service/eventCenter/pageList` en `getAlarmType`. (JS)
- Berichten: `POST user-service/userMsgDigest/getUnreadRecent` gaf een lege lijst;
  `GET user-service/userMsgDigest/getUnreadCountExist` gaf `true`. (HAR)
- Het portaal opent ook een websocket op `general-service/websocket/1/<id>`, vermoedelijk
  voor meldingen. (HAR) Een cloud-polling integratie gebruikt die niet.
- Alarmsoorten in het portaal (Alarmstatistiek): trilalarm, stroomuitval, lage accu, SOS,
  snelheidsoverschrijding, verplaatsing, sabotage, verboden rijden, offline.
- De structuur van een alarmmelding is niet met een echt alarm vastgesteld. Volgens de
  JavaScript van het portaal heeft een alarm `alarmId`, `alarmType` (code), `alarmTime`
  (tekst in UTC; het portaal zet die om naar lokale tijd), `pointTime`, `speed`, `lat`/`lon`,
  `latC`/`lonC` en `carId`. De codes 0 tot 143 met Nederlandse omschrijving staan in het
  taalbestand van het portaal (sleutel `alarmType`) en in `custom_components/whatsgps/alarms.py`.
  (JS)

## Coördinaten

- `lat`/`lon` en `latc`/`lonc` waren in alle 50 antwoorden gelijk. Het portaal tekent de
  positie op Google Maps (`mapType` 2) zonder omrekening. (HAR)
- **WGS-84, bevestigd.** De auto stond tijdens de opname thuis. Afstand tot de
  thuislocatie van Home Assistant: gelezen als WGS-84 39 m, als GCJ-02 1.136 m, als BD-09
  1.628 m. (HAR, afstandstest)
- Correctie: de eerste afstandstest gaf in alle drie de stelsels meer dan 100 km, omdat
  die een verouderde locatie uit `.storage/core.config` gebruikte. Home Assistant haalt de
  thuislocatie uit `configuration.yaml` (via `secrets.yaml`), en die overschrijft de
  opgeslagen waarde.
- In Home Assistant staat de tracker na installatie in zone `home`, en de waarden kwamen
  op 19 oktober om 11:34 overeen met het portaal (zie de overdracht).

## Tijden en tijdzone

- Tijden in antwoorden zijn epoch-milliseconden (`pointTime`, `heartTime`, `staticTime`,
  `time`), dus tijdzone-onafhankelijk. (HAR)
- Datums als tekst in verzoeken (`startTime`, `endTime` bij statistieken) zijn in UTC:
  middernacht lokale tijd verscheen als 22:00 de dag ervoor. (HAR)
- De gebruiker heeft `timeZone` 7200 (zomertijd Nederland). (HAR)

## Verbruik

Het portaal ververst elke 11 seconden; dat raakt alleen de cloud, niet de tracker. Hoe vaak
de tracker zelf een positie doorgeeft, bepaalt de modus op de tracker. In de opname was de
laatste fix enkele uren oud en de laatste communicatie enkele minuten.

## Uitkomst van de probe (19 oktober 2026)

`scripts/probe.py` is op 19 oktober door de auteur gedraaid met een eigen account.

1. **Coördinatenstelsel: WGS-84, bevestigd.** De auteur bevestigt dat de pin in het
   portaal op de echte plek van de auto stond; `lat`/`lon` is gelijk aan `latc`/`lonc`, het
   portaal tekent zonder omrekening op Google Maps, en de afstandstest met de juiste
   thuislocatie geeft 39 m als WGS-84 tegen ruim een kilometer in de andere stelsels.
2. **Signaalsterkte en modus: niet beschikbaar.** Ook `GET device-service/car/deviceDetail`
   en `GET device-service/car/getCarDiagnosis` (beide met `carId`) bevatten geen
   signaalsterkte of modus. Het portaal toont zelf ook geen signaalsterkte, alleen de tijd
   van het laatste signaal (`heartTime`, al een sensor). De modus is hooguit af te leiden
   uit de geschiedenis van verzonden commando's (`device-service/orderLog/getByCarIdPage`,
   niet onderzocht); dat is de laatst gevraagde modus, niet per se de actieve.
   `deviceDetail` bevat verder: `machineTypeName`, `online`, `runStatus`, `status`,
   `active`, `joinTime`, `serviceTime`, `customExpireTime` en gegevens van simkaart en
   kenteken. `getCarDiagnosis` bevat `totalMileage`, `totalMileageType` en `pointDt`.
3. **Alarmen:** sinds versie 0.3.0 een event-entiteit op de veldnamen uit de JavaScript. `POST alarm-service/carAlarm/getAllByPage`
   met `{"pageNum": 1, "pageSize": 10, "carId": ...}` werkt: `ret` 1, `total` 0, lege
   `data`, plus `pageIndex` en `pageSize` op het hoogste niveau. De structuur van een
   alarm is pas vast te stellen als er een is.
4. **Statusverzoek zonder `carId` en `carGroupIds` werkt** en geeft dezelfde lijst als met
   die velden. (probe)
5. **Vaste `appId`/`appKey` in de code: zo besloten.** Ze zijn ook nodig: zonder deze
   headers weigert de API een geldig token met HTTP 401, code `10006`. (probe)

Verder uit de probe: bij dit account (inloggen met het IMEI) is de `userId` gelijk aan de
`carId` van de tracker.

## Voorbeeldantwoorden (verzonnen waarden)

Login:

```json
{
  "ret": 1, "dialog": false, "code": "200", "time": 1800000000000,
  "data": {
    "token": "VOORBEELDTOKEN",
    "userId": 1000001, "entId": 100001, "userName": "356789012345678",
    "nickName": "Demo", "timeZone": 7200, "lang": "nl",
    "userType": 0, "clientType": 0, "objectType": 0, "buzType": 0,
    "mileageUnit": "0", "speedUnit": "km/h", "mapStatus": "0", "timeScale": "0"
  }
}
```

Status (`getMonitorCars`):

```json
{
  "ret": 1, "dialog": false, "code": "200", "time": 1800000000000,
  "data": [
    {
      "carGroupId": "1", "carGroupName": "Standaardgroep",
      "monitorCarsVoList": [
        {
          "carId": "1000001", "imei": "356789012345678", "machineName": "Demo",
          "carNO": "XX-000-X", "machineType": 208, "active": 1, "dataStatus": 1,
          "deviceType": 0,
          "carStatus": {
            "lat": 54.0, "lon": 3.0, "latc": 54.0, "lonc": 3.0,
            "pointTime": 1799980000000, "heartTime": 1799999640000,
            "staticTime": 1799945000000,
            "speed": 0, "dir": 0, "pointType": 1, "runStatus": 1,
            "online": 1, "accStatus": -1, "alarm": "", "status": "",
            "exData": "gpsMileage=1000;t=9;terminalChargingStatus=0;v=0;humidity=57;power=100;totalMileage=0",
            "wireless": true, "distance": 0.0, "show": 0, "snapshotStatus": 0
          }
        }
      ]
    }
  ]
}
```

Kilometers (`mileageSta`):

```json
{"ret": 1, "dialog": false, "code": "200", "time": 1800000000000,
 "data": {"todayMileages": 0, "totalMileages": 12345000, "totalRuntimes": 0}}
```
