set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# 💜 hypercolor-hass — list available recipes
default:
    just --list

# 🌀 sync all dependency groups (dev, hass, lint, test, types)
sync:
    uv sync --all-groups

# 🪄 ruff fix + format
fmt:
    uv run ruff check . --fix
    uv run ruff format .

# 🔮 ruff lint + format check
lint:
    uv run ruff check .
    uv run ruff format --check .

# 🧪 type-check with ty
typecheck:
    uv run ty check

# 🌊 run pytest
test:
    uv run pytest

# 🦋 end-to-end pytest (mocked daemon)
e2e:
    uv run pytest tests/test_hass_e2e.py

# ⚡ end-to-end pytest against a real daemon
e2e-real:
    HYPERCOLOR_HASS_REAL_E2E=1 uv run pytest tests/test_hass_e2e.py -m e2e

# 💎 build sdist + wheel
build:
    uv build

# 🎯 manifest, hacs.json, services.yaml, strings.json checks
metadata:
    uv run python scripts/check_integration_metadata.py

# 🛠️ stage the throwaway HA dev config
hass-setup:
    uv run python scripts/hass_dev.py --setup-only

# 🌙 boot a throwaway HA on :8123 with the integration symlinked in
hass-dev:
    uv run python scripts/hass_dev.py

# 🪐 run Home Assistant's config validator against the dev config
hass-check:
    uv run python scripts/hass_dev.py --setup-only
    uv run hass --script check_config --config .dev/hass/config

# 🌈 the full pipeline — what CI runs
verify: lint typecheck test metadata build

# 🔄 reset transient HA state under .dev/
clean-hass:
    rm -rf .dev/hass/config/.storage .dev/hass/config/deps .dev/hass/config/home-assistant.log* .dev/hass/config/home-assistant_v2.db*
