# Hypercolor for Home Assistant

Hypercolor for Home Assistant exposes a local Hypercolor daemon as a first-class HA hub: master light, scenes, profiles, layouts, presets, device topology, diagnostics, and audio-reactive primitives for whole-home automations.

This repo is a HACS custom integration. The integration targets Home Assistant `2026.4.4+`, matching the current PyPI release and its Python `3.14.2+` runtime floor.

## Local Development

```bash
uv sync --all-groups
just hass-dev
```

`just hass-dev` prepares `.dev/hass/config`, symlinks `custom_components/hypercolor` into that config directory, and starts a throwaway Home Assistant instance. Open <http://127.0.0.1:8123> and add Hypercolor from **Settings → Devices & services**.

Use these for the tight loop:

```bash
just fmt          # ruff fix + format
just verify       # lint + ty + pytest + metadata + uv build
just hass-check   # Home Assistant config validation
just clean-hass   # reset transient local HA state
```

The dev HA instance is isolated under `.dev/hass/config`; no production HA config is touched.

## Installation

1. In HACS, add this repository as a custom integration repository.
2. Install **Hypercolor**.
3. Restart Home Assistant.
4. Add the integration from **Settings → Devices & services**.

Hypercolor daemons advertise `_hypercolor._tcp.local.`. If discovery is available on your network, Home Assistant offers a one-click setup flow. Manual setup accepts host, port, and an optional API key.

## Removal

Remove the integration from **Settings → Devices & services**, then remove the repository from HACS. Restart Home Assistant to unload custom integration code fully.

## Validation

```bash
just verify
just hass-check
```

`just verify` covers Ruff, ty, pytest, integration metadata checks, and wheel construction through `uv_build`. `just hass-check` boots Home Assistant's config validator against the local throwaway config.

## Entity Semantics

The master light reports `effect` using the same display names exposed in Home
Assistant's effect picker. The daemon's stable identifier remains available as
the `active_effect_id` extra state attribute for templates and automations that
need an id instead of a label.

## Audio Hook

The audio beat and energy entities make cross-system automations straightforward:

```yaml
alias: Bass dim main lights
trigger:
  - platform: state
    entity_id: binary_sensor.hypercolor_audio_beat
    to: "on"
condition:
  - condition: numeric_state
    entity_id: sensor.hypercolor_audio_energy
    above: 0.7
action:
  - service: light.turn_on
    target:
      entity_id: light.living_room_main
    data:
      brightness_step_pct: -20
```
