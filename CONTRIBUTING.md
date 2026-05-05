# Contributing to Hypercolor for Home Assistant

Thanks for being here. This integration is a thin bridge between Home Assistant and the
[Hypercolor](https://github.com/hyperb1iss/hypercolor) daemon, so most lighting work lives
upstream. What lands in this repo is everything around the bridge: entities, services,
config flow, repairs, options, and the metadata that keeps HACS and HA happy.

## Setup

You need the upstream client checked out as a sibling directory so the integration can
install it editable.

```bash
git clone https://github.com/hyperb1iss/hypercolor.git ../hypercolor
git clone https://github.com/hyperb1iss/hypercolor-hass.git
cd hypercolor-hass

uv sync --all-groups
uv run pre-commit install
```

This project requires Python **3.14.2+** to match Home Assistant 2026.4.x. `uv python
install 3.14` will grab a managed interpreter if you don't have one.

## Tight loop

| Recipe | What it runs |
| --- | --- |
| `just fmt` | ruff fix + format |
| `just lint` | ruff check + format check |
| `just typecheck` | ty check |
| `just test` | pytest |
| `just metadata` | manifest, hacs.json, services.yaml, strings.json checks |
| `just hass-check` | Home Assistant config validator against the throwaway dev config |
| `just hass-dev` | boot a throwaway Home Assistant on `:8123` with the integration symlinked in |
| `just verify` | the full pipeline: lint → typecheck → test → metadata → build |

Run `just verify` before pushing. It mirrors what CI runs.

## House rules

- **Async only.** `SyncHypercolorClient` is forbidden — `scripts/check_integration_metadata.py`
  enforces it. Everything routes through `httpx.AsyncClient` and `hass.async_create_task`.
- **No new top-level dependencies** unless absolutely required. The integration ships
  through HACS, so every dependency lands in someone's HA install.
- **Coordinator-driven entities.** New entities should subscribe to one of the existing
  coordinators (`state`, `catalog`, `devices`, `metrics`, `audio`) instead of polling.
  The WebSocket loop already pumps fresh data into all of them.
- **Stable unique ids.** Build them from `runtime.server.instance_id` so an entity never
  changes id when host/port shifts.
- **Strings live in `strings.json`.** Translations (`translations/en.json`) mirror it.
  Keep them in sync.
- **Services document themselves.** Update `services.yaml` whenever you add or change a
  service handler in `services.py`.
- **Tests are mandatory.** Light, switch, button, sensor, binary sensor, number, select,
  and service surfaces all have test files. Add cases to the matching one or create a new
  test module.

## Commit style

Conventional commits, scoped to `hass`:

```
feat(hass): expose render budget sensor
fix(hass): handle missing active_effect_id from older daemons
refactor(hass): collapse coordinator setup into a helper
test(hass): cover audio reactive switch round-trip
docs(hass): expand the recipes section
```

## Pull requests

1. Branch off `main`.
2. Run `just verify` locally. CI runs the same pipeline plus `hassfest` and HACS validation.
3. Keep PRs focused. One feature, one fix, one cleanup. Mixed PRs are harder to review and
   harder to bisect later.
4. If your change touches the device or entity surface, screenshot or describe the new
   entities in the PR body.

## Reporting issues

When something breaks, the most useful payload is the output of:

```yaml
service: hypercolor.run_diagnostics
data:
  config_entry_id: <your entry id>
```

It returns daemon-side health, coordinator success state, and connection history with
hosts and keys redacted. Drop it in the issue along with HA version, daemon version, and
anything from the HA log under `custom_components.hypercolor`.

## License

By contributing you agree your changes ship under [Apache-2.0](LICENSE).
