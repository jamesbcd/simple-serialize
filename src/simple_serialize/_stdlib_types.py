import collections
import enum
import ipaddress
import pathlib
import re
from typing import cast

from ._collections import _deserialize_pairs, _serialize_pairs
from ._scalar_types import bytes_deserializer, bytes_serializer


def enum_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
    '''Represent an enum member by its underlying value.

    Args:
        obj: Enum member to serialize.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A dictionary with the member's value under ``"value"``.
    '''
    obj = cast(enum.Enum, obj)
    return {
        "value": obj.value
    }


def enum_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> enum.Enum:
    '''Reconstruct an enum member from its underlying value.

    Args:
        cls: Registered enum class.
        data: Dictionary containing the member value.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        The matching enum member.
    '''
    data = cast(dict, data)
    return cls(data["value"])


def path_serializer(obj: object, options: dict[str, object], ctx: object | None) -> str:
    '''Encode a path using POSIX separators.

    Args:
        obj: Path to serialize.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        The path's POSIX-form string.
    '''
    obj = cast(pathlib.Path, obj)
    return obj.as_posix()


def path_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> pathlib.Path:
    '''Reconstruct a platform-native path from a serialized path string.

    The value is first interpreted as a Windows path and normalized to POSIX
    separators, then parsed by the current platform's ``Path`` implementation.
    This handles serialized Windows-style separators consistently across hosts.

    Args:
        cls: Unused class argument required by the deserializer interface.
        data: Serialized path string.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        A :class:`pathlib.Path` on the current platform.
    '''
    return pathlib.Path(pathlib.PureWindowsPath(str(data)).as_posix())


def regex_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
    '''Encode a compiled regular expression's pattern and flags.

    Byte patterns use the same base64 representation as bytes values; string
    patterns are stored directly.

    Args:
        obj: Compiled regular expression.
        ctx: Opaque object passed to bytes serialization when needed.

    Returns:
        A dictionary containing the pattern and integer flags.
    '''
    obj = cast(re.Pattern, obj)
    pattern = obj.pattern
    if isinstance(pattern, bytes):
        pattern = bytes_serializer(pattern, options, ctx)
    return {
        "pattern": pattern,
        "flags": obj.flags
    }


def regex_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> re.Pattern:
    '''Recompile a regular expression from its stored pattern and flags.

    Args:
        cls: Unused class argument required by the deserializer interface.
        data: Dictionary containing a string or encoded byte pattern and flags.
        ctx: Opaque object passed to bytes deserialization for byte patterns.

    Returns:
        A compiled regular expression.
    '''
    data = cast(dict, data)
    pattern = data["pattern"]
    if isinstance(pattern, dict):
        pattern = bytes_deserializer(bytes, pattern, options, ctx)
    flags = data["flags"]
    return re.compile(pattern, flags)


def ipaddress_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> str:
    '''Encode an IP address, network, or interface in canonical text form.'''
    return str(obj)


def ipaddress_deserializer(
    cls: type,
    data: object,
    options: dict[str, object],
    ctx: object | None,
) -> object:
    '''Reconstruct an IP address, network, or interface from canonical text.'''
    if not isinstance(data, str):
        raise TypeError("IP address data must be a string")
    return cls(data)


def counter_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> list[list[object]]:
    '''Encode Counter items as pairs so non-string keys are preserved.'''
    return _serialize_pairs(cast(collections.Counter, obj).items())


def counter_deserializer(
    cls: type,
    data: object,
    options: dict[str, object],
    ctx: object | None,
) -> collections.Counter:
    '''Reconstruct a Counter while preserving keys and counts.'''
    result = cls()
    for key, count in _deserialize_pairs(data, "Counter"):
        result[key] = count
    return result


def ordered_dict_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> list[list[object]]:
    '''Encode OrderedDict items as pairs to preserve order and key types.'''
    return _serialize_pairs(cast(collections.OrderedDict, obj).items())


def ordered_dict_deserializer(
    cls: type,
    data: object,
    options: dict[str, object],
    ctx: object | None,
) -> collections.OrderedDict:
    '''Reconstruct an OrderedDict from ordered key-value pairs.'''
    return cls(_deserialize_pairs(data, "OrderedDict"))


def deque_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> dict[str, object]:
    '''Encode a deque's elements and optional maximum length.'''
    value = cast(collections.deque, obj)
    return {"items": list(value), "maxlen": value.maxlen}


def deque_deserializer(
    cls: type,
    data: object,
    options: dict[str, object],
    ctx: object | None,
) -> collections.deque:
    '''Reconstruct a deque with its original maximum length.'''
    if not isinstance(data, dict):
        raise TypeError("Deque data must contain items and maxlen")
    items = data.get("items")
    maxlen = data.get("maxlen")
    if (
        not isinstance(items, list)
        or (maxlen is not None and (type(maxlen) is not int or maxlen < 0))
    ):
        raise TypeError("Deque data must contain items and a non-negative maxlen")
    return cls(items, maxlen=maxlen)
