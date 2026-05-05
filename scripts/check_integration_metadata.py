from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "hypercolor"

REQUIRED_MANIFEST_KEYS = {
    "domain",
    "name",
    "version",
    "documentation",
    "issue_tracker",
    "codeowners",
    "config_flow",
    "iot_class",
    "integration_type",
    "quality_scale",
    "requirements",
    "zeroconf",
}


def main() -> None:
    manifest = _json(INTEGRATION / "manifest.json")
    hacs = _json(ROOT / "hacs.json")
    services = _yaml(INTEGRATION / "services.yaml")
    strings = _json(INTEGRATION / "strings.json")

    _require(manifest.keys() >= REQUIRED_MANIFEST_KEYS, "manifest.json is missing required keys")
    _require(manifest["domain"] == "hypercolor", "manifest domain must be hypercolor")
    _require(manifest["iot_class"] == "local_push", "Hypercolor must be local_push")
    _require(manifest["integration_type"] == "hub", "Hypercolor must declare hub integration type")
    _require(manifest["quality_scale"] == "bronze", "v1 quality scale target must be bronze")
    _require(
        manifest["zeroconf"] == [{"type": "_hypercolor._tcp.local."}],
        "manifest zeroconf record must match the daemon advertisement",
    )
    _require(hacs["homeassistant"] == "2026.4.4", "hacs.json must match the supported HA floor")
    _require("config" in strings, "strings.json must include config flow strings")
    _require(
        set(services) >= {"apply_effect", "set_control", "run_diagnostics"},
        "core services missing",
    )
    _require_no_sync_client_import()
    print("metadata ok")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _require_no_sync_client_import() -> None:
    offenders = []
    for path in INTEGRATION.rglob("*.py"):
        if "SyncHypercolorClient" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    _require(not offenders, f"SyncHypercolorClient import is forbidden: {offenders}")


if __name__ == "__main__":
    main()
