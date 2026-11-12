import datetime
import enum
import json
import pathlib
import re
from collections.abc import Iterable
from dataclasses import FrozenInstanceError, dataclass, field

import pytest

from simple_serialize import (
    DATA_KEY,
    TYPE_KEY,
    _Registry,
    deserialize,
    load,
    register,
    save,
    serializable,
    serialize,
    dataclass_deserializer,
    standard_deserializer,
    standard_serializer,
)


def test_standard_decorated_object_round_trips():
    @serializable("SerializeTestObject")
    class TestObject:
        def __init__(self):
            self.value = 42

    result = deserialize(serialize(TestObject()))

    assert isinstance(result, TestObject)
    assert result.value == 42


def test_standard_decorated_slotted_object_round_trips():
    class TestSlotBase:
        __slots__ = ("base_value",)

    @serializable("SerializeTestSlottedObject")
    class TestSlottedObject(TestSlotBase):
        __slots__ = ("value", "__private_value")

        def __init__(self):
            self.base_value = "base"
            self.value = 42
            self.__private_value = "private"

        def private_value(self):
            return self.__private_value

    result = deserialize(serialize(TestSlottedObject()))

    assert isinstance(result, TestSlottedObject)
    assert result.base_value == "base"
    assert result.value == 42
    assert result.private_value() == "private"


def test_standard_serializer_preserves_original_exception_as_cause():
    class BrokenObject:
        def __getattribute__(self, name):
            if name == "__dict__":
                raise ValueError("attribute access failed")
            return super().__getattribute__(name)

    with pytest.raises(TypeError, match="Failed to serialize") as exc_info:
        standard_serializer(BrokenObject(), {}, None)

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "attribute access failed"


def test_standard_deserializer_preserves_original_exception_as_cause():
    class BrokenObject:
        def __init__(self):
            raise ValueError("construction failed")

    with pytest.raises(TypeError, match="Failed to deserialize") as exc_info:
        standard_deserializer(BrokenObject, {}, {}, None)

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "construction failed"


def test_dataclass_deserializer_preserves_original_exception_as_cause():
    @dataclass
    class BrokenDataclass:
        value: int

        def __post_init__(self):
            raise ValueError("post-init failed")

    with pytest.raises(TypeError, match="Failed to deserialize") as exc_info:
        dataclass_deserializer(BrokenDataclass, {"value": 1}, {}, None)

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "post-init failed"


def test_custom_serializer_and_deserializer_round_trip():
    @serializable("SerializeTestCustom")
    class TestCustom:
        def __init__(self, value=0):
            self.value = value

        def _serialize(self, options, ctx):
            assert options == {}
            assert ctx is None
            return {"value": self.value * 2}

        @classmethod
        def _deserialize(cls, data, options, ctx):
            assert options == {}
            assert ctx is None
            return cls(data["value"] // 2)

    result = deserialize(serialize(TestCustom(21)))

    assert isinstance(result, TestCustom)
    assert result.value == 21


def test_save_and_load_pass_context_to_custom_callbacks(tmp_path):
    @serializable("SerializeTestSaveLoadContext")
    class TestContextual:
        def __init__(self, value):
            self.value = value

        def _serialize(self, options, ctx):
            assert options == {}
            assert ctx is supplied_ctx
            return {"value": self.value + ctx["offset"]}

        @classmethod
        def _deserialize(cls, data, options, ctx):
            assert options == {}
            assert ctx is supplied_ctx
            return cls(data["value"] - ctx["offset"])

    value = TestContextual(21)
    supplied_ctx = {"offset": 10}
    path = tmp_path / "context.json"

    save(value, path, supplied_ctx)
    result = load(path, supplied_ctx)

    assert isinstance(result, TestContextual)
    assert result.value == 21


def test_decorator_options_are_passed_before_context():
    expected_options = {"multiplier": 2, "label": "configured"}

    @serializable("SerializeTestDecoratorOptions", **expected_options)
    class TestConfigured:
        def __init__(self, value):
            self.value = value

        def _serialize(self, options, ctx):
            assert options == expected_options
            assert ctx == "context"
            return {"value": self.value * options["multiplier"]}

        @classmethod
        def _deserialize(cls, data, options, ctx):
            assert options == expected_options
            assert ctx == "context"
            return cls(data["value"] // options["multiplier"])

    result = deserialize(serialize(TestConfigured(21), "context"), "context")

    assert isinstance(result, TestConfigured)
    assert result.value == 21


def test_decorator_options_work_without_explicit_json_name():
    @serializable(multiplier=3)
    class TestConfigured:
        def __init__(self, value):
            self.value = value

        def _serialize(self, options, ctx):
            return {"value": self.value * options["multiplier"]}

        @classmethod
        def _deserialize(cls, data, options, ctx):
            return cls(data["value"] // options["multiplier"])

    result = deserialize(serialize(TestConfigured(14)))

    assert isinstance(result, TestConfigured)
    assert result.value == 14


def test_register_options_are_passed_before_context():
    class ExternalValue:
        def __init__(self, value):
            self.value = value

    expected_options = {"offset": 5}

    def serializer(obj, options, ctx):
        assert options == expected_options
        assert ctx == "context"
        return {"value": obj.value + options["offset"]}

    def deserializer(cls, data, options, ctx):
        assert options == expected_options
        assert ctx == "context"
        return cls(data["value"] - options["offset"])

    register(
        ExternalValue,
        serializer,
        deserializer,
        json_name="SerializeTestRegisterOptions",
        **expected_options,
    )
    result = deserialize(
        serialize(ExternalValue(21), "context"),
        "context",
    )

    assert isinstance(result, ExternalValue)
    assert result.value == 21


def test_standard_serializer_excludes_attributes():
    @serializable("SerializeTestExclude", exclude=["secret"])
    class TestExcluded:
        def __init__(self):
            self.value = 42
            self.secret = "hidden"

    serialized = serialize(TestExcluded())

    assert json.loads(serialized)[DATA_KEY] == {"value": 42}
    result = deserialize(serialized)
    assert isinstance(result, TestExcluded)
    assert result.value == 42
    assert result.secret == "hidden"


def test_select_takes_precedence_over_exclude_and_renames_attributes():
    @serializable(
        "SerializeTestSelectRename",
        select=["value", "secret"],
        exclude=["secret"],
        rename={"secret": "private"},
    )
    class TestSelected:
        def __init__(self):
            self.value = 42
            self.secret = "hidden"
            self.other = "excluded by select"

    serialized = serialize(TestSelected())

    assert json.loads(serialized)[DATA_KEY] == {
        "value": 42,
        "private": "hidden",
    }
    result = deserialize(serialized)
    assert isinstance(result, TestSelected)
    assert result.value == 42
    assert result.secret == "hidden"
    assert result.other == "excluded by select"


def test_dataclass_attribute_options_round_trip():
    @serializable(
        "SerializeTestDataclassAttributeOptions",
        exclude=["secret"],
        rename={"first_name": "firstName"},
    )
    @dataclass
    class TestPerson:
        first_name: str
        secret: str = "default"

    person = TestPerson("Ada", "not serialized")
    serialized = serialize(person)

    assert json.loads(serialized)[DATA_KEY] == {"firstName": "Ada"}
    assert deserialize(serialized) == TestPerson("Ada")


def test_registered_subclass_takes_priority_over_registered_base():
    registry = _Registry()

    class Base:
        pass

    class Child(Base):
        pass

    registry.register(
        Base, lambda obj, options, ctx: "base",
        lambda cls, data, options, ctx: data, "Base",
        inherited_option=True,
    )
    registry.register(
        Child, lambda obj, options, ctx: "child",
        lambda cls, data, options, ctx: data, "Child",
    )

    assert registry.serializer_for(Child())[0] == "Child"


def test_registered_mro_base_is_used_for_unregistered_subclass():
    registry = _Registry()

    class Base:
        pass

    class Child(Base):
        pass

    registry.register(
        Base,
        lambda obj, options, ctx: "base",
        lambda cls, data, options, ctx: data,
        "Base",
        inherited_option=True,
    )

    assert registry.serializer_for(Child())[0] == "Base"
    assert registry.serializer_for(Child())[2] == {"inherited_option": True}


def test_virtual_abc_registration_is_used_as_fallback():
    registry = _Registry()

    class IterableObject:
        def __iter__(self):
            return iter(())

    registry.register(
        Iterable,
        lambda obj, options, ctx: "iterable",
        lambda cls, data, options, ctx: data,
        "Iterable",
    )

    assert registry.serializer_for(IterableObject())[0] == "Iterable"


def test_duplicate_class_and_json_name_registration_is_rejected():
    registry = _Registry()

    class First:
        pass

    class Second:
        pass

    serializer = lambda obj, options, ctx: None
    deserializer = lambda cls, data, options, ctx: None
    registry.register(First, serializer, deserializer, "First")

    with pytest.raises(ValueError, match="already registered"):
        registry.register(First, serializer, deserializer, "Other")
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Second, serializer, deserializer, "First")


@pytest.mark.parametrize(
    "value",
    [
        pathlib.Path("a/b"),
        datetime.datetime(2024, 1, 2, 3, 4),
        datetime.date(2024, 1, 2),
        datetime.time(3, 4),
    ],
)
def test_builtin_value_round_trips(value):
    result = deserialize(serialize(value))

    assert type(result) is type(value)
    assert result == value


@pytest.mark.parametrize(
    "value",
    [
        datetime.timedelta(days=999999, microseconds=1),
        datetime.timedelta(days=-999999, microseconds=1),
        datetime.timedelta(microseconds=-1),
    ],
)
def test_timedelta_round_trip_preserves_microseconds(value):
    assert deserialize(serialize(value)) == value


def test_timedelta_deserializer_rejects_legacy_seconds_payload():
    payload = f'{{"{TYPE_KEY}": "timedelta", "{DATA_KEY}": 1.25}}'

    with pytest.raises(TypeError, match="Timedelta data"):
        deserialize(payload)


@pytest.mark.parametrize("value", [b"", b"\x00\xff\x80binary", b"utf-8 \xe2\x98\x83"])
def test_bytes_round_trip(value):
    result = deserialize(serialize(value))

    assert result == value


def test_string_regex_pattern_and_flags_round_trip():
    value = re.compile("a", re.IGNORECASE | re.MULTILINE)

    result = deserialize(serialize(value))

    assert result.pattern == value.pattern
    assert result.flags == value.flags


def test_bytes_regex_pattern_and_flags_round_trip():
    value = re.compile(b"a\\xff", re.IGNORECASE)

    result = deserialize(serialize(value))

    assert result.pattern == value.pattern
    assert result.flags == value.flags


@pytest.mark.parametrize(
    "value",
    [
        (1, "two", 3.0),
        {1, 2, 3},
        frozenset({"one", "two"}),
    ],
)
def test_container_value_round_trips(value):
    result = deserialize(serialize(value))

    assert type(result) is type(value)
    assert result == value


def test_frozen_dataclass_round_trips():
    @serializable("SerializeTestFrozenDataclass")
    @dataclass(frozen=True)
    class TestFrozenDataclass:
        value: int
        label: str

    value = TestFrozenDataclass(42, "answer")
    result = deserialize(serialize(value))

    assert result == value
    assert type(result) is TestFrozenDataclass
    with pytest.raises(FrozenInstanceError):
        result.value = 0


def test_dataclass_with_init_false_field_round_trips():
    @serializable("SerializeTestDataclassInitFalse")
    @dataclass
    class TestDataclass:
        value: int
        cache: int = field(init=False, default=0)

    value = TestDataclass(42)
    value.cache = 84

    result = deserialize(serialize(value))

    assert result == value
    assert result.cache == 84


def test_frozen_slotted_dataclass_with_init_false_field_round_trips():
    @serializable("SerializeTestFrozenSlottedDataclassInitFalse")
    @dataclass(frozen=True, slots=True)
    class TestDataclass:
        value: int
        cache: int = field(init=False, default=0)

        def __post_init__(self):
            object.__setattr__(self, "cache", self.value * 2)

    value = TestDataclass(42)
    object.__setattr__(value, "cache", 84)

    result = deserialize(serialize(value))

    assert result == value
    assert result.cache == 84


def test_dataclass_deserializer_ignores_unknown_fields():
    @serializable("SerializeTestDataclassUnknownField")
    @dataclass
    class TestDataclass:
        value: int

    payload = (
        f'{{"{TYPE_KEY}": "SerializeTestDataclassUnknownField", '
        f'"{DATA_KEY}": {{"value": 42, "legacy": "ignored"}}}}'
    )

    result = deserialize(payload)

    assert result == TestDataclass(42)


def test_int_enum_round_trips_when_registered():
    @serializable("SerializeTestIntEnum")
    class TestIntEnum(enum.IntEnum):
        ONE = 1

    result = deserialize(serialize(TestIntEnum.ONE))

    assert result is TestIntEnum.ONE


def test_string_enum_round_trips_when_registered():
    @serializable("SerializeTestStringEnum")
    class TestStringEnum(str, enum.Enum):
        RED = "red"

    result = deserialize(serialize(TestStringEnum.RED))

    assert result is TestStringEnum.RED


def test_regex_flag_round_trips():
    result = deserialize(serialize(re.RegexFlag.IGNORECASE))

    assert result is re.RegexFlag.IGNORECASE


def test_nested_registered_values_round_trip():
    @serializable("SerializeTestNested")
    class TestNested:
        def __init__(self, value=0):
            self.value = value

    value = {
        "items": [
            TestNested(1),
            pathlib.Path("nested"),
            re.RegexFlag.MULTILINE,
        ]
    }

    result = deserialize(serialize(value))

    assert isinstance(result["items"][0], TestNested)
    assert result["items"][0].value == 1
    assert result["items"][1] == pathlib.Path("nested")
    assert result["items"][2] is re.RegexFlag.MULTILINE


def test_none_data_round_trips():
    @serializable("SerializeTestNone")
    class TestNone:
        def _serialize(self, options, ctx):
            return None

        @classmethod
        def _deserialize(cls, data, options, ctx):
            assert data is None
            return cls

    assert deserialize(serialize(TestNone())) is TestNone


def test_reserved_metadata_requires_data_for_known_type():
    @serializable("SerializeTestMissingData")
    class TestMissingData:
        pass

    payload = f'{{"{TYPE_KEY}": "SerializeTestMissingData"}}'

    with pytest.raises(TypeError, match=DATA_KEY):
        deserialize(payload)


def test_unknown_serialized_type_is_rejected():
    payload = f'{{"{TYPE_KEY}": "Unknown", "{DATA_KEY}": {{}}}}'

    with pytest.raises(TypeError, match="No deserializer"):
        deserialize(payload)


def test_circular_container_is_rejected():
    value = []
    value.append(value)

    with pytest.raises(ValueError, match="Circular reference"):
        serialize(value)


def test_registered_objects_cannot_be_dictionary_keys():
    @serializable("SerializeTestKey")
    class TestKey:
        pass

    with pytest.raises(TypeError, match="dictionary keys"):
        serialize({TestKey(): "value"})
