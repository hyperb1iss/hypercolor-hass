from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
import voluptuous as vol
from homeassistant.const import CONF_NAME
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser

from custom_components.hypercolor import services as services_module
from custom_components.hypercolor.const import DOMAIN
from custom_components.hypercolor.services import (
    CONF_CONFIG_ENTRY_ID,
    SERVICE_APPLY_EFFECT,
    SERVICE_APPLY_PRESET,
    SERVICE_LIST_PRESETS,
    SERVICE_LIST_ZONES,
    SERVICE_SAVE_PRESET,
    SERVICE_SET_COLOR,
    SERVICE_SET_CONTROL,
    SERVICE_SET_ZONE,
    SERVICE_SNAPSHOT_SCENE,
    _upload_effect,
    async_setup_services,
)
from hypercolor.models import EffectPreset, EffectPresetSummary, SceneDocument, SceneSummary
from tests.support import hypercolor_payloads as payloads
from tests.support.hypercolor_payloads import PRIMARY_ZONE_ID
from tests.support.wire import minimal


async def test_registered_services_reject_non_admin_users(
    hass: HomeAssistant,
    hass_read_only_user: MockUser,
) -> None:
    _entry(hass, _Runtime())

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_APPLY_EFFECT,
            {CONF_CONFIG_ENTRY_ID: "entry-1", "effect_id": "aurora"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )


async def test_registered_apply_effect_targets_a_zone(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_APPLY_EFFECT,
        {
            CONF_CONFIG_ENTRY_ID: entry.entry_id,
            "effect_id": "aurora",
            "zone_id": "zone-1",
        },
        blocking=True,
    )

    assert runtime.client.calls == [
        (
            "apply_effect",
            ("aurora",),
            {
                "controls": None,
                "transition": None,
                "preset_id": None,
                "zone": "zone-1",
            },
        )
    ]
    assert runtime.refreshes == 1


async def test_registered_apply_effect_routes_to_preset(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_APPLY_EFFECT,
        {
            CONF_CONFIG_ENTRY_ID: entry.entry_id,
            "effect_id": "aurora",
            "preset_id": "soft",
        },
        blocking=True,
    )

    assert runtime.client.calls == [
        (
            "apply_effect",
            ("aurora",),
            {
                "controls": None,
                "transition": None,
                "preset_id": "soft",
                "zone": None,
            },
        )
    ]
    assert runtime.refreshes == 1


async def test_registered_apply_preset_uses_effect_scoped_route(
    hass: HomeAssistant,
) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_APPLY_PRESET,
        {
            CONF_CONFIG_ENTRY_ID: entry.entry_id,
            "effect_id": "aurora",
            "preset_id": "soft",
        },
        blocking=True,
    )

    assert runtime.client.calls == [("apply_effect_preset", ("aurora", "soft"), {})]
    assert runtime.refreshes == 1


async def test_registered_set_control_patches_the_active_layer(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_CONTROL,
        {CONF_CONFIG_ENTRY_ID: entry.entry_id, "control_name": "speed", "value": 40},
        blocking=True,
    )

    assert runtime.client.calls == [
        ("patch_layer_controls", ("zone-active", "layer-active", {"speed": 40}), {})
    ]
    assert runtime.refreshes == 1


async def test_registered_set_control_requires_an_active_effect(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    runtime.snapshot.state.active_effect = None
    entry = _entry(hass, runtime)

    with pytest.raises(HomeAssistantError, match="No effect is currently active"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_CONTROL,
            {CONF_CONFIG_ENTRY_ID: entry.entry_id, "control_name": "speed", "value": 40},
            blocking=True,
        )

    assert runtime.client.calls == []


async def test_registered_set_zone_patches_the_live_zone(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_ZONE,
        {
            CONF_CONFIG_ENTRY_ID: entry.entry_id,
            "zone_id": "zone-1",
            "brightness": 50,
            "enabled": True,
        },
        blocking=True,
    )

    assert runtime.client.calls == [
        ("update_zone", ("zone-1",), {"name": None, "brightness": 0.5, "enabled": True})
    ]
    assert runtime.refreshes == 1


async def test_registered_list_zones_reads_the_live_scene(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_LIST_ZONES,
        {CONF_CONFIG_ENTRY_ID: entry.entry_id},
        blocking=True,
        return_response=True,
    )

    response_data = cast(dict[str, Any], response)
    assert response_data["scene_id"] == "default"
    assert response_data["revision"] == 2
    zones = cast(list[dict[str, Any]], response_data["zones"])
    assert [zone["id"] for zone in zones] == [PRIMARY_ZONE_ID]
    assert zones[0]["layers"][0]["source"]["effect_id"] == "rainbow"
    assert runtime.refreshes == 0


async def test_registered_set_color_builds_hex_control(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_COLOR,
        {CONF_CONFIG_ENTRY_ID: entry.entry_id, "r": 128, "g": 255, "b": 0},
        blocking=True,
    )

    assert runtime.client.calls == [
        ("apply_effect", ("solid_color",), {"controls": {"color": "#80ff00"}})
    ]


async def test_registered_snapshot_scene_returns_the_saved_scene(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SNAPSHOT_SCENE,
        {CONF_CONFIG_ENTRY_ID: entry.entry_id, CONF_NAME: "Evening"},
        blocking=True,
        return_response=True,
    )

    assert runtime.client.calls == [("snapshot_scene", ("Evening",), {"description": None})]
    response_data = cast(dict[str, Any], response)
    assert response_data["scene"]["id"] == "scene-evening"
    assert response_data["scene"]["name"] == "Evening"
    assert runtime.refreshes == 1


async def test_registered_save_preset_uses_active_effect(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_PRESET,
        {
            CONF_CONFIG_ENTRY_ID: entry.entry_id,
            CONF_NAME: "Soft",
            "controls": {"speed": 40},
        },
        blocking=True,
        return_response=True,
    )

    assert runtime.client.calls == [
        (
            "save_preset",
            ("Soft", "aurora"),
            {"description": None, "controls": {"speed": 40}, "tags": None},
        )
    ]
    response_data = cast(dict[str, Any], response)
    assert response_data["preset"]["name"] == "Soft"
    assert response_data["preset"]["id"] == _PRESET_UUID


async def test_registered_list_presets_filters_without_mutating(hass: HomeAssistant) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_LIST_PRESETS,
        {CONF_CONFIG_ENTRY_ID: entry.entry_id, "effect_id": "aurora"},
        blocking=True,
        return_response=True,
    )

    response_data = cast(dict[str, Any], response)
    presets = cast(list[dict[str, Any]], response_data["presets"])
    assert [preset["id"] for preset in presets] == ["preset-1"]
    assert presets[0]["origin"] == "bundled"
    assert runtime.client.calls == [("get_effect_presets", ("aurora",), {})]
    assert runtime.refreshes == 0


async def test_registered_list_presets_defaults_to_active_effect(
    hass: HomeAssistant,
) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_LIST_PRESETS,
        {CONF_CONFIG_ENTRY_ID: entry.entry_id},
        blocking=True,
        return_response=True,
    )

    response_data = cast(dict[str, Any], response)
    presets = cast(list[dict[str, Any]], response_data["presets"])
    assert [preset["id"] for preset in presets] == ["preset-1"]
    assert runtime.client.calls == [("get_effect_presets", ("aurora",), {})]


@pytest.mark.parametrize("service_name", [SERVICE_APPLY_EFFECT, SERVICE_APPLY_PRESET])
def test_effect_scoped_service_schema_requires_effect_id(
    hass: HomeAssistant,
    service_name: str,
) -> None:
    _entry(hass, _Runtime())
    service = hass.services.async_services()[DOMAIN][service_name]
    assert service.schema is not None

    with pytest.raises(vol.MultipleInvalid, match="effect_id"):
        service.schema(
            {
                CONF_CONFIG_ENTRY_ID: "entry-1",
                "preset_id": "soft",
            }
        )


def test_apply_effect_schema_rejects_fake_entity_target(hass: HomeAssistant) -> None:
    _entry(hass, _Runtime())
    service = hass.services.async_services()[DOMAIN][SERVICE_APPLY_EFFECT]
    assert service.schema is not None

    with pytest.raises(vol.MultipleInvalid, match="entity_id"):
        service.schema(
            {
                CONF_CONFIG_ENTRY_ID: "entry-1",
                "effect_id": "aurora",
                "entity_id": "light.hypercolor",
            }
        )


def test_retired_profile_services_are_gone(hass: HomeAssistant) -> None:
    _entry(hass, _Runtime())
    registered = hass.services.async_services()[DOMAIN]

    assert "activate_profile" not in registered
    assert "save_profile" not in registered
    assert SERVICE_SNAPSHOT_SCENE in registered


async def test_upload_effect_rejects_path_outside_allowed_roots(
    hass: HomeAssistant,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)
    path = tmp_path / "secret.html"
    path.write_text("<html></html>")
    monkeypatch.setattr(hass.config, "is_allowed_path", lambda _: False)

    with pytest.raises(HomeAssistantError, match="outside Home Assistant's allowed paths"):
        await _upload_effect(_call(hass, entry, {"path": str(path)}))


async def test_upload_effect_rejects_oversized_file_before_read(
    hass: HomeAssistant,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)
    path = tmp_path / "huge.html"
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    monkeypatch.setattr(hass.config, "is_allowed_path", lambda _: True)

    with pytest.raises(HomeAssistantError, match="exceeds the 1 MiB"):
        await _upload_effect(_call(hass, entry, {"path": str(path)}))


async def test_upload_effect_rejects_path_replacement_during_open(
    hass: HomeAssistant,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _Runtime()
    entry = _entry(hass, runtime)
    path = tmp_path / "effect.html"
    outside = tmp_path / "secret.html"
    path.write_text("<html>safe</html>")
    outside.write_text("<html>secret</html>")
    monkeypatch.setattr(hass.config, "is_allowed_path", lambda _: True)
    real_open = services_module.os.open

    def replace_then_open(file_path: Any, flags: int) -> int:
        path.unlink()
        path.symlink_to(outside)
        return real_open(file_path, flags)

    monkeypatch.setattr(services_module.os, "open", replace_then_open)

    with pytest.raises(HomeAssistantError, match=r"Unable to read effect file|changed while"):
        await _upload_effect(_call(hass, entry, {"path": str(path)}))


_PRESET_UUID = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"


class _Runtime:
    def __init__(self) -> None:
        self.client = _FakeClient()
        self.refreshes = 0
        self.snapshot = SimpleNamespace(
            state=SimpleNamespace(
                active_effect_id="aurora",
                active_effect=SimpleNamespace(zone_id="zone-active", layer_id="layer-active"),
            )
        )

    async def async_mutate[ResultT](
        self,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        try:
            return await operation()
        finally:
            self.refreshes += 1


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def apply_effect(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("apply_effect", args, kwargs))

    async def apply_effect_preset(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("apply_effect_preset", args, kwargs))

    async def patch_layer_controls(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("patch_layer_controls", args, kwargs))

    async def update_zone(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("update_zone", args, kwargs))

    async def get_live_scene(self) -> SceneDocument:
        self.calls.append(("get_live_scene", (), {}))
        return SceneDocument.from_dict(
            payloads.scene_document([payloads.zone("rainbow", {"speed": 60.0}, None)])
        )

    async def snapshot_scene(self, *args: Any, **kwargs: Any) -> SceneSummary:
        self.calls.append(("snapshot_scene", args, kwargs))
        return SceneSummary.from_dict(minimal(SceneSummary, id="scene-evening", name=args[0]))

    async def save_preset(self, *args: Any, **kwargs: Any) -> EffectPreset:
        self.calls.append(("save_preset", args, kwargs))
        return EffectPreset.from_dict(
            minimal(EffectPreset, id=_PRESET_UUID, name="Soft", effect_id=_PRESET_UUID)
        )

    async def get_effect_presets(self, effect_id: str) -> list[EffectPresetSummary]:
        self.calls.append(("get_effect_presets", (effect_id,), {}))
        return [
            EffectPresetSummary.from_dict(
                minimal(
                    EffectPresetSummary,
                    id="preset-1",
                    name="Soft",
                    effect_id=effect_id,
                    origin="bundled",
                    editable=False,
                    controls={},
                )
            )
        ]

    async def upload_effect(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("upload_effect", args, kwargs))
        return {"id": "user:neon"}


def _entry(hass: HomeAssistant, runtime: _Runtime) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hyperia",
        unique_id="srv-1",
        entry_id="entry-1",
    )
    entry.runtime_data = runtime
    entry.add_to_hass(hass)
    async_setup_services(hass)
    return entry


def _call(hass: HomeAssistant, entry: MockConfigEntry, data: dict[str, Any]) -> Any:
    return SimpleNamespace(
        hass=hass,
        data={CONF_CONFIG_ENTRY_ID: entry.entry_id, **data},
    )
