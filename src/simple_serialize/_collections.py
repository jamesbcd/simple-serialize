from collections.abc import Iterable
from typing import cast

from ._objects import (
    _attribute_options,
    _deserialize_attributes,
    _serialize_attributes,
)


def iterable_serializer(obj: object, options: dict[str, object], ctx: object | None) -> list:
    '''Convert an iterable value to a list for JSON encoding.

    Args:
        obj: Iterable registered for this serializer.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        The iterable's elements in iteration order. Set iteration order is
        not guaranteed.
    '''
    obj = cast(Iterable, obj)
    return list(obj)


def iterable_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> Iterable:
    '''Reconstruct a registered iterable class from decoded list data.

    Args:
        cls: Iterable class to construct.
        data: Decoded sequence of elements.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        ``cls(data)``.
    '''
    data = cast(list, data)
    return cls(data)


def mapping_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
    '''Copy a mapping, applying attribute options to its string keys.

    Args:
        obj: Mapping value to copy.
        options: Registration options: ``exclude`` omits string keys,
            ``select`` includes only listed string keys and takes precedence
            over ``exclude``, and ``rename`` maps keys to JSON names.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A plain ``dict`` containing the selected, renamed key-value pairs.

    Raises:
        TypeError: If attribute options are used with non-string mapping keys.
    '''
    obj = cast(dict, obj)
    mapping = dict(obj)
    select, exclude, rename = _attribute_options(options)
    if select is None and not exclude and not rename:
        return mapping
    if not all(isinstance(name, str) for name in mapping):
        raise TypeError("Mapping keys must be strings when attribute options are used")
    return _serialize_attributes(cast(dict[str, object], mapping), options)


def mapping_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> object:
    '''Construct a mapping class from decoded, renamed dictionary data.

    Args:
        cls: Mapping class to construct.
        data: Decoded dictionary.
        options: Registration options; ``rename`` maps JSON keys back to their
            original names. ``select`` and ``exclude`` don't affect deserialization.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        ``cls(data)``.

    Raises:
        TypeError: If attribute options are used with non-string mapping keys.
    '''
    mapping = dict(cast(dict, data))
    select, exclude, rename = _attribute_options(options)
    if (select is not None or exclude or rename) and not all(
        isinstance(name, str) for name in mapping
    ):
        raise TypeError("Mapping keys must be strings when attribute options are used")
    attributes = _deserialize_attributes(
        cast(dict[str, object], mapping), options
    )
    return cls(attributes)


def _serialize_pairs(obj: object) -> list[list[object]]:
    return [[key, value] for key, value in cast(Iterable, obj)]


def _deserialize_pairs(data: object, type_name: str) -> list[list[object]]:
    if not isinstance(data, list) or not all(
        isinstance(pair, list) and len(pair) == 2 for pair in data
    ):
        raise TypeError(f"{type_name} data must be a list of key-value pairs")
    return data
