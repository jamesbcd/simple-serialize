import collections
import datetime
import decimal
from fractions import Fraction
import ipaddress
import pathlib
import re
import uuid
from typing import cast
from zoneinfo import ZoneInfo

from ._datetime_types import (
    isoformat_deserializer,
    isoformat_serializer,
    timedelta_deserializer,
    timedelta_serializer,
    timezone_deserializer,
    timezone_serializer,
    zoneinfo_deserializer,
    zoneinfo_serializer,
)
from ._registry import Deserializer, Serializer, _Registry
from ._scalar_types import (
    bytearray_deserializer,
    bytearray_serializer,
    bytes_deserializer,
    bytes_serializer,
    complex_deserializer,
    complex_serializer,
    decimal_deserializer,
    decimal_serializer,
    fraction_deserializer,
    fraction_serializer,
    memoryview_deserializer,
    memoryview_serializer,
    range_deserializer,
    range_serializer,
    slice_deserializer,
    slice_serializer,
    uuid_deserializer,
    uuid_serializer,
)
from ._stdlib_types import (
    counter_deserializer,
    counter_serializer,
    deque_deserializer,
    deque_serializer,
    enum_deserializer,
    enum_serializer,
    ipaddress_deserializer,
    ipaddress_serializer,
    ordered_dict_deserializer,
    ordered_dict_serializer,
    path_deserializer,
    path_serializer,
    regex_deserializer,
    regex_serializer,
)
from ._collections import iterable_deserializer, iterable_serializer


def install_builtins(registry: _Registry) -> None:
    registry.register(tuple, iterable_serializer, iterable_deserializer)

    registry.register(set, iterable_serializer, iterable_deserializer)

    registry.register(frozenset, iterable_serializer, iterable_deserializer)

    registry.register(range, range_serializer, range_deserializer)

    registry.register(slice, slice_serializer, slice_deserializer)

    registry.register(complex, complex_serializer, complex_deserializer)

    registry.register(bytes, bytes_serializer, bytes_deserializer)

    registry.register(bytearray, bytearray_serializer, bytearray_deserializer)

    registry.register(memoryview, memoryview_serializer, memoryview_deserializer)

    registry.register(pathlib.Path, path_serializer, path_deserializer)

    registry.register(datetime.datetime, cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))

    registry.register(datetime.date,     cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))

    registry.register(datetime.time,     cast(Serializer, isoformat_serializer), cast(Deserializer, isoformat_deserializer))

    registry.register(datetime.timedelta, timedelta_serializer, timedelta_deserializer)

    registry.register(datetime.timezone, timezone_serializer, timezone_deserializer)

    registry.register(ZoneInfo, zoneinfo_serializer, zoneinfo_deserializer)

    registry.register(re.Pattern, regex_serializer, regex_deserializer)

    registry.register(re.RegexFlag, enum_serializer, enum_deserializer)

    registry.register(decimal.Decimal, decimal_serializer, decimal_deserializer)

    registry.register(uuid.UUID, uuid_serializer, uuid_deserializer)

    registry.register(Fraction, fraction_serializer, fraction_deserializer)

    for _ip_type in (
        ipaddress.IPv4Address,
        ipaddress.IPv6Address,
        ipaddress.IPv4Network,
        ipaddress.IPv6Network,
        ipaddress.IPv4Interface,
        ipaddress.IPv6Interface,
    ):
        registry.register(_ip_type, ipaddress_serializer, ipaddress_deserializer)

    registry.register(collections.Counter, counter_serializer, counter_deserializer)

    registry.register(collections.OrderedDict, ordered_dict_serializer, ordered_dict_deserializer)

    registry.register(collections.deque, deque_serializer, deque_deserializer)
