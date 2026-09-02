"""Hypercolor scenes and effects, published as Home Assistant scenes.

Voice assistants reach the `scene` domain and very little else this
integration publishes. Home Assistant exposes `scene` by default and
never exposes `select`, its Alexa bridge has no mapping for light
effects at all, and Google reaches effects only as a mode setting on
the light rather than as a target you can name. Publishing every named
scene and every catalog effect as its own scene entity is what turns
"activate Neon Rain" into a working sentence, with no cloud work on
the Hypercolor side.

Entities follow the catalog: the coordinator's push pipeline adds them
when the daemon grows a scene or effect and drops them when one goes
away. Unique ids key off the daemon's ids, so a rename upstream keeps
the entity, its history, and every automation pointed at it.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from homeassistant.components.scene import DOMAIN as SCENE_DOMAIN, Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from hypercolor.models import EffectSummary, SceneSummary

from .entity import HypercolorEntity, hub_device_info
from .models import CatalogIndex
from .runtime_data import HypercolorRuntimeData

SCENE_KIND = "scene"
EFFECT_KIND = "effect"
EFFECT_NAME_PREFIX = "Effect: "

type CatalogTarget = tuple[str, str]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    tracked: set[str] | None = None

    @callback
    def _sync_catalog_scenes() -> None:
        nonlocal tracked
        wanted = catalog_targets(runtime)
        if not wanted:
            # An empty catalog is a daemon that has not finished starting,
            # not a user who deleted everything. Pruning here would take
            # every area assignment and rename with it, so entities go
            # unavailable and wait, the stance zone lights already take.
            return
        if tracked is not None and tracked == wanted.keys():
            return
        known = tracked or set()
        fresh = [
            _ENTITY_TYPES[kind](entry, item_id)
            for unique_id, (kind, item_id) in wanted.items()
            if unique_id not in known
        ]
        tracked = set(wanted)
        _prune_departed_entities(hass, entry, runtime, tracked)
        if fresh:
            async_add_entities(fresh)

    _sync_catalog_scenes()
    entry.async_on_unload(runtime.coordinator.async_add_listener(_sync_catalog_scenes))


def catalog_targets(runtime: HypercolorRuntimeData) -> dict[str, CatalogTarget]:
    """Map every catalog entry this platform publishes to its unique id."""
    catalog = runtime.snapshot.catalog
    return {
        catalog_unique_id(runtime, kind, item.id): (kind, item.id)
        for kind, index in ((SCENE_KIND, catalog.scenes), (EFFECT_KIND, catalog.effects))
        for item in index.items
    }


def catalog_unique_id(runtime: HypercolorRuntimeData, kind: str, item_id: str) -> str:
    return f"{runtime.server.instance_id}:{kind}:{item_id}"


@callback
def _prune_departed_entities(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    runtime: HypercolorRuntimeData,
    wanted: set[str],
) -> None:
    """Drop registry rows for catalog entries the daemon no longer serves.

    Deleting a scene should delete its entity, whether Home Assistant
    watched it happen or was down at the time, so this walks the
    registry rather than only the ids added in this session.
    """
    entity_registry = er.async_get(hass)
    prefixes = tuple(catalog_unique_id(runtime, kind, "") for kind in (SCENE_KIND, EFFECT_KIND))
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if registry_entry.domain != SCENE_DOMAIN:
            continue
        if not registry_entry.unique_id.startswith(prefixes):
            continue
        if registry_entry.unique_id not in wanted:
            entity_registry.async_remove(registry_entry.entity_id)


class HypercolorCatalogScene(HypercolorEntity, Scene):
    """One activatable catalog entry, named by the daemon."""

    _attr_has_entity_name = True
    _kind: str

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], item_id: str) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._item_id = item_id
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = catalog_unique_id(runtime, self._kind, item_id)

    @property
    def available(self) -> bool:
        return super().available and self._item_id in self._index.by_id

    @property
    def name(self) -> str:
        return self._index.label(self._item_id) or self._item_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {f"{self._kind}_id": self._item_id}

    @property
    @abstractmethod
    def _index(self) -> CatalogIndex[Any]:
        """The catalog slice this entity is named and kept alive by."""


class HypercolorSavedScene(HypercolorCatalogScene):
    """A named scene on the daemon, activated whole."""

    _kind = SCENE_KIND

    async def async_activate(self, **kwargs: Any) -> None:
        await self._runtime.async_mutate(
            lambda: self._runtime.client.activate_scene(self._item_id)
        )

    @property
    def _index(self) -> CatalogIndex[SceneSummary]:
        return self.snapshot.catalog.scenes


class HypercolorEffectScene(HypercolorCatalogScene):
    """A catalog effect, applied to the live scene on activation."""

    _kind = EFFECT_KIND

    @property
    def name(self) -> str:
        return f"{EFFECT_NAME_PREFIX}{super().name}"

    async def async_activate(self, **kwargs: Any) -> None:
        await self._runtime.async_mutate(lambda: self._runtime.client.apply_effect(self._item_id))

    @property
    def _index(self) -> CatalogIndex[EffectSummary]:
        return self.snapshot.catalog.effects


_ENTITY_TYPES: dict[str, type[HypercolorCatalogScene]] = {
    SCENE_KIND: HypercolorSavedScene,
    EFFECT_KIND: HypercolorEffectScene,
}
