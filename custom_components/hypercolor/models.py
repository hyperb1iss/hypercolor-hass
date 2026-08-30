from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Protocol, Self

from hypercolor.models import (
    AudioDevicesResponse,
    ControlDefinition,
    DeviceSummary,
    EffectDetailResponse,
    EffectPresetOrigin,
    EffectPresetSummary,
    EffectSummary,
    LayoutSummary,
    OutputPowerMode,
    OutputResource,
    SceneDocument,
    SceneSummary,
    SpatialLayout,
    SystemStatus,
    ZoneResource,
)
from hypercolor.websocket import SpectrumData

type JsonObject = dict[str, Any]

ZONE_ROLE_PRIMARY = "primary"
ZONE_ROLE_DISPLAY = "display"
DEVICE_STATUS_DISABLED = "disabled"


class NamedCatalogItem(Protocol):
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class CatalogIndex[CatalogItemT: NamedCatalogItem]:
    items: tuple[CatalogItemT, ...]
    by_id: Mapping[str, CatalogItemT]
    label_by_id: Mapping[str, str]
    id_by_label: Mapping[str, str]

    @classmethod
    def build(
        cls,
        items: Iterable[CatalogItemT],
        *,
        collision_label: Callable[[CatalogItemT], str] | None = None,
    ) -> Self:
        catalog_items = tuple(items)
        name_counts = Counter(item.name for item in catalog_items)
        by_id = {item.id: item for item in catalog_items}
        candidates = {
            item.id: (
                item.name
                if name_counts[item.name] == 1
                else collision_label(item)
                if collision_label is not None
                else f"{item.name} ({item.id})"
            )
            for item in catalog_items
        }
        candidate_counts = Counter(candidates.values())
        label_by_id = {
            item.id: (
                candidates[item.id]
                if candidate_counts[candidates[item.id]] == 1
                else f"{candidates[item.id]} [{item.id[:8]}]"
            )
            for item in catalog_items
        }
        id_by_label = {label: item_id for item_id, label in label_by_id.items()}
        return cls(
            items=catalog_items,
            by_id=MappingProxyType(by_id),
            label_by_id=MappingProxyType(label_by_id),
            id_by_label=MappingProxyType(id_by_label),
        )

    @property
    def options(self) -> list[str]:
        return [self.label_by_id[item.id] for item in self.items]

    def label(self, item_id: str | None) -> str | None:
        return self.label_by_id.get(item_id) if item_id is not None else None

    def resolve(self, label_or_id: str) -> str:
        return self.id_by_label.get(label_or_id, label_or_id)


@dataclass(frozen=True, slots=True)
class EffectLayer:
    """The addressable effect layer inside one live zone.

    Layer ids come straight off the scene document. The daemon mints
    them, so nothing here ever derives a layer id from a zone id.
    """

    zone_id: str
    layer_id: str
    effect_id: str
    control_values: Mapping[str, Any]
    preset_id: str | None


@dataclass(frozen=True, slots=True)
class ActiveEffect:
    layer: EffectLayer
    detail: EffectDetailResponse
    cover_image_url: str | None

    @property
    def id(self) -> str:
        return self.layer.effect_id

    @property
    def name(self) -> str:
        return self.detail.name

    @property
    def zone_id(self) -> str:
        return self.layer.zone_id

    @property
    def layer_id(self) -> str:
        return self.layer.layer_id

    @property
    def preset_id(self) -> str | None:
        return self.layer.preset_id

    @property
    def control_values(self) -> Mapping[str, Any]:
        return self.layer.control_values

    @property
    def controls(self) -> tuple[ControlDefinition, ...]:
        controls = self.detail.controls
        if not isinstance(controls, list):
            return ()
        return tuple(control for control in controls if isinstance(control, ControlDefinition))


@dataclass(frozen=True, slots=True)
class HypercolorState:
    status: SystemStatus
    output: OutputResource
    scene: SceneDocument
    active_layout: SpatialLayout | None
    active_effect: ActiveEffect | None

    @property
    def active_effect_id(self) -> str | None:
        return self.active_effect.id if self.active_effect is not None else None

    @property
    def active_effect_name(self) -> str | None:
        if self.active_effect is not None:
            return self.active_effect.name
        name = self.status.active_effect
        return name if isinstance(name, str) else None

    @property
    def active_preset_id(self) -> str | None:
        return self.active_effect.preset_id if self.active_effect is not None else None

    @property
    def active_effect_cover_image_url(self) -> str | None:
        return self.active_effect.cover_image_url if self.active_effect is not None else None

    @property
    def paused(self) -> bool:
        return self.output.power is OutputPowerMode.PAUSED

    @property
    def brightness(self) -> float:
        return self.output.brightness

    @property
    def zones(self) -> tuple[ZoneResource, ...]:
        return tuple(self.scene.zones)

    @property
    def renderable_zones(self) -> tuple[ZoneResource, ...]:
        return tuple(zone for zone in self.zones if zone_role(zone) != ZONE_ROLE_DISPLAY)

    def zone(self, zone_id: str) -> ZoneResource | None:
        return next((zone for zone in self.renderable_zones if zone.id == zone_id), None)


@dataclass(frozen=True, slots=True)
class HypercolorCatalog:
    effects: CatalogIndex[EffectSummary]
    scenes: CatalogIndex[SceneSummary]
    layouts: CatalogIndex[LayoutSummary]
    preset_effect_id: str | None
    presets: CatalogIndex[EffectPresetSummary]

    @classmethod
    def build(
        cls,
        *,
        effects: Iterable[EffectSummary],
        scenes: Iterable[SceneSummary],
        layouts: Iterable[LayoutSummary],
        preset_effect_id: str | None,
        presets: Iterable[EffectPresetSummary],
    ) -> Self:
        return cls(
            effects=CatalogIndex.build(effects),
            scenes=CatalogIndex.build(scenes),
            layouts=CatalogIndex.build(layouts),
            preset_effect_id=preset_effect_id,
            presets=CatalogIndex.build(
                presets,
                collision_label=_preset_collision_label,
            ),
        )


@dataclass(frozen=True, slots=True)
class HypercolorAudio:
    devices: AudioDevicesResponse | None = None
    spectrum: SpectrumData | None = None
    beat_until: float | None = None


@dataclass(frozen=True, slots=True)
class HypercolorSnapshot:
    state: HypercolorState
    catalog: HypercolorCatalog
    devices: tuple[DeviceSummary, ...]
    metrics: JsonObject = field(default_factory=dict)
    audio: HypercolorAudio = field(default_factory=HypercolorAudio)

    @property
    def active_effect_summary(self) -> EffectSummary | None:
        active_id = self.state.active_effect_id
        return self.catalog.effects.by_id.get(active_id) if active_id is not None else None

    @property
    def active_effect_audio_reactive(self) -> bool:
        effect = self.active_effect_summary
        return effect.audio_reactive is True if effect is not None else False

    @property
    def active_effect_presets(self) -> CatalogIndex[EffectPresetSummary]:
        if self.catalog.preset_effect_id != self.state.active_effect_id:
            return CatalogIndex.build(())
        return self.catalog.presets

    def device(self, device_id: str) -> DeviceSummary | None:
        return next((device for device in self.devices if device.id == device_id), None)

    def with_metrics(self, metrics: JsonObject) -> Self:
        return replace(self, metrics=metrics)

    def with_spectrum(self, spectrum: SpectrumData, beat_until: float | None) -> Self:
        return replace(self, audio=replace(self.audio, spectrum=spectrum, beat_until=beat_until))

    def with_push_telemetry(self, current: Self) -> Self:
        return replace(
            self,
            metrics=current.metrics,
            audio=replace(
                self.audio,
                spectrum=current.audio.spectrum,
                beat_until=current.audio.beat_until,
            ),
        )


def zone_role(zone: ZoneResource) -> str:
    return zone.role if isinstance(zone.role, str) else "custom"


def effect_layer(zone: ZoneResource) -> EffectLayer | None:
    """Return the topmost enabled effect layer of a zone, if it has one.

    The renderer skips disabled layers, so a disabled layer is never the
    effect a zone is showing, whatever sits above or below it.
    """
    for layer in reversed(zone.layers):
        source = layer.source.additional_properties
        if layer.enabled is False or source.get("type") != "effect":
            continue
        effect_id = source.get("effect_id")
        if not isinstance(effect_id, str):
            continue
        controls = source.get("controls")
        preset_id = source.get("preset_id")
        return EffectLayer(
            zone_id=zone.id,
            layer_id=str(layer.id),
            effect_id=effect_id,
            control_values=MappingProxyType(dict(controls) if isinstance(controls, dict) else {}),
            preset_id=preset_id if isinstance(preset_id, str) else None,
        )
    return None


def primary_effect_layer(scene: SceneDocument) -> EffectLayer | None:
    """Return the effect layer the master light represents.

    The primary zone wins; without one, the first renderable zone that
    carries an effect stands in. Disabled zones do not render, so they
    never own the master light's effect.
    """
    renderable = [
        zone for zone in scene.zones if zone.enabled and zone_role(zone) != ZONE_ROLE_DISPLAY
    ]
    ordered = sorted(renderable, key=lambda zone: zone_role(zone) != ZONE_ROLE_PRIMARY)
    return next((layer for zone in ordered if (layer := effect_layer(zone)) is not None), None)


def device_enabled(device: DeviceSummary) -> bool:
    return device.status != DEVICE_STATUS_DISABLED


def control_scalar(value: Any) -> Any:
    """Unwrap a canonical control envelope down to its plain value."""
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    if isinstance(value, dict) and "kind" in value:
        return value.get("value")
    return value


def _preset_collision_label(preset: EffectPresetSummary) -> str:
    origin = "Built-in" if preset.origin is EffectPresetOrigin.BUNDLED else "Saved"
    return f"{preset.name} ({origin})"
