from typing import Callable


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
