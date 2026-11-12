# simple-serialize

`simple-serialize` is a small Python library for serializing Python objects
to and from JSON. Classes must be registered to be serialized, either by using
the `@serializable` decorator (simplest), or the `register` function (for types
you don't control). Use `serialize`/`deserialize` for converting to and from
JSON strings, or `save`/`load` for writing and reading those strings to disk.

Requires Python 3.10 or later.

## Installation

Install from the repository:

```shell
python -m pip install .
```

## Quick start

Decorate a class to make it serializable. Ordinary classes are serialized from their instance attributes. Dataclasses are serialized from their fields.

```python
from dataclasses import dataclass

from simple_serialize import deserialize, serializable, serialize


@serializable
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

Registered objects are represented in JSON by a type name and serialized data.

```json
{
    "__type__": "Person",
    "__data__": {
        "name": "Ada",
        "age": 36
    }
}
```

Passing a string argument to @serializable will use that string instead of the class name
as the value of the `__type__` key. Use an explicit name when the JSON type name should remain stable if the Python class is renamed.

For a class you can't decorate, use the `register` function, and supply serializer 
and deserializer functions. For example:

```python
from simple_serialize import register


class ExternalValue: # Some externally defined class you don't control
    def __init__(self, value):
        self.value = value

# Functions you define to handle serialization and deserialization

def serialize_external(obj: ExternalValue, options, ctx):
    return {"value": obj.value}

def deserialize_external(cls, data, options, ctx):
    return cls(data["value"])

# Register the class and its handler functions

register(
    ExternalValue,
    serialize_external,
    deserialize_external,
    json_name="ExternalValue",
    units="meters",
)
```

The class must be registered in the current Python process before its serialized
value can be deserialized.

Serializer callbacks receive the instance, options dictionary, and an opaque context
context object (see below). They should return JSON-compatible data. Deserializers receive the class, decoded data, options dictionary, and context object. They should return a reconstructed instance. Additional keyword arguments to `register` become the options dictionary; `json_name` continues to select the JSON type name.

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
custom serialization and deserialization callbacks unchanged. 

```python
from simple_serialize import deserialize, serialize

ctx = {"offset": 10}
json_text = serialize(person, ctx)
restored = deserialize(json_text, ctx)
```

The library does not inspect or modify `ctx`; define and interpret its structure
in your own callbacks.

## Registration options

Keyword arguments passed to `@serializable` or `register` are collected into
an `options` dictionary passed to the serializer and deserializer. The default serializers for ordinary classes and dataclasses recognize three keywords:

- `exclude`: a list of attribute or field names omitted from serialized data.
- `select`: a list of the only attribute or field names to serialize (overrides
  `exclude`).
- `rename`: a mapping from Python attribute or field names to JSON names.
  Renamed names are mapped back during deserialization. Attribute names not in this
  mapping remain unchanged.

For example:

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

Names in `select` and `exclude` refer to Python attribute or field names, before
any renaming. An excluded or unselected value is not present in the JSON data. It therefore needs a suitable default or otherwise compatible constructor if the object is
to be deserialized.

Custom serialization callbacks receive these options in their options dictionary and remain responsible for applying them. The exported `mapping_serializer` and `mapping_deserializer` callbacks apply them to mapping keys when you register those callbacks for a mapping class. Native dictionaries are serialized as ordinary JSON objects and are not filtered or renamed.

## Custom serialization

For a decorated class, define `_serialize(self, options, ctx)` and
`_deserialize(cls, data, options, ctx)` methods to define custom conversions to
and from JSON. Decorator keyword arguments are available in the `options` dictionary:

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

If thse custom methods are omitted, enums use their member values, dataclasses use
their fields, and other classes use their instance attributes, including
initialized `__slots__`. The default deserializer for an ordinary class calls
its constructor without arguments, so such classes must support `Class()`.

## Supported types

JSON-native types (`None`, booleans, numbers, strings, lists, and dictionaries)
can be serialized directly. The library also has built-in handlers for:

- `tuple`, `set`, and `frozenset` (encoded as JSON arrays; set iteration order
  is not guaranteed)
- `complex` (real and imaginary components)
- `fractions.Fraction` (exact numerator and denominator)
- `decimal.Decimal` (text representation, preserving precision and exponent)
- `uuid.UUID` (canonical hyphenated string)
- `ipaddress` address, network, and interface values (canonical text)
- `collections.Counter`, `collections.OrderedDict`, and `collections.deque`
  (including non-string keys, order, and `deque.maxlen`)
- `bytes` and `bytearray` (base64 encoded)
- `memoryview` (contents, format, shape, and read-only state; only contiguous
  views are supported, and the original backing buffer is not retained)
- `range` and `slice` (start, stop, and step values)
- `pathlib.Path`
- `datetime.datetime`, `datetime.date`, `datetime.time`, and
  `datetime.timedelta` (`datetime.timezone` offsets/names and keyed
  `zoneinfo.ZoneInfo` values are preserved for datetimes and times)
- `datetime.timezone` and keyed `zoneinfo.ZoneInfo` values
- Compiled regular expressions (`re.Pattern`) and `re.RegexFlag`

Other Python classes, including enum and dataclass types, must be registered
before use. Restoring a `ZoneInfo` value requires the corresponding IANA
timezone database entry to be available on the receiving system. Arbitrary
custom `tzinfo` implementations are represented by their ISO offset rather
than reconstructed as the original timezone object.

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
