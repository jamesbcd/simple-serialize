import datetime
from typing import cast
from zoneinfo import ZoneInfo


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
