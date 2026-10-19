# WhatsGPS for Home Assistant

*[Nederlands](README.nl.md)*

A custom integration that reads the position and status of GPS trackers on the WhatsGPS
platform (Seeworld), such as the Protectly GPS tracker, from the cloud. Read only: it
never sends commands to a tracker.

- One status request per round for all trackers of the account, every 60 seconds by
  default (30 to 600 seconds). Distance comes from a separate request per tracker, at
  most every 10 minutes; alarms at most every 2 minutes.
- Set up from the UI, no YAML.
- No extra Python packages.

How the API works is documented (in Dutch) in [docs/api.md](docs/api.md).

## Installation

Requires Home Assistant 2026.10 or later.

**HACS:** HACS > top-right menu > Custom repositories, add
`https://github.com/rgerr/hass-whatsgps` as type Integration, install **WhatsGPS** and
restart Home Assistant.

**Manual:** copy `custom_components/whatsgps` to `config/custom_components/whatsgps` and
restart Home Assistant.

Then: Settings > Devices & services > Add integration > **WhatsGPS**. Sign in with the
same details as on www.whatsgps.com or in the WhatsGPS app: the account name or the
tracker's IMEI, and the password. The integration checks them by actually signing in.

## Options

Under **Configure** on the integration: how often Home Assistant fetches the status (30 to
600 seconds). This does not change the tracker itself: how often it reports a position,
and how much battery that costs, depends on the mode set on the tracker (Real Time, Smart,
Power Saving or Alarm) in the WhatsGPS app.

## Entities

One device per tracker (manufacturer Protectly/WhatsGPS, the IMEI as serial number, never
in entity names). Names follow the Home Assistant language (English and Dutch included).

| Entity | Content |
|---|---|
| Device tracker | Position. Accuracy follows the position source: satellite 20 m, Wi-Fi 100 m, cell tower 500 m, so zones do not switch wrongly |
| Speed | km/h |
| Direction | degrees |
| Tracker battery | percent; the tracker's own battery, not the car's |
| Charging | on while the tracker battery charges |
| Temperature, humidity | measured inside the tracker |
| External voltage | volts of a connected power supply; 0 for a wireless tracker (diagnostic) |
| Distance today, tracker odometer | km, as the portal shows them |
| Stationary since | when the tracker stopped (only while stationary) |
| Position source | satellite, Wi-Fi, cell tower, compass, differential or not located |
| Status | moving, stationary, idling, speeding, not located or offline |
| Last position fix, last contact | timestamps |
| Online, moving | binary sensors |
| Ignition | only if the tracker reports ignition (ACC) |
| Alarm | an event per new alarm, see below |

### Alarms

Every new WhatsGPS alarm becomes one event of the **Alarm** entity, also across restarts.
On a fresh install, existing alarms are not replayed.

Event types: `geofence_enter`, `geofence_exit`, `speeding`, `tamper`, `jamming`, `sos`,
`low_battery`, `power_cut`, `vibration`, `movement`, `offline`, `collision`, `tilt`,
`towing`, `ignition_on`, `ignition_off`, `magnet`, `fake_base_station`,
`high_temperature`, `low_temperature`, `connected`, `disconnected`; unknown codes become
`other`. Every event also carries `code` (the WhatsGPS code), `description` (the Dutch
label from the portal), `alarm_time` and `speed`.

```yaml
automation:
  - alias: "Car: notify on tracker alarm"
    triggers:
      - trigger: state
        entity_id: event.car_alarm
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.event_type in ['tamper', 'jamming', 'geofence_exit', 'sos'] }}"
    actions:
      - action: notify.notify
        data:
          title: "Car"
          message: "{{ trigger.to_state.attributes.description }}"
```

## Failures and robustness

- If fetching fails, the integration retries later and later (up to every 15 minutes).
  The first two failed rounds keep the last values; after the third the entities become
  unavailable. They recover by themselves.
- If WhatsGPS rejects the password, the integration does not keep signing in (that could
  lock the account); Home Assistant asks you to sign in again.
- If a token is rejected right after a successful sign-in, that is not a password
  problem (most likely WhatsGPS changed the portal's fixed appId/appKey). The integration
  then logs an error instead of asking for the password, and becomes unavailable after
  three rounds.
- New trackers on the account get their entities automatically, without a reload. A
  tracker that left the account can be removed as a device.
- The diagnostics download contains no password, token, IMEI, plate, SIM or coordinates.

## Known limitations

- **Signal strength and tracker mode** are not provided by WhatsGPS for these trackers:
  they are not in the status, the device details or the diagnosis endpoint.
- **Alarms:** the fields come from the portal's JavaScript; no real alarm has been
  received yet to verify them. Please open an issue if an alarm looks wrong.
- The integration uses the web portal's API with the fixed `appId` and `appKey` from the
  portal's public JavaScript. If WhatsGPS changes them, the integration stops working until
  an update.
- WhatsGPS blocks its static files (`statics/`) for clients that are not a browser
  ("Your request is not allowed! 003"). The API itself is not affected.
- Only tested with an EU account on www.whatsgps.com and one tracker.

## Checking your own account

`scripts/probe.py` signs in once, makes read-only requests and prints the answers
anonymised (no password, token, IMEI, IDs or coordinates). Standard library only, Python
3.11 or later:

```
python scripts/probe.py
```

Account and password come from `WHATSGPS_ACCOUNT` and `WHATSGPS_PASSWORD`, or the script
asks for them without echoing. With `WHATSGPS_HOME_LAT` and `WHATSGPS_HOME_LON` it shows
the distance from each position to home, read as WGS-84, GCJ-02 and BD-09.

`scripts/har_inspect.py` prints an anonymised summary of a browser HAR recording of the
portal, for working out new endpoints without exposing personal data.

## Development

- Python 3.14 with `pytest-homeassistant-custom-component==0.13.373` (Home Assistant
  2026.10.2), `ruff` and `mypy`.
- `pytest`, `ruff check .`, `ruff format --check .` and
  `mypy custom_components scripts tests`. GitHub Actions runs the same on Linux.
- On Windows, Home Assistant imports the Linux-only modules `fcntl` and `resource`; local
  tests need small stand-ins for them in the virtual environment.

## Licence

MIT, see [LICENSE](LICENSE). Not affiliated with WhatsGPS or Seeworld.
