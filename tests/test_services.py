from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.const import CONF_NAME
from homeassistant.helpers import config_validation as cv

from custom_components.hypercolor.const import DOMAIN
from custom_components.hypercolor.services import (
    CONF_CONFIG_ENTRY_ID,
    _apply_effect,
    _list_presets,
    _save_preset,
    _schema,
    _set_color,
    _upload_effect,
)


def test_service_schema_requires_mutation_fields() -> None:
    schema = _schema({vol.Required("effect_id"): cv.string})

    with pytest.raises(vol.MultipleInvalid, match="effect_id"):
        schema({CONF_CONFIG_ENTRY_ID: "entry-1"})


async def test_apply_effect_can_route_to_preset() -> None:
    client = _FakeClient()
    call = _call(client, {"preset_id": "preset-1"})

    await _apply_effect(call)

    assert client.calls == [("apply_preset", ("preset-1",), {})]


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
            {"id": "preset-1", "effect_id": "aurora"},
        ]
    }


async def test_upload_effect_accepts_inline_html() -> None:
    client = _FakeClient()
    call = _call(client, {"html": "<html></html>", "file_name": "neon.html"})

    result = await _upload_effect(call)

    assert client.calls == [
        ("upload_effect", ("neon.html", "<html></html>"), {}),
    ]
    assert result == {"effect": {"id": "user:neon"}}


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def apply_effect(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("apply_effect", args, kwargs))

    async def apply_preset(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("apply_preset", args, kwargs))

    async def save_preset(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("save_preset", args, kwargs))
        return {"id": "preset-1", "effect_id": "aurora"}

    async def get_presets(self) -> list[dict[str, str]]:
        return [
            {"id": "preset-1", "effect_id": "aurora"},
            {"id": "preset-2", "effect_id": "rainbow"},
        ]

    async def upload_effect(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("upload_effect", args, kwargs))
        return {"id": "user:neon"}


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
