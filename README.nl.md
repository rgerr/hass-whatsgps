# WhatsGPS voor Home Assistant

*[English](README.md)*

Custom integration die de positie en status van een GPS-tracker op het WhatsGPS-platform
(Seeworld), zoals de Protectly GPS-tracker, uit de cloud ophaalt. Alleen lezen: de
integratie stuurt geen commando's naar de tracker.

- Een statusverzoek per ronde voor alle trackers van het account, standaard elke 60
  seconden (instelbaar van 30 tot 600 seconden). De kilometers komen uit een apart
  verzoek per tracker, hooguit eens per 10 minuten.
- Toevoegen via de gebruikersinterface, zonder YAML.
- Geen externe Python-pakketten.

De werking van de API staat in [docs/api.md](docs/api.md).

## Installatie

Vereist Home Assistant 2026.10 of nieuwer.

**Via HACS of Marketplace (aanbevolen):** zoek op **WhatsGPS**, download de integratie en
herstart Home Assistant. Vanaf Home Assistant 2026.11 zit HACS ingebouwd als Marketplace;
in 2026.10 is het HACS.

Vindt de zoekfunctie WhatsGPS niet, voeg dan `https://github.com/rgerr/hass-whatsgps` toe
als aangepaste repository van het type Integratie (in HACS: menu rechtsboven > Aangepaste
repositories), download **WhatsGPS** en herstart Home Assistant.

**Handmatig (bijvoorbeeld Synology met Docker):** kopieer de map
`custom_components/whatsgps` naar `config/custom_components/whatsgps` van Home Assistant
(op een Synology bijvoorbeeld `\\NAS\docker\homeassistant\custom_components\whatsgps`) en
herstart Home Assistant (Instellingen > Systeem > Herstarten).

Daarna: Instellingen > Apparaten en diensten > Integratie toevoegen > **WhatsGPS**. Log in
met dezelfde gegevens als op www.whatsgps.com of in de WhatsGPS-app: de accountnaam of het
IMEI-nummer, en het wachtwoord. De integratie controleert dat door echt in te loggen.

## Instellingen

Bij de integratie onder **Configureren**: hoe vaak Home Assistant de status ophaalt
(30 tot 600 seconden). Dat verandert niets aan de tracker zelf. Hoe vaak de tracker een
positie doorgeeft en hoeveel accu dat kost, bepaalt de modus op de tracker (Real Time,
Smart, Power Saving of Alarm), in te stellen in de WhatsGPS-app.

## Entiteiten

Per tracker een apparaat (fabrikant Protectly/WhatsGPS, met het IMEI als serienummer,
niet in de namen van entiteiten):

| Entiteit | Inhoud |
|---|---|
| Apparaattracker | Positie. Nauwkeurigheid naar positiebron: satelliet 20 m, wifi 100 m, zendmast 500 m, zodat zones niet ten onrechte schakelen |
| Snelheid | km/h |
| Richting | graden |
| Tracker-accu | procent; de eigen accu van de tracker, niet die van de auto |
| Opladen | aan als de tracker-accu laadt |
| Temperatuur | °C, gemeten in de tracker |
| Luchtvochtigheid | procent, gemeten in de tracker |
| Externe spanning | volt van een aangesloten voeding; 0 bij een draadloze tracker (diagnose) |
| Kilometers vandaag | km, zoals het portaal toont |
| Kilometerstand tracker | km sinds de tracker meet, zoals het portaal toont |
| Stil sinds | tijdstip waarop de tracker stil kwam te staan (alleen bij stilstand) |
| Positiebron | satelliet, wifi, zendmast, kompas, differentieel of niet gelokaliseerd |
| Status | rijdend, stilstaand, stationair, te snel, niet gelokaliseerd of offline |
| Laatste positiebepaling | tijdstip van de laatste GPS-fix |
| Laatste contact | tijdstip van het laatste bericht van de tracker (diagnose) |
| Online | verbinding met de cloud (diagnose) |
| Beweging | aan als de tracker rijdt |
| Contact | alleen als de tracker contactgegevens (ACC) levert |
| Alarm | event per nieuw alarm, zie hieronder |

### Alarmen

Elk nieuw alarm van WhatsGPS wordt een event van de entiteit **Alarm**, een keer, ook na een
herstart. Bij de eerste installatie worden oude alarmen niet alsnog gemeld. De alarmen
worden hooguit eens per 2 minuten opgehaald, en eerder als de status een alarm meldt.

Event-types: `geofence_enter`, `geofence_exit`, `speeding`, `tamper`, `jamming`, `sos`,
`low_battery`, `power_cut`, `vibration`, `movement`, `offline`, `collision`, `tilt`,
`towing`, `ignition_on`, `ignition_off` en meer; onbekende codes worden `other`. Elk event
heeft ook `code` (de WhatsGPS-code), `description` (de Nederlandse omschrijving uit het
portaal), `alarm_time` en `speed`. Voorbeeld van een automatisering in je eigen package:

```yaml
automation:
  - alias: "Auto: melding bij alarm van de tracker"
    triggers:
      - trigger: state
        entity_id: event.auto_alarm
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.event_type in ['tamper', 'jamming', 'geofence_exit', 'sos'] }}"
    actions:
      - action: notify.notify
        data:
          title: "Auto"
          message: "{{ trigger.to_state.attributes.description }}"
```

Automatiseringen horen in je eigen YAML-packages, niet in deze integratie.

## Storingen en robuustheid

- Mislukt het ophalen, dan probeert de integratie het steeds later opnieuw (tot eens per
  15 minuten). De eerste twee mislukte rondes blijven de laatste waarden staan; na de
  derde worden de entiteiten onbeschikbaar. Ze herstellen vanzelf.
- Weigert WhatsGPS het wachtwoord, dan logt de integratie niet steeds opnieuw in (dat
  kan het account blokkeren) maar vraagt Home Assistant om opnieuw in te loggen.
- Wordt een token direct na een geslaagde login toch geweigerd, dan is dat geen
  wachtwoordprobleem (vermoedelijk heeft WhatsGPS de vaste appId/appKey van het portaal
  gewijzigd). De integratie vraagt dan niet om opnieuw in te loggen, maar meldt een fout
  in het logboek en wordt na drie rondes onbeschikbaar.
- Nieuwe trackers in je account krijgen vanzelf hun entiteiten, zonder herladen. Een
  tracker die uit je account verdwijnt, kun je als apparaat verwijderen.
- De diagnose (Downloaden bij de integratie) bevat geen wachtwoord, token, IMEI,
  kenteken, simkaart of coordinaten.

## Bekende beperkingen

- **Signaalsterkte en modus** levert WhatsGPS niet voor deze tracker: ze staan niet in de
  status, de apparaatdetails of de diagnose. Zie `docs/api.md`.
- **Alarmen:** de velden komen uit de JavaScript van het portaal; er is nog geen echt alarm
  ontvangen om ze mee te controleren. Afwijkingen graag melden als issue.
- De integratie gebruikt de API van het webportaal met de vaste `appId` en `appKey` uit
  de openbare JavaScript van dat portaal. Wijzigt WhatsGPS die, dan werkt de integratie
  niet meer tot een update.
- Inloggen via Home Assistant beeindigt een sessie in het webportaal niet (meerdere
  sessies tegelijk werken). Niet getest: de app, en na hoeveel foute wachtwoorden
  WhatsGPS een account blokkeert.

- Een tracker in twee WhatsGPS-accounts tegelijk (beide toegevoegd aan Home Assistant)
  wordt niet ondersteund.

## Controle met je eigen account

`scripts/probe.py` logt een keer in, doet alleen leesverzoeken en toont de antwoorden
geanonimiseerd. Alleen de standaardbibliotheek, Python 3.11 of nieuwer:

```
python scripts/probe.py
```

Account en wachtwoord komen uit `WHATSGPS_ACCOUNT` en `WHATSGPS_PASSWORD`, of het script
vraagt erom zonder ze te tonen. Met `WHATSGPS_HOME_LAT` en `WHATSGPS_HOME_LON` toont het
de afstand van de positie tot huis.

## Ontwikkelen

- Python 3.14 met `pytest-homeassistant-custom-component==0.13.375` (Home Assistant
  2026.10.4), `ruff` en `mypy`.
- `pytest`, `ruff check .`, `ruff format --check .` en `mypy custom_components scripts tests`.
  GitHub Actions draait dezelfde stappen op Linux.
- Op Windows importeert Home Assistant de Linux-modules `fcntl` en `resource`. Voor
  lokaal testen staan daar kleine vervangers voor in de virtuele omgeving (niet in de
  repository).
