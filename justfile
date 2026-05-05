set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
    just --list

sync:
    uv sync --all-groups

fmt:
    uv run ruff check . --fix
    uv run ruff format .

lint:
    uv run ruff check .
    uv run ruff format --check .

typecheck:
    uv run ty check

test:
    uv run pytest

build:
    uv build

metadata:
    uv run python scripts/check_integration_metadata.py

hass-setup:
    uv run python scripts/hass_dev.py --setup-only

hass-dev:
    uv run python scripts/hass_dev.py

hass-check:
    uv run python scripts/hass_dev.py --setup-only
    uv run hass --script check_config --config .dev/hass/config

verify: lint typecheck test metadata build

clean-hass:
    rm -rf .dev/hass/config/.storage .dev/hass/config/deps .dev/hass/config/home-assistant.log* .dev/hass/config/home-assistant_v2.db*
