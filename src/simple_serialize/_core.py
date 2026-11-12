import enum
import inspect
import json
import os
import pathlib
from dataclasses import is_dataclass
from typing import Any, Callable, TypeVar, overload

from ._objects import (
    dataclass_deserializer,
    dataclass_serializer,
    standard_deserializer,
    standard_serializer,
)
from ._registry import Deserializer, Serializer, _registry
from ._stdlib_types import enum_deserializer, enum_serializer


TYPE_KEY = "__type__"
DATA_KEY = "__data__"
Pathlike = str | os.PathLike | pathlib.Path


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

T = TypeVar("T", bound=type)

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
    respective built-in implementations. A classmethod deserializer is unbound so
    registration can invoke it with the class as its first argument. Both custom
    methods receive options before context.

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
