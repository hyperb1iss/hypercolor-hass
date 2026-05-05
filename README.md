<h1 align="center">Hypercolor for Home Assistant</h1>

<p align="center">
  <strong>Your whole desk, your whole room, on the bus</strong><br>
  <sub>✦ Hypercolor as a first-class HA hub ✦</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Home_Assistant-2026.4.4+-e135ff?style=for-the-badge&logo=homeassistant&logoColor=white" alt="Home Assistant">
  <img src="https://img.shields.io/badge/HACS-Custom-80ffea?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=black" alt="HACS">
  <img src="https://img.shields.io/badge/Python-3.14-ff6ac1?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Local_Push-mDNS-50fa7b?style=for-the-badge&logo=zwave&logoColor=white" alt="Local push">
  <img src="https://img.shields.io/badge/Apache-2.0-f1fa8c?style=for-the-badge&logo=apache&logoColor=black" alt="Apache 2.0">
</p>

<p align="center">
  <a href="https://github.com/hyperb1iss/hypercolor-hass/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/hyperb1iss/hypercolor-hass/ci.yml?style=flat-square&logo=github&logoColor=white&label=CI" alt="CI">
  </a>
  <a href="https://github.com/hyperb1iss/hypercolor-hass/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/hyperb1iss/hypercolor-hass?style=flat-square&logo=apache&logoColor=white" alt="License">
  </a>
  <a href="https://github.com/hyperb1iss/hypercolor-hass/releases">
    <img src="https://img.shields.io/github/v/release/hyperb1iss/hypercolor-hass?style=flat-square&logo=github&logoColor=white" alt="Release">
  </a>
  <a href="https://github.com/hyperb1iss/hypercolor-hass/stargazers">
    <img src="https://img.shields.io/github/stars/hyperb1iss/hypercolor-hass?style=flat-square&logo=github&logoColor=white" alt="Stars">
  </a>
</p>

<p align="center">
  <a href="#-the-pitch">Pitch</a> •
  <a href="#-features">Features</a> •
  <a href="#-requirements">Requirements</a> •
  <a href="#-install">Install</a> •
  <a href="#-entities">Entities</a> •
  <a href="#-services">Services</a> •
  <a href="#-recipes">Recipes</a> •
  <a href="#-development">Development</a> •
  <a href="#-contributing">Contributing</a>
</p>

---

## 🔮 The Pitch

[Hypercolor](https://github.com/hyperb1iss/hypercolor) is an open-source RGB lighting engine.
One daemon, every RGB device on your desk, all painted by the same effect at 60fps. Effects
are web pages, rendered headless and sampled onto your physical LED layout every frame.

This integration brings that engine into Home Assistant as a hub. Master light, scenes,
profiles, layouts, live controls, audio-reactive primitives, and full device topology
become first-class entities you can wire into automations, scripts, and dashboards.

## 🌈 Features

| | |
| - | - |
| 💎 **Master light** | brightness + effect picker, with the daemon's stable id available as an attribute for templates |
| 🦋 **Per-device lights** | opt in any device to its own light entity, registered as a child of the hub |
| 🌊 **Scenes & profiles** | activate scenes, apply profiles, save the current state as a new profile, all from a service |
| 🎯 **Layouts & presets** | select from spatial layouts and per-effect presets, exposed as native select entities |
| 🪄 **Live controls** | brightness, speed, hue shift, and intensity as Home Assistant number sliders that patch the running effect |
| 🌙 **Audio reactivity** | binary sensor for beat events with configurable hold, sensor for energy, switch to toggle audio capture |
| 🧪 **Diagnostics** | a single `run_diagnostics` service returns daemon health, coordinator state, connection history, and redaction-safe metadata |
| 💜 **Repair flows** | reauth on dropped API keys, unavailable issue when the daemon disappears, both auto-clear when fixed |
| 🌸 **mDNS discovery** | daemons advertise `_hypercolor._tcp.local.`; HA offers a one-click setup as soon as one shows up |
| 🪐 **Effect uploads** | push new HTML effects from a service call (path or inline HTML), great for blueprints |

## 📡 Requirements

- Home Assistant **2026.4.4** or newer
- Python **3.14.2+** (HA's runtime floor for this release)
- A reachable Hypercolor daemon (default port `9420`)
- Optional: an API key, if your daemon has auth turned on

The daemon is the actual lighting engine, [hyperb1iss/hypercolor](https://github.com/hyperb1iss/hypercolor).
Install it on the same network as Home Assistant, on Linux, macOS, or in a container. The
integration only ever talks to it over HTTP and a single WebSocket.

## 🛠️ Install

### HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `hyperb1iss/hypercolor-hass` with category **Integration**.
3. Search for **Hypercolor**, install, and restart Home Assistant.
4. Go to **Settings → Devices & services**. Hypercolor will already be waiting if discovery
   found a daemon. Otherwise click **Add integration** and search for it.

### Manual

```bash
git clone https://github.com/hyperb1iss/hypercolor-hass.git
cp -r hypercolor-hass/custom_components/hypercolor \
      /path/to/your/homeassistant/config/custom_components/
```

Restart Home Assistant and add the integration as above.

### Configuration

Once added, point the config flow at your daemon. Manual setup accepts:

- **Host** (default `127.0.0.1`)
- **Port** (default `9420`)
- **API key** (optional, only required if your daemon enforces auth)

Discovered daemons skip the host and port questions, just confirm and (optionally) drop in
an API key.

## 💎 Entities

Every entity attaches to a **hub device** (the daemon itself). Per-device entities attach
to **child devices** (your physical LED hardware), wired to the hub via `via_device` so
the device tree reads naturally.

### Hub device

| Entity | Type | Purpose |
| --- | --- | --- |
| `light.hypercolor` | light | master power, brightness, effect picker |
| `binary_sensor.hypercolor_connected` | binary_sensor | live connectivity to the daemon |
| `sensor.hypercolor_active_effect` | sensor | display name of the running effect |
| `sensor.hypercolor_fps` | sensor | render loop FPS |
| `select.hypercolor_scene` | select | activate a scene |
| `select.hypercolor_profile` | select | apply a profile |
| `select.hypercolor_layout` | select | switch spatial layouts |
| `select.hypercolor_preset` | select | apply a preset to the current effect |
| `button.hypercolor_previous_effect` / `next_effect` / `random_effect` | button | walk the catalog |
| `button.hypercolor_stop_effect` | button | clear the current effect |
| `button.hypercolor_discover_devices` | button | re-run device discovery |
| `number.hypercolor_brightness` / `speed` / `hue_shift` / `intensity` | number | live patches into the running effect |

### Optional channels

Toggle these in the integration's options panel:

- 🌊 **Audio entities** (`channels.audio`) — adds `binary_sensor.hypercolor_audio_beat`,
  `binary_sensor.hypercolor_audio_reactive_active`, `sensor.hypercolor_audio_energy`,
  `select.hypercolor_audio_device`, and `switch.hypercolor_audio_reactive`.
- 🧪 **Metrics entity** (`channels.metrics`) — adds `sensor.hypercolor_render_time`.
- 🦋 **Per-device entities** (`per_device_entities`) — opt specific device ids in to get
  their own light, identify button, and enabled switch.

### Live controls

The four number entities (`brightness`, `speed`, `hue_shift`, `intensity`) bind to the
matching control on the running effect. Min/max/step come from the effect's metadata, so
the slider always reflects what the active effect actually exposes. If the effect has no
matching control, the entity goes unavailable.

## 🪄 Services

Sixteen services cover the daemon's full surface area. All of them take `config_entry_id`
so multi-daemon setups stay unambiguous.

| Service | What it does |
| --- | --- |
| `hypercolor.apply_effect` | apply an effect by id, optionally with controls/transition/preset |
| `hypercolor.set_color` | shortcut for the `solid_color` effect, takes `hex` or `r/g/b` |
| `hypercolor.set_control` | patch a single control on the running effect |
| `hypercolor.activate_scene` / `create_scene` | activate or create a scene |
| `hypercolor.activate_profile` / `save_profile` | activate or capture a profile |
| `hypercolor.apply_layout` | switch spatial layouts |
| `hypercolor.apply_preset` / `save_preset` / `delete_preset` / `list_presets` | full preset CRUD |
| `hypercolor.identify_device` | flash a specific device for `duration_ms` |
| `hypercolor.set_display_face` | composite an effect onto a display face with blend mode and opacity |
| `hypercolor.upload_effect` | push a new HTML effect from a path or inline content |
| `hypercolor.run_diagnostics` | redaction-safe daemon + integration health snapshot |

The `services.yaml` ships full schemas, so the dev tools UI shows proper selectors for
every field.

## 🌊 Recipes

### Apply an effect on sunset

```yaml
alias: Sunset warm Hypercolor
trigger:
  - platform: sun
    event: sunset
action:
  - service: hypercolor.apply_effect
    data:
      config_entry_id: !input config_entry_id
      effect_id: warm_sunset
```

### Bass-reactive automation across the room

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
      transition: 0.1
```

The audio beat sensor uses a configurable hold (`audio_beat_hold_ms`, default 100ms) so
brief beats actually trigger automations instead of bouncing too fast for HA to see.

### Live tweak from a dashboard

```yaml
type: entities
title: Hypercolor
entities:
  - light.hypercolor
  - sensor.hypercolor_active_effect
  - select.hypercolor_scene
  - select.hypercolor_preset
  - number.hypercolor_brightness
  - number.hypercolor_speed
  - number.hypercolor_hue_shift
  - number.hypercolor_intensity
```

More examples live in [`examples/`](examples/).

## 🦋 Discovery & connectivity

Hypercolor daemons advertise on mDNS as `_hypercolor._tcp.local.` with an `id` property
that becomes the integration's unique id. That means the same daemon keeps the same config
entry across IP changes, container restarts, and network re-shuffles.

The integration also runs a background WebSocket session against the daemon. Events
trigger immediate coordinator refreshes; metrics, device metrics, and audio spectrum are
opt-in channels that ride the same socket. If the WebSocket drops, the integration
backs off exponentially and retries forever, so HA's connectivity sensor reflects reality
without needing per-tick polling.

## 🧪 Development

This project uses [`uv`](https://github.com/astral-sh/uv) and [`just`](https://github.com/casey/just).
Python 3.14, ruff, ty, pytest. The dev tooling expects a sibling checkout of
[`hypercolor`](https://github.com/hyperb1iss/hypercolor) at `../hypercolor` so the Python
client can be installed editable.

```bash
git clone https://github.com/hyperb1iss/hypercolor.git ../hypercolor
git clone https://github.com/hyperb1iss/hypercolor-hass.git
cd hypercolor-hass

uv sync --all-groups
just hass-dev
```

`just hass-dev` writes a throwaway HA config under `.dev/hass/config`, symlinks
`custom_components/hypercolor` into it, and boots a Home Assistant instance on
<http://127.0.0.1:8123>. No production HA config is touched.

### Tight loop

| Recipe | What it runs |
| --- | --- |
| `just fmt` | `ruff check --fix` then `ruff format` |
| `just lint` | `ruff check` and `ruff format --check` |
| `just typecheck` | `ty check` against the integration |
| `just test` | full pytest suite |
| `just metadata` | manifest, hacs.json, services.yaml, strings.json checks |
| `just hass-check` | Home Assistant config validation against the throwaway config |
| `just verify` | the whole pipeline: lint → typecheck → test → metadata → build |
| `just clean-hass` | reset transient HA state under `.dev/` |

Pre-commit is wired up too:

```bash
uv run pre-commit install
```

ruff and ty run on every commit.

### Tests

Unit tests live under `tests/` and use `pytest-homeassistant-custom-component` to bring up
a real HA instance per test. The end-to-end suite (`tests/test_hass_e2e.py`) exercises
the full integration lifecycle against a mock daemon. Pass `HYPERCOLOR_HASS_REAL_E2E=1`
and run `just e2e-real` to point it at a real daemon.

## 💜 Contributing

PRs welcome. The bar is:

1. `just verify` is green
2. Tests cover anything you added or changed
3. Conventional commits (`feat(hass):`, `fix(hass):`, etc.)
4. No `SyncHypercolorClient` import — the integration is async only

For larger ideas, open an issue first so we can sketch the shape before you write the
code. Driver work, spatial topology, and effect authoring all live upstream in
[`hypercolor`](https://github.com/hyperb1iss/hypercolor); this repo is just the bridge.

## 🌙 Related

- 💜 [Hypercolor](https://github.com/hyperb1iss/hypercolor) — the engine and daemon
- 🌌 [SignalRGB Home Assistant](https://github.com/hyperb1iss/signalrgb-homeassistant) — sister integration for SignalRGB on Windows
- 🪄 [hyper-light-card](https://github.com/hyperb1iss/hyper-light-card) — Lovelace card built around effect catalogs

## 📄 License

Apache-2.0. See [LICENSE](LICENSE).

---

<p align="center">
  <a href="https://github.com/hyperb1iss/hypercolor-hass">
    <img src="https://img.shields.io/github/stars/hyperb1iss/hypercolor-hass?style=social" alt="Star on GitHub">
  </a>
  &nbsp;&nbsp;
  <a href="https://ko-fi.com/hyperb1iss">
    <img src="https://img.shields.io/badge/Ko--fi-Support%20Development-ff5e5b?logo=ko-fi&logoColor=white" alt="Ko-fi">
  </a>
</p>

<p align="center">
  <sub>
    If Hypercolor lights up your home, give us a ⭐ or
    <a href="https://ko-fi.com/hyperb1iss">support the project</a><br><br>
    ✦ Built by <a href="https://hyperbliss.tech"><strong>Hyperbliss</strong></a> ✦
  </sub>
</p>
