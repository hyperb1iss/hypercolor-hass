from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.const import CONF_NAME
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockUser

from custom_components.hypercolor import services as services_module
from custom_components.hypercolor.const import DOMAIN
from custom_components.hypercolor.services import (
    CONF_CONFIG_ENTRY_ID,
    SERVICE_APPLY_EFFECT,
    _apply_effect,
    _apply_preset,
    _list_presets,
    _list_zones,
    _save_preset,
    _schema,
    _set_color,
    _set_unassigned_behavior,
    _set_zone,
    _upload_effect,
    async_setup_services,
)


def test_service_schema_requires_mutation_fields() -> None:
    schema = _schema({vol.Required("effect_id"): cv.string})

    with pytest.raises(vol.MultipleInvalid, match="effect_id"):
        schema({CONF_CONFIG_ENTRY_ID: "entry-1"})


async def test_registered_services_reject_non_admin_users(
    hass: HomeAssistant,
    hass_read_only_user: MockUser,
) -> None:
    async_setup_services(hass)

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_APPLY_EFFECT,
            {CONF_CONFIG_ENTRY_ID: "entry-1", "effect_id": "aurora"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )


async def test_apply_effect_can_route_to_preset() -> None:
    client = _FakeClient()
    call = _call(client, {"effect_id": "aurora", "preset_id": "preset-1"})

    await _apply_effect(call)

    assert client.calls == [
        ("apply_effect_preset", ("aurora", "preset-1"), {"render_group": None})
    ]


async def test_apply_effect_rejects_unscoped_preset() -> None:
    client = _FakeClient()
    call = _call(client, {"preset_id": "preset-1"})

    with pytest.raises(HomeAssistantError, match="effect_id is required"):
        await _apply_effect(call)

    assert client.calls == []


async def test_apply_preset_uses_effect_scoped_stack() -> None:
    client = _FakeClient()
    call = _call(client, {"effect_id": "aurora", "preset_id": "preset-1"})

    await _apply_preset(call)

    assert client.calls == [("apply_effect_preset", ("aurora", "preset-1"), {})]


async def test_apply_effect_targets_zone() -> None:
    client = _FakeClient()
    call = _call(client, {"effect_id": "aurora", "zone_id": "zone-1"})

    await _apply_effect(call)

    assert client.calls == [
        (
            "apply_effect",
            ("aurora",),
            {"controls": None, "transition": None, "render_group": "zone-1"},
        )
    ]


async def test_set_zone_scales_brightness_and_resolves_active_scene() -> None:
    client = _FakeClient()
    call = _call(client, {"zone_id": "zone-1", "brightness": 50, "enabled": True})

    await _set_zone(call)

    assert client.calls == [
        ("get_active_scene", (), {}),
        ("update_zone", ("scene-active", "zone-1"), {"brightness": 0.5, "enabled": True}),
    ]


async def test_set_unassigned_behavior_builds_fallback_payload() -> None:
    client = _FakeClient()
    call = _call(
        client,
        {"behavior": "fallback", "fallback_zone_id": "zone-2", "scene_id": "scene-9"},
    )

    await _set_unassigned_behavior(call)

    assert client.calls == [("set_unassigned_behavior", ("scene-9", {"fallback": "zone-2"}), {})]


async def test_list_zones_returns_jsonable_payload() -> None:
    client = _FakeClient()
    call = _call(client, {"scene_id": "scene-9"})

    result = await _list_zones(call)

    assert result == {
        "scene_id": "scene-9",
        "groups_revision": 4,
        "zones": [{"id": "zone-1", "name": "Desk", "role": "primary"}],
    }


async def test_set_color_applies_solid_color_effect() -> None:
    client = _FakeClient()
    call = _call(client, {"r": 128, "g": 255, "b": 0})

    await _set_color(call)

    assert client.calls == [
        (
            "apply_effect",
            ("solid_color",),
            {"controls": {"color": "#80ff00"}},
        )
    ]


async def test_save_preset_uses_active_effect_when_not_supplied() -> None:
    client = _FakeClient()
    call = _call(client, {CONF_NAME: "Soft", "controls": {"speed": 40}})

    result = await _save_preset(call)

    assert client.calls == [
        (
            "save_preset",
            ("Soft", "aurora"),
            {"description": None, "controls": {"speed": 40}, "tags": None},
        )
    ]
    assert result == {"preset": {"id": "preset-1", "effect_id": "aurora"}}


async def test_list_presets_filters_by_effect_id() -> None:
    client = _FakeClient()
    call = _call(client, {"effect_id": "aurora"})

    result = await _list_presets(call)

    assert result == {
        "presets": [
            {
                "id": "preset-1",
                "effect_id": "aurora",
                "origin": "bundled",
                "editable": False,
            },
        ]
    }
    assert client.calls == [("get_effect_presets", ("aurora",), {})]


async def test_list_presets_defaults_to_active_effect() -> None:
    client = _FakeClient()
    call = _call(client, {})

    await _list_presets(call)

    assert client.calls == [("get_effect_presets", ("aurora",), {})]


async def test_upload_effect_accepts_inline_html() -> None:
    client = _FakeClient()
    call = _call(client, {"html": "<html></html>", "file_name": "neon.html"})

    result = await _upload_effect(call)

    assert client.calls == [
        ("upload_effect", ("neon.html", "<html></html>"), {}),
    ]
    assert result == {"effect": {"id": "user:neon"}}


async def test_upload_effect_rejects_path_outside_allowed_roots(tmp_path: Any) -> None:
    path = tmp_path / "secret.html"
    path.write_text("<html></html>")
    call = _call(_FakeClient(), {"path": str(path)})
    call.hass.config = SimpleNamespace(is_allowed_path=lambda _: False)

    with pytest.raises(HomeAssistantError, match="outside Home Assistant's allowed paths"):
        await _upload_effect(call)


async def test_upload_effect_rejects_oversized_file_before_read(tmp_path: Any) -> None:
    path = tmp_path / "huge.html"
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    call = _call(_FakeClient(), {"path": str(path)})
    call.hass.config = SimpleNamespace(is_allowed_path=lambda _: True)

    with pytest.raises(HomeAssistantError, match="exceeds the 1 MiB"):
        await _upload_effect(call)


async def test_upload_effect_rejects_path_replacement_during_open(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "effect.html"
    outside = tmp_path / "secret.html"
    path.write_text("<html>safe</html>")
    outside.write_text("<html>secret</html>")
    call = _call(_FakeClient(), {"path": str(path)})
    call.hass.config = SimpleNamespace(is_allowed_path=lambda _: True)
    real_open = services_module.os.open

    def replace_then_open(file_path: Any, flags: int) -> int:
        path.unlink()
        path.symlink_to(outside)
        return real_open(file_path, flags)

    monkeypatch.setattr(services_module.os, "open", replace_then_open)

    with pytest.raises(HomeAssistantError, match=r"Unable to read effect file|changed while"):
        await _upload_effect(call)


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def apply_effect(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("apply_effect", args, kwargs))

    async def apply_effect_preset(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("apply_effect_preset", args, kwargs))

    async def save_preset(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("save_preset", args, kwargs))
        return {"id": "preset-1", "effect_id": "aurora"}

    async def get_effect_presets(self, effect_id: str) -> list[dict[str, Any]]:
        self.calls.append(("get_effect_presets", (effect_id,), {}))
        return [
            {
                "id": "preset-1",
                "effect_id": effect_id,
                "origin": "bundled",
                "editable": False,
            }
        ]

    async def upload_effect(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("upload_effect", args, kwargs))
        return {"id": "user:neon"}

    async def get_active_scene(self) -> Any:
        self.calls.append(("get_active_scene", (), {}))
        return SimpleNamespace(id="scene-active")

    async def update_zone(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("update_zone", args, kwargs))

    async def set_unassigned_behavior(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("set_unassigned_behavior", args, kwargs))

    async def get_zones(self, scene_id: str) -> Any:
        return SimpleNamespace(
            groups_revision=4,
            items=[{"id": "zone-1", "name": "Desk", "role": "primary"}],
        )


def _call(client: _FakeClient, data: dict[str, Any]) -> Any:
    entry = SimpleNamespace(
        domain=DOMAIN,
        entry_id="entry-1",
        title="Hyperia",
        runtime_data=SimpleNamespace(
            client=client,
            coordinators={
                "state": SimpleNamespace(
                    data={"active_effect": "Aurora", "active_effect_id": "aurora"}
                )
            },
        ),
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda entry_id: entry),
        async_add_executor_job=_run_executor_job,
    )
    return SimpleNamespace(
        hass=hass,
        data={CONF_CONFIG_ENTRY_ID: "entry-1", **data},
    )


async def _run_executor_job(func: Any, *args: Any) -> Any:
    return func(*args)
