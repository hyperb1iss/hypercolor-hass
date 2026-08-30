"""Build wire payloads that satisfy the generated Hypercolor models.

The daemon's responses decode strictly, so every required field has
to be present. Filling them by introspecting the generated attrs
classes keeps the fake daemon honest without hand-maintaining giant
fixtures that drift the moment upstream adds a status field.
"""

from __future__ import annotations

import enum
import types
import typing
import uuid
from datetime import datetime
from typing import Any

import attrs
from hypercolor._generated import models as generated

from hypercolor.models import Unset

type JsonObject = dict[str, Any]

_NAMESPACE: dict[str, Any] = {
    **vars(generated),
    "Unset": Unset,
    "UUID": uuid.UUID,
    "Any": typing.Any,
    "datetime": datetime,
}


def minimal(model: type[Any], **overrides: Any) -> JsonObject:
    """Return the smallest JSON object ``model.from_dict`` accepts."""
    attrs.resolve_types(model, globalns=_NAMESPACE, localns=_NAMESPACE)
    payload: JsonObject = {}
    for field in attrs.fields(model):
        if field.name == "additional_properties":
            continue
        key = field.name.rstrip("_")
        if key in overrides:
            payload[key] = overrides[key]
            continue
        if field.default is not attrs.NOTHING:
            continue
        payload[key] = _placeholder(field.type)
    unknown = set(overrides) - set(payload)
    if unknown:
        msg = f"{model.__name__} has no fields named {sorted(unknown)}"
        raise KeyError(msg)
    return payload


_SCALAR_PLACEHOLDERS: dict[Any, Any] = {
    bool: False,
    int: 0,
    float: 0.0,
    str: "",
    uuid.UUID: str(uuid.uuid5(uuid.NAMESPACE_URL, "hypercolor-hass")),
    typing.Any: None,
}
_CONTAINER_PLACEHOLDERS: dict[Any, Any] = {list: [], dict: {}}


def _placeholder(annotation: Any) -> Any:
    origin = typing.get_origin(annotation)
    if origin in (types.UnionType, typing.Union):
        candidates = [
            member
            for member in typing.get_args(annotation)
            if member is not Unset and member is not type(None)
        ]
        return _placeholder(candidates[0])
    if origin in _CONTAINER_PLACEHOLDERS:
        return _CONTAINER_PLACEHOLDERS[origin].copy()
    if annotation in _SCALAR_PLACEHOLDERS:
        return _SCALAR_PLACEHOLDERS[annotation]
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return next(iter(annotation)).value
    if isinstance(annotation, type) and attrs.has(annotation):
        return minimal(annotation)
    msg = f"no placeholder for {annotation!r}"
    raise TypeError(msg)
