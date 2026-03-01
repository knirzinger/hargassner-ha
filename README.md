# Hargassner Control — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)

Bidirectional **control** of Hargassner pellet boiler systems via the [Hargassner Connect](https://web.hargassner.at) cloud portal.

---

## ⚠️ Works Best Alongside BauerGroup Hargassner Integration

> **This integration is CONTROL ONLY — it does not provide boiler sensor data.**

For the full picture — 228 live sensors including temperatures, O₂ levels, pump states, buffer data, and boiler diagnostics — install the **BauerGroup IP-HargassnerIntegration** alongside this one:

🔗 **[github.com/bauer-group/IP-HargassnerIntegration](https://github.com/bauer-group/IP-HargassnerIntegration)**

BauerGroup connects directly to the boiler via local telnet and provides the real-time sensor feed. This integration connects to the Hargassner Connect cloud portal and provides the write-back controls. **Together they give you a complete integration.**

### What this integration does NOT do

- ❌ Does not provide boiler temperature, O₂, or exhaust sensors
- ❌ Does not provide flow / return temperature readings (Vorlauf / Rücklauf)
- ❌ Does not provide pump status or boiler operational state
- ❌ Does not provide buffer or domestic hot water temperature sensors
- ❌ Does not connect to the boiler directly — all control goes via the cloud portal

### What this integration DOES do

- ✅ Sets the heating circuit mode (Automatic / Heating / Reduction / Off)
- ✅ Adjusts all heating parameters (room temps, steepness, deactivation limits)
- ✅ Controls solar mode and bathroom heating (Badewanne)
- ✅ Triggers force hot-water charge
- ✅ Updates pellet stock level
- ✅ Shows last sync timestamp and connection status
- ✅ Supports English and German (matches Hargassner API terminology)

---

## Features

- **Control-only** — 13 control entities (number, select, button) + 2 status sensors
- **Auto-discovery** — OAuth credentials extracted from live JS bundle; installation ID auto-detected
- **Self-healing** — re-extracts credentials on startup; auto-retries on 401
- **Bilingual** — full EN/DE translations using exact Hargassner portal terminology
- **Zero config** — enter only your email and password

---

## Requirements

- Home Assistant 2024.1 or later
- A [Hargassner Connect](https://web.hargassner.at) account with your boiler registered
- Internet access from your HA host (outbound HTTPS to `web.hargassner.at`)
- [BauerGroup IP-HargassnerIntegration](https://github.com/bauer-group/IP-HargassnerIntegration) recommended for sensor data

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations**
2. Click the three-dot menu → **Custom repositories**
3. Add `https://github.com/knirzinger/hargassner-ha` with category **Integration**
4. Search for **Hargassner Control** and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/hargassner_control/` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Hargassner Control**
3. Enter your Hargassner Connect **email** and **password**
4. The integration auto-discovers your installation and connects

> **Credentials note:** Only your email and password are stored. The OAuth client credentials are fetched from the Hargassner Connect web app on every startup — never hardcoded, never stored.

---

## Entities

### Sensors (read-only, status only)

| Entity | Description |
|---|---|
| `sensor.last_sync` | Timestamp of last successful data refresh |
| `sensor.connection` | Online / Offline connection status |

### Numbers (read + write)

| Entity | EN Name | DE Name | Range | Step |
|---|---|---|---|---|
| `number.room_temperature_correction` | Temperature Correction | Temperatur Korrektur | −3 … +3 °C | 0.5 |
| `number.room_temperature_heating` | Room Temperature (Heating) | Raumtemperatur Heizen | 10 … 30 °C | 0.5 |
| `number.room_temperature_reduction` | Room Temperature (Reduction) | Raumtemperatur Absenkung | 10 … 30 °C | 0.5 |
| `number.steepness` | Heating Curve Steepness | Heizkurve Steilheit | 0.2 … 3.5 | 0.05 |
| `number.deactivation_limit_heating` | Heating Off Temp | Heizen Aus Temp | −10 … 30 °C | 1.0 |
| `number.deactivation_limit_reduction_day` | Day Setback Off Temp | Tagabsenkung Aus Temp | −10 … 30 °C | 1.0 |
| `number.deactivation_limit_reduction_night` | Night Setback Off Temp | Nachtabsenkung Aus Temp | −10 … 30 °C | 1.0 |
| `number.pellet_stock` | Pellet Stock | Pellets Lagerstand | 0 … 5000 kg | 10 |

### Selects (read + write)

| Entity | EN Name | DE Name | Options |
|---|---|---|---|
| `select.heating_mode` | Heating Mode | Heizkreis Modus | Automatic / Heating / Reduction / Off |
| `select.solar_mode` | Solar Mode | Solar Modus | On / Off |
| `select.bathroom_heating` | Bathroom Heating | Badewanne / Einmalladung | On / Off |

### Buttons (action)

| Entity | EN Name | DE Name |
|---|---|---|
| `button.force_charge` | Force Hot Water Charge | Warmwasser Sofort Laden |

---

## How It Works

All communication is outbound HTTPS from your HA host to `web.hargassner.at`. No inbound connections, no MQTT, no local LAN access to the boiler.

```
Home Assistant
  └─ HargassnerCoordinator (poll every 15 min)
       └─ HargassnerApiClient
            ├─ GET  /js/app.js                              → extract client_id + client_secret
            ├─ POST /oauth/token                            → ROPC Bearer token
            ├─ GET  /api/installations/{id}/widgets         → sync current settings
            ├─ PATCH /api/installations/{id}/widgets/…      → write parameter changes
            └─ POST  /api/installations/{id}/widgets/…      → trigger actions
```

---

## Automation Examples

**Solar surplus — enable solar mode when inverter produces excess:**
```yaml
automation:
  - alias: "Hargassner solar on surplus"
    trigger:
      - platform: numeric_state
        entity_id: sensor.fronius_power_surplus
        above: 1500
    action:
      - service: select.select_option
        target:
          entity_id: select.hargassner_control_solar_mode
        data:
          option: MODE_ON
```

**Badewanne (hot water boost):**
```yaml
automation:
  - alias: "Hargassner force charge"
    trigger:
      - platform: state
        entity_id: input_boolean.badewanne_active
        to: "on"
    action:
      - service: button.press
        target:
          entity_id: button.hargassner_control_force_charge
```

**Guard room thermostats against summer mode:**
```yaml
condition:
  - condition: not
    conditions:
      - condition: state
        entity_id: select.hargassner_control_heating_mode
        state: MODE_OFF
```

---

## Troubleshooting

**`secret_extraction_failed` during setup** — The portal JS structure changed. [Open a GitHub issue](https://github.com/knirzinger/hargassner-ha/issues).

**Entities show `unavailable`** — Check **Settings → System → Logs**, filter for `hargassner_control`. Usually a network issue or portal maintenance. Connection sensor will show `offline`.

**Values bounce back after write** — The portal rejected the value (out of range). Check HA logs for HTTP status code.

---

## Known Limitations

- Heating circuit 1 only — multi-circuit installations (HK2, HK3) not yet supported
- All control via cloud — no local LAN API on the boiler itself
- ROPC OAuth grant — a legacy flow; may require updates if Hargassner migrate to auth code flow

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/js/app.js` | Extract OAuth client_id + client_secret |
| `POST` | `/oauth/token` | Obtain Bearer token (ROPC) |
| `GET` | `/api/installations/{id}/widgets` | Read all controllable settings |
| `PATCH` | `/api/installations/{id}/widgets/heating-circuits/1/parameters/{param}` | Write heating circuit parameter |
| `PATCH` | `/api/installations/{id}/widgets/heater/parameters/fuel-stock` | Update pellet stock |
| `PATCH` | `/api/installations/{id}/widgets/buffer/default/parameters/solar-mode-active` | Set solar mode |
| `POST` | `/api/installations/{id}/widgets/boilers/1/actions/force-charging` | Force hot water charge |

---

## Disclaimer

Developed by reverse-engineering network traffic from a legally owned Hargassner installation. No proprietary software was decompiled or modified. Use subject to Hargassner's terms of service. No warranty regarding API stability.

---

## License

MIT — see [LICENSE](LICENSE) file.

## Author

Ronald Knirzinger
