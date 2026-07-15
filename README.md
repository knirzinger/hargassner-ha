# Hargassner Control — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration) [![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)

Bidirectional **control** of Hargassner pellet boiler systems via the [Hargassner Connect](https://web.hargassner.at) cloud portal.

---

## ⚠️ Works Best Alongside BauerGroup Hargassner Integration

> **This integration is CONTROL ONLY — it does not provide boiler sensor data.**

For the full picture — live sensors including temperatures, O₂ levels, pump states, buffer data, and boiler diagnostics — install the **BauerGroup IP-HargassnerIntegration** alongside this one:

🔗 **[github.com/bauer-group/IP-HargassnerIntegration](https://github.com/bauer-group/IP-HargassnerIntegration)**

BauerGroup connects directly to the boiler via local telnet and provides the real-time sensor feed. This integration connects to the Hargassner Connect cloud portal and provides the write-back controls. **Together they give you a complete integration.**

### What this integration does NOT do

- ❌ Does not provide boiler temperature, O₂, or exhaust sensors
- ❌ Does not provide flow / return temperature readings (Vorlauf / Rücklauf)
- ❌ Does not provide pump status as sensors
- ❌ Does not connect to the boiler directly — all control goes via the cloud portal

### What this integration DOES do

- ✅ Sets the heating circuit mode (Automatic / Heating / Reduction / Off, plus one-time boost/setback)
- ✅ Adjusts the room temperature correction
- ✅ Sets the domestic hot-water target temperature
- ✅ Selects the heater operating program
- ✅ Controls solar mode
- ✅ Triggers a force hot-water charge
- ✅ Updates pellet stock level
- ✅ Acknowledges pending events / warnings
- ✅ Shows last sync timestamp and connection status
- ✅ Supports English and German (matches Hargassner API terminology)
- ✅ Adapts automatically to your boiler — controls appear only when your device exposes them

---

## Features

- **Control-focused** — writable numbers, selects and buttons, plus two status sensors
- **Adaptive** — entities are created dynamically from your boiler's live capabilities; range/step/options come straight from the API
- **Resilient auth** — public OAuth client credentials are built in, with an automatic self-healing re-extraction fallback if Hargassner ever rotate them
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

> **Credentials note:** Only your email and password are stored. The OAuth *client* credentials used by the ROPC grant are public application identifiers built into the integration (and self-heal from the portal if rotated) — no user secret is ever stored.

---

## Entities

Entities are created **dynamically** based on what your specific boiler exposes, so
the exact set varies by model. The tables below list everything the integration
can create.

### Sensors (status only)

| Entity              | Description                               |
| ------------------- | ----------------------------------------- |
| `sensor.last_sync`  | Timestamp of last successful data refresh |
| `sensor.connection` | Online / Offline connection status        |

### Numbers (read + write)

| Entity                                      | Description                     | Range / step from API |
| ------------------------------------------- | ------------------------------- | --------------------- |
| `number.hot_water_temperature`              | Domestic hot-water target       | e.g. 10 … 84 °C       |
| `number.pellet_stock`                       | Pellet stock                    | e.g. 0 … 7874 kg      |
| `number.room_temperature_correction`        | Room temperature correction     | e.g. −3 … +3 °C       |
| `number.room_temperature_heating`*          | Room temperature (heating)      | device-dependent      |
| `number.room_temperature_reduction`*        | Room temperature (reduction)    | device-dependent      |
| `number.steepness`*                         | Heating-curve steepness         | device-dependent      |
| `number.deactivation_limit_heating`*        | Heating off temperature         | device-dependent      |
| `number.deactivation_limit_reduction_day`*  | Day setback off temperature     | device-dependent      |
| `number.deactivation_limit_reduction_night`*| Night setback off temperature   | device-dependent      |

\* Advanced setpoints — only created on boilers that expose them (e.g. Nano.2).

### Selects (read + write)

| Entity                    | Options (from API)                                                  |
| ------------------------- | ------------------------------------------------------------------ |
| `select.heating_mode`     | Automatic / Heating / Reduction / Off / One-time Heating / One-time Reduction |
| `select.solar_mode`       | On / Off                                                            |
| `select.heater_program`   | Off / Boiler / Automatic / Stop firing                             |
| `select.bathroom_heating`*| On / Off                                                           |

\* Only created on boilers that expose it.

### Buttons (action)

| Entity                   | Description                                  |
| ------------------------ | -------------------------------------------- |
| `button.force_charge`    | Immediate hot-water charge                   |
| `button.confirm_events`  | Acknowledge all pending events / warnings    |

---

## How It Works

All communication is outbound HTTPS from your HA host to `web.hargassner.at`. No inbound connections, no MQTT, no local LAN access to the boiler.

```
Home Assistant
  └─ HargassnerCoordinator (poll every 15 min)
       └─ HargassnerApiClient
            ├─ POST /oauth/token                              → ROPC Bearer token (built-in public client creds)
            ├─ GET  /api/installations                        → discover installation(s)
            ├─ GET  /api/installations/{id}/widgets           → read current state + capabilities
            ├─ PATCH <parameter resource>                     → write a parameter change
            └─ POST  <action resource>                        → trigger an action
```

Each writable parameter in the `/widgets` response carries its own `resource` URL,
plus range/step or option metadata. The integration builds entities directly from
that, so it adapts to different boiler models without code changes.

---

## Automation Examples

**Solar surplus — enable solar mode when the inverter produces excess:**

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
          option: "on"
```

**Force a hot-water charge:**

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

---

## Troubleshooting

**`invalid_auth` during setup** — Check your Hargassner Connect email and password.

**`cannot_connect` during setup** — Your HA host cannot reach `web.hargassner.at`. Check outbound internet access. The Home Assistant log now records the actual HTTP status.

**`secret_extraction_failed`** — The built-in client credentials were rejected and the portal structure changed so they could not be re-extracted. [Open a GitHub issue](https://github.com/knirzinger/hargassner-ha/issues).

**Entities show `unavailable`** — Check **Settings → System → Logs**, filter for `hargassner_control`. Usually a network issue or portal maintenance; the connection sensor will show `offline`.

**Some controls are missing** — That is expected: the integration only creates controls your specific boiler model exposes.

---

## Known Limitations

- Heating circuit 1 only — multi-circuit installations (HK2, HK3) not yet supported
- All control via cloud — no local LAN API on the boiler itself
- Advanced heating-curve configuration (steepness/niveau) on newer portals lives behind a configurator wizard and is not exposed here

---

## Credits & Acknowledgements

- **[@lithium73fr](https://github.com/lithium73fr)** and the
  [lithium73fr/hargassner-ha](https://github.com/lithium73fr/hargassner-ha)
  integration — an invaluable reference for the current cloud API shape, the
  dynamic-entity approach, and the authentication/branding details. Thank you.
- **[BauerGroup](https://github.com/bauer-group/IP-HargassnerIntegration)** — the
  local telnet sensor integration this project is designed to complement.
- Everyone who reported issues and contributed feedback:
  [@karlspace](https://github.com/karlspace),
  [@vanouzbek](https://github.com/vanouzbek) (French translation),
  [@Offerel](https://github.com/Offerel),
  [@abarwirsch](https://github.com/abarwirsch), and
  [@eltron02](https://github.com/eltron02). Thank you all — the reports and
  comments directly shaped this release.

---

## Disclaimer

Developed by reverse-engineering network traffic from a legally owned Hargassner installation. No proprietary software was decompiled or modified. Use subject to Hargassner's terms of service. No warranty regarding API stability.

---

## License

MIT — see [LICENSE](LICENSE) file.

## Author

Ronald Knirzinger
