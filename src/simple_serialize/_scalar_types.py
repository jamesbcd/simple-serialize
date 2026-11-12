import base64
import decimal
from fractions import Fraction
import uuid
from typing import cast


def range_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, int]:
    '''Encode a range using its start, stop, and step values.'''
    obj = cast(range, obj)
    return {"start": obj.start, "stop": obj.stop, "step": obj.step}


def range_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> range:
    '''Reconstruct a range from its start, stop, and step values.'''
    data = cast(dict, data)
    values = (data.get("start"), data.get("stop"), data.get("step"))
    if not all(type(value) is int for value in values):
        raise TypeError("Range data must contain integer start, stop, and step values")
    return range(*values)


def slice_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, object]:
    '''Encode a slice using its start, stop, and step values.'''
    obj = cast(slice, obj)
    return {"start": obj.start, "stop": obj.stop, "step": obj.step}


def slice_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> slice:
    '''Reconstruct a slice from its start, stop, and step values.'''
    data = cast(dict, data)
    if not all(key in data for key in ("start", "stop", "step")):
        raise TypeError("Slice data must contain start, stop, and step values")
    return slice(data["start"], data["stop"], data["step"])


def complex_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, float]:
    '''Encode a complex number using its real and imaginary components.'''
    obj = cast(complex, obj)
    return {"real": obj.real, "imag": obj.imag}


def complex_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> complex:
    '''Reconstruct a complex number from its real and imaginary components.'''
    data = cast(dict, data)
    real = data.get("real")
    imag = data.get("imag")
    if (
        not isinstance(real, (int, float))
        or isinstance(real, bool)
        or not isinstance(imag, (int, float))
        or isinstance(imag, bool)
    ):
        raise TypeError("Complex data must contain numeric real and imag values")
    return complex(real, imag)


def bytes_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
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


def bytes_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> bytes:
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


def bytearray_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict:
    '''Encode a bytearray using the bytes base64 representation.'''
    return bytes_serializer(bytes(cast(bytearray, obj)), options, ctx)


def bytearray_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> bytearray:
    '''Reconstruct a bytearray from the bytes base64 representation.'''
    return bytearray(bytes_deserializer(bytes, data, options, ctx))


def memoryview_serializer(obj: object, options: dict[str, object], ctx: object | None) -> dict[str, object]:
    '''Encode a contiguous memoryview's contents, format, shape, and access mode.'''
    view = cast(memoryview, obj)
    if not view.contiguous:
        raise TypeError("Only contiguous memoryviews can be serialized")
    raw = view.tobytes(order="C")
    try:
        memoryview(raw).cast(view.format, shape=list(view.shape))
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Memoryview format {view.format!r} cannot be reconstructed"
        ) from exc
    return {
        "data": bytes_serializer(raw, options, ctx),
        "format": view.format,
        "shape": list(view.shape),
        "readonly": view.readonly,
    }


def memoryview_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> memoryview:
    '''Reconstruct a contiguous memoryview from its contents and metadata.'''
    data = cast(dict, data)
    format = data.get("format")
    shape = data.get("shape")
    readonly = data.get("readonly")
    if (
        not isinstance(format, str)
        or not isinstance(shape, list)
        or not all(type(dimension) is int and dimension >= 0 for dimension in shape)
        or not isinstance(readonly, bool)
        or "data" not in data
    ):
        raise TypeError("Memoryview data must contain format, shape, readonly, and data values")
    raw = bytes_deserializer(bytes, data["data"], options, ctx)
    buffer = raw if readonly else bytearray(raw)
    return memoryview(buffer).cast(format, shape=shape)


def decimal_serializer(obj: object, options: dict[str, object], ctx: object | None) -> str:
    '''Encode a Decimal as text to preserve its exact value and exponent.'''
    return str(cast(decimal.Decimal, obj))


def decimal_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> decimal.Decimal:
    '''Reconstruct a Decimal from its exact text representation.'''
    if not isinstance(data, str):
        raise TypeError("Decimal data must be a string")
    return decimal.Decimal(data)


def uuid_serializer(obj: object, options: dict[str, object], ctx: object | None) -> str:
    '''Encode a UUID using its canonical hyphenated string representation.'''
    return str(cast(uuid.UUID, obj))


def uuid_deserializer(cls: type, data: object, options: dict[str, object], ctx: object | None) -> uuid.UUID:
    '''Reconstruct a UUID from its canonical string representation.'''
    if not isinstance(data, str):
        raise TypeError("UUID data must be a string")
    return uuid.UUID(data)


def fraction_serializer(
    obj: object,
    options: dict[str, object],
    ctx: object | None,
) -> dict[str, int]:
    '''Encode a Fraction as its exact normalized numerator and denominator.'''
    value = cast(Fraction, obj)
    return {"numerator": value.numerator, "denominator": value.denominator}


def fraction_deserializer(
    cls: type,
    data: object,
    options: dict[str, object],
    ctx: object | None,
) -> Fraction:
    '''Reconstruct a Fraction from exact integer components.'''
    if not isinstance(data, dict):
        raise TypeError("Fraction data must contain integer numerator and denominator")
    numerator = data.get("numerator")
    denominator = data.get("denominator")
    if type(numerator) is not int or type(denominator) is not int:
        raise TypeError("Fraction data must contain integer numerator and denominator")
    if denominator == 0:
        raise TypeError("Fraction denominator must not be zero")
    return Fraction(numerator, denominator)
