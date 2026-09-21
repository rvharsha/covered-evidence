"""Dataclass <-> dict conversion and JSON Schema generation, standard library only.

Supports: str, int, float, bool, StrEnum subclasses, X | None, list[X], and
nested dataclasses. Unknown keys and wrong types are errors that name the
path to the offending field, e.g. ``requirements[0].status``.
"""

from __future__ import annotations

import dataclasses
import json
import math
import types
import typing
from enum import Enum
from typing import Any, TypeVar, cast

T = TypeVar("T")

_SCALARS: dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _is_dataclass_type(t: Any) -> bool:
    return isinstance(t, type) and dataclasses.is_dataclass(t)


def _is_enum_type(t: Any) -> bool:
    return isinstance(t, type) and issubclass(t, Enum)


def _split_optional(t: Any) -> tuple[Any, bool]:
    origin = typing.get_origin(t)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(t) if a is not type(None)]
        if len(args) == 1 and len(typing.get_args(t)) == 2:
            return args[0], True
        raise TypeError(f"unsupported union {t!r}")
    return t, False


def _hints(cls: type) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r} in JSON object")
        out[key] = value
    return out


def _no_constants(token: str) -> Any:
    raise ValueError(f"{token} is not valid JSON")


def loads_strict(text: str) -> Any:
    """Parse JSON the way evidence must be parsed. ``json.loads`` keeps the LAST of duplicate
    keys while a human reader, or a first-key-wins parser, sees the first, so a file could show
    one value and verify as another. Duplicates and the non-JSON tokens NaN and Infinity are
    errors here."""
    return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants)


def from_dict(cls: type[T], data: Any, path: str = "") -> T:
    """Build ``cls`` from ``data`` with strict validation."""
    return cast(T, _decode(cls, data, path or cls.__name__))


def _decode(t: Any, value: Any, path: str) -> Any:
    inner, optional = _split_optional(t)
    if value is None:
        if optional:
            return None
        raise ValueError(f"{path}: expected {getattr(inner, '__name__', inner)}, got null")
    t = inner
    if _is_dataclass_type(t):
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected object, got {type(value).__name__}")
        hints = _hints(t)
        fields = {f.name: f for f in dataclasses.fields(t)}
        unknown = sorted(set(value) - set(fields))
        if unknown:
            raise ValueError(f"{path}: unknown field(s) {unknown}")
        kwargs: dict[str, Any] = {}
        for name in fields:
            sub = f"{path}.{name}"
            if name not in value:
                # A default is a convenience for Python construction only. On load every field
                # must be present, or two different documents (one with `amendments` stripped)
                # would share canonical bytes and both verify.
                raise ValueError(f"{sub}: missing required field")
            kwargs[name] = _decode(hints[name], value[name], sub)
        return t(**kwargs)
    if _is_enum_type(t):
        try:
            return t(value)
        except ValueError:
            allowed = [e.value for e in t]
            raise ValueError(f"{path}: {value!r} is not one of {allowed}") from None
    origin = typing.get_origin(t)
    if origin is list:
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected list, got {type(value).__name__}")
        (item_t,) = typing.get_args(t)
        return [_decode(item_t, v, f"{path}[{i}]") for i, v in enumerate(value)]
    if t is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected boolean, got {type(value).__name__}")
        return value
    if t is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path}: expected integer, got {type(value).__name__}")
        return value
    if t is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{path}: expected number, got {type(value).__name__}")
        if isinstance(value, int):
            if abs(value) > 2**53:
                raise ValueError(f"{path}: expected a finite number a float can hold exactly")
            # `1` and `1.0` decode to the same value and would share canonical bytes; a float
            # field takes a float token, so one value has one spelling
            raise ValueError(f"{path}: expected a number with a fraction (1.0, not 1)")
        if not math.isfinite(value):
            raise ValueError(f"{path}: expected a finite number, got {value!r}")
        return value
    if t is str:
        if not isinstance(value, str):
            raise ValueError(f"{path}: expected string, got {type(value).__name__}")
        return value
    raise TypeError(f"{path}: unsupported type {t!r}")


def with_defaults(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Complete a hand-written document IN PLACE with the dataclass's Python-side defaults, and
    return it. Loading never assumes a default (see ``_decode``), so an author who wants one
    writes it out, explicitly, with this. It is for authoring tools and test fixtures; a reader
    of evidence never calls it."""
    hints = _hints(cls)
    for f in dataclasses.fields(cls):
        if f.name not in data:
            if f.default is not dataclasses.MISSING:
                data[f.name] = to_dict(f.default)
            elif f.default_factory is not dataclasses.MISSING:
                data[f.name] = to_dict(f.default_factory())
            continue
        inner, _ = _split_optional(hints[f.name])
        value = data[f.name]
        if _is_dataclass_type(inner) and isinstance(value, dict):
            with_defaults(inner, value)
        elif typing.get_origin(inner) is list and isinstance(value, list):
            (item_t,) = typing.get_args(inner)
            if _is_dataclass_type(item_t):
                for row in value:
                    if isinstance(row, dict):
                        with_defaults(item_t, row)
    return data


def to_dict(obj: Any) -> Any:
    """Convert a dataclass instance to plain JSON-compatible data, field order preserved."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if obj is None or isinstance(obj, str | int | float | bool):
        return obj
    raise TypeError(f"cannot serialise {type(obj).__name__}")


def json_schema(cls: type, *, title: str | None = None) -> dict[str, Any]:
    """JSON Schema (draft 2020-12) for a dataclass, with additionalProperties false."""
    schema = _schema_for(cls)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = title or cls.__name__
    return schema


def _schema_for(t: Any) -> dict[str, Any]:
    inner, optional = _split_optional(t)
    s = _schema_inner(inner)
    if optional:
        return {"anyOf": [s, {"type": "null"}]}
    return s


def _schema_inner(t: Any) -> dict[str, Any]:
    if _is_dataclass_type(t):
        hints = _hints(t)
        props: dict[str, Any] = {}
        required: list[str] = []
        for f in dataclasses.fields(t):
            props[f.name] = _schema_for(hints[f.name])
            required.append(f.name)  # every field is required in a document; see _decode
        out: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
        if required:
            out["required"] = required
        return out
    if _is_enum_type(t):
        return {"type": "string", "enum": [e.value for e in t]}
    if typing.get_origin(t) is list:
        (item_t,) = typing.get_args(t)
        return {"type": "array", "items": _schema_for(item_t)}
    if t in _SCALARS:
        return {"type": _SCALARS[t]}
    raise TypeError(f"unsupported type {t!r}")
