'''Serialize registered Python objects to and from JSON.

Objects are represented by JSON objects containing the reserved ``__type__``
and ``__data__`` keys. Classes can be registered with :func:`register` or the
:func:`serializable` decorator. Built-in registrations cover common Python
values such as paths, dates, bytes, regular expressions, and containers.
'''
import enum
import base64
from dataclasses import fields, is_dataclass
import inspect
import json
import os
import pathlib
import datetime
import re
from typing import Any, Callable, Iterable, cast, TypeVar, overload


# Reserved keys identifying a registered type and its serialized data.
TYPE_KEY = "__type__"
DATA_KEY = "__data__"


class Context:
    '''Carry optional caller-supplied state through serialization operations.

    The context is passed to custom serializers and deserializers. It is
    currently only a transport for caller-provided values; the library itself
    does not interpret them.

    Attributes:
        args: Positional values supplied when the context was created.
        kwargs: Named values supplied when the context was created.
    '''

    def __init__(self, *args, **kwargs):
        '''Store positional and keyword context values.

        Args:
            *args: Positional values available to serializers and deserializers.
            **kwargs: Named values available to serializers and deserializers.
        '''
        # Preserve caller-supplied context for custom serialization callbacks.
        self.args = args
        self.kwargs = kwargs


# Type aliases for serializer and deserializer callables
# Serializer takes an object and context and returns a JSON-serializable representation
# Deserializer takes a class, JSON data, and context and returns an object instance.
Serializer = Callable[[object, Context], object]
Deserializer = Callable[[type, object, Context], object]


class _Registry:
    '''Map Python classes and JSON type names to serialization callbacks.

    Attributes:
        _serializers: Class-to-(JSON name, serializer) lookup table.
        _deserializers: JSON-name-to-(class, deserializer) lookup table.
    '''

    def __init__(self):
        '''Initialize empty serializer and deserializer lookup tables.'''
        # Keep each class and JSON name unique in its respective lookup table.
        self._serializers: dict[type, tuple[str, Serializer]] = {}
        self._deserializers: dict[str, tuple[type, Deserializer]] = {}

    def serializer_for(self, obj: object) -> tuple[str, Serializer] | None:
        '''Find a registered serializer applicable to ``obj``.

        Lookup prefers the exact runtime type, then registered base classes in
        method-resolution order, then any registered type matching through
        ``isinstance`` (including virtual ABC registrations).

        Args:
            obj: Object whose serializer is requested.

        Returns:
            The registered JSON type name and serializer, or ``None`` if no
            registration applies.
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
                 json_name: str | None = None):
        '''Add a class and its callbacks to the registry.

        Args:
            cls: Python class handled by the callbacks.
            serializer: Converts an instance and context into serializable data.
            deserializer: Reconstructs an instance from the class, data, and context.
            json_name: Type name stored in JSON; defaults to ``cls.__name__``.

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
        self._serializers[cls] = (json_name, serializer)
        self._deserializers[json_name] = (cls, deserializer)

_registry = _Registry()

# 
# Public API for registering and using serializers
#
def register(cls: type,
             serializer: Serializer,
             deserializer: Deserializer,
             json_name: str | None = None) -> None:
    '''Register a class with custom serialization callbacks.

    Use this function for classes that cannot be modified to add
    :func:`serializable` or custom ``_serialize`` and ``_deserialize`` methods.

    Args:
        cls: The Python class to register.
        serializer: Callable receiving an instance and :class:`Context`, and
            returning data that can be encoded as JSON.
        deserializer: Callable receiving the class, decoded data, and context,
            and returning an instance.
        json_name: Optional type name stored in the JSON representation.
            Defaults to the class name.

    Raises:
        TypeError: If either callback is not callable.
        ValueError: If the class or JSON type name is already registered.
    '''
    _registry.register(cls, serializer, deserializer, json_name)


# Accepted path values for :func:`save`.
Pathlike = str | os.PathLike | pathlib.Path


def save(obj: object, path: Pathlike, ctx: Context | None = None) -> None:
    '''Serialize ``obj`` as JSON and write it to ``path``.

    Missing parent directories are created. The object's type must be
    registered, either with :func:`serializable` or :func:`register`.

    Args:
        obj: Object to serialize.
        path: Destination path.
        ctx: Optional context passed to serializers.
    '''
    path = pathlib.Path(path)
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    json_str = serialize(obj, ctx)
    with path.open('w', encoding='utf-8') as file:
        file.write(json_str)

def serialize(obj: object, ctx: Context | None = None) -> str:
    '''Encode an object as an indented JSON string.

    Registered objects are encoded with the reserved :data:`TYPE_KEY` and
    :data:`DATA_KEY` fields. Dictionaries containing those fields may therefore
    be interpreted as serialization metadata when loaded. Nested dictionaries
    and lists/tuples are prepared recursively. Cycles in these containers or
    registered objects raise ``ValueError``; shared but non-cyclic references
    are serialized independently.

    Args:
        obj: Value to encode. Non-JSON-native objects must be registered.
        ctx: Optional context passed to serializers. A fresh empty context is
            used when omitted.

    Returns:
        A Unicode JSON string formatted with four-space indentation.
    '''
    if ctx is None:
        ctx = Context() # Empty for now, but may be used in future.
    return json.dumps(
        _prepare_for_json(obj, ctx),
        indent=4,
        ensure_ascii=False,
        default=lambda obj: _serialize_handler(obj, ctx),
    )

def load(path: Pathlike, ctx: Context | None = None) -> object:
    '''Read JSON from ``path`` and deserialize its value.

    Any registered types in the file must already be registered in this
    process, either with :func:`serializable` or :func:`register`.

    Args:
        path: Source path.
        ctx: Optional context passed to deserializers.

    Returns:
        The decoded Python value.
    '''
    path = pathlib.Path(path)
    with path.open('r', encoding='utf-8') as file:
        json_str = file.read()
    return deserialize(json_str, ctx)

def deserialize(json_str: str, ctx: Context | None = None) -> object:
    '''Decode a JSON string into Python values and registered objects.

    Objects containing :data:`TYPE_KEY` are treated as registered-type
    metadata and must also contain :data:`DATA_KEY`. Each encountered type
    name must have a deserializer registered in this process.

    Args:
        json_str: JSON text to decode.
        ctx: Optional context passed to deserializers. A fresh empty context is
            used when omitted.

    Returns:
        The decoded Python value.
    '''
    if ctx is None:
        ctx = Context()
    return json.loads(json_str, object_hook=lambda data: _deserialize_handler(data, ctx)) 

#
# Internal helper functions for working with JSON serialization and deserialization
#
def _prepare_for_json(
    obj: object,
    ctx: Context,
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
        ctx: Context passed to any registered serializer.
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

def _serialize_handler(obj: object, ctx: Context):
    '''Encode a registered object as a type-name/data metadata dictionary.

    This function is also used as ``json.dumps``'s fallback for values not
    handled by preprocessing.

    Args:
        obj: Registered object to encode.
        ctx: Context passed to its serializer.

    Returns:
        A dictionary containing :data:`TYPE_KEY` and :data:`DATA_KEY`.

    Raises:
        TypeError: If the object's type has no registered serializer.
    '''
    registered = _registry.serializer_for(obj)
    if registered is None:
        raise TypeError(f"Object of type {type(obj).__name__} is not registered as serializable")
    json_name, serializer = registered
    return {
        TYPE_KEY: json_name,
        DATA_KEY: serializer(obj, ctx)
    }

def _deserialize_handler(input_dict: dict, ctx: Context) -> object:
    '''Reconstruct registered objects found by ``json.loads``'s object hook.

    Ordinary dictionaries are returned unchanged. A dictionary containing
    :data:`TYPE_KEY` is treated as metadata, looked up by its JSON type name,
    and passed to the corresponding deserializer.

    Args:
        input_dict: A decoded JSON object.
        ctx: Context passed to registered deserializers.

    Returns:
        The original ordinary dictionary or its reconstructed object.

    Raises:
        TypeError: If the type name is unknown or its data field is missing.
    '''
    if TYPE_KEY not in input_dict:
        # This is a regular dictionary, so return it as-is.
        return input_dict
    json_name = input_dict[TYPE_KEY]
    (cls, deserializer) = _registry._deserializers.get(json_name, (object, None))
    if deserializer is None:
        raise TypeError(f"No deserializer registered for JSON type {json_name}")
    if DATA_KEY not in input_dict:
        raise TypeError(f"No {DATA_KEY} key found for JSON type {json_name}")
    data = input_dict[DATA_KEY]
    return deserializer(cls, data, ctx)

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

# Case 2: Used with a custom JSON name, e.g., @serializable("my_name")
# This returns a factory function that takes the class and returns it unchanged.
@overload
def serializable(cls_or_json_name: str, *args: Any, **kwargs: Any) -> Callable[[T], T]:
    '''Type signature for creating a decorator with a custom JSON name.'''
    ...

def serializable(cls_or_json_name: type | str, *args, **kwargs) -> Any:
    '''Decorator to register a class as serializable.

    Use as ``@serializable`` or ``@serializable("CustomName")``. The class
    remains unchanged after registration. Unless it provides custom callbacks,
    enums use enum-specific handling, dataclasses use field-based handling,
    and other classes use their instance attributes, including ``__dict__``
    entries and ``__slots__``.

    A decorated class can customize serialization by implementing:

        def _serialize(self, ctx: Context) -> object:
            # Return data that can be encoded as JSON.
    
        @classmethod
        def _deserialize(cls, data: object, ctx: Context) -> object:
            # Reconstruct and return an instance from the decoded data.

    Args:
        cls_or_json_name: The class to decorate, or a custom JSON type name
            when used as a decorator factory.
        *args: Accepted for decorator-call compatibility; not interpreted.
        **kwargs: Accepted for decorator-call compatibility; not interpreted.

    Returns:
        The decorated class, or a decorator when given a JSON type name.

    Raises:
        TypeError: If a class's custom serializer or deserializer is not callable.
        ValueError: If the class or JSON type name is already registered.
    '''
    if isinstance(cls_or_json_name, str):
        # Decorator was called with a custom JSON name e.g. @serializable("CustomName")
        # We have to return a wrapper function that will be called with the class itself
        json_name = cls_or_json_name
        def wrapper(cls: type) -> type:
            '''Register ``cls`` under the selected JSON type name and return it.'''
            serializer, deserializer = _get_serializers_for_decorated_class(cls)
            _registry.register(cls, serializer, deserializer, json_name)
            # We leave the underlying class unchanged
            return cls
        return wrapper
    else:
        # Decorator was used without arguments e.g. @serializable
        # So this function itself does the decoratorating
        cls = cls_or_json_name
        serializer, deserializer = _get_serializers_for_decorated_class(cls)
        _registry.register(cls, serializer, deserializer, cls.__name__)
        return cls

def _get_serializers_for_decorated_class(cls: type) -> tuple[Serializer, Deserializer]:
    '''Select custom or default callbacks for a decorated class.

    Callback selection prefers the class's ``_serialize`` or ``_deserialize``
    method. Otherwise enums, dataclasses, and ordinary classes use their
    respective built-in implementations. A classmethod deserializer is
    unbound so registration can invoke it with the class as its first argument.

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


def standard_serializer(obj: object, ctx: Context) -> dict:
    '''Copy an ordinary object's instance attributes into a dictionary.

    Args:
        obj: Object whose ``__dict__`` and ``__slots__`` will be copied.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A shallow copy of the object's initialized instance attributes.
    '''
    try:
        new_obj = dict(getattr(obj, "__dict__", {}))
        for name in _get_slot_names(type(obj)):
            try:
                new_obj[name] = getattr(obj, name)
            except AttributeError:
                continue
    except Exception:
        raise TypeError(f"Failed to serialize object of type {type(obj).__name__}")
    return new_obj

def standard_deserializer(cls: type, data: object, ctx: Context) -> object:
    '''Construct an ordinary class and restore its instance attributes.

    The class must be constructible without arguments. The decoded data is
    applied to its ``__dict__`` and declared slots.

    Args:
        cls: Class to instantiate.
        data: Mapping of instance attribute names to values.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        The reconstructed instance.

    Raises:
        TypeError: If construction or attribute restoration fails.
    '''
    try:
        instance = cls()
        attributes = dict(cast(dict, data))
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
        raise TypeError(f"Failed to deserialize object of type {cls.__name__}: {e}")
    return instance

def iterable_serializer(obj: object, ctx: Context) -> list:
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


def iterable_deserializer(cls: type, data: object, ctx: Context) -> Iterable:
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


def mapping_serializer(obj: object, ctx: Context) -> dict:
    '''Return a shallow dictionary copy of a mapping.

    Args:
        obj: Mapping value to copy.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A plain ``dict`` containing the same key-value pairs.
    '''
    obj = cast(dict, obj)
    return dict(obj)


def mapping_deserializer(cls: type, data: object, ctx: Context) -> object:
    '''Construct a mapping class from decoded dictionary data.

    Args:
        cls: Mapping class to construct.
        data: Decoded dictionary.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        ``cls(data)``.
    '''
    data = cast(dict, data)
    return cls(data)


def dataclass_serializer(obj: object, ctx: Context) -> dict:
    '''Serialize a dataclass instance as a field-name/value dictionary.

    Args:
        obj: Dataclass instance to serialize.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        A dictionary containing the values of the dataclass fields.

    Raises:
        TypeError: If ``obj`` is not a dataclass instance.
    '''
    if not is_dataclass(obj):
        raise TypeError(f"Object of type {type(obj).__name__} is not a dataclass")
    return {field.name: getattr(obj, field.name) for field in fields(obj)}


def dataclass_deserializer(cls: type, data: object, ctx: Context) -> object:
    '''Reconstruct a dataclass by passing decoded fields to its constructor.

    Constructor-based reconstruction also supports frozen dataclasses without
    assigning to their attributes after creation.

    Args:
        cls: Dataclass type to construct.
        data: Mapping of field names to decoded values.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        The reconstructed dataclass instance.

    Raises:
        TypeError: If construction fails.
    '''
    data = cast(dict, data)
    try:
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
        raise TypeError(f"Failed to deserialize object of type {cls.__name__}: {e}")
    return instance

#
# Custom serializers and deserializers for common types
#

# Enum serializers and deserializers
#
# We don't register a general enum serializer/deserializer here, because Enums are almost
# always subclasses, and it's better to register the subclasses.

def enum_serializer(obj: object, ctx: Context) -> dict:
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

def enum_deserializer(cls: type, data: object, ctx: Context) -> enum.Enum:
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

# Bytes serializers and deserializers

def bytes_serializer(obj: object, ctx: Context) -> dict:
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

def bytes_deserializer(cls: type, data: object, ctx: Context) -> bytes:
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

# Path serializers and deserializers

def path_serializer(obj: object, ctx: Context) -> str:
    '''Encode a path using POSIX separators.

    Args:
        obj: Path to serialize.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        The path's POSIX-form string.
    '''
    obj = cast(pathlib.Path, obj)
    return obj.as_posix()


def path_deserializer(cls: type, data: object, ctx: Context) -> pathlib.Path:
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

def isoformat_serializer(obj: object, ctx: Context) -> str:
    '''Encode a date, time, or datetime using its ISO 8601 representation.

    Args:
        obj: Temporal value to serialize.
        ctx: Unused context, accepted to match the serializer interface.

    Returns:
        The value returned by ``obj.isoformat()``.
    '''
    obj = cast(datetime.datetime | datetime.date | datetime.time, obj)
    return obj.isoformat()


def isoformat_deserializer(cls: type, data: object,
                           ctx: Context) -> datetime.datetime | datetime.date | datetime.time:
    '''Reconstruct a registered temporal type from ISO 8601 text.

    Args:
        cls: Registered ``datetime`` type.
        data: ISO-formatted date, time, or datetime string.
        ctx: Unused context, accepted to match the deserializer interface.

    Returns:
        The value returned by ``cls.fromisoformat(data)``.
    '''
    return cls.fromisoformat(str(data))


register(datetime.datetime, cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))
register(datetime.date,     cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))
register(datetime.time,     cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))


def timedelta_serializer(obj: object, ctx: Context) -> dict[str, int]:
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


def timedelta_deserializer(cls: type, data: object, ctx: Context) -> datetime.timedelta:
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

def regex_serializer(obj: object, ctx: Context) -> dict:
    '''Encode a compiled regular expression's pattern and flags.

    Byte patterns use the same base64 representation as bytes values; string
    patterns are stored directly.

    Args:
        obj: Compiled regular expression.
        ctx: Context passed to bytes serialization when needed.

    Returns:
        A dictionary containing the pattern and integer flags.
    '''
    obj = cast(re.Pattern, obj)
    pattern = obj.pattern
    if isinstance(pattern, bytes):
        pattern = bytes_serializer(pattern, ctx)
    return {
        "pattern": pattern,
        "flags": obj.flags
    }

def regex_deserializer(cls: type, data: object, ctx: Context) -> re.Pattern:
    '''Recompile a regular expression from its stored pattern and flags.

    Args:
        cls: Unused class argument required by the deserializer interface.
        data: Dictionary containing a string or encoded byte pattern and flags.
        ctx: Context passed to bytes deserialization for byte patterns.

    Returns:
        A compiled regular expression.
    '''
    data = cast(dict, data)
    pattern = data["pattern"]
    if isinstance(pattern, dict):
        pattern = bytes_deserializer(bytes, pattern, ctx)
    flags = data["flags"]
    return re.compile(pattern, flags)

_registry.register(re.Pattern, regex_serializer, regex_deserializer)
_registry.register(re.RegexFlag, enum_serializer, enum_deserializer)