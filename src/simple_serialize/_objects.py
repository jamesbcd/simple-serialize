from dataclasses import fields, is_dataclass
from typing import cast


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
