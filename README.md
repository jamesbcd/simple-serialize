# simple-serialize

`simple-serialize` is a small Python library for serializing Python values and
registered objects to and from JSON. Register a class with the `@serializable`
decorator or `register` function, then use `serialize`/`deserialize` for JSON
strings or `save`/`load` for files.

Requires Python 3.10 or later.

## Installation

Install from the repository:

```shell
python -m pip install .
```

## Quick start

Decorate a class to make it serializable. Dataclasses are serialized by field;
ordinary classes are serialized from their instance attributes.

```python
from dataclasses import dataclass

from simple_serialize import deserialize, serializable, serialize


@serializable("Person")
@dataclass
class Person:
    name: str
    age: int


person = Person("Ada", 36)
json_text = serialize(person)
print(json_text)

restored = deserialize(json_text)
assert restored == person
```

Registered objects are represented in JSON by a type name and serialized data:

```json
{
    "__type__": "Person",
    "__data__": {
        "name": "Ada",
        "age": 36
    }
}
```

The class must be registered in the current Python process before its serialized
value can be deserialized. Use an explicit name such as `"Person"` when the JSON
type name should remain stable if the Python class is renamed.

## JSON strings and files

`serialize(obj, ctx=None)` returns an indented JSON string, and
`deserialize(json_text, ctx=None)` returns the decoded value. The file helpers
use UTF-8; `save` creates missing parent directories.

```python
from simple_serialize import load, save

save(person, "data/person.json")
restored = load("data/person.json")
```

Both operations accept an optional opaque `ctx` value, which is passed to
custom serialization and deserialization callbacks unchanged. Per-class keyword
options supplied during registration are passed as a dictionary immediately
before `ctx`. If omitted, callbacks receive `None` for `ctx`:

```python
from simple_serialize import deserialize, serialize

ctx = {"offset": 10}
json_text = serialize(person, ctx)
restored = deserialize(json_text, ctx)
```

The library does not inspect or modify `ctx`; define and interpret its structure
in your own callbacks.

## Attribute options

The default serializers for ordinary classes and dataclasses recognize three
registration options:

- `exclude`: a list of attribute or field names omitted from serialized data.
- `select`: a list of the only attribute or field names to serialize. When both
  `select` and `exclude` are supplied, `select` takes precedence.
- `rename`: a mapping from Python attribute or field names to JSON names.
  Renamed names are mapped back during deserialization.

Names in `select` and `exclude` refer to Python attribute or field names, before
any renaming. For example:

```python
@serializable(
    exclude=["password"],
    rename={"first_name": "firstName"},
)
@dataclass
class Account:
    first_name: str
    password: str
```

An excluded or unselected value is not present in the JSON data. It therefore
needs a suitable default or otherwise compatible constructor if the object is
to be deserialized. Custom serialization callbacks receive these options in
their options dictionary and remain responsible for applying them.
The exported `mapping_serializer` and `mapping_deserializer` callbacks apply
them to mapping keys when you register those callbacks for a mapping class.
Native dictionaries are serialized as ordinary JSON objects and are not
filtered or renamed.

## Custom serialization

For a decorated class, define `_serialize(self, options, ctx)` and
`_deserialize(cls, data, options, ctx)` to control its JSON data. Decorator
keyword arguments become the `options` dictionary:

```python
from simple_serialize import serializable


@serializable(scale=1.8)
class Temperature:
    def __init__(self, celsius):
        self.celsius = celsius

    def _serialize(self, options, ctx):
        return {"fahrenheit": self.celsius * options["scale"] + 32}

    @classmethod
    def _deserialize(cls, data, options, ctx):
        return cls((data["fahrenheit"] - 32) / options["scale"])
```

Alternatively, use `register` for a class you cannot modify. The serializer
receives the instance, options dictionary, and context; the deserializer
receives the class, decoded data, options dictionary, and context. The
callbacks should return JSON-compatible data or a reconstructed instance,
respectively. Additional keyword arguments to `register` become the options
dictionary; `json_name` continues to select the JSON type name.

```python
from simple_serialize import register


class ExternalValue:
    def __init__(self, value):
        self.value = value


def serialize_external(obj: ExternalValue, options, ctx):
    return {"value": obj.value}


def deserialize_external(cls, data, options, ctx):
    return cls(data["value"])


register(
    ExternalValue,
    serialize_external,
    deserialize_external,
    json_name="ExternalValue",
    units="meters",
)
```

If custom callbacks are omitted, enums use their member values, dataclasses use
their fields, and other classes use their instance attributes, including
initialized `__slots__`. The default deserializer for an ordinary class calls
its constructor without arguments, so such classes must support `Class()`.

## Supported values

JSON-native values (`None`, booleans, numbers, strings, lists, and dictionaries)
can be serialized directly. The library also has built-in handlers for:

- `tuple`, `set`, and `frozenset` (encoded as JSON arrays; set iteration order
  is not guaranteed)
- `complex` (real and imaginary components)
- `decimal.Decimal` (text representation, preserving precision and exponent)
- `uuid.UUID` (canonical hyphenated string)
- `bytes` and `bytearray` (base64 encoded)
- `memoryview` (contents, format, shape, and read-only state; only contiguous
  views are supported, and the original backing buffer is not retained)
- `range` and `slice` (start, stop, and step values)
- `pathlib.Path`
- `datetime.datetime`, `datetime.date`, `datetime.time`, and
  `datetime.timedelta`
- Compiled regular expressions (`re.Pattern`) and `re.RegexFlag`

Other Python classes, including enum and dataclass types, must be registered
before use.

## Format and limitations

- The reserved JSON keys `__type__` and `__data__` identify registered values.
  Any dictionary containing `__type__` is treated as serialization metadata
  when deserialized, so avoid using that key for ordinary dictionary data.
- Registered objects cannot be dictionary keys.
- Circular references raise `ValueError`. Repeated references that are not
  circular are serialized as independent values; object identity is not kept.
- Only deserialize JSON from sources you trust. Deserialization invokes the
  registered callbacks and constructors in your process.

## Running the tests

Install the test dependency and run pytest:

```shell
python -m pip install '.[test]'
python -m pytest
```

## License

MIT
