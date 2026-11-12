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

Both operations accept an optional `Context`, which is passed to custom
serialization and deserialization callbacks:

```python
from simple_serialize import Context, deserialize, serialize

ctx = Context(offset=10)
json_text = serialize(person, ctx)
restored = deserialize(json_text, ctx)
```

`Context` stores positional values in `ctx.args` and named values in
`ctx.kwargs`. The library does not interpret those values; custom callbacks can
use them as needed.

## Custom serialization

For a decorated class, define `_serialize(self, ctx)` and
`_deserialize(cls, data, ctx)` to control its JSON data:

```python
from simple_serialize import Context, serializable


@serializable
class Temperature:
    def __init__(self, celsius):
        self.celsius = celsius

    def _serialize(self, ctx: Context):
        return {"fahrenheit": self.celsius * 9 / 5 + 32}

    @classmethod
    def _deserialize(cls, data, ctx: Context):
        return cls((data["fahrenheit"] - 32) * 5 / 9)
```

Alternatively, use `register` for a class you cannot modify. The serializer
receives the instance and context; the deserializer receives the class,
decoded data, and context. The callbacks should return JSON-compatible data
or a reconstructed instance, respectively.

```python
from simple_serialize import Context, register


class ExternalValue:
    def __init__(self, value):
        self.value = value


def serialize_external(obj: ExternalValue, ctx: Context):
    return {"value": obj.value}


def deserialize_external(cls, data, ctx: Context):
    return cls(data["value"])


register(
    ExternalValue,
    serialize_external,
    deserialize_external,
    json_name="ExternalValue",
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
- `bytes` (base64 encoded)
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
