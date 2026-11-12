'''Serialize registered Python objects to and from JSON.

Objects are represented by JSON objects containing the reserved ``__type__``
and ``__data__`` keys. Classes can be registered with :func:`register` or the
:func:`serializable` decorator. Built-in registrations cover common Python
values such as paths, dates, bytes, regular expressions, and containers.
'''
import enum
import base64
import collections
from dataclasses import fields, is_dataclass
import decimal
from fractions import Fraction
import inspect
import ipaddress
import json
import os
import pathlib
import datetime
import re
import uuid
from typing import Any, Callable, Iterable, cast, TypeVar, overload
from zoneinfo import ZoneInfo


__all__ = [
    "TYPE_KEY",
    "DATA_KEY",
    "Serializer",
    "Deserializer",
    "Pathlike",
    "register",
    "serializable",
    "save",
    "load",
    "serialize",
    "deserialize",
    "standard_serializer",
    "standard_deserializer",
    "iterable_serializer",
    "iterable_deserializer",
    "mapping_serializer",
    "mapping_deserializer",
    "dataclass_serializer",
    "dataclass_deserializer",
    "enum_serializer",
    "enum_deserializer",
    "complex_serializer",
    "complex_deserializer",
    "decimal_serializer",
    "decimal_deserializer",
    "fraction_serializer",
    "fraction_deserializer",
    "uuid_serializer",
    "uuid_deserializer",
    "timezone_serializer",
    "timezone_deserializer",
    "zoneinfo_serializer",
    "zoneinfo_deserializer",
    "ipaddress_serializer",
    "ipaddress_deserializer",
    "counter_serializer",
    "counter_deserializer",
    "ordered_dict_serializer",
    "ordered_dict_deserializer",
    "deque_serializer",
    "deque_deserializer",
    "bytes_serializer",
    "bytes_deserializer",
    "bytearray_serializer",
    "bytearray_deserializer",
    "memoryview_serializer",
    "memoryview_deserializer",
    "range_serializer",
    "range_deserializer",
    "slice_serializer",
    "slice_deserializer",
    "path_serializer",
    "path_deserializer",
    "isoformat_serializer",
    "isoformat_deserializer",
    "timedelta_serializer",
    "timedelta_deserializer",
    "regex_serializer",
    "regex_deserializer",
]


# Reserved keys identifying a registered type and its serialized data.
TYPE_KEY = "__type__"
DATA_KEY = "__data__"


# Type aliases for serializer and deserializer callables.
# Options are registration-specific; context is supplied by the caller.
Serializer = Callable[[object, dict[str, object], object | None], object]
Deserializer = Callable[[type, object, dict[str, object], object | None], object]


class _Registry:
    '''Map Python classes and JSON type names to serialization callbacks.

    Attributes:
        _serializers: Class-to-(JSON name, serializer, options) lookup table.
        _deserializers: JSON-name-to-(class, deserializer, options) lookup table.
    '''

    def __init__(self):
        '''Initialize empty serializer and deserializer lookup tables.'''
        # Keep each class and JSON name unique in its respective lookup table.
        self._serializers: dict[type, tuple[str, Serializer, dict[str, object]]] = {}
        self._deserializers: dict[
            str, tuple[type, Deserializer, dict[str, object]]
        ] = {}

    def serializer_for(
        self, obj: object
    ) -> tuple[str, Serializer, dict[str, object]] | None:
        '''Find a registered serializer applicable to ``obj``.

        Lookup prefers the exact runtime type, then registered base classes in
        method-resolution order, then any registered type matching through
        ``isinstance`` (including virtual ABC registrations).

        Args:
            obj: Object whose serializer is requested.

        Returns:
            The registered JSON type name, serializer, and options, or
            ``None`` if no registration applies.
        '''
        obj_type = type(obj)
        registered = self._serializers.get(obj_type)
        # First, try to find a serializer registered for the exact type of the object.
        if registered is not None:
            return registered
        # If no exact match is found, check the base classes in the method resolution order (MRO).
        for base_type in obj_type.__mro__[1:]:
            registered = self._serializers.get(base_type)
            if registered is not None:
                return registered
        # Finally, as a last resort, check all registered types to see if the object is an instance
        # of any of them.
        for registered_cls, registered in self._serializers.items():
            if isinstance(obj, registered_cls):
                return registered
        return None

    def register(self, cls: type,
                 serializer: Serializer,
                 deserializer: Deserializer,
                 json_name: str | None = None,
                 **options: object) -> None:
        '''Add a class and its callbacks to the registry.

        Args:
            cls: Python class handled by the callbacks.
            serializer: Converts an instance, options, and context into
                serializable data.
            deserializer: Reconstructs an instance from the class, data,
                options, and context.
            json_name: Type name stored in JSON; defaults to ``cls.__name__``.
            **options: Registration-specific options passed to both callbacks.
                Built-in attribute handlers recognize ``exclude`` (names to
                omit), ``select`` (names to include; takes precedence over
                ``exclude``), and ``rename`` (Python names to JSON names, and
                back during deserialization).

        Raises:
            TypeError: If either callback is not callable.
            ValueError: If the class or JSON type name is already registered.
        '''
        if json_name is None:
            json_name = cls.__name__
        if not callable(serializer):
            raise TypeError(f"Serializer for object of type {cls.__name__} is not callable")
        if not callable(deserializer):
            raise TypeError(f"Deserializer for object of type {cls.__name__} is not callable")
        if cls in self._serializers:
            raise ValueError(f"Class {cls.__name__} is already registered")
        if json_name in self._deserializers:
            raise ValueError(f"JSON name {json_name} is already registered")
        class_options = dict(options)
        self._serializers[cls] = (json_name, serializer, class_options)
        self._deserializers[json_name] = (cls, deserializer, class_options)

_registry = _Registry()

# 
# Public API for registering and using serializers
#
def register(cls: type,
             serializer: Serializer,
             deserializer: Deserializer,
             json_name: str | None = None,
             **options: object) -> None:
    '''Register a class with custom serialization callbacks.

    Use this function for classes that cannot be modified to add
    :func:`serializable` or custom ``_serialize`` and ``_deserialize`` methods.

    Args:
        cls: The Python class to register.
        serializer: Callable receiving an instance, options dictionary, and
            optional context, and returning data that can be encoded as JSON.
        deserializer: Callable receiving the class, decoded data, options
            dictionary, and context, and returning an instance.
        json_name: Optional type name stored in the JSON representation.
            Defaults to the class name.
        **options: Registration-specific options passed to both callbacks.
            Built-in attribute handlers recognize ``exclude`` (names to omit),
            ``select`` (names to include; takes precedence over ``exclude``),
            and ``rename`` (Python names to JSON names, and back during
            deserialization). Custom callbacks control how they use options.

    Raises:
        TypeError: If either callback is not callable.
        ValueError: If the class or JSON type name is already registered.
    '''
    _registry.register(cls, serializer, deserializer, json_name, **options)


# Accepted path values for :func:`save`.
Pathlike = str | os.PathLike | pathlib.Path


def save(obj: object, path: Pathlike, ctx: object | None = None) -> None:
    '''Serialize ``obj`` as JSON and write it to ``path``.

    Missing parent directories are created. The object's type must be
    registered, either with :func:`serializable` or :func:`register`.

    Args:
        obj: Object to serialize.
        path: Destination path.
        ctx: Optional opaque object passed to serializers.
    '''
    path = pathlib.Path(path)
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    json_str = serialize(obj, ctx)
    with path.open('w', encoding='utf-8') as file:
        file.write(json_str)

def serialize(obj: object, ctx: object | None = None) -> str:
    '''Encode an object as an indented JSON string.

    Registered objects are encoded with the reserved :data:`TYPE_KEY` and
    :data:`DATA_KEY` fields. Dictionaries containing those fields may therefore
    be interpreted as serialization metadata when loaded. Nested dictionaries
    and lists/tuples are prepared recursively. Cycles in these containers or
    registered objects raise ``ValueError``; shared but non-cyclic references
    are serialized independently.

    Args:
        obj: Value to encode. Non-JSON-native objects must be registered.
        ctx: Optional opaque object passed to serializers. ``None`` is passed
            when omitted.

    Returns:
        A Unicode JSON string formatted with four-space indentation.
    '''
    return json.dumps(
        _prepare_for_json(obj, ctx),
        indent=4,
        ensure_ascii=False,
        default=lambda obj: _serialize_handler(obj, ctx),
    )

def load(path: Pathlike, ctx: object | None = None) -> object:
    '''Read JSON from ``path`` and deserialize its value.

    Any registered types in the file must already be registered in this
    process, either with :func:`serializable` or :func:`register`.

    Args:
        path: Source path.
        ctx: Optional opaque object passed to deserializers.

    Returns:
        The decoded Python value.
    '''
    path = pathlib.Path(path)
    with path.open('r', encoding='utf-8') as file:
        json_str = file.read()
    return deserialize(json_str, ctx)

def deserialize(json_str: str, ctx: object | None = None) -> object:
    '''Decode a JSON string into Python values and registered objects.

    Objects containing :data:`TYPE_KEY` are treated as registered-type
    metadata and must also contain :data:`DATA_KEY`. Each encountered type
    name must have a deserializer registered in this process.

    Args:
        json_str: JSON text to decode.
        ctx: Optional opaque object passed to deserializers. ``None`` is passed
            when omitted.

    Returns:
        The decoded Python value.
    '''
    return json.loads(json_str, object_hook=lambda data: _deserialize_handler(data, ctx)) 

#
# Internal helper functions for working with JSON serialization and deserialization
#
def _prepare_for_json(
    obj: object,
    ctx: object | None,
    active_ids: set[int] | None = None,
) -> object:
    '''Recursively convert registered values and containers for ``json.dumps``.

    Preprocessing is needed because JSON's encoder handles native containers
    and their subclasses directly, bypassing its default handler. It also
    ensures registered values such as ``IntEnum`` instances are encoded by
    their registration. ``active_ids`` tracks only the current recursion path,
    so actual cycles are rejected while repeated non-cyclic references remain
    valid. Registered objects used as dictionary keys are rejected because
    dictionary keys are not recursively encoded.

    Args:
        obj: Value to prepare.
        ctx: Opaque object passed to any registered serializer.
        active_ids: Object identities on the current recursive path; initialized
            on the outermost call.

    Returns:
        JSON-compatible data, with registered values represented by metadata
        dictionaries.

    Raises:
        ValueError: If a cycle is encountered.
        TypeError: If a registered object is used as a dictionary key.
    '''
    if active_ids is None:
        active_ids = set()

    registered = _registry.serializer_for(obj)
    if registered is not None:
        object_id = id(obj)
        if object_id in active_ids:
            raise ValueError(f"Circular reference to {obj} during serialization")
        active_ids.add(object_id)
        try:
            serialized = _serialize_handler(obj, ctx)
            return _prepare_for_json(serialized, ctx, active_ids)
        finally:
            active_ids.remove(object_id)

    if isinstance(obj, dict):
        object_id = id(obj)
        if object_id in active_ids:
            raise ValueError(f"Circular reference to {obj} during serialization")
        active_ids.add(object_id)
        try:
            prepared: dict[object, object] = {}
            for key, value in obj.items():
                if _registry.serializer_for(key) is not None:
                    raise TypeError(
                        f"Registered serializable object {key} cannot be dictionary keys"
                    )
                prepared[key] = _prepare_for_json(value, ctx, active_ids)
            return prepared
        finally:
            active_ids.remove(object_id)

    if isinstance(obj, (list, tuple)):
        object_id = id(obj)
        if object_id in active_ids:
            raise ValueError(f"Circular reference to {obj} during serialization")
        active_ids.add(object_id)
        try:
            return [
                _prepare_for_json(value, ctx, active_ids)
                for value in obj
            ]
        finally:
            active_ids.remove(object_id)

    return obj

def _serialize_handler(obj: object, ctx: object | None):
    '''Encode a registered object as a type-name/data metadata dictionary.

    This function is also used as ``json.dumps``'s fallback for values not
    handled by preprocessing.

    Args:
        obj: Registered object to encode.
        options: Registration-specific options passed to its serializer.
        ctx: Opaque object passed to its serializer.

    Returns:
        A dictionary containing :data:`TYPE_KEY` and :data:`DATA_KEY`.

    Raises:
        TypeError: If the object's type has no registered serializer.
    '''
    registered = _registry.serializer_for(obj)
    if registered is None:
        raise TypeError(f"Object of type {type(obj).__name__} is not registered as serializable")
    json_name, serializer, options = registered
    return {
        TYPE_KEY: json_name,
        DATA_KEY: serializer(obj, options, ctx)
    }

def _deserialize_handler(input_dict: dict, ctx: object | None) -> object:
    '''Reconstruct registered objects found by ``json.loads``'s object hook.

    Ordinary dictionaries are returned unchanged. A dictionary containing
    :data:`TYPE_KEY` is treated as metadata, looked up by its JSON type name,
    and passed to the corresponding deserializer.

    Args:
        input_dict: A decoded JSON object.
        options: Registration-specific options passed to its deserializer.
        ctx: Opaque object passed to registered deserializers.

    Returns:
        The original ordinary dictionary or its reconstructed object.

    Raises:
        TypeError: If the type name is unknown or its data field is missing.
    '''
    if TYPE_KEY not in input_dict:
        # This is a regular dictionary, so return it as-is.
        return input_dict
    json_name = input_dict[TYPE_KEY]
    registered = _registry._deserializers.get(json_name)
    if registered is None:
        raise TypeError(f"No deserializer registered for JSON type {json_name}")
    cls, deserializer, options = registered
    if DATA_KEY not in input_dict:
        raise TypeError(f"No {DATA_KEY} key found for JSON type {json_name}")
    data = input_dict[DATA_KEY]
    return deserializer(cls, data, options, ctx)

#
# Decorator for easiest way to register serializable classes
#

# We have to do some type overloading to support both usage patterns of the decorator:
# 1. Used directly as @serializable (without parentheses)
# 2. Used with parentheses and optional arguments, e.g., @serializable("CustomName")
# First, create a generic type variable that represents a class
T = TypeVar("T", bound=type)

# Case 1: Used directly as @serializable (without parentheses)
@overload
def serializable(cls_or_json_name: T) -> T:
    '''Type signature for decorating a class directly.'''
    ...

@overload
def serializable(
    cls_or_json_name: str | None = None, **options: object
) -> Callable[[T], T]:
    '''Type signature for creating a decorator with registration options.'''
    ...

def serializable(
    cls_or_json_name: type | str | None = None,
    *args: Any,
    **options: object,
) -> Any:
    '''Decorator to register a class as serializable.

    Use as ``@serializable``, ``@serializable("CustomName")``, or
    ``@serializable(option=value)``. Keyword options are passed to both
    callbacks before the context argument. The class remains unchanged after
    registration. Unless it provides custom callbacks, enums use enum-specific
    handling, dataclasses use field-based handling, and other classes use their
    instance attributes, including ``__dict__`` entries and ``__slots__``.

    A decorated class can customize serialization by implementing:

        def _serialize(
            self, options: dict[str, object], ctx: object | None
        ) -> object:
            # Return data that can be encoded as JSON.
    
        @classmethod
        def _deserialize(
            cls, data: object, options: dict[str, object], ctx: object | None
        ) -> object:
            # Reconstruct and return an instance from the decoded data.

    Args:
        cls_or_json_name: The class to decorate, or an optional custom JSON type
            name when used as a decorator factory.
        *args: Accepted for decorator-call compatibility; not interpreted.
        **options: Registration-specific options passed to both callbacks.
            Built-in attribute handlers recognize ``exclude`` (names to omit),
            ``select`` (names to include; takes precedence over ``exclude``),
            and ``rename`` (Python names to JSON names, and back during
            deserialization). Custom callbacks control how they use options.
            ``json_name`` may be used to set the JSON type name when decorating.

    Returns:
        The decorated class, or a decorator when given options.

    Raises:
        TypeError: If a class's custom serializer or deserializer is not callable,
            or if ``json_name`` is invalid.
        ValueError: If the class or JSON type name is already registered.
    '''
    json_name = cls_or_json_name if isinstance(cls_or_json_name, str) else None
    keyword_json_name = options.pop("json_name", None)
    if keyword_json_name is not None:
        if json_name is not None:
            raise TypeError("json_name cannot be specified both positionally and by keyword")
        if not isinstance(keyword_json_name, str):
            raise TypeError("json_name must be a string")
        json_name = keyword_json_name

    def wrapper(cls: type) -> type:
        '''Register ``cls`` and return it unchanged.'''
        serializer, deserializer = _get_serializers_for_decorated_class(cls)
        _registry.register(cls, serializer, deserializer, json_name, **options)
        return cls

    if isinstance(cls_or_json_name, type):
        return wrapper(cls_or_json_name)
    return wrapper

def _get_serializers_for_decorated_class(cls: type) -> tuple[Serializer, Deserializer]:
    '''Select custom or default callbacks for a decorated class.

    Callback selection prefers the class's ``_serialize`` or ``_deserialize``
    method. Otherwise enums, dataclasses, and ordinary classes use their
    respective built-in implementations.     A classmethod deserializer is unbound so registration can invoke it with
    the class as its first argument. Both custom methods receive options before
    context.

    Args:
        cls: Class being registered.

    Returns:
        The serializer and deserializer to register.

    Raises:
        TypeError: If a defined ``_serialize`` or ``_deserialize`` attribute is
            not callable.
    '''
    serializer = getattr(cls, "_serialize", None)
    if serializer is not None and not callable(serializer):
        raise TypeError(f"_serialize() method for object of type {cls.__name__} is not callable")
    if serializer is None:
        if issubclass(cls, enum.Enum):
            serializer = enum_serializer
        elif is_dataclass(cls):
            serializer = dataclass_serializer
        else:
            serializer = standard_serializer
    deserializer = getattr(cls, "_deserialize", None)
    if deserializer is not None and not callable(deserializer):
        raise TypeError(f"_deserialize() method for object of type {cls.__name__} is not callable")
    if deserializer is None:
        if issubclass(cls, enum.Enum):
            deserializer = enum_deserializer
        elif is_dataclass(cls):
            deserializer = dataclass_deserializer
        else:
            deserializer = standard_deserializer
    else:
        # The decorated class implemented _deserialize()
        if inspect.ismethod(deserializer) and inspect.isclass(deserializer.__self__):
            # If the deserializer is a class method, we extract the underlying
            # unbound function, as it will be called with the class as the first
            # argument anyway.
            deserializer = deserializer.__func__
    return serializer, deserializer

#
# Standard serializers and deserializers
#

def _get_slot_names(cls: type) -> set[str]:
    '''Return the slot attribute names declared across ``cls``'s MRO.'''
    names = set()
    for base in cls.__mro__:
        slots = base.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for name in slots:
            if name in ("__dict__", "__weakref__"):
                continue
            if name.startswith("__") and not name.endswith("__"):
                name = f"_{base.__name__.lstrip('_')}{name}"
            names.add(name)
    return names


def _attribute_options(
    options: dict[str, object],
) -> tuple[set[str] | None, set[str], dict[str, str]]:
    '''Validate attribute options and return select, exclude, and rename.

    ``select`` names the only attributes to include and takes precedence over
    ``exclude``; ``rename`` maps Python attribute names to JSON names.
    '''
    select = options.get("select")
    if select is not None and (
        not isinstance(select, list)
        or not all(isinstance(name, str) for name in select)
    ):
        raise TypeError("select option must be a list of attribute names")
    exclude = options.get("exclude", [])
    if (
        not isinstance(exclude, list)
        or not all(isinstance(name, str) for name in exclude)
    ):
        raise TypeError("exclude option must be a list of attribute names")
    rename = options.get("rename", {})
    if not isinstance(rename, dict) or not all(
        isinstance(name, str) and isinstance(alias, str)
        for name, alias in rename.items()
    ):
        raise TypeError("rename option must map attribute names to strings")
    return (
        set(select) if select is not None else None,
        set(exclude),
        cast(dict[str, str], rename),
    )


def _serialize_attributes(
    attributes: dict[str, object], options: dict[str, object]
) -> dict[str, object]:
    '''Filter and rename an attribute dictionary using registration options.

    ``exclude`` omits names, ``select`` includes only listed names and
    overrides ``exclude``, and ``rename`` maps Python names to JSON names.
    '''
    select, exclude, rename = _attribute_options(options)
    serialized = {}
    for name, value in attributes.items():
        if select is not None:
            if name not in select:
                continue
        elif name in exclude:
            continue
        serialized_name = rename.get(name, name)
        if serialized_name in serialized:
            raise ValueError(
                f"Multiple attributes serialize as {serialized_name!r}"
            )
        serialized[serialized_name] = value
    return serialized


def _deserialize_attributes(
    attributes: dict[str, object], options: dict[str, object]
) -> dict[str, object]:
    '''Map renamed JSON names back to Python names using ``rename`` options.'''
    _, _, rename = _attribute_options(options)
    original_names = {alias: name for name, alias in rename.items()}
    return {
        original_names.get(name, name): value
        for name, value in attributes.items()
    }


def standard_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
    '''Copy an ordinary object's instance attributes into a dictionary.

    Args:
        obj: Object whose ``__dict__`` and ``__slots__`` will be copied.
        options: Registration options: ``exclude`` omits names, ``select``
            includes only listed names and takes precedence over ``exclude``,
            and ``rename`` maps Python names to JSON names.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A shallow copy of the object's initialized instance attributes.

    Raises:
        TypeError: If reading instance attributes fails; the original exception
            is preserved as the cause.
    '''
    try:
        new_obj = dict(getattr(obj, "__dict__", {}))
        for name in _get_slot_names(type(obj)):
            try:
                new_obj[name] = getattr(obj, name)
            except AttributeError:
                continue
    except Exception as e:
        raise TypeError(
            f"Failed to serialize object of type {type(obj).__name__}"
        ) from e
    return _serialize_attributes(new_obj, options)

def standard_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> object:
    '''Construct an ordinary class and restore its instance attributes.

    The class must be constructible without arguments. The decoded data is
    applied to its ``__dict__`` and declared slots.

    Args:
        cls: Class to instantiate.
        data: Mapping of instance attribute names to values.
        options: Registration options; ``rename`` maps JSON names back to
            Python names. ``select`` and ``exclude`` don't affect deserialization.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        The reconstructed instance.

    Raises:
        TypeError: If construction or attribute restoration fails; the original
            exception is preserved as the cause.
    '''
    try:
        instance = cls()
        attributes = _deserialize_attributes(dict(cast(dict, data)), options)
        slot_names = _get_slot_names(cls)
        slot_attributes = {
            name: value for name, value in attributes.items() if name in slot_names
        }
        instance_dict = getattr(instance, "__dict__", None)
        if instance_dict is not None:
            instance_dict.update(
                (name, value)
                for name, value in attributes.items()
                if name not in slot_names
            )
        for name, value in slot_attributes.items():
            setattr(instance, name, value)
    except Exception as e:
        raise TypeError(
            f"Failed to deserialize object of type {cls.__name__}: {e}"
        ) from e
    return instance

def dataclass_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
    '''Serialize a dataclass instance as a field-name/value dictionary.

    Args:
        obj: Dataclass instance to serialize.
        options: Registration options: ``exclude`` omits field names,
            ``select`` includes only listed names and takes precedence over
            ``exclude``, and ``rename`` maps Python names to JSON names.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A dictionary containing the values of the dataclass fields.

    Raises:
        TypeError: If ``obj`` is not a dataclass instance.
    '''
    if not is_dataclass(obj):
        raise TypeError(f"Object of type {type(obj).__name__} is not a dataclass")
    attributes = {field.name: getattr(obj, field.name) for field in fields(obj)}
    return _serialize_attributes(attributes, options)


def dataclass_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> object:
    '''Reconstruct a dataclass by passing decoded fields to its constructor.

    Constructor-based reconstruction also supports frozen dataclasses without
    assigning to their attributes after creation.

    Args:
        cls: Dataclass type to construct.
        data: Mapping of field names to decoded values.
        options: Registration options; ``rename`` maps JSON names back to
            Python field names. ``select`` and ``exclude`` don't affect deserialization.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        The reconstructed dataclass instance.

    Raises:
        TypeError: If construction fails; the original exception is preserved
            as the cause.
    '''
    data = cast(dict, data)
    try:
        data = _deserialize_attributes(data, options)
        dataclass_fields = fields(cls)
        init_field_names = {
            dataclass_field.name for dataclass_field in dataclass_fields
            if dataclass_field.init
        }
        init_data = {
            name: value for name, value in data.items()
            if name in init_field_names
        }
        instance = cls(**init_data)
        for dataclass_field in dataclass_fields:
            if not dataclass_field.init and dataclass_field.name in data:
                object.__setattr__(
                    instance,
                    dataclass_field.name,
                    data[dataclass_field.name],
                )
    except Exception as e:
        raise TypeError(
            f"Failed to deserialize object of type {cls.__name__}: {e}"
        ) from e
    return instance

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


# Tuples, sets, and frozensets are encoded as JSON arrays and rebuilt from
# those arrays by calling their constructors.
register(tuple, iterable_serializer, iterable_deserializer)
register(set, iterable_serializer, iterable_deserializer)
register(frozenset, iterable_serializer, iterable_deserializer)


def range_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, int]:
    '''Encode a range using its start, stop, and step values.'''
    obj = cast(range, obj)
    return {"start": obj.start, "stop": obj.stop, "step": obj.step}


def range_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> range:
    '''Reconstruct a range from its start, stop, and step values.'''
    data = cast(dict, data)
    values = (data.get("start"), data.get("stop"), data.get("step"))
    if not all(type(value) is int for value in values):
        raise TypeError("Range data must contain integer start, stop, and step values")
    return range(*values)


register(range, range_serializer, range_deserializer)


def slice_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, object]:
    '''Encode a slice using its start, stop, and step values.'''
    obj = cast(slice, obj)
    return {"start": obj.start, "stop": obj.stop, "step": obj.step}


def slice_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> slice:
    '''Reconstruct a slice from its start, stop, and step values.'''
    data = cast(dict, data)
    if not all(key in data for key in ("start", "stop", "step")):
        raise TypeError("Slice data must contain start, stop, and step values")
    return slice(data["start"], data["stop"], data["step"])


register(slice, slice_serializer, slice_deserializer)


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

#
# Custom serializers and deserializers for common types
#

# Enum serializers and deserializers
#
# We don't register a general enum serializer/deserializer here, because Enums are almost
# always subclasses, and it's better to register the subclasses.

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


def complex_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, float]:
    '''Encode a complex number using its real and imaginary components.'''
    obj = cast(complex, obj)
    return {"real": obj.real, "imag": obj.imag}


def complex_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> complex:
    '''Reconstruct a complex number from its real and imaginary components.'''
    data = cast(dict, data)
    real = data.get("real")
    imag = data.get("imag")
    if (
        not isinstance(real, (int, float))
        or isinstance(real, bool)
        or not isinstance(imag, (int, float))
        or isinstance(imag, bool)
    ):
        raise TypeError("Complex data must contain numeric real and imag values")
    return complex(real, imag)


register(complex, complex_serializer, complex_deserializer)


# Bytes serializers and deserializers

def bytes_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
    '''Encode bytes as validated, ASCII base64 text.

    Args:
        obj: Bytes value to encode.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A dictionary containing the ``"base64"`` encoding marker and value.
    '''
    obj = cast(bytes, obj)
    return {
        "encoding": "base64",
        "value": base64.b64encode(obj).decode("ascii"),
    }

def bytes_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> bytes:
    '''Decode the base64 representation produced by :func:`bytes_serializer`.

    Args:
        cls: Unused class argument required by the deserializer interface.
        data: Dictionary containing an encoding marker and base64 value.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        The decoded bytes.

    Raises:
        ValueError: If the encoding marker is unsupported or the base64 data is
            invalid.
    '''
    data = cast(dict, data)
    if data.get("encoding") != "base64":
        raise ValueError("Unsupported bytes encoding")
    return base64.b64decode(data["value"], validate=True)

register(bytes, bytes_serializer, bytes_deserializer)


def bytearray_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
    '''Encode a bytearray using the bytes base64 representation.'''
    return bytes_serializer(bytes(cast(bytearray, obj)), options, ctx)


def bytearray_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> bytearray:
    '''Reconstruct a bytearray from the bytes base64 representation.'''
    return bytearray(bytes_deserializer(bytes, data, options, ctx))


register(bytearray, bytearray_serializer, bytearray_deserializer)


def memoryview_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, object]:
    '''Encode a contiguous memoryview's contents, format, shape, and access mode.'''
    view = cast(memoryview, obj)
    if not view.contiguous:
        raise TypeError("Only contiguous memoryviews can be serialized")
    raw = view.tobytes(order="C")
    try:
        memoryview(raw).cast(view.format, shape=list(view.shape))
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Memoryview format {view.format!r} cannot be reconstructed"
        ) from exc
    return {
        "data": bytes_serializer(raw, options, ctx),
        "format": view.format,
        "shape": list(view.shape),
        "readonly": view.readonly,
    }


def memoryview_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> memoryview:
    '''Reconstruct a contiguous memoryview from its contents and metadata.'''
    data = cast(dict, data)
    format = data.get("format")
    shape = data.get("shape")
    readonly = data.get("readonly")
    if (
        not isinstance(format, str)
        or not isinstance(shape, list)
        or not all(type(dimension) is int and dimension >= 0 for dimension in shape)
        or not isinstance(readonly, bool)
        or "data" not in data
    ):
        raise TypeError("Memoryview data must contain format, shape, readonly, and data values")
    raw = bytes_deserializer(bytes, data["data"], options, ctx)
    buffer = raw if readonly else bytearray(raw)
    return memoryview(buffer).cast(format, shape=shape)


register(memoryview, memoryview_serializer, memoryview_deserializer)


# Path serializers and deserializers

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


register(pathlib.Path, path_serializer, path_deserializer)


# Datetime serializers and deserializers

def isoformat_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> str | dict[str, object]:
    '''Encode a date, time, or datetime using its ISO 8601 representation.

    Datetimes and times with a fold value or reconstructable timezone also
    store that metadata alongside the ISO representation.

    Args:
        obj: Temporal value to serialize.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        The ISO representation, optionally with fold and timezone metadata.
    '''
    obj = cast(datetime.datetime | datetime.date | datetime.time, obj)
    value = obj.isoformat()
    if not isinstance(obj, (datetime.datetime, datetime.time)):
        return value

    data: dict[str, object] = {"value": value, "fold": obj.fold}
    if isinstance(obj.tzinfo, (datetime.timezone, ZoneInfo)):
        data["tzinfo"] = obj.tzinfo
    if obj.fold or "tzinfo" in data:
        return data
    return value


def isoformat_deserializer(cls: type, data: object, options: dict[str, object],
                           ctx: object | None) -> datetime.datetime | datetime.date | datetime.time:
    '''Reconstruct a registered temporal type from ISO 8601 text.

    Args:
        cls: Registered ``datetime`` type.
        data: ISO-formatted date, time, or datetime string, optionally accompanied
            by fold and timezone metadata.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        The value returned by ``cls.fromisoformat(data)`` with metadata restored
        when present.
    '''
    if isinstance(data, dict):
        value = data.get("value")
        fold = data.get("fold", 0)
        tzinfo = data.get("tzinfo")
        if (
            not isinstance(value, str)
            or type(fold) is not int
            or fold not in (0, 1)
            or (tzinfo is not None and not isinstance(tzinfo, datetime.tzinfo))
        ):
            raise TypeError("Temporal data must contain a valid value, fold, and timezone")
        return cls.fromisoformat(value).replace(fold=fold, tzinfo=tzinfo)
    return cls.fromisoformat(str(data))


register(datetime.datetime, cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))
register(datetime.date,     cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))
register(datetime.time,     cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))


def timedelta_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, int]:
    '''Encode a duration as exact integer day, second, and microsecond components.

    Args:
        obj: Duration to serialize.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A dictionary containing the normalized duration components.
    '''
    obj = cast(datetime.timedelta, obj)
    return {
        "days": obj.days,
        "seconds": obj.seconds,
        "microseconds": obj.microseconds,
    }


def timedelta_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> datetime.timedelta:
    '''Reconstruct a duration from exact integer components. (Storing a floating-point
    number of seconds can fail to preserve the correct number of microseconds.)

    Args:
        cls: Unused class argument required by the deserializer interface.
        data: A dictionary containing days, seconds, and microseconds.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        A :class:`datetime.timedelta`.
    '''
    if not isinstance(data, dict):
        raise TypeError("Timedelta data must contain days, seconds, and microseconds")
    return datetime.timedelta(
        days=data["days"],
        seconds=data["seconds"],
        microseconds=data["microseconds"],
    )


register(datetime.timedelta, timedelta_serializer, timedelta_deserializer)


# Regex serializers and deserializers

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

_registry.register(re.Pattern, regex_serializer, regex_deserializer)
_registry.register(re.RegexFlag, enum_serializer, enum_deserializer)


def decimal_serializer(obj: object, options: dict[str, object], ctx: object | None) -> str:
    '''Encode a Decimal as text to preserve its exact value and exponent.'''
    return str(cast(decimal.Decimal, obj))


def decimal_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> decimal.Decimal:
    '''Reconstruct a Decimal from its exact text representation.'''
    if not isinstance(data, str):
        raise TypeError("Decimal data must be a string")
    return decimal.Decimal(data)


register(decimal.Decimal, decimal_serializer, decimal_deserializer)


def uuid_serializer(obj: object, options: dict[str, object], ctx: object | None) -> str:
    '''Encode a UUID using its canonical hyphenated string representation.'''
    return str(cast(uuid.UUID, obj))


def uuid_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> uuid.UUID:
    '''Reconstruct a UUID from its canonical string representation.'''
    if not isinstance(data, str):
        raise TypeError("UUID data must be a string")
    return uuid.UUID(data)


register(uuid.UUID, uuid_serializer, uuid_deserializer)


# Additional standard-library value handlers

def fraction_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> dict[str, int]:
    '''Encode a Fraction as its exact normalized numerator and denominator.'''
    value = cast(Fraction, obj)
    return {"numerator": value.numerator, "denominator": value.denominator}


def fraction_deserializer(
    cls: type,
    data: object,
    options: dict[str, object],
    ctx: object | None,
) -> Fraction:
    '''Reconstruct a Fraction from exact integer components.'''
    if not isinstance(data, dict):
        raise TypeError("Fraction data must contain integer numerator and denominator")
    numerator = data.get("numerator")
    denominator = data.get("denominator")
    if type(numerator) is not int or type(denominator) is not int:
        raise TypeError("Fraction data must contain integer numerator and denominator")
    if denominator == 0:
        raise TypeError("Fraction denominator must not be zero")
    return Fraction(numerator, denominator)


register(Fraction, fraction_serializer, fraction_deserializer)


def timezone_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> dict[str, object]:
    '''Encode a fixed timezone by its exact offset and name.'''
    value = cast(datetime.timezone, obj)
    offset = value.utcoffset(None)
    if offset is None:
        raise TypeError("Timezone must have a fixed UTC offset")
    return {
        "offset_microseconds": (
            (offset.days * 86400 + offset.seconds) * 1_000_000
            + offset.microseconds
        ),
        "name": value.tzname(None),
    }


def timezone_deserializer(
    cls: type,
    data: object,
    options: dict[str, object],
    ctx: object | None,
) -> datetime.timezone:
    '''Reconstruct a fixed timezone from its exact offset and name.'''
    if not isinstance(data, dict):
        raise TypeError("Timezone data must contain an integer offset and optional name")
    offset_microseconds = data.get("offset_microseconds")
    name = data.get("name")
    if (
        type(offset_microseconds) is not int
        or (name is not None and not isinstance(name, str))
    ):
        raise TypeError("Timezone data must contain an integer offset and optional name")
    offset = datetime.timedelta(microseconds=offset_microseconds)
    if name is None:
        return datetime.timezone(offset)
    return datetime.timezone(offset, name)


register(datetime.timezone, timezone_serializer, timezone_deserializer)


def zoneinfo_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> str:
    '''Encode a ZoneInfo timezone by its IANA key.'''
    key = cast(ZoneInfo, obj).key
    if key is None:
        raise TypeError("ZoneInfo values without a key cannot be serialized")
    return key


def zoneinfo_deserializer(
    cls: type,
    data: object,
    options: dict[str, object],
    ctx: object | None,
) -> ZoneInfo:
    '''Reconstruct a ZoneInfo timezone using its IANA key.'''
    if not isinstance(data, str):
        raise TypeError("ZoneInfo data must be a string key")
    return ZoneInfo(data)


register(ZoneInfo, zoneinfo_serializer, zoneinfo_deserializer)


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


for _ip_type in (
    ipaddress.IPv4Address,
    ipaddress.IPv6Address,
    ipaddress.IPv4Network,
    ipaddress.IPv6Network,
    ipaddress.IPv4Interface,
    ipaddress.IPv6Interface,
):
    register(_ip_type, ipaddress_serializer, ipaddress_deserializer)


def _serialize_pairs(obj: object) -> list[list[object]]:
    return [[key, value] for key, value in cast(Iterable, obj)]


def _deserialize_pairs(data: object, type_name: str) -> list[list[object]]:
    if not isinstance(data, list) or not all(
        isinstance(pair, list) and len(pair) == 2 for pair in data
    ):
        raise TypeError(f"{type_name} data must be a list of key-value pairs")
    return data


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


register(collections.Counter, counter_serializer, counter_deserializer)


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


register(collections.OrderedDict, ordered_dict_serializer, ordered_dict_deserializer)


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


register(collections.deque, deque_serializer, deque_deserializer)
