from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Protocol, Self

from hypercolor.models import (
    ActiveEffect,
    ActiveScene,
    AudioDevices,
    Device,
    EffectPreset,
    EffectPresetOrigin,
    EffectSummary,
    JsonObject,
    Layout,
    LayoutSummary,
    ProfileSummary,
    Scene,
    SystemState,
    Zone,
)
from hypercolor.websocket import SpectrumData


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
class HypercolorState:
    status: SystemState
    active_effect: ActiveEffect | None
    active_scene: ActiveScene | None
    active_layout: Layout | None
    active_effect_cover_image_url: str | None

    @property
    def active_effect_id(self) -> str | None:
        return self.active_effect.id if self.active_effect is not None else None

    @property
    def active_effect_name(self) -> str | None:
        if self.active_effect is not None:
            return self.active_effect.name
        return self.status.active_effect

    @property
    def active_preset_id(self) -> str | None:
        if self.active_effect is None:
            return None
        return self.active_effect.active_preset_id

    @property
    def active_preset_modified(self) -> bool:
        return (
            self.active_effect.active_preset_modified if self.active_effect is not None else False
        )

    @property
    def paused(self) -> bool:
        return self.status.paused

    @property
    def zones(self) -> tuple[Zone, ...]:
        if self.active_scene is None:
            return ()
        return tuple(self.active_scene.groups)

    @property
    def renderable_zones(self) -> tuple[Zone, ...]:
        return tuple(zone for zone in self.zones if not zone.is_display)

    def zone(self, zone_id: str) -> Zone | None:
        return next((zone for zone in self.renderable_zones if zone.id == zone_id), None)


@dataclass(frozen=True, slots=True)
class HypercolorCatalog:
    effects: CatalogIndex[EffectSummary]
    scenes: CatalogIndex[Scene]
    profiles: CatalogIndex[ProfileSummary]
    layouts: CatalogIndex[LayoutSummary]
    preset_effect_id: str | None
    presets: CatalogIndex[EffectPreset]

    @classmethod
    def build(
        cls,
        *,
        effects: Iterable[EffectSummary],
        scenes: Iterable[Scene],
        profiles: Iterable[ProfileSummary],
        layouts: Iterable[LayoutSummary],
        preset_effect_id: str | None,
        presets: Iterable[EffectPreset],
    ) -> Self:
        return cls(
            effects=CatalogIndex.build(effects),
            scenes=CatalogIndex.build(scenes),
            profiles=CatalogIndex.build(profiles),
            layouts=CatalogIndex.build(layouts),
            preset_effect_id=preset_effect_id,
            presets=CatalogIndex.build(
                presets,
                collision_label=_preset_collision_label,
            ),
        )


@dataclass(frozen=True, slots=True)
class HypercolorAudio:
    devices: AudioDevices | None = None
    spectrum: SpectrumData | None = None
    beat_until: float | None = None


@dataclass(frozen=True, slots=True)
class HypercolorSnapshot:
    state: HypercolorState
    catalog: HypercolorCatalog
    devices: tuple[Device, ...]
    metrics: JsonObject = field(default_factory=dict)
    audio: HypercolorAudio = field(default_factory=HypercolorAudio)

    @property
    def active_effect_summary(self) -> EffectSummary | None:
        active_id = self.state.active_effect_id
        return self.catalog.effects.by_id.get(active_id) if active_id is not None else None

    @property
    def active_effect_audio_reactive(self) -> bool:
        effect = self.active_effect_summary
        return effect.audio_reactive if effect is not None else False

    @property
    def active_effect_presets(self) -> CatalogIndex[EffectPreset]:
        if self.catalog.preset_effect_id != self.state.active_effect_id:
            return CatalogIndex.build(())
        return self.catalog.presets

    def device(self, device_id: str) -> Device | None:
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


def control_scalar(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        inner = next(iter(value.values()))
        if isinstance(inner, (int, float, str, bool)):
            return inner
    return value


def _preset_collision_label(preset: EffectPreset) -> str:
    origin = "Built-in" if preset.origin is EffectPresetOrigin.BUNDLED else "Saved"
    return f"{preset.name} ({origin})"
