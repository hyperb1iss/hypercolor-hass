from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / ".dev" / "hass" / "config"
SOURCE_COMPONENT = ROOT / "custom_components" / "hypercolor"
DEV_COMPONENT = CONFIG_DIR / "custom_components" / "hypercolor"

CONFIGURATION = """\
default_config:

logger:
  default: info
  logs:
    custom_components.hypercolor: debug
    hypercolor: debug

http:
  server_host: 127.0.0.1
  server_port: 8123
"""


def main() -> None:
    args = _args()
    setup_dev_config()

    if args.setup_only:
        print(f"Hypercolor dev HA config ready at {CONFIG_DIR}")
        return

    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "homeassistant",
            "--config",
            str(CONFIG_DIR),
            "--debug",
        ],
    )


def setup_dev_config() -> None:
    custom_components_dir = CONFIG_DIR / "custom_components"
    custom_components_dir.mkdir(parents=True, exist_ok=True)
    _write_if_missing(CONFIG_DIR / "configuration.yaml", CONFIGURATION)
    _write_if_missing(CONFIG_DIR / "automations.yaml", "[]\n")
    _write_if_missing(CONFIG_DIR / "scripts.yaml", "{}\n")
    _write_if_missing(CONFIG_DIR / "scenes.yaml", "[]\n")
    _link_component()


def _link_component() -> None:
    if DEV_COMPONENT.is_symlink() and DEV_COMPONENT.resolve() == SOURCE_COMPONENT:
        return
    if DEV_COMPONENT.exists() or DEV_COMPONENT.is_symlink():
        msg = f"{DEV_COMPONENT} already exists and is not the Hypercolor dev symlink"
        raise SystemExit(msg)
    DEV_COMPONENT.symlink_to(SOURCE_COMPONENT, target_is_directory=True)


def _write_if_missing(path: Path, contents: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and run a throwaway Home Assistant dev instance."
    )
    parser.add_argument("--setup-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
